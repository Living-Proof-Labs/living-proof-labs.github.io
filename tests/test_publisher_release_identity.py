# SPDX-License-Identifier: Apache-2.0
"""Publisher release planning, transport and fail-closed delivery fixtures."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import build_docs
from check_artifact import artifact, emit_seal_outputs
from publisher_release_identity import validate_delivery, validate_plan, verify_existing_release
from test_artifact import LEGACY, RUN, SHA

PR = '1.2.3-pr.87.42.1'
MAIN_PREVIEW = '1.2.4-main.43.1'
STABLE = '1.2.3'
OTHER = 'e' * 40


class PublisherIdentity(unittest.TestCase):
    def test_untagged_pr_and_main_use_same_named_plan_and_exact_context(self):
        for version in (PR, STABLE, MAIN_PREVIEW):
            validate_plan(version, SHA, SHA, SHA, RUN, RUN, '1', '1')
        for context in [
            ('', SHA, SHA, SHA, RUN, RUN, '1', '1'),
            ('01.2.3', SHA, SHA, SHA, RUN, RUN, '1', '1'),
            (PR, SHA, OTHER, SHA, RUN, RUN, '1', '1'),
            (PR, SHA, SHA, OTHER, RUN, RUN, '1', '1'),
            (PR, SHA, SHA, SHA, RUN, '999', '1', '1'),
            (PR, SHA, SHA, SHA, RUN, RUN, '1', '2'),
            (PR, SHA, SHA, SHA, RUN, RUN, '01', '01'),
        ]:
            with self.subTest(context=context), self.assertRaises(ValueError):
                validate_plan(*context)

    def test_only_publication_requires_exact_writer_or_existing_stable_version(self):
        validate_delivery(STABLE, 'v1.2.3', SHA, SHA, 'push', STABLE, SHA)
        validate_delivery(STABLE, 'v1.2.3', SHA, SHA, 'workflow_dispatch', '', '')
        for context in [
            (PR, '', SHA, SHA, 'pull_request', '', ''),
            (MAIN_PREVIEW, 'v1.2.4', SHA, SHA, 'push', '1.2.4', SHA),
            (STABLE, '', SHA, SHA, 'push', STABLE, SHA),
            (STABLE, 'v1.2.4', SHA, SHA, 'push', '1.2.4', SHA),
            (STABLE, 'v1.2.3', SHA, SHA, 'push', STABLE, OTHER),
            (STABLE, 'v1.2.3', SHA, SHA, 'workflow_dispatch', STABLE, SHA),
            (STABLE, 'v1.2.3', SHA, OTHER, 'workflow_dispatch', '', ''),
        ]:
            with self.subTest(context=context), self.assertRaises(ValueError):
                validate_delivery(*context)

    def test_fully_qualified_current_public_release_rejects_bare_tag_and_stale_main(self):
        tag = 'v1.2.3'
        ref = f'refs/tags/{tag}'
        public = {'tag_name': tag, 'draft': False, 'prerelease': False,
                  'published_at': '2026-11-21T20:00:00Z'}

        def check(refs=f'{SHA}\t{ref}\n', release=public, current=SHA):
            def command(args, **kwargs):
                self.assertEqual(kwargs, {'text': True, 'timeout': 30})
                if args[-1] == 'refs/heads/main':
                    return f'{current}\trefs/heads/main\n'
                if args[0] == 'git':
                    self.assertEqual(args[-2:], [ref, f'{ref}^{{}}'])
                    self.assertIn('ls-remote', args)
                    return refs
                self.assertEqual(args[:4], ['gh', 'api', '--hostname', 'github.com'])
                self.assertTrue(args[-1].endswith(f'/releases/tags/{tag}'))
                return json.dumps(release)
            verify_existing_release(tag, SHA, command)

        check()
        check(refs=f'{OTHER}\t{ref}\n{SHA}\t{ref}^{{}}\n')
        with self.assertRaisesRegex(ValueError, 'exact publisher commit'):
            check(refs=f'{OTHER}\t{ref}\n')
        with self.assertRaisesRegex(ValueError, 'fully qualified'):
            check(refs=f'{SHA}\trefs/heads/{tag}\n')
        for release in (None, {'tag_name': tag}, dict(public, draft=True), dict(public, published_at=None)):
            with self.subTest(release=release), self.assertRaisesRegex(ValueError, 'published stable release'):
                check(release=release)
        with self.assertRaisesRegex(ValueError, 'no longer current main'):
            check(current=OTHER)


class CommonVersionedBuild(unittest.TestCase):
    def test_same_builder_writes_page_and_seals_exact_version_commit_and_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            content = work / 'content'
            (content / 'docs').mkdir(parents=True)
            (content / 'docs/index.md').write_text('# Docs\n')
            (content / 'docs/directory.json').write_text('{"manuals": [], "projects": []}')
            (content / 'docs/site.json').write_text(json.dumps({
                'pages': [{'source': 'docs/index.md', 'path': 'index.md', 'title': 'Docs',
                           'license': 'CC-BY-4.0'}],
                'directory': 'docs/directory.json',
            }))
            build_lock = json.loads((ROOT / 'content.lock.json').read_text())
            pinned = dict(build_lock, locked_commit=build_lock['commit'], locked_tag=build_lock['tag'],
                          pinned=True, dirty=False)
            calls = []

            def command(*args, **_kwargs):
                return {('git', 'rev-parse', 'HEAD'): SHA,
                        ('git', 'status', '--porcelain', '--untracked-files=normal'): '',
                        ('task', '--list', '--json'): '{"tasks": []}'}[args]

            def render(args, **kwargs):
                calls.append((args, kwargs))
                stage = build_docs.STAGE
                (stage / 'site').mkdir()
                for path in (stage / 'source').iterdir():
                    if path.suffix in {'.json', '.md'}:
                        dest = path.name if path.suffix == '.json' else f'{path.stem}.html'
                        (stage / 'site' / dest).write_bytes(path.read_bytes())

            for name, version in [('pr', PR), ('main-preview', MAIN_PREVIEW), ('main', STABLE), ('retry', STABLE)]:
                with self.subTest(lane=name):
                    stage = work / name / 'stage'
                    site = work / name / 'artifact/site'
                    with patch.dict(os.environ, {'GITHUB_ACTIONS': 'true', 'GITHUB_RUN_ID': RUN,
                                               'GITHUB_RUN_ATTEMPT': '1', 'PUBLISHER_SHA': SHA,
                                               'PUBLISHER_VERSION': version}), \
                         patch.object(build_docs, 'STAGE', stage), patch.object(build_docs, 'SITE', site), \
                         patch.object(build_docs, 'content_identity', return_value=(content, dict(pinned))), \
                         patch.object(build_docs, 'command', side_effect=command), \
                         patch.object(build_docs, 'brand_css', return_value=b'/* fixture */'), \
                         patch.object(build_docs, 'installed_zensical', return_value=('zensical', '0.1.1')), \
                         patch.object(build_docs.subprocess, 'run', side_effect=render):
                        build_docs.main()
                    built = json.loads((site / 'build.json').read_text())
                    self.assertEqual(built['publisher']['version'], version)
                    self.assertEqual(built['publisher']['commit'], SHA)
                    self.assertNotIn('tag', built['publisher'])
                    self.assertIn(f'Docs: {version}', (site / 'index.html').read_text())
                    self.assertIn(f'https://github.com/Living-Proof-Labs/living-proof-labs.github.io/tree/{SHA}',
                                  (site / 'source.html').read_text())
                    seal = artifact('seal', site.parent, build_lock, SHA, RUN, publisher_version=version)
                    outputs = work / f'{name}-outputs'
                    emit_seal_outputs(seal, outputs)
                    self.assertEqual(outputs.read_text(),
                                     f'version={version}\ncommit={SHA}\nrun-id={RUN}\nattempt=1\n')
                    self.assertEqual(seal, json.loads((site.parent / 'site-manifest.json').read_text()))
                    self.assertEqual(json.loads((site.parent / 'site-manifest.json').read_text())
                                     ['publisher_version'], version)
                    artifact('check', site.parent, build_lock, SHA, RUN, publisher_version=version)
                    with self.assertRaisesRegex(ValueError, 'shared plan'):
                        artifact('check', site.parent, build_lock, SHA, RUN, publisher_version='8.9.0')
                    with self.assertRaisesRegex(ValueError, 'run/attempt'):
                        artifact('check', site.parent, build_lock, SHA, RUN, '2', publisher_version=version)
            self.assertEqual(calls, [(['zensical', 'build', '--clean', '-f', '.build/mkdocs.yml'],
                                      {'cwd': ROOT, 'check': True})] * 4)


if __name__ == '__main__':
    unittest.main()
