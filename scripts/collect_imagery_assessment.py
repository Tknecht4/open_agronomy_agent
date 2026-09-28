#!/usr/bin/env python3
"""Plan or execute bounded anonymous HLS acquisition for the frozen Akron cohort.

Default execution is offline: it records the exact planned public STAC query and
the unavailable denominator. ``--online`` sends the public sampled-support
geometry to Planetary Computer and reads its public HLS COGs; use it only after
the location-egress approval recorded in the acquisition summary is granted.
No labels, benchmark questions, credentials, or paid services are read.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

PROTOCOL = ROOT / "docs/reviews/artifacts/field-imagery-20260927/label-protocol.json"
SUMMARY = ROOT / "docs/reviews/artifacts/field-imagery-20260927/acquisition-summary.json"
OUTPUT = ROOT / "outputs/imagery-assessment-acquisition"
CACHE = Path(tempfile.gettempdir()) / "open-agronomy-hls-assessment-cache-native-final"
LEGACY_CACHE = Path(tempfile.gettempdir()) / "open-agronomy-hls-assessment-cache"
STAC = "https://planetarycomputer.microsoft.com/api/stac/v1/search"
PROVIDERS = {"hls2-s30": "hls-s30-planetary-computer",
             "hls2-l30": "hls-l30-planetary-computer"}
MAX_CANDIDATES = 12
MAX_PAYLOAD_BYTES = 256 * 1024 * 1024
MIN_FREE_BYTES = 1024 * 1024 * 1024
SCENE_DEADLINE_SECONDS = 120
SCRIPT_VERSION = "akron-hls-acquisition-v2-native-verified"
PRIMARY_PROCESS_VERSION = "hls-chip-v2-native-asset-grid-fmask-v1"


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def file_hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(json.dumps(value, sort_keys=True, indent=2, allow_nan=False).encode() + b"\n")
    temporary.replace(path)


def research_geometry(protocol: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Return station query context and each bundle's fixed sampled support.

    Input point datum is unresolved by the publisher. EPSG:32613 is a declared
    working assumption, not a surveyed boundary or a datum determination.
    """
    from pyproj import Transformer
    from shapely.geometry import MultiPoint, mapping
    from shapely.ops import transform

    to_wgs = Transformer.from_crs("EPSG:32613", "EPSG:4326", always_xy=True)
    by_unit: dict[str, list[list[float]]] = {}
    for bundle in protocol["bundles"]:
        if bundle["physical_unit"] in protocol["excluded_physical_units_all_years"]:
            raise ValueError("exposed unit entered acquisition protocol")
        by_unit.setdefault(bundle["physical_unit"], []).extend(bundle["sampling_utm13n"])
    if set(by_unit) != set(protocol["physical_units"]) or len(protocol["bundles"]) != 29:
        raise ValueError("frozen cohort identity mismatch")
    bundle_utm = {b["bundle_id"]: MultiPoint(b["sampling_utm13n"]).convex_hull.buffer(15)
                  for b in protocol["bundles"]}
    # The shared scene/grid request uses the sampling hull of all eligible
    # points. Unit support remains the separate unit hull plus 15 m.
    station_utm = MultiPoint([point for points in by_unit.values() for point in points]).convex_hull.buffer(15)
    station = mapping(transform(to_wgs.transform, station_utm))
    bundles = {bundle_id: mapping(transform(to_wgs.transform, geom))
               for bundle_id, geom in bundle_utm.items()}
    geometry_receipt = {
        "status": "assumed_not_surveyed", "input_crs": "UTM zone 13N datum unresolved",
        "working_crs": "EPSG:32613", "station_role": "shared_research_context_query",
        "station_rule": "convex hull of all eligible sampling coordinates buffered 15 m",
        "bundle_role": "sampled_support_research_aoi",
        "bundle_rule": "convex hull of the bundle's sampled coordinates buffered 15 m",
        "station_geometry_hash": digest(station),
        "bundle_geometry_hashes": {bundle_id: digest(geom) for bundle_id, geom in bundles.items()},
        "unit_context_dependency": "shared 224x224 native grid; adjacent contexts and tokens are dependent",
    }
    return station, bundles, geometry_receipt


