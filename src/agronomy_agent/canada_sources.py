from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from agronomy_agent.paths import repo_path
from agronomy_agent.query_context import extract_crop_entities


SCHEMA_VERSION = "open_agronomy_agent.canada_agronomy_sources.v1"
USE_CASES = {"discover", "download", "local_rag", "distributable_bundle", "training", "live_retrieval"}
PROJECT_MANAGED_CONTENT_USE_CASES = {"download", "local_rag", "training"}
UNVERIFIED_CONTENT_LICENSE_STATUSES = {
    "permission_required",
    "live_reference_only",
    "review_required",
}
LICENSE_STATUSES = {
    "redistributable",
    "local_noncommercial_only",
    "permission_required",
    "live_reference_only",
    "review_required",
}
LICENSE_SCOPE_BASES = {
    "source_specific_record",
    "jurisdiction_wide_open_licence",
    "item_not_labelled",
    "permission_or_clarification_required",
}
CONTENT_MODES = {
    "corpus_document",
    "source_hub",
    "geospatial_tool",
    "live_regulatory_boundary",
    "structured_snapshot",
}
RUNTIME_SOURCE_TYPES = {"applied_guidance", "regional_environment_profile"}
REQUIRED_SOURCE_FIELDS = {
    "id",
    "title",
    "publisher",
    "authority_type",
    "jurisdiction",
    "language",
    "url",
    "format",
    "content_mode",
    "crops",
    "buckets",
    "priority",
    "currency",
    "regulatory",
    "license",
    "use_policy",
}

DEFAULT_CANADA_SOURCE_MANIFEST_PATH = "data/manifests/canada_agronomy_sources.json"

_CANADIAN_PROVINCE_CODES = {
    "AB": "Alberta",
    "BC": "British Columbia",
    "MB": "Manitoba",
    "NB": "New Brunswick",
    "NL": "Newfoundland and Labrador",
    "NS": "Nova Scotia",
    "ON": "Ontario",
    "PE": "Prince Edward Island",
    "QC": "Quebec",
    "SK": "Saskatchewan",
}
_CANADIAN_PROVINCE_ALIASES = {
    "COLOMBIE-BRITANNIQUE": "British Columbia",
    "COLOMBIE BRITANNIQUE": "British Columbia",
    "NOUVEAU-BRUNSWICK": "New Brunswick",
    "NOUVEAU BRUNSWICK": "New Brunswick",
    "TERRE-NEUVE-ET-LABRADOR": "Newfoundland and Labrador",
    "TERRE-NEUVE ET LABRADOR": "Newfoundland and Labrador",
    "NOUVELLE-ÉCOSSE": "Nova Scotia",
    "NOUVELLE ECOSSE": "Nova Scotia",
    "ÎLE-DU-PRINCE-ÉDOUARD": "Prince Edward Island",
    "ILE-DU-PRINCE-EDOUARD": "Prince Edward Island",
    "ÎLE DU PRINCE ÉDOUARD": "Prince Edward Island",
    "ILE DU PRINCE EDOUARD": "Prince Edward Island",
    "QUÉBEC": "Quebec",
}


