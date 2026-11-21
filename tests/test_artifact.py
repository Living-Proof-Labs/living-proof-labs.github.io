# SPDX-License-Identifier: Apache-2.0
"""Artifact identity and actual deployment-freshness script regression checks."""
import copy
import json
import os
from pathlib import Path
import subprocess
import shutil
import tarfile
import sys
import tempfile
import unittest
import zipfile

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from check_artifact import artifact, check_identity
from docs_source import projection_identity, acquire
from test_docs_payload import fixture, pin
from test_docs_source import api_fixture, evidence

SHA = 'c' * 40
RUN = '456'
LEGACY = {'repository': 'Living-Proof-Labs/.github', 'tag': 'v1.1.3', 'commit': 'd' * 40}


def identity(content):
    return {'source_commit': SHA, 'source_dirty': False, 'workflow_run': RUN, 'workflow_attempt': '1',
            'publisher': {'repository': 'Living-Proof-Labs/living-proof-labs.github.io',
                          'commit': SHA, 'dirty': False}, 'content': content}


def legacy_identity():
    return identity(dict(LEGACY, locked_commit=LEGACY['commit'], locked_tag=LEGACY['tag'],
                         pinned=True, dirty=False))


class ArtifactIdentity(unittest.TestCase):
    def test_legacy_roundtrip_and_tampering(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'site').mkdir()
            (root / 'site/index.html').write_text('reviewed site')
            (root / 'site/build.json').write_text(json.dumps(legacy_identity()))
            artifact('seal', root, LEGACY, SHA, RUN)
            artifact('check', root, LEGACY, SHA, RUN)
            (root / 'site/index.html').write_text('different site')
            with self.assertRaisesRegex(ValueError, 'manifest/bytes mismatch'):
                artifact('check', root, LEGACY, SHA, RUN)

    def test_scoped_transport_preserves_nojekyll_and_exact_seal(self):
        workflow = yaml.safe_load((ROOT / '.github/workflows/docs.yml').read_text())
        upload = next(s for s in workflow['jobs']['build']['steps']
                      if s.get('with', {}).get('name') == 'root-documentation-review')['with']
        self.assertTrue(upload['include-hidden-files'])
        self.assertEqual(upload['path'].splitlines(),
                         ['artifacts/site/', 'artifacts/site-manifest.json',
                          'artifacts/content-provenance.json'])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'artifacts'
            (root / 'site').mkdir(parents=True)
            (root / 'site/index.html').write_text('ordinary site')
            (root / 'site/build.json').write_text(json.dumps(legacy_identity()))
            (root / 'site/.nojekyll').write_bytes(b'')
            (root / 'unrelated.txt').write_text('not transported')
            artifact('seal', root, LEGACY, SHA, RUN)
            selected = [f for f in (root / 'site').rglob('*') if f.is_file()]
            selected.append(root / 'site-manifest.json')
            archive = Path(tmp) / 'transport.zip'
            with zipfile.ZipFile(archive, 'w') as bundle:
                for f in selected:
                    bundle.write(f, f.relative_to(root).as_posix())
            restored = Path(tmp) / 'verified'
            with zipfile.ZipFile(archive) as bundle:
                bundle.extractall(restored)  # Only the ordinary files created above.
            self.assertEqual({str(f.relative_to(root)): f.read_bytes() for f in selected},
                             {str(f.relative_to(restored)): f.read_bytes()
                              for f in restored.rglob('*') if f.is_file()})
            self.assertFalse((restored / 'unrelated.txt').exists())
            artifact('check', restored, LEGACY, SHA, RUN)
            validator = Path(tmp) / 'publisher-check'
            shutil.copytree(ROOT / 'tools', validator / 'tools')
            (validator / 'content.lock.json').write_text(json.dumps(LEGACY))
            package = workflow['jobs']['verify-transport']['steps'][-1]['run']
            env = dict(os.environ, PUBLISHER_SHA=SHA, GITHUB_SHA=SHA,
                       GITHUB_RUN_ID=RUN, GITHUB_RUN_ATTEMPT='1', RUNNER_TEMP=tmp)
            subprocess.run(['bash', '-eu', '-c', package], cwd=tmp, env=env,
                           capture_output=True, text=True, check=True)
            with tarfile.open(Path(tmp) / 'artifact.tar') as bundle:
                files = {m.name.removeprefix('./'): bundle.extractfile(m).read()
                         for m in bundle.getmembers() if m.isfile()}
            self.assertEqual(files, {str(f.relative_to(restored / 'site')): f.read_bytes()
                                     for f in (restored / 'site').rglob('*') if f.is_file()})
            (restored / 'site/.nojekyll').unlink()
            with self.assertRaisesRegex(ValueError, 'manifest/bytes mismatch'):
                artifact('check', restored, LEGACY, SHA, RUN)
            (root / 'site/.private').write_text('not approved')
            with self.assertRaisesRegex(ValueError, 'hidden'):
                artifact('seal', root, LEGACY, SHA, RUN)

    def test_docs_identity_is_bound_to_lock_source_publisher_and_run(self):
        _, blobs = fixture()
        lock = pin(blobs)
        get, _ = api_fixture(blobs, evidence())
        with tempfile.TemporaryDirectory() as tmp:
            acquire(lock, Path(tmp) / 'content', get)
            content = projection_identity(lock, Path(tmp) / 'content')
        value = identity(content)
        check_identity(value, lock, SHA, RUN)
        with self.assertRaisesRegex(ValueError, 'run/attempt'):
            check_identity(value, lock, SHA, RUN, '2')
        cases = [(dict(lock, manifest_sha256='0' * 64), SHA, RUN),
                 (dict(lock, commit='b' * 40), SHA, RUN), (lock, 'e' * 40, RUN),
                 (lock, SHA, '457'), (LEGACY, SHA, RUN)]
        for reviewed, publisher, run in cases:
            with self.subTest(lock=reviewed, publisher=publisher, run=run), self.assertRaises(ValueError):
                check_identity(value, reviewed, publisher, run)
        for field, replacement in [('source_checks', {}), ('manifest', {}), ('dirty', True),
                                   ('repository', 'other/.github'), ('pinned', False)]:
            mutated = copy.deepcopy(value)
            mutated['content'][field] = replacement
            with self.subTest(field=field), self.assertRaises(ValueError):
                check_identity(mutated, lock, SHA, RUN)

    def test_docs_artifact_requires_the_matching_acquisition_receipt(self):
        _, blobs = fixture()
        lock = pin(blobs)
        get, _ = api_fixture(blobs, evidence())
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            acquire(lock, root / 'content', get)
            content = projection_identity(lock, root / 'content')
            (root / 'site').mkdir()
            (root / 'site/index.html').write_text('docs site')
            (root / 'site/build.json').write_text(json.dumps(identity(content)))
            with self.assertRaisesRegex(ValueError, 'missing or linked content provenance'):
                artifact('seal', root, lock, SHA, RUN)
            receipt = root / 'content-provenance.json'
            receipt.write_bytes((root / 'content/.docs-provenance.json').read_bytes())
            artifact('seal', root, lock, SHA, RUN)
            artifact('check', root, lock, SHA, RUN)
            mutated = json.loads(receipt.read_text())
            mutated['evidence']['jobs'][0]['conclusion'] = 'failure'
            receipt.write_text(json.dumps(mutated))
            with self.assertRaises(ValueError):
                artifact('check', root, lock, SHA, RUN)

    def test_missing_manifest_extra_files_and_links_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'site').mkdir()
            (root / 'site/index.html').write_text('site')
            (root / 'site/build.json').write_text(json.dumps(legacy_identity()))
            with self.assertRaisesRegex(ValueError, 'missing artifact manifest'):
                artifact('check', root, LEGACY, SHA, RUN)
            artifact('seal', root, LEGACY, SHA, RUN)
            added = root / 'site/extra.html'
            added.write_text('unexpected')
            with self.assertRaises(ValueError):
                artifact('check', root, LEGACY, SHA, RUN)
            added.unlink()
            added.symlink_to(root / 'site/index.html')
            with self.assertRaisesRegex(ValueError, 'symlink'):
                artifact('check', root, LEGACY, SHA, RUN)
            added.unlink()
            os.link(root / 'site/index.html', added)
            with self.assertRaisesRegex(ValueError, 'hard link'):
                artifact('check', root, LEGACY, SHA, RUN)