def query_bodies(station: dict[str, Any], years: list[int]) -> dict[str, list[dict[str, Any]]]:
    return {str(year): [
        {"collections": [collection], "intersects": station,
         "datetime": f"{year}-05-01T00:00:00Z/{year}-06-15T23:59:59Z",
         "limit": MAX_CANDIDATES,
         "sortby": [{"field": "properties.datetime", "direction": "desc"}]}
        for collection in PROVIDERS] for year in years}


def plan(protocol: dict[str, Any], selected: list[dict[str, Any]]) -> dict[str, Any]:
    station, bundles, geometry = research_geometry(protocol)
    years = sorted({int(b["year"]) for b in selected})
    return {
        "schema_version": "imagery_assessment_acquisition.v1",
        "script_version": SCRIPT_VERSION,
        "primary_process_version": PRIMARY_PROCESS_VERSION,
        "label_protocol_id": protocol["protocol_id"],
        "label_protocol_sha256": file_hash(PROTOCOL),
        "source": {"name": "USDA Akron public research observations",
                   "doi": protocol["source_url"], "source_sha256": protocol["source_sha256"],
                   "license": protocol["source_license"],
                   "coordinate_status": "public source sampling points; datum unresolved"},
        "imagery_source": {"catalog": STAC, "collections": list(PROVIDERS),
                           "assets": "NASA HLS S30/L30 six 30 m reflectance bands and Fmask",
                           "terms": "HLS source CC BY 4.0; Planetary Computer STAC license metadata requires separate review for redistribution"},
        "external_location_egress": {
            "status": "approved_by_user_for_public_akron_to_planetary_computer",
            "history": [
                {"status": "auto_review_rejected", "reason": "precise sampled-location geometry to external Planetary Computer endpoint"},
                {"status": "user_approved", "scope": "public USDA Akron sampled-support polygons and 2019-2022 date ranges to planetarycomputer.microsoft.com for HLS retrieval and model assessment"},
            ],
            "destination": STAC,
            "payload_description": "public Akron-derived station sampling hull plus 15 m as exact GeoJSON intersects; no private user-uploaded geometry",
            "exact_post_json_by_year_and_collection": query_bodies(station, years),
            "subsequent_requests_if_approved": "same intersects and source item IDs to the catalog, anonymous public SAS token, bounded HLS COG byte ranges",
            "credential_policy": "anonymous public SAS retained in memory only; never persisted",
        },
        "geometry": geometry,
        "bounds": {"scene_candidates_per_year_max": MAX_CANDIDATES,
                   "active_acquisition_workers_max": 1,
                   "scene_deadline_seconds": SCENE_DEADLINE_SECONDS,
                   "new_imagery_payload_bytes_max": MAX_PAYLOAD_BYTES,
                   "free_disk_reserve_bytes_min": MIN_FREE_BYTES,
                   "dates_per_bundle": 4, "bands_per_date": 6,
                   "native_context_shape": [224, 224]},
        "selection": "latest four distinct QA-positive acquisition dates in May 1-June 15 window; ties by source item ID; sorted chronological for model; independent of labels",
        "support": {"bundle_wgs84": bundles, "station_wgs84": station},
        "selected_bundle_ids": [b["bundle_id"] for b in selected],
        "bundles": {b["bundle_id"]: {"status": "not_acquired", "candidate_count": 0,
                                     "attempted_count": 0, "selected_dates": [],
                                     "missing_date_count": 4}
                    for b in selected},
        "years": {},
    }


