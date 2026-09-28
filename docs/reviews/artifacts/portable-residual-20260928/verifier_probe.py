"""Model-free exploratory contrasts for assess_claim_risk; never runtime input."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import subprocess

from agronomy_agent.agent import build_context
from agronomy_agent.answer_verifier import _claim_edit_ledger, assess_claim_risk, context_evidence_text


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
FIXTURE = HERE / "verifier-contrasts.json"
RESULT = HERE / "verifier-results.json"
SOURCE_FILES = (
    "src/agronomy_agent/answer_verifier.py",
    "src/agronomy_agent/decision_route.py",
    "src/agronomy_agent/evidence_handshake.py",
    "src/agronomy_agent/router.py",
    "configs/rag.yaml",
)
RETAINED_QWEN_LEDGER = ROOT / "docs/reviews/artifacts/portable-agronomy-20260928/qwen27b-v4-cells.jsonl.gz"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def reconstructed_qwen_assessment() -> dict:
    """Compare a local evidence reconstruction with a retained assessment.

    The old ledger has snippets and IDs, not full verifier evidence bytes.
    Equality here is diagnostic consistency, not an exact historical replay.
    """
    with gzip.open(RETAINED_QWEN_LEDGER, "rt") as source:
        retained = next(
            json.loads(line)["turns"][0]
            for line in source
            if '"case_id": "PFMH3-12"' in line and '"arm": "active"' in line
        )
    question = retained["question"]
    draft = retained["answer_stages"]["draft"]["text"]
    context = build_context(question, rag_config="configs/rag.yaml", use_context_cache=False, use_search_cache=False)
    evidence_text = context_evidence_text(context)
    observed = assess_claim_risk(
        draft,
        question=question,
        evidence_text=evidence_text,
        question_type=context.route.question_type,
        risk_level=context.route.risk_level,
        evidence_docs=context.retrieved_docs,
        preserve_entities=context.evidence_handshake.preserve_entities if context.evidence_handshake else (),
        required_entities=context.evidence_handshake.required_entities if context.evidence_handshake else (),
    ).as_record()
    retained_docs = retained["retrieved_docs"]
    return {
        "status": "consistent_local_reconstruction_not_exact_historical_replay",
        "limitation": "The retained ledger has document IDs and snippets but not the exact full verifier evidence text or full historical document text hashes.",
        "retained_ledger_path": str(RETAINED_QWEN_LEDGER.relative_to(ROOT)),
        "retained_ledger_sha256": digest(RETAINED_QWEN_LEDGER),
        "case_id": "PFMH3-12",
        "arm": "active",
        "question_sha256": hashlib.sha256(question.encode()).hexdigest(),
        "draft_sha256": hashlib.sha256(draft.encode()).hexdigest(),
        "draft_hash_matches_retained": hashlib.sha256(draft.encode()).hexdigest() == retained["answer_stages"]["draft"]["sha256"],
        "doc_ids_match_in_order": [doc.doc_id for doc in context.retrieved_docs] == [doc["doc_id"] for doc in retained_docs],
        "docs": [
            {"doc_id": doc.doc_id,
             "reconstructed_full_text_sha256": hashlib.sha256(doc.text.encode()).hexdigest(),
             "retained_snippet_is_reconstructed_prefix": old["snippet"] == doc.text[:len(old["snippet"])],
             "retained_full_text_sha256": old.get("chunk_sha256") or old.get("raw_sha256") or None}
            for old, doc in zip(retained_docs, context.retrieved_docs, strict=True)
        ],
        "reconstructed_evidence_text_sha256": hashlib.sha256(evidence_text.encode()).hexdigest(),
        "retained_evidence_text_sha256": None,
        "reconstructed_assessment": observed,
        "recorded_assessment": retained["verification"]["draft_assessment"],
        "assessment_record_equal": observed == retained["verification"]["draft_assessment"],
    }


def main() -> None:
    fixture = json.loads(FIXTURE.read_text())
    ids = [item["id"] for item in fixture["cases"]]
    assert len(ids) == len(set(ids))
    records = []
    counts = Counter()
    for item in fixture["cases"]:
        assessment = assess_claim_risk(
            item["answer"],
            question=item["question"],
            evidence_text=item["evidence_text"],
            question_type=item["question_type"],
            risk_level=item["risk_level"],
            evidence_docs=(),
        )
        observed = assessment.as_record()
        match = observed["requires_review"] == item["expected_review"]
        counts["cases"] += 1
        counts["matches"] += int(match)
        counts["false_negative"] += int(item["expected_review"] and not observed["requires_review"])
        counts["false_positive"] += int(not item["expected_review"] and observed["requires_review"])
        records.append({**item, "observed": observed, "review_label_match": match})

    # This separate helper demonstration does not assert that the assessment
    # has localized a defect to either sentence. It exposes ledger fan-out.
    ledger_draft = "The shipment mass is 120 kg. You can spray now because the forecast is clear."
    ledger_final = "Check the current label and local conditions before any application."
    defect = {
        "defect_id": "illustrative_regulated_permission",
        "reason": "unsupported_regulated_permission",
        "evidence_ids": ["illustrative_label_gap"],
    }
    ledger = _claim_edit_ledger(
        draft=ledger_draft,
        final=ledger_final,
        defect_records=(defect,),
        fallback_applied=True,
        rewrite_accepted=False,
    )
    result = {
        "status": "project_authored_exploratory_model_free_not_heldout",
        "run_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "fixture_sha256": digest(FIXTURE),
        "source_sha256": {path: digest(ROOT / path) for path in SOURCE_FILES},
        "assess_claim_risk_inputs": "answer, question, evidence_text, question_type, risk_level, evidence_docs=()",
        "summary": dict(counts),
        "cases": records,
        "separate_claim_edit_ledger_demonstration": {
            "status": "synthetic_helper_call_not_localized_claim_proof",
            "draft": ledger_draft,
            "final": ledger_final,
            "defect_records": [defect],
            "observed": ledger,
        },
        "retained_qwen_assessment_reconstruction": reconstructed_qwen_assessment(),
    }
    RESULT.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({
        "summary": result["summary"],
        "cases": [{"id": row["id"], "expected": row["expected_review"],
                   "observed": row["observed"]["requires_review"],
                   "reasons": row["observed"]["reasons"],
                   "unsupported_numbers": row["observed"]["unsupported_numbers"]}
                  for row in records],
    }, indent=2))


if __name__ == "__main__":
    main()
