# SPDX-License-Identifier: Apache-2.0
"""The pin check accepts a merged release tag and rejects branches, bare commits, and unmerged tags.

It also verifies that build_docs refuses a content.lock.json pointing at a branch instead of a tag,
and refuses CI publication if the checkout lacks a matching release tag.
"""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import build_docs  # noqa: E402
from check_content_pin import lock_errors, main, reachable  # noqa: E402


def git(repo, *args):
    return subprocess.check_output(['git', '-c', 'user.name=t', '-c', 'user.email=t@t', *args],
                                   cwd=repo, text=True).strip()


def make_content_repo(repo, *, tag='v1.0.0', tag_on_branch_only=False):
    git(repo, 'init', '-q', '-b', 'main')
    Path(repo, 'docs').mkdir(exist_ok=True)
    Path(repo, 'docs', 'site.json').write_text('{"pages": [], "directory": "docs/directory.json"}\n')
    git(repo, 'add', 'docs/site.json')
    git(repo, 'commit', '-q', '-m', 'one')
    commit = git(repo, 'rev-parse', 'HEAD')
    if tag_on_branch_only:
        git(repo, 'branch', tag, commit)
    elif tag:
        git(repo, 'tag', tag, commit)
    return commit


REVIEWED_SOURCE = 'dbf9895d74c95410adb6bb8b9222c88ba05393c4'
REVIEWED_DIGEST = '7d0a39a9445f5061cadd76e6aad792bba3715596743e31c0553a890dcf5f6d40'


class CommittedLock(unittest.TestCase):
    def test_committed_content_lock_pins_a_supported_exact_source(self):
        lock = json.loads((ROOT / 'content.lock.json').read_text())
        self.assertEqual(lock['repository'], 'Living-Proof-Labs/.github')
        self.assertEqual(lock_errors(lock), [])
        if lock.get('mode') == 'documentation-v1':
            self.assertEqual(set(lock), {'mode', 'repository', 'commit', 'manifest_sha256'})
        else:
            self.assertEqual(set(lock), {'repository', 'tag', 'commit'})

    def test_committed_lock_is_the_reviewed_documentation_payload(self):
        lock = json.loads((ROOT / 'content.lock.json').read_text())
        self.assertEqual(lock, {
            'mode': 'documentation-v1',
            'repository': 'Living-Proof-Labs/.github',
            'commit': REVIEWED_SOURCE,
            'manifest_sha256': REVIEWED_DIGEST,
        })
        self.assertNotIn('tag', lock)


class PinReachability(unittest.TestCase):
    def test_merged_and_unmerged(self):
        with tempfile.TemporaryDirectory() as repo:
            git(repo, 'init', '-q', '-b', 'main')
            git(repo, 'commit', '-q', '--allow-empty', '-m', 'one')
            merged = git(repo, 'rev-parse', 'HEAD')
            git(repo, 'checkout', '-q', '-b', 'side')
            git(repo, 'commit', '-q', '--allow-empty', '-m', 'side')
            side = git(repo, 'rev-parse', 'HEAD')
            self.assertTrue(reachable(repo, merged, 'main'))
            self.assertFalse(reachable(repo, side, 'main'))


class PinRepository(unittest.TestCase):
    def run_main(self, payload):
        with tempfile.TemporaryDirectory() as root:
            Path(root, 'content.lock.json').write_text(json.dumps(payload))
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                return main(['check_content_pin.py'], root=Path(root)), output.getvalue()

    def test_rejects_another_repository_before_fetching(self):
        with tempfile.TemporaryDirectory() as repo:
            commit = make_content_repo(repo)
            with mock.patch.dict(os.environ, {'CONTENT_MAIN_REF': 'main', 'CONTENT_DIR': repo}):
                for repository in ('Living-Proof-Labs/website', 'someone/.github',
                                   'living-proof-labs/.github', '', None):
                    with self.subTest(repository=repository):
                        code, output = self.run_main({
                            'repository': repository,
                            'tag': 'v1.0.0',
                            'commit': commit,
                        })
                        self.assertEqual(code, 1)
                        self.assertIn('only Living-Proof-Labs/.github', output)

    def test_rejects_branch_or_non_release_tag_in_lock(self):
        with tempfile.TemporaryDirectory() as repo:
            commit = make_content_repo(repo)
            with mock.patch.dict(os.environ, {'CONTENT_MAIN_REF': 'main', 'CONTENT_DIR': repo}):
                bad_payloads = [
                    {'repository': 'Living-Proof-Labs/.github', 'tag': 'main', 'commit': commit},
                    {'repository': 'Living-Proof-Labs/.github', 'tag': 'refs/heads/main', 'commit': commit},
                    {'repository': 'Living-Proof-Labs/.github', 'tag': 'feature/docs', 'commit': commit},
                    {'repository': 'Living-Proof-Labs/.github', 'tag': 'v1.0', 'commit': commit},
                    {'repository': 'Living-Proof-Labs/.github', 'tag': 'latest', 'commit': commit},
                    {'repository': 'Living-Proof-Labs/.github', 'tag': '', 'commit': commit},
                    {'repository': 'Living-Proof-Labs/.github', 'commit': commit},
                    {'repository': 'Living-Proof-Labs/.github', 'tag': 'v1.0.0', 'branch': 'main', 'commit': commit},
                ]
                for payload in bad_payloads:
                    with self.subTest(payload=payload):
                        code, output = self.run_main(payload)
                        self.assertEqual(code, 1, output)

    def test_rejects_branch_named_like_a_tag(self):
        with tempfile.TemporaryDirectory() as repo:
            commit = make_content_repo(repo, tag='v1.0.0', tag_on_branch_only=True)
            with mock.patch.dict(os.environ, {'CONTENT_MAIN_REF': 'main', 'CONTENT_DIR': repo}):
                code, output = self.run_main({
                    'repository': 'Living-Proof-Labs/.github',
                    'tag': 'v1.0.0',
                    'commit': commit,
                })
            self.assertEqual(code, 1)
            self.assertIn('is not a tag', output)

    def test_rejects_tag_pointing_to_different_commit(self):
        with tempfile.TemporaryDirectory() as repo:
            first = make_content_repo(repo)
            git(repo, 'commit', '-q', '--allow-empty', '-m', 'two')
            second = git(repo, 'rev-parse', 'HEAD')
            with mock.patch.dict(os.environ, {'CONTENT_MAIN_REF': 'main', 'CONTENT_DIR': repo}):
                code, output = self.run_main({
                    'repository': 'Living-Proof-Labs/.github',
                    'tag': 'v1.0.0',
                    'commit': second,
                })
            self.assertEqual(code, 1)
            self.assertIn(f'resolves to {first}', output)

    def test_accepts_the_content_repository_at_a_merged_tag(self):
        with tempfile.TemporaryDirectory() as repo:
            commit = make_content_repo(repo)
            with mock.patch.dict(os.environ, {'CONTENT_MAIN_REF': 'main', 'CONTENT_DIR': repo}):
                code, output = self.run_main({
                    'repository': 'Living-Proof-Labs/.github',
                    'tag': 'v1.0.0',
                    'commit': commit,
                })
            self.assertEqual(code, 0, output)
            self.assertIn('v1.0.0', output)


