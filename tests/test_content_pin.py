# SPDX-License-Identifier: Apache-2.0
"""The pin check accepts a merged commit and rejects one only on a side branch.

It also rejects a lock that names any repository other than Living-Proof-Labs/.github.
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

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from check_content_pin import main, reachable  # noqa: E402


def git(repo, *args):
    return subprocess.check_output(['git', '-c', 'user.name=t', '-c', 'user.email=t@t', *args],
                                   cwd=repo, text=True).strip()


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
    def run_main(self, repository, commit):
        with tempfile.TemporaryDirectory() as root:
            Path(root, 'content.lock.json').write_text(
                json.dumps({'repository': repository, 'commit': commit}))
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                return main(['check_content_pin.py'], root=Path(root)), output.getvalue()

    def test_rejects_another_repository_before_fetching(self):
        with tempfile.TemporaryDirectory() as repo:
            git(repo, 'init', '-q', '-b', 'main')
            git(repo, 'commit', '-q', '--allow-empty', '-m', 'one')
            commit = git(repo, 'rev-parse', 'HEAD')
            os.environ['CONTENT_MAIN_REF'] = 'main'  # the commit is reachable: only the name fails
            try:
                for repository in ('Living-Proof-Labs/website', 'someone/.github',
                                   'living-proof-labs/.github', '', None):
                    with self.subTest(repository=repository):
                        code, output = self.run_main(repository, commit)
                        self.assertEqual(code, 1)
                        self.assertIn('only Living-Proof-Labs/.github', output)
            finally:
                del os.environ['CONTENT_MAIN_REF']

    def test_accepts_the_content_repository(self):
        with tempfile.TemporaryDirectory() as repo:
            git(repo, 'init', '-q', '-b', 'main')
            git(repo, 'commit', '-q', '--allow-empty', '-m', 'one')
            commit = git(repo, 'rev-parse', 'HEAD')
            os.environ['CONTENT_MAIN_REF'] = 'main'
            os.environ['CONTENT_DIR'] = repo
            try:
                code, output = self.run_main('Living-Proof-Labs/.github', commit)
            finally:
                del os.environ['CONTENT_MAIN_REF'], os.environ['CONTENT_DIR']
            self.assertEqual(code, 0, output)


if __name__ == '__main__':
    unittest.main()
