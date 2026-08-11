from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from html import unescape


LEAK_GUARD_VERSION = "phase5.leak_guard.v3"

_LABEL_SEPARATOR = r"[\s_-]+"


def _internal_label_pattern(label: str) -> re.Pattern[str]:
    return re.compile(rf"\b{_LABEL_SEPARATOR.join(label.split())}\s*:", re.IGNORECASE)


_FIELD_NAME_PATTERNS = {
    "question_type": r"question(?:[_-]*type|Type)",
    "risk": r"risk(?:[_-]*level|Level)?",
    "priority_namespaces": r"priority(?:[_-]*namespaces|Namespaces)",
    "product_label": r"product(?:[_-]+label|Label)",
    "field_data": r"field(?:[_-]+data|Data)",
    "soil_water": r"soil(?:[_-]+water|Water)",
}


_LEAK_PATTERNS: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    ("routing_notes", "high", _internal_label_pattern("routing notes")),
    ("tool_notes", "high", _internal_label_pattern("tool notes")),
    ("coverage_checklist", "high", _internal_label_pattern("answer coverage checklist")),
    ("management_lane", "high", _internal_label_pattern("management lane")),
    ("decision_focus", "high", _internal_label_pattern("decision focus")),
    ("start_answer_instruction", "high", re.compile(r"Start the answer with", re.IGNORECASE)),
    ("evidence_handshake", "high", re.compile(r"\bcompact evidence handshake\b", re.IGNORECASE)),
    ("primary_decision_evidence", "high", re.compile(r"\bprimary decision evidence\s*:", re.IGNORECASE)),
    ("supporting_boundary_evidence", "high", re.compile(r"\bsupporting or boundary evidence\s*:", re.IGNORECASE)),
    ("evidence_roles", "high", re.compile(r"\bevidence roles\s*:", re.IGNORECASE)),
    ("commit_rule", "high", re.compile(r"\bcommit rule\s*:", re.IGNORECASE)),
    ("preserve_entities", "medium", re.compile(r"^\s*[-*•]?\s*preserve\s*:", re.IGNORECASE | re.MULTILINE)),
    ("route_field", "medium", re.compile(rf"\b{_FIELD_NAME_PATTERNS['question_type']}\s*=", re.IGNORECASE)),
    ("risk_field", "medium", re.compile(rf"\b{_FIELD_NAME_PATTERNS['risk']}\s*=", re.IGNORECASE)),
    ("priority_namespaces", "medium", re.compile(rf"\b{_FIELD_NAME_PATTERNS['priority_namespaces']}\b", re.IGNORECASE)),
    ("hidden_instructions", "high", re.compile(r"\bhidden instructions\b", re.IGNORECASE)),
    ("hidden_prompt_language", "high", re.compile(r"\b(?:system prompt|hidden prompt|internal prompt|prompt template|internal instructions)\b", re.IGNORECASE)),
    ("developer_policy_language", "high", re.compile(r"\b(?:developer message|developer policy|developer instructions)\b", re.IGNORECASE)),
    ("internal_rubric", "high", re.compile(r"\b(?:internal rubric|rubric score|scoring details)\b", re.IGNORECASE)),
    ("eval_regex_fragment", "medium", re.compile(r"(?:required_patterns|forbidden_patterns|ask_for_patterns|forbidden_contains|\\b|\(\?i\)|\[[^\]\n]{1,40}\]\+?)", re.IGNORECASE)),
    (
        "raw_source_id",
        "medium",
        re.compile(
            r"\b(?:retrieved[_-]doc|[Ss]ource|[Cc]hunk|[Dd]oc)[_-][A-Za-z0-9][A-Za-z0-9_-]{1,40}\b"
            r"|\b(?:retrievedDoc|RetrievedDoc|[Ss]ource|[Cc]hunk|[Dd]oc)[A-Z][A-Za-z0-9]{2,40}\b"
        ),
    ),
    ("route_name_product_label", "medium", re.compile(rf"\b{_FIELD_NAME_PATTERNS['product_label']}\b", re.IGNORECASE)),
    ("route_name_field_data", "medium", re.compile(rf"\b{_FIELD_NAME_PATTERNS['field_data']}\b", re.IGNORECASE)),
    ("route_name_soil_water", "medium", re.compile(rf"\b{_FIELD_NAME_PATTERNS['soil_water']}\b", re.IGNORECASE)),
)


@dataclass(frozen=True)
class LeakFinding:
    leak_class: str
    severity: str
    matched_text_hash: str

    def as_record(self) -> dict[str, str]:
        return {
            "leak_class": self.leak_class,
            "severity": self.severity,
            "matched_text_hash": self.matched_text_hash,
        }


def detect_prompt_leaks(answer_text: str) -> list[LeakFinding]:
    findings: list[LeakFinding] = []
    scan_text = _normalize_for_leak_scan(answer_text)
    for leak_class, severity, pattern in _LEAK_PATTERNS:
        match = pattern.search(scan_text)
        if not match:
            continue
        findings.append(
            LeakFinding(
                leak_class=leak_class,
                severity=severity,
                matched_text_hash=hashlib.sha256(match.group(0).lower().encode("utf-8")).hexdigest(),
            )
        )
    return findings


def _normalize_for_leak_scan(answer_text: str) -> str:
    decoded = unescape(answer_text)
    return re.sub(r"[\u00a0\u2000-\u200a\u202f\u205f\u3000]", " ", decoded)
