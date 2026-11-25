# SPDX-License-Identifier: Apache-2.0
"""Documentation-only lock/payload validation, separate from source-check evidence.

Inputs are Git blob bytes, never an extracted archive or an upstream program.
"""
import hashlib
from html.parser import HTMLParser
import json
import re
from urllib.parse import urlsplit


REPOSITORY = 'Living-Proof-Labs/.github'
MODE = 'documentation-v1'
LOCK_KEYS = {'mode', 'repository', 'commit', 'manifest_sha256'}
APPROVED_PAGES = {
    'docs/index.md', 'docs/quickstart.md', 'docs/reading-reports.md',
    'docs/vision.md', 'docs/architecture/verification-architecture.md',
    'docs/contribute.md', 'docs/GITHUB-APPS.md',
}
MEDIA_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp', '.mp4', '.webm', '.vtt', '.txt'}
MAX_FILES = 256
MAX_TEXT_BYTES = 2 * 1024 * 1024
MAX_FILE_BYTES = 256 * 1024 * 1024
MAX_PAYLOAD_BYTES = 512 * 1024 * 1024


def require(condition, message):
    if not condition:
        raise ValueError(message)


def hex_digest(value, length):
    return isinstance(value, str) and re.fullmatch(rf'[0-9a-f]{{{length}}}', value) is not None


def validate_lock(lock):
    require(isinstance(lock, dict) and set(lock) == LOCK_KEYS,
            'documentation lock requires exactly mode, repository, commit, manifest_sha256')
    require(lock['mode'] == MODE, 'unsupported documentation lock mode')
    require(lock['repository'] == REPOSITORY, 'unexpected content repository')
    require(hex_digest(lock['commit'], 40), 'content commit must be a full lowercase SHA')
    require(hex_digest(lock['manifest_sha256'], 64), 'manifest digest must be lowercase SHA-256')


def safe_path(value):
    """Only literal portable relative paths; no normalization of unsafe input."""
    return (isinstance(value, str) and len(value) <= 240
            and re.fullmatch(r'[A-Za-z0-9_/-]+(?:\.[A-Za-z0-9_-]+)*', value) is not None
            and all(part not in ('', '.', '..') and not part.startswith('.')
                    for part in value.split('/')))


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f'duplicate JSON key: {key}')
        result[key] = value
    return result


def read_json(data):
    require(len(data) <= MAX_TEXT_BYTES, 'JSON input exceeds size limit')
    def reject_constant(value):
        raise ValueError(f'non-finite JSON value: {value}')
    return json.loads(data.decode('utf-8'), object_pairs_hook=unique_object,
                      parse_constant=reject_constant)


def text(value):
    return (isinstance(value, str) and bool(value.strip())
            and all(ord(char) >= 32 for char in value))


