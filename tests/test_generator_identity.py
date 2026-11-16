# SPDX-License-Identifier: Apache-2.0
"""The recorded generator is the Zensical that built the site (proposed in Vera's review of #53)."""
import importlib.metadata
import json
import os
import re
import unittest
from pathlib import Path

SITE = Path(__file__).resolve().parents[1] / 'artifacts/site'


def _generator_identity_runs():
    """A local run without a build may skip. CI must fail instead of skipping."""
    if os.environ.get('GITHUB_ACTIONS') == 'true':
        return True
    return (SITE / 'build.json').is_file()


@unittest.skipUnless(_generator_identity_runs(), 'build the site first (task build)')
class GeneratorIdentity(unittest.TestCase):
    def test_build_json_source_page_and_html_name_the_installed_zensical(self):
        version = importlib.metadata.version('zensical')
        identity = json.loads((SITE / 'build.json').read_text())
        self.assertEqual(identity['generator'], f'zensical=={version}')
        self.assertIn(f'Zensical {version}', (SITE / 'source.html').read_text())
        meta = re.search(r'<meta name="generator" content="zensical-([^"]+)">',
                         (SITE / 'index.html').read_text())
        self.assertEqual(meta and meta.group(1), version)


if __name__ == '__main__':
    unittest.main()
