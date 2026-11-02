# SPDX-License-Identifier: Apache-2.0
"""The pin check accepts a merged commit and rejects one only on a side branch."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from check_content_pin import reachable  # noqa: E402


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


if __name__ == '__main__':
    unittest.main()
