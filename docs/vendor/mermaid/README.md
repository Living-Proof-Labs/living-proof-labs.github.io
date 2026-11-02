<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Vendored Mermaid

`mermaid-12.2.0.min.js` is `dist/mermaid.min.js` from the npm package
[mermaid 12.2.0](https://www.npmjs.com/package/mermaid/v/12.2.0), unmodified,
under the MIT license in [LICENSE](LICENSE).

- Tarball: <https://registry.npmjs.org/mermaid/-/mermaid-12.2.0.tgz>
- npm integrity: `sha512-w7nr/SFrLO7BaVTs3dQTvYSV6nYSBj0Yy9DjBhsIJtAcHqRzXSq4Pg32ujHZ/AdWsAMNEvvhbm5dt9E2tOiHzw==`
- File sha256: `a8a6a6f805b074a8261a2825c86f99c8054acb3b35f50bb7e24a4f9f2c3c3b9f`

The build loads it only on pages with diagrams, so the site never fetches Mermaid
from a CDN and offline builds and browser tests render the same release that is
published. Upgrade by replacing the file from a newer tarball, updating the
version in `tools/build_docs.py`, `tools/check_site.py` and this file, and
running `task verify`.
