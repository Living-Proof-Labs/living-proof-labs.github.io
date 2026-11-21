<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Working agreement

Read [collaboration-guidelines v6.0.0](https://github.com/Living-Proof-Labs/collaboration-guidelines/blob/v6.0.0/AGENTS.md)
and relevant procedures at that tag before work. The inspected tag resolves to
52a2f274576dab20e96ee1152b6c8d187cfbf377.

Keep this a small documentation directory. Manuals remain in their own repositories.
Use your own authorized GitHub identity; do not use another contributor's account.
Use a draft pull request and independent agent review before merge.

## Bounded exceptions

The root is a documentation-only Zensical site that publishes a pinned revision of
the organization pages authored in Living-Proof-Labs/.github (`docs/site.json`).
Do not add or edit organization content here; change it in .github, then move
`content.lock.json` to the merged commit. Task generates the contributor reference from actual commands. Docker supplies the
locked build/browser environment; CI uses those tasks and publishes only the
verified artifact. Do not add application packaging for this editorial site. Publisher releases on
verified `main` use the shared semantic-release workflow after Pages deployment
succeeds, keeping publisher tags distinct from the pinned upstream content
version. Local search covers only the root pages, not remote manuals.

Preserve /vision.html, root section fragments and license-file URLs. GitHub
Actions is the only publication route; the legacy Jekyll fallback was removed
because its page sources moved to .github. Revisit this exception if application behavior is introduced.

Current repository directory links and the current hosted manual are intentional
navigation exceptions to cross-repository version pinning. Keep shared guidance,
downloads and executable examples pinned to published versions. Add a hosted
manual only after checking it live. Do not imply repository links are hosted manuals.

Domain and Pages settings are coordinated separately from content changes.