def public_candidates(query: list[dict[str, Any]], year: int) -> list[dict[str, Any]]:
    from agronomy_agent.field_imagery import _request_json, _PLANETARY_COMPUTER

    found: list[dict[str, Any]] = []
    for body in query:
        response = _request_json(_PLANETARY_COMPUTER, body=body)
        features = response.get("features")
        if not isinstance(features, list) or len(features) > MAX_CANDIDATES:
            raise RuntimeError("invalid_or_oversized_catalog_response")
        collection = body["collections"][0]
        for item in features:
            if not isinstance(item, dict) or item.get("collection") != collection:
                continue
            item_id = item.get("id")
            props = item.get("properties")
            if not isinstance(item_id, str) or not isinstance(props, dict):
                continue
            acquired = props.get("datetime")
            if not isinstance(acquired, str) or len(acquired) > 40:
                continue
            try:
                acquired_date = date.fromisoformat(acquired[:10])
            except ValueError:
                continue
            if not date(year, 5, 1) <= acquired_date <= date(year, 6, 15):
                continue
            band_keys = (("B02", "B03", "B04", "B8A", "B11", "B12", "Fmask")
                         if collection == "hls2-s30" else
                         ("B02", "B03", "B04", "B05", "B06", "B07", "Fmask"))
            assets = item.get("assets")
            if not isinstance(assets, dict) or any(k not in assets for k in band_keys):
                continue
            found.append({"scene_id": f"{collection}:{item_id}", "collection": collection,
                          "provider": PROVIDERS[collection], "acquired_at": acquired,
                          "date": acquired_date.isoformat(),
                          "scene_cloud_percent": props.get("eo:cloud_cover"),
                          "asset_ids": [f"{collection}:{item_id}:{k}" for k in band_keys]})
    unique = {x["scene_id"]: x for x in found}
    return sorted(unique.values(), key=lambda x: (x["acquired_at"], x["scene_id"]), reverse=True)[:MAX_CANDIDATES]


def worker_scene(args: argparse.Namespace) -> int:
    from agronomy_agent import imagery_analytics

    imagery_analytics.MAX_COG_TRANSFER_BYTES = min(16 * 1024 * 1024, args.transfer_limit)
    geom = json.loads(Path(args.geometry_file).read_text())
    receipt = imagery_analytics.analyze_scene(geom, args.provider, args.scene_id,
                                              cache_root=args.cache_root, network_mode="online",
                                              context_pixels=224)
    write_json(Path(args.worker_receipt), receipt)
    return 0 if receipt["status"] in ("available", "empty_valid_area") else 2


def run_scene(candidate: dict[str, Any], geometry_file: Path, cache: Path,
              output: Path, transfer_limit: int) -> dict[str, Any]:
    receipt_path = output / "workers" / (digest(candidate["scene_id"]) + ".json")
    if receipt_path.exists():
        receipt = json.loads(receipt_path.read_text())
        if receipt.get("status") not in ("available", "empty_valid_area") and receipt.get("process_version") == PRIMARY_PROCESS_VERSION:
            return receipt
        if (receipt.get("process_version") == PRIMARY_PROCESS_VERSION and
                receipt.get("source_native_grid") is True and
                isinstance(receipt.get("grid", {}).get("native_asset_grid"), dict) and
                (cache / receipt["cache_files"]["npz"]).exists()):
            return receipt
        superseded = output / "superseded-transitional" / "workers" / receipt_path.name
        if not superseded.exists():
            write_json(superseded, receipt)
    command = [sys.executable, __file__, "--worker-scene", "--provider", candidate["provider"],
               "--scene-id", candidate["scene_id"], "--geometry-file", str(geometry_file),
               "--cache-root", str(cache), "--worker-receipt", str(receipt_path),
               "--transfer-limit", str(transfer_limit)]
    started = time.monotonic()
    try:
        child = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               timeout=SCENE_DEADLINE_SECONDS, check=False)
        receipt = json.loads(receipt_path.read_text()) if receipt_path.exists() else {
            "status": "unavailable", "error_type": "worker_no_receipt"}
        receipt["worker_exit_code"] = child.returncode
    except subprocess.TimeoutExpired:
        receipt = {"status": "timeout", "error_type": "scene_deadline_120_seconds"}
    receipt.update(scene_id=candidate["scene_id"], acquired_at=candidate["acquired_at"],
                   worker_elapsed_seconds=time.monotonic() - started)
    write_json(receipt_path, receipt)
    return receipt


