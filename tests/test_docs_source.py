# SPDX-License-Identifier: Apache-2.0
"""Exact-source acquisition and offline projection, using deterministic API fixtures."""
import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from docs_source import (api, PREFIX, REQUIRED_JOBS, WORKFLOW, acquire, fetch_blobs,
                         candidate, projection_identity, source_evidence, verify_evidence)
from test_docs_payload import COMMIT, fixture, pin


def evidence():
    run = {'id': 123, 'run_attempt': 2, 'head_sha': COMMIT, 'head_branch': 'main',
           'event': 'push', 'path': WORKFLOW, 'status': 'completed', 'conclusion': 'failure',
           'repository': {'full_name': 'Living-Proof-Labs/.github'},
           'head_repository': {'full_name': 'Living-Proof-Labs/.github'},
           'html_url': 'https://github.com/Living-Proof-Labs/.github/actions/runs/123'}
    return {'branch': {'name': 'main', 'protected': True, 'commit': {'sha': COMMIT}},
            'comparison': {'status': 'identical', 'base_commit': {'sha': COMMIT},
                           'merge_base_commit': {'sha': COMMIT}},
            'run': run, 'jobs': [
                {'id': i + 10, 'name': name, 'run_id': 123, 'run_attempt': 2,
                 'head_sha': COMMIT, 'status': 'completed', 'conclusion': 'success'}
                for i, name in enumerate(REQUIRED_JOBS)] + [
                    {'name': 'Strict repository settings audit', 'conclusion': 'failure'}]}


def api_fixture(blobs, proof):
    entries, objects = [], {}
    for path, (mode, data) in blobs.items():
        sha = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
        entries.append({'path': path, 'mode': mode, 'type': 'blob', 'size': len(data), 'sha': sha})
        objects[PREFIX + '/git/blobs/' + sha] = {'sha': sha, 'encoding': 'base64',
                                                'content': base64.b64encode(data).decode()}
    objects.update({PREFIX + '/branches/main': proof['branch'],
                    PREFIX + f'/compare/{COMMIT}...{COMMIT}': proof['comparison'],
                    PREFIX + '/actions/runs/123': proof['run'],
                    PREFIX + '/actions/runs/123/attempts/2/jobs?per_page=100': {
                        'total_count': len(proof['jobs']), 'jobs': proof['jobs']},
                    PREFIX + f'/git/trees/{COMMIT}?recursive=1': {'truncated': False, 'tree': entries}})

    def get(path, **kwargs):
        if '/actions/workflows/verify.yml/runs?' in path:
            return {'total_count': 1, 'workflow_runs': [proof['run']]}
        return copy.deepcopy(objects[path])
    return get, objects


