---
layout: default
title: Documentation
---
<!-- SPDX-License-Identifier: CC-BY-4.0 -->

# Helping robots help humans

<a id="living-proof-labs-documentation"></a>

<div class="lead" markdown>
A capability claim should lead somewhere you can inspect: a requirement, a run,
the evidence behind its assessment, and a useful next step.
**Living Proof Labs is building that connection.**
</div>

[Start the quickstart](quickstart.md){ .md-button .md-button--primary }
[Learn the concepts](vision.md){ .md-button }

A software change can alter what a robot does. We want developers to ask
*“Does it still pause when asked—and under which conditions?”* and follow the
answer from versioned software through a repeatable scenario to an explainable
report. When a result changes, evidence should help people investigate and improve
it, not leave them with an unexplained score.

<div class="reading-paths" markdown>
<div markdown>
### Run the demo
The [quickstart](quickstart.md) takes you from a fresh clone to a rendered report
using recorded fixture data.
</div>
<div markdown>
### Learn the concepts
Follow the [requirement-to-improvement loop](vision.html) and the
[glossary](vision.html#glossary) of specifications, evidence, assessments and policy.
</div>
<div markdown>
### Find your part
Pick a [guide for your role](guides.md), or a [project manual](#published-manuals)
for commands, contracts, execution, reporting or contribution.
</div>
</div>

## From software to a useful next step

**Versioned software and requirements → execution and evidence → separate
assessments → explicit policy → traceable report → investigation and iteration.**

The intended execution paths include repeatable simulation and, eventually,
physical robots in their own controlled environments. Evidence keeps the original
observations and their context. Deterministic checks, human judgment and agentic
evaluation should remain distinguishable; a versioned policy explains how supported
assessments become a grade. Log analysis and coding agents can then help propose
and test changes, while developers retain responsibility for investigating them.

[Walk through the full loop](vision.html#from-a-requirement-to-the-next-improvement)
and [learn what a grade does—and does not—mean](vision.html#evaluation-is-not-diagnosis).

!!! info "Current scope"
    Today, versioned specifications, deterministic fixtures, recorded/mock
    assessments and portable reports demonstrate parts of this loop. Simulation,
    physical-robot execution, live evaluators and automated diagnosis remain
    integration work, and reports do not certify safety. See the
    [roadmap](roadmap.md) for what is available now and what we are building.

Search on this site covers this introduction and its local reference pages.
Open a project's manual to search that project's documentation.

<a id="livingproof"></a>

## Published manuals

<a id="project-directory"></a>

One row per project. Each manual is independently published; its documentation
source revision may be newer than its package release, so check its Version and
source page before installation. A repository without a manual is listed for
completeness, not as an available integration.

<div class="project-table" markdown>

| Project | Manual | Repository | Scope |
| --- | --- | --- | --- |
| [LivingProof](https://docs.livingprooflabs.com/livingproof/) | [Manual](https://docs.livingprooflabs.com/livingproof/) | [livingproof](https://github.com/Living-Proof-Labs/livingproof) | Command entry point and installed plugins |
| [Capability reporter](https://docs.livingprooflabs.com/livingproof-capability-report/) | [Manual](https://docs.livingprooflabs.com/livingproof-capability-report/) | [livingproof-capability-report](https://github.com/Living-Proof-Labs/livingproof-capability-report) | Bundle validation, policy grading and reports |
| [Capability verifier](https://docs.livingprooflabs.com/capability-verifier/) | [Manual](https://docs.livingprooflabs.com/capability-verifier/) | [capability-verifier](https://github.com/Living-Proof-Labs/capability-verifier) | Fixture execution and portable evidence |
| [Robot capability specifications](https://docs.livingprooflabs.com/robot-capability-specs/) | [Manual](https://docs.livingprooflabs.com/robot-capability-specs/) | [robot-capability-specs](https://github.com/Living-Proof-Labs/robot-capability-specs) | Requirements, conditions and acceptance criteria |
| [Common library](https://docs.livingprooflabs.com/livingproof-common/) | [Manual](https://docs.livingprooflabs.com/livingproof-common/) | [livingproof-common](https://github.com/Living-Proof-Labs/livingproof-common) | Shared library interfaces |
| [MuJoCo simulator](https://docs.livingprooflabs.com/livingproof-sim-mujoco/) | [Manual](https://docs.livingprooflabs.com/livingproof-sim-mujoco/) | [livingproof-sim-mujoco](https://github.com/Living-Proof-Labs/livingproof-sim-mujoco) | Standalone native engine example; no capability-pipeline integration implied |
| [Collaboration guidelines](https://docs.livingprooflabs.com/collaboration-guidelines/) | [Manual](https://docs.livingprooflabs.com/collaboration-guidelines/) | [collaboration-guidelines](https://github.com/Living-Proof-Labs/collaboration-guidelines) | Shared contribution and engineering standards |
| [Unitree Foxglove SDK](https://github.com/Living-Proof-Labs/unitree-foxglove-sdk) | No hosted manual | [unitree-foxglove-sdk](https://github.com/Living-Proof-Labs/unitree-foxglove-sdk) | Robot and visualization project; no hosted manual |

</div>

## Help improve the documentation

Report manual corrections in the relevant project. For directory corrections,
[open a directory issue](https://github.com/Living-Proof-Labs/living-proof-labs.github.io/issues).

## Version and source

This directory follows the current default branch; historical rendered copies are
not maintained. Use source history for earlier revisions. Documentation identity
is separate from each project's package or catalog release.

Contributors follow [guidelines v6.0.0](https://github.com/Living-Proof-Labs/collaboration-guidelines/tree/v6.0.0)
and this repository's editorial validation instructions. See
[license scopes](https://github.com/Living-Proof-Labs/living-proof-labs.github.io/blob/main/LICENSE.md). No private security reporting route is documented here.
