"""Canonical, serialization-stable contracts for the OpenAgronomy evidence spine.

This module is intentionally adapter-first.  It records what the current
runtime actually captured and uses explicit ``capture_status`` values for data
that legacy chunks cannot reconstruct.  It does not change retrieval, prompt
packing, generation, or answer verification.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
import re
from typing import Any, Iterable, Mapping, Sequence


CONTRACT_FAMILY_VERSION = "open_agronomy_agent.evidence_fabric.v1"
_HEX_64_RE = re.compile(r"^[0-9a-f]{64}$")
_PAGE_RE = re.compile(r"^\[page\s+(\d+)\]", re.IGNORECASE)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def content_id(prefix: str, value: Any) -> str:
    digest = hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
    return f"{prefix}_{digest[:24]}"


def _clean_tuple(values: Iterable[Any] | None) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(value).strip() for value in (values or ()) if str(value).strip()))


def _valid_sha(value: Any) -> str | None:
    candidate = str(value or "").strip().lower()
    return candidate if _HEX_64_RE.fullmatch(candidate) else None


class ContractRecord:
    """Small common surface used by persistence, tests, and trace exports."""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def canonical_json(self) -> str:
        return canonical_json(self.to_dict())

    def record_sha256(self) -> str:
        return sha256_text(self.canonical_json())


@dataclass(frozen=True)
class SourceAsset(ContractRecord):
    schema_version: str
    asset_id: str
    source_id: str
    title: str
    canonical_uri: str
    source_type: str
    publisher: str | None
    license_status: str
    license_identifier: str | None
    distribution_scope: str
    capture_status: str


@dataclass(frozen=True)
class SourceVersion(ContractRecord):
    schema_version: str
    version_id: str
    asset_id: str
    raw_sha256: str | None
    extracted_text_sha256: str | None
    manifest_sha256: str | None
    publication_date: str | None
    retrieved_at: str | None
    effective_at: str | None
    currency_status: str
    parser_name: str | None
    parser_version: str | None
    capture_status: str


@dataclass(frozen=True)
class EvidenceSpan(ContractRecord):
    schema_version: str
    span_id: str
    source_version_id: str
    exact_text: str
    exact_text_sha256: str
    locator: Mapping[str, Any]
    source_byte_start: int | None
    source_byte_end: int | None
    transformation_sha256: str | None
    parser_version: str | None
    statement_type: str
    review_state: str
    capture_status: str


@dataclass(frozen=True)
class ApplicabilityEnvelope(ContractRecord):
    schema_version: str
    applicability_id: str
    jurisdictions: tuple[str, ...]
    crops: tuple[str, ...]
    crop_stages: tuple[str, ...]
    practices: tuple[str, ...]
    methods: tuple[str, ...]
    units: tuple[str, ...]
    depth_scope: tuple[str, ...]
    temporal_scope: tuple[str, ...]
    region_layer_versions: tuple[str, ...]
    overlap_fractions: tuple[float, ...]
    transfer_status: str
    limitations: tuple[str, ...]
    capture_status: str


@dataclass(frozen=True)
class EvidenceCapsule(ContractRecord):
    schema_version: str
    capsule_id: str
    source_version_id: str
    span_ids: tuple[str, ...]
    applicability_id: str
    claim_text: str
    authority_role: str
    evidence_role: str
    factual_interpretation_authority: str
    field_action_authority: str
    authority_reason: str
    limitations: tuple[str, ...]
    review_state: str
    retrieval_eligible: bool
    training_eligible: bool | None
    capture_status: str


@dataclass(frozen=True)
class CoverageState(ContractRecord):
    schema_version: str
    slot_key: str
    status: str
    required_authority: str | None
    evidence_capsule_ids: tuple[str, ...]
    missing_inputs: tuple[str, ...]
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class CapabilityEvidence(ContractRecord):
    """One typed non-document evidence contribution.

    Tool results, graph assertions, public adapter observations, and field
    observations retain different authority roles, but share one identity and
    hashing contract from prompt assembly through verification and trace.
    """

    schema_version: str
    evidence_id: str
    evidence_kind: str
    capability_id: str
    capability_version: str
    invocation_id: str | None
    result_id: str
    status: str
    claim_text: str
    payload_sha256: str
    authority_role: str
    freshness_status: str
    provenance: str
    limitations: tuple[str, ...]
    record: Mapping[str, Any]


@dataclass(frozen=True)
class QuestionFrame(ContractRecord):
    schema_version: str
    question_frame_id: str
    question_sha256: str
    primary_intent: str
    intent_set: tuple[str, ...]
    action: str
    risk_level: str
    crop_scope: tuple[str, ...]
    jurisdiction_scope: tuple[str, ...]
    evidence_slots: tuple[Mapping[str, Any], ...]
    missing_inputs: tuple[str, ...]
    field_snapshot_sha256: str | None
    answer_mode: str
    capture_status: str


@dataclass(frozen=True)
class EvidencePacket(ContractRecord):
    schema_version: str
    packet_id: str
    question_frame_id: str
    source_assets: tuple[SourceAsset, ...]
    source_versions: tuple[SourceVersion, ...]
    spans: tuple[EvidenceSpan, ...]
    applicability: tuple[ApplicabilityEnvelope, ...]
    capsules: tuple[EvidenceCapsule, ...]
    coverage: tuple[CoverageState, ...]
    capability_evidence: tuple[CapabilityEvidence, ...]
    selected_document_order: tuple[str, ...]
    packed_context_sha256: str | None
    version_ledger: Mapping[str, Any]
    capture_status: str


def capability_evidence_from_records(
    records: Iterable[Mapping[str, Any] | Any] | None,
) -> tuple[CapabilityEvidence, ...]:
    """Normalize runtime capability records without promoting their authority."""

    output: list[CapabilityEvidence] = []
    seen: set[str] = set()
    for raw in records or ():
        if hasattr(raw, "to_dict"):
            value = raw.to_dict()
        elif isinstance(raw, Mapping):
            value = dict(raw)
        else:
            continue
        payload = value.get("payload") if isinstance(value.get("payload"), Mapping) else value
        payload_record = dict(payload)
        capability_id = str(
            value.get("capability_id")
            or value.get("tool_id")
            or value.get("name")
            or value.get("graph_id")
            or value.get("source_id")
            or "unknown_capability"
        )
        capability_version = str(
            value.get("capability_version")
            or value.get("tool_version")
            or value.get("graph_version")
            or value.get("version")
            or "not_declared"
        )
        evidence_kind = str(value.get("evidence_kind") or _capability_kind(value, payload_record))
        invocation_id = str(value.get("invocation_id") or "") or None
        result_id = str(value.get("result_id") or value.get("record_id") or "")
        payload_sha = _valid_sha(value.get("payload_sha256")) or sha256_text(canonical_json(payload_record))
        if not result_id:
            result_id = content_id(
                "capability_result",
                {
                    "capability_id": capability_id,
                    "capability_version": capability_version,
                    "payload_sha256": payload_sha,
                },
            )
        evidence_id = content_id(
            "capability_evidence",
            {
                "evidence_kind": evidence_kind,
                "result_id": result_id,
                "payload_sha256": payload_sha,
            },
        )
        if evidence_id in seen:
            continue
        seen.add(evidence_id)
        limitations = _clean_tuple(
            value.get("limitations")
            or payload_record.get("limitations")
            or ([payload_record.get("boundary")] if payload_record.get("boundary") else ())
        )
        freshness_status = _capability_freshness(value, payload_record)
        output.append(
            CapabilityEvidence(
                schema_version="open_agronomy_agent.capability_evidence.v1",
                evidence_id=evidence_id,
                evidence_kind=evidence_kind,
                capability_id=capability_id,
                capability_version=capability_version,
                invocation_id=invocation_id,
                result_id=result_id,
                status=str(value.get("status") or payload_record.get("status") or "captured"),
                claim_text=_capability_claim_text(value, payload_record),
                payload_sha256=payload_sha,
                authority_role=str(
                    value.get("authority_role")
                    or payload_record.get("authority_role")
                    or payload_record.get("boundary")
                    or "context_only_not_field_action_authority"
                ),
                freshness_status=freshness_status,
                provenance=str(
                    value.get("provenance")
                    or payload_record.get("provenance")
                    or "runtime_capability_record"
                ),
                limitations=limitations,
                record=value,
            )
        )
    return tuple(output)


def _capability_freshness(value: Mapping[str, Any], payload: Mapping[str, Any]) -> str:
    explicit = str(value.get("freshness_status") or "").strip()
    if explicit:
        return explicit
    freshness = payload.get("freshness")
    if isinstance(freshness, Mapping):
        nested = str(freshness.get("status") or "").strip()
        if nested:
            return nested
    return "not_declared"


def _capability_kind(value: Mapping[str, Any], payload: Mapping[str, Any]) -> str:
    if value.get("graph_id") or value.get("node_id"):
        return "graph_assertion"
    if value.get("tool_id") or value.get("invocation_id") or payload.get("tool"):
        return "tool_result"
    if payload.get("kind") == "public_adapter" or value.get("name"):
        return "public_adapter_observation"
    if value.get("field_snapshot_sha256") or value.get("source_id") == "user_field_context":
        return "field_observation"
    return "capability_observation"


def _capability_claim_text(value: Mapping[str, Any], payload: Mapping[str, Any]) -> str:
    for candidate in (
        payload.get("answer"),
        value.get("text"),
        payload.get("summary"),
        payload.get("claim_text"),
    ):
        text = " ".join(str(candidate or "").split())
        if text:
            return text
    return ""


@dataclass(frozen=True)
class AnswerDraftClaim(ContractRecord):
    schema_version: str
    claim_id: str
    text: str
    claim_type: str
    evidence_capsule_ids: tuple[str, ...]
    scope: Mapping[str, Any]


@dataclass(frozen=True)
class ValidatedClaim(ContractRecord):
    schema_version: str
    claim_id: str
    text: str
    status: str
    evidence_capsule_ids: tuple[str, ...]
    validation_events: tuple[Mapping[str, Any], ...]
    repaired_text: str | None


@dataclass(frozen=True)
class ValidatedAnswer(ContractRecord):
    schema_version: str
    validated_answer_id: str
    answer_sha256: str
    evidence_packet_id: str | None
    claims: tuple[ValidatedClaim, ...]
    answer_status: str
    verifier_record: Mapping[str, Any] | None
    validation_policy: str
    capture_status: str


def source_contracts_from_retrieved_doc(doc: Any) -> tuple[SourceAsset, SourceVersion]:
    """Adapt one existing ``RetrievedDoc`` without inventing absent lineage."""

    source_id = str(getattr(doc, "source_id", "") or getattr(doc, "doc_id", "") or "unknown")
    canonical_uri = str(getattr(doc, "source", "") or "")
    asset_seed = {"source_id": source_id, "canonical_uri": canonical_uri}
    asset_id = content_id("asset", asset_seed)
    raw_sha = _valid_sha(getattr(doc, "raw_sha256", None))
    chunk_sha = _valid_sha(getattr(doc, "chunk_sha256", None))
    manifest_sha = _valid_sha(getattr(doc, "manifest_sha256", None))
    asset = SourceAsset(
        schema_version="open_agronomy_agent.source_asset.v1",
        asset_id=asset_id,
        source_id=source_id,
        title=str(getattr(doc, "title", "") or source_id),
        canonical_uri=canonical_uri,
        source_type=str(getattr(doc, "source_type", "") or "unspecified"),
        publisher=None,
        license_status=str(getattr(doc, "license_status", "") or "unknown"),
        license_identifier=str(getattr(doc, "license_identifier", "") or "") or None,
        distribution_scope=str(getattr(doc, "distribution_scope", "") or "unspecified"),
        capture_status="captured_from_retrieved_document",
    )
    version_seed = {
        "asset_id": asset_id,
        "raw_sha256": raw_sha,
        "manifest_sha256": manifest_sha,
        "corpus_path": str(getattr(doc, "corpus_path", "") or ""),
    }
    version = SourceVersion(
        schema_version="open_agronomy_agent.source_version.v1",
        version_id=content_id("version", version_seed),
        asset_id=asset_id,
        raw_sha256=raw_sha,
        extracted_text_sha256=None,
        manifest_sha256=manifest_sha,
        publication_date=None,
        retrieved_at=None,
        effective_at=None,
        currency_status=str(getattr(doc, "currency_status", "") or "unspecified"),
        parser_name=None,
        parser_version=None,
        capture_status="complete_hash_lineage" if raw_sha and chunk_sha and manifest_sha else "partial_legacy_lineage",
    )
    return asset, version


def applicability_from_retrieved_doc(
    doc: Any,
    *,
    question_jurisdictions: Sequence[str] = (),
    region_layer_versions: Sequence[str] = (),
) -> ApplicabilityEnvelope:
    jurisdictions = _clean_tuple(getattr(doc, "jurisdictions", ()) or ())
    crops = _clean_tuple(getattr(doc, "crops", ()) or ())
    target = {value.casefold() for value in _clean_tuple(question_jurisdictions)}
    actual = {value.casefold() for value in jurisdictions}
    source_type = str(getattr(doc, "source_type", "") or "")
    if target and actual and not target.intersection(actual):
        transfer_status = "blocked_jurisdiction_mismatch"
    elif source_type in {"regional_environment", "regional_environment_profile"}:
        transfer_status = "regional_prior"
    elif target and actual:
        transfer_status = "direct_jurisdiction_match"
    else:
        transfer_status = "broad_or_unspecified"
    payload = {
        "doc_id": str(getattr(doc, "doc_id", "") or ""),
        "jurisdictions": jurisdictions,
        "crops": crops,
        "transfer_status": transfer_status,
        "region_layers": _clean_tuple(region_layer_versions),
    }
    return ApplicabilityEnvelope(
        schema_version="open_agronomy_agent.applicability_envelope.v1",
        applicability_id=content_id("applicability", payload),
        jurisdictions=jurisdictions,
        crops=crops,
        crop_stages=(),
        practices=(),
        methods=(),
        units=(),
        depth_scope=(),
        temporal_scope=(str(getattr(doc, "currency_status", "") or "unspecified"),),
        region_layer_versions=_clean_tuple(region_layer_versions),
        overlap_fractions=(),
        transfer_status=transfer_status,
        limitations=(
            "retrieved chunk does not carry normalized stage, practice, method, unit, or depth applicability"
        ),
        capture_status="partial_legacy_applicability",
    )


def span_and_capsule_from_retrieved_doc(
    doc: Any,
    *,
    source_version: SourceVersion,
    applicability: ApplicabilityEnvelope,
    evidence_role: str,
    evidence_reason: str = "",
) -> tuple[EvidenceSpan, EvidenceCapsule]:
    from agronomy_agent.evidence_authority import classify_evidence_authority

    exact_text = str(getattr(doc, "text", "") or "")
    page_match = _PAGE_RE.match(exact_text)
    locator: dict[str, Any] = {
        "kind": "retrieved_chunk",
        "doc_id": str(getattr(doc, "doc_id", "") or ""),
        "corpus_path": str(getattr(doc, "corpus_path", "") or ""),
    }
    if page_match:
        locator["page"] = int(page_match.group(1))
    transformation_sha = _valid_sha(getattr(doc, "chunk_sha256", None))
    span_seed = {
        "source_version_id": source_version.version_id,
        "doc_id": locator["doc_id"],
        "exact_text_sha256": sha256_text(exact_text),
        "locator": locator,
    }
    span = EvidenceSpan(
        schema_version="open_agronomy_agent.evidence_span.v1",
        span_id=content_id("span", span_seed),
        source_version_id=source_version.version_id,
        exact_text=exact_text,
        exact_text_sha256=sha256_text(exact_text),
        locator=locator,
        source_byte_start=None,
        source_byte_end=None,
        transformation_sha256=transformation_sha,
        parser_version=None,
        statement_type=(
            "regional_prior"
            if applicability.transfer_status == "regional_prior"
            else "source_claim"
        ),
        review_state="retrieval_eligible_not_claim_reviewed",
        capture_status="exact_chunk_text_source_offsets_not_captured",
    )
    capsule_seed = {
        "span_id": span.span_id,
        "applicability_id": applicability.applicability_id,
        "evidence_role": evidence_role,
    }
    authority = classify_evidence_authority(
        doc,
        evidence_role=evidence_role,
        evidence_reason=evidence_reason,
    )
    capsule = EvidenceCapsule(
        schema_version="open_agronomy_agent.evidence_capsule.v1",
        capsule_id=content_id("capsule", capsule_seed),
        source_version_id=source_version.version_id,
        span_ids=(span.span_id,),
        applicability_id=applicability.applicability_id,
        claim_text=exact_text,
        authority_role=str(getattr(doc, "answer_role", "") or "unspecified"),
        evidence_role=evidence_role,
        factual_interpretation_authority=authority.factual_interpretation_authority,
        field_action_authority=authority.field_action_authority,
        authority_reason=authority.reason,
        limitations=tuple(
            value
            for value in (
                "regional evidence is context, not field truth"
                if applicability.transfer_status == "regional_prior"
                else "",
                "capsule is adapted from a retrieved chunk and has not received claim-level human review",
            )
            if value
        ),
        review_state="legacy_chunk_not_claim_reviewed",
        retrieval_eligible=str(getattr(doc, "retrieval_policy", "standard") or "standard") != "excluded",
        training_eligible=None,
        capture_status="adapter_generated_not_curated",
    )
    return span, capsule


def question_frame_from_runtime(
    *,
    question: str,
    route: Any,
    query_context: Mapping[str, Any] | None,
    decision_contract: Mapping[str, Any] | None,
    field_context: Mapping[str, Any] | None,
) -> QuestionFrame:
    contract = dict(decision_contract or {})
    obligations = tuple(dict(item) for item in contract.get("evidence_obligations") or ())
    crops = contract.get("crop_scope") or (query_context or {}).get("crops") or ()
    jurisdictions = contract.get("jurisdiction_scope") or (query_context or {}).get("target_jurisdictions") or ()
    field_sha = sha256_text(canonical_json(field_context)) if field_context else None
    seed = {
        "question_sha256": sha256_text(question),
        "route": str(getattr(route, "question_type", "conceptual")),
        "contract_policy": contract.get("policy_id"),
        "field_snapshot_sha256": field_sha,
    }
    return QuestionFrame(
        schema_version="open_agronomy_agent.question_frame.v1",
        question_frame_id=content_id("question", seed),
        question_sha256=sha256_text(question),
        primary_intent=str(contract.get("primary_intent") or getattr(route, "question_type", "conceptual")),
        intent_set=_clean_tuple(contract.get("intent_set") or (getattr(route, "question_type", "conceptual"),)),
        action=str(contract.get("action") or "inform"),
        risk_level=str(getattr(route, "risk_level", "low") or "low"),
        crop_scope=_clean_tuple(crops),
        jurisdiction_scope=_clean_tuple(jurisdictions),
        evidence_slots=obligations,
        missing_inputs=_clean_tuple(contract.get("missing_inputs") or ()),
        field_snapshot_sha256=field_sha,
        answer_mode=str(contract.get("answer_mode") or "inform"),
        capture_status="compiled_from_current_route_and_decision_contract",
    )


def _coverage_states(
    *,
    question_frame: QuestionFrame,
    decision_contract: Any | None,
    docs: Sequence[Any],
    capsules_by_doc_id: Mapping[str, EvidenceCapsule],
) -> tuple[CoverageState, ...]:
    if decision_contract is None or not question_frame.evidence_slots:
        return (
            CoverageState(
                schema_version="open_agronomy_agent.coverage_state.v1",
                slot_key="general_support",
                status="ADEQUATE" if docs else "ABSENT",
                required_authority=None,
                evidence_capsule_ids=tuple(capsule.capsule_id for capsule in capsules_by_doc_id.values()),
                missing_inputs=(),
                reasons=("no typed evidence obligation was compiled",),
            ),
        )
    from agronomy_agent.decision_contract import obligation_coverage

    rows: list[CoverageState] = []
    obligations = {str(item.get("key")): item for item in question_frame.evidence_slots}
    for key, obligation in obligations.items():
        supporting = [doc for doc in docs if key in obligation_coverage(doc, decision_contract)]
        capsule_ids = tuple(
            capsules_by_doc_id[str(getattr(doc, "doc_id", ""))].capsule_id
            for doc in supporting
            if str(getattr(doc, "doc_id", "")) in capsules_by_doc_id
        )
        stale = any(
            any(token in str(getattr(doc, "currency_status", "") or "").casefold() for token in ("stale", "historical", "expired"))
            for doc in supporting
        )
        boundary_only = bool(supporting) and all(
            str(getattr(doc, "retrieval_policy", "standard") or "standard") == "context_only"
            or str(getattr(doc, "source_type", "") or "") in {"boundary", "regional_environment", "regional_environment_profile"}
            for doc in supporting
        )
        missing_inputs = _clean_tuple(obligation.get("missing_inputs") or ())
        if not supporting:
            status = "ABSENT"
            reasons = ("no selected document met the obligation lexical coverage rule",)
        elif stale:
            status = "STALE"
            reasons = ("supporting evidence is marked historical, stale, or expired",)
        elif boundary_only or missing_inputs:
            status = "PARTIAL"
            reasons = tuple(
                value
                for value in (
                    "selected support is boundary or context-only evidence" if boundary_only else "",
                    "question is missing decision inputs" if missing_inputs else "",
                )
                if value
            )
        else:
            status = "ADEQUATE"
            reasons = ("selected evidence covers the typed obligation",)
        rows.append(
            CoverageState(
                schema_version="open_agronomy_agent.coverage_state.v1",
                slot_key=key,
                status=status,
                required_authority=str(obligation.get("authority") or "") or None,
                evidence_capsule_ids=capsule_ids,
                missing_inputs=missing_inputs,
                reasons=reasons,
            )
        )
    return tuple(rows)


def evidence_packet_from_runtime(
    *,
    question_frame: QuestionFrame,
    docs: Sequence[Any],
    evidence_handshake: Any | None,
    packed_context: Any | None,
    decision_contract: Any | None,
    version_ledger: Mapping[str, Any],
    capability_records: Iterable[Mapping[str, Any] | Any] | None = None,
) -> EvidencePacket:
    roles = {
        str(doc_id): (str(role), str(reason))
        for doc_id, role, reason in (getattr(evidence_handshake, "evidence_roles", ()) or ())
    }
    assets: dict[str, SourceAsset] = {}
    versions: dict[str, SourceVersion] = {}
    applicability: list[ApplicabilityEnvelope] = []
    spans: list[EvidenceSpan] = []
    capsules: list[EvidenceCapsule] = []
    capsules_by_doc_id: dict[str, EvidenceCapsule] = {}
    region_layers = _clean_tuple(version_ledger.get("region_layer_versions") or ())
    for doc in docs:
        asset, version = source_contracts_from_retrieved_doc(doc)
        envelope = applicability_from_retrieved_doc(
            doc,
            question_jurisdictions=question_frame.jurisdiction_scope,
            region_layer_versions=region_layers,
        )
        doc_id = str(getattr(doc, "doc_id", "") or "")
        span, capsule = span_and_capsule_from_retrieved_doc(
            doc,
            source_version=version,
            applicability=envelope,
            evidence_role=roles.get(doc_id, ("supporting", ""))[0],
            evidence_reason=roles.get(doc_id, ("supporting", ""))[1],
        )
        assets[asset.asset_id] = asset
        versions[version.version_id] = version
        applicability.append(envelope)
        spans.append(span)
        capsules.append(capsule)
        capsules_by_doc_id[doc_id] = capsule
    coverage = _coverage_states(
        question_frame=question_frame,
        decision_contract=decision_contract,
        docs=docs,
        capsules_by_doc_id=capsules_by_doc_id,
    )
    capability_evidence = capability_evidence_from_records(capability_records)
    if capability_evidence:
        successful = tuple(
            item
            for item in capability_evidence
            if item.status.casefold() in {"calculated", "success", "ok", "available", "captured"}
        )
        coverage = (
            *coverage,
            CoverageState(
                schema_version="open_agronomy_agent.coverage_state.v1",
                slot_key="capability_result",
                status="ADEQUATE" if successful else "PARTIAL",
                required_authority=None,
                evidence_capsule_ids=(),
                missing_inputs=(),
                reasons=(
                    "typed capability result captured with stable invocation and result identity"
                    if successful
                    else "capability record captured without a successful result"
                ,),
            ),
        )
    packed_text = str(getattr(packed_context, "text", "") or "")
    packet_seed = {
        "question_frame_id": question_frame.question_frame_id,
        "selected_document_order": [str(getattr(doc, "doc_id", "")) for doc in docs],
        "capsule_ids": [capsule.capsule_id for capsule in capsules],
        "capability_evidence_ids": [item.evidence_id for item in capability_evidence],
        "coverage": [state.to_dict() for state in coverage],
        "version_ledger": dict(version_ledger),
    }
    return EvidencePacket(
        schema_version="open_agronomy_agent.evidence_packet.v1",
        packet_id=content_id("packet", packet_seed),
        question_frame_id=question_frame.question_frame_id,
        source_assets=tuple(assets.values()),
        source_versions=tuple(versions.values()),
        spans=tuple(spans),
        applicability=tuple(applicability),
        capsules=tuple(capsules),
        coverage=coverage,
        capability_evidence=capability_evidence,
        selected_document_order=tuple(str(getattr(doc, "doc_id", "")) for doc in docs),
        packed_context_sha256=sha256_text(packed_text) if packed_text else None,
        version_ledger=dict(version_ledger),
        capture_status=(
            "no_evidence_selected"
            if not docs and not capability_evidence
            else "capability_evidence_only"
            if not docs
            else "canonical_adapter_complete"
            if all(version.capture_status == "complete_hash_lineage" for version in versions.values())
            else "canonical_adapter_with_legacy_gaps"
        ),
    )


def validated_answer_from_runtime(
    *,
    answer: str,
    evidence_packet: Mapping[str, Any] | EvidencePacket | None,
    verifier_record: Mapping[str, Any] | None,
) -> ValidatedAnswer:
    packet_id = (
        evidence_packet.packet_id
        if isinstance(evidence_packet, EvidencePacket)
        else str((evidence_packet or {}).get("packet_id") or "") or None
    )
    verifier = dict(verifier_record or {}) or None
    final_assessment = (verifier or {}).get("final_assessment") or (verifier or {}).get("draft_assessment") or {}
    requires_review = bool(final_assessment.get("requires_review", False)) if verifier else True
    typed_capability_validation = bool(
        verifier
        and verifier.get("selection_policy") == "typed_capability_identity_v1"
        and verifier.get("status") == "validated"
        and any(str(value or "").strip() for value in (verifier.get("result_ids") or ()))
    )
    status = (
        "validated_typed_capability_result"
        if typed_capability_validation
        else "legacy_verifier_pass"
        if verifier and not requires_review
        else "review_required"
    )
    return ValidatedAnswer(
        schema_version="open_agronomy_agent.validated_answer.v1",
        validated_answer_id=content_id(
            "validated_answer",
            {"answer_sha256": sha256_text(answer), "packet_id": packet_id, "status": status},
        ),
        answer_sha256=sha256_text(answer),
        evidence_packet_id=packet_id,
        claims=(),
        answer_status=status,
        verifier_record=verifier,
        validation_policy=(
            "typed_capability_identity_v1"
            if typed_capability_validation
            else "legacy_text_verifier_adapter_no_claim_level_attestation"
        ),
        capture_status=(
            "exact_typed_capability_result_validated"
            if typed_capability_validation
            else "answer_captured_claim_lineage_not_yet_validated"
        ),
    )


def legacy_evidence_fabric_record(record: Mapping[str, Any] | None) -> dict[str, Any]:
    """Never silently relabel a pre-contract trace as canonically captured."""

    if not isinstance(record, Mapping) or record.get("schema_version") != CONTRACT_FAMILY_VERSION:
        return {
            "schema_version": CONTRACT_FAMILY_VERSION,
            "status": "legacy_not_captured",
            "question_frame": None,
            "evidence_packet": None,
            "validated_answer": None,
        }
    return dict(record)


def build_evidence_fabric_record(
    *,
    question_frame: QuestionFrame,
    evidence_packet: EvidencePacket,
    validated_answer: ValidatedAnswer | None = None,
) -> dict[str, Any]:
    record = {
        "schema_version": CONTRACT_FAMILY_VERSION,
        "status": "captured",
        "question_frame": question_frame.to_dict(),
        "evidence_packet": evidence_packet.to_dict(),
        "validated_answer": validated_answer.to_dict() if validated_answer is not None else None,
    }
    record["record_sha256"] = sha256_text(canonical_json(record))
    return record


def extend_evidence_fabric_capabilities(
    record: Mapping[str, Any],
    capability_records: Iterable[Mapping[str, Any] | Any],
) -> dict[str, Any]:
    """Append late-bound adapter results while preserving packet identity rules."""

    output = dict(record)
    packet = dict(output.get("evidence_packet") or {})
    if not packet:
        return output
    existing = [
        dict(item)
        for item in (packet.get("capability_evidence") or [])
        if isinstance(item, Mapping)
    ]
    additions = [item.to_dict() for item in capability_evidence_from_records(capability_records)]
    by_id = {
        str(item.get("evidence_id") or ""): item
        for item in (*existing, *additions)
        if str(item.get("evidence_id") or "")
    }
    if len(by_id) == len(existing):
        return output
    packet["capability_evidence"] = list(by_id.values())
    coverage = [
        dict(item)
        for item in (packet.get("coverage") or [])
        if isinstance(item, Mapping) and item.get("slot_key") != "capability_result"
    ]
    successful = any(
        str(item.get("status") or "").casefold()
        in {"calculated", "success", "ok", "available", "captured", "source_lane_available"}
        for item in by_id.values()
    )
    coverage.append(
        CoverageState(
            schema_version="open_agronomy_agent.coverage_state.v1",
            slot_key="capability_result",
            status="ADEQUATE" if successful else "PARTIAL",
            required_authority=None,
            evidence_capsule_ids=(),
            missing_inputs=(),
            reasons=(
                "typed capability result captured with stable invocation and result identity"
                if successful
                else "capability record captured without a successful result",
            ),
        ).to_dict()
    )
    packet["coverage"] = coverage
    packet["packet_id"] = content_id(
        "packet",
        {
            "question_frame_id": packet.get("question_frame_id"),
            "selected_document_order": packet.get("selected_document_order") or [],
            "capsule_ids": [
                item.get("capsule_id")
                for item in (packet.get("capsules") or [])
                if isinstance(item, Mapping)
            ],
            "capability_evidence_ids": sorted(by_id),
            "coverage": coverage,
            "version_ledger": packet.get("version_ledger") or {},
        },
    )
    packet["capture_status"] = (
        "capability_evidence_only"
        if not packet.get("source_assets")
        else "canonical_adapter_with_capability_evidence"
    )
    output["evidence_packet"] = packet
    output["record_sha256"] = sha256_text(
        canonical_json({key: value for key, value in output.items() if key != "record_sha256"})
    )
    return output
