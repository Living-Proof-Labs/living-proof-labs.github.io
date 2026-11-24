# SPDX-License-Identifier: Apache-2.0
"""The release git guard tags the sealed commit after main moves and never updates main."""
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / 'tools' / 'release_git'
ENV = dict(os.environ, GIT_AUTHOR_NAME='Release Guard', GIT_AUTHOR_EMAIL='guard@example.com',
           GIT_COMMITTER_NAME='Release Guard', GIT_COMMITTER_EMAIL='guard@example.com')


def git(*args, repo=None, check=True):
    command = ['git']
    if repo is not None:
        command += ['-C', str(repo)]
    result = subprocess.run([*command, *args], capture_output=True, text=True, env=ENV)
    if check and result.returncode != 0:
        raise AssertionError(result.stderr or result.stdout)
    return result


def commit(repo, message):
    path = Path(repo) / 'note'
    path.write_text(message + '\n')
    git('add', 'note', repo=repo)
    git('commit', '-m', message, repo=repo)
    return git('rev-parse', 'HEAD', repo=repo).stdout.strip()


def run_guard(*args, cwd, git_real='/usr/bin/git'):
    env = dict(ENV, GIT_REAL=git_real)
    return subprocess.run([str(GUARD), *args], cwd=cwd, capture_output=True, text=True, env=env)


class ReleaseGitGuard(unittest.TestCase):
    def test_guard_invokes_real_git_by_absolute_path(self):
        source = GUARD.read_text()
        self.assertIn('GIT_REAL:-/usr/bin/git', source)
        self.assertNotIn(':refs/heads/', source)
        self.assertIn('+refs/heads/main:refs/remotes/release-guard/main', source)

    def test_overtaken_main_tags_the_built_commit_without_moving_main(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bare, built, later = root / 'bare.git', root / 'built', root / 'later'
            git('init', '--bare', '-b', 'main', str(bare))
            git('clone', str(bare), str(built))
            built_sha = commit(built, 'sealed fix')
            git('push', 'origin', 'HEAD:main', repo=built)
            git('clone', str(bare), str(later))
            later_sha = commit(later, 'later chore')
            git('push', 'origin', 'HEAD:main', repo=later)
            probe = run_guard('push', '--dry-run', '--no-verify', '--', str(bare), 'HEAD:main', cwd=built)
            self.assertEqual(probe.returncode, 0, probe.stderr)
            self.assertEqual(git('rev-parse', 'refs/heads/main', repo=bare).stdout.strip(), later_sha)
            git('tag', 'v1.2.3', built_sha, repo=built)
            pushed = run_guard('push', '--tags', '--', str(bare), cwd=built)
            self.assertEqual(pushed.returncode, 0, pushed.stderr)
            self.assertEqual(git('rev-parse', 'refs/tags/v1.2.3^{}', repo=bare).stdout.strip(), built_sha)
            self.assertEqual(git('rev-parse', 'refs/heads/main', repo=bare).stdout.strip(), later_sha)

    def test_current_main_probe_succeeds_without_moving_main(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bare, built = root / 'bare.git', root / 'built'
            git('init', '--bare', '-b', 'main', str(bare))
            git('clone', str(bare), str(built))
            built_sha = commit(built, 'sealed fix')
            git('push', 'origin', 'HEAD:main', repo=built)
            probe = run_guard('push', '--dry-run', '--no-verify', '--', str(bare), 'HEAD:main', cwd=built)
            self.assertEqual(probe.returncode, 0, probe.stderr)
            self.assertEqual(git('rev-parse', 'refs/heads/main', repo=bare).stdout.strip(), built_sha)

    def test_unrelated_history_is_rejected_and_main_stays(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bare, other, built = root / 'bare.git', root / 'other', root / 'built'
            git('init', '--bare', '-b', 'main', str(bare))
            git('clone', str(bare), str(other))
            other_sha = commit(other, 'unrelated')
            git('push', 'origin', 'HEAD:main', repo=other)
            git('init', '-b', 'main', str(built))
            commit(built, 'sealed fix')
            probe = run_guard('push', '--dry-run', '--no-verify', '--', str(bare), 'HEAD:main', cwd=built)
            self.assertNotEqual(probe.returncode, 0, probe.stdout)
            self.assertEqual(git('rev-parse', 'refs/heads/main', repo=bare).stdout.strip(), other_sha)

    def test_permission_failure_is_not_a_moved_main(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / 'git'
            log = Path(tmp) / 'log'
            fake.write_text(
                '#!/bin/bash\n'
                f'printf "%s\\n" "$*" >> {str(log)!r}\n'
                'if [[ "$1" == push ]]; then\n'
                '  echo " ! [rejected] main -> main (non-fast-forward)" >&2\n'
                '  echo "remote: 403 Permission to repo denied" >&2\n'
                '  exit 1\n'
                'fi\n'
                'if [[ "$1" == rev-parse && "$2" == HEAD ]]; then echo 1111111111111111111111111111111111111111; exit 0; fi\n'
                'if [[ "$1" == rev-parse ]]; then echo 2222222222222222222222222222222222222222; exit 0; fi\n'
                'if [[ "$1" == merge-base ]]; then exit 0; fi\n'
                'exit 0\n')
            fake.chmod(0o755)
            result = run_guard(
                'push', '--dry-run', '--no-verify', '--', 'https://example.test/repo.git', 'HEAD:main',
                cwd=tmp, git_real=str(fake))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('403', result.stderr)
            self.assertNotIn('fetch', log.read_text())

    def test_force_and_branch_updates_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / 'git'
            log = Path(tmp) / 'log'
            fake.write_text('#!/bin/bash\nprintf "%s\\n" "$*" >> ' + repr(str(log)) + '\nexit 0\n')
            fake.chmod(0o755)
            env_cwd = tmp
            cases = [
                ['push', '--force', '--tags', '--', 'https://example.test/repo.git'],
                ['push', '--force-with-lease', '--', 'https://example.test/repo.git', 'HEAD:main'],
                ['push', '--', 'https://example.test/repo.git', 'HEAD:main'],
                ['push', '--', 'https://example.test/repo.git', '+refs/heads/main'],
            ]
            for args in cases:
                log.write_text('')
                with self.subTest(args=args):
                    result = run_guard(*args, cwd=env_cwd, git_real=str(fake))
                    self.assertNotEqual(result.returncode, 0, result.stderr)
                    self.assertIn('refusing', result.stderr)
                    self.assertEqual(log.read_text(), '')

    def test_tag_and_notes_pushes_are_forwarded_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / 'git'
            log = Path(tmp) / 'log'
            fake.write_text('#!/bin/bash\nprintf "%s\\n" "$*" >> ' + repr(str(log)) + '\nexit 0\n')
            fake.chmod(0o755)
            for args in (
                ['push', '--tags', '--', 'https://example.test/repo.git'],
                ['push', '--', 'https://example.test/repo.git', 'refs/notes/semantic-release-v1.2.3'],
            ):
                log.write_text('')
                result = run_guard(*args, cwd=tmp, git_real=str(fake))
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(log.read_text().strip(), ' '.join(args))

    def test_guard_script_is_executable(self):
        mode = GUARD.stat().st_mode
        self.assertTrue(mode & stat.S_IXUSR)


if __name__ == '__main__':
    unittest.main()
