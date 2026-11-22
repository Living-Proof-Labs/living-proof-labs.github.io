# SPDX-License-Identifier: Apache-2.0
"""Exact-source acquisition and offline projection, using deterministic API fixtures."""
import base64
import copy
from email.message import EmailMessage
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
from urllib.request import HTTPSHandler, build_opener
from urllib.response import addinfourl

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import docs_source
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

    def test_docs_payload_advances_when_unrelated_settings_audit_failed(self):
        _, blobs = fixture()
        proof = evidence()
        self.assertEqual(proof['run']['conclusion'], 'failure')
        audit = next(job for job in proof['jobs'] if job['name'] == 'Strict repository settings audit')
        self.assertEqual(audit['conclusion'], 'failure')
        upstream = dict(blobs, **{
            '.github/workflows/verify.yml': ('100644', b'name: Verify\n'),
            '.github/workflows/apply-repository-settings.yml': ('100644', b'name: Apply settings\n'),
            'config/github/repository-policy.json': ('100644', b'{"rules": true}\n'),
        })
        get, _ = api_fixture(upstream, proof)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'content'
            acquire(pin(blobs), target, get)
            self.assertTrue((target / 'docs/index.md').is_file())
            self.assertFalse((target / '.github').exists())
            self.assertFalse((target / 'config').exists())
            self.assertEqual(projection_identity(pin(blobs), target)['source_checks']['jobs'][0]['name'],
                             REQUIRED_JOBS[0])

    def test_settings_and_mixed_releases_cannot_skip_the_docs_gate(self):
        _, blobs = fixture()
        proof = evidence()
        proof['jobs'][0]['conclusion'] = 'failure'
        proof['jobs'][-1]['conclusion'] = 'success'
        get, _ = api_fixture(blobs, proof)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'content'
            with self.assertRaises(ValueError):
                acquire(pin(blobs), target, get)
            self.assertFalse(target.exists())
        for path in ('.github/workflows/apply-repository-settings.yml',
                     'config/github/repository-policy.json'):
            blocked = evidence()
            blocked['run']['path'] = path
            with self.subTest(path=path), self.assertRaises(ValueError):
                verify_evidence(COMMIT, blocked)
        dispatched = evidence()
        dispatched['run']['event'] = 'workflow_dispatch'
        with self.assertRaises(ValueError):
            verify_evidence(COMMIT, dispatched)


TOKEN = 'ordinary-test-placeholder'
PAT = 'pat-must-not-leak'
SOURCE_API = 'https://api.github.com/repos/Living-Proof-Labs/.github/'


def credential_environment(**values):
    """Isolate the test from ambient publisher, app, and personal tokens."""
    blocked = ('GITHUB_TOKEN', 'GH_TOKEN', 'DOCS_SOURCE_TOKEN', 'CONTENT_URL', 'CONTENT_MAIN_REF')
    environment = {key: value for key, value in os.environ.items() if key not in blocked}
    environment.update(values)
    return environment


def capture_request(path, **environment):
    response = mock.MagicMock()
    response.__enter__.return_value.read.return_value = b'{"public": true}'
    response.__enter__.return_value.geturl.return_value = 'https://api.github.com/' + path.split('#', 1)[0]
    opener = mock.Mock()
    opener.open.return_value = response
    error = None
    with mock.patch.dict(os.environ, credential_environment(**environment), clear=True), \
            mock.patch('docs_source.build_opener', return_value=opener):
        try:
            api(path)
        except ValueError as caught:
            error = caught
    request = opener.open.call_args.args[0] if opener.open.called else None
    return error, request


