---
layout: default
title: Documentation
---
<!-- SPDX-License-Identifier: CC-BY-4.0 -->

# Prove what your robot can do, every software version.

<a id="living-proof-labs-documentation"></a>

<div class="lead" markdown>
Open tools for robotics teams to write capability requirements as user stories,
run them repeatably, and get a traceable report, not an unexplained score.
</div>

<div class="hero-actions" markdown>
[Run the 5-minute demo](quickstart.md){ .md-button .md-button--primary }
[See an example report](quickstart.html#3-open-a-rendered-report){ .md-button }
[Talk to us about a design partnership](https://livingprooflabs.com/#contact){ .hero-tertiary }
</div>

<figure class="hero-report" markdown>
![A capability report row: catalog v1.1.1, revision 1.0.0, status PASS, reason "All required assessments pass with verified evidence".](assets/report-example.png){ loading=lazy }
<figcaption>A real report from the released example bundle.</figcaption>
</figure>

## The problem

Your robot passed yesterday. After today's software update, does it still pause
when asked? Under which conditions? And can you show why? A single score cannot
answer that. You need the requirement, the run and the evidence behind each
result, kept together for every software version.

## How it works

<div class="how-steps" markdown>
<div markdown>
### 1. Write the story
State a capability as a user story with conditions and acceptance criteria.
[Robot capability specifications](https://docs.livingprooflabs.com/robot-capability-specs/)
</div>
<div markdown>
### 2. Run it
Run the scenario repeatably and keep the evidence.
[Capability verifier](https://docs.livingprooflabs.com/capability-verifier/)
</div>
<div markdown>
### 3. Assess the evidence
Check each requirement against the evidence, then grade with an explicit, versioned policy.
[Capability reporter](https://docs.livingprooflabs.com/livingproof-capability-report/)
</div>
<div markdown>
### 4. Read the report
See what passed, what did not, and why, traced back to the evidence.
[Open an example report](quickstart.html#3-open-a-rendered-report)
</div>
</div>

## Available now / Building

<div class="now-building" markdown>
<div markdown>
<span class="badge badge-now">Available now</span>

- Versioned capability specifications
- Deterministic fixtures and recorded or mock assessments
- Explicit, versioned grading policy
- Portable reports you can open in a browser
</div>
<div markdown>
<span class="badge badge-building">Building</span>

- Simulation grading in MuJoCo and Gazebo
- Physical-robot execution at controlled test sites
- Live evaluators
- Automated diagnosis-to-code workflows
</div>
</div>

Reports are evidence for engineering decisions, not safety certification.
[See the roadmap](roadmap.md).

## Who it's for

- Robot software engineers who need to know what a change did to behavior.
- Test and QA leads who need repeatable, explainable results.
- Integrators deploying robots in human spaces who need evidence they can share.

## Choose your path

<div class="reading-paths" markdown>
<div markdown>
### Try it
Go from a fresh clone to a rendered report in the [Quickstart](quickstart.md).
</div>
<div markdown>
### Write capability specs
Turn a behavior into requirements with [robot capability specifications](https://docs.livingprooflabs.com/robot-capability-specs/).
</div>
<div markdown>
### Run verification and read reports
Collect evidence with the [verifier](https://docs.livingprooflabs.com/capability-verifier/) and grade it with the [reporter](https://docs.livingprooflabs.com/livingproof-capability-report/).
</div>
<div markdown>
### Contribute
Learn the [concepts](vision.md), then see [how to contribute](contribute.md).
</div>
</div>

More guides: [guides by role](guides.md).

<a id="livingproof"></a>

## Published manuals

<a id="project-directory"></a>

One row per project. Each manual is independently published; its documentation
source revision may be newer than its package release, so check its Version and
source page before installation. A repository without a manual is listed for
completeness, not as an available integration. Search on this site covers this
page and its local reference pages; open a project's manual to search it.

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