class BuildRejectsBranchPin(unittest.TestCase):
    def test_site_build_fails_when_lock_points_at_a_branch_instead_of_a_tag(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / 'content'
            repo.mkdir()
            commit = make_content_repo(repo)
            lock_path = Path(tmp) / 'content.lock.json'
            bad_locks = [
                {'repository': 'Living-Proof-Labs/.github', 'tag': 'main', 'commit': commit},
                {'repository': 'Living-Proof-Labs/.github', 'tag': 'refs/heads/main', 'commit': commit},
                {'repository': 'Living-Proof-Labs/.github', 'branch': 'main', 'commit': commit},
                {'repository': 'Living-Proof-Labs/.github', 'commit': commit},
            ]
            for payload in bad_locks:
                with self.subTest(payload=payload):
                    lock_path.write_text(json.dumps(payload))
                    with mock.patch.object(build_docs, 'LOCK', lock_path), \
                         mock.patch.dict(os.environ, {'CONTENT_DIR': str(repo)}):
                        with self.assertRaises(SystemExit) as caught:
                            build_docs.main()
                    self.assertIn('FAIL:', str(caught.exception))

    def test_content_identity_requires_release_tag_in_checkout(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / 'content'
            repo.mkdir()
            commit = make_content_repo(repo, tag='v1.0.0', tag_on_branch_only=True)
            lock = {
                'repository': 'Living-Proof-Labs/.github',
                'tag': 'v1.0.0',
                'commit': commit,
            }
            with mock.patch.dict(os.environ, {'CONTENT_DIR': str(repo), 'GITHUB_ACTIONS': 'false'}):
                _, content = build_docs.content_identity(lock)
            self.assertFalse(content['pinned'])
            self.assertIsNone(content['tag'])
            self.assertEqual(content['locked_tag'], 'v1.0.0')

            with mock.patch.dict(os.environ, {'CONTENT_DIR': str(repo), 'GITHUB_ACTIONS': 'true'}):
                with self.assertRaises(SystemExit) as caught:
                    build_docs.content_identity(lock)
            self.assertIn('tag v1.0.0 is missing', str(caught.exception))

    def test_ci_rejects_tag_mismatch_even_when_checkout_matches_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            first = make_content_repo(repo)
            git(repo, 'commit', '-q', '--allow-empty', '-m', 'two')
            second = git(repo, 'rev-parse', 'HEAD')
            lock = {'repository': 'Living-Proof-Labs/.github',
                    'tag': 'v1.0.0', 'commit': second}
            with mock.patch.dict(os.environ, {'CONTENT_DIR': str(repo),
                                             'GITHUB_ACTIONS': 'true'}):
                with self.assertRaises(SystemExit) as caught:
                    build_docs.content_identity(lock)
            self.assertIn(f'tag v1.0.0 resolves to {first[:12]}', str(caught.exception))
            self.assertIn(second[:12], str(caught.exception))

    def test_content_identity_records_pinned_tag(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / 'content'
            repo.mkdir()
            commit = make_content_repo(repo, tag='v1.0.0')
            lock = {
                'repository': 'Living-Proof-Labs/.github',
                'tag': 'v1.0.0',
                'commit': commit,
            }
            with mock.patch.dict(os.environ, {'CONTENT_DIR': str(repo), 'GITHUB_ACTIONS': 'true'}):
                _, content = build_docs.content_identity(lock)
            self.assertTrue(content['pinned'])
            self.assertEqual(content['tag'], 'v1.0.0')
            self.assertEqual(content['locked_tag'], 'v1.0.0')
            self.assertEqual(content['commit'], commit)
            self.assertEqual(content['locked_commit'], commit)


if __name__ == '__main__':
    unittest.main()
