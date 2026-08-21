# Open Agronomy Agent fine-tuning data-design review

**Status:** fail-closed design review only. No source, training row, dataset,
adapter, or model artifact is admitted, created, or promoted by this review.

**Date:** 2026-08-13
**Decision owner:** project maintainers, with separate source-rights and
agronomic review for any later training release

## Scope and observed state

This is the separate review required by Phase 5 of the
[compact offline data plan](open-agronomy-compact-offline-data-plan-20260813.md).
It defines the evidence that a future fine-tuning release would need; it does
not alter the Canadian RAG, spatial-source, or existing ML-training contracts.

The present admission result is **zero training-eligible Canadian sources**:

| Evidence inspected | Observed state | Training consequence |
|---|---|---|
| `data/manifests/canada_agronomy_sources.json` | All 45 source records set `use_policy.training: false`, including records allowed for local RAG and redistribution. | No registry source may supply a training row. |
| `data/derived/rag/curated_canada/v1/` | The 952-row, 16-source curated store explicitly says retrieval/redistribution do not authorize training or fine-tuning. | A shard, chunk, retrieval result, or store receipt is not a training input. |
| `data/manifests/canada_offline_source_admission_candidates_v1.json` | All 11 candidates are `candidate_not_admitted`, with `training: false` and `not_assessed_no_training_authorization`. | The queue is discovery metadata only, not a source of bytes or examples. |

Existing generic SFT helpers accept generic datasets and license labels; they
do not implement the ledger below. They must not be treated as a Canadian
source-admission path. A training configuration, a successful preprocessing
run, or an accessible public page is likewise not authorization.

## Future source-rights ledger

A future release must introduce a separate, immutable, reviewable
**training-rights ledger**. It references the source registry but never
overrides it. A row may be considered only when all of the following are true:

1. The exact source is an admitted source-registry record and its current
   `use_policy.training` is explicitly `true`.
2. The ledger binds the exact resource/edition and extracted material by hash,
   and has a current source-specific human approval for the named purpose.
3. The approval covers copying/extraction, transformation, training,
   evaluation, and the intended distribution of the resulting adapter or model
   where applicable.
4. Every stated restriction, attribution, third-party exclusion, geographic
   limit, currency limit, and source-role boundary is represented in the row.

Any missing, expired, revoked, ambiguous, or changed value makes the source
ineligible. A ledger record cannot convert a candidate record to an admitted
source, and an open/re-distributable RAG licence is not a training grant.

| Required ledger field | Required binding or decision |
|---|---|
| `ledger_id`, status, release scope | Unique ID; `approved` only for one named dataset release and stated task family. |
| Source identity | Source-registry ID, canonical source-record hash, publisher, canonical URL, exact resource ID/version/date, and raw/extracted SHA-256s. |
| Material selection | Page/section/table/record selectors, extraction version, excluded ranges, content fingerprints, and a statement of whether verbatim text, a derivative, or a human-authored abstraction is permitted. |
| Rights evidence | Licence/permission snapshot and hash, attribution, commercial/adaptation/training/evaluation/model-distribution decisions, third-party review, reviewer, decision date, and next-review/expiry date. |
| Intended use | Model family, task/prompt purpose, release mode, jurisdictions/languages/crops, and whether a row may teach only routing, abstention, evidence handling, or a bounded agronomic statement. |
| Agronomic boundaries | Authority type, retrieval role, historic/current status, field-vs-regional limitation, required live authority, and falsifiers/conditions requiring local evidence. |
| Audit and revocation | Approval reference, approvers, superseded/revoked links, and the exact event that invalidates the approval (changed source bytes, licence, transformation, purpose, or model distribution). |

The source registry remains the first denial point. The ledger adds a
purpose-specific training decision; it is not a weaker copy of `license` or a
blanket publisher-level assertion.

## Allowed row contract

Future rows must be source-bound records, not unstructured chat JSONL. A row
is eligible only if it contains all of these fields and passes the corresponding
release validator:

