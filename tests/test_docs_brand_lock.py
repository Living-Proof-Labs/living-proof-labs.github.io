# SPDX-License-Identifier: Apache-2.0
"""docs-brand.lock.json names a published release whose tag, commit and brand.css bytes all agree.

Proposed by Vera in the capability-verifier#72 review (guidelines bump checklist item 7). tools that
fetch brand.css by commit and check only its sha256 will accept a version-only update. This is the
Python equivalent of `lock.mjs --check` from collaboration-guidelines#68. Offline tests use a fake
GitHub; LIVINGPROOF_NETWORK=1 checks the real release (set GITHUB_TOKEN to avoid the anonymous rate
limit).

Run with: python3 -m unittest tests.test_docs_brand_lock
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import unittest
import urllib.request
from pathlib import Path


def _root() -> Path:
    here = Path(__file__).resolve().parent
    for candidate in (here, *here.parents):
        if (candidate / "docs-brand.lock.json").is_file():
            return candidate
    raise AssertionError("could not find docs-brand.lock.json")


ROOT = _root()
REPO = "Living-Proof-Labs/collaboration-guidelines"
PATH = "brand/docs/brand.css"
API = f"https://api.github.com/repos/{REPO}"


def lock():
    return json.loads((ROOT / "docs-brand.lock.json").read_text())


def problems(pin, get):
    found = []
    if sorted(pin) != ["commit", "path", "repository", "sha256", "version"]:
        return [f"expected the five lock fields, got {sorted(pin)}"]
    if pin["repository"] != REPO or pin["path"] != PATH:
        found.append("lock must name the collaboration-guidelines brand.css")
    if not re.fullmatch(r"v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", pin["version"]):
        found.append(f"version {pin['version']} is not a full release tag")
    if not re.fullmatch(r"[0-9a-f]{40}", pin["commit"]) or not re.fullmatch(
        r"[0-9a-f]{64}", pin["sha256"]
    ):
        found.append("commit must be 40 and sha256 64 lowercase hex characters")
    if found:
        return found
    release = json.loads(get(f"{API}/releases/tags/{pin['version']}"))
    if (
        release.get("tag_name") != pin["version"]
        or release.get("draft")
        or release.get("prerelease")
    ):
        found.append(f"{pin['version']} is not a published stable release")
    commit = json.loads(get(f"{API}/commits/{pin['version']}"))["sha"]
    if commit != pin["commit"]:
        found.append(f"{pin['version']} is commit {commit}, lock says {pin['commit']}")
    digest = hashlib.sha256(
        get(f"https://raw.githubusercontent.com/{REPO}/{commit}/{PATH}")
    ).hexdigest()
    if digest != pin["sha256"]:
        found.append(
            f"brand.css at {pin['version']} has sha256 {digest}, lock says {pin['sha256']}"
        )
    return found


V740 = ("v7.4.0", "613e3d97bbb1f00836d88b25c380b9eafdcfb15a", b"/* brand v7.4.0 */")
V920 = ("v9.2.0", "8c8155ec9db30dbe19ce5c2a71cf10f3f71271b0", b"/* brand v9.2.0 */")


def fake_github(*releases, draft=()):
    pages = {}
    for tag, commit, css in releases:
        pages[f"{API}/releases/tags/{tag}"] = json.dumps(
            {"tag_name": tag, "draft": tag in draft, "prerelease": False}
        )
        pages[f"{API}/commits/{tag}"] = json.dumps({"sha": commit})
        pages[f"https://raw.githubusercontent.com/{REPO}/{commit}/{PATH}"] = css
    return lambda url: pages[url] if isinstance(pages[url], bytes) else pages[url].encode()


def pin_for(tag, commit, css):
    return {
        "repository": REPO,
        "version": tag,
        "commit": commit,
        "path": PATH,
        "sha256": hashlib.sha256(css).hexdigest(),
    }


class DocsBrandLock(unittest.TestCase):
    def test_committed_lock_has_the_five_fields_and_spellings(self) -> None:
        pin = lock()
        self.assertEqual(sorted(pin), ["commit", "path", "repository", "sha256", "version"])
        self.assertEqual(pin["repository"], REPO)
        self.assertEqual(pin["path"], PATH)
        self.assertRegex(pin["version"], r"^v\d+\.\d+\.\d+$")
        self.assertRegex(pin["commit"], r"^[0-9a-f]{40}$")
        self.assertRegex(pin["sha256"], r"^[0-9a-f]{64}$")

    def test_a_regenerated_lock_passes(self) -> None:
        self.assertEqual(problems(pin_for(*V920), fake_github(V740, V920)), [])

    def test_a_version_only_update_is_refused(self) -> None:
        pin = pin_for(*V740) | {"version": "v9.2.0"}
        found = problems(pin, fake_github(V740, V920))
        self.assertTrue(any("is commit 8c8155e" in p for p in found), found)
        self.assertTrue(any("brand.css at v9.2.0" in p for p in found), found)

    def test_a_draft_release_is_refused(self) -> None:
        found = problems(pin_for(*V920), fake_github(V920, draft={"v9.2.0"}))
        self.assertEqual(found, ["v9.2.0 is not a published stable release"])

    def test_a_short_tag_is_refused_before_any_request(self) -> None:
        def offline(url):
            raise AssertionError(f"unexpected request {url}")

        self.assertEqual(
            problems(pin_for(*V920) | {"version": "v9.2"}, offline),
            ["version v9.2 is not a full release tag"],
        )

    @unittest.skipUnless(os.environ.get("LIVINGPROOF_NETWORK"), "set LIVINGPROOF_NETWORK=1")
    def test_committed_lock_matches_the_real_release(self) -> None:
        token = os.environ.get("GITHUB_TOKEN")

        def get(url):
            request = urllib.request.Request(
                url, headers={"Authorization": f"Bearer {token}"} if token else {}
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.read()

        self.assertEqual(problems(lock(), get), [])


if __name__ == "__main__":
    unittest.main()
