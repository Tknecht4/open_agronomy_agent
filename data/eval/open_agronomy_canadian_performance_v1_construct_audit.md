# Canadian field benchmark construct audit

## Verdict

The current benchmark is useful development evidence, but it is not an estimate of real-world agronomist-level correctness. The original proxy is retained as regression raw material, not promoted as ground truth.

## Current suite

- 241 total rows; 90 primary semantic field-decision rows; 31 secondary advisory rows.
- 120 rows test regression or interface behaviour and must not be averaged into agronomic answer quality.
- Proven real-user questions: 0.
- Primary multi-turn cases: 0; primary executable geometry payloads: 0.

## Original proxy recovery

- Legacy proxy banks are not packaged in this public checkout. The consolidated 241-case suite remains independently auditable.

## Claims

What it can measure:

- synthetic Canadian field-scenario response behaviour
- kernel, retrieval, evidence-boundary, and safety regressions
- answer-origin and fallback dependence when generation traces are retained

What it cannot measure:

- frequency or distribution of real grower questions
- probability of a correct and useful field recommendation
- field outcomes or economic benefit
- independently certified agronomic correctness

## Required arms

- `raw_model`: user question only.
- `baseline`: raw model plus the Open Agronomy kernel and answer contract.
- `kernel_field_context`: kernel plus the same structured field context admitted to the full-system arm.
- `agronomic_rag`: kernel, governed evidence, deterministic in-process tools and guards, and verifier policy; external service orchestration remains a separate product gate.

## Promotion rule

Do not promote a legacy proxy row into the semantic capability lane without answer-blind source review, case-specific reference claims and material errors, and an independent agronomy reviewer.
