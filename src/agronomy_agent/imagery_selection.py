"""Frozen bounded candidate plans and explicit field-support scene selection.

Source adapters remain the sole pixel/QA processors. Selection records are
operator artifacts, not a second pixel cache or field-action authority.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any

import httpx

from agronomy_agent.field_imagery import _dates, _valid_geometry, _request_json, _EARTH_SEARCH, _PLANETARY_COMPUTER
from agronomy_agent.geospatial.catalog import source_definition
from agronomy_agent.geospatial.cog import transfer_budget, TransferBudget
from agronomy_agent.geospatial.scene_quality import validate_policy, assess_support, rank_candidates
from agronomy_agent.imagery_budget import validate_policy as validate_storage_policy
from agronomy_agent import imagery_analytics as hls
from agronomy_agent import sentinel2_analytics as sentinel2

PLAN_VERSION = "imagery-selection-plan.v1"
SELECTION_VERSION = "imagery-selection.v1"
MAX_CANDIDATES = 8
PROVIDERS = (sentinel2.PROVIDER_ID, *hls.BAND_KEYS)


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _instant(value: Any) -> datetime:
    if not isinstance(value, str) or len(value) > 48:
        raise ValueError("UTC acquisition time required")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() != timezone.utc.utcoffset(result):
        raise ValueError("UTC acquisition time required")
    return result


def _configuration(geometry: dict[str, Any], provider_id: str, start_date: str,
                   end_date: str, policy: dict[str, Any], limit: int,
                   processing: dict[str, Any] | None) -> dict[str, Any]:
    if provider_id not in PROVIDERS:
        raise ValueError("unsupported imagery processing provider")
    geometry, _ = _valid_geometry(geometry)
    _dates(start_date, end_date)
    if type(limit) is not int or not 1 <= limit <= MAX_CANDIDATES:
        raise ValueError("candidate limit must be an integer from 1 to 8")
    policy = validate_policy(policy)
    if processing is not None and not isinstance(processing, dict):
        raise ValueError("processing options must be an object")
    if provider_id == sentinel2.PROVIDER_ID:
        options = {"cloud_buffer_m": 60, "edge_buffer_m": 20, **(processing or {})}
        if set(options) != {"cloud_buffer_m", "edge_buffer_m"}:
            raise ValueError("unexpected Sentinel-2 processing option")
        sentinel2._request(geometry, None, start_date, end_date, **options)
        version = sentinel2.PROCESS_VERSION
    else:
        if processing or policy["support"] != "field":
            raise ValueError("HLS selection supports field polygons without extra processing options")
        options = {}
        version = hls.PROCESS_VERSION
    return {"geometry": geometry, "geometry_hash": _hash(geometry), "provider_id": provider_id,
            "start_date": start_date, "end_date": end_date, "candidate_limit": limit,
            "policy": policy, "processing": options, "processor_version": version}


def _query(request: dict[str, Any]) -> dict[str, Any]:
    start, end = _dates(request["start_date"], request["end_date"])
    return {"collections": [source_definition(request["provider_id"])["collection"]],
            "intersects": request["geometry"], "datetime": f"{start}/{end}",
            "limit": request["candidate_limit"],
            "sortby": [{"field": "properties.datetime", "direction": "desc"},
                       {"field": "id", "direction": "asc"}]}


def _endpoint(provider: str) -> str:
    return _EARTH_SEARCH if provider == sentinel2.PROVIDER_ID else _PLANETARY_COMPUTER


def _expected_request(request: dict[str, Any], scene_id: str) -> str:
    if request["provider_id"] == sentinel2.PROVIDER_ID:
        return sentinel2._request(request["geometry"], scene_id, request["start_date"],
                                 request["end_date"], **request["processing"])["request_hash"]
    return hls._request_identity(request["geometry"], request["provider_id"], scene_id,
                                request["start_date"], request["end_date"], 0, None,
                                sampling_mode="field_polygon")[3]


def _candidate(item: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    collection = source_definition(request["provider_id"])["collection"]
    if not isinstance(item, dict) or item.get("collection") != collection:
        raise ValueError("candidate collection mismatch")
    item_id = item.get("id")
    if not isinstance(item_id, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,160}", item_id):
        raise ValueError("invalid candidate item identity")
    props = item.get("properties")
    if not isinstance(props, dict):
        raise ValueError("invalid candidate properties")
    acquired = props.get("datetime")
    day = _instant(acquired).date().isoformat()
    if not request["start_date"] <= day <= request["end_date"]:
        raise ValueError("candidate outside requested dates")
    cloud = props.get("eo:cloud_cover")
    if cloud is not None and (type(cloud) not in (int, float) or not math.isfinite(cloud) or not 0 <= cloud <= 100):
        raise ValueError("invalid scene cloud metadata")
    scene_id = f"{collection}:{item_id}"
    _expected_request(request, scene_id)
    return {"scene_id": scene_id, "acquired_at": acquired,
            "scene_cloud_percent": cloud, "discovery_item_sha256": _hash(item)}


def build_selection_plan(geometry: dict[str, Any], provider_id: str, start_date: str,
                         end_date: str, *, policy: dict[str, Any], limit: int = 3,
                         processing: dict[str, Any] | None = None,
                         network_mode: str = "offline") -> dict[str, Any]:
    """Freeze one bounded metadata page; never follow pagination or fetch pixels."""
    request = _configuration(geometry, provider_id, start_date, end_date, policy, limit, processing)
    if network_mode not in ("offline", "online"):
        raise ValueError("network_mode must be offline or online")
    query = _query(request)
    plan: dict[str, Any] = {"schema_version": PLAN_VERSION, "request": request,
        "created_at": datetime.now(timezone.utc).isoformat(), "status": "blocked_offline", "candidates": [],
        "discovery": {"endpoint": _endpoint(provider_id), "query_sha256": _hash(query),
                      "response_sha256": None, "returned_count": None, "more_results_indicated": None,
                      "scope": "one_bounded_page_not_exhaustive", "scene_cloud_filter": None}}
    if network_mode == "online":
        try:
            response = _request_json(_endpoint(provider_id), body=query)
            plan["discovery"]["response_sha256"] = _hash(response)
            features = response.get("features")
            if not isinstance(features, list) or len(features) > limit:
                raise ValueError("invalid bounded candidate response")
            plan["discovery"]["returned_count"] = len(features)
            links = response.get("links", [])
            if not isinstance(links, list) or any(not isinstance(link, dict) for link in links):
                raise ValueError("invalid pagination metadata")
            # A next link establishes more results; absence does not prove an
            # exhaustive period search. Never fetch or persist a next-link URL.
            plan["discovery"]["more_results_indicated"] = True if any(link.get("rel") == "next" for link in links) else None
            candidates = [_candidate(item, request) for item in features]
            if len({c["scene_id"] for c in candidates}) != len(candidates):
                raise ValueError("duplicate candidate identities")
            candidates.sort(key=lambda c: (-_instant(c["acquired_at"]).timestamp(), c["scene_id"]))
            plan.update(status="ready" if candidates else "no_scene", candidates=candidates)
        except (ValueError, TypeError, RuntimeError, httpx.HTTPError) as exc:
            plan.update(status="unavailable", reason="candidate_discovery_unavailable", error_type=type(exc).__name__)
    plan["plan_hash"] = _hash(plan)
    return plan


def validate_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """Check persisted request and candidate contracts before any cache/network use."""
    if not isinstance(plan, dict) or len(_canonical(plan)) > 2 * 1024**2:
        raise ValueError("invalid or oversized selection plan")
    if plan.get("schema_version") != PLAN_VERSION or plan.get("plan_hash") != _hash({k: v for k, v in plan.items() if k != "plan_hash"}):
        raise ValueError("selection plan identity mismatch")
    _instant(plan.get("created_at"))
    request = plan.get("request")
    if not isinstance(request, dict):
        raise ValueError("selection request is missing")
    try:
        expected = _configuration(request["geometry"], request["provider_id"], request["start_date"], request["end_date"],
                                  request["policy"], request["candidate_limit"], request["processing"])
    except KeyError as exc:
        raise ValueError("selection request is incomplete") from exc
    if request != expected:
        raise ValueError("selection request or processor version changed")
    discovery = plan.get("discovery")
    if not isinstance(discovery, dict) or discovery.get("endpoint") != _endpoint(request["provider_id"]) or discovery.get("query_sha256") != _hash(_query(request)):
        raise ValueError("selection discovery binding mismatch")
    if (set(discovery) != {"endpoint", "query_sha256", "response_sha256", "returned_count",
                           "more_results_indicated", "scope", "scene_cloud_filter"} or
            discovery["scope"] != "one_bounded_page_not_exhaustive" or
            discovery["scene_cloud_filter"] is not None or
            (discovery["more_results_indicated"] is not None and
             discovery["more_results_indicated"] is not True)):
        raise ValueError("invalid bounded discovery scope")
    response_hash = discovery["response_sha256"]
    if response_hash is not None and (not isinstance(response_hash, str) or not re.fullmatch(r"[a-f0-9]{64}", response_hash)):
        raise ValueError("invalid discovery response hash")
    if plan.get("status") in ("ready", "no_scene") and (response_hash is None or
            type(discovery["returned_count"]) is not int or
            not 0 <= discovery["returned_count"] <= request["candidate_limit"]):
        raise ValueError("missing successful discovery evidence")
    candidates = plan.get("candidates")
    if not isinstance(candidates, list) or len(candidates) > request["candidate_limit"]:
        raise ValueError("selection candidates exceed limit")
    status = plan.get("status")
    if status not in ("ready", "no_scene", "blocked_offline", "unavailable"):
        raise ValueError("unknown selection plan status")
    if (status == "ready") != bool(candidates) or (status in ("ready", "no_scene") and discovery.get("returned_count") != len(candidates)):
        raise ValueError("contradictory selection plan status/count")
    ids = set()
    for c in candidates:
        if not isinstance(c, dict) or set(c) != {"scene_id", "acquired_at", "scene_cloud_percent", "discovery_item_sha256"}:
            raise ValueError("invalid frozen candidate")
        sid = c["scene_id"]
        if not isinstance(sid, str):
            raise ValueError("candidate scene identity must be a string")
        _expected_request(request, sid)
        day = _instant(c["acquired_at"]).date().isoformat()
        if sid in ids or not request["start_date"] <= day <= request["end_date"]:
            raise ValueError("duplicate or out-of-period candidate")
        ids.add(sid)
        if not isinstance(c["discovery_item_sha256"], str) or not re.fullmatch(r"[a-f0-9]{64}", c["discovery_item_sha256"]):
            raise ValueError("candidate metadata identity missing")
        cloud = c["scene_cloud_percent"]
        if cloud is not None and (type(cloud) not in (int, float) or not math.isfinite(cloud) or not 0 <= cloud <= 100):
            raise ValueError("candidate scene cloud metadata invalid")
    if candidates != sorted(candidates, key=lambda c: (-_instant(c["acquired_at"]).timestamp(), c["scene_id"])):
        raise ValueError("candidate ordering contradicts plan")
    return json.loads(_canonical(plan))


def _receipt_matches(receipt: dict[str, Any], request: dict[str, Any], candidate: dict[str, Any]) -> bool:
    source = receipt.get("source")
    if not isinstance(source, dict):
        return False
    try:
        return (receipt.get("request_hash") == _expected_request(request, candidate["scene_id"]) and
                receipt.get("provider_id") == source.get("provider_id") == request["provider_id"] and
                receipt.get("scene_id") == source.get("scene_id") == candidate["scene_id"] and
                source.get("collection") == source_definition(request["provider_id"])["collection"] and
                receipt.get("geometry_hash") == request["geometry_hash"] and
                receipt.get("process_version") == request["processor_version"] and
                _instant(source.get("acquired_at")) == _instant(candidate["acquired_at"]) and
                all(isinstance(receipt.get(k), str) and re.fullmatch(r"[a-f0-9]{64}", receipt[k]) for k in ("chip_hash", "process_hash")))
    except (ValueError, TypeError):
        return False


def select_from_plan(plan: dict[str, Any], *, cache_root: str | Path,
                     network_mode: str = "offline", budget_root: str | Path | None = None,
                     max_cache_bytes: int = 2 * 1024**3, min_free_bytes: int = 1024**3,
                     max_cog_bytes: int = 128 * 1024**2, per_scene_cog_bytes: int = 32 * 1024**2,
                     max_cog_requests: int = 512) -> dict[str, Any]:
    """Assess every frozen candidate, preserving failures and exact chip bindings.

    A failed candidate prevents a complete winner. Ranked observed candidates
    remain inspectable; a subsequent run may fill missing chips in the same plan.
    """
    plan = validate_plan(plan)
    if network_mode not in ("offline", "online"):
        raise ValueError("network_mode must be offline or online")
    validate_storage_policy(max_cache_bytes, min_free_bytes)
    TransferBudget(max_cog_bytes, per_scene_cog_bytes, max_cog_requests)
    request = plan["request"]
    rows = []
    with transfer_budget(max_cog_bytes, per_scene_cog_bytes, max_requests=max_cog_requests) as budget:
        for candidate in plan["candidates"]:
            before = budget.snapshot()
            quota_exhausted = before["byte_limit_refusals"] > 0 or before["http_requests"] >= before["request_limit"]
            attempt_mode = "offline" if quota_exhausted else network_mode
            kwargs = dict(cache_root=cache_root, network_mode=attempt_mode, budget_root=budget_root,
                          max_cache_bytes=max_cache_bytes, min_free_bytes=min_free_bytes,
                          start_date=request["start_date"], end_date=request["end_date"])
            try:
                if request["provider_id"] == sentinel2.PROVIDER_ID:
                    receipt = sentinel2.analyze_sentinel2_scene(request["geometry"], candidate["scene_id"],
                                                               **request["processing"], **kwargs)
                else:
                    receipt = hls.analyze_scene(request["geometry"], request["provider_id"], candidate["scene_id"],
                                                sampling_mode="field_polygon", **kwargs)
            except (ValueError, RuntimeError, OSError) as exc:
                receipt = {"status": "unavailable", "error_type": type(exc).__name__}
            if quota_exhausted and receipt.get("status") == "blocked_offline":
                receipt = {**receipt, "status": "not_evaluated_resource_limit", "reason": "cog_budget_exhausted"}
            assessment = assess_support(receipt, request["policy"])
            if receipt.get("status") in ("available", "empty_valid_area") and not _receipt_matches(receipt, request, candidate):
                assessment = {"status": "unavailable", "reason": "receipt_identity_mismatch"}
            after = budget.snapshot()
            refusal_keys = ("byte_limit_refusals", "request_limit_refusals", "scene_limit_refusals")
            refusal_count = sum(after[k] - before[k] for k in refusal_keys)
            if refusal_count:
                receipt = {**receipt, "reason": "cog_budget_exhausted"}
                assessment = {"status": "unavailable", "reason": "cog_budget_exhausted"}
            rows.append({**candidate, "processing_status": receipt.get("status", "unavailable"),
                         "processing_error_type": receipt.get("error_type"),
                         "processing_reason": (receipt.get("reason") if isinstance(receipt.get("reason"), str) and
                                               re.fullmatch(r"[a-z0-9_]{1,80}", receipt["reason"]) else None),
                         "assessment": assessment, "request_hash": receipt.get("request_hash"),
                         "chip_hash": receipt.get("chip_hash"), "process_hash": receipt.get("process_hash"),
                         "cache_hit": receipt.get("cache_hit", False),
                         "cog_bytes_this_attempt": after["bytes"] - before["bytes"],
                         "cog_requests_this_attempt": after["http_requests"] - before["http_requests"],
                         "cog_budget_refusals_this_attempt": refusal_count})
        transfer = budget.snapshot()
    decision = rank_candidates([{k: row[k] for k in ("scene_id", "acquired_at", "assessment")}
                                for row in rows], request["policy"])
    if plan["status"] != "ready":
        decision.update(status=plan["status"], selected_scene_id=None)
    scientific_rows = [{k: row[k] for k in ("scene_id", "acquired_at", "assessment", "request_hash", "chip_hash", "process_hash")} for row in rows]
    result = {"schema_version": SELECTION_VERSION, **decision, "plan": plan, "plan_hash": plan["plan_hash"],
              "decision_hash": _hash({"plan_hash": plan["plan_hash"], "decision": decision, "candidates": scientific_rows}),
              "candidates": rows, "transfer": transfer, "created_at": datetime.now(timezone.utc).isoformat(),
              "selection_scope": "best_eligible_within_frozen_bounded_candidate_list",
              "scientific_qualification": "coverage_screened_not_field_validated",
              "evidence_role": "selection_record", "field_action_authority": "not_authorized",
              "limitations": ["Coverage screening does not prove cloud-free or representative crop observations.",
                              "The bounded latest candidate page is not an exhaustive period search; missingness can bias selection.",
                              "Only one provider/processing recipe is compared; no temporal or sensor harmonization is inferred.",
                              "COG quotas exclude separately bounded STAC/token JSON and HTTP headers; no whole-job deadline is claimed."]}
    result["receipt_hash"] = _hash(result)
    return result
