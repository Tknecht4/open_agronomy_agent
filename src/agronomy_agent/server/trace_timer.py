from __future__ import annotations

import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator


PHASE5_PROFILER_SCHEMA_VERSION = "phase5.profiler_span.v1"
PHASE5_TURN_METRICS_SCHEMA_VERSION = "phase5.turn_metrics.v1"


PHASE5_STAGES = (
    "http.request",
    "auth.resolve_user",
    "thread.load",
    "field_context.load",
    "agent.route.classify",
    "agent.rag.lexical_search",
    "agent.kg.search",
    "agent.tools.run_guard_notes",
    "agent.tools.public_adapters",
    "agent.tools.public_label_adapter",
    "agent.tools.public_source_cards",
    "agent.plan.coverage_checklist",
    "agent.context.pack",
    "agent.prompt.build_messages",
    "model.queue_wait",
    "model.load_or_reuse",
    "model.tokenizer.chat_template",
    "model.prefill_to_first_token",
    "model.decode_stream",
    "agent.answer.postprocess",
    "agent.answer.leak_check",
    "thread.persist_trace",
    "ui.stream_response",
    "feedback.capture",
    "export.generate",
)


@dataclass
class TraceSpan:
    trace_id: str
    span_id: str
    stage: str
    start_ns: int
    end_ns: int
    status: str = "ok"
    thread_id: str | None = None
    turn_id: str | None = None
    parent_span_id: str | None = None
    error_type: str | None = None
    error_message_redacted: str | None = None
    input_size: int | None = None
    output_size: int | None = None
    token_estimate_in: int | None = None
    token_estimate_out: int | None = None
    cache_status: str | None = None
    component_version: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_ms(self) -> float:
        return round((self.end_ns - self.start_ns) / 1_000_000, 3)

    def as_record(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "thread_id": self.thread_id,
            "turn_id": self.turn_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "stage": self.stage,
            "start_ns": self.start_ns,
            "end_ns": self.end_ns,
            "duration_ms": self.duration_ms,
            "status": self.status,
            "error_type": self.error_type,
            "error_message_redacted": self.error_message_redacted,
            "input_size": self.input_size,
            "output_size": self.output_size,
            "token_estimate_in": self.token_estimate_in,
            "token_estimate_out": self.token_estimate_out,
            "cache_status": self.cache_status,
            "component_version": self.component_version,
            "metadata": dict(self.metadata),
            "schema_version": PHASE5_PROFILER_SCHEMA_VERSION,
        }


class TraceProfiler:
    """Collects monotonic stage timings for one assistant turn."""

    def __init__(self, *, trace_id: str | None = None, on_span: Callable[[TraceSpan], None] | None = None) -> None:
        self.trace_id = trace_id or str(uuid.uuid4())
        self.started_ns = time.monotonic_ns()
        self.spans: list[TraceSpan] = []
        self.thread_id: str | None = None
        self.turn_id: str | None = None
        self._on_span = on_span

    def set_thread_id(self, thread_id: str | None) -> None:
        self.thread_id = thread_id
        for span in self.spans:
            span.thread_id = span.thread_id or thread_id

    def set_turn_id(self, turn_id: str | None) -> None:
        self.turn_id = turn_id
        for span in self.spans:
            span.turn_id = span.turn_id or turn_id

    @contextmanager
    def span(
        self,
        stage: str,
        *,
        input_size: int | None = None,
        metadata: dict[str, Any] | None = None,
        cache_status: str | None = None,
        component_version: str | None = None,
    ) -> Iterator[TraceSpan]:
        if stage not in PHASE5_STAGES:
            raise ValueError(f"unknown Phase 5 profiler stage: {stage}")
        start_ns = time.monotonic_ns()
        span = TraceSpan(
            trace_id=self.trace_id,
            thread_id=self.thread_id,
            turn_id=self.turn_id,
            span_id=str(uuid.uuid4()),
            stage=stage,
            start_ns=start_ns,
            end_ns=start_ns,
            input_size=input_size,
            metadata=dict(metadata or {}),
            cache_status=cache_status,
            component_version=component_version,
        )
        try:
            yield span
        except Exception as exc:
            span.status = "error"
            span.error_type = exc.__class__.__name__
            span.error_message_redacted = str(exc)[:240]
            raise
        finally:
            span.end_ns = time.monotonic_ns()
            self._record_span(span)

    def add_skipped(self, stage: str, *, reason: str) -> None:
        if stage not in PHASE5_STAGES:
            raise ValueError(f"unknown Phase 5 profiler stage: {stage}")
        now_ns = time.monotonic_ns()
        self._record_span(
            TraceSpan(
                trace_id=self.trace_id,
                thread_id=self.thread_id,
                turn_id=self.turn_id,
                span_id=str(uuid.uuid4()),
                stage=stage,
                start_ns=now_ns,
                end_ns=now_ns,
                status="skipped",
                metadata={"reason": reason},
            )
        )

    def add_observed(
        self,
        stage: str,
        *,
        start_ns: int,
        end_ns: int | None = None,
        status: str = "ok",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if stage not in PHASE5_STAGES:
            raise ValueError(f"unknown Phase 5 profiler stage: {stage}")
        self._record_span(
            TraceSpan(
                trace_id=self.trace_id,
                thread_id=self.thread_id,
                turn_id=self.turn_id,
                span_id=str(uuid.uuid4()),
                stage=stage,
                start_ns=start_ns,
                end_ns=end_ns or time.monotonic_ns(),
                status=status,
                metadata=dict(metadata or {}),
            )
        )

    def _record_span(self, span: TraceSpan) -> None:
        self.spans.append(span)
        if not self._on_span:
            return
        try:
            self._on_span(span)
        except Exception:
            # Progress observers must never affect answer generation or trace persistence.
            return

    def ensure_stages(self, stages: tuple[str, ...] = PHASE5_STAGES) -> None:
        present = {span.stage for span in self.spans}
        for stage in stages:
            if stage not in present:
                self.add_skipped(stage, reason="not_applicable")

    def total_latency_ms(self) -> float:
        end_ns = max((span.end_ns for span in self.spans), default=time.monotonic_ns())
        return round((end_ns - self.started_ns) / 1_000_000, 3)

    def span_records(self) -> list[dict[str, Any]]:
        return [span.as_record() for span in self.spans]
