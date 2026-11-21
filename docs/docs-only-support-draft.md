<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Documentation-only source mode

This support route implements [.github #152](https://github.com/Living-Proof-Labs/.github/issues/152).
The committed production lock remains the existing release-tag lock. Adding this
support does not activate new content, relax the source audit or publish a release.
A separate reviewed lock change is required after independent support review.

The explicit `documentation-v1` lock has exactly `mode`, `repository`, `commit`
and `manifest_sha256`. The repository is fixed to `Living-Proof-Labs/.github`;
commit and digest require full lowercase hex values. There is no fallback from a
failed tag check to this mode. Existing `repository`, `tag`, `commit` locks keep
their release-tag checks and Renovate `github-tags` handling unchanged. Renovate
does not match the docs-only schema; its future update policy requires separate
review rather than silently switching to branch tracking.

## Propose and review a source revision

Inside the prepared repository Docker environment, with network access for this
acquisition step only:

```sh
python3 tools/docs_source.py FULL_SOURCE_COMMIT > artifacts/docs-source-candidate.json
```

This prints proposed lock, canonical manifest and API evidence; it does not edit
the production lock or create tags/releases. Review the complete projected change
from the current live content, including the Health directory entry already on
source main. The implementation validates inputs, not editorial approval or
settings rollout. Publisher #80's live dated-link smoke check remains post-delivery.

After separate review, a normal publisher PR may change `content.lock.json` to
that proposed lock. `task content` then requires a new, absent `.content` directory
(or an explicitly selected new local `CONTENT_DIR`). It refuses to overwrite an
existing projection. `CONTENT_URL` and `CONTENT_MAIN_REF` overrides are rejected
for this mode. The release-tag mode retains its existing local development behavior.

## Source trust and payload boundary

The fetcher contacts only `https://api.github.com/repos/Living-Proof-Labs/.github/`
using TLS validation and anonymous public access. Publisher credentials are never sent. Redirects,
wrong origin, unprotected main, non-ancestor commits, incomplete/truncated API
results, missing checks and mismatched source/run/attempt identities fail closed.
The source workflow must be `.github/workflows/verify.yml` on a `push` to `main`
for the exact locked commit. The latest matching run and its current attempt must
be complete, with these exact jobs successful:

- `Repository directory tests`
- `Organization docs preview (publisher build and checks)`

An unrelated failed audit or aggregate is not treated as a failed documentation
job and does not become an operational release authorization. Source evidence is
rechecked after downloading the payload; an intervening new run/attempt requires
fresh acquisition. These requirements do not change the upstream workflow.

Only approved declared Markdown, `docs/site.json`, `docs/directory.json` and
allowlisted static media blobs are selected. The fixed page allowlist is publisher
code and must be reviewed when adding pages. Git blob identity, modes, lengths,
paths, case collisions, JSON structure and active markup are checked. Source
policy, workflows, hooks and tooling are never staged or executed. No upstream
archive or Actions artifact is extracted. Media extensions are an input boundary,
not proof of encoding; normal offline browser/link checks remain necessary.

The manifest is ASCII JSON with sorted keys, compact separators and one trailing
newline. It identifies schema version 1, repository, commit, and a path-sorted
list of files with byte lengths and SHA-256 digests. Source bytes are not normalized.
The lock digest is SHA-256 of those exact manifest bytes.

## Offline build and deployment

The projection contains source data plus a manifest and source API receipt. The
build recomputes every digest, rejects extra/linked files and revalidates evidence.
The receipt is reviewable transport evidence, not a cryptographic attestation:
CI always acquires it itself through the fixed API before its offline Docker build.
Do not treat an externally supplied receipt as authenticated on its own.

`task verify` retains the publisher's build, links, fixture and browser checks.
`build.json` and the source page record content commit, payload digest and source
workflow/run/attempt separately from publisher revision/run. The verified site is
sealed with a complete file inventory and the reviewed lock. Artifact upload is limited to the site, seal and optional source receipt, with hidden files enabled to retain `.nojekyll`; other hidden site files are refused. Deployment reads its
validator and lock from the exact trusted publisher revision, never from content
or artifact code; it verifies same-run identity and all site bytes before packaging.
Links, hard links and special files are rejected. The existing main freshness check
stays inside the deployment lock. Only the generated site is packaged.

GitHub's same-run artifact boundary supplies authentication; the file digest
inventory detects mismatch/corruption, not malicious replacement of both an
artifact and its manifest by an actor already controlling that trusted build.
No extra permissions, manual dispatch, settings or audit changes are needed.