class SourceCredential(unittest.TestCase):
    """The workflow github.token authenticates one repository API and no other destination."""

    def test_token_is_attached_for_source_repository_api(self):
        cases = [
            PREFIX + '/branches/main',
            PREFIX + '/actions/runs/123',
            PREFIX + '/actions/workflows/verify.yml/runs?head_sha=' + COMMIT
            + '&event=push&branch=main&per_page=100',
            PREFIX + f'/compare/{COMMIT}...{COMMIT}',
            PREFIX + f'/git/trees/{COMMIT}?recursive=1',
            PREFIX + '/git/blobs/' + COMMIT,
        ]
        for path in cases:
            for name, environment in (
                    ('workflow', {'DOCS_SOURCE_TOKEN': TOKEN, 'GITHUB_TOKEN': 'other-workflow-token',
                                  'GH_TOKEN': PAT}),
                    ('actions', {'GITHUB_TOKEN': TOKEN, 'GH_TOKEN': PAT})):
                with self.subTest(path=path, credential=name):
                    error, request = capture_request(
                        path, CONTENT_URL='https://evil.example/other.git', **environment)
                    self.assertIsNone(error)
                    self.assertEqual(request.get_header('Authorization'), 'Bearer ' + TOKEN)
                    self.assertTrue(request.full_url.startswith(SOURCE_API))
                    self.assertNotIn(TOKEN, request.full_url)
                    self.assertNotIn(PAT, request.full_url)
                    self.assertNotIn('evil.example', request.full_url)
                    self.assertNotIn('other-workflow-token', request.header_items().__repr__())

    def test_personal_token_and_absent_token_are_not_attached(self):
        error, request = capture_request(PREFIX + '/branches/main', GH_TOKEN=PAT)
        self.assertIsNone(error)
        self.assertIsNone(request.get_header('Authorization'))
        self.assertNotIn(PAT, request.full_url)
        error, request = capture_request(PREFIX + '/branches/main')
        self.assertIsNone(error)
        self.assertIsNone(request.get_header('Authorization'))

    def test_token_is_not_attached_for_other_repos_hosts_or_config_urls(self):
        paths = [
            'repos/Living-Proof-Labs/living-proof-labs.github.io/contents/README.md',
            'repos/OtherOrg/.github/branches/main',
            'repos/Living-Proof-Labs/.github.evil/branches/main',
            PREFIX + '/../../repos/Other/secret',
            PREFIX + '/../../../repos/Other/secret',
            PREFIX + '/%2e%2e/%2e%2e/repos/Other/secret',
            PREFIX + '/%2E%2E/branches/main',
            PREFIX + '/branches/main\r\nHost: evil.example',
            PREFIX + '/@evil.example/branches/main',
            PREFIX + '/branches/main\\@evil.example',
            'https://evil.example/repos/Living-Proof-Labs/.github/branches/main',
            'https://api.github.com/repos/Other/secret',
            '//evil.example/repos/Living-Proof-Labs/.github/branches/main',
            '//api.github.com/repos/Living-Proof-Labs/.github/branches/main',
            PREFIX + '/branches/main#https://evil.example/steal',
            'repos/Living-Proof-Labs/.github',
        ]
        for path in paths:
            with self.subTest(path=path):
                error, request = capture_request(
                    path, DOCS_SOURCE_TOKEN=TOKEN,
                    CONTENT_URL='https://github.com/Other/secret.git')
                self.assertIsNotNone(error)
                self.assertIsNone(request)

    def test_redirect_target_does_not_receive_the_token(self):
        seen = []

        class Record(HTTPSHandler):
            def https_open(self, req):
                seen.append((req.full_url, req.get_header('Authorization')))
                headers = EmailMessage()
                headers['Location'] = 'https://api.github.com/repos/Other/secret'
                response = addinfourl(io.BytesIO(b''), headers, req.full_url, 302)
                response.msg = 'Found'
                return response

        def opener(*handlers):
            return build_opener(*handlers, Record)

        environment = credential_environment(DOCS_SOURCE_TOKEN=TOKEN, GH_TOKEN=PAT)
        for key in ('http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'all_proxy'):
            environment.pop(key, None)
        with mock.patch.dict(os.environ, environment, clear=True), \
                mock.patch('docs_source.build_opener', side_effect=opener), \
                self.assertRaisesRegex(ValueError, 'redirect refused'):
            api(PREFIX + '/branches/main')
        self.assertEqual(seen, [(SOURCE_API + 'branches/main', 'Bearer ' + TOKEN)])
        self.assertFalse(any(url.startswith('https://api.github.com/repos/Other/') for url, _ in seen))
        self.assertFalse(any(header and 'Other/secret' in url for url, header in seen))

    def test_workflow_supplies_github_token_only_on_source_acquisition(self):
        workflow = (Path(__file__).resolve().parents[1] / '.github/workflows/docs.yml').read_text()
        section = workflow.split('Acquire and verify the reviewed content source', 1)[1]
        section = section.split('\n      - name:', 1)[0]
        self.assertIn('DOCS_SOURCE_TOKEN: ${{ github.token }}', section)
        self.assertNotIn('GH_TOKEN', section)
        self.assertNotIn('GITHUB_TOKEN', section)
        self.assertNotIn('permissions:', section)

    def test_contract_explains_why_the_authenticated_read_is_safe(self):
        source = Path(docs_source.__file__).read_text()
        draft = (Path(__file__).resolve().parents[1] / 'docs/docs-only-support-draft.md').read_text()
        for text in (source, draft):
            self.assertIn(SOURCE_API, text)
            self.assertIn('contents: read', text)
            self.assertNotIn('never forward the publisher', text)
            self.assertNotIn('Publisher credentials are never sent.', text)
        self.assertIn('DOCS_SOURCE_TOKEN', draft)
        self.assertIn('redirect', draft.lower())


if __name__ == '__main__':
    unittest.main()