@dataclass(frozen=True)
class CanadianCoverageBoundary:
    jurisdiction: str
    status: str
    registered_source_ids: tuple[str, ...]
    distributable_source_ids: tuple[str, ...]
    retrieved_source_ids: tuple[str, ...]
    retrieved_context_source_ids: tuple[str, ...]
    live_references: tuple[dict[str, Any], ...]

    @property
    def requires_prompt_boundary(self) -> bool:
        return self.status != "province_specific_guidance_retrieved"

    def prompt_block(self) -> str:
        if not self.requires_prompt_boundary:
            return ""
        if self.status == "distributable_guidance_not_retrieved":
            evidence_state = (
                "The source registry contains distributable province-specific guidance, but no matching "
                "province-specific applied-guidance chunk survived retrieval for this turn. Treat this as a retrieval gap."
            )
        elif self.status == "province_specific_context_retrieved":
            evidence_state = (
                "Province-specific material was retrieved, but it is governed as context-only and cannot supply "
                "current local calibration, rates, thresholds, timing rules, product choices, or legal requirements."
            )
        elif self.status == "live_reference_only":
            evidence_state = (
                "The distributable local corpus contains no province-specific applied-guidance document for this jurisdiction. "
                "The source registry contains official discovery or live-reference sources only."
            )
        else:
            evidence_state = (
                "No province-specific applied-guidance source is available from the distributable registry for this jurisdiction."
            )
        return (
            f"Canadian jurisdiction evidence boundary: {self.jurisdiction}. {evidence_state} "
            "Do not substitute guidance, calibration, rates, thresholds, timing rules, product choices, or legal requirements "
            "from another province. Give general agronomic reasoning when it is useful, state the local evidence gap briefly "
            "when it materially affects the decision, and direct locally calibrated decisions to the current provincial authority. "
            "For pesticide use, the current PMRA product label remains authoritative."
        )

    def as_record(self) -> dict[str, Any]:
        return {
            "jurisdiction": self.jurisdiction,
            "status": self.status,
            "requires_prompt_boundary": self.requires_prompt_boundary,
            "registered_source_ids": list(self.registered_source_ids),
            "distributable_source_ids": list(self.distributable_source_ids),
            "retrieved_source_ids": list(self.retrieved_source_ids),
            "retrieved_context_source_ids": list(self.retrieved_context_source_ids),
            "live_references": [dict(item) for item in self.live_references],
            "prompt_block": self.prompt_block(),
        }


def canonical_canadian_province(value: str | None) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    upper = raw.upper()
    if upper in _CANADIAN_PROVINCE_CODES:
        return _CANADIAN_PROVINCE_CODES[upper]
    if upper in _CANADIAN_PROVINCE_ALIASES:
        return _CANADIAN_PROVINCE_ALIASES[upper]
    for province in _CANADIAN_PROVINCE_CODES.values():
        if upper == province.upper():
            return province
    return None


def build_canadian_coverage_boundary(
    jurisdiction: str | None,
    retrieved_docs: Iterable[Any],
    *,
    question: str | None = None,
    manifest_path: str | Path = DEFAULT_CANADA_SOURCE_MANIFEST_PATH,
) -> CanadianCoverageBoundary | None:
    province = canonical_canadian_province(jurisdiction)
    if province is None:
        return None

    manifest = _cached_source_manifest(str(repo_path(manifest_path).resolve()))
    registered = [
        source
        for source in manifest["sources"]
        if province in {canonical_canadian_province(value) for value in source.get("jurisdiction") or []}
    ]
    distributable = [
        source
        for source in registered
        if source_allowed_for(source, "distributable_bundle")
        and source.get("runtime_source_type") != "regional_environment_profile"
    ]
    retrieved_source_ids = sorted(
        {
            str(getattr(doc, "source_id", "") or "")
            for doc in retrieved_docs
            if str(getattr(doc, "source_type", "") or "").lower() == "applied_guidance"
            and str(getattr(doc, "retrieval_policy", "standard") or "standard").lower() == "standard"
            and province
            in {
                canonical_canadian_province(value)
                for value in getattr(doc, "jurisdictions", ()) or ()
            }
            and str(getattr(doc, "source_id", "") or "")
        }
    )
    retrieved_context_source_ids = sorted(
        {
            str(getattr(doc, "source_id", "") or "")
            for doc in retrieved_docs
            if str(getattr(doc, "source_type", "") or "").lower() == "applied_guidance"
            and str(getattr(doc, "retrieval_policy", "standard") or "standard").lower() == "context_only"
            and province
            in {
                canonical_canadian_province(value)
                for value in getattr(doc, "jurisdictions", ()) or ()
            }
            and str(getattr(doc, "source_id", "") or "")
        }
    )
    if retrieved_source_ids:
        status = "province_specific_guidance_retrieved"
    elif retrieved_context_source_ids:
        status = "province_specific_context_retrieved"
    elif distributable:
        status = "distributable_guidance_not_retrieved"
    elif registered:
        status = "live_reference_only"
    else:
        status = "unregistered_jurisdiction"

    live_references = tuple(
        _live_reference_record(source, question=question)
        for source in sorted(
            (
                source
                for source in registered
                if source_allowed_for(source, "live_retrieval")
                and source.get("runtime_source_type") != "regional_environment_profile"
            ),
            key=lambda source: _live_reference_sort_key(source, question=question),
        )
    )
    return CanadianCoverageBoundary(
        jurisdiction=province,
        status=status,
        registered_source_ids=tuple(sorted(str(source["id"]) for source in registered)),
        distributable_source_ids=tuple(sorted(str(source["id"]) for source in distributable)),
        retrieved_source_ids=tuple(retrieved_source_ids),
        retrieved_context_source_ids=tuple(retrieved_context_source_ids),
        live_references=live_references,
    )


