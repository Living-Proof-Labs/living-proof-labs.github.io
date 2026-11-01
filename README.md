<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Living Proof Labs documentation root

**[Start here: documentation](https://docs.livingprooflabs.com/)**

This repository is the **publisher** of the organization documentation root. The
content (overview, vision, verification architecture, contribution page and the
manual/project directory) is authored in
[Living-Proof-Labs/.github `docs/`](https://github.com/Living-Proof-Labs/.github/tree/main/docs)
and declared in its `docs/site.json`. Edit content there, not here. This repository
owns the theme, local search, navigation assembly, generated Task reference,
redirects, link checks, source identity and deployment. Search covers only the
published root pages, not other repositories' manuals.

`content.lock.json` pins one full `.github` commit. A content change merges in
`.github` first; a pull request here then moves the pin. `build.json` and every
page record both the content and the publisher revision.

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
exists, local links, assets and fragments resolve, redirects point to existing
pages, architecture is in navigation and the search index, and both revisions
appear on every page.

## Publication

Selected route: **Pages → Build and deployment → Source: GitHub Actions**.
Switch from the original `main` / root branch source only after candidate review.
The existing custom domain and DNS remain unchanged. `.github/workflows/docs.yml`
builds PR previews with `contents: read`; only the separate trusted-main deploy
job has `pages: write` and `id-token: write`. It checks freshness inside the
publication lock, verifies the publisher commit and that content is at the
locked, clean `.github` commit, and deploys the successful run's site.
The deploy job does not check out or execute project code.

Review artifacts expire after 14 days; the one-day Pages transfer artifact is
transport, not a public download promise. The live manual remains published.
Verify `build.json`, visible source identity, navigation, search and old links
against the successful deployment before calling a change delivered.

## Compatibility and rollback

Keep `/vision.html`, `/#published-manuals`, `/#livingproof`, prior section anchors
and `/LICENSES/*.txt` working. `use_directory_urls: false` preserves HTML routes.
The full vision retains Apache-2.0 attribution; see [license scopes](LICENSE.md).

A content rollback moves `content.lock.json` back to the last known-good `.github`
commit through review and rebuilds. A publisher rollback reverts the PR here.
The original `_config.yml`, `_layouts/` and `assets/style.css` remain, but the
page sources are no longer in this repository, so the Jekyll branch fallback no
longer serves content; it would need the pinned `.github` pages copied in first.
Removing that fallback is a separate decision. This is a documented procedure,
not a claim that rollback was executed.

The [portal rollout issue](https://github.com/Living-Proof-Labs/.github/issues/3)
owns historical domain evidence. Neither this build nor a rollback changes DNS,
mail or the marketing site. The bounded navigation exception in AGENTS.md allows
current rendered-manual links while shared guidance stays pinned to v6.0.0.
