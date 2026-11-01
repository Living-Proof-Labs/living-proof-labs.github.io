#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check built directory links; optionally request live external destinations."""
import argparse
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit
from urllib.request import Request, urlopen


class Page(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.ids = set()
        self.links = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.add(attrs["id"])
        if tag == "a" and "href" in attrs:
            self.links.append(attrs["href"])
        if tag in {"link", "script", "img"}:
            key = "href" if tag == "link" else "src"
            if key in attrs:
                self.links.append(attrs[key])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("site", type=Path)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    root = args.site.resolve()
    pages = {p: Page(p.read_text()) for p in root.rglob("*.html")}
    failures = []
    external = set()
    if root / "index.html" not in pages:
        failures.append("Missing built index.html; run task build first")
    required = {
        'index.html': ['living-proof-labs-documentation', 'livingproof', 'published-manuals',
                       'project-directory', 'help-improve-the-documentation', 'version-and-source'],
        'vision.html': ['helping-robots-help-humans', 'from-a-requirement-to-the-next-improvement',
                        'what-goes-in-what-comes-out', 'see-it-today'],
    }
    for name, anchors in required.items():
        page = pages.get(root / name)
        for anchor in anchors:
            if page is None or anchor not in page.ids:
                failures.append(f'Missing historical route/anchor: {name}#{anchor}')
    try:
        identity = json.loads((root / 'build.json').read_text())
        publisher, content = identity['publisher'], identity['content']
        assert len(publisher['commit']) == 40 and publisher['commit'] == identity['source_commit']
        assert len(content['commit']) == 40, 'content commit'
        assert content['repository'] == 'Living-Proof-Labs/.github', 'content repository'
        for name in identity['pages']:
            text = (root / name).read_text()
            for role, commit in (('publisher', publisher['commit']), ('content', content['commit'])):
                assert commit[:7] in text, f'{name} does not show the {role} revision'
        source = (root / 'source.html').read_text()
        assert publisher['commit'] in source and content['commit'] in source, 'source.html revisions'
    except (OSError, ValueError, KeyError, AssertionError) as error:
        identity = {}
        failures.append(f'Invalid or inconsistent build identity: {error}')
    for name in identity.get('pages', []):
        if root / name not in pages:
            failures.append(f'Missing declared page: {name}')
    for old, target in identity.get('redirects', {}).items():
        page = root / old
        if not page.is_file():
            failures.append(f'Missing redirect page: {old}')
        elif not (root / target).is_file():
            failures.append(f'Redirect {old} points to missing page {target}')
        elif 'http-equiv="refresh"' not in page.read_text():
            failures.append(f'Redirect {old} does not redirect')
    architecture = 'architecture/verification-architecture.html'
    home = pages.get(root / 'index.html')
    if home is None or not any(urlsplit(h).path.lstrip('./') == architecture for h in home.links):
        failures.append('Architecture is not linked from the documentation homepage')
    home_text = (root / 'index.html').read_text() if home else ''
    nav = home_text[home_text.find('md-nav--primary'):]
    if architecture not in nav:
        failures.append('Architecture is missing from the primary navigation')
    try:
        search = json.loads((root / 'search.json').read_text())
        items = search.get('items') or search.get('docs') or []
        if not any(str(item.get('location', '')).startswith(architecture) for item in items):
            failures.append('Architecture is missing from the search index')
    except (OSError, ValueError) as error:
        failures.append(f'Unreadable search index: {error}')
    mermaid_pages = 0
    for path in pages:
        text = path.read_text()
        # A ```mermaid fence that reached the page as highlighted code was not rendered.
        if 'language-mermaid' in text or '<span class="filename">mermaid' in text:
            failures.append(f'{path.relative_to(root)}: Mermaid block rendered as a literal code block')
        if '<pre class="mermaid">' in text:
            mermaid_pages += 1
            if 'assets/vendor/mermaid/mermaid-12.2.0.min.js"></script>' not in text:
                failures.append(f'{path.relative_to(root)}: diagrams without the vendored Mermaid')
            if any('%%{init' in block for block in re.findall(r'<pre class="mermaid">(.*?)</pre>', text, re.S)):
                failures.append(f'{path.relative_to(root)}: Mermaid init directive overrides site themes')
    arch = root / 'architecture/verification-architecture.html'
    if arch in pages and arch.read_text().count('<pre class="mermaid">') < 2:
        failures.append('architecture: expected its two Mermaid diagrams')
    if not mermaid_pages:
        failures.append('No page carries a Mermaid diagram; the renderer is untested')
    for path, page in pages.items():
        for href in page.links:
            url = urlsplit(href)
            if url.scheme or url.netloc:
                # The canonical hostname is validated separately after cutover.
                if url.hostname != "docs.livingprooflabs.com":
                    external.add(href)
                continue
            route = unquote(urljoin("/" + str(path.relative_to(root)), url.path))
            if route == "/livingproof/":
                external.add("https://living-proof-labs.github.io/livingproof/")
                continue
            target = (root / route.lstrip("/")).resolve()
            if not target.is_relative_to(root):
                failures.append(f"Path escapes site: {href}")
                continue
            if target.is_dir():
                target /= "index.html"
            if not target.is_file():
                failures.append(f"{path.relative_to(root)}: missing {href}")
            elif url.fragment and target in pages and unquote(url.fragment) not in pages[target].ids:
                failures.append(f"{path.relative_to(root)}: missing fragment {href}")
    if args.live:
        for url in sorted(external):
            try:
                with urlopen(Request(url, headers={"User-Agent": "Living-Proof-Labs-docs-link-check"}), timeout=30) as response:
                    print(f"{response.status} {url} -> {response.url}")
            except Exception as error:
                failures.append(f"{url}: {error}")
    for failure in failures:
        print(f"FAIL: {failure}")
    print(f"Checked {len(pages)} HTML page(s); {len(failures)} failure(s)")
    return bool(failures)


if __name__ == "__main__":
    raise SystemExit(main())
