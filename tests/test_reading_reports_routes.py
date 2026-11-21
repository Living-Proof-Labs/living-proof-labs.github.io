# SPDX-License-Identifier: Apache-2.0
"""The built reader guide uses the site's canonical .html route.

Run after task build, as task verify does. Missing artifacts must fail locally
as well as in CI: skipping when the guide is absent would hide a regression.
Assertions adapted from Vera's proposed patch in issue #67.
"""
import html
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / 'artifacts/site'


class HtmlRoutes(unittest.TestCase):
    def test_publisher_uses_html_filenames_not_directory_urls(self):
        text = (ROOT / 'docs/mkdocs.yml').read_text()
        self.assertRegex(text, r'(?m)^use_directory_urls:\s*false\s*$')

    def test_guide_is_emitted_as_html_with_no_slash_alias(self):
        self.assertTrue((SITE / 'reading-reports.html').is_file(),
                        'Missing reading-reports.html; run task build and check the content manifest')
        self.assertFalse((SITE / 'reading-reports').exists())
        identity = json.loads((SITE / 'build.json').read_text())
        self.assertIn('reading-reports.html', identity['pages'])
        self.assertNotIn('reading-reports/', identity.get('redirects', {}))
        self.assertNotIn('reading-reports/index.html', identity.get('redirects', {}))

    def test_homepage_and_navigation_link_to_html_route(self):
        index = (SITE / 'index.html').read_text()
        self.assertIn('href="reading-reports.html"', index)
        self.assertIn('href="./reading-reports.html"', index)
        self.assertNotRegex(index, r'href="(?:\./)?reading-reports/"')

    def test_repeated_outcome_guidance_and_content_footer(self):
        page = (SITE / 'reading-reports.html').read_text()
        text = ' '.join(html.unescape(re.sub(r'<[^>]+>', ' ', page)).split())
        for phrase in (
            'repeated-outcome@1.0.0', '3 of 3 repeats agree',
            'with no Wilson interval or threshold',
            'applies to corner reports', '21–100%',
        ):
            self.assertIn(phrase, text)
        lock = json.loads((ROOT / 'content.lock.json').read_text())
        short_commit = lock['commit'][:7]
        if lock.get('mode') == 'documentation-v1':
            label = short_commit
        else:
            label = f"{lock['tag']} ({short_commit})"
        self.assertIn(f' · content {label} · publisher ', text)

    def test_guide_canonical_url_is_html_route(self):
        canonical = re.search(r'<link rel="canonical" href="([^"]+)"',
                              (SITE / 'reading-reports.html').read_text())
        self.assertEqual(canonical and canonical.group(1),
                         'https://docs.livingprooflabs.com/reading-reports.html')


if __name__ == '__main__':
    unittest.main()
