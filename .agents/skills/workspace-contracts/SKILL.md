---
name: workspace-contracts
description: Change the production Open Agronomy workspace request, field-save or recovery flow with shared server planners, authorization and durable operation checks.
---

Read the current branch, dirty state, assigned paths and nearest server/frontend
README. Trace the active consumer from `frontend/src/main.tsx` to
`OpenAgronomyApp`, then `server/app.py` to `execute_agent_request`; an alternate
shell's tests do not establish production behavior.

Use canonical server planners for capability readiness. A preview authenticates
and authorizes before private reads, creates no turn/session receipt, and binds
the exact question, model/profile, saved field and conversation head. Submission
reauthorizes and checks freshness under the session guard. Keep synchronous
guard waits off the API event loop. Qualify each deterministic bypass against
actual execution with generator construction forbidden; planner intent alone
is insufficient numeric validation.

Preserve late user edits across save acknowledgments. Unsaved field/map context
must keep Ask blocked. Ignore stale preview responses and register operation
UUIDs only at dispatch. Test actual persisted retries, changed-payload conflicts,
queued-history changes, cancellation before dispatch and interrupted recovery
with synthetic state. Historical answers and stored receipts remain immutable.

Use cached focused API/UI checks while iterating. State whether transport is
mocked and whether a native package was actually exercised. Complete public
manifest and shared inventory updates through the integration owner. See the
[workspace guide](../../../docs/public/operations/workspace.md) and
[server contracts](../../../src/agronomy_agent/server/README.md).
