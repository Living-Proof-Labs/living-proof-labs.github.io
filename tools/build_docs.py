# SPDX-License-Identifier: Apache-2.0
"""Publish the organization pages authored in a pinned .github revision.

Content (overview, vision, architecture, contribution page, directory) is authored in
Living-Proof-Labs/.github and declared in its docs/site.json; this repository is the
publisher: theme, search, generated Task help, identity, redirects and deployment.
`content.lock.json` pins the content commit. CONTENT_DIR (default `.content`) must be a
checkout of it; `task content` fetches one. A local preview may point CONTENT_DIR at a
working tree; its revision is then recorded as unpinned and CI refuses to build it.
When that revision contains docs/media/, this build copies the whole directory into
the site media/ path without changing bytes, including NOTICE.txt. A revision with
no docs/media directory still builds.
"""
import hashlib
import html
import importlib.metadata
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import shutil
import subprocess
import sys
import urllib.request
from urllib.parse import urlsplit, urlunsplit

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_content_pin import TAG_PATTERN, lock_errors, tag_commit  # noqa: E402
from publisher_release_identity import validate_version  # noqa: E402

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


def command(*args, cwd=None):
    return subprocess.check_output(args, cwd=cwd or ROOT, text=True).strip()


def installed_zensical():
    """Return the name and version of the Zensical package running this build."""
    metadata = importlib.metadata.metadata('zensical')
    return metadata['Name'], metadata['Version']


def content_dir():
    return Path(os.environ.get('CONTENT_DIR') or ROOT / '.content').resolve()


def media_root(content_root):
    return Path(content_root) / 'docs' / 'media'


def media_digests(content_root):
    """Return sha256 digests for docs/media, or an empty map when that directory is absent.

    Older organization revisions have no docs/media directory. That absence means
    there is nothing to publish, not that the pin is broken.
    """
    root = media_root(content_root)
    if not root.is_dir():
        return {}
    digests = {}
    for path in sorted(item for item in root.rglob('*') if item.is_file()):
        rel = path.relative_to(root).as_posix()
        if not rel or PurePosixPath(rel).is_absolute() or '..' in PurePosixPath(rel).parts:
            raise SystemExit(f'Refusing media path that leaves docs/media: {rel}')
        digests[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return digests


def copy_content_media(content_root, destination):
    """Copy docs/media into the built media path when the pinned revision has one.

    The copy includes NOTICE.txt and every other file in that directory. Each file
    is copied as bytes, so a recording is not rewritten. A missing docs/media
    directory is left alone and an older pin still builds.
    """
    root = media_root(content_root)
    if not root.is_dir():
        return
    destination = Path(destination)
    for path in sorted(item for item in root.rglob('*') if item.is_file()):
        rel = path.relative_to(root)
        if '..' in rel.parts:
            raise SystemExit(f'Refusing media path that leaves docs/media: {rel.as_posix()}')
        target = destination / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)


def content_identity(lock):
    errors = lock_errors(lock)
    if errors:
        raise SystemExit('\n'.join(errors))
    path = content_dir()
    if lock.get('mode') == 'documentation-v1':
        from docs_source import projection_identity
        return path, projection_identity(lock, path)
    if not (path / 'docs/site.json').is_file():
        raise SystemExit(f'No organization content at {path}; run `task content` to fetch '
                         f'{lock["repository"]}@{lock["tag"]} ({lock["commit"][:12]}) or set CONTENT_DIR')
    commit = command('git', 'rev-parse', 'HEAD', cwd=path)
    dirty = bool(command('git', 'status', '--porcelain', '--untracked-files=normal', cwd=path))
    resolved_tag = tag_commit(path, lock['tag'])
    pinned = commit == lock['commit'] and resolved_tag == lock['commit'] and not dirty
    if os.environ.get('GITHUB_ACTIONS') == 'true' and not pinned:
        if resolved_tag != lock['commit']:
            detail = (f'tag {lock["tag"]} resolves to {resolved_tag[:12]}'
                      if resolved_tag else f'tag {lock["tag"]} is missing')
            raise SystemExit(f'Refusing CI publication: {detail}, '
                             f'content.lock.json pins {lock["tag"]} at {lock["commit"][:12]}')
        raise SystemExit(f'Refusing CI publication: content is {commit[:12]}'
                         f'{" with local changes" if dirty else ""}, '
                         f'content.lock.json pins {lock["commit"][:12]}')
    return path, {'repository': lock['repository'],
                  'tag': lock['tag'] if pinned else None,
                  'commit': commit, 'dirty': dirty,
                  'pinned': pinned,
                  'locked_tag': lock['tag'],
                  'locked_commit': lock['commit']}


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


