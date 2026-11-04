# SPDX-License-Identifier: Apache-2.0
"""Publish the organization pages authored in a pinned .github revision.

Content (overview, vision, architecture, contribution page, directory) is authored in
Living-Proof-Labs/.github and declared in its docs/site.json; this repository is the
publisher: theme, search, generated Task help, identity, redirects and deployment.
`content.lock.json` pins the content commit. CONTENT_DIR (default `.content`) must be a
checkout of it; `task content` fetches one. A local preview may point CONTENT_DIR at a
working tree; its revision is then recorded as unpinned and CI refuses to build it.
"""
import hashlib
import html
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import shutil
import subprocess
import urllib.request
from urllib.parse import urlsplit, urlunsplit

import yaml

ROOT = Path(__file__).resolve().parents[1]
STAGE = ROOT / '.build'
SITE = ROOT / 'artifacts/site'
PUBLISHER = 'Living-Proof-Labs/living-proof-labs.github.io'
LOCK = ROOT / 'content.lock.json'
BRAND_LOCK = ROOT / 'docs-brand.lock.json'
MERMAID = 'mermaid-12.2.0.min.js'
LICENSE_PAGE = {'LICENSE.md': 'license.md'}


def brand_css():
    """Return the docs brand pinned in docs-brand.lock.json after checking its sha256.

    The brand is owned by collaboration-guidelines brand/docs/. DOCS_BRAND_FILE may name a copy
    staged by tools/fetch_brand.py (how CI and the offline `task verify` get it), and
    DOCS_BRAND_SOURCE may name a local collaboration-guidelines checkout to read the pinned
    commit offline. The digest is enforced on every path.
    """
    pin = json.loads(BRAND_LOCK.read_text())
    staged = os.environ.get('DOCS_BRAND_FILE')
    local = os.environ.get('DOCS_BRAND_SOURCE')
    if staged:
        if not Path(staged).is_file():
            raise FileNotFoundError(f'{staged} is missing; run `task brand` (tools/fetch_brand.py) first')
        data = Path(staged).read_bytes()
    elif local:
        data = subprocess.check_output(['git', '-C', local, 'show', f"{pin['commit']}:{pin['path']}"])
    else:
        url = f"https://raw.githubusercontent.com/{pin['repository']}/{pin['commit']}/{pin['path']}"
        with urllib.request.urlopen(url, timeout=30) as response:
            data = response.read()
    digest = hashlib.sha256(data).hexdigest()
    if digest != pin['sha256']:
        raise ValueError(f"Docs brand {pin['version']} sha256 is {digest}, pinned {pin['sha256']}")
    return data


def command(*args, cwd=ROOT):
    return subprocess.check_output(args, cwd=cwd, text=True).strip()


def content_dir():
    return Path(os.environ.get('CONTENT_DIR') or ROOT / '.content').resolve()


def content_identity(lock):
    path = content_dir()
    if not (path / 'docs/site.json').is_file():
        raise SystemExit(f'No organization content at {path}; run `task content` to fetch '
                         f'{lock["repository"]}@{lock["commit"][:12]} or set CONTENT_DIR')
    commit = command('git', 'rev-parse', 'HEAD', cwd=path)
    dirty = bool(command('git', 'status', '--porcelain', '--untracked-files=normal', cwd=path))
    pinned = commit == lock['commit'] and not dirty
    if os.environ.get('GITHUB_ACTIONS') == 'true' and not pinned:
        raise SystemExit(f'Refusing CI publication: content is {commit[:12]}'
                         f'{" with local changes" if dirty else ""}, '
                         f'content.lock.json pins {lock["commit"][:12]}')
    return path, {'repository': lock['repository'], 'commit': commit, 'dirty': dirty,
                  'pinned': pinned, 'locked_commit': lock['commit']}


def table(header, rows):
    out = ['| ' + ' | '.join(header) + ' |', '| ' + ' | '.join('---' for _ in header) + ' |']
    out += ['| ' + ' | '.join(cell.replace('|', '\\|') for cell in row) + ' |' for row in rows]
    return '\n'.join(out)


def directory_tables(directory):
    owner = 'https://github.com/Living-Proof-Labs/'
    return {
        'manuals': table(['Rendered manual', 'Scope'],
                         [[f'[{m["title"]}]({m["url"]})', m['scope']] for m in directory['manuals']]),
        'projects': table(['Project', 'Find here'],
                          [[f'[{p["title"]}]({owner}{p["repository"]})', p['summary']]
                           for p in directory['projects']]),
    }


