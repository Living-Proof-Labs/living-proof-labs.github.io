# SPDX-License-Identifier: Apache-2.0
"""collaboration-guidelines bumps move every consumer pin together and keep the release interface.

Proposed by Vera in the capability-verifier#72 review (guidelines bump checklist items 2, 3 and 6),
adapted for this repository. Offline: the shared release interface is recorded here and checked
against the publisher's writer and resolver calls. When a guidelines release changes either
interface, update SHARED_WORKFLOWS in the same pull request after reading the diff.
LIVINGPROOF_NETWORK=1 also compares the recorded interfaces with the pinned tag.

Run with: python3 -m unittest discover -s tests -p test_guidelines_pins.py
"""

from __future__ import annotations

from functools import lru_cache
import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = "Living-Proof-Labs/collaboration-guidelines"
TAG = r"v(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)"
USES = re.compile(
    rf"^\s+uses:\s*{re.escape(REPO)}/\.github/workflows/"
    rf"(?P<file>[\w.-]+\.ya?ml)@(?P<ref>\S+)\s*$",
    re.MULTILINE,
)
PRESET = re.compile(rf"^github>{REPO}:renovate-preset#(?P<ref>.+)$")
SHARED_WORKFLOWS = {
    "semantic-release.yml": {
        "inputs": {"dry-run", "draft-release", "expected-version", "expected-commit"},
        "outputs": {"draft-created", "published", "version", "git-tag", "release-url", "commit"},
        "contents": "write",
    },
    "semantic-release-candidate.yml": {
        "inputs": {"replay-tag"},
        "outputs": {"semver-version", "pep440-version", "debian-version",
                    "version", "git-tag", "commit", "run-id", "run-attempt"},
        "contents": "read",
    },
}


def _root() -> Path:
    here = Path(__file__).resolve().parent
    for candidate in (here, *here.parents):
        if (candidate / "renovate.json").is_file():
            return candidate
    raise AssertionError("could not find the repository root (renovate.json)")


ROOT = _root()


def workflow_path() -> Path | None:
    for name in (".github/workflows/verify.yml", ".github/workflows/release.yml", ".github/workflows/docs.yml"):
        path = ROOT / name
        if path.is_file() and USES.search(path.read_text()):
            return path
    return None


def guideline_calls(text: str | None = None) -> dict[str, re.Match[str]]:
    path = workflow_path()
    if text is None:
        if path is None:
            return {}
        text = path.read_text()
    calls: dict[str, re.Match[str]] = {}
    for match in USES.finditer(text):
        headers = re.findall(r"^  ([A-Za-z0-9_-]+):\s*$", text[: match.start()], re.MULTILINE)
        assert headers, "expected a job name above the guidelines workflow call"
        calls[headers[-1]] = match
    return calls


def preset_refs(config: dict | None = None) -> list[str]:
    config = config or json.loads((ROOT / "renovate.json").read_text())
    return [m.group("ref") for m in map(PRESET.match, config.get("extends", [])) if m]


def pinned_versions(text: str | None = None, config: dict | None = None) -> set[str]:
    refs = set(preset_refs(config))
    if text is not None or workflow_path() is not None:
        refs |= {match.group("ref") for match in guideline_calls(text).values()}
    return refs


def _job_block(text: str, job: str) -> str:
    match = re.search(rf"^  {re.escape(job)}:\n", text, re.MULTILINE)
    assert match, f"job {job} not found"
    start = match.start()
    end = len(text)
    for later in re.finditer(r"^  [A-Za-z0-9_-]+:\s*$", text[match.end() :], re.MULTILINE):
        end = match.end() + later.start()
        break
    return text[start:end]


def _mapping(block: str, key: str, indent: int = 4) -> dict[str, str]:
    pad = " " * indent
    inner = " " * (indent + 2)
    found = re.search(rf"^{pad}{re.escape(key)}:\n((?:{inner}.*\n)*)", block, re.MULTILINE)
    if not found:
        return {}
    return dict(re.findall(rf"^{inner}([A-Za-z0-9_-]+):\s*(\S+)", found.group(1), re.MULTILINE))


def _workflow_call_keys(shared: str, section: str) -> set[str]:
    call = re.search(r"^  workflow_call:\n((?:    .*\n)+)", shared, re.MULTILINE)
    assert call, "expected a workflow_call interface"
    body = call.group(1)
    found = re.search(rf"^    {re.escape(section)}:\n((?:      .*\n)+)", body, re.MULTILINE)
    if not found:
        return set()
    return set(re.findall(r"^      ([A-Za-z0-9_-]+):", found.group(1), re.MULTILINE))


@lru_cache(maxsize=4)
def released_checks(ref: str) -> dict[str, str]:
    """Read the tested files from one exact tag snapshot without running it."""
    if not re.fullmatch(TAG, ref):
        raise ValueError("expected a full Guidelines release tag")
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    with tempfile.TemporaryDirectory() as checkout:
        def git(*args: str) -> str:
            return subprocess.check_output(["git", "-C", checkout, *args],
                                           env=env, text=True, timeout=45)

        git("init", "--quiet")
        git("fetch", "--quiet", "--depth=1", f"https://github.com/{REPO}.git", f"refs/tags/{ref}")
        return {
            path: git("show", f"FETCH_HEAD:{path}")
            for path in ("renovate-preset.json", *(
                f".github/workflows/{file}" for file in SHARED_WORKFLOWS
            ))
        }


