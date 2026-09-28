"""Rerun six previously observed, model-free METHOD consumer spot checks.

This receipt is a rerun: the first terminal spot checks were not serialized.
It uses only existing question fixtures and the non-active candidate profile.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess

from agronomy_agent.agent import build_context
from agronomy_agent.method_context import requested_methods, reviewed_method_ids


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
CONTRASTS = HERE / "method-contrasts.json"
EXPOSED = ROOT / "data/eval/production_foundations_method_holdout_v3.jsonl"
PROFILE = ROOT / "configs/rag_production_foundations_method_candidate.yaml"
OUTPUT = HERE / "method-consumer-results.json"
IDS = ("T06", "E09", "E12", "M02", "PFMH3-05", "PFMH3-06")
SOURCE_FILES = (
    "src/agronomy_agent/method_context.py",
    "src/agronomy_agent/decision_contract.py",
    "src/agronomy_agent/query_context.py",
    "src/agronomy_agent/evidence_contracts.py",
    "src/agronomy_agent/agent.py",
    "configs/rag_production_foundations_method_candidate.yaml",
    "data/manifests/runtime_corpus_policy_production_foundations_method_candidate.json",
    "data/manifests/production_foundations_method_support_v2.json",
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    contrast_rows = {row["id"]: row for row in json.loads(CONTRASTS.read_text())["cases"]}
    exposed_rows = {row["id"]: row for row in (json.loads(line) for line in EXPOSED.read_text().splitlines())}
    cases = []
    for case_id in IDS:
        source = CONTRASTS if case_id in contrast_rows else EXPOSED
        row = (contrast_rows if source == CONTRASTS else exposed_rows)[case_id]
        question = row["question"]
        context = build_context(
            question,
            rag_config=str(PROFILE.relative_to(ROOT)),
            use_context_cache=False,
            use_search_cache=False,
        )
        contract = context.runtime_metadata["decision_contract"]
        packet = context.runtime_metadata["evidence_fabric"]["evidence_packet"]
        cards = []
        for doc in context.retrieved_docs:
            if doc.answer_role != "method_context":
                continue
            scope = doc.method_scope or {}
            cards.append({
                "doc_id": doc.doc_id,
                "text_sha256": hashlib.sha256(doc.text.encode()).hexdigest(),
                "reviewed_method_ids": list(reviewed_method_ids(doc)),
                "answer_role": doc.answer_role,
                "transfer_scope": doc.transfer_scope,
                "retrieval_policy": doc.retrieval_policy,
                "authority_tier": doc.authority_tier,
                "jurisdictions": list(doc.jurisdictions),
                "source_jurisdictions": list(doc.source_jurisdictions),
                "supporting_source_ids": list(doc.supporting_source_ids),
                "method_scope": scope,
            })
        cards.sort(key=lambda card: card["doc_id"])
        coverage = [
            {"slot_key": item["slot_key"], "status": item["status"],
             "required_authority": item["required_authority"], "reasons": list(item["reasons"])}
            for item in packet["coverage"] if item["slot_key"].startswith("method:")
        ]
        applicability = [
            {"methods": list(item["methods"]), "transfer_status": item["transfer_status"],
             "capture_status": item["capture_status"]}
            for item in packet["applicability"] if item.get("methods")
        ]
        cases.append({
            "id": case_id,
            "fixture": str(source.relative_to(ROOT)),
            "question": question,
            "question_sha256": hashlib.sha256(question.encode()).hexdigest(),
            "expected_original": row.get("expected", row.get("method")),
            "selected_families": list(requested_methods(question)),
            "country": context.runtime_metadata["query_context"].get("country"),
            "method_obligations": [
                {"key": item["key"], "authority": item["authority"],
                 "retrieval_terms": list(item["retrieval_terms"])}
                for item in contract["evidence_obligations"] if item["key"].startswith("method:")
            ],
            "contract_retrieval_queries": list(contract["retrieval_queries"]),
            "final_method_cards": cards,
            "method_applicability": applicability,
            "method_coverage": coverage,
        })
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    output = {
        "status": "model_free_rerun_of_unserialized_spot_checks_exploratory_not_heldout",
        "reason_for_rerun": "Original six terminal observations were not retained as a structured receipt; this repeats exactly those six question fixtures on the pinned source.",
        "rerun_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": head,
        "profile": str(PROFILE.relative_to(ROOT)),
        "fixture_sha256": {str(path.relative_to(ROOT)): sha(path) for path in (CONTRASTS, EXPOSED)},
        "source_sha256": {path: sha(ROOT / path) for path in SOURCE_FILES},
        "question_ids": list(IDS),
        "case_count": len(cases),
        "model_generation_executed": False,
        "cases": cases,
    }
    OUTPUT.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"status": output["status"], "git_head": head, "case_count": len(cases),
                      "observations": [{"id": case["id"], "selected": case["selected_families"],
                                        "obligations": [item["key"] for item in case["method_obligations"]],
                                        "cards": [item["doc_id"] for item in case["final_method_cards"]]}
                                       for case in cases]}, indent=2))


if __name__ == "__main__":
    main()