def publisher_release_tag(repo=None, ref='HEAD', *, dirty=False):
    """Return the highest vX.Y.Z release tag on ref when the checkout is clean, or None."""
    if dirty:
        return None
    output = command('git', 'tag', '--points-at', ref, cwd=repo or ROOT)
    tags = [line.strip() for line in output.splitlines() if TAG_PATTERN.fullmatch(line.strip())]
    if not tags:
        return None
    return max(tags, key=lambda tag: tuple(int(part) for part in tag[1:].split('.')))


def main():
    sha = command('git', 'rev-parse', 'HEAD')
    dirty = bool(command('git', 'status', '--porcelain', '--untracked-files=normal'))
    if os.environ.get('GITHUB_ACTIONS') == 'true' and dirty:
        raise SystemExit('Refusing CI publication from a dirty source tree')
    publisher_tag = publisher_release_tag(ROOT, dirty=dirty)
    lock = json.loads(LOCK.read_text())
    errors = lock_errors(lock)
    if errors:
        raise SystemExit('\n'.join(errors))
    content_root, content = content_identity(lock)
    site = json.loads((content_root / 'docs/site.json').read_text())
    shutil.rmtree(STAGE, ignore_errors=True)
    source = STAGE / 'source'
    source.mkdir(parents=True)
    content_url = f'https://github.com/{content["repository"]}'
    blob = f'{content_url}/blob/{content["commit"]}/'
    publisher_repo_url = f'https://github.com/{PUBLISHER}'
    publisher_url = f'{publisher_repo_url}/tree/{sha}'
    publisher_version = os.environ.get('PUBLISHER_VERSION', '')
    if publisher_version or os.environ.get('GITHUB_ACTIONS') == 'true':
        validate_version(publisher_version)
        if sha != os.environ.get('PUBLISHER_SHA') or dirty:
            raise SystemExit('Shared build version requires the exact clean publisher commit')
    content_label = content['tag'] if content.get('tag') else 'commit'
    publisher_label = publisher_tag if publisher_tag else 'commit'
    flags = (' · local changes' if dirty else '') + ('' if content['pinned'] else ' · content not at pinned revision')
    label = publisher_version or 'development'
    identity = f'Docs: {label} · content {content_label} · publisher {publisher_label}{flags}'
    pages = {p['source']: p['path'] for p in site['pages']}
    licenses = {p['path']: p['license'] for p in site['pages']}
    tables = directory_tables(json.loads((content_root / site['directory']).read_text()))
    content['source_files'] = {}
    if content.get('mode') == 'documentation-v1':
        content['source_files']['docs/site.json'] = hashlib.sha256(
            (content_root / 'docs/site.json').read_bytes()).hexdigest()
    for page in site['pages']:
        text = (content_root / page['source']).read_text()
        raw = (content_root / page['source']).read_bytes() if content.get('mode') else text.encode()
        content['source_files'][page['source']] = hashlib.sha256(raw).hexdigest()
        for kind, rendered in tables.items():
            text = re.sub(rf'<!-- directory:{kind} -->.*?<!-- /directory:{kind} -->',
                          lambda _m, r=rendered: r, text, flags=re.S)
        text = rewrite_links(text, page['source'], page['path'], pages, blob)
        target = source / page['path']
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    directory_text = (content_root / site['directory']).read_text()
    raw = (content_root / site['directory']).read_bytes() if content.get('mode') else directory_text.encode()
    content['source_files'][site['directory']] = hashlib.sha256(raw).hexdigest()
    content['media_files'] = media_digests(content_root)
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
    # Browsers request /favicon.ico before they read <link rel="icon">. The page
    # already publishes this brand icon under assets/; the root copy is the same file.
    shutil.copyfile(ROOT / 'docs' / 'favicon.ico', source / 'favicon.ico')
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
    generator_name, generator_version = installed_zensical()
    generator_label = generator_name[:1].upper() + generator_name[1:]
    publisher_info = {'repository': PUBLISHER, 'tag': publisher_tag, 'commit': sha, 'dirty': dirty,
                      'source_files': publisher_files}
    if publisher_version and not dirty:
        publisher_info['version'] = publisher_version
    provenance = {'source_commit': sha, 'source_dirty': dirty,
                  'generator': f'{generator_name}=={generator_version}',
                  'publisher': publisher_info,
                  'content': content, 'pages': sorted(p.replace('.md', '.html') for p in licenses),
                  'redirects': redirects, 'workflow_run': run,
                  'workflow_attempt': os.environ.get('GITHUB_RUN_ATTEMPT')}
    (source / 'build.json').write_text(json.dumps(provenance, indent=2) + '\n')
    content_rev = (
        f'[`{content["tag"]}`]({content_url}/releases/tag/{content["tag"]}) '
        f'([`{content["commit"]}`]({content_url}/tree/{content["commit"]}))'
        if content.get('tag') else
        f'[`{content["commit"]}`]({content_url}/tree/{content["commit"]})'
    )
    publisher_rev = (
        f'[`{publisher_tag}`]({publisher_repo_url}/releases/tag/{publisher_tag}) '
        f'([`{sha}`]({publisher_url}))'
        if publisher_tag else
        f'[`{sha}`]({publisher_url})'
    )
    source_checks = content.get('source_checks')
    docs_evidence = (f'Documentation payload SHA-256: `{content["manifest_sha256"]}`. '
                     f'[Source documentation checks]({source_checks["url"]}), '
                     f'attempt {source_checks["run_attempt"]}.\n'
                     if source_checks else '')
    (source / 'source.md').write_text(f'''# Version and source

**{identity}**

| Role | Repository | Revision |
| --- | --- | --- |
| Content (authored) | [{content["repository"]}]({content_url}) | {content_rev} |
| Publisher (build, theme, search) | [{PUBLISHER}]({publisher_repo_url}) | {publisher_rev} |

Content pinned by `content.lock.json`: **{content["pinned"]}** (`{content.get("mode") or content["locked_tag"]}` at `{content["locked_commit"][:12]}`). Local content changes:
**{content["dirty"]}**. Local publisher changes: **{dirty}**.
{docs_evidence}
[Machine-readable build identity](build.json) lists every source file and its sha256.
When the pinned revision contains `docs/media/`, that record includes each media
file hash and the build publishes those bytes under `media/`.

The organization overview, vision, architecture and directory are authored in
`.github` and published here from that pinned revision; this repository keeps no
editable copy. Edit the pages in [`.github/docs`]({content_url}/tree/main/docs).
This site follows the pinned revision; historical rendered copies are not
maintained. Documentation identity is separate from each project's package or
catalog release.

The generator is {generator_label} {generator_version}, with the dependency closure recorded in `uv.lock`.
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
        content_href = page_source if origin else (
            f'{content_url}/releases/tag/{content["tag"]}'
            if content.get('tag') else f'{content_url}/tree/{content["commit"]}'
        )
        publisher_href = (
            f'{publisher_repo_url}/releases/tag/{publisher_tag}'
            if publisher_tag else publisher_url
        )
        identity_links = (
            f'Docs: {label} · '
            f'content [{content_label}]({content_href} "content {content["commit"]}") · '
            f'publisher [{publisher_label}]({publisher_href} "publisher {sha}")'
            f'{flags}'
        )
        pos = text.find('\n', text.find('# '))
        text = (text[:pos] + f'\n\n<div class="docs-identity" markdown>{identity_links}'
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
    # The generator needs the files present. The published copy below is taken
    # from the content revision again so the site keeps the original bytes.
    copy_content_media(content_root, source / 'media')
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
    copy_content_media(content_root, SITE / 'media')
    (SITE / '.nojekyll').touch()
    if content.get('mode') == 'documentation-v1':
        (SITE.parent / 'content-provenance.json').write_bytes(
            (content_root / '.docs-provenance.json').read_bytes())


if __name__ == '__main__':
    main()
