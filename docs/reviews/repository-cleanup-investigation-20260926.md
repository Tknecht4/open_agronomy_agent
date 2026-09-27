# Repository cleanup investigation

**Branch:** `codex/public-repo-cleanup`  
**Starting commit:** `7a341115f48f568153d95f467933a3602b305281`

## Purpose

Make the public repository easier to understand, install, test, and maintain
without deleting governed data, frozen evidence, or optional operator code on
the basis of a shallow reference count.

## Baseline inventory

- 152 Python modules and approximately 116,963 Python lines under
  `src/agronomy_agent`.
- 87 Python test files with 717 explicit test functions and 992 collected test
  cases after parametrization.
- 116 scripts, 83 configuration files, and 104 documentation files.
- Approximately 987.9 MiB of tracked data versus 5.3 MiB of package source.
- Largest modules: `server/app.py` (7,375 lines), `server/storage/db.py`
  (6,131), `answer_verifier.py` (5,317), `agent.py` (5,030), and
  `chat_service.py` (4,907).

These counts are navigation signals, not deletion criteria.

## Evidence classes

### Remove now: disconnected research islands

The following areas were introduced in the initial public checkpoint, have no
current caller, test, console entry point, active config, or supported docs,
and are superseded by active paths:

- legacy Agno comparison/promotion/ingestion adapters (active ingestion uses
  `agno_runtime/source_ingest.py`);
- the optional LFM prompt-router shadow and its alternate route-decision
  candidate (the live route remains deterministic and registry-planned);
- quarantined Decision Card matcher/index code (the retained evaluation lane
  consumes frozen cases, not these modules);
- unused Phase 5 context-ablation, hardening, judge, latency, and release
  report generators; and
- applied-guidance promotion/reviewer machinery with no CLI, caller, tests, or
  documented operator workflow.

Historical receipts may still name removed files because they describe an
older immutable source snapshot. That is expected and must not be rewritten.

Phase 1 and the follow-up unsupported-surface pass removed 29 modules and
10,522 Python lines from these islands, plus two experiment-only requirement
files, one unused gate matrix, and one broken readiness script. The complete
backend suite still collected and passed all 992 tests; no test was removed.
This confirms that the deleted code was outside every current collected test
contract, while also documenting that those proposed features never had
supported coverage.

### Investigate before removal

| Area | Why it looks stale | Why it is not safe to delete yet |
|---|---|---|
| Hosted worker, Redis/object-store preflights | No direct tests or public operator guide | Container/hosted deployment intent and service functions exist |
| Backup transaction guard | Broader encrypted/readiness scaffold was removed | `server/storage/backup.py` remains active because database startup checks pending restore state |
| Training/SFT utilities | Not used by product runtime | Intentional offline maintainer tooling; needs license/output review before retirement |
| Large historical scripts/configs | Referenced mainly by frozen receipts/public manifest | Some are reproduction inputs; archive policy must precede moves |

## Priority investigation map

1. **Harness parity:** provide one canonical real executor for the v3 matrix or
   retire the model-backed execution claim. The current retained comparison
   still uses the legacy text-agent evaluator.
2. **Verifier dependence and reproducibility:** explain the 98–100/241 Gemma 4
   fallback/degraded cases and 27 non-repeatable full-system cases before
   changing prompts or thresholds.
3. **Large-module ownership:** split app, storage, agent, verifier, and chat
   service only at stable public seams with characterization tests.
4. **Test value:** map each test to a public contract/failure mode; consolidate
   duplicate fixtures and source-text assertions, but retain negative,
   authority, privacy, and frozen-identity regressions.
5. **Repository weight:** replace the 218,258-row NRCS pack and BM25 statistics
   with a versioned, content-addressed release/dataset install path before
   removing the checked-in copy.
6. **Configuration layout:** add an index/status registry first. Moving frozen
   configs would invalidate paths and hashes; active/historical separation can
   begin through documentation and loaders.
7. **Operator surfaces:** either document and test hosted worker, backup,
   Redis, object-store, and recovery commands or remove their unsupported
   public-readiness language.

## Test cleanup method

For each candidate test:

1. state the contract and failure it catches;
2. identify another test, if any, that exercises the same public seam;
3. temporarily remove or mutate the controlling implementation and confirm
   which test fails;
4. consolidate only when the replacement still catches the mutation; and
5. rerun the owning focused suite plus the full suite.

Removing a test because production still passes once is not evidence that the
test has no value. Conversely, a test that only freezes source text should be
replaced by a behavioral or AST contract when practical.

The initial normalized-AST comparison found four superficially duplicate test
groups. Review showed they are parametrized regulated-language cases or
source/jurisdiction-specific admission contracts. No test was removed: merging
those cases would reduce the visible failure identity without reducing runtime
or fixture complexity materially. Three files currently assert source/AST
structure directly (`test_evals.py`, the v2 runner contract, and the router
capability-mutation guard); these should be replaced only when an equivalent
behavioral seam can detect the same forbidden regression.

## Documentation plan

- Keep `README.md` as installation/status/claims overview.
- Keep `ARCHITECTURE.md` as the maintainer and AI-agent code map.
- Keep `AGENTS.md` as concise repository-working rules.
- Keep supported behavior in `docs/public/`; dated investigations and public-
  safe receipts belong in `docs/reviews/`.
- Move historical papers/evidence to release assets only through a manifest-
  preserving archival change, not ad hoc deletion.

## Acceptance for this cleanup round

- full backend/frontend/documentation/public-package gates pass;
- active product and benchmark entry points import and run their focused tests;
- removed code has no live or dynamic consumer;
- frozen receipts remain byte-unchanged;
- the public docs state what is active, historical, candidate, or unsupported;
  and
- any residual risk has an owner, evidence gap, and next discriminating check.

## Phase 1 verification

- `python -m compileall -q src scripts`: passed.
- full backend suite: 992 passed, one upstream deprecation warning.
- public documentation source audit: passed.
- a general backend/frontend CI workflow was added because the repository had
  only a documentation workflow despite using the full local suite as a merge
  gate.

The follow-up pass removed an incomplete security/recovery readiness island
whose sole CLI referenced five absent drill scripts/tests, plus unreachable
demo, deployment-readiness, and persisted-path migration modules. Active backup
transaction checks, storage backends, and hosted worker/preflight code were
retained for an explicit operator-surface review.
