<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Documentation directory

Small Markdown-first directory for Living Proof Labs. Edit `index.md` to maintain
the directory; each project's manual remains independently deployed.

## Publication

The rollout owner configures Pages to **Deploy from a branch → main → / (root)**.
GitHub's supported native Jekyll build reads `_config.yml` and `_layouts/`.
No custom workflow, additional token, or permission grant is needed for this
content. Repository Pages enablement still requires authorized settings access.
Do not add `.nojekyll`.

The intended canonical URL is `https://docs.livingprooflabs.com/`. This is the
organization-site repository, so `baseurl` is empty. `/livingproof/` resolves to
the separately published project on both the default organization hostname and
the custom hostname. Do not copy manuals into this repository. The marketing
project keeps its own `livingprooflabs.com` override.

Domain verification, custom-domain attachment, DNS and HTTPS are coordinated in
[the rollout issue](https://github.com/Living-Proof-Labs/.github/issues/3).
The configuration's `url` affects canonical markup; it does not configure DNS or
attach a Pages domain. Announce the branded URL only after live validation.

## Validation

For a local build with Ruby 3.3.6 and Jekyll 3.10.0 (the native Pages Jekyll
series), install the Markdown parser and build:

```sh
gem install jekyll -v 3.10.0 --no-document
gem install kramdown-parser-gfm -v 1.1.0 --no-document
jekyll build
```

Use an isolated Ruby environment or container; the Pages service manages its own
dependencies. These commands are a local preview, not a replacement deployment.

After building with Jekyll, run `python3 tools/check_site.py _site`. The checker
validates local files and fragments while treating `/livingproof/` as an external
project route. Run `python3 tools/check_site.py _site --live` to request that route
on the default GitHub hostname and check remote directory links. Network failures
are failures, not proof that a target is absent. The rollout owner separately
checks the branded hostname after cutover.

Serve `_site` with `python3 -m http.server --directory _site 8000` and inspect
desktop/mobile layouts, keyboard navigation, and the manual link. A local server
does not contain the separately deployed `/livingproof/` manual. On the live
manual, exercise search, navigation and nested pages; do not treat fetching its
search index as an interactive search test.

Revert the content commit to roll back the directory. Domain rollback is separate
and must follow the rollout issue; no content rollback changes mail or marketing
routing.

See [license scopes](LICENSE.md).
