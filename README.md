<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Living Proof Labs documentation root

**[Start here: documentation](https://docs.livingprooflabs.com/)**

The organization introduction, vision and seven-manual directory. Each product
owns its own manual and deployment. This root uses Zensical for local search,
responsive navigation and light/dark/system appearance; search does not index
other repositories. Edit `index.md`, `vision.md` and `contribute.md`; generated
Task reference and source identity are not separate authored sources.

## Build and review

Host prerequisites: Docker, Git and Task 3.54.0. The development image supplies
Python 3.12, uv 0.12.23, Task 3.54.0, Chromium and locked Zensical dependencies.

```sh
docker build --target development -t root-docs .
docker run --rm --network none --user "$(id -u):$(id -g)" \
  -v "$PWD:/workspace" root-docs task verify
```

This host command is for Linux Docker hosts. The prepared development container
uses the same Dockerfile; inside it, use `task setup` then `task verify` directly.
`task build`, `task check` and `task test` can be run separately. No nested Docker
is needed. Dependency updates require a deliberate `uv lock` change and review.
The container's numeric user keeps generated output owned by the host contributor.

Serve `artifacts/site` over HTTP to inspect the artifact. Browser tests exercise
search result opening, preserved fragments/reload, keyboard/mobile controls and
palette persistence. Results are individual JUnit cases in
`artifacts/browser-tests.xml`; screenshots support review, not a full accessibility
certification. Local links/assets and source identity are checked offline.

## Publication

Selected route: **Pages → Build and deployment → Source: GitHub Actions**.
Switch from the original `main` / root branch source only after candidate review.
The existing custom domain and DNS remain unchanged. `.github/workflows/docs.yml`
builds PR previews with `contents: read`; only the separate trusted-main deploy
job has `pages: write` and `id-token: write`. It checks freshness inside the
publication lock, verifies source identity and deploys the successful run's site.
The deploy job does not check out or execute project code.

Review artifacts expire after 14 days; the one-day Pages transfer artifact is
transport, not a public download promise. The live manual remains published.
Verify `build.json`, visible source identity, navigation, search and old links
against the successful deployment before calling a change delivered.

## Compatibility and rollback

Keep `/vision.html`, `/#published-manuals`, `/#livingproof`, prior section anchors
and `/LICENSES/*.txt` working. `use_directory_urls: false` preserves HTML routes.
The full vision retains Apache-2.0 attribution; see [license scopes](LICENSE.md).

The original `_config.yml`, `_layouts/` and `assets/style.css` remain as a branch
Jekyll fallback. Before merge, the current public site is unchanged. A content
rollback reverts the PR through review and rebuilds the last known-good source.
If Actions publication itself is unavailable, an authorized operator can restore
Pages to `main` / root using the retained Jekyll files. This fallback lacks the
new search/theme interface; validate its links after any actual rollback. This is
a documented procedure, not a claim that rollback was executed.

The [portal rollout issue](https://github.com/Living-Proof-Labs/.github/issues/3)
owns historical domain evidence. Neither this build nor a rollback changes DNS,
mail or the marketing site. The bounded navigation exception in AGENTS.md allows
current rendered-manual links while shared guidance stays pinned to v6.0.0.
