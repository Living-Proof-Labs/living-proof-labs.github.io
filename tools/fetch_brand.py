# SPDX-License-Identifier: Apache-2.0
"""Fetch the docs brand pinned in docs-brand.lock.json into .brand/ (needs network).

Run before the offline build: the lock's commit must be what its release tag points at, and
the file's sha256 must match the lock. build_docs.py reads the staged copy through
DOCS_BRAND_FILE and checks the digest again, so the build itself never needs network access.
"""
import hashlib
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / '.brand/brand.css'


def tag_commit(pin):
    url = f"https://github.com/{pin['repository']}.git"
    ref = f"refs/tags/{pin['version']}"
    out = subprocess.check_output(
        ['git', '-c', 'credential.helper=', 'ls-remote', '--exit-code', url, ref, f'{ref}^{{}}'],
        text=True,
        timeout=30,
        env={'GIT_TERMINAL_PROMPT': '0', 'PATH': '/usr/bin:/bin:/usr/local/bin'},
    )
    refs = dict(reversed(line.split('\t')) for line in out.splitlines())
    return refs.get(f'{ref}^{{}}', refs[ref])


def main():
    pin = json.loads((ROOT / 'docs-brand.lock.json').read_text())
    commit = tag_commit(pin)
    if commit != pin['commit']:
        sys.exit(f"Docs brand tag {pin['version']} is {commit}, lock pins {pin['commit']}")
    url = f"https://raw.githubusercontent.com/{pin['repository']}/{pin['commit']}/{pin['path']}"
    with urllib.request.urlopen(url, timeout=30) as response:
        data = response.read()
    digest = hashlib.sha256(data).hexdigest()
    if digest != pin['sha256']:
        sys.exit(f"Docs brand {pin['version']} sha256 is {digest}, pinned {pin['sha256']}")
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_bytes(data)
    print(f"Docs brand {pin['version']} ({pin['commit'][:12]}) sha256 {digest} -> {OUT.relative_to(ROOT)}")


if __name__ == '__main__':
    main()
