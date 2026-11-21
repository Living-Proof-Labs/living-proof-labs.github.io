# SPDX-License-Identifier: Apache-2.0
"""Seal/check the same-run site against the reviewed publisher lock and identity.

The deploy job runs this file from its exact trusted publisher SHA, never from
the artifact or the upstream content. Digests detect corruption/substitution;
GitHub's same-run artifact boundary supplies authentication, not these digests.
"""
import hashlib
import json
import os
from pathlib import Path
import stat
import sys

from check_content_pin import lock_errors
from docs_payload import MODE, REPOSITORY, hex_digest, read_json, require
from docs_source import REQUIRED_JOBS, WORKFLOW, positive, verify_evidence

PUBLISHER = 'Living-Proof-Labs/living-proof-labs.github.io'


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True) + '\n').encode()


def check_docs_identity(content):
    require(content.get('mode') == MODE and content.get('repository') == REPOSITORY,
            'unexpected documentation source')
    require(hex_digest(content.get('commit'), 40) and content.get('commit') == content.get('locked_commit')
            and content.get('tag') is None and content.get('locked_tag') is None
            and content.get('pinned') is True and content.get('dirty') is False,
            'invalid documentation identity')
    manifest = content.get('manifest', {})
    require(manifest.get('repository') == REPOSITORY and manifest.get('commit') == content['commit']
            and manifest.get('schema_version') == 1, 'manifest source mismatch')
    require(hashlib.sha256(canonical(manifest)).hexdigest() == content.get('manifest_sha256'),
            'build manifest digest mismatch')
    checks = content.get('source_checks', {})
    require(checks.get('workflow') == WORKFLOW and checks.get('head_sha') == content['commit']
            and hex_digest(checks.get('protected_main'), 40)
            and positive(checks.get('run_id')) and positive(checks.get('run_attempt')),
            'invalid source-check provenance')
    require(checks.get('url') == f'https://github.com/{REPOSITORY}/actions/runs/{checks["run_id"]}',
            'invalid source-check URL')
    jobs = checks.get('jobs', [])
    require([job.get('name') for job in jobs] == list(REQUIRED_JOBS)
            and all(positive(job.get('id')) for job in jobs), 'invalid source-check jobs')


def check_identity(identity, lock, publisher_sha, run_id, run_attempt='1'):
    require(not lock_errors(lock), 'invalid reviewed content lock')
    require(hex_digest(publisher_sha, 40) and isinstance(run_id, str) and run_id.isdecimal()
            and isinstance(run_attempt, str) and run_attempt.isdecimal() and int(run_attempt) > 0,
            'missing publisher/run identity')
    require(identity.get('source_commit') == publisher_sha and identity.get('source_dirty') is False
            and identity.get('publisher', {}).get('repository') == PUBLISHER
            and identity['publisher'].get('commit') == publisher_sha
            and identity['publisher'].get('dirty') is False
            and identity.get('workflow_run') == run_id and identity.get('workflow_attempt') == run_attempt,
            'wrong publisher revision or artifact run/attempt')
    content = identity.get('content', {})
    require(content.get('repository') == lock['repository'] and content.get('pinned') is True
            and content.get('dirty') is False and content.get('commit') == lock['commit']
            and content.get('locked_commit') == lock['commit'], 'artifact content differs from reviewed lock')
    if lock.get('mode') == MODE:
        check_docs_identity(content)
        require(content['manifest_sha256'] == lock['manifest_sha256'], 'artifact uses another payload')
    else:
        require('mode' not in content and content.get('tag') == lock['tag']
                and content.get('locked_tag') == lock['tag'], 'artifact release tag differs from reviewed lock')


def inventory(site):
    require(site.is_dir() and not site.is_symlink(), 'missing or linked artifact site')
    files = {}
    for path in sorted(site.rglob('*')):
        info = path.lstat()
        require(not stat.S_ISLNK(info.st_mode), 'artifact contains a symlink')
        if stat.S_ISDIR(info.st_mode):
            continue
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1,
                'artifact contains a special file or hard link')
        relative = path.relative_to(site).as_posix()
        files[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    require('build.json' in files and 'index.html' in files, 'incomplete artifact site')
    return files


def artifact(action, root, lock, publisher_sha, run_id, run_attempt='1'):
    root = Path(root)
    files = inventory(root / 'site')
    identity = json.loads((root / 'site/build.json').read_text())
    check_identity(identity, lock, publisher_sha, run_id, run_attempt)
    expected = {'publisher_commit': publisher_sha, 'workflow_run': run_id, 'workflow_attempt': run_attempt,
                'content_lock': lock, 'files': files}
    if lock.get('mode') == MODE:
        receipt = root / 'content-provenance.json'
        require(receipt.is_file() and not receipt.is_symlink(), 'missing or linked content provenance')
        raw = receipt.read_bytes()
        proof = read_json(raw)
        require(proof.get('lock') == lock, 'artifact provenance lock mismatch')
        require(verify_evidence(lock['commit'], proof['evidence']) == identity['content']['source_checks'],
                'artifact source-check evidence mismatch')
        expected['content_provenance_sha256'] = hashlib.sha256(raw).hexdigest()
    seal = root / 'site-manifest.json'
    if action == 'seal':
        require(not seal.is_symlink(), 'linked artifact manifest')
        seal.write_bytes(canonical(expected))
    else:
        require(action == 'check' and seal.is_file() and not seal.is_symlink(), 'missing artifact manifest')
        require(seal.read_bytes() == canonical(expected), 'artifact manifest/bytes mismatch')


if __name__ == '__main__':
    require(len(sys.argv) == 3 and sys.argv[1] in {'seal', 'check'},
            'usage: check_artifact.py seal|check ARTIFACT_DIRECTORY')
    lock = json.loads((Path(__file__).resolve().parents[1] / 'content.lock.json').read_text())
    artifact(sys.argv[1], sys.argv[2], lock, os.environ.get('PUBLISHER_SHA') or os.environ['GITHUB_SHA'],
             os.environ['GITHUB_RUN_ID'],
             os.environ['GITHUB_RUN_ATTEMPT'])
