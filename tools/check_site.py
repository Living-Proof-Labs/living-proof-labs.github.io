#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check built directory links, video media and recorded bytes; optionally request live external destinations."""
import argparse
import hashlib
import json
import re
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urljoin, urlsplit
from urllib.request import Request, urlopen


class Page(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.ids = set()
        self.links = []
        self.destination_errors = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "base":
            self.destination_errors.append("base changes effective destinations")
        for key in ("href", "src", "poster", "action", "formaction"):
            if key in attrs:
                value = attrs[key]
                try:
                    url = urlsplit(value.strip())
                    if (any(ord(c) < 32 or ord(c) == 127 for c in value)
                            or url.scheme.lower() not in {"", "http", "https", "mailto", "tel"}
                            or url.username or url.password):
                        self.destination_errors.append(f"Unsupported rendered {key} destination")
                except ValueError:
                    self.destination_errors.append(f"Malformed rendered {key} destination")
        if "id" in attrs:
            self.ids.add(attrs["id"])
        if tag in {"a", "link"} and "href" in attrs:
            self.links.append(attrs["href"])
        if tag in {"script", "img", "video", "audio", "source", "track"} and "src" in attrs:
            self.links.append(attrs["src"])
        # A poster is not the download anchor. A missing poster or caption track
        # has to fail even when the MP4 link still resolves.
        if tag in {"video", "audio"} and "poster" in attrs:
            self.links.append(attrs["poster"])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("site", type=Path)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args(argv)
    root = args.site.resolve()
    pages = {p: Page(p.read_text()) for p in root.rglob("*.html")}
    failures = [f"{path.relative_to(root)}: {error}"
                for path, page in pages.items() for error in page.destination_errors]
    external = set()
    if root / "index.html" not in pages:
        failures.append("Missing built index.html; run task build first")
    icon = root / "favicon.ico"
    brand_icon = Path(__file__).resolve().parents[1] / "docs" / "favicon.ico"
    icon_bytes = icon.read_bytes() if icon.is_file() else b""
    if icon_bytes != brand_icon.read_bytes() or not icon_bytes.startswith(b"\x00\x00\x01\x00"):
        failures.append("Root /favicon.ico must be the existing docs/favicon.ico brand icon")
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
        if content.get('mode') == 'documentation-v1':
            from check_artifact import check_docs_identity
            check_docs_identity(content)
        else:
            assert re.fullmatch(r'v(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)',
                                content['locked_tag']), 'content locked_tag'
            if content.get('pinned'):
                assert content.get('tag') == content['locked_tag'], 'content tag'
        for name in identity['pages']:
            text = (root / name).read_text()
            for role, commit in (('publisher', publisher['commit']), ('content', content['commit'])):
                assert commit[:7] in text, f'{name} does not show the {role} revision'
        source = (root / 'source.html').read_text()
        assert publisher['commit'] in source and content['commit'] in source, 'source.html revisions'
        if content.get('tag'):
            assert content['tag'] in source, 'source.html content tag'
    except (OSError, ValueError, KeyError, AssertionError) as error:
        identity = {}
        failures.append(f'Invalid or inconsistent build identity: {error}')
    media_root = (root / 'media').resolve()
    for rel, digest in identity.get('content', {}).get('media_files', {}).items():
        path = PurePosixPath(str(rel))
        built = root / 'media' / str(rel)
        if not rel or path.is_absolute() or '..' in path.parts or not built.resolve().is_relative_to(media_root):
            failures.append(f'Media path escapes the built site: {rel}')
            continue
        if not built.is_file():
            failures.append(f'Missing built media file: media/{rel}')
            continue
        actual = hashlib.sha256(built.read_bytes()).hexdigest()
        if actual != digest:
            failures.append(f'Media bytes differ from build.json: media/{rel}')
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
    if 'data-md-component="source"' in home_text:
        failures.append('Source badge still loads repository facts (GitHub releases API)')
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
    if arch in pages and arch.read_text().count('<pre class="mermaid">') < 3:
        failures.append('architecture: expected its three Mermaid diagrams')
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
