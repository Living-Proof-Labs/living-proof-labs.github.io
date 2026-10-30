#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Run quickstart.md's shell blocks verbatim, then check the documented results.

Each ```sh block is run with bash in the work directory, in page order, so the
page and CI cannot drift. QUICKSTART_STEPS limits which numbered steps run
(e.g. QUICKSTART_STEPS=3 skips the Docker demo). Usage:
    python3 tools/run_quickstart.py [WORKDIR]
"""
import os
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def blocks():
    step = None
    found = []
    text = (ROOT / 'quickstart.md').read_text()
    for match in re.finditer(r'^## (\d+)\.|^```sh\n(.*?)^```', text, re.M | re.S):
        if match.group(1):
            step = match.group(1)
        else:
            found.append((step, match.group(2)))
    return found


def main():
    work = Path(sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp(prefix='quickstart-'))
    work.mkdir(parents=True, exist_ok=True)
    wanted = set(os.environ.get('QUICKSTART_STEPS', '2,3').split(','))
    ran = set()
    for step, script in blocks():
        if step not in wanted:
            print(f'--- skip step {step}')
            continue
        print(f'--- step {step}: {work}\n{script}', flush=True)
        subprocess.run(['bash', '-euo', 'pipefail', '-c', script], cwd=work, check=True)
        ran.add(step)
    failures = []
    if '2' in ran:
        demo = work / 'capability-verifier/artifacts/demo.xml'
        suite = ET.parse(demo).getroot()
        suite = suite if suite.tag == 'testsuite' else suite.find('testsuite')
        if (suite.get('tests'), suite.get('failures'), suite.get('errors')) != ('5', '0', '0'):
            failures.append(f'demo.xml: expected 5 tests, 0 failures/errors; got {suite.attrib}')
    if '3' in ran:
        html = (work / 'baseline/report.html').read_text()
        for needle in ('PASS', 'all-required-v1', 'All required assessments pass with verified evidence'):
            if needle not in html:
                failures.append(f'report.html is missing {needle!r}')
    if not ran:
        failures.append('no quickstart steps ran')
    for failure in failures:
        print('FAIL', failure)
    print(f'Quickstart steps run: {sorted(ran)}; {len(failures)} failure(s)')
    sys.exit(1 if failures else 0)


if __name__ == '__main__':
    main()
