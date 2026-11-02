# SPDX-License-Identifier: Apache-2.0
"""Fail unless the content commit pinned in content.lock.json is reachable from .github main.

Usage: check_content_pin.py [CONTENT_GIT_DIR]. The directory must be a clone of the
content repository; `main` is fetched from CONTENT_URL (default: GitHub) unless
CONTENT_MAIN_REF names an existing ref to test against instead.
"""
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
CONTENT_REPOSITORY = 'Living-Proof-Labs/.github'


def reachable(repo, commit, main_ref):
    return subprocess.run(['git', 'merge-base', '--is-ancestor', commit, main_ref],
                          cwd=repo).returncode == 0


def repository_error(lock):
    """Why the lock's repository is not the content repository, or None."""
    if lock.get('repository') != CONTENT_REPOSITORY:
        return (f'FAIL: content.lock.json pins {lock.get("repository")!r}; '
                f'only {CONTENT_REPOSITORY} content may be published')
    return None


def main(argv, root=ROOT):
    lock = json.loads((root / 'content.lock.json').read_text())
    error = repository_error(lock)
    if error:
        print(error)
        return 1
    repo = Path(argv[1] if len(argv) > 1 else os.environ.get('CONTENT_DIR') or root / '.content')
    main_ref = os.environ.get('CONTENT_MAIN_REF')
    if not main_ref:
        url = os.environ.get('CONTENT_URL') or f'https://github.com/{lock["repository"]}.git'
        subprocess.run(['git', 'fetch', '-q', url, '+refs/heads/main:refs/remotes/pin-check/main'],
                       cwd=repo, check=True)
        main_ref = 'refs/remotes/pin-check/main'
    if not reachable(repo, lock['commit'], main_ref):
        print(f'FAIL: {lock["repository"]}@{lock["commit"]} is not reachable from main; '
              'pin a merged .github commit')
        return 1
    print(f'{lock["repository"]}@{lock["commit"][:12]} is reachable from main')
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
