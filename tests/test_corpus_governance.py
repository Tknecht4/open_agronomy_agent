import hashlib
import json
from pathlib import Path

from agronomy_agent.agno_runtime.local_index import RetrievedDoc
from agronomy_agent.corpus_governance import (
    CORPUS_AUDIT_IMPLEMENTATION_PATHS,
    audit_runtime_corpora,
    filter_docs_by_corpus_governance,
    load_corpus_policy,
    partition_runtime_corpus_paths,
)
from agronomy_agent.security_evidence import validate_implementation_binding


ROOT = Path(__file__).resolve().parents[1]


def _doc(path: str, *, doc_id: str = "doc") -> RetrievedDoc:
    return RetrievedDoc(
        doc_id=doc_id,
        title="title",
        text="text",
        source="source",
        score=1.0,
        tags=(),
        namespaces=(),
        source_type="applied_guidance",
        allowed_roles=(),
        corpus_path=str(ROOT / path),
    )


def test_runtime_corpus_manifest_hashes_and_rows_are_valid() -> None:
    for config_name in ("rag_governed_runtime_v1.yaml", "rag_final_mvp.yaml"):
        report = audit_runtime_corpora(root=ROOT, rag_config_path=ROOT / "configs" / config_name)
        assert report["status"] == "pass", report["errors"]
        assert report["configured_corpus_count"] == report["audited_corpus_count"] == 23
        validate_implementation_binding(
            report["implementation_binding"],
            expected_paths=CORPUS_AUDIT_IMPLEMENTATION_PATHS,
        )
        assert report["corpus_file_counts_by_eligibility"]["quarantined"] > 0
        assert report["row_counts_by_eligibility"]["decisive"] > 0
        assert report["row_counts_by_eligibility"]["context_only"] > 0
        assert report["row_counts_by_eligibility"]["requires_live_authority"] > 0
        v13 = next(
            row
            for row in report["corpora"]
            if row["path"] == "data/derived/rag/canada_agronomy_distributable_v13.jsonl"
        )
        assert v13["effective_eligibility_counts"] == {
            "context_only": 706,
            "requires_live_authority": 12,
        }


def test_quarantined_forum_and_eval_gap_rows_never_enter_context() -> None:
    policy = load_corpus_policy(ROOT, "data/manifests/runtime_corpus_policy.json")
    docs = [
        _doc("data/derived/rag/forum_newagtalk_forum_threads_rag_corpus.jsonl", doc_id="forum"),
        _doc("data/seed/aiagribench_public_gap_corpus.jsonl", doc_id="eval-gap"),
        _doc("data/derived/rag/canada_agronomy_distributable_v13.jsonl", doc_id="government"),
    ]
    allowed, blocked = filter_docs_by_corpus_governance("Explain crop rotation.", docs, policy)
    assert [doc.doc_id for doc in allowed] == ["government"]
    assert {row["doc_id"] for row in blocked} == {"forum", "eval-gap"}


def test_runtime_loader_indexes_only_policy_registered_non_quarantined_corpora() -> None:
    policy = load_corpus_policy(ROOT, "data/manifests/runtime_corpus_policy.json")
    configured = [
        "data/seed/agronomy_rag_corpus.jsonl",
        "data/derived/rag/document_expansion_rag_corpus.jsonl",
        "data/seed/aiagribench_public_gap_corpus.jsonl",
        "data/not_registered.jsonl",
        ROOT / "data/derived/rag/canada_agronomy_distributable_v13.jsonl",
    ]

    loadable, excluded = partition_runtime_corpus_paths(configured, policy)

    assert loadable == [
        "data/seed/agronomy_rag_corpus.jsonl",
        ROOT / "data/derived/rag/canada_agronomy_distributable_v13.jsonl",
    ]
    assert {row["path"] for row in excluded} == {
        "data/derived/rag/document_expansion_rag_corpus.jsonl",
        "data/seed/aiagribench_public_gap_corpus.jsonl",
        "data/not_registered.jsonl",
    }
    assert next(
        row for row in excluded if row["path"] == "data/not_registered.jsonl"
    )["reason"] == "missing_policy_entry"