def rewrite_links(text, source, destination, pages, blob):
    """Page links follow the published layout; other repository files open on GitHub."""
    def rewrite(match):
        target = match[1]
        url = urlsplit(target)
        if url.scheme or url.netloc or target.startswith('#') or not url.path:
            return match[0]
        resolved = posixpath.normpath(posixpath.join(posixpath.dirname(source), url.path))
        if resolved in pages:
            relative = posixpath.relpath(pages[resolved], posixpath.dirname(destination) or '.')
            return '](' + urlunsplit(('', '', relative, url.query, url.fragment)) + ')'
        return '](' + blob + resolved + (('#' + url.fragment) if url.fragment else '') + ')'
    return re.sub(r'\]\(([^)\s]+)\)', rewrite, text)


def redirect_page(target, base):
    href = html.escape(posixpath.relpath(target, base or '.'))
    return (f'<!doctype html>\n<html lang="en"><head><meta charset="utf-8">\n'
            f'<title>Moved</title>\n<meta http-equiv="refresh" content="0; url={href}">\n'
            f'<link rel="canonical" href="https://docs.livingprooflabs.com/{html.escape(target)}">\n'
            f'<meta name="robots" content="noindex"></head>\n'
            f'<body><p>This page moved to <a href="{href}">{href}</a>.</p></body></html>\n')


