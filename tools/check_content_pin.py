# SPDX-License-Identifier: Apache-2.0
"""Verify the explicit released-tag or documentation-only content lock.

Usage: check_content_pin.py [CONTENT_GIT_DIR]. The directory must be a clone of the
content repository; `main` and the pinned tag are fetched from CONTENT_URL (default: GitHub)
unless CONTENT_MAIN_REF names an existing ref to test against instead.
Those overrides apply only to legacy tag mode. Documentation mode revalidates
the staged manifest and canonical GitHub exact-main documentation-job evidence.
"""
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
CONTENT_REPOSITORY = 'Living-Proof-Labs/.github'
TAG_PATTERN = re.compile(r'^v(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)$')
COMMIT_PATTERN = re.compile(r'^[0-9a-f]{40}$')
EXPECTED_KEYS = {'repository', 'tag', 'commit'}


def reachable(repo, commit, main_ref):
    return subprocess.run(['git', 'merge-base', '--is-ancestor', commit, main_ref],
                          cwd=repo).returncode == 0


def tag_commit(repo, tag):
    """Return the commit SHA that refs/tags/<tag> resolves to in repo, or None."""
    if not isinstance(tag, str) or not TAG_PATTERN.fullmatch(tag):
        return None
    result = subprocess.run(
        ['git', 'rev-parse', '--verify', '--quiet', f'refs/tags/{tag}^{{commit}}'],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def repository_error(lock):
    """Why the lock's repository is not the content repository, or None."""
    repo = lock.get('repository') if isinstance(lock, dict) else None
    if repo != CONTENT_REPOSITORY:
        return (f'FAIL: content.lock.json pins {repo!r}; '
                f'only {CONTENT_REPOSITORY} content may be published')
    return None


def lock_errors(lock):
    """Return validation errors for content.lock.json, or an empty list."""
    if not isinstance(lock, dict):
        return ['FAIL: content.lock.json must be a JSON object']
    if 'mode' in lock:
        from docs_payload import validate_lock
        try:
            validate_lock(lock)
        except ValueError as error:
            return [f'FAIL: {error}']
        return []
    errors = []
    repo_error = repository_error(lock)
    if repo_error:
        errors.append(repo_error)
    extra = sorted(set(lock) - EXPECTED_KEYS)
    if extra:
        errors.append(
            f'FAIL: content.lock.json has unsupported field(s) {", ".join(extra)}; '
            'pin a released tag with repository, tag, and commit'
        )
    tag = lock.get('tag')
    if not isinstance(tag, str) or not TAG_PATTERN.fullmatch(tag):
        errors.append(
            f'FAIL: content.lock.json tag {tag!r} must be a published vX.Y.Z release tag, '
            'not a branch or bare commit'
        )
    commit = lock.get('commit')
    if not isinstance(commit, str) or not COMMIT_PATTERN.fullmatch(commit):
        errors.append(
            f'FAIL: content.lock.json commit {commit!r} must be a full 40-character commit'
        )
    return errors


def main(argv, root=ROOT):
    lock = json.loads((root / 'content.lock.json').read_text())
    errors = lock_errors(lock)
    if errors:
        for error in errors:
            print(error)
        return 1
    repo = Path(argv[1] if len(argv) > 1 else os.environ.get('CONTENT_DIR') or root / '.content')
    if lock.get('mode') == 'documentation-v1':
        from docs_source import projection_identity, source_evidence
        identity = projection_identity(lock, repo)
        evidence = source_evidence(lock['commit'])
        from docs_source import verify_evidence
        if verify_evidence(lock['commit'], evidence) != identity['source_checks']:
            raise SystemExit('FAIL: source verification changed; reacquire the documentation payload')
        print(f'{lock["repository"]}@{lock["commit"]}: docs payload and source checks verified')
        return 0
    main_ref = os.environ.get('CONTENT_MAIN_REF')
    if not main_ref:
        url = os.environ.get('CONTENT_URL') or f'https://github.com/{lock["repository"]}.git'
        subprocess.run(['git', 'fetch', '-q', url, '+refs/heads/main:refs/remotes/pin-check/main'],
                       cwd=repo, check=True)
        tag_ref = f'refs/tags/{lock["tag"]}'
        fetched = subprocess.run(['git', 'fetch', '-q', url, f'+{tag_ref}:{tag_ref}'], cwd=repo)
        if fetched.returncode != 0:
            print(f'FAIL: {lock["repository"]} has no published tag {lock["tag"]}')
            return 1
        main_ref = 'refs/remotes/pin-check/main'
    resolved = tag_commit(repo, lock['tag'])
    if not resolved:
        print(f'FAIL: {lock["tag"]} is not a tag in {repo}; pin a published release tag, not a branch')
        return 1
    if resolved != lock['commit']:
        print(f'FAIL: tag {lock["tag"]} resolves to {resolved}, content.lock.json pins {lock["commit"]}')
        return 1
    if not reachable(repo, lock['commit'], main_ref):
        print(f'FAIL: {lock["repository"]}@{lock["commit"]} is not reachable from main; '
              'pin a merged .github commit')
        return 1
    print(f'{lock["repository"]}@{lock["tag"]} ({lock["commit"][:12]}) is reachable from main')
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
