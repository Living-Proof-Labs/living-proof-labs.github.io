# SPDX-License-Identifier: Apache-2.0
"""Stage owned Markdown, actual Task help and source identity, then build Zensical."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import yaml

ROOT = Path(__file__).resolve().parents[1]
STAGE = ROOT / '.build'
SITE = ROOT / 'artifacts/site'
SOURCES = {'index.md': 'index.md', 'vision.md': 'vision.md',
           'contribute.md': 'contribute.md', 'LICENSE.md': 'license.md'}


def command(*args):
    return subprocess.check_output(args, cwd=ROOT, text=True).strip()


def main():
    sha = command('git', 'rev-parse', 'HEAD')
    dirty = bool(command('git', 'status', '--porcelain', '--untracked-files=normal'))
    if os.environ.get('GITHUB_ACTIONS') == 'true' and dirty:
        raise SystemExit('Refusing CI publication from a dirty source tree')
    shutil.rmtree(STAGE, ignore_errors=True)
    source = STAGE / 'source'
    source.mkdir(parents=True)
    identity = f'Docs: development · {sha[:7]}' + (' · local changes' if dirty else '')
    source_url = f'https://github.com/Living-Proof-Labs/living-proof-labs.github.io/tree/{sha}'
    manifest = {}
    for src, dest in SOURCES.items():
        text = (ROOT / src).read_text()
        manifest[src] = hashlib.sha256(text.encode()).hexdigest()
        text = re.sub(r'\A---\n.*?\n---\n', '', text, flags=re.S)
        # MkDocs handles Markdown destinations; retain final public .html links.
        (source / dest).write_text(text)
    shutil.copytree(ROOT / 'LICENSES', source / 'LICENSES')
    (source / 'assets').mkdir()
    shutil.copyfile(ROOT / 'docs/landing.css', source / 'assets/landing.css')
    tasks = json.loads(command('task', '--list', '--json'))['tasks']
    lines = ['# Contributor tasks', '',
             'Generated from the reviewed Taskfile using `task --list --json` and',
             '`task <name> --summary`. Run these commands inside the prepared Docker',
             'development environment; they do not invoke Docker recursively.',
             'The repository README documents the host container command.', '']
    for task in tasks:
        name = task['name']
        lines += [f'## {name}', '', task.get('desc', ''), '', '```text',
                  command('task', name, '--summary'), '```', '']
    (source / 'tasks.md').write_text('\n'.join(lines))
    run = os.environ.get('GITHUB_RUN_ID')
    provenance = {'source_commit': sha, 'source_dirty': dirty, 'generator': 'zensical==0.0.73',
                  'source_files': manifest, 'workflow_run': run}
    (source / 'build.json').write_text(json.dumps(provenance, indent=2) + '\n')
    (source / 'source.md').write_text(f'''# Version and source

**{identity}**

Full source: [`{sha}`]({source_url}). Local changes: **{dirty}**.
[Machine-readable build identity](build.json).

This site follows the current main branch. Historical rendered copies are not
maintained; use source history for earlier revisions. Documentation identity is
separate from each project's package or catalog release. This site is not an
application package and has no package release badge.

The generator is Zensical 0.0.73, with the dependency closure recorded in `uv.lock`.
The build stages repository Markdown and native Task help; it does not import or
search other projects' manuals. Their deployments and evidence remain independent.

'''+(f'[Deployment workflow run](https://github.com/Living-Proof-Labs/living-proof-labs.github.io/actions/runs/{run}).\n' if run else 'Local preview: no hosted workflow run is claimed.\n'))
    for page in source.glob('*.md'):
        license_name = 'Apache-2.0' if page.name == 'vision.md' else 'CC-BY-4.0'
        text = page.read_text()
        # Keep the page title first and make documentation identity visible without scripts.
        pos = text.find('\n', text.find('# '))
        text = text[:pos] + f'\n\n<div class="docs-identity" markdown>[{identity}]({source_url}) · [Version and source](source.md)</div>\n' + text[pos:]
        text += f'\n---\n\n[Documentation home](https://docs.livingprooflabs.com/) · [Source]({source_url}) · [Help / report an issue](https://github.com/Living-Proof-Labs/living-proof-labs.github.io/issues) · [License: {license_name}](license.md)\n'
        page.write_text(text)
    config = yaml.safe_load((ROOT / 'docs/mkdocs.yml').read_text())
    config.update(docs_dir='source', site_dir='site')
    (STAGE / 'mkdocs.yml').write_text(yaml.safe_dump(config, sort_keys=False))
    subprocess.run(['zensical', 'build', '--clean', '-f', '.build/mkdocs.yml'], cwd=ROOT, check=True)
    shutil.rmtree(SITE, ignore_errors=True)
    shutil.copytree(STAGE / 'site', SITE)
    (SITE / '.nojekyll').touch()


if __name__ == '__main__':
    main()
