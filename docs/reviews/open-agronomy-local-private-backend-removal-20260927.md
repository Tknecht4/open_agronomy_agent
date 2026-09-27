# Local-private backend removal

**Branch:** `codex/remove-hosted-backends`  
**Starting commit:** `d7794feea78f9230a5c1d5f1e7a9b7b50e5c3914`

## Decision

Open Agronomy Agent no longer offers Redis-backed queues or rate limiting, or
S3-compatible artifact storage. Those paths were early scale-out scaffolding
and do not belong in the local-private product. Application artifacts remain
under the operator-selected local filesystem root, request limiting remains
in process memory, and ingest job state remains in the configured application
database (SQLite by default).

## Evidence before removal

Observation:

- Redis was selectable through server settings and supplied a socket-level
  protocol client, fixed-window limiter, five remote queues, a preflight CLI,
  fail-open controls, and remote branches in attachment, evaluation, export,
  image, and ingest routes.
- S3 was selectable through server settings and supplied signing, request,
  bucket preflight, and object round-trip code.
- The standalone worker existed to consume remote queues. The local UI already
  exposes an authenticated run endpoint for queued local ingestion; evaluation,
  export, image, and attachment paths otherwise execute in the application.
- Neither backend had a supported deployment profile or live-service receipt.

Interpretation:

The remote implementations were not helping the local runtime or small-model
answer path. Retaining them enlarged the configuration, security, operational,
and test surface while suggesting a deployment mode the project had explicitly
chosen not to support.

## Removed

- Redis protocol, rate limiter, queue implementation, preflight, fail-open
  controls, queue names, endpoint branches, and container environment knobs.
- S3 signing/client/preflight implementation, credentials and endpoint
  settings, selection branches, and container environment knob.
- The standalone queue worker and queue-only service helpers.
- Direct tests that existed solely to characterize the retired remote paths.

## Retained local contracts

- `FixedWindowRateLimiter` with a fixed `memory` backend identity.
- `LocalObjectStore`, rooted beneath the configured artifact directory with
  path-escape protection and owner-only directories/files.
- SQLite-local ingest job records and the explicit authenticated run endpoint.
- Existing queue-related database tables and normalization code so old local
  databases remain readable. This round performs no destructive schema
  migration.
- Historical receipts remain unchanged even when they name files present in an
  older source snapshot.

Retired namespaced backend environment variables fail closed and name every
stale variable without echoing credential values. Generic third-party
environment variables are ignored because this application no longer consumes
them.

## Scope boundary

This decision removes Redis/S3 scale-out infrastructure. It does not silently
rewrite historical benchmark identities, delete local account/workspace data,
or claim that other compatibility interfaces are newly deployment-qualified.
Any later decision about the schema-checked Postgres or identity-provider
interfaces requires its own consumer, migration, and privacy review.

## Verification plan

The owner performs one focused local-boundary pass, one complete backend suite,
frontend type checking/tests/build, strict documentation audits, generated
runtime-manifest validation, and a manifest-selected public-package build. A
fresh independent Astra reviewer must accept the exact committed candidate
before it can merge. No paid external service or live Redis/S3 instance is
required or authorized for this removal.

## Local verification results

- Package inventory: 118 Python modules and 104,627 Python lines.
- Test inventory: 89 files, 726 explicit test functions, and 1,016 collected
  cases.
- Complete backend suite: 1,016 passed in 134.73 seconds with Starlette
  deprecations promoted to errors. Retained log SHA-256:
  `5d1bc9ca556e29b11b2fca269c12a16cd336ee021e2d163f8840bf5a05f98991`.
- Frontend: 205 tests, type checking, and production build passed.
- Public documentation source/render audits and strict MkDocs build passed.
- Edge package validation passed with current contract
  `e33f48adb45408627958e76c46405b0a241ca0a3d263b58e7ade335b4a2e0fc8`.
- The first public-package attempt exhausted temporary disk while copying the
  checked-in NRCS pack. After removing only task-generated temporary trees, the
  809-file package passed. Its external receipt is retained separately so this
  included review does not create a self-referential package hash.

## Acceptance repairs

Independent review rejected the first committed candidate because its
`job_queue` status hard-coded `sqlite-local` even though the separately retained
database compatibility layer can select Postgres, and because a one-byte source
formatting repair occurred after runtime-manifest generation. Runtime responses
now describe ingest as `database-recorded`, include the actual database backend,
and limit the local-only claim to artifact storage and rate limiting. The
runtime manifest was then regenerated and validated before rebuilding the
public package.

The public-package builder deliberately regenerates
`container/runtime_manifest.json` inside the curated destination so that its
runtime-asset digest binds the 809-file public tree rather than the larger
source checkout. Its receipted manifest hash therefore differs from the source
manifest by design; it must match the generated file inside that package.