def apply_canadian_coverage_disclosure(
    answer: str,
    *,
    question: str | None,
    boundaries: Iterable[dict[str, Any]],
) -> str:
    clean = str(answer or "").strip()
    query = str(question or "")
    if not clean or not _requires_local_authority(query):
        return clean

    additions: list[str] = []
    pesticide_question = bool(
        re.search(
            r"\b(?:pesticide|herbicide|fungicide|insecticide|spray|active ingredient|product label|"
            r"product rate|product registration|exact product)\b",
            query,
            re.IGNORECASE,
        )
    )
    legal_requirement_question = bool(
        re.search(r"\b(?:setback|legal requirement|regulat\w*)\b", query, re.IGNORECASE)
    )
    for boundary in boundaries:
        if not boundary.get("requires_prompt_boundary"):
            continue
        jurisdiction = canonical_canadian_province(str(boundary.get("jurisdiction") or ""))
        if not jurisdiction:
            continue
        status = str(boundary.get("status") or "")
        if status == "province_specific_context_retrieved":
            already_disclosed = bool(
                re.search(re.escape(jurisdiction), clean, re.IGNORECASE)
                and re.search(
                    r"\b(?:context-only|historical)\b[^.]{0,140}\b(?:guidance|calibration|rate|threshold|timing|current)\b",
                    clean,
                    re.IGNORECASE,
                )
            )
        else:
            already_disclosed = bool(
                re.search(re.escape(jurisdiction), clean, re.IGNORECASE)
                and re.search(
                    r"\b(?:current|provincial|province-specific|local)\b[^.]{0,100}\b(?:guidance|authority|source|calibration|label)\b",
                    clean,
                    re.IGNORECASE,
                )
            )
        if already_disclosed:
            sentence = ""
        elif status == "distributable_guidance_not_retrieved":
            sentence = (
                f"No {jurisdiction}-specific applied guidance was retrieved for this turn, so verify locally calibrated "
                f"rates, thresholds, and timing with current {jurisdiction} agricultural guidance."
            )
        elif status == "province_specific_context_retrieved":
            sentence = (
                f"The retrieved {jurisdiction} material is context-only, not current decisive applied guidance, so verify "
                f"locally calibrated rates, thresholds, and timing with current {jurisdiction} agricultural guidance."
            )
        else:
            sentence = (
                f"The current evidence bundle does not contain {jurisdiction}-specific applied guidance, so verify locally calibrated "
                f"rates, thresholds, and timing with current {jurisdiction} agricultural guidance."
            )

        query_crops = set(extract_crop_entities(query.lower()))
        live_reference = None if legal_requirement_question else next(
            (
                item
                for item in boundary.get("live_references") or []
                if isinstance(item, dict)
                and int(item.get("selection_score") or 0) > 0
                and bool(((item.get("selection_basis") or {}).get("matched_terms") or []))
                and _live_reference_crop_compatible(item, query_crops=query_crops)
                and _safe_https_url(item.get("url"))
                and str(item.get("title") or "").strip()
            ),
            None,
        )
        if live_reference and str(live_reference["url"]) not in clean:
            title = _markdown_link_text(str(live_reference["title"]))
            sentence += (
                f" When connected, check the official [{title}]({live_reference['url']}) before acting; "
                "this is a live reference, not evidence retrieved into this answer."
            )
        if pesticide_question and "PMRA product label" not in clean:
            sentence += " The current PMRA product label controls pesticide use."
        if sentence.strip():
            additions.append(sentence.strip())
    if not additions:
        return clean
    return f"{clean}\n\n{' '.join(dict.fromkeys(additions))}".strip()


