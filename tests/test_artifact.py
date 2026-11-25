# SPDX-License-Identifier: Apache-2.0
"""Artifact identity and actual deployment-freshness script regression checks."""
import copy
import hashlib
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
                      if s.get('with', {}).get('name') == 'root-documentation-review-${{ github.run_attempt }}')['with']
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
            env = dict(os.environ, PUBLISHER_SHA=SHA, GITHUB_SHA=SHA, PUBLISHER_VERSION='',
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
        deployment_packaging = next(s['run'] for s in steps if s.get('name') ==
                                    'Check identity and package only generated site')
        self.assertEqual(packaging, deployment_packaging)
        self.assertEqual(proof['steps'][0]['with']['name'], 'root-documentation-review-${{ github.run_attempt }}')
        self.assertEqual(next(s for s in steps if 'actions/download-artifact' in s.get('uses', ''))
                         ['with']['name'], proof['steps'][0]['with']['name'])
        self.assertTrue(any('publisher_release_identity.py check-release' in s.get('run', '') for s in steps))
        self.assertFalse(any('docker' in s.get('run', '') or 'fetch_content' in s.get('run', '') for s in steps))

    def test_one_shared_build_input_and_production_gates(self):
        self.assertEqual(self.workflow['permissions'], {'contents': 'read'})
        jobs = self.workflow['jobs']
        version, build, release, deploy = (jobs[k] for k in ('version', 'build', 'release', 'deploy'))
        prefix = 'Living-Proof-Labs/collaboration-guidelines/.github/workflows/'
        self.assertEqual(version['uses'].partition('@')[0], f'{prefix}semantic-release-candidate.yml')
        self.assertEqual(version['permissions'], {'contents': 'read'})
        self.assertEqual(build['needs'], 'version')
        self.assertEqual(build['env'], {
            'PUBLISHER_SHA': '${{ needs.version.outputs.commit }}',
            'PUBLISHER_VERSION': '${{ needs.version.outputs.semver-version }}',
        })
        self.assertTrue(any('publisher_release_identity.py check-plan' in s.get('run', '') for s in build['steps']))
        self.assertEqual(sum('root-docs task verify' in s.get('run', '') for s in build['steps']), 1)
        for step in build['steps']:
            for term in ('PUBLISHER_TAG', 'git-tag', 'needs.release', 'check-release'):
                self.assertNotIn(term, str(step))
        self.assertEqual(release['needs'], ['version', 'build'])
        self.assertEqual(release['permissions'], {'contents': 'write'})
        self.assertIn("github.event_name == 'push'", release['if'])
        self.assertIn("github.ref == 'refs/heads/main'", release['if'])
        self.assertIn("needs.version.outputs.git-tag != ''", release['if'])
        self.assertIn('needs.version.outputs.version == needs.build.outputs.artifact-version', release['if'])
        self.assertIn('needs.version.outputs.commit == needs.build.outputs.artifact-commit', release['if'])
        self.assertNotIn('uses', release)
        self.assertNotIn('with', release)
        self.assertEqual(release['runs-on'], 'ubuntu-24.04')
        self.assertEqual(release['concurrency'], {
            'group': 'shared-semantic-release', 'cancel-in-progress': False,
        })
        writer = next(step for step in release['steps']
                      if 'semantic-release@' in step.get('uses', ''))
        self.assertEqual(writer['id'], 'release')
        candidate_ref = version['uses'].rpartition('@')[2]
        self.assertEqual(
            writer['uses'],
            'Living-Proof-Labs/collaboration-guidelines/.github/actions/semantic-release@' + candidate_ref)
        self.assertEqual(writer['with'], {
            'token': '${{ github.token }}',
            'expected-version': '${{ needs.build.outputs.artifact-version }}',
            'expected-commit': '${{ needs.build.outputs.artifact-commit }}',
        })
        for job in (jobs['verify-transport'], deploy):
            self.assertEqual(job['env']['PUBLISHER_VERSION'], writer['with']['expected-version'])
            self.assertEqual(job['env']['PUBLISHER_SHA'], writer['with']['expected-commit'])
        for job in (release, deploy):
            self.assertIn('needs.build.outputs.artifact-run-id == github.run_id', job['if'])
            self.assertIn('needs.build.outputs.artifact-attempt == github.run_attempt', job['if'])
        self.assertEqual(build['outputs'], {
            'artifact-version': '${{ steps.seal.outputs.version }}',
            'artifact-commit': '${{ steps.seal.outputs.commit }}',
            'artifact-run-id': '${{ steps.seal.outputs.run-id }}',
            'artifact-attempt': '${{ steps.seal.outputs.attempt }}',
        })
        seal = next(step for step in build['steps'] if step.get('id') == 'seal')
        self.assertEqual(seal['run'], 'python3 tools/check_artifact.py seal artifacts')
        checkout = release['steps'][0]
        self.assertEqual(checkout['uses'], build['steps'][0]['uses'])
        self.assertEqual(checkout['with'], {
            'ref': '${{ github.sha }}', 'fetch-depth': 0, 'persist-credentials': False,
        })
        attach = next(step for step in release['steps']
                      if step.get('name') == 'Attach main at the sealed commit')
        self.assertIn('git checkout --force -B main "$GITHUB_SHA"\n', attach['run'])
        self.assertIn('test "$(git rev-parse --abbrev-ref HEAD)" = main\n', attach['run'])
        self.assertIn('test "$(git rev-parse HEAD)" = "$GITHUB_SHA"\n', attach['run'])
        self.assertNotIn('origin/main', attach['run'])
        guard = next(step for step in release['steps'] if 'tools/release_git' in step.get('run', ''))
        self.assertLess(release['steps'].index(checkout), release['steps'].index(attach))
        self.assertLess(release['steps'].index(attach), release['steps'].index(guard))
        self.assertLess(release['steps'].index(guard), release['steps'].index(writer))
        self.assertIn('cp tools/release_git "$dir/git"', guard['run'])
        self.assertIn('echo "$dir" >> "$GITHUB_PATH"', guard['run'])
        self.assertNotIn('semantic-release.yml@', (ROOT / '.github/workflows/docs.yml').read_text())
        self.assertEqual(release['outputs']['published'], '${{ steps.release.outputs.published }}')
        self.assertEqual(release['outputs']['git-tag'], '${{ steps.release.outputs.git-tag }}')
        self.assertEqual(release['outputs']['commit'], '${{ steps.release.outputs.commit }}')
        self.assertEqual(deploy['needs'], ['version', 'build', 'release'])
        self.assertIn("needs.build.result == 'success'", deploy['if'])
        self.assertIn("needs.release.result == 'success'", deploy['if'])
        self.assertIn("needs.release.outputs.published == 'true'", deploy['if'])
        self.assertIn("github.event_name == 'workflow_dispatch' && inputs.release_tag != ''", deploy['if'])
        artifact_name = 'github-pages-${{ github.run_attempt }}'
        upload = next(step for step in deploy['steps'] if step.get('id') == 'pages-artifact')
        self.assertEqual(upload['with']['name'], artifact_name)
        self.assertEqual(deploy['steps'][-1]['with']['artifact_name'], artifact_name)


    def test_pages_readback_uses_the_same_runtime_by_exact_id_and_name(self):
        deploy = self.workflow['jobs']['deploy']
        self.assertEqual(deploy['permissions'], {'contents': 'read', 'pages': 'write', 'id-token': 'write'})
        steps = deploy['steps']
        fresh = "steps.freshness.outputs.current == 'true'"
        upload = next(step for step in steps if step.get('id') == 'pages-artifact')
        self.assertEqual(steps[-3]['name'], 'Require matching ID and name readback of the exact tar')
        self.assertEqual(steps[-1]['id'], 'deployment')
        expected_name = upload['with']['name']
        self.assertEqual(steps[-3]['env']['EXPECTED_NAME'], expected_name)
        self.assertEqual(steps[-1]['with']['artifact_name'], expected_name)
        self.assertTrue(all(step.get('if', '').startswith(fresh)
                            for step in steps[steps.index(upload) - 1:]))
        for route, selector, selected in (
                ('id', 'artifact-ids', '${{ steps.pages-artifact.outputs.artifact-id }}'),
                ('name', 'name', expected_name)):
            first = next(step for step in steps if step.get('id') == f'pages-{route}-first')
            retry = next(step for step in steps if step.get('id') == f'pages-{route}-retry')
            self.assertTrue(first['continue-on-error'])
            self.assertNotIn('continue-on-error', retry)
            self.assertEqual(retry['if'], f"{fresh} && steps.pages-{route}-first.outcome == 'failure'")
            self.assertEqual(first['uses'], retry['uses'])
            self.assertEqual(first['uses'], steps[1]['uses'])
            for step in (first, retry):
                self.assertEqual(set(step['with']), {selector, 'path'})
                self.assertEqual(step['with'][selector], selected)
            self.assertNotEqual(first['with']['path'], retry['with']['path'])
            readback = steps[-3]['env'][f'{route.upper()}_READBACK']
            self.assertIn(f"steps.pages-{route}-first.outcome == 'success'", readback)
            self.assertIn(f'steps.pages-{route}-retry.outputs.download-path', readback)

    def test_main_must_still_match_after_readback_and_directly_before_deploy(self):
        deploy = self.workflow['jobs']['deploy']
        self.assertEqual(deploy['concurrency']['group'], 'github-pages')
        start = next(step for step in deploy['steps'] if step.get('id') == 'freshness')
        readback, final, publish = deploy['steps'][-3:]
        self.assertEqual(readback['name'], 'Require matching ID and name readback of the exact tar')
        self.assertEqual(final['id'], 'final-freshness')
        self.assertEqual(publish['id'], 'deployment')
        self.assertEqual(publish['if'], "steps.freshness.outputs.current == 'true'")
        self.assertEqual(final['if'], publish['if'])
        self.assertNotIn('continue-on-error', final)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            git = root / 'git'
            git.write_text('#!/bin/sh\n[ "$1 $2 $3 $4 $6" = "-c credential.helper= ls-remote --exit-code refs/heads/main" ] || exit 9\n'
                           '[ "$5" = "https://github.com/$GITHUB_REPOSITORY.git" ] || exit 9\n'
                           'cat "$TEST_REMOTE_FILE"\n')
            git.chmod(0o755)
            ref = root / 'remote-ref'
            output = root / 'output'
            env = dict(os.environ, PATH=str(root) + ':' + os.environ['PATH'], TEST_REMOTE_FILE=str(ref),
                       GITHUB_REPOSITORY='Living-Proof-Labs/living-proof-labs.github.io',
                       GITHUB_SHA=SHA, GITHUB_OUTPUT=str(output), GITHUB_STEP_SUMMARY=str(root / 'summary'))
            ref.write_text(SHA + '\trefs/heads/main\n')
            subprocess.run(['bash', '-c', start['run']], env=env, check=True)
            self.assertEqual(output.read_text(), 'current=true\n')
            subprocess.run(['bash', '-c', final['run']], env=env, check=True)
            # Even with an unchanged, cached early success, a late main advance must fail.
            ref.write_text('f' * 40 + '\trefs/heads/main\n')
            stale = subprocess.run(['bash', '-c', final['run']], env=env, capture_output=True, text=True)
            self.assertNotEqual(stale.returncode, 0)
            self.assertIn('Main advanced during artifact readback', stale.stderr)
            self.assertEqual(output.read_text(), 'current=true\n')
            ref.unlink()
            unavailable = subprocess.run(['bash', '-c', final['run']], env=env, capture_output=True)
            self.assertNotEqual(unavailable.returncode, 0)

    def test_pages_readback_compares_both_downloads_to_the_produced_tar(self):
        steps = self.workflow['jobs']['deploy']['steps']
        record = next(step['run'] for step in steps if step.get('id') == 'pages-package')
        check = steps[-3]['run']
        for kind in ('exact', 'missing', 'wrong-id-bytes', 'wrong-name-bytes', 'wrong-attempt-name'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                work = Path(tmp)
                (work / 'artifact.tar').write_bytes(b'verified sealed tar')
                output = work / 'output'
                env = dict(os.environ, RUNNER_TEMP=str(work), GITHUB_OUTPUT=str(output))
                subprocess.run(['bash', '-e', '-o', 'pipefail', '-c', record], env=env, check=True)
                key, digest = output.read_text().strip().split('=', 1)
                self.assertEqual(key, 'tar-sha256')
                self.assertEqual(digest, hashlib.sha256(b'verified sealed tar').hexdigest())
                name = 'github-pages-2'
                by_id, by_name = work / 'id', work / 'name'
                id_dir = by_id / ('github-pages-1' if kind == 'wrong-attempt-name' else name)
                id_dir.mkdir(parents=True)
                by_name.mkdir()
                (id_dir / 'artifact.tar').write_bytes(
                    b'other' if kind == 'wrong-id-bytes' else b'verified sealed tar')
                if kind != 'missing':
                    (by_name / 'artifact.tar').write_bytes(
                        b'other' if kind == 'wrong-name-bytes' else b'verified sealed tar')
                result = subprocess.run(
                    ['bash', '-c', check], env=dict(env, EXPECTED_TAR=digest, EXPECTED_NAME=name,
                                                    ID_READBACK=str(by_id), NAME_READBACK=str(by_name)),
                    capture_output=True, text=True)
                self.assertEqual(result.returncode == 0, kind == 'exact', result.stderr)


if __name__ == '__main__':
    unittest.main()
