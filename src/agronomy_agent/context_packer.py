from __future__ import annotations

import os
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from agronomy_agent.decision_route import build_decision_route_state
from agronomy_agent.paths import repo_path


DEFAULT_CONTEXT_POLICY_PATH = "configs/context_policy_v1.yaml"
DEFAULT_SOURCE_TYPE_BUDGETS = {"applied_guidance": 4, "boundary": 2, "regional_environment": 2, "ontology": 1}
USER_FIELD_CONTEXT_KEYS = ("crop_current", "region_text", "province_state", "management_notes")
_AAFC_CROP_HEALTH_PRODUCT_RE = re.compile(
    r"(?:\baafc\b.{0,100}\b(?:crop[- ]health (?:index|indices)|crop stress index|crop development stage|growth[- ]stage raster)\b|"
    r"\b(?:crop[- ]health (?:index|indices)|crop stress index)\b|"
    r"\bcrop development stage (?:layer|raster|product|values?)\b|\bgrowth[- ]stage raster\b)",
    re.IGNORECASE,
)


def estimate_tokens(text: str) -> int:
    return max(1, (len(text) + 3) // 4)


def format_user_field_context(field_context: dict[str, Any] | None) -> str | None:
    """Render only the structured user fields admitted to generation.

    Keeping this formatter shared makes the field-context ablation and the full
    context packer directly comparable and prevents metadata-only fields from
    leaking into either prompt.
    """

    active = field_context or {}
    field_bits = [f"{key}: {active[key]}" for key in USER_FIELD_CONTEXT_KEYS if active.get(key)]
    return "Field context: " + "; ".join(field_bits) if field_bits else None


def _trim_to_tokens(text: str, max_tokens: int) -> str:
    if estimate_tokens(text) <= max_tokens:
        return text
    return text[: max(0, max_tokens * 4)].rsplit(" ", 1)[0].strip()


@dataclass(frozen=True)
class ContextSection:
    slot: str
    text: str
    token_estimate: int
    visible_to_user: str | bool
    source_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class PackedContext:
    version: str
    text: str
    sections: tuple[ContextSection, ...]
    token_estimate: int
    budget_report: dict[str, Any] | None = None

    def visible_evidence(self) -> list[dict[str, Any]]:
        cards: list[dict[str, Any]] = []
        for section in self.sections:
            if section.visible_to_user in {"evidence_cards_only", "summary_only", True} and section.source_ids:
                cards.append(
                    {
                        "slot": section.slot,
                        "source_ids": list(section.source_ids),
                        "summary": section.text[:360],
                    }
                )
        return cards


@dataclass(frozen=True)
class _RankedDocCandidate:
    original_index: int
    doc: Any
    source: str
    static_score: float


class ContextPacker:
    """Versioned context ordering and budget enforcement for Phase 5 experiments."""

    def __init__(self, policy: dict[str, Any]) -> None:
        self.policy = policy
        self.version = str(policy.get("context_packer_version") or "phase5_context_packer_v1")
        self.max_context_tokens = int(policy.get("max_context_tokens_default") or 2600)
        self._slots = {slot["slot"]: slot for slot in policy.get("slots", []) if isinstance(slot, dict) and slot.get("slot")}
        self._source_type_budgets = {
            **DEFAULT_SOURCE_TYPE_BUDGETS,
            **{
                str(key): int(value)
                for key, value in (policy.get("source_type_budgets") or {}).items()
                if str(key).strip() and int(value) >= 0
            },
        }

    @classmethod
    def from_policy_path(cls, path: str | Path = DEFAULT_CONTEXT_POLICY_PATH) -> "ContextPacker":
        payload = yaml.safe_load(repo_path(path).read_text(encoding="utf-8")) or {}
        return cls(payload)

    def pack(self, *, question: str, context: Any, field_context: dict[str, Any] | None = None) -> PackedContext:
        sections: list[ContextSection] = []
        budget_report: dict[str, Any] = {
            "budget_version": "phase5_context_source_budget_v1",
            "max_context_tokens": self.max_context_tokens,
            "source_type_budgets": dict(self._source_type_budgets),
            "available_by_source_type": {},
            "selected_by_source_type": {},
            "slot_limits": {},
            "dropped_doc_ids": [],
        }
        self._append(
            sections,
            "safety_task_policy",
            (
                "Do not invent labels, rates, local laws, calibration curves, or product claims. "
                "Treat evidence marked CONTEXT ONLY as historical or general background, not current field-specific authority. "
                "Static evidence that requires a live authority is excluded before packing."
            ),
        )
        coverage_boundaries = list(
            (getattr(context, "runtime_metadata", {}) or {}).get("canadian_coverage_boundaries") or []
        )
        coverage_blocks = [
            str(item.get("prompt_block") or "").strip()
            for item in coverage_boundaries
            if item.get("requires_prompt_boundary") and str(item.get("prompt_block") or "").strip()
        ]
        if coverage_blocks:
            self._append(
                sections,
                "canadian_jurisdiction_evidence_boundary",
                "\n".join(coverage_blocks),
            )
        rendered_field_context = format_user_field_context(field_context)
        if rendered_field_context:
            self._append(sections, "user_field_context", rendered_field_context)
        decision_state = build_decision_route_state(question, getattr(context.route, "question_type", ""))
        self._append(sections, "decision_route_state", decision_state.prompt_block())
        evidence_handshake = getattr(context, "evidence_handshake", None)
        if evidence_handshake is not None:
            self._append(sections, "evidence_handshake", evidence_handshake.prompt_block())
        self._append(
            sections,
            "route_summary",
            (
                f"Route: type={context.route.question_type}; risk={context.route.risk_level}; "
                f"audience={context.route.audience}; style={context.route.answer_style}; "
                f"namespaces={', '.join(context.route.namespaces)}. "
                f"Route guidance: {getattr(context.route, 'guidance', '')}"
            ),
        )
        if context.tool_notes:
            self._append(
                sections,
                "guard_summary",
                "Guard notes:\n" + "\n".join(f"- {note.name}: {note.text}" for note in context.tool_notes),
            )
        self._append_docs(
            sections,
            context,
            question=question,
            decision_state=decision_state,
            field_context=field_context,
            budget_report=budget_report,
        )
        if context.graph_hits:
            hints = []
            for hit in context.graph_hits[: self._slot_limit("kg_vocabulary_hints", "max_items", 3)]:
                neighbors = "; ".join(hit.neighbors) if hit.neighbors else "no direct neighbors"
                hints.append(f"- {hit.name} ({hit.kind}): {hit.evidence} Related: {neighbors}.")
            self._append(sections, "kg_vocabulary_hints", "Knowledge graph vocabulary hints:\n" + "\n".join(hints))
        if context.coverage_checklist and bool(self.policy.get("include_internal_answer_audit", False)):
            self._append(
                sections,
                "internal_answer_audit",
                (
                    "Internal answer audit priorities. Use these to avoid blind spots, "
                    "but do not expose them as a public checklist:\n"
                    + "\n".join(f"- {item}." for item in context.coverage_checklist)
                ),
            )
        self._append(
            sections,
            "user_question_output_contract",
            (
                "The caller supplies the final field question and output contract after this evidence block. "
                "Use this packed context only as supporting evidence; the final field question controls the answer."
            ),
        )
        budgeted = self._fit_budget(sections)
        text = "\n\n".join(section.text for section in budgeted if section.text)
        return PackedContext(
            version=self.version,
            text=text,
            sections=tuple(budgeted),
            token_estimate=sum(section.token_estimate for section in budgeted),
            budget_report=budget_report,
        )

    def _append_docs(
        self,
        sections: list[ContextSection],
        context: Any,
        *,
        question: str,
        decision_state: Any,
        field_context: dict[str, Any] | None,
        budget_report: dict[str, Any],
    ) -> None:
        primary_docs = []
        boundary_docs = []
        regional_docs = []
        ontology_docs = []
        available_by_type: Counter[str] = Counter()
        retrieved_docs = list(context.retrieved_docs)
        budget_report["retrieval_policy_counts"] = dict(
            sorted(Counter(str(getattr(doc, "retrieval_policy", "standard") or "standard") for doc in retrieved_docs).items())
        )
        budget_report["content_risk_tag_counts"] = dict(
            sorted(Counter(tag for doc in retrieved_docs for tag in getattr(doc, "content_risk_tags", ())).items())
        )
        for doc in retrieved_docs:
            source_type = getattr(doc, "source_type", "")
            namespaces = set(getattr(doc, "namespaces", ()))
            source_key = _source_type_key(source_type, namespaces)
            available_by_type[source_key] += 1
        filtered_docs, decision_filtered = _filter_decision_docs(
            retrieved_docs,
            question=question,
            crop=getattr(decision_state, "crop", None),
            decision=getattr(decision_state, "decision", ""),
        )
        budget_report["decision_filter"] = {
            "filtered_doc_ids": [item[0] for item in decision_filtered],
            "reasons_by_doc_id": {item[0]: item[1] for item in decision_filtered},
        }
        budget_report["dropped_doc_ids"].extend(item[0] for item in decision_filtered)
        evidence_handshake = getattr(context, "evidence_handshake", None)
        evidence_roles = {
            doc_id: role
            for doc_id, role, _ in getattr(evidence_handshake, "evidence_roles", ())
        }
        distractor_doc_ids = {
            doc_id for doc_id, role in evidence_roles.items() if role == "distractor"
        }
        if distractor_doc_ids:
            filtered_docs = [doc for doc in filtered_docs if str(getattr(doc, "doc_id", "")) not in distractor_doc_ids]
            budget_report["evidence_role_filter"] = {
                "dropped_doc_ids": sorted(distractor_doc_ids),
                "reasons_by_doc_id": {doc_id: "premise_distractor" for doc_id in sorted(distractor_doc_ids)},
            }
            budget_report["dropped_doc_ids"].extend(sorted(distractor_doc_ids))
        budget_report["evidence_roles"] = dict(sorted(evidence_roles.items()))
        for doc in filtered_docs:
            source_type = getattr(doc, "source_type", "")
            namespaces = set(getattr(doc, "namespaces", ()))
            source_key = _source_type_key(source_type, namespaces)
            if source_key == "boundary":
                boundary_docs.append(doc)
            elif source_key == "ontology":
                ontology_docs.append(doc)
            elif source_key == "regional_environment":
                regional_docs.append(doc)
            else:
                primary_docs.append(doc)
        budget_report["available_by_source_type"] = dict(sorted(available_by_type.items()))
        route_namespaces = set(getattr(context.route, "namespaces", ()))
        required_tools = set(getattr(context.route, "required_tools", ()))
        field_terms = _field_terms(field_context)
        regional_terms = _regional_field_terms(field_context)
        named_product_doc_ids = {
            doc_id for doc_id, role in evidence_roles.items() if role in {"decisive", "interpretive"}
        }
        regional_docs, region_filtered_doc_ids = _filter_regional_docs(
            regional_docs,
            regional_terms,
            preserve_doc_ids=named_product_doc_ids,
        )
        budget_report["regional_filter"] = {
            "required_terms": sorted(regional_terms),
            "filtered_doc_ids": region_filtered_doc_ids,
        }
        budget_report["dropped_doc_ids"].extend(region_filtered_doc_ids)
        budget_report["ranking_features"] = list(self.policy.get("ranking_features") or [])
        self._append_doc_slot(
            sections,
            "primary_applied_evidence",
            _prioritize_evidence_roles(self._rank_docs(
                primary_docs,
                source_type_key="applied_guidance",
                route_namespaces=route_namespaces,
                required_tools=required_tools,
                field_terms=field_terms,
            ), evidence_handshake),
            source_type_budget="applied_guidance",
            budget_report=budget_report,
            evidence_roles=evidence_roles,
        )
        self._append_doc_slot(
            sections,
            "boundary_evidence",
            _prioritize_evidence_roles(self._rank_docs(boundary_docs, source_type_key="boundary", route_namespaces=route_namespaces, required_tools=required_tools, field_terms=field_terms), evidence_handshake),
            source_type_budget="boundary",
            budget_report=budget_report,
            evidence_roles=evidence_roles,
        )
        self._append_doc_slot(
            sections,
            "regional_context",
            _prioritize_evidence_roles(self._rank_docs(
                regional_docs,
                source_type_key="regional_environment",
                route_namespaces=route_namespaces,
                required_tools=required_tools,
                field_terms=field_terms,
            ), evidence_handshake),
            source_type_budget="regional_environment",
            budget_report=budget_report,
            evidence_roles=evidence_roles,
            max_tokens_override=(
                int(self._slots.get("regional_context", {}).get("named_product_max_tokens") or 1100)
                if _AAFC_CROP_HEALTH_PRODUCT_RE.search(question)
                else None
            ),
        )
        self._append_doc_slot(
            sections,
            "ontology_reference",
            _prioritize_evidence_roles(self._rank_docs(ontology_docs, source_type_key="ontology", route_namespaces=route_namespaces, required_tools=required_tools, field_terms=field_terms), evidence_handshake),
            source_type_budget="ontology",
            budget_report=budget_report,
            evidence_roles=evidence_roles,
        )

    def _rank_docs(
        self,
        docs: list[Any],
        *,
        source_type_key: str,
        route_namespaces: set[str],
        required_tools: set[str],
        field_terms: set[str],
    ) -> list[Any]:
        tool_terms = _tool_terms(required_tools)
        remaining = [
            _RankedDocCandidate(
                original_index=index,
                doc=doc,
                source=str(getattr(doc, "source", "")),
                static_score=self._score_doc_static(
                    doc,
                    source_type_key=source_type_key,
                    route_namespaces=route_namespaces,
                    tool_terms=tool_terms,
                    field_terms=field_terms,
                ),
            )
            for index, doc in enumerate(docs)
        ]
        ranked: list[Any] = []
        seen_sources: Counter[str] = Counter()
        while remaining:
            best = max(
                (
                    (
                        candidate,
                        candidate.static_score - 1.25 * seen_sources[candidate.source],
                    )
                    for candidate in remaining
                ),
                key=lambda item: (item[1], -item[0].original_index),
            )
            best_candidate = best[0]
            ranked.append(best_candidate.doc)
            seen_sources[best_candidate.source] += 1
            remaining = [candidate for candidate in remaining if candidate.original_index != best_candidate.original_index]
        return ranked

    def _score_doc(
        self,
        doc: Any,
        *,
        source_type_key: str,
        route_namespaces: set[str],
        required_tools: set[str],
        field_terms: set[str],
        repeated_source_count: int,
    ) -> float:
        return self._score_doc_static(
            doc,
            source_type_key=source_type_key,
            route_namespaces=route_namespaces,
            required_tools=required_tools,
            field_terms=field_terms,
        ) - 1.25 * repeated_source_count

    def _score_doc_static(
        self,
        doc: Any,
        *,
        source_type_key: str,
        route_namespaces: set[str],
        required_tools: set[str] | None = None,
        tool_terms: set[str] | None = None,
        field_terms: set[str],
    ) -> float:
        namespaces = set(getattr(doc, "namespaces", ()))
        text = _doc_search_text(doc)
        tool_terms = tool_terms if tool_terms is not None else _tool_terms(required_tools or set())
        lexical_score = float(getattr(doc, "score", 0.0) or 0.0)
        namespace_match = (
            0.0
            if source_type_key == "regional_environment"
            else 2.0 * len(namespaces & route_namespaces)
        )
        source_type_bonus = {
            "applied_guidance": 1.5,
            "boundary": 1.25,
            "regional_environment": 0.5,
            "ontology": -0.75,
        }.get(source_type_key, 0.0)
        route_tool_alignment = 1.0 if any(term and term in text for term in tool_terms) else 0.0
        field_context_match = 1.0 if any(term and term in text for term in field_terms) else 0.0
        source_authority = 0.75 if any(term in text for term in ("extension", ".edu", ".gov", "label", "university")) else 0.0
        ontology_penalty = 1.0 if source_type_key == "ontology" and route_namespaces and not (namespaces & route_namespaces) else 0.0
        token_cost_penalty = min(1.5, estimate_tokens(str(getattr(doc, "text", ""))) / 800.0)
        return (
            lexical_score
            + namespace_match
            + source_type_bonus
            + route_tool_alignment
            + field_context_match
            + source_authority
            - ontology_penalty
            - token_cost_penalty
        )

    def _append_doc_slot(
        self,
        sections: list[ContextSection],
        slot: str,
        docs: list[Any],
        *,
        source_type_budget: str,
        budget_report: dict[str, Any],
        evidence_roles: dict[str, str],
        max_tokens_override: int | None = None,
    ) -> None:
        limit = min(self._slot_limit(slot, "max_items", 4), self._source_type_limit(source_type_budget, self._slot_limit(slot, "max_items", 4)))
        budget_report["slot_limits"][slot] = limit
        selected = docs[:limit]
        selected_counter = Counter(budget_report.get("selected_by_source_type", {}))
        selected_counter[source_type_budget] += len(selected)
        budget_report["selected_by_source_type"] = dict(sorted(selected_counter.items()))
        budget_report["dropped_doc_ids"].extend(str(getattr(doc, "doc_id", "")) for doc in docs[limit:] if getattr(doc, "doc_id", ""))
        if not selected:
            return
        slot_token_budget = int(
            max_tokens_override
            or self._slots.get(slot, {}).get("max_tokens")
            or self.max_context_tokens
        )
        per_doc_token_budget = max(
            96,
            (slot_token_budget - 12) // len(selected),
        )
        lines = []
        source_ids = []
        for doc in selected:
            source_ids.append(str(doc.doc_id))
            assigned_role = evidence_roles.get(str(doc.doc_id))
            retrieval_policy = str(getattr(doc, "retrieval_policy", "standard") or "standard").strip().lower()
            if retrieval_policy == "context_only" and assigned_role != "interpretive":
                role = "CONSTRAINT"
            elif assigned_role == "decisive":
                role = "BOUNDED ACTION SUPPORT"
            elif assigned_role == "interpretive":
                role = "SOURCE INTERPRETATION"
            elif assigned_role == "supporting":
                role = "SUPPORTING"
            elif assigned_role == "boundary":
                role = "CONSTRAINT"
            elif slot == "primary_applied_evidence":
                role = "BOUNDED ACTION SUPPORT" if not lines else "SUPPORTING"
            elif slot == "boundary_evidence":
                role = "CONSTRAINT"
            elif slot == "regional_context":
                role = "REGIONAL PRIOR"
            else:
                role = "VOCABULARY"
            policy_note = _doc_policy_note(doc)
            lines.append(_trim_to_tokens(
                f"- [{role}] [{doc.doc_id}].{policy_note} "
                f"Title: {doc.title}. Source: {doc.source}. Excerpt: {doc.text}",
                per_doc_token_budget,
            ))
        self._append(
            sections,
            slot,
            f"{slot.replace('_', ' ').title()}:\n" + "\n".join(lines),
            source_ids=tuple(source_ids),
            max_tokens_override=max_tokens_override,
        )

    def _append(
        self,
        sections: list[ContextSection],
        slot: str,
        text: str,
        source_ids: tuple[str, ...] = (),
        max_tokens_override: int | None = None,
    ) -> None:
        spec = self._slots.get(slot, {})
        max_tokens = int(max_tokens_override or spec.get("max_tokens") or self.max_context_tokens)
        trimmed = _trim_to_tokens(text.strip(), max_tokens)
        sections.append(
            ContextSection(
                slot=slot,
                text=trimmed,
                token_estimate=estimate_tokens(trimmed),
                visible_to_user=spec.get("visible_to_user", False),
                source_ids=source_ids,
            )
        )

    def _fit_budget(self, sections: list[ContextSection]) -> list[ContextSection]:
        kept: list[ContextSection] = []
        total = 0
        for section in sections:
            if total + section.token_estimate > self.max_context_tokens and section.slot not in {
                "safety_task_policy",
                "route_summary",
                "decision_route_state",
                "evidence_handshake",
                "canadian_jurisdiction_evidence_boundary",
                "hidden_answer_contract",
                "user_question_output_contract",
            }:
                continue
            kept.append(section)
            total += section.token_estimate
        return kept

    def _slot_limit(self, slot: str, key: str, fallback: int) -> int:
        return int(self._slots.get(slot, {}).get(key) or fallback)

    def _source_type_limit(self, source_type: str, fallback: int) -> int:
        return int(self._source_type_budgets.get(source_type, fallback))


def _prioritize_evidence_roles(docs: list[Any], handshake: Any | None) -> list[Any]:
    if handshake is None:
        return docs
    roles = {doc_id: role for doc_id, role, _ in getattr(handshake, "evidence_roles", ())}
    primary_doc_id = str(getattr(handshake, "primary_doc_id", "") or "")
    priority = {"decisive": 0, "interpretive": 0, "supporting": 1, "boundary": 2, "distractor": 3}
    indexed = list(enumerate(docs))
    indexed.sort(
        key=lambda item: (
            0 if str(getattr(item[1], "doc_id", "")) == primary_doc_id else 1,
            priority.get(roles.get(str(getattr(item[1], "doc_id", "")), "supporting"), 1),
            item[0],
        )
    )
    return [doc for _, doc in indexed]


_DEFAULT_PACKER: ContextPacker | None = None
_DEFAULT_PACKER_PATH: str | None = None


def default_context_packer() -> ContextPacker:
    global _DEFAULT_PACKER, _DEFAULT_PACKER_PATH
    policy_path = os.environ.get("AGRONOMY_AGENT_CONTEXT_POLICY_PATH") or DEFAULT_CONTEXT_POLICY_PATH
    if _DEFAULT_PACKER is None or _DEFAULT_PACKER_PATH != policy_path:
        _DEFAULT_PACKER = ContextPacker.from_policy_path(policy_path)
        _DEFAULT_PACKER_PATH = policy_path
    return _DEFAULT_PACKER


def reset_default_context_packer() -> None:
    global _DEFAULT_PACKER, _DEFAULT_PACKER_PATH
    _DEFAULT_PACKER = None
    _DEFAULT_PACKER_PATH = None


def _source_type_key(source_type: str, namespaces: set[str]) -> str:
    normalized = (source_type or "").strip().lower()
    if normalized in {"applied", "applied_guidance", "extension_document", "user_upload_private", "community_forum"}:
        return "applied_guidance"
    if normalized in {"regional", "regional_environment", "regional_environment_profile"} or "regional_environment" in namespaces:
        return "regional_environment"
    if normalized == "boundary" or namespaces & {"label_boundary", "field_data_boundary"}:
        return "boundary"
    if normalized == "ontology":
        return "ontology"
    return normalized or "unknown"


def _doc_policy_note(doc: Any) -> str:
    policy = str(getattr(doc, "retrieval_policy", "standard") or "standard").strip().lower()
    risks = set(getattr(doc, "content_risk_tags", ()))
    notes: list[str] = []
    if policy == "context_only":
        notes.append(
            "CONTEXT ONLY: use qualitative background only; do not copy numeric thresholds, "
            "rates, product uses, or timing into the answer; FIELD ACTION: NOT AUTHORIZED; "
            "validate against current local guidance"
        )
    if str(getattr(doc, "transfer_scope", "") or "").strip().lower() == "cross_border_analogue":
        notes.append(
            "US CROSS-BORDER ANALOGUE: match climate, landscape, soil and ecological process; "
            "never treat as Canadian field truth, calibration, legal authority or prescription"
        )
    if "historical_source_requires_current_validation" in risks:
        notes.append("historical source")
    if "numeric_fertility_guidance_requires_local_calibration" in risks:
        notes.append("numeric fertility guidance requires current local soil-test calibration")
    if "pesticide_guidance_requires_current_pmra_label" in risks:
        notes.append("pesticide use requires the current PMRA label")
    return " Evidence policy: " + "; ".join(notes) + "." if notes else ""


def _tool_terms(required_tools: set[str]) -> set[str]:
    return {tool.replace("_guard", "").replace("_", " ") for tool in required_tools}


def _field_terms(field_context: dict[str, Any] | None) -> set[str]:
    return {
        str(value).strip().lower()
        for value in (field_context or {}).values()
        if value is not None and str(value).strip()
    }


def _regional_field_terms(field_context: dict[str, Any] | None) -> set[str]:
    region_keys = {
        "region_text",
        "province_state",
        "province",
        "state",
        "county",
        "country",
        "jurisdiction",
        "mlra",
        "ecoregion",
        "ecodistrict",
        "soil_region",
        "location",
    }
    terms: set[str] = set()
    for key, value in (field_context or {}).items():
        if str(key).strip().lower() not in region_keys or value is None:
            continue
        cleaned = str(value).strip().lower()
        if not cleaned:
            continue
        terms.add(cleaned)
        terms.update(part.strip().lower() for part in cleaned.replace("/", ",").split(",") if len(part.strip()) >= 3)
    return terms


def _filter_regional_docs(
    docs: list[Any],
    regional_terms: set[str],
    *,
    preserve_doc_ids: set[str] | None = None,
) -> tuple[list[Any], list[str]]:
    if not regional_terms:
        return docs, []
    preserve_doc_ids = preserve_doc_ids or set()
    kept = []
    dropped = []
    for doc in docs:
        doc_id = str(getattr(doc, "doc_id", ""))
        haystack = _doc_search_text(doc)
        if doc_id in preserve_doc_ids or any(term and term in haystack for term in regional_terms):
            kept.append(doc)
        else:
            dropped.append(doc_id)
    return kept, [doc_id for doc_id in dropped if doc_id]


def _doc_search_text(doc: Any) -> str:
    return " ".join(
        [
            str(getattr(doc, "doc_id", "")),
            str(getattr(doc, "title", "")),
            str(getattr(doc, "text", "")),
            str(getattr(doc, "source", "")),
            " ".join(str(item) for item in getattr(doc, "tags", ()) or ()),
            " ".join(str(item) for item in getattr(doc, "knowledge_domains", ()) or ()),
            str(getattr(doc, "knowledge_bucket", "")),
        ]
    ).lower()


_CROP_NAMES = {
    "canola",
    "corn",
    "cotton",
    "dry bean",
    "potato",
    "sorghum",
    "soybean",
    "spring wheat",
    "sugar beet",
    "tomato",
    "winter wheat",
}


def _filter_decision_docs(
    docs: list[Any],
    *,
    question: str,
    crop: str | None,
    decision: str,
) -> tuple[list[Any], list[tuple[str, str]]]:
    """Drop conditional distractors whose prerequisite is absent from the query."""

    if not crop or decision not in {
        "drought_nitrogen_adjustment",
        "fertility_rate",
        "water_limited_nitrogen_increase",
    }:
        return docs, []
    question_lower = question.lower()
    rescue_change = bool(
        re.search(
            r"\b(?:increase|rescue|top[- ]?dress|top up|additional|change)\b.{0,50}\b(?:nitrogen|n rate|rate)\b|"
            r"\b(?:nitrogen|n rate)\b.{0,50}\b(?:increase|rescue|top[- ]?dress|top up|additional|change)\b",
            question_lower,
        )
    )
    if not rescue_change:
        return docs, []
    doc_text = {id(doc): _doc_search_text(doc) for doc in docs}

    kept: list[Any] = []
    dropped: list[tuple[str, str]] = []
    for doc in docs:
        text = doc_text[id(doc)]
        identifier = f"{getattr(doc, 'doc_id', '')} {getattr(doc, 'title', '')}".lower()
        reason = ""
        if "manure" not in question_lower and "manure" in identifier:
            reason = "unstated_manure_context"
        elif "tile" not in question_lower and "tile" in identifier:
            reason = "unstated_tile_context"
        elif "irrigat" not in question_lower and re.search(r"\b(?:irrigation|chemigation|fertigation)\b", identifier):
            reason = "unstated_irrigation_context"
        else:
            explicit_other_crops = {
                other
                for other in _CROP_NAMES - {crop}
                if re.search(rf"\b(?:for |in )?{re.escape(other)}\b", text)
            }
            mentions_target = bool(re.search(rf"\b{re.escape(crop)}\b", text))
            if explicit_other_crops and not mentions_target:
                reason = "crop_mismatch:" + ",".join(sorted(explicit_other_crops))
        if reason:
            dropped.append((str(getattr(doc, "doc_id", "")), reason))
        else:
            kept.append(doc)
    return kept, dropped