class TrustedSource(unittest.TestCase):
    def test_proposal_is_repeatable_and_source_overrides_are_rejected(self):
        _, blobs = fixture()
        get, _ = api_fixture(blobs, evidence())
        self.assertEqual(candidate(COMMIT, get), candidate(COMMIT, get))
        with tempfile.TemporaryDirectory() as directory:
            for name in ['CONTENT_URL', 'CONTENT_MAIN_REF']:
                with mock.patch.dict(os.environ, {name: 'other'}), self.assertRaisesRegex(ValueError, 'overrides'):
                    acquire(pin(blobs), Path(directory) / 'content', get)

    def test_public_request_count_keeps_three_fresh_evidence_reads(self):
        _, blobs = fixture()
        for number in range(10):
            blobs[f'docs/media/fixture-{number}.txt'] = ('100644', f'fixture {number}'.encode())
        original, _ = api_fixture(blobs, evidence())
        calls = []
        def get(path, **kwargs):
            calls.append(path)
            return original(path, **kwargs)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'content'
            lock = pin(blobs)
            acquire(lock, target, get)
            self.assertEqual(len(calls), 20)  # 13 blobs + tree + two three-request checks.
            projection_identity(lock, target)
            source_evidence(COMMIT, get)  # The separate pin check is still fresh.
            self.assertEqual(len(calls), 23)
            self.assertEqual(calls.count(PREFIX + '/branches/main'), 3)
            self.assertEqual(sum('/actions/workflows/' in path for path in calls), 3)
            self.assertEqual(sum('/attempts/' in path for path in calls), 3)
            self.assertFalse(any('/compare/' in path for path in calls))
            self.assertNotIn(PREFIX + '/actions/runs/123', calls)

    def test_older_pin_still_requires_independent_ancestry_response(self):
        _, blobs = fixture()
        proof = evidence()
        proof['branch']['commit']['sha'] = 'b' * 40
        original, objects = api_fixture(blobs, proof)
        path = PREFIX + f'/compare/{COMMIT}...' + 'b' * 40
        calls = []
        objects[path] = dict(proof['comparison'], status='ahead')
        def get(url, **kwargs):
            calls.append(url)
            return original(url, **kwargs)
        source_evidence(COMMIT, get)
        self.assertEqual(len(calls), 4)
        self.assertIn(path, calls)
        objects[path]['status'] = 'diverged'
        with self.assertRaisesRegex(ValueError, 'ancestor'):
            source_evidence(COMMIT, get)

    def test_incomplete_listing_and_rate_limit_fail_closed(self):
        _, blobs = fixture()
        original, _ = api_fixture(blobs, evidence())
        def incomplete(path, **kwargs):
            if '/actions/workflows/' in path:
                return {'total_count': 1, 'workflow_runs': [{'id': 123}]}
            return original(path, **kwargs)
        with self.assertRaises(ValueError):
            source_evidence(COMMIT, incomplete)
        from urllib.error import HTTPError
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'content'
            get = mock.Mock(side_effect=HTTPError('https://api.github.com/', 403,
                                                 'rate limit', {}, None))
            with self.assertRaises(HTTPError):
                acquire(pin(blobs), target, get)
            self.assertFalse(target.exists())
            self.assertEqual(get.call_count, 1)

    def test_docs_success_is_independent_of_red_audit_and_aggregate(self):
        result = verify_evidence(COMMIT, evidence())
        self.assertEqual(result['run_id'], 123)
        self.assertEqual(result['run_attempt'], 2)

    def test_wrong_source_ref_run_attempt_or_job_is_rejected(self):
        cases = [('run', 'event', 'pull_request'), ('run', 'head_branch', 'topic'),
                 ('run', 'head_sha', 'b' * 40), ('run', 'path', '.github/workflows/other.yml'),
                 ('run', 'status', 'in_progress'), ('run', 'run_attempt', 3),
                 ('run', 'repository', {'full_name': 'other/source'}),
                 ('run', 'head_repository', {'full_name': 'fork/.github'}),
                 ('run', 'html_url', 'https://example.org'), ('branch', 'protected', False),
                 ('comparison', 'status', 'diverged'),
                 ('comparison', 'merge_base_commit', {'sha': 'b' * 40})]
        for section, key, value in cases:
            proof = evidence()
            proof[section][key] = value
            with self.subTest(section=section, key=key), self.assertRaises(ValueError):
                verify_evidence(COMMIT, proof)
        for field, value in [('conclusion', 'skipped'), ('conclusion', 'failure'),
                             ('run_id', 99), ('head_sha', 'b' * 40), ('run_attempt', 1)]:
            proof = evidence()
            proof['jobs'][0][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                verify_evidence(COMMIT, proof)
        for jobs in [[], evidence()['jobs'][1:], evidence()['jobs'] + [evidence()['jobs'][0]]]:
            with self.subTest(jobs=jobs), self.assertRaises(ValueError):
                verify_evidence(COMMIT, dict(evidence(), jobs=jobs))

    def test_newer_failed_run_cannot_fall_back_to_older_success(self):
        _, blobs = fixture()
        original, _ = api_fixture(blobs, evidence())
        def get(path, **kwargs):
            if '/actions/workflows/' in path:
                return {'total_count': 2, 'workflow_runs': [evidence()['run'],
                        dict(evidence()['run'], id=124, status='in_progress')]}
            if path.endswith('/actions/runs/124'):
                return dict(evidence()['run'], id=124, status='in_progress')
            if '/runs/124/attempts/' in path:
                return {'total_count': 0, 'jobs': []}
            return original(path, **kwargs)
        with self.assertRaises(ValueError):
            source_evidence(COMMIT, get)

    def test_projection_contains_only_selected_data_and_rechecks_every_byte(self):
        _, blobs = fixture()
        lock = pin(blobs)
        upstream = dict(blobs, **{'.github/workflows/verify.yml': ('100644', b'not staged'),
                                 'config/github/repository-policy.json': ('100644', b'not staged')})
        get, _ = api_fixture(upstream, evidence())
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'content'
            with mock.patch.dict(os.environ, {}, clear=True):
                acquire(lock, target, get)
            identity = projection_identity(lock, target)
            self.assertEqual(identity['source_checks']['run_attempt'], 2)
            self.assertFalse((target / '.github').exists())
            self.assertFalse((target / 'config').exists())
            with self.assertRaisesRegex(ValueError, 'already exists'):
                acquire(lock, target, get)
            (target / 'docs/index.md').write_text('# Tampered\n')
            with self.assertRaisesRegex(ValueError, 'digest mismatch'):
                projection_identity(lock, target)

    def test_unsafe_tree_or_blob_fails_before_staging(self):
        _, blobs = fixture()
        get, objects = api_fixture(blobs, evidence())
        tree = objects[PREFIX + f'/git/trees/{COMMIT}?recursive=1']
        tree['truncated'] = True
        with self.assertRaises(ValueError):
            fetch_blobs(COMMIT, get)
        tree['truncated'] = False
        entry = tree['tree'][0]
        entry['mode'] = '120000'
        with self.assertRaises(ValueError):
            fetch_blobs(COMMIT, get)
        entry['mode'] = '100644'
        objects[PREFIX + '/git/blobs/' + entry['sha']]['content'] = base64.b64encode(b'wrong').decode()
        with self.assertRaises(ValueError):
            fetch_blobs(COMMIT, get)

    def test_receipt_and_link_substitution_fail(self):
        _, blobs = fixture()
        get, _ = api_fixture(blobs, evidence())
        lock = pin(blobs)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'content'
            acquire(lock, target, get)
            receipt = target / '.docs-provenance.json'
            saved = receipt.read_bytes()
            changed = json.loads(saved)
            changed['evidence']['jobs'][0]['conclusion'] = 'failure'
            receipt.write_text(json.dumps(changed))
            with self.assertRaises(ValueError):
                projection_identity(lock, target)
            receipt.write_bytes(saved)
            (target / 'docs/index.md').unlink()
            (target / 'docs/index.md').symlink_to(receipt)
            with self.assertRaisesRegex(ValueError, 'linked'):
                projection_identity(lock, target)

    def test_changing_source_attempt_leaves_no_projection(self):
        _, blobs = fixture()
        get, _ = api_fixture(blobs, evidence())
        proof = evidence()
        changed = copy.deepcopy(proof)
        changed['run']['run_attempt'] = 3
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'content'
            with mock.patch('docs_source.source_evidence', side_effect=[proof, changed]):
                with self.assertRaisesRegex(ValueError, 'changed during acquisition'):
                    acquire(pin(blobs), target, get)
            self.assertFalse(target.exists())


if __name__ == '__main__':
    unittest.main()


class AnonymousTransport(unittest.TestCase):
    def test_publisher_token_is_never_forwarded(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'{"public": true}'
        opener = mock.Mock()
        opener.open.return_value = response
        with mock.patch.dict(os.environ, {'GITHUB_TOKEN': 'ordinary-test-placeholder'}), \
                mock.patch('docs_source.build_opener', return_value=opener):
            self.assertEqual(api(PREFIX + '/actions/runs/123'), {'public': True})
        request = opener.open.call_args.args[0]
        self.assertIsNone(request.get_header('Authorization'))
        self.assertEqual(request.full_url,
                         'https://api.github.com/repos/Living-Proof-Labs/.github/actions/runs/123')
