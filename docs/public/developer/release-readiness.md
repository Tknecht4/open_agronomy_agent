# Release-candidate checkout gates

Run benchmark release candidates only from a clean committed checkout. The gate below separates repository identity, dependency observation, implementation tests, documentation rendering, and public-package scope. Passing it does not establish agronomic performance and does not authorize a benchmark run.

## Dependency boundary

`frontend/package-lock.json` supplies an exact npm resolution. The Python requirement files currently declare compatible ranges rather than a complete, hash-locked transitive environment. Replacing those declarations with a lock generated from one Apple Silicon machine would overstate portability, so this release records the exact installed Python packages instead.

`capture_release_environment.py` creates that observation receipt without filesystem paths or secrets. It must remain described as **one observed environment, not a portable Python lock**. A benchmark run must retain the receipt and its hash with the model, code, configuration, and run identities.

`build_runtime_sbom.py` remains a deterministic source-level dependency inventory. Its Python entries are direct range declarations; it is not an image-level or installed-environment SBOM.

The checked-in `Containerfile` currently names upstream base-image tags rather than immutable registry digests. The checkout and SBOM gates hash that file but do not turn those tags into reproducible image identity. Any published OCI release must separately retain the resolved base and final image digests plus an image-level SBOM; the local benchmark receipt must describe the host environment actually used rather than implying it ran in that container.

## Exact clean-checkout validation

From a fresh checkout at the intended commit, create the exercised Python environment and install all test and documentation declarations before capturing it:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install \
  --requirement requirements.txt \
  --requirement requirements-phase4-ci.txt \
  --requirement requirements-docs.txt
.venv/bin/python -m pip install --editable .
```

These commands resolve the declared Python ranges at that time; they do not create a portable lock. From the repository root, after the intended changes have been committed:

```bash
git status --porcelain=v1 --untracked-files=all
```

The command must print nothing. Then capture the installed environment and audit it against the same commit and dependency inputs:

```bash
PYTHONPATH=src .venv/bin/python scripts/capture_release_environment.py \
  --output outputs/release/release_environment.json

PYTHONPATH=src .venv/bin/python scripts/audit_release_candidate_checkout.py \
  --require-clean \
  --environment-receipt outputs/release/release_environment.json
```

The checkout audit must report `"status": "pass"`. It fails on dirty state, an untracked public-manifest input, dependency-input drift, a stale/different commit receipt, or a receipt that hides the range-only Python boundary.

Run the implementation and generated-documentation gates:

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q

cd frontend
npm ci
npm run typecheck
npm test
npm run build
cd ..

PYTHONPATH=src .venv/bin/python scripts/check_public_docs.py
PYTHONPATH=src .venv/bin/mkdocs build --strict
PYTHONPATH=src .venv/bin/python scripts/check_public_docs.py \
  --site-dir build/docs-site
```

Build the curated public tree and source-level dependency inventory into ignored outputs:

```bash
OAA_RC_TMP="$(mktemp -d)"
PYTHONPATH=src .venv/bin/python scripts/build_public_repository.py \
  --destination "$OAA_RC_TMP/public-release"

PYTHONPATH=src .venv/bin/python scripts/build_runtime_sbom.py \
  --output outputs/release/open_agronomy_agent.spdx.json
```

Finally rerun the clean-checkout audit. Build products are ignored; any source-tree mutation or newly untracked release input must still block:

```bash
PYTHONPATH=src .venv/bin/python scripts/audit_release_candidate_checkout.py \
  --require-clean \
  --environment-receipt outputs/release/release_environment.json
```

Record the commit, environment-receipt SHA-256, public-package receipt, SBOM SHA-256, test counts, and any warnings in the benchmark release-candidate record. A later dependency, source, configuration, model, or code change requires a new receipt and a new gate run.

## RC3 development-rerun preflight

`configs/final_benchmark_round_rc3.json` is not a v3 release contract. It plans
three declared trials for each of three candidates on the
exposed-and-used-for-system-tuning 241-case internal suite under the active
cumulative runtime-v2 knowledge contract and labels the round
`development_rerun_nonclaim`. Every trial has explicit generation,
verification, case-order, and judge seeds; the plan requires a fresh process,
no prompt cache, and a unique output/invocation identity. AgroQA v1 is retired
after RC1 exposure and the preflight must emit no external-diagnostic command.
RC1 and RC2 remain frozen historical identities.

The judge seed is retained only as an inert replication identity;
`judge_seed_application=not_requested`. RC3 disables automated semantic judging,
has no judge egress class, rejects any supplied judge calibration, and emits no
`--judge` option.

After the clean-checkout, environment, public-package, full-test, documentation,
and source-retention gates pass, run:

