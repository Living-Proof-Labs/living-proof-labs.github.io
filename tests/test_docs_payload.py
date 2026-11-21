# SPDX-License-Identifier: Apache-2.0
"""Docs-only payload contract; no network or upstream code execution."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from check_content_pin import lock_errors  # noqa: E402
from docs_payload import payload_manifest, validate_lock, verify_payload  # noqa: E402
import docs_payload  # noqa: E402

COMMIT = 'a' * 40


def fixture():
    site = {
        'schema_version': 1,
        'pages': [{'source': 'docs/index.md', 'path': 'index.md',
                   'title': 'Start here', 'license': 'CC-BY-4.0'}],
        'directory': 'docs/directory.json',
        'redirects': {},
    }
    blobs = {
        'docs/site.json': ('100644', json.dumps(site).encode()),
        'docs/directory.json': ('100644', b'{"schema_version":1,"manuals":[],"projects":[]}\n'),
        'docs/index.md': ('100644', b'# Start here\n'),
    }
    return site, blobs


def pin(blobs):
    return {'mode': 'documentation-v1', 'repository': 'Living-Proof-Labs/.github',
            'commit': COMMIT,
            'manifest_sha256': hashlib.sha256(payload_manifest(COMMIT, blobs)).hexdigest()}


class DocumentationPayload(unittest.TestCase):
    def test_canonical_manifest_is_sorted_and_identifies_exact_raw_bytes(self):
        _, blobs = fixture()
        expected = {
            'schema_version': 1, 'repository': 'Living-Proof-Labs/.github', 'commit': COMMIT,
            'files': [
                {'path': path, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
                for path, data in [
                    ('docs/directory.json', blobs['docs/directory.json'][1]),
                    ('docs/index.md', b'# Start here\n'),
                    ('docs/site.json', blobs['docs/site.json'][1]),
                ]
            ],
        }
        manifest = payload_manifest(COMMIT, blobs)
        self.assertEqual(manifest, (json.dumps(expected, sort_keys=True, separators=(',', ':'))
                                    + '\n').encode())
        self.assertEqual(manifest, payload_manifest(COMMIT, dict(reversed(list(blobs.items())))))
        self.assertEqual(verify_payload(pin(blobs), blobs), manifest)

    def test_byte_changes_and_missing_files_cannot_reuse_reviewed_digest(self):
        _, blobs = fixture()
        lock = pin(blobs)
        changed = copy.deepcopy(blobs)
        changed['docs/index.md'] = ('100644', b'# Start here\r\n')
        with self.assertRaisesRegex(ValueError, 'digest mismatch'):
            verify_payload(lock, changed)
        del changed['docs/index.md']
        with self.assertRaisesRegex(ValueError, 'missing declared content'):
            verify_payload(lock, changed)

    def test_wrong_lock_identity_or_untyped_ref_fails(self):
        _, blobs = fixture()
        lock = pin(blobs)
        for key, value in [('mode', 'release'), ('repository', 'someone/.github'),
                           ('commit', 'main'), ('commit', 'a' * 39), ('commit', 'A' * 40),
                           ('manifest_sha256', 'f' * 63), ('tag', 'v1.1.3'),
                           ('ref', 'refs/heads/main'), ('path', 'docs')]:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                validate_lock(dict(lock, **{key: value}))
        for field in lock:
            missing = dict(lock)
            del missing[field]
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_lock(missing)
        with self.assertRaisesRegex(ValueError, 'digest mismatch'):
            verify_payload(dict(lock, commit='b' * 40), blobs)

    def test_policy_workflow_and_executable_payloads_fail(self):
        _, blobs = fixture()
        for path in ['.github/workflows/verify.yml', 'config/github/repository-policy.json',
                     'tools/apply.py', 'docs/other.md', 'docs/media/runner.py',
                     'docs/media/script.js', 'docs/media/page.html', 'docs/media/icon.svg',
                     'docs/media/archive.zip', 'docs/media/config.yml']:
            with self.subTest(path=path), self.assertRaises(ValueError):
                payload_manifest(COMMIT, dict(blobs, **{path: ('100644', b'not allowed')}))

    def test_links_submodules_executable_modes_and_archive_bytes_fail(self):
        _, blobs = fixture()
        for value in [('120000', b'../../secret'), ('160000', b'a' * 40),
                      ('100755', b'#!/bin/sh'), b'PK\x03\x04archive']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                payload_manifest(COMMIT, dict(blobs, **{'docs/media/NOTICE.txt': value}))

    def test_paths_are_rejected_without_normalizing_them(self):
        _, blobs = fixture()
        for path in ['/docs/media/NOTICE.txt', 'docs/media/../NOTICE.txt',
                     'docs//media/NOTICE.txt', 'docs/media/./NOTICE.txt',
                     'docs/media/%2e%2e/NOTICE.txt', 'docs/media\\NOTICE.txt',
                     'docs/media/file\n.txt', 'docs/media/.hidden.txt']:
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, 'unsafe payload path'):
                payload_manifest(COMMIT, dict(blobs, **{path: ('100644', b'notice')}))

    def test_static_media_is_hashed_and_case_collisions_fail(self):
        _, blobs = fixture()
        blobs['docs/media/NOTICE.txt'] = ('100644', b'Attribution\n')
        blobs['docs/media/clip.mp4'] = ('100644', b'fixture media bytes')
        manifest = json.loads(verify_payload(pin(blobs), blobs))
        self.assertEqual(len(manifest['files']), 5)
        blobs['docs/media/notice.txt'] = ('100644', b'different attribution')
        with self.assertRaisesRegex(ValueError, 'case-colliding'):
            payload_manifest(COMMIT, blobs)

    def test_unsafe_declarations_and_outputs_fail(self):
        site, blobs = fixture()
        variants = []
        for field, value in [('source', 'config/github/repository-policy.json'),
                             ('source', 'docs/unapproved.md'), ('path', '../index.md'),
                             ('path', 'assets/index.md'), ('path', 'version.md'),
                             ('path', 'Version.md'), ('path', 'ASSETS/index.md'),
                             ('license', 'unknown')]:
            variant = copy.deepcopy(site)
            variant['pages'][0][field] = value
            variants.append(variant)
        variants += [dict(site, directory='config/github/repositories.json'),
                     dict(site, extra='field'), dict(site, schema_version=True),
                     dict(site, redirects={'../old.html': 'index.html'}),
                     dict(site, redirects={'index.html': 'index.html'}),
                     dict(site, redirects={'old.html': 'https://example.org'}),
                     dict(site, redirects={'Version.html': 'index.html'}),
                     dict(site, redirects={'old.html': 'index.html', 'OLD.html': 'index.html'}),
                     dict(site, pages=site['pages'] * 2)]
        for variant in variants:
            with self.subTest(site=variant), self.assertRaises(ValueError):
                payload_manifest(COMMIT, dict(blobs, **{
                    'docs/site.json': ('100644', json.dumps(variant).encode())}))

    def test_ambiguous_json_and_invalid_text_fail(self):
        _, blobs = fixture()
        for data in [b'{"manuals":[],"manuals":[],"projects":[]}',
                     b'{"manuals":[],"projects":[],"x":NaN}', b'\xff', b'[]']:
            with self.subTest(data=data), self.assertRaises(ValueError):
                payload_manifest(COMMIT, dict(blobs, **{'docs/directory.json': ('100644', data)}))
        with self.assertRaisesRegex(ValueError, 'NUL'):
            payload_manifest(COMMIT, dict(blobs, **{'docs/index.md': ('100644', b'# Bad\x00')}))

    def test_production_lock_is_unchanged_and_new_mode_is_explicit(self):
        lock = json.loads((ROOT / 'content.lock.json').read_text())
        self.assertEqual(lock_errors(lock), [])
        self.assertEqual(lock, {'repository': 'Living-Proof-Labs/.github', 'tag': 'v1.1.3',
                               'commit': '28cfb4b8c9891f1233e9fb818fc09d0e3e444fed'})
        _, blobs = fixture()
        self.assertEqual(lock_errors(pin(blobs)), [])
        ambiguous = pin(blobs)
        del ambiguous['mode']
        self.assertTrue(lock_errors(ambiguous), 'bare commit must not select docs mode')

    def test_active_content_is_rejected(self):
        _, blobs = fixture()
        for data in [b'<script>alert(1)</script>', b'<img src="x" onerror="alert(1)">',
                     b'[click](javascript:alert(1))', b'<iframe src="https://example.org"></iframe>',
                     b'<a href="&#106;avascript:alert(1)">click</a>',
                     b'<video style="background:url(https://example.org)"></video>',
                     b'<video style="width:expression(alert(1))"></video>']:
            with self.subTest(data=data), self.assertRaises(ValueError):
                payload_manifest(COMMIT, dict(blobs, **{'docs/index.md': ('100644', data)}))

    def test_existing_recording_static_styles_are_data(self):
        _, blobs = fixture()
        blobs['docs/index.md'] = ('100644', b'<figure style="margin:1.25rem 0 1.5rem;'
                                 b'border:1px solid var(--md-default-fg-color--lightest)">'
                                 b'<video style="display:block;width:100%;height:auto;background:#0b1120">'
                                 b'</video></figure>')
        verify_payload(pin(blobs), blobs)

    def test_existing_directory_documentation_field_is_validated(self):
        _, blobs = fixture()
        directory = {'schema_version': 1, 'manuals': [], 'projects': [
            {'repository': 'livingproof', 'title': 'LivingProof', 'summary': 'Commands',
             'documentation': {'label': 'Manual', 'url': 'https://docs.livingprooflabs.com/livingproof/'}}]}
        blobs['docs/directory.json'] = ('100644', json.dumps(directory).encode())
        verify_payload(pin(blobs), blobs)
        directory['projects'][0]['documentation']['url'] = 'javascript:alert(1)'
        blobs['docs/directory.json'] = ('100644', json.dumps(directory).encode())
        with self.assertRaises(ValueError):
            payload_manifest(COMMIT, blobs)

    def test_resource_limits_fail_closed(self):
        _, blobs = fixture()
        for setting, value in [('MAX_FILES', 2), ('MAX_TEXT_BYTES', 1),
                               ('MAX_FILE_BYTES', 1), ('MAX_PAYLOAD_BYTES', 1)]:
            with self.subTest(setting=setting), mock.patch.object(docs_payload, setting, value):
                with self.assertRaises(ValueError):
                    payload_manifest(COMMIT, blobs)


if __name__ == '__main__':
    unittest.main()
