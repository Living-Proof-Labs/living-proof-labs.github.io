# SPDX-License-Identifier: Apache-2.0
"""Footer identity renders release tags or 'commit' with no commit SHAs in visible text."""
import contextlib
import html
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / 'artifacts' / 'site'
sys.path.insert(0, str(ROOT / 'tools'))
import build_docs  # noqa: E402
from check_site import COMMIT_ID, Page, main as check_site  # noqa: E402


def git(repo, *args):
    return subprocess.check_output(
        ['git', '-c', 'user.name=t', '-c', 'user.email=t@t', *args],
        cwd=repo,
        text=True,
    ).strip()


def make_publisher_fixture(root, content_repo, lock):
    (root / 'LICENSES').mkdir()
    (root / 'LICENSES' / 'CC-BY-4.0.txt').write_text('CC-BY-4.0\n')
    (root / 'LICENSE.md').write_text('# License\n\nApache-2.0\n')
    (root / 'Taskfile.yml').write_text(
        "version: '3'\ntasks:\n  setup:\n    desc: Setup\n    cmds:\n      - echo ok\n"
    )
    shutil.copytree(ROOT / 'docs', root / 'docs')
    (root / 'content.lock.json').write_text(json.dumps(lock))
    (root / 'docs-brand.lock.json').write_text((ROOT / 'docs-brand.lock.json').read_text())
    git(root, 'init', '-q', '-b', 'main')
    git(root, 'add', '.')
    git(root, 'commit', '-q', '-m', 'publisher fixture')
    return git(root, 'rev-parse', 'HEAD')


def make_content_fixture(repo, *, tag='v1.1.1'):
    (repo / 'docs' / 'architecture').mkdir(parents=True)
    site_json = {
        'pages': [
            {'source': 'docs/index.md', 'path': 'index.md', 'title': 'Start here', 'license': 'CC-BY-4.0'},
            {
                'source': 'docs/architecture/verification-architecture.md',
                'path': 'architecture/verification-architecture.md',
                'title': 'Verification architecture',
                'license': 'CC-BY-4.0',
            },
        ],
        'directory': 'docs/directory.json',
        'redirects': {'architecture.html': 'architecture/verification-architecture.html'},
    }
    (repo / 'docs' / 'site.json').write_text(json.dumps(site_json))
    (repo / 'docs' / 'directory.json').write_text(json.dumps({'manuals': [], 'projects': []}))
    (repo / 'docs' / 'index.md').write_text(
        '# Living Proof Labs documentation\n\n'
        'See [Verification architecture](architecture/verification-architecture.md).\n'
    )
    (repo / 'docs' / 'architecture' / 'verification-architecture.md').write_text(
        '# Verification architecture\n\nOverview.\n'
    )
    git(repo, 'init', '-q', '-b', 'main')
    git(repo, 'add', '.')
    git(repo, 'commit', '-q', '-m', 'content fixture')
    commit = git(repo, 'rev-parse', 'HEAD')
    if tag:
        git(repo, 'tag', tag, commit)
    return commit


class BuiltFooterIdentity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (SITE / 'index.html').is_file() or not (SITE / 'build.json').is_file():
            raise AssertionError('Missing built site; run task build first')

    def test_built_pages_footer_shows_tags_only_with_full_shas_in_href_or_title(self):
        identity = json.loads((SITE / 'build.json').read_text())
        content = identity['content']
        publisher = identity['publisher']
        expected_content = content['tag'] if content.get('tag') else 'commit'
        expected_publisher = publisher['tag'] if publisher.get('tag') else 'commit'
        expected = f'Docs: development · content {expected_content} · publisher {expected_publisher}'

        for name in sorted(set(identity['pages']) | {'source.html'}):
            with self.subTest(page=name):
                page = Page((SITE / name).read_text())
                self.assertTrue(page.identity_found, f'{name} missing .docs-identity')
                self.assertIn(expected, page.identity_text)
                self.assertEqual(COMMIT_ID.findall(page.identity_text), [], page.identity_text)
                self.assertNotIn(content['commit'][:7], page.identity_text)
                self.assertNotIn(publisher['commit'][:7], page.identity_text)
                attr_blob = ' '.join(page.identity_attrs)
                self.assertIn(content['commit'], attr_blob)
                self.assertIn(publisher['commit'], attr_blob)

        flags = (
            (' · local changes' if identity.get('source_dirty') else '')
            + ('' if content.get('pinned') else ' · content not at pinned revision')
        )
        source_html = (SITE / 'source.html').read_text()
        summary = re.search(r'<p><strong>(Docs:.*?)</strong></p>', source_html)
        self.assertIsNotNone(summary)
        summary_text = html.unescape(summary.group(1))
        self.assertEqual(summary_text, expected + flags)
        self.assertEqual(COMMIT_ID.findall(summary_text), [])

    def test_check_site_rejects_short_sha_in_footer_visible_text(self):
        identity = json.loads((SITE / 'build.json').read_text())
        content_short = identity['content']['commit'][:7]
        publisher_short = identity['publisher']['commit'][:7]
        with tempfile.TemporaryDirectory() as tmp:
            site = Path(tmp) / 'site'
            shutil.copytree(SITE, site)
            index = site / 'index.html'
            original = index.read_text()
            old_footer = (
                f'Docs: development · content {identity["content"]["tag"]} '
                f'({content_short}) · publisher {publisher_short}'
            )
            mutated = re.sub(
                r'<div class="docs-identity">.*?</div>',
                f'<div class="docs-identity"><p><a href="https://github.com/Living-Proof-Labs/.github">{old_footer}</a></p></div>',
                original,
                count=1,
                flags=re.S,
            )
            self.assertNotEqual(mutated, original)
            index.write_text(mutated)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                failed = check_site([str(site)])
        self.assertTrue(failed, output.getvalue())
        self.assertIn('Invalid or inconsistent build identity', output.getvalue())