```bash
PYTHONPATH=src .venv/bin/python scripts/audit_final_benchmark_readiness.py \
  --plan configs/final_benchmark_round_rc3.json \
  --hub-cache /absolute/path/to/huggingface/hub \
  --egress-authorization /absolute/path/to/authorized_egress_receipt.json \
  --public-release-root "$OAA_RC_TMP/public-release" \
  --environment-receipt outputs/release/release_environment.json \
  --output outputs/release/rc3_preflight.json
```

The checked-in `configs/benchmark_egress_authorization.template.json` is
intentionally unauthorized and expired; it cannot be used to make this gate
pass. A human-controlled schema-v4 receipt must be bound to benchmark ID
`open_agronomy_canadian_performance_v1_runtime_v2`, the exact internal suite,
the exact suite-case application-message contract, the active public
runtime-artifact contract, and the static-prompt contract. It must be currently
valid in UTC and exactly match the plan's
`payload_classes_by_phase_and_arm` map:

| Phase and arm | Authorized payload classes, in order |
|---|---|
| candidate raw | project-owned frozen question |
| candidate baseline | project-owned frozen question; system/answer-contract prompt |
| candidate kernel | project-owned frozen question; system/answer-contract prompt; synthetic field context |
| candidate RAG | project-owned frozen question; system/answer-contract prompt; synthetic field context; selected public runtime document excerpts; public runtime graph evidence |
| verification RAG | project-owned frozen question; system/answer-contract prompt; selected public runtime document excerpts; candidate draft; verifier evidence |

The receipt's global authorized taxonomy uses the exact machine names
`project_owned_frozen_benchmark_questions`,
`benchmark_system_and_answer_contract_prompts`, `synthetic_eval_field_context`,
`selected_public_release_runtime_document_source_excerpts`,
`public_release_runtime_graph_evidence`, `candidate_drafts_for_verification`,
and `verifier_evidence`. It must exactly
exclude `farmer_records`, `private_field_history`, `credentials`, and
`whole_local_knowledge_corpus_files`.

The preflight independently rebuilds all three v4 contract hashes and rejects
a plan or human receipt that merely supplies self-consistent labels. Candidate
application messages must match the case-and-arm hash byte-for-byte before the
App Server starts. The App Server text-only transport control is receipted
separately from those application messages. Deterministic tools remain local
and bypass Luna; governed guard notes are static prompt content, not an
authorized tool-result class.

The preflight also requires the plan's private-knowledge policy. The runner
forces `AGRONOMY_AGENT_PRIVATE_KNOWLEDGE=disabled` and passes
`--private-knowledge-policy disabled` to every child evaluation. A configured
runtime profile that permits private knowledge outside this benchmark does not
override this benchmark invariant. Supplying `--judge-calibration` is an RC3
failure, not a way to enable advisory judging.

A successful audit emits nine unique internal commands: three models by three
trials. Each emitted command includes `--resume-partial-runs` and
`--reuse-complete-runs`; either path still fails unless the stored invocation
has exact substantive identity, and reuse additionally requires a valid
complete-run receipt. The audit performs no generation or judging and
authorizes only the declared non-claim rerun. Do not execute a planned command
if the preflight status is not `ready`, if an output has an incompatible or
unreceipted state, or if source/config/model identity changed after the receipt.

Before an expensive matrix, retain one claim-ineligible rehearsal through the
same typed server core used by the cockpit and validate all 17 ordered stage
receipts. For retrieval isolation, execute the same fixed question under
`retrieval_neither`, `retrieval_document_only`, `retrieval_graph_only`, and
`retrieval_both`, changing only the named retrieval configuration. This 2×2 is
instrumentation QA; it is not a v3 benchmark outcome.

## Sealed-v3 human gates

The public v3 protocol is a fail-closed design contract. It does not include a
plaintext or sealed evaluation cohort. Its model-free audit must remain blocked
while only the checked-in templates exist:

```bash
PYTHONPATH=src .venv/bin/python scripts/audit_open_agronomy_benchmark_v3_readiness.py \
  --commitment configs/open_agronomy_benchmark_v3_holdout_commitment.template.json \
  --judge-calibration configs/benchmark_judge_calibration.template.json \
  --output outputs/release/v3_governance_audit.json
```

Only a private, independently authored and reviewed, hash-committed holdout with
an access/exposure record can close the holdout gate. Only a real human-labeled
calibration package that passes the preregistered quality and order-sensitivity
thresholds can close the judge gate. Human egress authorization is a third,
separate gate. Passing tests, replacing placeholder digests, or having model
access closes none of them.

A later topology or answer-affecting feature change also requires compatibility
review. The v3 protocol currently binds the exact ordered 17-stage
`open_agronomy_agent.production_stage_topology.v3`; silent stage drift is a
release blocker and may require a new benchmark cohort.