def _live_reference_crop_compatible(item: dict[str, Any], *, query_crops: set[str]) -> bool:
    """Do not surface a crop-specific live link for a different named crop."""

    if not query_crops:
        return True
    source_crops = set(extract_crop_entities(" ".join(str(value) for value in item.get("crops") or ())))
    return not source_crops or bool(query_crops & source_crops)


def _requires_local_authority(question: str) -> bool:
    return bool(
        re.search(
            r"\b(?:rate|how much|threshold|recommend|recommendation|apply|application|spray|label|"
            r"product label|product rate|product registration|exact product|which product|what product|"
            r"fertiliz\w*|nitrogen|phosphorus|potassium|sulphur|sulfur|"
            r"lime|exact (?:irrigation )?(?:depth|timing|schedule|date|interval)|"
            r"setback|legal requirement|regulat\w*|"
            r"seeding date|planting date|harvest timing|trafficability|field traffic|"
            r"driv(?:e|es|en|ing)\b[^.?\n]{0,35}\b(?:equipment|machinery|tractor|vehicle|field|corner|area)|"
            r"(?:equipment|machinery|tractor|vehicle)\b[^.?\n]{0,35}\b(?:enter(?:s|ed|ing)?|driv(?:e|es|en|ing)))\b",
            question,
            re.IGNORECASE,
        )
    )


_QUERY_BUCKET_RULES: tuple[tuple[re.Pattern[str], tuple[str, ...]], ...] = (
    (
        re.compile(
            r"\b(?:fertiliz\w*|nutrient\w*|nitrogen|phosphorus|phosphate|potassium|potash|"
            r"sulphur|sulfur|lime|manure|compost|soil test\w*|soil sampl\w*|tissue sampl\w*)\b",
            re.IGNORECASE,
        ),
        ("nutrient_management", "soil_water"),
    ),
    (
        re.compile(
            r"\b(?:pesticide|herbicide|fungicide|insecticide|spray|weed\w*|disease\w*|"
            r"infect\w*|clubroot|blight|rust|insect\w*|pathogen\w*|product label|active ingredient)\b",
            re.IGNORECASE,
        ),
        ("pest_management", "weeds", "diseases", "product_stewardship"),
    ),
    (
        re.compile(
            r"\b(?:seed\w*|plant\w*|harvest\w*|rotation|tillage|stand|crop management)\b",
            re.IGNORECASE,
        ),
        ("crop_management", "seed_hybrid"),
    ),
    (
        re.compile(
            r"\b(?:irrigat\w*|drain\w*|erosion|moisture|drought|water|runoff|conservation)\b",
            re.IGNORECASE,
        ),
        ("soil_water", "water_weather", "conservation"),
    ),
    (
        re.compile(
            r"\b(?:trafficability|compaction|rutting|smearing|tractor|machinery|equipment|field traffic)\b",
            re.IGNORECASE,
        ),
        ("soil_water", "conservation", "field_data"),
    ),
)
_REFERENCE_QUERY_STOPWORDS = {
    "about",
    "after",
    "agriculture",
    "and",
    "apply",
    "before",
    "current",
    "crop",
    "crops",
    "exact",
    "field",
    "guidance",
    "much",
    "official",
    "rate",
    "recommend",
    "recommendation",
    "should",
    "specific",
    "what",
    "when",
    "where",
    "which",
    "with",
}
_REFERENCE_TERM_ALIASES = {
    "cereals": "cereal",
    "blight": "protection",
    "clubroot": "protection",
    "crops": "crop",
    "disease": "protection",
    "diseases": "protection",
    "forages": "forage",
    "fertilizer": "nutrient",
    "fertilizers": "nutrient",
    "fertilisation": "nutrient",
    "fertilization": "nutrient",
    "fertility": "nutrient",
    "fungicide": "protection",
    "fungicides": "protection",
    "herbicide": "protection",
    "herbicides": "protection",
    "insect": "protection",
    "insecticide": "protection",
    "insecticides": "protection",
    "insects": "protection",
    "infected": "protection",
    "infection": "protection",
    "infections": "protection",
    "nitrogen": "nutrient",
    "nutrients": "nutrient",
    "oilseeds": "oilseed",
    "pest": "protection",
    "pesticide": "protection",
    "pesticides": "protection",
    "pests": "protection",
    "potatoes": "potato",
    "phosphorus": "nutrient",
    "potassium": "nutrient",
    "sulfur": "nutrient",
    "sulphur": "nutrient",
    "spray": "protection",
    "rust": "protection",
    "trafficking": "trafficability",
    "weed": "protection",
    "weeds": "protection",
}
_PRIORITY_RANK = {"critical": 3, "high": 2, "medium": 1}


