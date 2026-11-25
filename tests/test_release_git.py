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


def recording_git(tmp):
    fake = Path(tmp) / 'git'
    log = Path(tmp) / 'log'
    fake.write_text('#!/bin/bash\nprintf "%s\\n" "$*" >> ' + repr(str(log)) + '\nexit 0\n')
    fake.chmod(0o755)
    return fake, log


URL = 'https://example.test/repo.git'
SHA = 'a' * 40
LOG_PARSER_FORMAT = (
    '%H==FIELD==%h==FIELD==%T==FIELD==%t==FIELD==%an==FIELD==%ae==FIELD==%ai==FIELD=='
    '%cn==FIELD==%ce==FIELD==%ci==FIELD==%s==FIELD==%b==FIELD==%H==FIELD==%B==FIELD=='
    '%d==FIELD==%ci==END==')
FOR_EACH_REF_FORMAT = '%(refname:short)%00%(objecttype)%00%(objectname)%00%(*objectname)'


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

    def assert_refused(self, args, message, cwd, git_real, log):
        log.write_text('')
        result = run_guard(*args, cwd=cwd, git_real=git_real)
        self.assertNotEqual(result.returncode, 0, result.stderr)
        self.assertIn(message, result.stderr)
        for other in (
            'refusing a force push',
            'refusing a forced refspec',
            'refusing a push that is not a tag or notes update',
            'refusing an unrecognized git option',
            'refusing a git config override',
            'refusing a git config change',
            'refusing an unknown git subcommand',
            'refusing a remote command option',
            'refusing a notes refspec',
            'refusing fetch arguments',
            'refusing tag arguments',
            'refusing notes arguments',
            'refusing for-each-ref arguments',
            'refusing ls-remote arguments',
            'refusing log arguments',
            'refusing rev-parse arguments',
            'refusing rev-list arguments',
            'refusing check-ref-format arguments',
            'refusing an unused git option',
            'refusing a push remote',
        ):
            if other != message:
                self.assertNotIn(other, result.stderr)
        self.assertEqual(log.read_text(), '')
        return result

    def test_force_push_is_refused_before_the_catchall(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake, log = recording_git(tmp)
            cases = [
                ['push', '--force', '--tags', '--', URL],
                ['push', '--force-with-lease', '--', URL, 'HEAD:main'],
                ['push', '--force-with-lease=refs/heads/main', '--tags', '--', URL],
            ]
            for args in cases:
                with self.subTest(args=args):
                    self.assert_refused(args, 'refusing a force push', tmp, str(fake), log)

    def test_forced_refspec_is_refused_before_the_catchall(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake, log = recording_git(tmp)
            cases = [
                ['push', '--', URL, '+refs/heads/main'],
                ['push', '--', URL, '+refs/notes/semantic-release-v1.2.3'],
            ]
            for args in cases:
                with self.subTest(args=args):
                    self.assert_refused(args, 'refusing a forced refspec', tmp, str(fake), log)

    def test_branch_update_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake, log = recording_git(tmp)
            self.assert_refused(
                ['push', '--', URL, 'HEAD:main'],
                'refusing a push that is not a tag or notes update', tmp, str(fake), log)

    def test_directory_and_git_dir_are_unused_options(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake, log = recording_git(tmp)
            cases = [
                ['-C', '/tmp/not-used', 'push', '--', URL, 'HEAD:main'],
                ['-C/tmp/not-used', 'fetch', 'origin', 'refs/tags/v1.0.0:refs/tags/v1.0.0', '--force'],
                ['--git-dir', '/tmp/not-a-repo', 'push', '--force', '--', URL, 'HEAD:main'],
                ['--git-dir=/tmp/not-a-repo', 'fetch', '--tags', '--', 'origin'],
            ]
            for args in cases:
                with self.subTest(args=args[0]):
                    self.assert_refused(args, 'refusing an unused git option', tmp, str(fake), log)

    def test_global_options_stay_on_forwarded_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake, log = recording_git(tmp)
            cases = [
                ['--', 'tag', '--merged', 'main'],
            ]
            for args in cases:
                log.write_text('')
                with self.subTest(args=args):
                    result = run_guard(*args, cwd=tmp, git_real=str(fake))
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(log.read_text().strip(), ' '.join(args))

    def test_command_line_alias_cannot_push_a_branch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bare, built = root / 'bare.git', root / 'built'
            git('init', '--bare', '-b', 'main', str(bare))
            git('clone', str(bare), str(built))
            built_sha = commit(built, 'sealed fix')
            git('push', 'origin', 'HEAD:main', repo=built)
            alias = run_guard(
                '-c', 'alias.p=push', 'p', '--force', '--', str(bare), 'HEAD:main', cwd=built)
            self.assertNotEqual(alias.returncode, 0, alias.stderr)
            self.assertIn('refusing a git config override', alias.stderr)
            self.assertNotIn('refusing an unknown git subcommand', alias.stderr)
            attached = run_guard(
                '-calias.p=push', 'p', '--force', '--', str(bare), 'HEAD:main', cwd=built)
            self.assertIn('refusing a git config override', attached.stderr)
            self.assertNotIn('refusing an unknown git subcommand', attached.stderr)
            env = dict(ENV, AL='push')
            configured = subprocess.run(
                [str(GUARD), '--config-env=alias.q=AL', 'q', '--', str(bare), 'HEAD:refs/heads/evil'],
                cwd=built, capture_output=True, text=True, env=env)
            self.assertNotEqual(configured.returncode, 0, configured.stderr)
            self.assertIn('refusing a git config override', configured.stderr)
            self.assertNotIn('refusing an unknown git subcommand', configured.stderr)
            separate = run_guard(
                '--config-env', 'alias.q=AL', 'q', '--', str(bare), 'HEAD:refs/heads/evil', cwd=built)
            self.assertIn('refusing a git config override', separate.stderr)
            self.assertNotIn('refusing an unrecognized git option', separate.stderr)
            self.assertEqual(git('rev-parse', 'refs/heads/main', repo=bare).stdout.strip(), built_sha)
            self.assertNotEqual(git('rev-parse', '--verify', 'refs/heads/evil', repo=bare, check=False).returncode, 0)

    def test_config_override_cannot_rewrite_the_push_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake, log = recording_git(tmp)
            cases = [
                ['-c', 'url.https://github.com/.insteadOf=https://evil.example/', 'push', '--tags', '--', URL],
                ['-c', 'url.https://github.com/.pushInsteadOf=https://evil.example/', 'push', '--tags', '--', URL],
                ['-c', 'core.sshCommand=evil', 'push', '--tags', '--', URL],
                ['-ccore.hooksPath=/tmp/hooks', 'push', '--tags', '--', URL],
            ]
            for args in cases:
                with self.subTest(args=args):
                    self.assert_refused(args, 'refusing a git config override', tmp, str(fake), log)

    def test_unknown_subcommand_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake, log = recording_git(tmp)
            for args in (['status'], ['commit', '-m', 'nope'], ['p', '--force', '--', URL, 'HEAD:main']):
                with self.subTest(args=args):
                    self.assert_refused(args, 'refusing an unknown git subcommand', tmp, str(fake), log)

    def test_release_subcommands_are_forwarded(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake, log = recording_git(tmp)
            cases = [
                ['rev-parse', 'HEAD'],
                ['rev-parse', '--is-shallow-repository'],
                ['rev-parse', '--abbrev-ref', 'HEAD'],
                ['rev-parse', '--verify', 'HEAD'],
                ['rev-parse', '--verify', SHA],
                ['rev-parse', '--verify', 'refs/tags/v1.2.3^{commit}'],
                ['rev-parse', '--verify', 'v1.2.3^{commit}'],
                ['rev-parse', '--git-dir'],
                ['rev-list', '-1', 'v1.2.3'],
                ['tag', '--merged', 'main'],
                ['tag', '--merged', SHA],
                ['tag', 'v1.2.3', SHA],
                ['log', '-z', '--format=%H%x00%B', 'HEAD'],
                ['log', '-z', '--format=%H%x00%B', f'v1.2.3..{SHA}'],
                ['log', f'--format={LOG_PARSER_FORMAT}', f'{SHA}..{SHA}'],
                ['log', '--tags=*', '--decorate-refs=refs/tags/*', '--no-walk',
                 '--format=%d%x09%N', '--notes=refs/notes/semantic-release*'],
                ['fetch', '--unshallow', '--tags', '--', URL],
                ['fetch', '--tags', '--', URL],
                ['fetch', '--unshallow', '--', URL, '+refs/notes/*:refs/notes/*'],
                ['fetch', '--', URL, '+refs/notes/*:refs/notes/*'],
                ['fetch', 'origin', 'refs/tags/v1.2.3:refs/tags/v1.2.3', '--force'],
                ['ls-remote', '--heads', '--', URL],
                ['ls-remote', '--heads', '--', URL, 'main'],
                ['ls-remote', '--tags', '--', URL, 'refs/tags/v1.2.3'],
                ['config', '--get', 'remote.origin.url'],
                ['notes', '--ref', 'semantic-release-v1.2.3', 'add', '-f', '-m', '{}', 'v1.2.3'],
                ['check-ref-format', 'refs/tags/v0.0.0'],
                ['check-ref-format', 'refs/heads/main'],
                ['for-each-ref', f'--format={FOR_EACH_REF_FORMAT}', 'refs/tags'],
                ['push', '--tags', '--', URL],
                ['push', '--', URL, 'refs/notes/semantic-release-v1.2.3'],
                ['push', '--', URL, 'refs/notes/a:refs/notes/b'],
                ['--', 'rev-parse', 'HEAD'],
            ]
            for args in cases:
                log.write_text('')
                with self.subTest(args=args):
                    result = run_guard(*args, cwd=tmp, git_real=str(fake))
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(log.read_text().strip(), ' '.join(args))

    def test_config_writes_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake, log = recording_git(tmp)
            self.assert_refused(
                ['config', 'alias.p', 'push'],
                'refusing a git config change', tmp, str(fake), log)
            self.assert_refused(
                ['config', '--replace-all', 'url.https://github.com/.insteadOf', 'https://evil.example/'],
                'refusing a git config change', tmp, str(fake), log)

    def test_notes_push_cannot_create_a_branch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bare, built = root / 'bare.git', root / 'built'
            git('init', '--bare', '-b', 'main', str(bare))
            git('clone', str(bare), str(built))
            built_sha = commit(built, 'sealed fix')
            git('push', 'origin', 'HEAD:main', repo=built)
            git('update-ref', 'refs/notes/x', built_sha, repo=built)
            bad = run_guard('push', '--', str(bare), 'refs/notes/x:refs/heads/evil', cwd=built)
            self.assertNotEqual(bad.returncode, 0, bad.stderr)
            self.assertIn('refusing a notes refspec', bad.stderr)
            self.assertNotIn('refusing a push that is not a tag or notes update', bad.stderr)
            self.assertNotEqual(
                git('rev-parse', '--verify', 'refs/heads/evil', repo=bare, check=False).returncode, 0)
            plus = run_guard('push', '--', str(bare), '+refs/notes/semantic-release-v1.2.3', cwd=built)
            self.assertNotEqual(plus.returncode, 0)
            self.assertIn('refusing a forced refspec', plus.stderr)
            self.assertNotIn('refusing a notes refspec', plus.stderr)

    def test_fetch_cannot_run_a_remote_command_or_update_a_branch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            marker = root / 'PWNED'
            bare, built = root / 'bare.git', root / 'built'
            git('init', '--bare', '-b', 'main', str(bare))
            git('clone', str(bare), str(built))
            commit(built, 'sealed fix')
            packed = run_guard(
                'fetch', f'--upload-pack=touch {marker}', str(bare), 'main', cwd=built)
            self.assertNotEqual(packed.returncode, 0, packed.stderr)
            self.assertIn('refusing a remote command option', packed.stderr)
            self.assertFalse(marker.exists())
            fake, log = recording_git(tmp)
            cases = [
                (['fetch', '--upload-pack=touch /tmp/PWNED', str(bare), 'main'],
                 'refusing a remote command option'),
                (['fetch', '-u', 'touch /tmp/PWNED', str(bare)], 'refusing a remote command option'),
                (['ls-remote', '--upload-pack=touch /tmp/PWNED', URL], 'refusing a remote command option'),
                (['fetch', '--receive-pack=touch /tmp/PWNED', URL], 'refusing a remote command option'),
                (['fetch', '--exec=touch /tmp/PWNED', URL], 'refusing a remote command option'),
                (['fetch', '--update-head-ok', '--', URL, '+refs/heads/main:refs/heads/main'],
                 'refusing fetch arguments'),
                (['fetch', 'origin', '+refs/heads/main:refs/heads/main'], 'refusing fetch arguments'),
                (['fetch', '--tags', '--', URL, 'refs/notes/x:refs/heads/main'], 'refusing fetch arguments'),
                (['tag', '-f', 'v1.2.3', SHA], 'refusing tag arguments'),
                (['tag', 'refs/heads/evil', SHA], 'refusing tag arguments'),
                (['notes', '--ref', 'refs/heads/evil', 'add', '-f', '-m', '{}', 'v1.2.3'],
                 'refusing notes arguments'),
                (['for-each-ref', '--format=%(authordate)', 'refs/heads'],
                 'refusing for-each-ref arguments'),
                (['config', '--get', 'include.path'], 'refusing a git config change'),
                (['config', '--get', '--file', str(root / 'evil'), 'remote.origin.url'],
                 'refusing a git config change'),
                (['ls-remote', '--heads', '--upload-pack=touch', URL], 'refusing a remote command option'),
            ]
            for args, message in cases:
                with self.subTest(args=args):
                    self.assert_refused(args, message, tmp, str(fake), log)

    def test_unused_global_options_do_not_run_a_helper(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake, log = recording_git(tmp)
            cases = [
                ['--exec-path=/tmp/ep', 'push', '--tags', '--', URL],
                ['--exec-path', '/tmp/ep', 'ls-remote', '--heads', '--', URL],
                ['--work-tree=/tmp/wt', 'rev-parse', 'HEAD'],
                ['--work-tree', '/tmp/wt', 'rev-parse', 'HEAD'],
                ['--namespace=hidden', 'rev-parse', 'HEAD'],
                ['--namespace', 'hidden', 'rev-parse', 'HEAD'],
                ['--super-prefix=pre', 'rev-parse', 'HEAD'],
                ['--super-prefix', 'pre', 'rev-parse', 'HEAD'],
            ]
            for args in cases:
                with self.subTest(args=args[0]):
                    self.assert_refused(args, 'refusing an unused git option', tmp, str(fake), log)

    def test_rev_parse_rejects_an_extra_argument(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake, log = recording_git(tmp)
            self.assert_refused(
                ['rev-parse', 'HEAD', '--foo'], 'refusing rev-parse arguments', tmp, str(fake), log)

    def test_log_rejects_an_extra_argument(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake, log = recording_git(tmp)
            self.assert_refused(
                ['log', '-z', '--format=%H%x00%B', 'HEAD', '--all'],
                'refusing log arguments', tmp, str(fake), log)

    def test_ls_remote_rejects_an_extra_argument(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake, log = recording_git(tmp)
            self.assert_refused(
                ['ls-remote', '--heads', '--', URL, 'main', '--exit-code'],
                'refusing ls-remote arguments', tmp, str(fake), log)

    def test_fetch_tag_source_must_match_destination(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake, log = recording_git(tmp)
            self.assert_refused(
                ['fetch', 'origin', 'refs/tags/v1.2.3:refs/tags/v9.9.9', '--force'],
                'refusing fetch arguments', tmp, str(fake), log)

    def test_remote_with_a_colon_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake, log = recording_git(tmp)
            for remote in ('ext::git', 'git@github.com:org/repo.git'):
                with self.subTest(remote=remote):
                    self.assert_refused(
                        ['fetch', '--tags', '--', remote],
                        'refusing fetch arguments', tmp, str(fake), log)

    def test_dry_run_push_rejects_a_non_remote(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake, log = recording_git(tmp)
            self.assert_refused(
                ['push', '--dry-run', '--no-verify', '--', 'ext::evil', 'HEAD:main'],
                'refusing a push remote', tmp, str(fake), log)

    def test_tags_push_rejects_a_non_remote(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake, log = recording_git(tmp)
            self.assert_refused(
                ['push', '--tags', '--', 'git@github.com:org/repo.git'],
                'refusing a push remote', tmp, str(fake), log)

    def test_unknown_global_option_is_not_forwarded(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake, log = recording_git(tmp)
            self.assert_refused(
                ['--not-a-real-option', 'rev-parse', 'HEAD'],
                'refusing an unrecognized git option', tmp, str(fake), log)

    def test_bare_notes_ref_must_be_one_component(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake, log = recording_git(tmp)
            self.assert_refused(
                ['push', '--', URL, 'refs/notes/../heads/main'],
                'refusing a notes refspec', tmp, str(fake), log)
            self.assert_refused(
                ['push', '--', URL, 'refs/notes/foo/bar'],
                'refusing a notes refspec', tmp, str(fake), log)

    def test_planted_uploadpack_does_not_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evil = root / 'evil'
            marker = root / 'PWNED'
            git('init', '-b', 'main', str(evil))
            commit(evil, 'planted')
            git('config', 'remote.origin.url', 'https://example.invalid/repo.git', repo=evil)
            git('config', 'remote.origin.uploadpack', f'touch {marker}; false', repo=evil)
            cases = [
                ['-C', str(evil), 'fetch', 'origin', 'refs/tags/v1.0.0:refs/tags/v1.0.0', '--force'],
                ['-C' + str(evil), 'fetch', 'origin', 'refs/tags/v1.0.0:refs/tags/v1.0.0', '--force'],
                ['--git-dir', str(evil / '.git'), 'fetch', '--tags', '--', 'origin'],
                ['--git-dir=' + str(evil / '.git'), 'fetch', '--tags', '--', 'origin'],
            ]
            for args in cases:
                marker.unlink(missing_ok=True)
                with self.subTest(args=args[0]):
                    result = run_guard(*args, cwd=tmp)
                    self.assertNotEqual(result.returncode, 0, result.stderr)
                    self.assertIn('refusing an unused git option', result.stderr)
                    self.assertFalse(marker.exists())

    def test_tag_create_requires_a_commit_sha(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake, log = recording_git(tmp)
            for target in ('HEAD', 'main'):
                with self.subTest(target=target):
                    self.assert_refused(
                        ['tag', 'v1.0.0', target], 'refusing tag arguments', tmp, str(fake), log)

    def test_check_ref_format_rejects_extra_arguments(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake, log = recording_git(tmp)
            for args in (
                ['check-ref-format', 'refs/tags/v1.2.3', '--normalize'],
                ['check-ref-format', '--branch'],
            ):
                with self.subTest(args=args):
                    self.assert_refused(
                        args, 'refusing check-ref-format arguments', tmp, str(fake), log)

    def test_rev_list_accepts_only_a_tag(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake, log = recording_git(tmp)
            for args in (
                ['rev-list', '-1', 'HEAD'],
                ['rev-list', '-1', SHA],
                ['rev-list', 'v1.2.3'],
                ['rev-list', '-1', 'v1.2.3', '--count'],
            ):
                with self.subTest(args=args):
                    self.assert_refused(
                        args, 'refusing rev-list arguments', tmp, str(fake), log)

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
