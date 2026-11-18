# SPDX-License-Identifier: Apache-2.0
"""Fetch the pinned .github content release tag into .content (or CONTENT_DIR)."""
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_content_pin import lock_errors, tag_commit  # noqa: E402


def git(*args, cwd):
    subprocess.run(['git', *args], cwd=cwd, check=True)


def main():
    lock = json.loads((ROOT / 'content.lock.json').read_text())
    errors = lock_errors(lock)
    if errors:
        raise SystemExit('\n'.join(errors))
    target = Path(os.environ.get('CONTENT_DIR') or ROOT / '.content')
    url = os.environ.get('CONTENT_URL') or f'https://github.com/{lock["repository"]}.git'
    target.mkdir(parents=True, exist_ok=True)
    if not (target / '.git').exists():
        git('init', '-q', cwd=target)
    ref = f'refs/tags/{lock["tag"]}'
    git('fetch', '-q', '--depth', '1', '--force', url, f'{ref}:{ref}', cwd=target)
    resolved = tag_commit(target, lock['tag'])
    if resolved != lock['commit']:
        raise SystemExit(
            f'FAIL: {lock["repository"]} tag {lock["tag"]} resolves to {resolved}, '
            f'content.lock.json pins {lock["commit"]}'
        )
    git('checkout', '-q', '--detach', lock['commit'], cwd=target)
    print(f'{lock["repository"]}@{lock["tag"]} ({lock["commit"]}) in {target}')


if __name__ == '__main__':
    main()