class DeployWorkflow(unittest.TestCase):
    def setUp(self):
        self.workflow = yaml.safe_load((ROOT / '.github/workflows/docs.yml').read_text())

    def test_actual_freshness_script_rejects_stale_and_missing_remote(self):
        steps = self.workflow['jobs']['deploy']['steps']
        script = next(step['run'] for step in steps if step.get('id') == 'freshness')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            git = root / 'git'
            git.write_text('#!/bin/sh\nprintf "%s" "$TEST_REMOTE"\n')
            git.chmod(0o755)
            for remote, expected in [(SHA + '\trefs/heads/main\n', 'current=true'),
                                     ('f' * 40 + '\trefs/heads/main\n', 'current=false'),
                                     ('', None), ('not-a-sha\trefs/heads/main\n', None)]:
                output = root / 'output'
                output.write_text('')
                env = dict(os.environ, PATH=str(root) + ':' + os.environ['PATH'], TEST_REMOTE=remote,
                           GITHUB_REPOSITORY='Living-Proof-Labs/living-proof-labs.github.io',
                           GITHUB_SHA=SHA, GITHUB_OUTPUT=str(output), GITHUB_STEP_SUMMARY=str(root / 'summary'))
                result = subprocess.run(['bash', '-c', script], env=env, capture_output=True, text=True)
                if expected is None:
                    self.assertNotEqual(result.returncode, 0)
                else:
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn(expected, output.read_text())

    def test_deploy_validator_comes_from_exact_publisher_not_content_or_artifact(self):
        steps = self.workflow['jobs']['deploy']['steps']
        proof = self.workflow['jobs']['verify-transport']
        self.assertEqual(proof['needs'], 'build')
        self.assertIn("github.event_name == 'pull_request'", proof['if'])
        self.assertNotIn('permissions', proof)
        for name in ['Read the artifact validator and lock from the exact trusted publisher revision',
                     'Check identity and package only generated site']:
            deploy_step = next(step for step in steps if step.get('name') == name)
            proof_step = next(step for step in proof['steps'] if step.get('name') == name)
            self.assertEqual(deploy_step['run'], proof_step['run'])
            self.assertEqual(deploy_step['env'], proof_step['env'])
            self.assertEqual(deploy_step['if'], "steps.freshness.outputs.current == 'true'")
            subprocess.run(['bash', '-n'], input=proof_step['run'], text=True, check=True)
        checkout = proof['steps'][1]['run']
        self.assertIn('credential.helper=', checkout)
        self.assertIn('GIT_CONFIG_GLOBAL=/dev/null', checkout)
        self.assertIn('"$PR_HEAD_REPOSITORY" == "$GITHUB_REPOSITORY"', checkout)
        self.assertIn('"$PUBLISHER_SHA" == "$GITHUB_SHA"', checkout)
        self.assertIn('https://github.com/Living-Proof-Labs/living-proof-labs.github.io.git', checkout)
        self.assertIn('rev-parse FETCH_HEAD', checkout)
        packaging = proof['steps'][2]['run']
        self.assertIn('publisher-check/tools/check_artifact.py check verified', packaging)
        self.assertIn('test -f verified/site/.nojekyll', packaging)
        self.assertNotIn('--dereference', packaging)
        self.assertEqual(self.workflow['jobs']['deploy']['needs'], 'build')
        seal = next(step for step in self.workflow['jobs']['build']['steps']
                    if 'check_artifact.py seal' in step.get('run', ''))
        self.assertEqual(seal['env']['PUBLISHER_SHA'], '${{ github.event.pull_request.head.sha || github.sha }}')


if __name__ == '__main__':
    unittest.main()