def test_high_consequence_context_allows_only_decisive_corpora() -> None:
    policy = load_corpus_policy(ROOT, "data/manifests/runtime_corpus_policy.json")
    docs = [
        _doc("data/seed/agronomy_rag_corpus.jsonl", doc_id="synthesis"),
        _doc("data/derived/rag/nrcs_esd_rag_corpus_compact.jsonl", doc_id="regional"),
        _doc("data/derived/rag/canada_agronomy_distributable_v13.jsonl", doc_id="government"),
    ]
    allowed, blocked = filter_docs_by_corpus_governance("What nitrogen rate should I apply?", docs, policy)
    assert [doc.doc_id for doc in allowed] == ["government"]
    assert {row["reason"] for row in blocked} == {"not_decisive_for_high_consequence"}


def test_superseded_v8_corpus_is_explicitly_quarantined() -> None:
    policy = load_corpus_policy(ROOT, "data/manifests/runtime_corpus_policy.json")
    docs = [
        _doc(
            "data/derived/rag/canada_agronomy_distributable_v8.jsonl",
            doc_id="rights-superseded",
        )
    ]

    allowed, blocked = filter_docs_by_corpus_governance("Explain crop rotation.", docs, policy)

    assert allowed == []
    assert blocked[0]["doc_id"] == "rights-superseded"
    assert blocked[0]["runtime_eligibility"] == "quarantined"


def test_context_only_supplement_cannot_support_a_high_consequence_action() -> None:
    policy = load_corpus_policy(ROOT, "data/manifests/runtime_corpus_policy.json")
    docs = [
        _doc(
            "data/derived/rag/canada_agronomy_supplement_v1.jsonl",
            doc_id="historical-potato-supplement",
        )
    ]

    allowed, blocked = filter_docs_by_corpus_governance(
        "What exact nitrogen rate should I apply to my potato field?",
        docs,
        policy,
    )

    assert allowed == []
    assert len(blocked) == 1
    assert blocked[0]["doc_id"] == "historical-potato-supplement"
    assert blocked[0]["runtime_eligibility"] == "context_only"
    assert blocked[0]["reason"] == "not_decisive_for_high_consequence"


def test_shadow_contract_can_retain_context_only_without_promoting_it() -> None:
    policy = load_corpus_policy(ROOT, "data/manifests/runtime_corpus_policy.json")
    docs = [
        _doc(
            "data/derived/rag/canada_agronomy_supplement_v1.jsonl",
            doc_id="historical-potato-supplement",
        )
    ]

    allowed, blocked = filter_docs_by_corpus_governance(
        "What exact nitrogen rate should I apply to my potato field?",
        docs,
        policy,
        allow_context_only_support=True,
    )

    assert [doc.doc_id for doc in allowed] == ["historical-potato-supplement"]
    assert blocked == []


def test_bilingual_and_regional_context_additions_remain_non_decisive() -> None:
    policy = load_corpus_policy(ROOT, "data/manifests/runtime_corpus_policy.json")
    docs = [
        _doc(
            "data/derived/rag/canada_agronomy_supplement_v2.jsonl",
            doc_id="french-federal-context",
        ),
        _doc(
            "data/derived/rag/canada_agronomy_regional_context_v1.jsonl",
            doc_id="provincial-regional-context",
        ),
        _doc(
            "data/derived/rag/canada_agronomy_ontario_context_v1.jsonl",
            doc_id="ontario-crop-statistics",
        ),
    ]

    allowed, blocked = filter_docs_by_corpus_governance(
        "Quel taux exact d'azote dois-je appliquer dans ce champ?",
        docs,
        policy,
    )

    assert allowed == []
    assert {row["doc_id"] for row in blocked} == {
        "french-federal-context",
        "provincial-regional-context",
        "ontario-crop-statistics",
    }
    assert {row["runtime_eligibility"] for row in blocked} == {"context_only"}
    assert {row["reason"] for row in blocked} == {"not_decisive_for_high_consequence"}


