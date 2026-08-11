from __future__ import annotations

import hashlib
from typing import Any

from agronomy_agent.server.services.chat_service import run_turn
from agronomy_agent.server.services.retrieval_service import retrieve_only
from agronomy_agent.server.services.router_service import route_query
from agronomy_agent.server.settings import ServerSettings
from agronomy_agent.server.storage.db import TraceStore


def _hash_text(value: Any) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def _normalize_route(route_payload: Any) -> dict[str, Any]:
    return {
        "question_type": route_payload.get("question_type"),
        "risk_level": route_payload.get("risk_level"),
        "namespaces": list(route_payload.get("namespaces", [])),
        "required_tools": list(route_payload.get("required_tools", [])),
        "query_expansion": list(route_payload.get("query_expansion", [])),
        "answer_style": route_payload.get("answer_style"),
        "audience": route_payload.get("audience"),
        "guidance": route_payload.get("guidance"),
    }


def _normalize_retrieved_docs(docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for doc in docs:
        normalized.append(
            {
                "doc_id": doc.get("doc_id"),
                "title": doc.get("title"),
                "source": doc.get("source"),
                "source_type": doc.get("source_type"),
                "rank": doc.get("rank"),
                "score": doc.get("score"),
                "snippet": doc.get("snippet", ""),
                "tags": list(doc.get("tags", [])),
            },
        )
    return normalized


def _coerce_int(value: Any, default: int, *, name: str) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be integer") from exc
    if parsed <= 0:
        raise ValueError(f"{name} must be positive")
    return parsed


def _merge_context(base: dict[str, Any], updates: dict[str, Any] | None) -> dict[str, Any]:
    if not updates:
        return base
    merged = dict(base)
    for key, value in updates.items():
        if value is not None:
            merged[key] = value
    return merged


def _resolve_mode(base_turn: dict[str, Any], override_mode: str | None) -> str:
    base_system = base_turn.get("system_state", {}) or {}
    return override_mode or base_system.get("mode", "mock")


def _resolve_model_id(base_turn: dict[str, Any], mode: str, override_model: str | None, default_model_id: str) -> str | None:
    if mode == "mock":
        return "mock"
    return override_model or base_turn.get("system_state", {}).get("model_id") or default_model_id


def _build_system_state(base_turn: dict[str, Any], *, mode: str, model_id: str | None, rag_config: str | None, prompt_version: str) -> dict[str, Any]:
    system_state = {
        "mode": mode,
        "model_id": model_id or "mock",
        "rag_config": None if mode == "baseline" else rag_config,
        "prompt_version": prompt_version,
        "latency_ms": 0,
    }
    if mode == "mock":
        system_state["model_id"] = "mock"
    if model_id is not None:
        system_state["model_config_hash"] = _hash_text(model_id)
    if rag_config:
        system_state["rag_config_hash"] = _hash_text(rag_config)
    base_system = base_turn.get("system_state", {}) or {}
    corpus_audit_id = base_system.get("corpus_audit_id")
    if corpus_audit_id:
        system_state["corpus_audit_id"] = corpus_audit_id
    return system_state


def _build_objectives(trace: dict[str, Any], latency_ms: int) -> dict[str, Any]:
    return {
        "safety": 1.0,
        "route_correctness": 1.0,
        "tool_use": 1.0 if trace.get("tool_invocations") else 0.5,
        "retrieval_support": 0.0 if not trace.get("retrieved_docs") else min(1.0, len(trace["retrieved_docs"]) / 5.0),
        "latency_ms": latency_ms,
    }


def _build_delta(base_turn: dict[str, Any], replayed_turn: dict[str, Any], *, pipeline: str) -> dict[str, Any]:
    base_state = base_turn.get("system_state", {}) or {}
    replay_state = replayed_turn.get("system_state", {}) or {}
    delta: dict[str, Any] = {"pipeline": pipeline}
    fields = ["mode", "model_id", "rag_config"]
    for key in fields:
        base_val = base_state.get(key)
        replay_val = replay_state.get(key)
        if base_val != replay_val:
            delta[key] = {"base": base_val, "replay": replay_val}
    return delta


def _build_replay_delta(
    base_turn: dict[str, Any],
    replayed_turn: dict[str, Any],
    *,
    pipeline: str,
    max_tokens: int,
    top_k: int | None = None,
) -> dict[str, Any]:
    delta = _build_delta(base_turn, replayed_turn, pipeline=pipeline)
    delta["max_tokens"] = max_tokens
    if top_k is not None:
        delta["top_k"] = top_k
    return delta


def _create_replay_turn(
    *,
    store: TraceStore,
    base_turn: dict[str, Any],
    session_id: str,
    message: str,
    pipeline: str,
    trace: dict[str, Any],
    mode: str,
    model_id: str | None,
    rag_config: str | None,
    prompt_version: str,
) -> dict[str, Any]:
    system_state = _build_system_state(
        base_turn,
        mode=mode,
        model_id=model_id,
        rag_config=rag_config,
        prompt_version=prompt_version,
    )
    turn_id = store.create_turn(
        session_id=session_id,
        user_message=f"[{pipeline} replay] {message}",
        answer=f"Replay ({pipeline}): {message}",
        parent_turn_id=base_turn.get("turn_id"),
        system_state=system_state,
        trace=trace,
        objectives=_build_objectives(trace, 0),
        feedback={"rating": None, "accepted": None, "failure_tags": [], "evidence_feedback": []},
        prompt_messages=None,
        metadata={"replay_mode": pipeline},
        event_stream=True,
    )
    turn = store.get_turn(turn_id) or {}
    if not turn:
        raise ValueError("failed to persist turn")
    turn["turn_id"] = turn_id
    return turn


def replay_turn(
    *,
    store: TraceStore,
    settings: ServerSettings,
    base_turn_id: str,
    override: dict[str, Any],
) -> dict[str, Any]:
    base_turn = store.get_turn(base_turn_id)
    if not base_turn:
        raise ValueError("base turn not found")
    session_id = base_turn.get("session_id")
    if not session_id:
        raise ValueError("base turn missing session")

    if override.get("override_session_context"):
        session = store.get_session(session_id)
        if session:
            context = _merge_context(session.get("context", {}), override["override_session_context"])
            store.update_session(session_id, context=context)

    pipeline = override.get("pipeline", "full")
    if pipeline not in {"full", "route_only", "retrieve_only", "answer_only"}:
        raise ValueError(f"unsupported replay pipeline: {pipeline}")

    mode = _resolve_mode(base_turn, override.get("mode"))
    model_id = _resolve_model_id(base_turn, mode, override.get("model_id"), settings.default_model_id)
    rag_config = override.get("rag_config", base_turn.get("system_state", {}).get("rag_config"))
    max_tokens = _coerce_int(override.get("max_tokens", 360), default=360, name="max_tokens")
    top_k = None
    if override.get("top_k") is not None:
        top_k = _coerce_int(override.get("top_k"), default=5, name="top_k")
    trace_options = override.get("trace_options", {}) or {}
    message = base_turn["user_message"]
    pipeline_top_k = None

    if pipeline == "route_only":
        route_payload = route_query(message)
        normalized_route = _normalize_route(route_payload)
        trace = {
            "route": normalized_route,
            "coverage_checklist": [],
            "retrieved_docs": [],
            "graph_hits": [],
            "tool_invocations": [],
            "prompt_messages": [],
            "metadata": {"replay_mode": pipeline},
        }
        replay_turn_record = _create_replay_turn(
            store=store,
            base_turn=base_turn,
            session_id=session_id,
            message=message,
            pipeline=pipeline,
            trace=trace,
            mode=mode,
            model_id=model_id,
            rag_config=rag_config,
            prompt_version=settings.prompt_version,
        )
    elif pipeline == "retrieve_only":
        retrieve_top_k = top_k if top_k is not None else 5
        pipeline_top_k = retrieve_top_k
        retrieval = retrieve_only(message, top_k=retrieve_top_k, rag_config=rag_config or settings.default_rag_config)
        route_payload = _normalize_route(retrieval.get("route", {}) or route_query(message))
        docs = _normalize_retrieved_docs(list(retrieval.get("retrieved_docs", [])))
        trace = {
            "route": route_payload,
            "coverage_checklist": [],
            "retrieved_docs": docs,
            "graph_hits": [],
            "tool_invocations": [],
            "prompt_messages": [],
            "metadata": {
                "replay_mode": pipeline,
                "doc_count": len(docs),
                "top_doc_score": max((doc.get("score", 0.0) for doc in docs), default=0.0),
                "top_k": retrieve_top_k,
            },
        }
        replay_turn_record = _create_replay_turn(
            store=store,
            base_turn=base_turn,
            session_id=session_id,
            message=message,
            pipeline=pipeline,
            trace=trace,
            mode=mode,
            model_id=model_id,
            rag_config=rag_config,
            prompt_version=settings.prompt_version,
        )
    else:
        output = run_turn(
            store=store,
            settings=settings,
            session_id=session_id,
            message=message,
            mode=mode,
            model_id=model_id,
            rag_config=rag_config or settings.default_rag_config,
            max_tokens=max_tokens,
            trace_options=trace_options,
            parent_turn_id=base_turn_id,
        )
        replay_turn_record = output.get("turn")
        if not replay_turn_record:
            raise ValueError("failed to persist turn")

    return {
        "turn_id": replay_turn_record["turn_id"],
        "turn": replay_turn_record,
        "base_turn": base_turn,
        "config_delta": _build_replay_delta(
            base_turn,
            replay_turn_record,
            pipeline=pipeline,
            max_tokens=max_tokens,
            top_k=(
                pipeline_top_k
                if pipeline_top_k is not None
                else (top_k if override.get("top_k") is not None else None)
            ),
        ),
    }
