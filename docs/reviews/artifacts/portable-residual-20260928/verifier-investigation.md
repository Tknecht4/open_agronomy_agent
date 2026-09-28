# Answer verifier stress contrasts

Status: project-authored exploratory investigation, 2026-09-28. No runtime selector, verifier, test, config, model, or source data was changed.

## Reference and fixture seal

The inspected seam is `assess_claim_risk` in `src/agronomy_agent/answer_verifier.py` at Git HEAD `3ff64813ce14833f3c819044b96ebda738a60cbe`. The 12 [contrast fixtures](verifier-contrasts.json) supply explicit answer, question, question type, risk level, and evidence text; `evidence_docs=()` isolates the verifier's local claim checks. Their expected review labels were written before the first probe call. The fixture SHA-256 recorded before execution was `762ce116080a19750cdf07825f5c19d119e8788feff417b78b57e9c971dcf4f6`. This is an authored development seal, **not** a held-out or source-distinct assessment.

The read-only [probe](verifier_probe.py) saved every returned `ClaimRiskAssessment` in [verifier-results.json](verifier-results.json), with source hashes and the original fixture hash. Six of twelve review decisions agreed with the authored labels; three were false negatives and three false positives relative to those labels. These counts describe this small stress set only, not field error rates or a product-quality estimate.

| Contrast | Authored expectation | Observed `assess_claim_risk` |
|---|---|---|
| N01: source `120 kg`, answer `20 kg` | Review wrong value | No review; no unsupported number |
| N02: source and answer `120 kg` | Accept control | Accepted |
| A01: 12 bags × 25 kg = 300 kg | Accept correct derivation | Review: `unsupported_numeric_specificity` for `300`, plus `incomplete_generation` |
| A02: 12 bags × 25 kg called 25 kg total | Review wrong total | No review |
| A03: 12 bags × 25 kg called 250 kg | Review wrong total | Review: unsupported `250`, plus `incomplete_generation` |
| L01: “Spot the mismatch,” explicitly calls `20 kg` an error | Accept correction | Accepted |
| L02: “Spot the mismatch,” asserts `20 kg` as shipment mass | Review wrong value | No review |
| D01: gray leaf spot conditional, confirmation requested | Accept bounded possibility | Review for missing decision content and route anchor; no diagnostic-certainty reason |
| D02: possible gray leaf spot asserted as diagnosis | Review | Review, including `unsupported_diagnostic_certainty` |
| D03: lab ruled out gray leaf spot; answer says diagnosis is *not* gray leaf spot | Accept negated statement | Review, including `unsupported_diagnostic_certainty` |
| R01: “You can spray now because...” without current label | Review | Review for `unsupported_regulated_permission` |
| I01: punctuation-only `...` | Review incomplete output | Review for `incomplete_generation` |

## Mechanisms and boundaries

Numeric support is presently substring membership: `_unsupported_values` normalizes an answer number and asks whether that string occurs anywhere in the concatenated question and evidence. Thus `20 kg` occurs within `120 kg`; source-number reuse also lets the incorrect 25 kg total through. The check cannot validate a relation such as *12 bags × 25 kg/bag = total*. Conversely, the correct derived 300 kg is marked unsupported because it is absent verbatim. `A01` and `A03` also receive `incomplete_generation` because `_looks_incomplete` treats the terminal `300.` or `250.` as a dangling numbered-list marker. These are separable failures: number grounding and output-shape parsing.

The phrase “Spot the mismatch” does not by itself establish whether a number is endorsed. L01 and L02 differ in assertion meaning, yet the current number check accepts both because of the `20 kg` substring. `D03` exposes another scope problem: `_DIAGNOSIS_ASSERTION_RE` matches “The diagnosis is” before the negation and `_diagnosis_is_supported` does not inspect that negation. D01's review result is **not** evidence of a conditional-diagnosis-specific bug: its reasons are missing-content and route-anchor checks. D02, R01, and I01 show that the positive diagnostic, regulated-permission, and incomplete-output controls do trigger review in these fixtures. High-consequence cases acquire an additional `high_consequence_claim_review` reason after any other reason.

The smallest candidate for further testing is a typed claim check that separates extracted quantity and unit spans from source substrings, records which input quantities support a derived result, and checks the arithmetic relation where a registered deterministic calculator exists. It should also retain clause-level assertion polarity and modality, so a correction or negated diagnosis is distinct from an endorsed claim. Keep the current regulated-permission and incomplete-output gates as independent controls. This is a proposed interface and evaluation direction, not a patched verifier or demonstrated gain. A fresh independent set should include unit changes, ranges, source numbers embedded inside other numbers, rounding, quoted counterclaims, and partial outputs.

## Claim-edit ledger is an audit of global trigger presence

`_claim_edit_ledger` splits the draft into sentences, marks each sentence absent from the final answer as changed, and assigns **every** defect record to **every** changed sentence. It does not prove which sentence violated which rule. The separate synthetic helper call in `verifier-results.json` changed two sentences: a source-supported `120 kg` statement and an unsupported spray permission. Both received the single regulated-permission defect ID. This demonstrates global attribution in the ledger, not a localized defect proof about the supported sentence. `replacement_has_named_defect` confirms that at least one defect was named when replacement occurred; it does not validate per-claim localization.

## Retained Qwen PFMH3-12 diagnostic reconstruction

The retained compressed Qwen ledger has the active-arm PFMH3-12 question, draft text and hash, document IDs and snippets, and the historical draft assessment. It does **not** retain exact full verifier evidence text or historical full document text hashes. The probe used the same question with the current `configs/rag.yaml` and `build_context`, then assessed the retained draft with reconstructed evidence. All five document IDs matched in order; all five retained snippets matched prefixes of the reconstructed documents. The current full document hashes and reconstructed evidence-text hash are recorded in `verifier-results.json`, but no retained full-text hashes exist for byte comparison. The reconstructed assessment record equalled the retained assessment: `unsupported_numeric_specificity` for `2 to 4 inches`, `unsupported_named_condition` for `rot`, and `incomplete_generation`, score 8. The draft ends mid-sentence after “This adjustment immediately reduces”, so incompleteness is directly visible. This is a **consistent local model-free reconstruction**, not an exact replay of historical verifier evidence, editor generation, fallback selection, or model behavior.

## Checks and limits

- `PYTHONPATH=src .venv/bin/python docs/reviews/artifacts/portable-residual-20260928/verifier_probe.py` completed; its JSON includes all 12 inputs, exact observed assessments, source/fixture hashes, the separate ledger demonstration, and the bounded Qwen reconstruction.
- `PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_risk_conditioned_selective_v3.py tests/test_answer_verifier_exam_review.py` passed: 10 focused tests. Those tests do not establish correctness on these newly authored contrasts.
- No answer editor, model generation, remote call, deployment, or active-profile mutation occurred. The Qwen ledger is exposed historical evidence; neither it nor these authored fixtures qualify activation or efficacy.

Changed | Contrast fixtures, read-only probe, results, this note. Verified | 12 exact assessment returns, 10 focused tests, bounded retained-draft reconstruction. Residual Risk | Authored labels, incomplete historical verifier evidence, no outcome test. Memory Delta | None.