def validate_site(site):
    require(isinstance(site, dict), 'site declaration must be an object')
    require({'schema_version', 'pages', 'directory', 'redirects'} <= set(site)
            <= {'schema_version', 'description', 'pages', 'directory', 'redirects'},
            'unsupported site declaration fields')
    require(type(site['schema_version']) is int and site['schema_version'] == 1,
            'unsupported site schema')
    require(site['directory'] == 'docs/directory.json', 'unexpected directory input')
    require(isinstance(site['pages'], list) and 0 < len(site['pages']) <= len(APPROVED_PAGES),
            'invalid declared pages')
    sources, outputs = set(), set()
    for page in site['pages']:
        require(isinstance(page, dict) and set(page) == {'source', 'path', 'title', 'license'},
                'unsupported page declaration')
        source, output = page['source'], page['path']
        require(isinstance(source, str) and source in APPROVED_PAGES, 'unapproved Markdown input')
        require(safe_path(output) and output.endswith('.md'), 'unsafe page output path')
        require(output.casefold() not in {'version.md', 'source.md', 'tasks.md', 'license.md'}
                and not output.casefold().startswith(('assets/', 'media/', 'licenses/')),
                'page collides with publisher-owned output')
        require(source not in sources and output.casefold() not in outputs, 'duplicate page declaration')
        # Organization pages are Apache-2.0 only (collaboration-guidelines#162).
        require(text(page['title']) and page['license'] == 'Apache-2.0',
                'invalid page metadata')
        sources.add(source)
        outputs.add(output.casefold())
    require('index.md' in outputs and 'docs/index.md' in sources, 'missing landing page')
    redirects = site['redirects']
    require(isinstance(redirects, dict), 'redirects must be an object')
    html_outputs = {path[:-3] + '.html' for path in outputs}
    redirect_names = set()
    for source, target in redirects.items():
        require(safe_path(source) and source.endswith('.html') and safe_path(target),
                'unsafe redirect path')
        require(source.casefold() not in html_outputs and target.casefold() in html_outputs,
                'redirect must point directly to a declared page without replacing one')
        require(source.casefold() not in redirect_names, 'case-colliding redirects')
        redirect_names.add(source.casefold())
        require(not source.casefold().startswith(('assets/', 'media/', 'licenses/'))
                and source.casefold() not in {'version.html', 'source.html', 'tasks.html', 'license.html'},
                'redirect collides with publisher-owned output')
    return sources


def inline_style(value):
    allowed = {'margin', 'padding', 'width', 'max-width', 'height', 'border',
               'border-radius', 'background', 'display'}
    require(isinstance(value, str), 'missing inline style')
    for declaration in value.split(';'):
        if not declaration.strip():
            continue
        parts = declaration.split(':', 1)
        require(len(parts) == 2 and parts[0].strip() in allowed, 'unsupported inline style property')
        plain = re.sub(r'var\(--md-[a-z-]+\)', 'brand', parts[1].strip())
        require(re.fullmatch(r'[A-Za-z0-9#.% -]+', plain) is not None,
                'active or unsupported inline style value')


class InertMarkup(HTMLParser):
    def handle_starttag(self, tag, attrs):
        require(tag not in {'script', 'iframe', 'object', 'embed', 'base', 'meta', 'link',
                            'style', 'form', 'input', 'button', 'svg', 'math'},
                'active markup is not allowed in documentation content')
        for key, value in attrs:
            require(not key.startswith('on') and key != 'srcdoc',
                    'active HTML attribute is not allowed')
            if key == 'style':
                inline_style(value)
            if key in {'href', 'src', 'poster', 'action'} and value:
                require(urlsplit(value).scheme.lower() in {'', 'https', 'http', 'mailto'},
                        'active URL is not allowed')


def validate_markdown(data):
    value = data.decode('utf-8')
    require(not re.search(r'(?i)\b(?:javascript|vbscript|data)\s*:', value), 'active URL in Markdown')
    InertMarkup(convert_charrefs=True).feed(value)


def validate_directory(directory):
    require(isinstance(directory, dict)
            and {'schema_version', 'manuals', 'projects'} <= set(directory)
            <= {'schema_version', 'description', 'manuals', 'projects'}
            and type(directory['schema_version']) is int and directory['schema_version'] == 1,
            'invalid directory declaration')
    for category, keys in [('manuals', {'repository', 'title', 'url', 'scope'}),
                           ('projects', {'repository', 'title', 'summary'})]:
        rows = directory[category]
        require(isinstance(rows, list) and len(rows) <= MAX_FILES, 'invalid directory entries')
        names = set()
        for row in rows:
            optional = {'documentation'} if category == 'projects' else set()
            require(isinstance(row, dict) and keys <= set(row) <= keys | optional,
                    'unsupported directory entry')
            require(all(text(row[key]) and not any(char in row[key] for char in '<>[]')
                        for key in keys), 'unsafe directory text')
            name = row['repository']
            require((name == '.github' or re.fullmatch(r'[a-z0-9][a-z0-9.-]*', name) is not None)
                    and name not in names, 'invalid or duplicate directory repository')
            names.add(name)
            if 'documentation' in row:
                document = row['documentation']
                require(isinstance(document, dict) and {'label'} <= set(document) <= {'label', 'url'}
                        and text(document['label']) and not any(c in document['label'] for c in '<>[]'),
                        'invalid project documentation metadata')
                if 'url' in document:
                    require(text(document['url']), 'invalid project documentation URL')
                    url = urlsplit(document['url'])
                    require(url.scheme == 'https' and bool(url.hostname)
                            and not url.username and not url.password and url.port in {None, 443},
                            'project documentation must use HTTPS')
            for link in ([row['url']] if category == 'manuals' else []):
                url = urlsplit(link)
                require(url.scheme == 'https' and url.hostname == 'docs.livingprooflabs.com'
                        and not url.username and not url.password and url.port in {None, 443},
                        'manual must link to the canonical documentation host')