class PublisherReleaseTag(unittest.TestCase):
    def test_release_tag_selection_and_dirty_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            git(repo, 'init', '-q', '-b', 'main')
            git(repo, 'commit', '-q', '--allow-empty', '-m', 'one')
            self.assertIsNone(build_docs.publisher_release_tag(repo))

            git(repo, 'tag', 'preview')
            self.assertIsNone(build_docs.publisher_release_tag(repo))

            git(repo, 'tag', 'v1.2.0')
            self.assertEqual(build_docs.publisher_release_tag(repo), 'v1.2.0')

            git(repo, 'tag', 'v1.10.0')
            self.assertEqual(build_docs.publisher_release_tag(repo), 'v1.10.0')
            self.assertIsNone(build_docs.publisher_release_tag(repo, dirty=True))

            git(repo, 'commit', '-q', '--allow-empty', '-m', 'two')
            self.assertIsNone(build_docs.publisher_release_tag(repo))


class SyntheticFooterBuild(unittest.TestCase):
    def _build_fixture(self, *, content_tagged, publisher_tag):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            content_repo = base / 'content'
            content_repo.mkdir()
            content_commit = make_content_fixture(content_repo, tag='v1.1.1' if content_tagged else None)
            lock = {
                'repository': 'Living-Proof-Labs/.github',
                'tag': 'v1.1.1',
                'commit': content_commit,
            }
            pub_repo = base / 'publisher'
            pub_repo.mkdir()
            pub_commit = make_publisher_fixture(pub_repo, content_repo, lock)
            if publisher_tag:
                git(pub_repo, 'tag', publisher_tag, pub_commit)
            with mock.patch.object(build_docs, 'ROOT', pub_repo), \
                 mock.patch.object(build_docs, 'STAGE', pub_repo / '.build'), \
                 mock.patch.object(build_docs, 'SITE', pub_repo / 'artifacts/site'), \
                 mock.patch.object(build_docs, 'LOCK', pub_repo / 'content.lock.json'), \
                 mock.patch.object(build_docs, 'BRAND_LOCK', pub_repo / 'docs-brand.lock.json'), \
                 mock.patch.object(build_docs, 'brand_css', return_value=b'/* brand */\n'), \
                 mock.patch.dict(os.environ, {'CONTENT_DIR': str(content_repo), 'GITHUB_ACTIONS': 'false'}):
                build_docs.main()
            site = pub_repo / 'artifacts/site'
            build_json = json.loads((site / 'build.json').read_text())
            index_page = Page((site / 'index.html').read_text())
            tasks_page = Page((site / 'tasks.html').read_text())
            source_html = (site / 'source.html').read_text()
            return build_json, content_commit, pub_commit, index_page, tasks_page, source_html

    def test_tagged_content_and_tagged_publisher(self):
        build_json, content_sha, pub_sha, index_page, tasks_page, source_html = self._build_fixture(
            content_tagged=True, publisher_tag='v2.3.4'
        )
        self.assertEqual(build_json['publisher']['tag'], 'v2.3.4')
        expected = 'Docs: development · content v1.1.1 · publisher v2.3.4'
        for page in (index_page, tasks_page):
            self.assertIn(expected, page.identity_text)
            self.assertEqual(COMMIT_ID.findall(page.identity_text), [], page.identity_text)
            attrs = ' '.join(page.identity_attrs)
            self.assertIn(content_sha, attrs)
            self.assertIn(pub_sha, attrs)
            self.assertIn('releases/tag/v2.3.4', attrs)
        self.assertIn(f'<strong>{expected}</strong>', source_html)

    def test_tagged_content_and_untagged_publisher(self):
        build_json, content_sha, pub_sha, index_page, tasks_page, _ = self._build_fixture(
            content_tagged=True, publisher_tag=None
        )
        self.assertIsNone(build_json['publisher']['tag'])
        expected = 'Docs: development · content v1.1.1 · publisher commit'
        for page in (index_page, tasks_page):
            self.assertIn(expected, page.identity_text)
            self.assertEqual(COMMIT_ID.findall(page.identity_text), [], page.identity_text)
            attrs = ' '.join(page.identity_attrs)
            self.assertIn(content_sha, attrs)
            self.assertIn(pub_sha, attrs)

    def test_untagged_content_and_untagged_publisher(self):
        build_json, content_sha, pub_sha, index_page, tasks_page, _ = self._build_fixture(
            content_tagged=False, publisher_tag=None
        )
        self.assertIsNone(build_json['content']['tag'])
        self.assertIsNone(build_json['publisher']['tag'])
        expected = 'Docs: development · content commit · publisher commit · content not at pinned revision'
        for page in (index_page, tasks_page):
            self.assertIn(expected, page.identity_text)
            self.assertEqual(COMMIT_ID.findall(page.identity_text), [], page.identity_text)
            attrs = ' '.join(page.identity_attrs)
            self.assertIn(content_sha, attrs)
            self.assertIn(pub_sha, attrs)


if __name__ == '__main__':
    unittest.main()
