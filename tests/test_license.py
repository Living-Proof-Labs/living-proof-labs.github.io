# SPDX-License-Identifier: Apache-2.0
"""collaboration-guidelines#162: one root Apache-2.0 LICENSE and no CC BY 4.0."""
import hashlib
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
# SHA-256 of the unmodified SPDX Apache-2.0 text, as in livingproof-common/LICENSE.
APACHE_2_0_SHA256 = 'c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4'
SKIP = {'.git', '.build', 'node_modules', 'artifacts', 'dist', '.venv', '.task', '.content', '.brand',
        '.pytest_cache', '.ruff_cache'}


class ApacheOnlyLicense(unittest.TestCase):
    def test_root_license_is_exact_apache_2_0(self):
        self.assertEqual(hashlib.sha256((ROOT / 'LICENSE').read_bytes()).hexdigest(), APACHE_2_0_SHA256)

    def test_no_license_index_or_licenses_directory(self):
        self.assertFalse((ROOT / 'LICENSE.md').exists())
        self.assertFalse((ROOT / 'LICENSES').exists())

    def test_no_file_declares_cc_by_spdx_identifier(self):
        def files(directory):
            for path in directory.iterdir():
                if path.name in SKIP:
                    continue
                if path.is_dir() and not path.is_symlink():
                    yield from files(path)
                elif path.is_file():
                    yield path
        pattern = re.compile(rb'SPDX-License-Identifier:\s*CC-BY')
        offenders = [str(p.relative_to(ROOT)) for p in files(ROOT) if pattern.search(p.read_bytes())]
        self.assertEqual(offenders, [])
