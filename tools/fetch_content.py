# SPDX-License-Identifier: Apache-2.0
"""Fetch the pinned .github content commit into .content (or CONTENT_DIR)."""
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def git(*args, cwd):
    subprocess.run(['git', *args], cwd=cwd, check=True)


def main():
    lock = json.loads((ROOT / 'content.lock.json').read_text())
    target = Path(os.environ.get('CONTENT_DIR') or ROOT / '.content')
    url = os.environ.get('CONTENT_URL') or f'https://github.com/{lock["repository"]}.git'
    target.mkdir(parents=True, exist_ok=True)
    if not (target / '.git').exists():
        git('init', '-q', cwd=target)
    git('fetch', '-q', '--depth', '1', url, lock['commit'], cwd=target)
    git('checkout', '-q', '--detach', lock['commit'], cwd=target)
    print(f'{lock["repository"]}@{lock["commit"]} in {target}')


if __name__ == '__main__':
    main()
