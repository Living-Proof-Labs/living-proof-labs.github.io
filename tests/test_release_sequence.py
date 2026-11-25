# SPDX-License-Identifier: Apache-2.0
"""Two main runs: an overtaken release, then a newer chore or fix.

The shared rules publish a patch for both fix and chore. Main runs must be
serialized so the newer candidate plans only after the older tag exists.
Otherwise the newer writer is sealed at the old version and fails closed,
and the older deploy skips because it is no longer main.
"""
from pathlib import Path
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github' / 'workflows' / 'docs.yml'
OLDER = '93875e2096ac60895ac23b61920cf9c037fbccd7'
NEWER = 'ce99e6e595000000000000000000000000000001'
PATCH = ('fix', 'chore', 'perf', 'docs', 'build', 'ci', 'test', 'refactor', 'style', 'revert')


def workflow():
    return yaml.safe_load(WORKFLOW.read_text())


def main_runs_are_serialized(spec=None) -> bool:
    spec = workflow() if spec is None else spec
    group = (spec.get('concurrency') or {}).get('group', '')
    queued = (spec.get('concurrency') or {}).get('cancel-in-progress')
    return 'refs/heads/main' in group and 'main-publication' in group and queued is False


def _kind(message: str) -> str | None:
    word = message.split(':', 1)[0].split('(', 1)[0].strip()
    if word == 'feat':
        return 'minor'
    if word in PATCH:
        return 'patch'
    return None


def _bump(base: str, kind: str | None) -> str | None:
    if kind is None:
        return None
    major, minor, patch = (int(part) for part in base.split('.'))
    if kind == 'major':
        return f'{major + 1}.0.0'
    if kind == 'minor':
        return f'{major}.{minor + 1}.0'
    return f'{major}.{minor}.{patch + 1}'


def publish_pair(older: str, newer: str, *, serialized: bool) -> dict:
    """Return the publication outcome for two commits after v1.0.7."""
    if not serialized:
        # Both candidates plan before either tag exists: one patch at each head.
        # The older writer then tags 1.0.8. The newer plan no longer matches.
        return {'failed': True, 'deployed': None, 'tag': ('1.0.8', OLDER)}
    first = _bump('1.0.7', _kind(older))
    second = _bump(first, _kind(newer))
    if second is None:
        return {'failed': False, 'deployed': None, 'tag': (first, OLDER)}
    return {'failed': False, 'deployed': (second, NEWER), 'tag': (first, OLDER)}


class ReleaseSequence(unittest.TestCase):
    def test_chore_after_an_overtaken_fix_deploys_the_release(self) -> None:
        outcome = publish_pair('fix: send the token only to the source API',
                                'chore(deps): update the guidelines pin',
                                serialized=main_runs_are_serialized())
        self.assertFalse(outcome['failed'])
        self.assertEqual(outcome['tag'], ('1.0.8', OLDER))
        version, commit = outcome['deployed']
        self.assertEqual((version, commit), ('1.0.9', NEWER))

    def test_fix_after_an_overtaken_fix_deploys_without_a_red_run(self) -> None:
        outcome = publish_pair('fix: send the token only to the source API',
                                'fix: show release tags in the footer',
                                serialized=main_runs_are_serialized())
        self.assertFalse(outcome['failed'])
        self.assertEqual(outcome['tag'], ('1.0.8', OLDER))
        self.assertEqual(outcome['deployed'], ('1.0.9', NEWER))


if __name__ == '__main__':
    unittest.main()