def test_manitoba_2026_scouting_candidate_remains_non_decisive() -> None:
    policy = load_corpus_policy(ROOT, "data/manifests/runtime_corpus_policy.json")
    docs = [
        _doc(
            "data/derived/rag/canada_agronomy_supplement_v3.jsonl",
            doc_id="mb-2026-scouting-candidate",
        )
    ]

    allowed, blocked = filter_docs_by_corpus_governance(
        "Should I spray this Manitoba canola field at the flea beetle threshold?",
        docs,
        policy,
    )

    assert allowed == []
    assert blocked[0]["runtime_eligibility"] == "context_only"
    assert blocked[0]["reason"] == "not_decisive_for_high_consequence"


def test_unreviewed_provincial_standard_rows_fail_the_runtime_audit(
    tmp_path: Path,
) -> None:
    (tmp_path / "configs").mkdir()
    (tmp_path / "data" / "manifests").mkdir(parents=True)
    corpus_path = tmp_path / "data" / "provincial.jsonl"
    policy_path = tmp_path / "data" / "policy.json"
    queue_path = (
        tmp_path
        / "data"
        / "manifests"
        / "provincial_applied_guidance_admission_queue_20260724.json"
    )
    config_path = tmp_path / "configs" / "rag.yaml"
    row = {
        "doc_id": "mb-unreviewed",
        "source_id": "mb-unreviewed",
        "source": "https://example.invalid/mb",
        "source_type": "applied_guidance",
        "jurisdiction": ["Manitoba"],
        "retrieval_policy": "standard",
    }
    corpus_path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    policy_path.write_text(
        json.dumps(
            {
                "schema_version": "open_agronomy_agent.runtime_corpus_policy.v1",
                "default_eligibility": "quarantined",
                "corpora": [
                    {
                        "path": "data/provincial.jsonl",
                        "sha256": hashlib.sha256(corpus_path.read_bytes()).hexdigest(),
                        "runtime_eligibility": "decisive",
                        "evidence_tier": "government_applied_guidance",
                        "rights_status": "redistributable",
                        "reason": "synthetic governance test",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    queue_path.write_text(
        json.dumps(
            {
                "schema_version": (
                    "open_agronomy_agent.provincial_applied_guidance_queue.v1"
                ),
                "recommendation_grade_active_provinces": 0,
                "recommendation_grade_active_jurisdictions": [],
                "rows": [
                    {
                        "jurisdiction": "Manitoba",
                        "admission_state": (
                            "candidate_pending_independent_agronomist"
                        ),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    config_path.write_text(
        "\n".join(
            (
                "retrieval:",
                "  artifact_root: ..",
                "  corpus_policy_manifest: data/policy.json",
                "  corpus_paths:",
                "    - data/provincial.jsonl",
            )
        )
        + "\n",
        encoding="utf-8",
    )

    report = audit_runtime_corpora(root=tmp_path, rag_config_path=config_path)

    assert report["status"] == "fail"
    assert report["provincial_applied_guidance_boundary"][
        "unreviewed_standard_decisive_rows_by_jurisdiction"
    ] == {"Manitoba": 1}
    assert "unreviewed_provincial_decisive_rows:Manitoba:1" in report["errors"]

    queue_path.unlink()
    missing_queue = audit_runtime_corpora(
        root=tmp_path, rag_config_path=config_path
    )
    assert missing_queue["status"] == "fail"
    assert any(
        error.startswith("invalid_provincial_admission_queue:")
        for error in missing_queue["errors"]
    )

    row["retrieval_policy"] = "context_only"
    corpus_path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy["corpora"][0]["sha256"] = hashlib.sha256(
        corpus_path.read_bytes()
    ).hexdigest()
    policy_path.write_text(json.dumps(policy), encoding="utf-8")

    repaired = audit_runtime_corpora(root=tmp_path, rag_config_path=config_path)

    assert repaired["status"] == "pass"
    assert repaired["provincial_applied_guidance_boundary"]["gate_passed"] is True