def payload_manifest(commit, blobs):
    """Validate a complete selected payload and return its canonical manifest bytes.

    blobs maps literal source paths to (Git mode string, bytes). Only regular
    non-executable blobs are accepted. The future trusted fetcher must select
    these blobs from the authenticated commit and enforce limits before reading.
    This function performs no fetch, checkout, archive extraction or execution.
    """
    require(hex_digest(commit, 40), 'content commit must be a full lowercase SHA')
    require(isinstance(blobs, dict) and 0 < len(blobs) <= MAX_FILES, 'invalid payload file count')
    total = 0
    names = set()
    for path, entry in blobs.items():
        require(safe_path(path), 'unsafe payload path')
        require(path.casefold() not in names, 'case-colliding payload paths')
        names.add(path.casefold())
        require(isinstance(entry, tuple) and len(entry) == 2, 'expected Git mode and bytes')
        mode, data = entry
        require(mode == '100644' and isinstance(data, bytes),
                'only regular non-executable Git blobs are allowed')
        require(len(data) <= MAX_FILE_BYTES, 'payload file exceeds size limit')
        total += len(data)
    require(total <= MAX_PAYLOAD_BYTES, 'payload exceeds size limit')
    require('docs/site.json' in blobs and 'docs/directory.json' in blobs, 'missing declarations')
    sources = validate_site(read_json(blobs['docs/site.json'][1]))
    directory = read_json(blobs['docs/directory.json'][1])
    validate_directory(directory)
    required = sources | {'docs/site.json', 'docs/directory.json'}
    require(required <= set(blobs), 'missing declared content')
    for path, (_, data) in blobs.items():
        if path in required:
            require(len(data) <= MAX_TEXT_BYTES, 'text input exceeds size limit')
            require('\x00' not in data.decode('utf-8'), 'NUL in text input')
            if path in sources:
                try:
                    validate_markdown(data)
                except ValueError as error:
                    raise ValueError(f'{path}: {error}') from error
        else:
            extension = '.' + path.rsplit('.', 1)[-1]
            require(path.startswith('docs/media/') and extension in MEDIA_EXTENSIONS,
                    'payload contains an unapproved input')
            if extension in {'.vtt', '.txt'}:
                require(len(data) <= MAX_TEXT_BYTES and '\x00' not in data.decode('utf-8'),
                        'invalid media text')
    manifest = {
        'schema_version': 1,
        'repository': REPOSITORY,
        'commit': commit,
        'files': [{'path': path, 'size': len(blobs[path][1]),
                   'sha256': hashlib.sha256(blobs[path][1]).hexdigest()}
                  for path in sorted(blobs)],
    }
    return (json.dumps(manifest, sort_keys=True, separators=(',', ':'), ensure_ascii=True)
            + '\n').encode('ascii')


def verify_payload(lock, blobs):
    """Check the reviewed digest; this is not a source-check or deploy attestation."""
    validate_lock(lock)
    manifest = payload_manifest(lock['commit'], blobs)
    require(hashlib.sha256(manifest).hexdigest() == lock['manifest_sha256'],
            'documentation payload manifest digest mismatch')
    return manifest
