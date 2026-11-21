# SPDX-License-Identifier: Apache-2.0
"""Acquire a docs-only projection through the canonical GitHub API, never checkout/code.

Transport evidence comes only from TLS-authenticated api.github.com responses.
The offline receipt is reviewable evidence, not a signature or a replacement for
that acquisition step. CI always reacquires it before the offline build.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from docs_payload import (MODE, REPOSITORY, MAX_FILES, MAX_FILE_BYTES, MAX_PAYLOAD_BYTES, MAX_TEXT_BYTES,
                          hex_digest, payload_manifest, read_json, require, safe_path,
                          validate_lock, validate_site, verify_payload)

WORKFLOW = '.github/workflows/verify.yml'
REQUIRED_JOBS = ('Repository directory tests', 'Organization docs preview (publisher build and checks)')
RECEIPT = '.docs-provenance.json'
MANIFEST = '.docs-manifest.json'
PREFIX = f'repos/{REPOSITORY}'


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('source API redirect refused')


def api(path, limit=4 * 1024 * 1024):
    require(path.startswith(PREFIX + '/'), 'unexpected source API origin')
    headers = {'Accept': 'application/vnd.github+json', 'User-Agent': 'Living-Proof-Labs-docs-publisher',
               'X-GitHub-Api-Version': '2022-11-28'}
    # Public canonical source: never forward the publisher's repository token.
    with build_opener(NoRedirect).open(Request('https://api.github.com/' + path, headers=headers),
                                         timeout=30) as response:
        data = response.read(limit + 1)
    require(len(data) <= limit, 'source API response exceeds limit')
    return json.loads(data)


def positive(value):
    return type(value) is int and value > 0


def verify_evidence(commit, evidence):
    """Validate API evidence, including attempt identity, not aggregate conclusion."""
    require(isinstance(evidence, dict) and set(evidence) == {'branch', 'comparison', 'run', 'jobs'},
            'missing or unexpected source evidence')
    branch, comparison, run, jobs = (evidence[k] for k in ('branch', 'comparison', 'run', 'jobs'))
    require(branch.get('name') == 'main' and branch.get('protected') is True,
            'source main must be protected')
    main_sha = branch.get('commit', {}).get('sha')
    require(hex_digest(main_sha, 40), 'invalid protected-main identity')
    require(comparison.get('status') in {'ahead', 'identical'}
            and comparison.get('merge_base_commit', {}).get('sha') == commit
            and comparison.get('base_commit', {}).get('sha') == commit,
            'source commit is not an ancestor of protected main')
    require(run.get('head_sha') == commit and run.get('head_branch') == 'main'
            and run.get('event') == 'push' and run.get('path') == WORKFLOW
            and run.get('repository', {}).get('full_name') == REPOSITORY
            and run.get('head_repository', {}).get('full_name') == REPOSITORY,
            'source run must be the canonical exact-main push workflow')
    require(run.get('status') == 'completed' and positive(run.get('id'))
            and positive(run.get('run_attempt')), 'source run incomplete or missing attempt')
    require(run.get('html_url') == f'https://github.com/{REPOSITORY}/actions/runs/{run["id"]}',
            'unexpected source run URL')
    require(isinstance(jobs, list) and len(jobs) <= 100, 'invalid source job evidence')
    for name in REQUIRED_JOBS:
        matches = [job for job in jobs if job.get('name') == name]
        require(len(matches) == 1, f'missing or ambiguous required source job: {name}')
        job = matches[0]
        require(job.get('status') == 'completed' and job.get('conclusion') == 'success'
                and job.get('head_sha') == commit and job.get('run_id') == run['id']
                and job.get('run_attempt') == run['run_attempt'] and positive(job.get('id')),
                f'failed, stale or mismatched required source job: {name}')
    return {'workflow': WORKFLOW, 'run_id': run['id'], 'run_attempt': run['run_attempt'],
            'url': run['html_url'], 'head_sha': commit, 'protected_main': main_sha,
            'jobs': [{'name': name, 'id': next(j['id'] for j in jobs if j['name'] == name)}
                     for name in REQUIRED_JOBS]}


def source_evidence(commit, get=api):
    require(hex_digest(commit, 40), 'source commit must be a full lowercase SHA')
    branch = get(PREFIX + '/branches/main')
    main_sha = branch.get('commit', {}).get('sha')
    require(hex_digest(main_sha, 40), 'invalid protected-main identity')
    comparison = get(PREFIX + f'/compare/{commit}...{main_sha}')
    query = urlencode({'head_sha': commit, 'event': 'push', 'branch': 'main', 'per_page': 100})
    listing = get(PREFIX + '/actions/workflows/verify.yml/runs?' + query)
    runs = listing.get('workflow_runs', [])
    require(0 < listing.get('total_count', 0) == len(runs) <= 100, 'missing or truncated source runs')
    require(all(positive(run.get('id')) for run in runs), 'invalid source run IDs')
    # A failed/incomplete newer run cannot be hidden by an older success.
    run_id = max(run['id'] for run in runs)
    run = get(PREFIX + f'/actions/runs/{run_id}')
    require(run.get('id') == run_id, 'source API returned another run')
    attempt = run.get('run_attempt')
    require(positive(attempt), 'missing source run attempt')
    listing = get(PREFIX + f'/actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100')
    jobs = listing.get('jobs', [])
    require(listing.get('total_count') == len(jobs) <= 100, 'truncated source job evidence')
    evidence = {'branch': branch, 'comparison': comparison, 'run': run, 'jobs': jobs}
    verify_evidence(commit, evidence)
    return evidence


def fetch_blobs(commit, get=api):
    require(hex_digest(commit, 40), 'source commit must be a full lowercase SHA')
    tree = get(PREFIX + f'/git/trees/{commit}?recursive=1')
    require(tree.get('truncated') is False, 'truncated source tree')
    entries = tree.get('tree')
    require(isinstance(entries, list), 'missing source tree')
    index = {entry['path']: entry for entry in entries}
    require(len(index) == len(entries), 'duplicate source tree paths')
    require('docs/media' not in index or index['docs/media'].get('type') == 'tree',
            'media root must be a tree, not a link or submodule')

    def read(path):
        entry = index.get(path, {})
        require(entry.get('type') == 'blob' and entry.get('mode') == '100644'
                and type(entry.get('size')) is int and 0 <= entry['size'] <= MAX_FILE_BYTES
                and hex_digest(entry.get('sha'), 40), 'unsafe or missing source blob: ' + path)
        blob = get(PREFIX + '/git/blobs/' + entry['sha'], limit=MAX_FILE_BYTES * 2)
        require(blob.get('encoding') == 'base64' and blob.get('sha') == entry['sha'],
                'invalid source blob encoding or identity')
        data = base64.b64decode(''.join(blob['content'].split()), validate=True)
        require(len(data) == entry['size'], 'source blob size mismatch')
        git_hash = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
        require(git_hash == entry['sha'], 'source blob object mismatch')
        return ('100644', data)

    site = read('docs/site.json')
    sources = validate_site(read_json(site[1]))
    paths = sources | {'docs/site.json', 'docs/directory.json'}
    # Include every media entry; invalid modes/extensions must fail, not disappear.
    paths |= {path for path, entry in index.items()
              if path.startswith('docs/media/') and entry.get('type') != 'tree'}
    require(len(paths) <= MAX_FILES, 'too many source payload files')
    require(sum(index.get(path, {}).get('size', MAX_PAYLOAD_BYTES + 1) for path in paths)
            <= MAX_PAYLOAD_BYTES, 'source payload exceeds size limit')
    blobs = {'docs/site.json': site}
    for path in sorted(paths - {'docs/site.json'}):
        require(safe_path(path), 'unsafe source path')
        blobs[path] = read(path)
    return blobs


def acquire(lock, target, get=api):
    validate_lock(lock)
    require(not os.environ.get('CONTENT_URL') and not os.environ.get('CONTENT_MAIN_REF'),
            'source overrides are not supported in documentation mode')
    target = Path(target)
    require(not target.exists() and not target.is_symlink(),
            'documentation projection already exists; select a new empty destination')
    evidence = source_evidence(lock['commit'], get)
    blobs = fetch_blobs(lock['commit'], get)
    manifest = verify_payload(lock, blobs)
    # Recheck after payload retrieval: fail on a newly started attempt or run.
    require(source_evidence(lock['commit'], get) == evidence, 'source evidence changed during acquisition')
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix='.docs-payload-', dir=target.parent))
    try:
        for path, (_, data) in blobs.items():
            file = temporary / path
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(data)
        (temporary / MANIFEST).write_bytes(manifest)
        (temporary / RECEIPT).write_text(json.dumps({'lock': lock, 'evidence': evidence}, sort_keys=True) + '\n')
        temporary.rename(target)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def projection_identity(lock, target):
    """Revalidate the exact acquired projection for the offline trusted build."""
    validate_lock(lock)
    target = Path(target)
    require(target.is_dir() and not target.is_symlink(), 'missing or linked projection')
    blobs = {}
    total = 0
    for path in target.rglob('*'):
        require(not path.is_symlink(), 'linked projection entry')
        if path.is_dir():
            continue
        require(path.is_file(), 'non-regular projection entry')
        relative = path.relative_to(target).as_posix()
        require(path.stat().st_size <= MAX_FILE_BYTES, 'projection file exceeds limit')
        if relative in {MANIFEST, RECEIPT}:
            require(path.stat().st_size <= MAX_TEXT_BYTES, 'projection metadata exceeds limit')
            continue
        total += path.stat().st_size
        require(total <= MAX_PAYLOAD_BYTES and len(blobs) < MAX_FILES, 'projection exceeds size limit')
        require(path.stat().st_mode & 0o111 == 0, 'executable projection entry')
        blobs[relative] = ('100644', path.read_bytes())
    manifest = verify_payload(lock, blobs)
    require((target / MANIFEST).read_bytes() == manifest, 'stored manifest differs from payload')
    receipt = read_json((target / RECEIPT).read_bytes())
    require(set(receipt) == {'lock', 'evidence'} and receipt['lock'] == lock, 'receipt lock mismatch')
    checks = verify_evidence(lock['commit'], receipt['evidence'])
    return {'mode': MODE, 'repository': REPOSITORY, 'commit': lock['commit'],
            'locked_commit': lock['commit'], 'tag': None, 'locked_tag': None,
            'manifest_sha256': lock['manifest_sha256'], 'manifest': json.loads(manifest),
            'source_checks': checks, 'pinned': True, 'dirty': False}


def candidate(commit, get=api):
    """Produce review material only; never update the lock or publication state."""
    evidence = source_evidence(commit, get)
    manifest = payload_manifest(commit, fetch_blobs(commit, get))
    require(source_evidence(commit, get) == evidence, 'source evidence changed during acquisition')
    lock = {'mode': MODE, 'repository': REPOSITORY, 'commit': commit,
            'manifest_sha256': hashlib.sha256(manifest).hexdigest()}
    return {'proposed_lock': lock, 'manifest': json.loads(manifest), 'evidence': evidence}


if __name__ == '__main__':
    require(len(sys.argv) == 2, 'usage: docs_source.py FULL_SOURCE_COMMIT (prints review material only)')
    print(json.dumps(candidate(sys.argv[1]), indent=2, sort_keys=True))
