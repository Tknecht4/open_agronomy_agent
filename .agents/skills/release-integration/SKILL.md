---
name: release-integration
description: Compose and verify Open Agronomy fixes in an isolated integration checkout, prepare source-safe pull requests and maintain exact release evidence.
---

Establish the remote identity, current main SHA, checkout branch/dirty state and
assigned paths before composing changes. Reuse a suitable isolated checkout;
never include another lane's dirty science or historical receipts. Coordinate
overlapping paths with their owners and preserve their sealed commits.

Measure actual free disk and outstanding reservations before checkout changes,
tests or packaging. Borrow cached tools read-only where appropriate, and state
that limitation. Follow the native builder's own space floor for a build;
source tests or replacement frontend assets cannot qualify an old packaged backend.

Integrate the smallest complete fix, check its active consumer through
`server/services/chat_service.py::execute_agent_request` or the actual frontend
entrypoint, and test the exact composed candidate. Require independent review
for integration defects. Tests of an alternate shell cannot substitute for
production-entrypoint coverage. Search imports, CLI, dynamic registry, config,
container and documentation consumers before retiring a code island.

For routine public scope checks use `scripts/build_public_repository.py --check`.
Use `--verify --receipt <new-json-path>` when materialization itself needs
checking; reserve `--destination` for a downstream consumer needing a retained
tree. Keep raw answers, private logs, user data and unlicensed source snapshots
out of the public tree. Regenerate shared inventories after source edits settle.

Link a major issue's reproduction and acceptance criteria to its attempted fix,
tested commit and PR. Follow branch protection and the task's existing merge,
deployment and release authorization. A passing source check, a merged PR and an
installed native app are separate qualifications. Record exact commits and CI
results, and name remaining gaps without rewriting prior evidence.