def main():
    sha = command('git', 'rev-parse', 'HEAD')
    dirty = bool(command('git', 'status', '--porcelain', '--untracked-files=normal'))
    if os.environ.get('GITHUB_ACTIONS') == 'true' and dirty:
        raise SystemExit('Refusing CI publication from a dirty source tree')
    lock = json.loads(LOCK.read_text())
    if not re.fullmatch(r'[0-9a-f]{40}', lock['commit']):
        raise SystemExit('content.lock.json must pin a full 40-character commit')
    content_root, content = content_identity(lock)
    site = json.loads((content_root / 'docs/site.json').read_text())
    shutil.rmtree(STAGE, ignore_errors=True)
    source = STAGE / 'source'
    source.mkdir(parents=True)
    content_url = f'https://github.com/{content["repository"]}'
    blob = f'{content_url}/blob/{content["commit"]}/'
    publisher_url = f'https://github.com/{PUBLISHER}/tree/{sha}'
    flags = (' · local changes' if dirty else '') + ('' if content['pinned'] else ' · content not at pinned revision')
    identity = f'Docs: development · content {content["commit"][:7]} · publisher {sha[:7]}{flags}'
    pages = {p['source']: p['path'] for p in site['pages']}
    licenses = {p['path']: p['license'] for p in site['pages']}
    tables = directory_tables(json.loads((content_root / site['directory']).read_text()))
    content['source_files'] = {}
    for page in site['pages']:
        text = (content_root / page['source']).read_text()
        content['source_files'][page['source']] = hashlib.sha256(text.encode()).hexdigest()
        for kind, rendered in tables.items():
            text = re.sub(rf'<!-- directory:{kind} -->.*?<!-- /directory:{kind} -->',
                          lambda _m, r=rendered: r, text, flags=re.S)
        text = rewrite_links(text, page['source'], page['path'], pages, blob)
        target = source / page['path']
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    directory_text = (content_root / site['directory']).read_text()
    content['source_files'][site['directory']] = hashlib.sha256(directory_text.encode()).hexdigest()
    publisher_files = {}
    for src, dest in LICENSE_PAGE.items():
        text = (ROOT / src).read_text()
        publisher_files[src] = hashlib.sha256(text.encode()).hexdigest()
        (source / dest).write_text(text)
        licenses[dest] = 'CC-BY-4.0'
    shutil.copytree(ROOT / 'LICENSES', source / 'LICENSES')
    (source / 'assets').mkdir()
    shutil.copyfile(ROOT / 'docs/landing.css', source / 'assets/landing.css')
    (source / 'assets/brand.css').write_bytes(brand_css())
    for icon in ('favicon.svg', 'favicon.ico', 'favicon-32.png', 'apple-touch-icon.png',
                 'icon-192.png', 'icon-512.png', 'site.webmanifest'):
        shutil.copyfile(ROOT / 'docs' / icon, source / 'assets' / icon)
    shutil.copytree(ROOT / 'docs/vendor/mermaid', source / 'assets/vendor/mermaid')
    shutil.rmtree(STAGE / 'overrides', ignore_errors=True)
    shutil.copytree(ROOT / 'docs/overrides', STAGE / 'overrides')
    tasks = json.loads(command('task', '--list', '--json'))['tasks']
    lines = ['# Contributor tasks', '',
             'Generated from the publisher Taskfile using `task --list --json` and',
             '`task <name> --summary`. Run these commands inside the prepared Docker',
             'development environment; they do not invoke Docker recursively.',
             'The repository README documents the host container command.', '']
    for task in tasks:
        name = task['name']
        lines += [f'## {name}', '', task.get('desc', ''), '', '```text',
                  command('task', name, '--summary'), '```', '']
    (source / 'tasks.md').write_text('\n'.join(lines))
    licenses['tasks.md'] = 'CC-BY-4.0'
    run = os.environ.get('GITHUB_RUN_ID')
    redirects = site.get('redirects', {})
    provenance = {'source_commit': sha, 'source_dirty': dirty, 'generator': 'zensical==0.0.73',
                  'publisher': {'repository': PUBLISHER, 'commit': sha, 'dirty': dirty,
                                'source_files': publisher_files},
                  'content': content, 'pages': sorted(p.replace('.md', '.html') for p in licenses),
                  'redirects': redirects, 'workflow_run': run}
    (source / 'build.json').write_text(json.dumps(provenance, indent=2) + '\n')
    (source / 'source.md').write_text(f'''# Version and source

**{identity}**

| Role | Repository | Revision |
| --- | --- | --- |
| Content (authored) | [{content["repository"]}]({content_url}) | [`{content["commit"]}`]({content_url}/tree/{content["commit"]}) |
| Publisher (build, theme, search) | [{PUBLISHER}](https://github.com/{PUBLISHER}) | [`{sha}`]({publisher_url}) |

Content pinned by `content.lock.json`: **{content["pinned"]}**. Local content changes:
**{content["dirty"]}**. Local publisher changes: **{dirty}**.
[Machine-readable build identity](build.json) lists every source file and its sha256.

The organization overview, vision, architecture and directory are authored in
`.github` and published here from that pinned revision; this repository keeps no
editable copy. Edit the pages in [`.github/docs`]({content_url}/tree/main/docs).
This site follows the pinned revision; historical rendered copies are not
maintained. Documentation identity is separate from each project's package or
catalog release.

The generator is Zensical 0.0.73, with the dependency closure recorded in `uv.lock`.
The build does not import or search other projects' manuals. Their deployments and
evidence remain independent.

'''+(f'[Deployment workflow run](https://github.com/{PUBLISHER}/actions/runs/{run}).\n' if run else 'Local preview: no hosted workflow run is claimed.\n'))
    licenses['source.md'] = 'CC-BY-4.0'
    for page in sorted(source.rglob('*.md')):
        rel = page.relative_to(source).as_posix()
        text = re.sub(r'\A---\n.*?\n---\n', '', page.read_text(), flags=re.S)
        up = posixpath.relpath('.', posixpath.dirname(rel) or '.')
        here = f'{up}/' if up != '.' else ''
        origin = next((src for src, dest in pages.items() if dest == rel), None)
        page_source = blob + origin if origin else publisher_url
        pos = text.find('\n', text.find('# '))
        text = (text[:pos] + f'\n\n<div class="docs-identity" markdown>[{identity}]({page_source})'
                f' · [Version and source]({here}source.md)</div>\n' + text[pos:])
        issues = f'{content_url}/issues' if origin else f'https://github.com/{PUBLISHER}/issues'
        text += (f'\n---\n\n[Documentation home](https://docs.livingprooflabs.com/) · '
                 f'[Source]({page_source}) · [Help / report an issue]({issues}) · '
                 f'[License: {licenses.get(rel, "CC-BY-4.0")}]({here}license.md)\n')
        page.write_text(text)
    config = yaml.safe_load((ROOT / 'docs/mkdocs.yml').read_text())
    nav = [{p['title']: p['path']} for p in site['pages']]
    nav.insert(min(3, len(nav)), {'Manual directory': 'index.html#published-manuals'})
    nav += [{'Contributor tasks': 'tasks.md'}, {'Version and source': 'source.md'},
            {'License': 'license.md'}, {'livingprooflabs.com ↗': 'https://livingprooflabs.com/'}]
    config.update(docs_dir='source', site_dir='site', nav=nav)
    (STAGE / 'mkdocs.yml').write_text(yaml.safe_dump(config, sort_keys=False, allow_unicode=True))
    subprocess.run(['zensical', 'build', '--clean', '-f', '.build/mkdocs.yml'], cwd=ROOT, check=True)
    for old, target in redirects.items():
        if (STAGE / 'site' / old).exists():
            raise SystemExit(f'Redirect {old} would replace a published page')
        path = STAGE / 'site' / old
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(redirect_page(target, str(PurePosixPath(old).parent)))
    for page in (STAGE / 'site').rglob('*.html'):
        text = page.read_text()
        if 'class="mermaid"' in text:
            # Zensical uses a global `mermaid` when one exists instead of fetching unpkg,
            # so diagram pages load the vendored, reviewed release before its bundle.
            up = posixpath.relpath('.', posixpath.dirname(page.relative_to(STAGE / 'site').as_posix()) or '.')
            src = ('' if up == '.' else up + '/') + 'assets/vendor/mermaid/' + MERMAID
            page.write_text(text.replace('</head>', f'<script src="{src}"></script>\n</head>', 1))
    shutil.rmtree(SITE, ignore_errors=True)
    shutil.copytree(STAGE / 'site', SITE)
    (SITE / '.nojekyll').touch()


if __name__ == '__main__':
    main()
