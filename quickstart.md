---
layout: default
title: Quickstart
---
<!-- SPDX-License-Identifier: CC-BY-4.0 -->

# Quickstart

*About 5 minutes once Docker images are cached; the first build takes longer.*

!!! tip "No Docker?"
    [Skip to step 3](#3-open-a-rendered-report) to open a real report in under a minute.

Go from a fresh clone to a passing demo, then open a rendered report. This page
wraps the [capability verifier v1.0.1 quickstart](https://github.com/Living-Proof-Labs/capability-verifier/tree/v1.0.1#quickstart);
that manual owns the details. Everything here uses recorded fixture data: no
robot, simulator, model call or live human review is involved.

<!-- The sh blocks below are run verbatim, in order, by tools/run_quickstart.py
     (used by .github/workflows/quickstart.yml). Keep them runnable. -->

## 1. Install the prerequisites

Install [Git](https://git-scm.com/downloads),
[Docker with Compose v2](https://docs.docker.com/compose/install/) and
[Task 3.54.0](https://taskfile.dev/docs/installation), then start Docker.
You do not need Python, uv or Node.js on your machine; the project's Dockerfile
supplies the runtime.

## 2. Clone the released demo and run it

```sh
git clone --branch v1.0.1 https://github.com/Living-Proof-Labs/capability-verifier.git
cd capability-verifier
task demo
```

`task demo` builds the Docker runtime and runs five Gherkin examples from
[robot-capability-specs v1.1.0](https://github.com/Living-Proof-Labs/robot-capability-specs/tree/v1.1.0/specs/v1).
The first run needs network access for the base images, Debian packages, Python
dependencies and the public specification catalog; later runs use Docker's cache.

The command succeeds when all five examples pass. The console ends with:

```text
============================== 5 passed in 0.03s ===============================
```

(Timing varies.) Each example prints its full JSON report. Three of them show the
verdicts you should expect:

| Evidence fixture | Verification result | Why the test passes |
| --- | --- | --- |
| Valid pause in 120 ms | `PASS` | The requirement is met |
| Motion not inhibited; other evaluators favorable | `FAIL` | The failure is detected, not averaged away |
| Elapsed time missing | <code>INSUFFICIENT_<wbr>EVIDENCE</code> | Missing data never passes silently |

`artifacts/demo.xml` keeps each full report as a JUnit property.

!!! note "If the build stops at `apt-get update`"
    The first build installs Debian packages from `deb.debian.org`. Networks or
    proxies that block that host make the build fail at this step, before any
    test runs. Retry from a network that can reach it.

## 3. Open a rendered report

The demo prints JSON. To see the report a person reads, download a released
example bundle and open its `report.html`. You do not need Docker for this step.

```sh
# Release that publishes the example bundles
BASE=https://github.com/Living-Proof-Labs/capability-verifier/releases/download/v1.3.0
# The baseline (passing) example bundle
BUNDLE=capability-verifier-v1.3.0-baseline-22ce11f3-4bbe-5ee8-b0cf-a357ad5e41a8-amd64-40284818922-1.zip

# Download the bundle and the published checksums
curl -fsSLO "$BASE/$BUNDLE"
curl -fsSLO "$BASE/BUNDLE-SHA256SUMS"

# Check the download; this prints "...zip: OK"
sha256sum --check --ignore-missing BUNDLE-SHA256SUMS

# Unpack into ./baseline
unzip -q "$BUNDLE" -d baseline
```

On macOS, use `shasum -a 256 --check --ignore-missing BUNDLE-SHA256SUMS`. Open `baseline/report.html` in a browser.
It shows one result, `PASS`, under the `all-required-v1` policy, with the reason
"All required assessments pass with verified evidence". The same folder holds
`report.txt`, `report.json` and `report.csv`, plus the manifest, evidence,
provenance and checksums behind them.

## Next steps

- Learn the vocabulary in [Concepts](vision.html#glossary).
- See how one observation can [meet one requirement and fail another](vision.html#see-it-today).
- Pick a [guide for your role](guides.md).