def _live_reference_record(source: dict[str, Any], *, question: str | None) -> dict[str, Any]:
    score, matched_buckets, matched_terms = _live_reference_match(source, question=question)
    return {
        "source_id": str(source["id"]),
        "title": str(source["title"]),
        "url": str(source["url"]),
        "publisher": str(source.get("publisher") or ""),
        "language": [str(value) for value in source.get("language") or []],
        "crops": [str(value) for value in source.get("crops") or []],
        "buckets": [str(value) for value in source.get("buckets") or []],
        "currency_status": str((source.get("currency") or {}).get("status") or ""),
        "require_live_authority": bool((source.get("regulatory") or {}).get("require_live_authority")),
        "license_status": str((source.get("license") or {}).get("status") or ""),
        "selection_score": score,
        "selection_basis": {
            "matched_buckets": list(matched_buckets),
            "matched_terms": list(matched_terms),
        },
    }


def _live_reference_sort_key(source: dict[str, Any], *, question: str | None) -> tuple[int, int, str]:
    score, _, _ = _live_reference_match(source, question=question)
    return (-score, -_PRIORITY_RANK.get(str(source.get("priority") or "").lower(), 0), str(source["id"]))


def _live_reference_match(
    source: dict[str, Any],
    *,
    question: str | None,
) -> tuple[int, tuple[str, ...], tuple[str, ...]]:
    query = str(question or "").lower()
    if not query:
        return 0, (), ()

    matched_query_groups = [
        set(buckets)
        for pattern, buckets in _QUERY_BUCKET_RULES
        if pattern.search(query)
    ]
    query_buckets = set().union(*matched_query_groups) if matched_query_groups else set()
    source_buckets = {str(value).lower() for value in source.get("buckets") or []}
    matched_buckets = tuple(sorted(query_buckets & source_buckets))

    query_terms = {
        _REFERENCE_TERM_ALIASES.get(token, token)
        for token in re.findall(r"[a-zà-ÿ][a-zà-ÿ-]{2,}", query)
        if token not in _REFERENCE_QUERY_STOPWORDS
    }
    source_terms = {
        _REFERENCE_TERM_ALIASES.get(token, token)
        for value in (
            str(source.get("title") or ""),
            *(str(item) for item in source.get("crops") or []),
            *(str(item) for item in source.get("keywords") or []),
        )
        for token in re.findall(r"[a-zà-ÿ][a-zà-ÿ-]{2,}", value.lower())
    }
    matched_terms = tuple(sorted(query_terms & source_terms))
    # A source should not win merely because the manifest represents one topic
    # with several overlapping buckets (for example pest management, weeds,
    # diseases, and product stewardship). Score each matched query topic once;
    # keep the individual bucket matches in the trace for auditability.
    matched_topic_count = sum(bool(group & source_buckets) for group in matched_query_groups)
    score = 12 * matched_topic_count + 4 * len(matched_terms)
    return score, matched_buckets, matched_terms


def _markdown_link_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")


@lru_cache(maxsize=4)
def _cached_source_manifest(path: str) -> dict[str, Any]:
    return load_canada_source_manifest(Path(path))


