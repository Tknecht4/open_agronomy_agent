"""Read-only, field-scoped comparison of two existing optical jobs."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Any

from agronomy_agent.field_events import verify_field_event_chain
from agronomy_agent.imagery_comparison_presentation import comparison_answer, grower_message
from agronomy_agent.paths import REPO_ROOT
from agronomy_agent.server.schemas import ImageryComparisonSelection
from agronomy_agent.server.services import imagery_service as imagery
from agronomy_agent.server.storage import imagery_job_store as jobs


class ComparisonConflict(ValueError):
    pass


def _aware_instant(value: str) -> datetime:
    instant = datetime.fromisoformat(value)
    if instant.tzinfo is None:
        raise ValueError("A date without a timezone cannot guide scouting")
    return instant


def _scouting_observation(store, field_id: str, dates: tuple[str, str]) -> dict | None:
    """Use an explicit, located grower observation in the selected date interval."""
    events = store.list_phase4_field_events(field_id)
    if not events or not verify_field_event_chain(events)["valid"]:
        return None
    superseded = {event.get("corrects_event_id") for event in events}
    observation_ids = set()
    accepted = []
    first, last = sorted(_aware_instant(value) for value in dates)
    for event in events:
        if event["event_type"] != "observation" and not (
            event["event_type"] == "correction" and event.get("corrects_event_id") in observation_ids
        ):
            continue
        observation_ids.add(event["id"])
        provenance = event.get("provenance") or {}
        payload = event.get("payload") or {}
        location = payload.get("scouting_location")
        if (
            event["id"] in superseded or provenance.get("capture_method") != "grower_entry"
            or provenance.get("observation_time_status") != "user_supplied"
            or event.get("occurred_at") == event.get("recorded_at")
            or payload.get("imagery_analysis") or not isinstance(location, str)
            or not 0 < len(location.strip()) <= 120 or not location.strip().isprintable()
        ):
            continue
        offset = provenance.get("observation_utc_offset_minutes")
        if offset is not None and (type(offset) is not int or abs(offset) > 14 * 60):
            continue
        recorded_zone = timezone.utc if offset is None else timezone(timedelta(minutes=offset))
        try:
            instant = _aware_instant(event["occurred_at"])
            observed = instant.astimezone(recorded_zone).date()
            start, end = (acquired.astimezone(recorded_zone).date() for acquired in (first, last))
        except (KeyError, OverflowError, TypeError, ValueError):
            continue
        if start <= observed <= end:
            accepted.append((instant, {
                "event_id": event["id"], "integrity_sha256": event["integrity_sha256"],
                "date": observed.isoformat(), "date_basis": "utc" if offset is None else "recorded_local",
                "location": location.strip(),
            }))
    return max(accepted, key=lambda record: record[0])[1] if accepted else None


def bind_selection(store, field: dict, selection: ImageryComparisonSelection) -> dict:
    """Bind immutable job receipts and a current boundary without running the worker."""
    revision = jobs.current_geometry_revision(store, field["id"])
    if selection.geometry_revision_id != revision:
        raise ComparisonConflict("The saved boundary changed. Reload the field and select current analyses.")
    selected = []
    unavailable = False
    for job_id in sorted((str(selection.first_job_id), str(selection.second_job_id))):
        job = jobs.get_job(store, job_id, field_id=field["id"])
        if job is None or job["workspace_id"] != field["workspace_id"]:
            raise LookupError("Image analysis not found for this field")
        identity = {"id": job_id, "sha256": job.get("result_sha256")}
        if job["geometry_revision_id"] != revision:
            raise ComparisonConflict("Both analyses must use the current saved boundary.")
        result = job.get("result") or {}
        observed = (result.get("source") or {}).get("acquired_at")
        if job["status"] == "completed" and result.get("chip_hash") and observed:
            try:
                _aware_instant(observed)
            except (TypeError, ValueError):
                unavailable = True
            else:
                identity["acquired_at"] = observed
        else:
            unavailable = True
        selected.append(identity)
    dates = tuple(item["acquired_at"] for item in selected if "acquired_at" in item)
    scouting = _scouting_observation(store, field["id"], dates) if len(dates) == 2 else None
    return {"jobs": selected, "geometry_revision_id": revision, "unavailable": unavailable,
            "scouting_observation": scouting}


def _run_comparison(settings, cache: Path, geometry: dict, chips: list[str], *, maps: bool) -> dict:
    env = {"PATH": os.defpath, "PYTHONNOUSERSITE": "1", "PROJ_NETWORK": "OFF", "OMP_NUM_THREADS": "1"}
    standalone = settings.imagery_worker_executable
    if standalone:
        command = [str(standalone), "--compare"]
    else:
        command = [str(settings.imagery_worker_python), "-m", "agronomy_agent.imagery_comparison"]
        env["PYTHONPATH"] = str(REPO_ROOT / "src")
    limit = 8 * 1024 * 1024 if maps else 64 * 1024
    with tempfile.TemporaryDirectory(prefix="agronomy-comparison-") as directory, tempfile.TemporaryFile() as output:
        path = Path(directory) / "geometry.json"
        path.write_text(json.dumps(geometry), encoding="utf-8")
        command.extend(["--geometry", str(path), "--cache-root", str(cache), "--chips", *chips])
        if maps:
            command.append("--maps")
        completed = imagery._run_process(
            command, standalone=bool(standalone), cwd=REPO_ROOT, env=env, stdin=subprocess.DEVNULL,
            stdout=output, stderr=subprocess.DEVNULL, timeout=30, check=False,
        )
        output.seek(0)
        data = output.read(limit + 1)
    if completed.returncode != 0 or len(data) > limit:
        raise ValueError("Comparison worker failed")
    result = json.loads(data)
    if not isinstance(result, dict) or not isinstance(result.get("status"), str):
        raise ValueError("Invalid comparison worker result")
    return result


def _compute(store, settings, field: dict, pair: dict, *, maps: bool) -> dict:
    if pair["unavailable"]:
        return {"status": "unavailable_source"}
    confirmed = []
    for reference in pair["jobs"]:
        job = jobs.get_job(store, reference["id"], field_id=field["id"])
        if not job or job["workspace_id"] != field["workspace_id"] or job["result_sha256"] != reference["sha256"]:
            return {"status": "unavailable_source"}
        if job["geometry"]["type"] != "Polygon":
            return {"status": "polygon_required"}
        receipt = imagery.verified_job_result(settings, field, job)
        if receipt is None:
            return {"status": "unavailable_source"}
        confirmed.append((job, receipt))
    if not (settings.imagery_worker_python or settings.imagery_worker_executable):
        return {"status": "not_configured"}
    if not imagery._WORKER_SLOT.acquire(blocking=False):
        return {"status": "busy"}
    try:
        chips = [receipt["chip_hash"] for _, receipt in confirmed]
        result = _run_comparison(settings, imagery.field_cache(settings, field), confirmed[0][0]["geometry"], chips, maps=maps)
        if result.get("before") and sorted([result["before"]["chip_hash"], result["after"]["chip_hash"]]) != sorted(chips):
            raise ValueError("Comparison result identity mismatch")
        return result
    except (OSError, ValueError, TypeError, KeyError, subprocess.TimeoutExpired):
        return {"status": "unavailable_source"}
    finally:
        imagery._WORKER_SLOT.release()


def compare_selection(store, settings, field: dict, pair: dict, *, maps: bool = False) -> dict[str, Any]:
    result = _compute(store, settings, field, pair, maps=maps)
    if jobs.current_geometry_revision(store, field["id"]) != pair["geometry_revision_id"]:
        raise ComparisonConflict("The saved boundary changed during comparison. Reload the field.")
    # Dates may still be known when the bytes or installed worker are unavailable.
    references = sorted((item for item in pair["jobs"] if "acquired_at" in item), key=lambda item: datetime.fromisoformat(item["acquired_at"]))
    if len(references) == 2:
        dates = (references[0]["acquired_at"], references[1]["acquired_at"])
        if _scouting_observation(store, field["id"], dates) != pair["scouting_observation"]:
            raise ComparisonConflict("Field observations changed during comparison. Review the latest records and retry.")
        for name, reference in zip(("before", "after"), references):
            result.setdefault(name, {"acquired_at": datetime.fromisoformat(reference["acquired_at"]).astimezone(timezone.utc).isoformat()})
    result.update(
        selection=pair, evidence_role="processed_observation",
        scouting_support="no_imagery_target", field_action_authority="not_authorized",
        scouting_observation=pair["scouting_observation"],
    )
    result["overview"] = grower_message(result)
    result["message"] = comparison_answer(result)
    return result
