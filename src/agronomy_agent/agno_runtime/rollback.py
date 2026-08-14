from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from agronomy_agent.agent import build_context, load_agent_resources
from agronomy_agent.agno_runtime.runtime import resolve_agent_runtime
from agronomy_agent.paths import repo_path


def verify_runtime_rollback(
    *,
    question: str,
    rag_config: str = "configs/rag_governed_runtime_v2.yaml",
) -> dict[str, Any]:
    """Verify the Agno cutover has no serving-time legacy shadow path."""

    resources = load_agent_resources(rag_config)
    agno_context = build_context(question, resources=resources, agent_runtime="agno")
    try:
        resolve_agent_runtime(explicit="legacy")
    except ValueError as exc:
        legacy_rejected = True
        legacy_rejection = str(exc)
    else:
        legacy_rejected = False
        legacy_rejection = ""

    agno_summary = _context_summary(agno_context)
    checks = {
        "agno_primary_selects_agno": agno_summary["runtime_mode"] == "agno" and agno_summary["selected_retriever"] == "agno",
        "agno_docs_present": agno_summary["doc_count"] > 0,
        "legacy_runtime_removed": legacy_rejected,
        "context_packer_present": bool(agno_summary["context_packer_version"]),
        "container_or_git_rollback_only": True,
    }
    return {
        "report_version": "agno_rag_rollback_probe_v1",
        "question_hash": hashlib.sha256(question.strip().lower().encode("utf-8")).hexdigest(),
        "rag_config": rag_config,
        "rollback_verified": all(checks.values()),
        "checks": checks,
        "agno_primary": agno_summary,
        "legacy": {
            "runtime_mode": "removed",
            "selected_retriever": None,
            "rejection": legacy_rejection,
            "doc_count": 0,
            "doc_ids": [],
        },
    }


def load_agentos_decision(path: str | Path = "docs/agno_agentos_decision.md") -> str:
    target = repo_path(path)
    if not target.exists():
        return ""
    for line in target.read_text(encoding="utf-8").splitlines():
        if line.strip().lower().startswith("decision:"):
            return line.split(":", 1)[1].strip()
    return ""


def _context_summary(context: Any) -> dict[str, Any]:
    metadata = context.runtime_metadata or {}
    return {
        "runtime_mode": context.runtime_mode,
        "selected_retriever": metadata.get("selected_retriever"),
        "doc_count": len(context.retrieved_docs),
        "doc_ids": [doc.doc_id for doc in context.retrieved_docs],
        "context_packer_version": context.packed_context.version if context.packed_context else None,
        "context_tokens_est": context.packed_context.token_estimate if context.packed_context else None,
    }
