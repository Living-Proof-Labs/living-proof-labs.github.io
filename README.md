<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Living Proof Labs documentation root

**[Start here: documentation](https://docs.livingprooflabs.com/)**

This repository is the **publisher** of the organization documentation root. The
content (overview, vision, verification architecture, contribution page and the
manual/project directory) is authored in
[Living-Proof-Labs/.github `docs/`](https://github.com/Living-Proof-Labs/.github/tree/main/docs)
and declared in its `docs/site.json`. Edit content there, not here. This repository
owns the theme configuration, local search, navigation assembly, generated Task
reference, redirects, link checks, source identity and deployment. The docs brand
(colours, fonts, `brand.css`) is owned by
[collaboration-guidelines `brand/docs/`](https://github.com/Living-Proof-Labs/collaboration-guidelines/tree/main/brand/docs);
change it there, not here. Search covers only the
published root pages, not other repositories' manuals.

`content.lock.json` is a reviewed `documentation-v1` pin of protected
`.github` main `5ee53121d9ce5b8e730797f3970880da334a0820`, the commit release
tag v1.2.2 resolves to, and the SHA-256 of that documentation payload. The
publisher acquires those docs through the canonical GitHub API. The strict
settings audit is not an input to this pin, and this lock does not publish an
operational `.github` release. A later protected-main commit needs its own
reviewed lock. Renovate's release-tag pattern does not match this schema.
Tag mode remains implemented for a lock that still names `repository`, `tag`,
and `commit`; it is not a fallback when documentation checks fail.
See [the docs-only source contract](docs/docs-only-support-draft.md).
`build.json` and every page record both the content and the
publisher revision. When that revision contains `docs/media/`, the build copies
the whole directory into the site's `media/` path, including `NOTICE.txt`,
without changing file bytes. A revision that has no `docs/media/` directory
still builds.

## Build and review

Host prerequisites: Docker, Git and Task 3.54.0. The development image supplies
Python 3.12, uv 0.12.23, Task 3.54.0, Chromium and locked Zensical dependencies.

```sh
task content    # fetch the pinned .github revision into .content (needs network)
docker build --target development -t root-docs .
docker run --rm --network none --user "$(id -u):$(id -g)" \
  -v "$PWD:/workspace" root-docs task verify
```

This host command is for Linux Docker hosts. The prepared development container
uses the same Dockerfile; inside it, use `task setup` then `task verify` directly.
`task build`, `task check` and `task test` can be run separately. No nested Docker
is needed. To preview unmerged `.github` content, set `CONTENT_DIR` to that
checkout; the build records it as unpinned and CI refuses to publish it.
Dependency updates require a deliberate `uv lock` change and review.
The container's numeric user keeps generated output owned by the host contributor.

Serve `artifacts/site` over HTTP to inspect the artifact. Browser tests exercise
search result opening, preserved fragments/reload, keyboard/mobile controls and
palette persistence, and that the architecture page is reachable from the
homepage, the navigation, search and the `/architecture.html` redirect. Results are individual JUnit cases in
`artifacts/browser-tests.xml`; screenshots support review, not a full accessibility
certification. `task check` runs offline: every page declared in `build.json`
exists, local links, assets and fragments resolve, video sources, posters and
caption tracks resolve, published `media/` bytes match `build.json` when the
pin has `docs/media/`, redirects point to existing pages, architecture is in
navigation and the search index, and both revisions appear on every page.

## Diagrams

Fenced `mermaid` blocks in the published pages render as diagrams with the
vendored Mermaid 12.2.0 in [`docs/vendor/mermaid`](docs/vendor/mermaid/README.md),
loaded only on pages that have diagrams; nothing is fetched from a CDN. The
authoring guidance lives with the content, in `.github` `docs/contribute.md`.
`task check` fails if a block is left as code or a diagram page lacks the vendored
script; `task test` renders the architecture diagrams at desktop and phone widths in
light and dark, and saves `artifacts/mermaid-*.png`.

## Publication

Selected route: **Pages → Build and deployment → Source: GitHub Actions**.
Pages must already use GitHub Actions as its source before this merges; the branch
source has no page content any more.
The existing custom domain and DNS remain unchanged. `.github/workflows/docs.yml`
builds PR previews with `contents: read`; only the separate trusted-main deploy
job has `pages: write` and `id-token: write`. It checks freshness inside the
publication lock, verifies the publisher commit and that content is at the
locked, clean `.github` commit, and deploys the successful run's site.
The deploy job checks out the exact trusted publisher revision only to run its
artifact validator against its reviewed lock. It never executes upstream content
or code from the downloaded artifact.

Review artifacts expire after 14 days; the one-day Pages transfer artifact is
transport, not a public download promise. The live manual remains published.
Verify `build.json`, visible source identity, navigation, search and old links
against the successful deployment before calling a change delivered.

The shared read-only resolver supplies one `semver-version` and exact source
for pull requests, main and an explicit delivery retry. All three run the same
build, checks and artifact seal. Pull requests and ordinary no-release main
runs cannot publish. On a release-worthy main run, the shared release writer
receives the version and commit from the verified artifact seal. It checks out
that commit and refuses to tag if the release plan changed while building. If
main advances while the writer is checking the branch, the writer still tags
that sealed commit and does not update main. Main publication runs one at a
time, so the next run plans only after that tag exists. The shared rules treat
a fix and a maintenance commit, including a Renovate chore, as their own
release: that later run tags current main and deploys it. Pages then
independently requires the published stable tag, exact current main and the
sealed artifact from that attempt. A tag or version mismatch leaves the
current live site unchanged. A `GIT_CONFIG_COUNT` value that rewrites
`url.insteadOf` is outside this guard; using it would require control of the
runner environment. `RELEASES_ENABLED=false`
prevents a new release and therefore ordinary main deployment.

Publisher releases are distinct from the pinned `.github` content in
`content.lock.json`. To retry delivery, use the already-published exact
current-main release tag as the workflow's `release_tag`; no tag is created.
Rerun all jobs if a partial rerun retained an earlier attempt's version plan
or artifact. No old attempt's artifact is reused.

## Compatibility and rollback

Keep `/vision.html`, `/#published-manuals`, `/#livingproof`, prior section anchors
and `/LICENSES/*.txt` working. `use_directory_urls: false` preserves HTML routes.
The full vision retains Apache-2.0 attribution; see [license scopes](LICENSE.md).

A content rollback moves `content.lock.json` back to the last known-good `.github`
commit through review and rebuilds. A publisher rollback reverts the PR here.
The legacy Jekyll fallback (`_config.yml`, `_layouts/`, `assets/style.css`) was
removed: its page sources moved to `.github`, so it could no longer serve content.
If Actions publication is unavailable, redeploy the last successful run's
artifact; switching Pages back to branch publishing is no longer supported. This is a documented procedure,
not a claim that rollback was executed.

The [portal rollout issue](https://github.com/Living-Proof-Labs/.github/issues/3)
owns historical domain evidence. Neither this build nor a rollback changes DNS,
mail or the marketing site. The bounded navigation exception in AGENTS.md allows
current rendered-manual links while shared guidance stays pinned to v6.0.0.
