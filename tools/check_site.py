#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check built directory links; optionally request live external destinations."""
import argparse
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
        failures.append("Missing built index.html; build with Jekyll first")
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
                failures.append(f"{path.name}: missing {href}")
            elif url.fragment and target in pages and unquote(url.fragment) not in pages[target].ids:
                failures.append(f"{path.name}: missing fragment {href}")
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