def load_canada_source_manifest(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    errors = validate_canada_source_manifest(payload)
    if errors:
        raise ValueError("Invalid Canadian source manifest:\n- " + "\n- ".join(errors))
    return payload


def validate_canada_source_manifest(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if payload.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    required_jurisdictions = payload.get("required_jurisdictions")
    if not isinstance(required_jurisdictions, list) or not all(_text(value) for value in required_jurisdictions):
        errors.append("required_jurisdictions must be a non-empty string list")
        required_jurisdictions = []
    sources = payload.get("sources")
    if not isinstance(sources, list) or not sources:
        return errors + ["sources must be a non-empty list"]

    ids = [str(source.get("id") or "") for source in sources if isinstance(source, dict)]
    duplicate_ids = sorted(value for value, count in Counter(ids).items() if value and count > 1)
    if duplicate_ids:
        errors.append(f"duplicate source ids: {duplicate_ids}")

    covered_jurisdictions: set[str] = set()
    for index, source in enumerate(sources):
        prefix = f"sources[{index}]"
        if not isinstance(source, dict):
            errors.append(f"{prefix} must be an object")
            continue
        source_id = _text(source.get("id")) or prefix
        prefix = source_id
        missing = sorted(field for field in REQUIRED_SOURCE_FIELDS if field not in source)
        if missing:
            errors.append(f"{prefix} missing fields: {missing}")
            continue
        if source.get("content_mode") not in CONTENT_MODES:
            errors.append(f"{prefix} has invalid content_mode")
        if not _safe_https_url(source.get("url")):
            errors.append(f"{prefix}.url must be an https URL")
        if source.get("download_url") is not None and not _safe_https_url(source.get("download_url")):
            errors.append(f"{prefix}.download_url must be an https URL when present")
        expected_raw_sha256 = source.get("expected_raw_sha256")
        if expected_raw_sha256 is not None and not re.fullmatch(
            r"[0-9a-fA-F]{64}", _text(expected_raw_sha256)
        ):
            errors.append(f"{prefix}.expected_raw_sha256 must be a 64-character hexadecimal SHA-256")
        runtime_source_type = source.get("runtime_source_type")
        if runtime_source_type is not None and runtime_source_type not in RUNTIME_SOURCE_TYPES:
            errors.append(f"{prefix}.runtime_source_type is invalid")
        for key in ("jurisdiction", "language", "crops", "buckets"):
            values = source.get(key)
            if not isinstance(values, list) or not values or not all(_text(value) for value in values):
                errors.append(f"{prefix}.{key} must be a non-empty string list")
        covered_jurisdictions.update(str(value) for value in source.get("jurisdiction") or [])

        currency = source.get("currency")
        if not isinstance(currency, dict) or not _text(currency.get("status")):
            errors.append(f"{prefix}.currency.status is required")
        elif not isinstance(currency.get("volatile"), bool):
            errors.append(f"{prefix}.currency.volatile must be boolean")
        elif not isinstance(currency.get("review_interval_days"), int) or currency["review_interval_days"] <= 0:
            errors.append(f"{prefix}.currency.review_interval_days must be positive")

        regulatory = source.get("regulatory")
        if not isinstance(regulatory, dict) or not isinstance(regulatory.get("regulated_advice"), bool):
            errors.append(f"{prefix}.regulatory.regulated_advice must be boolean")
        elif not isinstance(regulatory.get("require_live_authority"), bool):
            errors.append(f"{prefix}.regulatory.require_live_authority must be boolean")

        license_record = source.get("license")
        if not isinstance(license_record, dict):
            errors.append(f"{prefix}.license must be an object")
            continue
        status = license_record.get("status")
        if status not in LICENSE_STATUSES:
            errors.append(f"{prefix}.license.status is invalid")
        for key in ("identifier", "evidence_url", "reviewed_on", "attribution", "notes"):
            if not _text(license_record.get(key)):
                errors.append(f"{prefix}.license.{key} is required")
        if not _safe_https_url(license_record.get("evidence_url")):
            errors.append(f"{prefix}.license.evidence_url must be an https URL")
        if "scope_verified" in license_record and not isinstance(license_record.get("scope_verified"), bool):
            errors.append(f"{prefix}.license.scope_verified must be boolean when present")
        if "scope_basis" in license_record and license_record.get("scope_basis") not in LICENSE_SCOPE_BASES:
            errors.append(f"{prefix}.license.scope_basis is invalid")
        if "scope_evidence_url" in license_record and not _safe_https_url(
            license_record.get("scope_evidence_url")
        ):
            errors.append(f"{prefix}.license.scope_evidence_url must be an https URL when present")
        use_policy = source.get("use_policy")
        if not isinstance(use_policy, dict) or set(use_policy) != USE_CASES:
            errors.append(f"{prefix}.use_policy must contain exactly {sorted(USE_CASES)}")
            continue
        if not all(isinstance(value, bool) for value in use_policy.values()):
            errors.append(f"{prefix}.use_policy values must be boolean")
        if status in UNVERIFIED_CONTENT_LICENSE_STATUSES:
            enabled_content_uses = sorted(
                use_case
                for use_case in PROJECT_MANAGED_CONTENT_USE_CASES
                if use_policy.get(use_case) is True
            )
            if enabled_content_uses:
                errors.append(
                    f"{prefix} license status {status} cannot enable project-managed content uses "
                    f"{enabled_content_uses}"
                )
        if use_policy.get("distributable_bundle"):
            if status != "redistributable":
                errors.append(f"{prefix} distributable_bundle requires redistributable license status")
            if license_record.get("scope_verified") is not True:
                errors.append(f"{prefix} distributable_bundle requires license.scope_verified=true")
            if license_record.get("scope_basis") not in {
                "source_specific_record",
                "jurisdiction_wide_open_licence",
            }:
                errors.append(
                    f"{prefix} distributable_bundle requires a verified source-specific or jurisdiction-wide scope basis"
                )
            if not _safe_https_url(license_record.get("scope_evidence_url")):
                errors.append(f"{prefix} distributable_bundle requires license.scope_evidence_url")
            for key in ("permits_modification", "permits_commercial", "permits_redistribution"):
                if license_record.get(key) is not True:
                    errors.append(f"{prefix} distributable_bundle requires license.{key}=true")
            if not use_policy.get("download"):
                errors.append(f"{prefix} distributable_bundle requires download")
            if (
                source.get("content_mode") != "structured_snapshot"
                and not use_policy.get("local_rag")
            ):
                errors.append(
                    f"{prefix} distributable_bundle requires local_rag unless content_mode is structured_snapshot"
                )
        if source.get("content_mode") == "live_regulatory_boundary" and use_policy.get("distributable_bundle"):
            errors.append(f"{prefix} live regulatory content cannot be a distributable static bundle")
        if source.get("content_mode") == "structured_snapshot":
            if use_policy.get("local_rag"):
                errors.append(
                    f"{prefix} structured_snapshot must use a typed adapter instead of local_rag"
                )
            snapshot = source.get("snapshot")
            if not isinstance(snapshot, dict):
                errors.append(f"{prefix}.snapshot must be an object for structured_snapshot")
            else:
                for key in ("path", "manifest_path"):
                    if not _safe_relative_path(snapshot.get(key)):
                        errors.append(
                            f"{prefix}.snapshot.{key} must be a safe repository-relative path"
                        )
                if (
                    not isinstance(snapshot.get("row_count"), int)
                    or snapshot["row_count"] <= 0
                ):
                    errors.append(f"{prefix}.snapshot.row_count must be positive")
                if not re.fullmatch(
                    r"\d{4}-\d{2}-\d{2}",
                    _text(snapshot.get("source_release_date")),
                ):
                    errors.append(
                        f"{prefix}.snapshot.source_release_date must be YYYY-MM-DD"
                    )
        if regulatory.get("require_live_authority") and use_policy.get("training"):
            errors.append(f"{prefix} current-authority content cannot be enabled for training")

        ingest_policy = source.get("ingest_policy")
        if ingest_policy is not None:
            if not isinstance(ingest_policy, dict):
                errors.append(f"{prefix}.ingest_policy must be an object")
            else:
                for range_key in ("include_page_ranges", "exclude_page_ranges"):
                    page_ranges = ingest_policy.get(range_key, [])
                    if not isinstance(page_ranges, list) or not all(
                        isinstance(value, list)
                        and len(value) == 2
                        and all(isinstance(page, int) and page > 0 for page in value)
                        and value[0] <= value[1]
                        for value in page_ranges
                    ):
                        errors.append(
                            f"{prefix}.ingest_policy.{range_key} must contain positive [start, end] page ranges"
                        )
                line_patterns = ingest_policy.get("exclude_line_patterns", [])
                if not isinstance(line_patterns, list) or not all(_text(value) for value in line_patterns):
                    errors.append(f"{prefix}.ingest_policy.exclude_line_patterns must be a string list")
                else:
                    for pattern in line_patterns:
                        try:
                            re.compile(str(pattern))
                        except re.error as exc:
                            errors.append(f"{prefix}.ingest_policy.exclude_line_patterns has invalid regex: {exc}")
                semantic_companion_path = ingest_policy.get("semantic_companion_path")
                if semantic_companion_path is not None and not _text(semantic_companion_path):
                    errors.append(f"{prefix}.ingest_policy.semantic_companion_path must be a non-empty string")
                elif semantic_companion_path is not None and not _safe_relative_path(
                    semantic_companion_path
                ):
                    errors.append(
                        f"{prefix}.ingest_policy.semantic_companion_path must be a safe repository-relative path"
                    )
                semantic_companion_sha256 = ingest_policy.get(
                    "semantic_companion_sha256"
                )
                if semantic_companion_path is not None and not re.fullmatch(
                    r"[0-9a-f]{64}", _text(semantic_companion_sha256)
                ):
                    errors.append(
                        f"{prefix}.ingest_policy.semantic_companion_sha256 must be a lowercase SHA-256 when semantic_companion_path is set"
                    )
                elif semantic_companion_path is None and semantic_companion_sha256 is not None:
                    errors.append(
                        f"{prefix}.ingest_policy.semantic_companion_sha256 requires semantic_companion_path"
                    )
                emit_source_chunks = ingest_policy.get("emit_source_chunks", True)
                if not isinstance(emit_source_chunks, bool):
                    errors.append(f"{prefix}.ingest_policy.emit_source_chunks must be boolean")
                elif emit_source_chunks is False and not _text(semantic_companion_path):
                    errors.append(
                        f"{prefix}.ingest_policy.emit_source_chunks=false requires semantic_companion_path"
                    )

    missing_jurisdictions = sorted(set(required_jurisdictions) - covered_jurisdictions)
    if missing_jurisdictions:
        errors.append(f"required jurisdictions without a source: {missing_jurisdictions}")
    return errors


def source_allowed_for(source: dict[str, Any], use_case: str) -> bool:
    if use_case not in USE_CASES:
        raise ValueError(f"unknown source use case: {use_case}")
    if (source.get("use_policy") or {}).get(use_case) is not True:
        return False
    license_record = source.get("license") or {}
    if (
        use_case in PROJECT_MANAGED_CONTENT_USE_CASES
        and license_record.get("status") in UNVERIFIED_CONTENT_LICENSE_STATUSES
    ):
        return False
    if use_case != "distributable_bundle":
        return True
    return (
        license_record.get("status") == "redistributable"
        and license_record.get("scope_verified") is True
        and license_record.get("scope_basis")
        in {"source_specific_record", "jurisdiction_wide_open_licence"}
        and bool(_safe_https_url(license_record.get("scope_evidence_url")))
        and license_record.get("permits_modification") is True
        and license_record.get("permits_commercial") is True
        and license_record.get("permits_redistribution") is True
    )


def source_license_snapshot(source: dict[str, Any]) -> dict[str, Any]:
    license_record = source.get("license") or {}
    return {
        "status": license_record.get("status"),
        "identifier": license_record.get("identifier"),
        "evidence_url": license_record.get("evidence_url"),
        "scope_verified": license_record.get("scope_verified"),
        "scope_basis": license_record.get("scope_basis"),
        "scope_evidence_url": license_record.get("scope_evidence_url"),
        "reviewed_on": license_record.get("reviewed_on"),
        "attribution": license_record.get("attribution"),
        "permits_modification": license_record.get("permits_modification"),
        "permits_commercial": license_record.get("permits_commercial"),
        "permits_redistribution": license_record.get("permits_redistribution"),
    }


def _text(value: Any) -> str:
    return str(value or "").strip()


def _safe_https_url(value: Any) -> str:
    url = _text(value)
    return url if re.fullmatch(r"https://[^\s<>()]+", url, re.IGNORECASE) else ""


def _safe_relative_path(value: Any) -> str:
    text = _text(value)
    if not text:
        return ""
    path = Path(text)
    if path.is_absolute() or ".." in path.parts:
        return ""
    return text