| Row field group | Required contract |
|---|---|
| Identity and split | Stable `row_id`, named `training_release_id`, `split`, deterministic `split_group_id`, and normalized `content_fingerprint`. |
| Task and messages | Declared task family and curriculum purpose; complete messages; no hidden context that changes the claimed answer. |
| Source proof | Non-empty ledger IDs plus exact source locators and raw/extracted/content hashes for every factual claim or quoted/derived material. |
| Transformation | Method, version, operator, and input/output hashes. Model-generated drafts require the model/prompt/version and a human factual review; generation never supplies authority. |
| Applicability and limits | Source geography, date/edition, crop/topic, authority/retrieval role, uncertainty, and current-label/local-test/live-authority boundaries carried into the target behavior. |
| Review | Rights review, agronomic/safety review, reviewer identities or approval references, rubric version, and review timestamp. |

There are only three prospective row classes: source-grounded instruction,
project-owned policy/routing behavior, and clearly marked safety or abstention
counterfactuals. The latter two still need an approved author/policy provenance
and human review; they cannot smuggle unsupported agronomic facts into the
dataset. No row may make a regional mapped prior, Census aggregate, or an old
guide appear to be a current field observation, diagnostic result, product
label, or management-rate authority.

## Provenance, split, and evaluation rules

Splits must be assigned before training from a deterministic, recorded mapping.
All paraphrases, translations, summaries, prompt variants, retrieved snippets,
and model-generated derivatives sharing a source edition, source span, fact
cluster, field scenario, or near-duplicate fingerprint must share one
`split_group_id`. Random row-level splitting is prohibited.

The release manifest must record the ledger hash, source-registry hash, input
and output file hashes, source coverage by province/crop/topic/policy role,
split algorithm and seed, group counts, deduplication thresholds, model/prompt
versions used in transformation, and every exclusion. Validation and test
groups must not be used to write prompts, select few-shot examples, tune
hyperparameters, or repair answers. At least one review-defined holdout should
test a genuinely unseen source, edition, region, crop/topic, or time period;
if that coverage is too small, the release is insufficient rather than allowed
to leak groups across splits.

Benchmark, golden-replay, and external evaluation material remain independent
of training data. Their presence in the repository or in a reviewer workflow
does not license their use as examples.

## Hard exclusions

Until a later release clears every gate, exclude:

- all current Canadian source-registry records and every current curated-store
  shard, including rows that are redistributable for RAG;
- all eleven metadata-only candidates, their linked resources, and any
  boundary, SLC, AESD/Census, or DSS derivative;
- public-but-permission-pending university/extension pages, live references,
  third-party figures/tables/images, and material outside an approved selector;
- private overlays; grower, field, customer, user-conversation, telemetry, or
  feedback data; and any personal or confidential information;
- raw RAG retrieval traces, answer transcripts, model self-generated answers
  without approved evidence and review, and source-less synthetic agronomy;
- current-label/product, pesticide, regulatory, economic, and other volatile
  claims presented as timeless instruction; and
- benchmark, test, or validation material, except as independently governed
  evaluation assets that never enter the training split.

Training working bytes must remain physically and policy-separated from the
public curated RAG store. This review grants no right to place training data in
Git, distribute it, or distribute a resulting model artifact.

## Human gates for a future release

1. **Purpose and scope:** maintainers approve a bounded model role, task set,
   model/distribution target, and evaluation design before source selection.
2. **Source rights:** a source-rights reviewer freezes exact bytes and decides
   the complete action set in the ledger. Public availability, an open
   catalogue, or RAG redistribution cannot substitute for this decision.
3. **Material and derivation:** a reviewer verifies selectors, third-party
   exclusions, attribution, extraction/transform lineage, geography, currency,
   and the mapped-prior/context boundary.
4. **Row and split QA:** an agronomic/safety reviewer approves each factual or
   behavioral row class; an independent reviewer validates contamination,
   deduplication, and held-out groups.
5. **Release and training:** maintainers approve the immutable dataset manifest
   and evaluation gate before a training job. A separate decision is required
   before publishing a dataset, adapter, or model.

Any source refresh, licence or permission change, newly found third-party
material, altered transformation, changed task purpose, changed model release
mode, failed evaluation, or revoked approval returns affected rows to
ineligible status. No automated job may promote them.

## Decision for this implementation round

This review deliberately creates no ledger, training rows, JSONL files, model
artifacts, source downloads, source-policy changes, or candidate promotions.
The current `training: false` boundaries remain authoritative. The next action,
if authorized later, is a source-by-source rights decision and a reviewed
ledger proposal—not extraction from the compact Canadian knowledge store.