class GuidelinesPins(unittest.TestCase):
    def test_every_guidelines_pin_is_a_full_release_tag(self) -> None:
        refs = pinned_versions()
        self.assertTrue(refs, "expected a Renovate preset pin and/or a release workflow call")
        for ref in refs:
            self.assertRegex(ref, rf"^{TAG}$", f"{ref} is not a full vX.Y.Z release tag")

    def test_workflow_call_and_renovate_preset_name_one_guidelines_release(self) -> None:
        refs = pinned_versions()
        self.assertEqual(len(refs), 1, sorted(refs))

    @unittest.skipUnless(workflow_path() is not None, "this repository has no guidelines workflow call")
    def test_mismatched_pins_are_reported(self) -> None:
        text = workflow_path().read_text()
        mutated = USES.sub(lambda m: m.group(0).replace(m.group("ref"), "v2.2.0", 1), text, count=1)
        self.assertEqual(pinned_versions(mutated), {*preset_refs(), "v2.2.0"})

    def test_release_calls_use_only_their_shared_interfaces(self) -> None:
        path = workflow_path()
        self.assertIsNotNone(path, "publisher must call the shared resolver and writer")
        text = path.read_text()
        calls = guideline_calls(text)
        self.assertCountEqual([match.group("file") for match in calls.values()], SHARED_WORKFLOWS)
        for name, match in calls.items():
            contract = SHARED_WORKFLOWS[match.group("file")]
            with self.subTest(job=name):
                block = _job_block(text, name)
                self.assertLessEqual(set(_mapping(block, "with")), contract["inputs"])
                self.assertEqual(_mapping(block, "permissions").get("contents"), contract["contents"])
                used = set(re.findall(rf"needs\.{re.escape(name)}\.outputs\.([\w-]+)", text))
                self.assertLessEqual(used, contract["outputs"])

    @unittest.skipUnless(workflow_path() is not None, "this repository has no guidelines workflow call")
    def test_an_unknown_release_output_is_reported(self) -> None:
        text = workflow_path().read_text()
        mutated = (
            text + "\n# needs.release.outputs.tag\n"
            if "needs.release.outputs" in text
            else text.replace(
                "permissions:", "needs.release.outputs.tag: placeholder\n  permissions:", 1
            )
        )
        found = set(re.findall(r"needs\.release\.outputs\.([\w-]+)", mutated))
        self.assertIn("tag", found)
        self.assertIn("tag", found - SHARED_WORKFLOWS["semantic-release.yml"]["outputs"])

    @unittest.skipUnless(os.environ.get("LIVINGPROOF_NETWORK"), "set LIVINGPROOF_NETWORK=1")
    def test_recorded_interfaces_match_both_pinned_shared_workflows(self) -> None:
        calls = guideline_calls()
        self.assertCountEqual([match.group("file") for match in calls.values()], SHARED_WORKFLOWS)
        for match in calls.values():
            file, ref = match.group("file", "ref")
            with self.subTest(workflow=file, tag=ref):
                shared = released_checks(ref)[f".github/workflows/{file}"]
                for section in ("inputs", "outputs"):
                    self.assertEqual(_workflow_call_keys(shared, section), SHARED_WORKFLOWS[file][section])

    def test_this_repository_does_not_opt_in_to_docs_brand_updates(self) -> None:
        # Proposed by Vera in the living-proof-labs.github.io#51 review.
        # v9.4.0 adds a docs-brand manager that stays disabled until a consumer
        # opts in. This repo enables regex for content only and does not override
        # the disabled docs-brand package rule.
        config = json.loads((ROOT / "renovate.json").read_text())
        # Content tracking may use regex without opting into brand updates.
        for manager in config.get("customManagers", []):
            self.assertEqual(manager.get("managerFilePatterns"),
                             [r"/^content\.lock\.json$/"])
        for rule in config.get("packageRules") or []:
            dumped = json.dumps(rule)
            if "docs-brand" in dumped or rule.get("matchDepTypes") == ["docs-brand"]:
                self.assertIs(rule.get("enabled"), False, rule)

    @unittest.skipUnless(os.environ.get("LIVINGPROOF_NETWORK"), "set LIVINGPROOF_NETWORK=1")
    def test_pinned_preset_keeps_docs_brand_disabled_by_default(self) -> None:
        # Proposed by Vera in the living-proof-labs.github.io#51 review.
        refs = pinned_versions()
        self.assertTrue(refs, "expected a Renovate preset pin")
        (ref,) = refs
        preset = json.loads(released_checks(ref)["renovate-preset.json"])
        brand_rules = [
            rule
            for rule in preset.get("packageRules", [])
            if "docs-brand" in json.dumps(rule) or rule.get("matchDepTypes") == ["docs-brand"]
        ]
        self.assertTrue(brand_rules, f"pinned {ref} preset has no docs-brand packageRule")
        for rule in brand_rules:
            self.assertIs(rule.get("enabled"), False, rule)
            self.assertIs(rule.get("automerge"), False, rule)
        managers = [
            manager
            for manager in preset.get("customManagers", [])
            if manager.get("depTypeTemplate") == "docs-brand"
            or "docs-brand.lock.json" in json.dumps(manager)
        ]
        self.assertTrue(managers, f"pinned {ref} preset has no docs-brand.lock.json manager")




if __name__ == "__main__":
    unittest.main()
