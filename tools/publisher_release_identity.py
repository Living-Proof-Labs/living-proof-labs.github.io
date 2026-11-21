# SPDX-License-Identifier: Apache-2.0
"""Bind one shared build plan, then independently gate publisher delivery."""
import json
import os
import re
import subprocess
import sys

PUBLISHER = 'Living-Proof-Labs/living-proof-labs.github.io'
ORIGIN = f'https://github.com/{PUBLISHER}.git'
NUMBER = r'(?:0|[1-9][0-9]*)'
STABLE = re.compile(rf'{NUMBER}\.{NUMBER}\.{NUMBER}')
VERSION = re.compile(rf'{STABLE.pattern}(?:-(?:pr\.[1-9][0-9]*|main)\.[1-9][0-9]*\.[1-9][0-9]*)?')
COMMIT = re.compile(r'[0-9a-f]{40}')


def validate_version(version):
    if not isinstance(version, str) or len(version) > 256 or not VERSION.fullmatch(version):
        raise ValueError('missing or invalid shared publisher build version')
    return version


def validate_plan(version, planned_sha, expected_sha, checkout_sha, planned_run, expected_run,
                  planned_attempt, expected_attempt):
    validate_version(version)
    if not COMMIT.fullmatch(planned_sha) or planned_sha != expected_sha or planned_sha != checkout_sha:
        raise ValueError('shared plan does not name the exact publisher checkout')
    if (not re.fullmatch(r'[1-9][0-9]*', expected_run) or not re.fullmatch(r'[1-9][0-9]*', expected_attempt)
            or (planned_run, planned_attempt) != (expected_run, expected_attempt)):
        raise ValueError('shared plan is from another run or attempt; rerun all jobs')


def validate_delivery(version, tag, expected_sha, checkout_sha, event, release_version, release_sha):
    if not STABLE.fullmatch(version) or tag != f'v{version}':
        raise ValueError('published tag must match the sealed stable version')
    if not COMMIT.fullmatch(expected_sha) or checkout_sha != expected_sha:
        raise ValueError('publication checkout does not match the exact publisher source')
    if event == 'push':
        if (release_version, release_sha) != (version, expected_sha):
            raise ValueError('writer version or commit differs from the verified publisher build')
    elif event != 'workflow_dispatch' or release_version or release_sha:
        raise ValueError('delivery retry must not invoke the release writer')


def verify_existing_release(tag, commit, command=subprocess.check_output):
    """Read only canonical refs and the exact public release; never create a tag."""
    ref = f'refs/tags/{tag}'
    peeled = f'{ref}^{{}}'
    args = ['git', '-c', 'credential.helper=', 'ls-remote', '--exit-code', ORIGIN]
    refs = {}
    for line in command([*args, ref, peeled], text=True, timeout=30).splitlines():
        sha, name = line.split('\t')
        if name not in {ref, peeled} or name in refs or not COMMIT.fullmatch(sha):
            raise ValueError('unexpected response for fully qualified release tag')
        refs[name] = sha
    if ref not in refs or refs.get(peeled, refs[ref]) != commit:
        raise ValueError('published tag does not resolve to the exact publisher commit')
    release = json.loads(command(
        ['gh', 'api', '--hostname', 'github.com', f'repos/{PUBLISHER}/releases/tags/{tag}'],
        text=True, timeout=30,
    ))
    if (not isinstance(release, dict) or release.get('tag_name') != tag or release.get('draft') is not False
            or release.get('prerelease') is not False or not isinstance(release.get('published_at'), str)
            or not release['published_at'].strip()):
        raise ValueError('tag has no matching published stable release')
    if command([*args, 'refs/heads/main'], text=True, timeout=30).strip() != f'{commit}\trefs/heads/main':
        raise ValueError('publication source is no longer current main')


def main():
    env = os.environ
    sha = env['PUBLISHER_SHA']
    version = env['PUBLISHER_VERSION']
    checkout = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    if sys.argv[1:] == ['check-plan']:
        validate_plan(version, sha, env['EXPECTED_PUBLISHER_SHA'], checkout,
                      env['PLAN_RUN_ID'], env['GITHUB_RUN_ID'], env['PLAN_RUN_ATTEMPT'], env['GITHUB_RUN_ATTEMPT'])
    elif sys.argv[1:] == ['check-release']:
        if env['GITHUB_REPOSITORY'] != PUBLISHER or env['GITHUB_REF'] != 'refs/heads/main' or env['GITHUB_SHA'] != sha:
            raise ValueError('production publication requires this repository and exact main')
        tag = env['PUBLISHER_TAG']
        validate_delivery(version, tag, sha, checkout, env['GITHUB_EVENT_NAME'],
                          env.get('RELEASE_VERSION', ''), env.get('RELEASE_COMMIT', ''))
        verify_existing_release(tag, sha)
    else:
        raise ValueError('expected check-plan or check-release')


if __name__ == '__main__':
    main()
