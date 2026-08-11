from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from scripts import evaluate_evidence_fabric_equivalence as equivalence


def test_equivalence_gate_checks_exact_prompt_context_and_document_order(
    tmp_path: Path, monkeypatch
) -> None:
    messages = [
        {"role": "system", "content": "Be accurate."},
        {"role": "user", "content": "unchanged context\n\nField question:\nWhat should I scout?"},
    ]
    outputs = tmp_path / "outputs.jsonl"
    row = {
        "eval_id": "case-1",
        "question": "What should I scout?",
        "answer_profile": "benchmark",
        "eval_field_context": {"crop_current": "canola"},
        "metadata": {
            "retrieved_doc_ids": ["doc-1"],
            "benchmark_generation_input": {
                "messages": messages,
                "context_block": "unchanged context",
            },
        },
    }
    outputs.write_text(json.dumps(row) + "\n", encoding="utf-8")
    rag_config = tmp_path / "rag.yaml"
    model_config = tmp_path / "model.yaml"
    rag_config.write_text("{}\n", encoding="utf-8")
    model_config.write_text("{}\n", encoding="utf-8")
    context = SimpleNamespace(
        retrieved_docs=[SimpleNamespace(doc_id="doc-1")],
        packed_context=SimpleNamespace(text="unchanged context"),
        runtime_metadata={"evidence_fabric": {"status": "captured", "evidence_packet": {"packet_id": "packet-1"}}},
    )
    monkeypatch.setattr(equivalence, "load_agent_resources", lambda _path: object())
    monkeypatch.setattr(equivalence, "build_messages", lambda *_args, **_kwargs: (messages, context))

    report = equivalence.evaluate(
        reference_outputs=outputs,
        rag_config=rag_config,
        model_config=model_config,
        sample_count=1,
    )

    assert report["status"] == "pass"
    assert report["comparisons"][0]["checks"] == {
        "messages_exact": True,
        "context_block_exact": True,
        "selected_document_order_exact": True,
        "fabric_captured": True,
    }
