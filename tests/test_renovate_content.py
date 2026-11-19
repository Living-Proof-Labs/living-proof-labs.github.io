# SPDX-License-Identifier: Apache-2.0
"""Exercise the committed Renovate pattern against real and future content locks."""
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


class RenovateContent(unittest.TestCase):
    def setUp(self):
        config = json.loads((ROOT / 'renovate.json').read_text())
        self.assertIn('custom.regex', config['enabledManagers'])
        managers = [m for m in config['customManagers']
                    if m.get('datasourceTemplate') == 'github-tags']
        self.assertEqual(len(managers), 1)
        self.manager = managers[0]
        self.assertEqual(self.manager['customType'], 'regex')
        self.assertEqual(self.manager['versioningTemplate'], 'semver')
        self.assertEqual(self.manager['managerFilePatterns'],
                         [r'/^content\.lock\.json$/'])
        self.assertEqual(len(self.manager['matchStrings']), 1)
        # Python and RE2 share this pattern's syntax except named capture groups.
        pattern = self.manager['matchStrings'][0]
        self.pattern = re.compile(pattern.replace('(?<', '(?P<'))

    def extract(self, text):
        matches = list(self.pattern.finditer(text))
        self.assertEqual(len(matches), 1)
        return matches[0]

    def test_extracts_committed_tag_and_full_digest(self):
        text = (ROOT / 'content.lock.json').read_text()
        lock = json.loads(text)
        self.assertEqual(self.extract(text).groupdict(), {
            'depName': lock['repository'], 'currentValue': lock['tag'],
            'currentDigest': lock['commit'],
        })

    def test_next_release_updates_both_fields_and_is_detected_again(self):
        text = (ROOT / 'content.lock.json').read_text()
        match = self.extract(text)
        # Renovate replaces the named currentValue/currentDigest captures.
        updates = [('currentValue', 'v1.2.0'), ('currentDigest', 'a' * 40)]
        for group, value in sorted(updates, key=lambda x: match.start(x[0]), reverse=True):
            start, end = match.span(group)
            text = text[:start] + value + text[end:]
        lock = json.loads(text)
        self.assertEqual(lock, {'repository': 'Living-Proof-Labs/.github',
                               'tag': 'v1.2.0', 'commit': 'a' * 40})
        for formatted in (text, json.dumps(lock)):
            captures = self.extract(formatted).groupdict()
            self.assertEqual(captures['currentValue'], 'v1.2.0')
            self.assertEqual(captures['currentDigest'], 'a' * 40)

    def test_rejects_branch_short_digest_and_other_repository(self):
        lock = json.loads((ROOT / 'content.lock.json').read_text())
        for field, value in [('tag', 'main'), ('commit', '53f55dd'),
                             ('repository', 'Living-Proof-Labs/other')]:
            with self.subTest(field=field):
                self.assertIsNone(self.pattern.search(json.dumps({**lock, field: value})))


if __name__ == '__main__':
    unittest.main()