def used_bytes(root: Path) -> int:
    return sum(p.stat().st_size for p in root.rglob("*") if p.is_file()) if root.exists() else 0


def budget_remaining(output: Path, cache: Path, legacy_cache: Path, downloaded_bytes: int) -> int:
    used = used_bytes(output) + used_bytes(cache) + used_bytes(legacy_cache) + downloaded_bytes
    remaining = MAX_PAYLOAD_BYTES - used
    if remaining <= 0 or shutil.disk_usage(output).free - MIN_FREE_BYTES < 16 * 1024 * 1024:
        return 0
    return remaining


def unit_masks(chip: Path, units: dict[str, dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    import numpy as np
    from rasterio.transform import Affine
    from pyproj import Transformer
    from shapely.geometry import shape
    from shapely.ops import transform
    from agronomy_agent.imagery_analytics import _dependencies, _field_weights

    with np.load(chip, allow_pickle=False) as data:
        meta = json.loads(str(data["metadata_json"].item()))
        valid = data["valid_mask"].copy()
    if (valid.shape != (224, 224) or meta["resolution_m"] != 30 or
            meta.get("process_version") != PRIMARY_PROCESS_VERSION or
            meta.get("source_native_grid") is not True or
            meta.get("resampling_method") != "nearest" or
            not isinstance(meta.get("native_asset_grid"), dict)):
        raise ValueError("station_chip_is_not_native_224")
    native = meta["native_asset_grid"]
    if native.get("crs") != meta.get("crs") or native.get("resolution_m") != 30:
        raise ValueError("station_chip_source_grid_mismatch")
    for index in (2, 5):
        offset = (meta["transform"][index] - native["transform"][index]) / 30
        if abs(offset - round(offset)) > 1e-6:
            raise ValueError("station_chip_not_on_source_lattice")
    affine = Affine(*meta["transform"])
    projector = Transformer.from_crs("EPSG:4326", meta["crs"], always_xy=True)
    deps = _dependencies()
    weights = {unit: _field_weights(transform(projector.transform, shape(geom)),
                                    affine, 224, 224, deps) for unit, geom in units.items()}
    return weights, meta


def make_unit_chip(station_chip: Path, weights: Any, unit: str, bundle_id: str, support_hash: str,
                   output: Path) -> tuple[Path, dict[str, Any]]:
    import numpy as np

    with np.load(station_chip, allow_pickle=False) as data:
        bands, valid = data["bands"].copy(), data["valid_mask"].copy()
        metadata = json.loads(str(data["metadata_json"].item()))
    field = weights > 0
    if not field.any() or not (field & valid).any():
        raise ValueError("unit_has_no_valid_sampled_support")
    context_sha = file_hash(station_chip)
    metadata["research_support"] = {
        "physical_unit": unit, "bundle_id": bundle_id, "role": "sampled_support_research_aoi",
        "rule": "bundle sampling hull buffered 15 m; EPSG:32613 assumed",
        "support_geometry_hash": support_hash, "context_chip_sha256": context_sha,
        "field_mask_sha256": hashlib.sha256(field.tobytes()).hexdigest()}
    key = digest({"script_version": SCRIPT_VERSION, "source_chip_sha256": context_sha,
                  "support_geometry_hash": support_hash, "unit": unit, "bundle_id": bundle_id,
                  "field_mask_sha256": metadata["research_support"]["field_mask_sha256"]})
    destination = output / "chips" / f"{key}.npz"
    if not destination.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        temp = destination.with_name(f".{key}.{os.getpid()}.npz")
        with temp.open("wb") as stream:
            np.savez_compressed(stream, bands=bands, valid_mask=valid, field_mask=field,
                                field_weights=weights, metadata_json=canonical(metadata).decode())
        temp.replace(destination)
    qa = {"field_pixel_count": int(field.sum()),
          "valid_pixel_count": int((field & valid).sum()),
          "valid_support_fraction": float((field & valid).sum() / field.sum()),
          "weighted_support_m2": float(weights.sum() * 900),
          "weighted_valid_support_m2": float(weights[valid].sum() * 900),
          "field_mask_sha256": metadata["research_support"]["field_mask_sha256"],
          "chip_sha256": file_hash(destination), "chip_bytes": destination.stat().st_size,
          "source_context_sha256": context_sha}
    return destination, qa


def acquire(args: argparse.Namespace, protocol: dict[str, Any], selected: list[dict[str, Any]],
            summary: dict[str, Any]) -> None:
    import numpy as np

    output, cache = args.output, args.cache_root
    output.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    geom_file = output / "station-query-geometry.geojson"
    write_json(geom_file, summary["support"]["station_wgs84"])
    selected_by_year: dict[int, list[dict[str, Any]]] = {}
    for b in selected:
        selected_by_year.setdefault(b["year"], []).append(b)
    downloaded_bytes = sum(a.get("cog_transfer_bytes") or 0
                           for y in summary["years"].values()
                           for group in ("attempts", "superseded_attempts") for a in y.get(group, []))
    for year, bundles in sorted(selected_by_year.items()):
        state = summary["years"].setdefault(str(year), {"status": "not_started", "candidates": [], "attempts": []})
        if not state["candidates"]:
            try:
                state["candidates"] = public_candidates(
                    summary["external_location_egress"]["exact_post_json_by_year_and_collection"][str(year)], year)
                state["status"] = "catalog_available"
            except Exception as exc:
                state.update(status="catalog_unavailable", error_type=type(exc).__name__)
                checkpoint(summary, output)
                continue
            checkpoint(summary, output)
        chosen: dict[str, dict[str, dict[str, Any]]] = {b["bundle_id"]: {} for b in bundles}
        context_chosen: dict[str, dict[str, Any]] = {}
        for candidate in state["candidates"]:
            if len(context_chosen) == 4 and all(len(dates) == 4 for dates in chosen.values()):
                break
            if (candidate["date"] in context_chosen and
                    all(candidate["date"] in dates or len(dates) == 4 for dates in chosen.values())):
                continue
            remaining = budget_remaining(output, cache, args.legacy_cache_root, downloaded_bytes)
            if remaining < 16 * 1024 * 1024:
                state["status"] = "stopped_payload_or_disk_budget"
                checkpoint(summary, output)
                break
            receipt = run_scene(candidate, geom_file, cache, output, min(remaining, 16 * 1024 * 1024))
            if not any(a["scene_id"] == candidate["scene_id"] for a in state["attempts"]):
                state["attempts"].append({**candidate, "status": receipt["status"],
                                          "worker_exit_code": receipt.get("worker_exit_code"),
                                          "worker_elapsed_seconds": receipt.get("worker_elapsed_seconds"),
                                          "error_type": receipt.get("error_type"),
                                          "cog_transfer_bytes": receipt.get("cog_transfer_bytes"),
                                          "cog_range_requests": receipt.get("cog_range_requests"),
                                          "source": receipt.get("source"),
                                          "source_geometry_hash": receipt.get("geometry_hash"),
                                          "process_hash": receipt.get("process_hash"),
                                          "preview_version": receipt.get("preview_version", "pre_finite_alpha_preview_version"),
                                          "context_chip_hash": receipt.get("chip_hash")})
                downloaded_bytes += receipt.get("cog_transfer_bytes") or 0
            if (receipt["status"] not in ("available", "empty_valid_area") or
                    receipt.get("process_version") != PRIMARY_PROCESS_VERSION or
                    receipt.get("source_native_grid") is not True or
                    not isinstance(receipt.get("grid", {}).get("native_asset_grid"), dict)):
                checkpoint(summary, output)
                continue
            station_chip = cache / receipt["cache_files"]["npz"]
            if not station_chip.exists():
                state["attempts"][-1]["status"] = "missing_cached_chip"
                checkpoint(summary, output)
                continue
            try:
                weights, meta = unit_masks(station_chip, {b["bundle_id"]: summary["support"]["bundle_wgs84"][b["bundle_id"]]
                                                    for b in bundles})
                with np.load(station_chip, allow_pickle=False) as data:
                    valid = data["valid_mask"].copy()
                if meta["source"]["acquired_at"][:10] != candidate["date"]:
                    raise ValueError("catalog_and_chip_acquisition_date_mismatch")
                if (len(context_chosen) < 4 and candidate["date"] not in context_chosen and
                        (receipt.get("qa", {}).get("valid_area_m2") or 0) > 0):
                    context_chosen[candidate["date"]] = {
                        "candidate": candidate, "station_chip": str(station_chip),
                        "station_chip_sha256": file_hash(station_chip),
                        "qa": receipt["qa"]}
                for b in bundles:
                    bundle_id, unit = b["bundle_id"], b["physical_unit"]
                    if len(chosen[bundle_id]) == 4 or candidate["date"] in chosen[bundle_id]:
                        continue
                    mask = weights[bundle_id] > 0
                    if mask.any() and (mask & valid).any():
                        chosen[bundle_id][candidate["date"]] = {
                            "candidate": candidate, "station_chip": str(station_chip),
                            "station_chip_sha256": file_hash(station_chip),
                            "valid_support_fraction": float((mask & valid).sum() / mask.sum())}
            except Exception as exc:
                state["attempts"][-1]["unit_qa_error_type"] = type(exc).__name__
            checkpoint(summary, output)
        context_dates = sorted(context_chosen)
        if len(context_dates) == 4:
            context_chips = []
            for d in context_dates:
                info = context_chosen[d]
                source = Path(info["station_chip"])
                expected_sha = info["station_chip_sha256"]
                target = output / "contexts" / "chips" / f"{expected_sha}.npz"
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.exists():
                    shutil.copyfile(source, target)
                if file_hash(target) != expected_sha:
                    raise RuntimeError("station_context_copy_hash_mismatch")
                context_chips.append({"path": str(Path("chips") / target.name), "date": d,
                                      "scene_id": info["candidate"]["scene_id"],
                                      "sha256": expected_sha, "qa": info["qa"]})
            context_manifest = {"year": year, "cutoff": f"{year}-06-15", "chips": context_chips,
                                "label_protocol_id": protocol["protocol_id"],
                                "primary_process_version": PRIMARY_PROCESS_VERSION,
                                "support_role": "station_sampling_hull_buffer_15m_for_shared_context_only",
                                "unit_support_rule": "each bundle sampling hull buffer 15m; model derives ROI separately"}
            context_path = output / "contexts" / f"{year}.json"
            write_json(context_path, context_manifest)
            context_status = "ok"
            loader_error = None
            try:
                from agronomy_agent.imagery_models import load_chip_manifest
                prepared = load_chip_manifest(context_path)
                if (prepared["receipt"].get("source_native_grid") is not True or
                        set(prepared["receipt"].get("process_versions", [])) != {PRIMARY_PROCESS_VERSION}):
                    raise ValueError("native_v2_model_loader_gate_failed")
            except (ValueError, TypeError, KeyError, RuntimeError) as exc:
                context_status = "provisional_loader_rejection"
                loader_error = f"{type(exc).__name__}:{exc}"
            state["context"] = {"status": context_status, "manifest": str(context_path.relative_to(output)),
                                "manifest_sha256": file_hash(context_path), "dates": context_dates,
                                "loader_error": loader_error}
        else:
            state["context"] = {"status": "insufficient_four_qa_positive_station_dates",
                                "dates": context_dates, "missing_date_count": 4-len(context_dates)}
        write_context_index(output, summary, selected_by_year)
        checkpoint(summary, output)
        for b in bundles:
            bundle_id = b["bundle_id"]
            dates = sorted(chosen[bundle_id])
            entry = summary["bundles"][bundle_id]
            entry.update(candidate_count=len(state["candidates"]), attempted_count=len(state["attempts"]),
                         selected_dates=dates, missing_date_count=4-len(dates),
                         cutoff=b["cutoff"], physical_unit=b["physical_unit"])
            if len(dates) != 4:
                entry["status"] = "insufficient_four_qa_positive_dates"
                continue
            manifest_chips = []
            for d in dates:
                info = chosen[bundle_id][d]
                weights, _ = unit_masks(Path(info["station_chip"]),
                                         {bundle_id: summary["support"]["bundle_wgs84"][bundle_id]})
                chip, qa = make_unit_chip(Path(info["station_chip"]), weights[bundle_id],
                                          b["physical_unit"], bundle_id,
                                          summary["geometry"]["bundle_geometry_hashes"][bundle_id], output)
                manifest_chips.append({"path": str(Path("..") / "chips" / chip.name),
                                       "date": d, "scene_id": info["candidate"]["scene_id"], "qa": qa})
            manifest = {"bundle_id": bundle_id, "cutoff": b["cutoff"], "chips": manifest_chips,
                        "label_protocol_id": protocol["protocol_id"],
                        "primary_process_version": PRIMARY_PROCESS_VERSION,
                        "context": "shared_stational_native_224; unit_sampled_support_mask; overlapping_contexts_dependent"}
            manifest_path = output / "manifests" / f"{bundle_id}.json"
            if manifest_path.exists():
                previous = json.loads(manifest_path.read_text())
                if previous.get("primary_process_version") != PRIMARY_PROCESS_VERSION:
                    archive = output / "superseded-v1" / "manifests" / manifest_path.name
                    if not archive.exists():
                        write_json(archive, previous)
            write_json(manifest_path, manifest)
            entry.update(status="four_dates_native_224_available", manifest=str(manifest_path.relative_to(ROOT)),
                         manifest_sha256=file_hash(manifest_path))
            checkpoint(summary, output)
        if state["status"] not in ("stopped_payload_or_disk_budget", "catalog_unavailable"):
            state["status"] = "bounded_candidates_exhausted_or_complete"
        write_context_index(output, summary, selected_by_year)
        checkpoint(summary, output)


def write_context_index(output: Path, summary: dict[str, Any], selected_by_year: dict[int, list[dict[str, Any]]]) -> None:
    contexts = []
    for year in sorted(selected_by_year):
        context = summary["years"].get(str(year), {}).get("context", {})
        if context.get("status") == "ok":
            contexts.append({"year": year, "status": "ok", "manifest": context["manifest"]})
        else:
            contexts.append({"year": year, "status": "error",
                             "error": context.get("status", "context_not_acquired")})
    write_json(output / "contexts.json", {"contexts": contexts,
                                           "label_protocol_id": summary["label_protocol_id"],
                                           "primary_process_version": PRIMARY_PROCESS_VERSION})


def checkpoint(summary: dict[str, Any], output: Path) -> None:
    summary["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
    summary["counts"] = {
        "bundles_total": len(summary["bundles"]),
        "bundles_four_dates": sum(b["status"] == "four_dates_native_224_available" for b in summary["bundles"].values()),
        "bundles_missing": sum(b["status"] != "four_dates_native_224_available" for b in summary["bundles"].values()),
        "year_contexts_four_dates": sum(y.get("context", {}).get("status") == "ok" for y in summary["years"].values()),
        "scenes_attempted": sum(len(y.get("attempts", [])) for y in summary["years"].values()),
        "superseded_scenes_attempted": sum(len(y.get("superseded_attempts", [])) for y in summary["years"].values()),
        "observed_cog_transfer_bytes": sum(a.get("cog_transfer_bytes") or 0 for y in summary["years"].values()
                                           for group in ("attempts", "superseded_attempts") for a in y.get(group, [])),
        "output_bytes": used_bytes(output),
    }
    write_json(output / "acquisition-summary.json", summary)
    write_json(SUMMARY, summary)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=PROTOCOL)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--cache-root", type=Path, default=CACHE,
                        help="content-addressed scene cache outside repository")
    parser.add_argument("--legacy-cache-root", type=Path, default=LEGACY_CACHE,
                        help="prior cache location to include in cumulative payload budget")
    parser.add_argument("--bundle-id", help="one frozen bundle; default bounded first bundle")
    parser.add_argument("--all-bundles", action="store_true", help="plan or acquire all 29 eligible bundles")
    parser.add_argument("--online", action="store_true", help="send location to public STAC and fetch bounded HLS; requires explicit approval")
    parser.add_argument("--worker-scene", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--scene-id", help=argparse.SUPPRESS)
    parser.add_argument("--provider", help=argparse.SUPPRESS)
    parser.add_argument("--geometry-file", help=argparse.SUPPRESS)
    parser.add_argument("--worker-receipt", help=argparse.SUPPRESS)
    parser.add_argument("--transfer-limit", type=int, default=16 * 1024 * 1024, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker_scene:
        return worker_scene(args)
    if args.protocol.resolve() != PROTOCOL.resolve():
        parser.error("only the frozen repository label protocol is supported")
    if ROOT in args.cache_root.resolve().parents or args.cache_root.resolve() == ROOT:
        parser.error("scene cache must be outside the repository")
    if ROOT in args.legacy_cache_root.resolve().parents or args.legacy_cache_root.resolve() == ROOT:
        parser.error("legacy scene cache must be outside the repository")
    protocol = json.loads(PROTOCOL.read_text())
    bundles = protocol["bundles"]
    if args.bundle_id:
        selected = [b for b in bundles if b["bundle_id"] == args.bundle_id]
        if len(selected) != 1:
            parser.error("unknown frozen bundle")
    elif args.all_bundles:
        selected = bundles
    else:
        selected = [next(b for b in bundles if b["bundle_id"] == "akron-SB1-2021")]
    fresh = plan(protocol, selected)
    if SUMMARY.exists() and args.online:
        old = json.loads(SUMMARY.read_text())
        if old.get("label_protocol_sha256") == fresh["label_protocol_sha256"]:
            fresh["years"] = old.get("years", {})
            if (old.get("primary_process_version") != PRIMARY_PROCESS_VERSION or
                    old.get("script_version") != SCRIPT_VERSION):
                archive = args.output / "superseded-transitional" / "acquisition-summary.json"
                if not archive.exists():
                    write_json(archive, old)
                for state in fresh["years"].values():
                    state["superseded_attempts"] = state.get("superseded_attempts", []) + state.pop("attempts", [])
                    state["attempts"] = []
                    state["status"] = "transitional_chips_superseded_pending_native_reacquisition"
            else:
                for key in fresh["bundles"]:
                    if key in old.get("bundles", {}):
                        fresh["bundles"][key] = old["bundles"][key]
    checkpoint(fresh, args.output)
    if not args.online:
        print(json.dumps({"status": "planned_offline_user_approved_transfer_not_executed",
                          "bundles": len(selected), "summary": str(SUMMARY)}, indent=2))
        return 0
    acquire(args, protocol, selected, fresh)
    done = fresh["counts"]["bundles_four_dates"]
    print(json.dumps({"status": "bounded_acquisition_complete" if done == len(selected) else "incomplete",
                      "bundles_four_dates": done, "bundles_total": len(selected),
                      "summary": str(SUMMARY)}, indent=2))
    return 0 if done == len(selected) else 2


if __name__ == "__main__":
    raise SystemExit(main())
