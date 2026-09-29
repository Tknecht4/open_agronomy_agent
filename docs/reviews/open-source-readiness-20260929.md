# Open-source readiness implementation

Status: implementation candidate; independent review and remote CI pending. Authorized by the maintainer after the farmOS comparison.
Baseline: `2c3e84217155d99cb082b784a82e60356deaec7e`.

## Scope and acceptance

| Obligation | Implementation boundary | Acceptance evidence |
|---|---|---|
| Protect contributions without locking out a solo maintainer | GitHub main rules, restricted Actions tokens, documented review policy | Fresh API reads; required checks from the reviewed PR |
| Give users and contributors a usable intake path | Contributing, support, conduct, security, issue/PR templates, ownership | Links, public-package inclusion, manual content review |
| Maintain dependency security | Reviewed automated updates and Python advisory CI | Audited declared environment and fail-closed CI check |
| Measure and separate distribution payloads while preserving evidence | Public allowlist, size budgets, content-addressed split packaging | Exact inventory, hashes, round-trip reconstruction, adversarial archive tests |
| Keep desktop release claims accurate | Release/recovery documentation | Signing, notarization, downloaded-app launch and upgrade qualification remain explicit gates |

The active runtime/corpus and frozen experiments retain their identities. No
farmOS code is copied. A smaller developer distribution is not a qualified
smaller Mac installer, and publishing a release requires its release gates.

## Working conditions and resource plan

The primary checkout contains unrelated geospatial work. A managed worktree
creation failed with `ENOSPC`; an isolated local clone was populated using APFS
copy-on-write files, checked against committed Git blob identities. Only dirty
source files were replaced from the committed object database in the candidate.
The original checkout was not edited. Local disk headroom is under 1 GiB.

Plan: owner plus two bounded implementation workers, followed by one independent
Astra review. Initial envelope: approximately 45–75 minutes including local
checks and remote CI; no paid model evaluation or new dataset downloads. Actual
provider cost is unavailable. Checkpoint after contributor and packaging
candidates; if resource limits interfere, keep evidence and use clean CI for
large installation/build checks rather than deleting retained data. Do not run
a full local Mac build with insufficient scratch space.

## Verification and remaining work

Implemented contributor/support/security/conduct guidance, ownership and issue/PR
forms, bounded weekly dependency updates, installed-environment Python scanning,
and an always-running documentation check. The main branch now requires PRs,
current backend/frontend checks, and resolved conversations even for admins.
Force pushes and deletion are disabled. Discussions, private vulnerability
reporting, secret scanning, push protection, and dependency security updates
were enabled and fresh-read through GitHub's API. The documentation `build`
check will be required after the unconditional workflow is integrated.

The initial installed inventory contained 136 third-party distributions. The
scanner reported affected `cryptography==46.0.7` and `datasets==4.8.5` (duplicate
advisory aliases retained in the raw diagnostic). An isolated replacement with
`cryptography==50.0.1` and `datasets==5.0.1` satisfied their installed dependency
requirements and cleared all reported advisories. Current declarations and Mac
constraints now require those patched lines; the original live environment was
not modified. The first scanner attempt used unsupported system Python, and a
later empty-inventory attempt was rejected as validation. CI explicitly checks
that the exported inventory is nonempty and fails on audit errors/findings.

Local focused validation: 38 tests passed across the public builder, split
packaging, public docs, field-LAN certificates, and knowledge-update trust.
Strict MkDocs and the rendered-site audit passed. The public builder was
exercised by the focused tests and the real split build. The first real split
candidate contained 1,286 files / 1,058,688,791 bytes, in a 5,202,624-byte source
archive and 115,793,578-byte evidence archive. Its independently recorded plan
digest was `94d3b1f99ca1d1f0775754722dad207e02999ec605275e014701fa2afc45758d`;
streamed verification passed. These measurements precede final documentation
and review repairs; they are not an installer-size or final-release claim.

The split command preserves every selected public file and executable modes,
requires a separately trusted plan digest, and rejects malformed inventories,
links, traversal, duplicate/missing/extra files, digest drift, and oversized
expansion. A full-tree input budget of 1.1 GB makes growth explicit. CI also
reconstructs the real archives and audits the restored runtime corpus.

Remaining acceptance: independent review, full PR backend/frontend/docs checks,
fresh Mac qualification for dependency changes, and integration verification.
The source/evidence split does not make the NRCS pack optional at runtime,
rewrite Git history, or reduce the installed Mac bundle. Those require a
separate compatibility-preserving corpus migration and installer qualification.
Developer ID signing/notarization and an installed-app upgrade/rollback drill
remain required before a downloadable desktop release. Bounded field-history
APIs, broader typed operation/outcome schemas, and farmOS integration remain
separately scoped follow-ups, not implied by this hardening package.

