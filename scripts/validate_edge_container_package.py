#!/usr/bin/env python3
"""Validate the Apple-primary edge image and its Docker translation."""
from __future__ import annotations

import argparse
import importlib.util
import json
import shlex
from pathlib import Path
from typing import Any

import yaml

from agronomy_agent.corpus_governance import audit_runtime_corpora


REQUIRED_RUNTIME_ENV = {
    "AGRONOMY_AGENT_DB_PATH=/state/db/open-agronomy.sqlite3",
    "AGRONOMY_AGENT_STATIC_DIR=/app/frontend/dist",
    "AGRONOMY_AGENT_MODEL_BACKEND=mlx_http",
    "AGRONOMY_AGENT_GEO_CACHE_DIR=/state/cache/geo",
    "AGRONOMY_AGENT_AGNO_INDEX_CACHE_DIR=/state/cache/agno_lexical_index",
    "AGRONOMY_AGENT_TOOL_CACHE_ROOT=/state/cache/public_tools",
}

GEOSPATIAL_LINEAGE_MANIFESTS = (
    "data/derived/geo_layers/bc_agriculture_capability_manifest.json",
    "data/derived/geo_layers/sk_thematic_soil_manifest.json",
    "data/derived/geo_layers/sk_detailed_soil_manifest.json",
    "data/derived/geo_layers/ca_soil_erosion_risk_manifest.json",
    "data/derived/geo_layers/pei_detailed_soil_manifest.json",
    "data/derived/geo_layers/ns_pictou_detailed_soil_manifest.json",
    "data/derived/geo_layers/ab_detailed_soil_manifest.json",
    "data/derived/geo_layers/mb_detailed_soil_manifest.json",
)
REQUIRED_DISCOVERY_CONTROL_FILES: tuple[str, ...] = ()
REQUIRED_PUBLIC_ADAPTER_SMOKE_RECEIPTS: dict[str, dict[str, Any]] = {}
RUNTIME_MANIFEST_BOUND_FIELDS = (
    "schema_version",
    "status",
    "contract_sha256",
    "image_contract",
    "model",
    "rag_config",
    "runtime_knowledge",
    "runtime_knowledge_bytes",
    "runtime_policies",
    "runtime_assets",
    "geo_cache_seed",
    "bundled_geo_layers",
    "benchmark_evidence",
    "control_files",
)


def _build_current_runtime_manifest(root: Path) -> dict[str, Any]:
    builder_path = Path(__file__).with_name("build_edge_runtime_manifest.py")
    spec = importlib.util.spec_from_file_location(
        "_edge_runtime_manifest_builder_for_validation",
        builder_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load runtime-manifest builder: {builder_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.build_manifest(root)


def _runtime_manifest_drift(
    manifest: dict[str, Any],
    current: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    for field in RUNTIME_MANIFEST_BOUND_FIELDS:
        if manifest.get(field) != current.get(field):
            errors.append(f"runtime manifest is stale or inconsistent: {field}")
    return errors


def _copy_instructions(containerfile: str) -> list[tuple[list[str], str]]:
    """Return shell-form COPY sources and destination after line continuation."""
    normalized = containerfile.replace("\\\n", " ")
    instructions: list[tuple[list[str], str]] = []
    for raw_line in normalized.splitlines():
        line = raw_line.strip()
        if not line.startswith("COPY "):
            continue
        try:
            tokens = shlex.split(line)
        except ValueError:
            continue
        operands = [token for token in tokens[1:] if not token.startswith("--")]
        if len(operands) >= 2:
            instructions.append((operands[:-1], operands[-1]))
    return instructions


def _containerfile_copies_path(root: Path, containerfile: str, path: str) -> bool:
    requested = Path(path)
    requested_text = requested.as_posix()
    for sources, raw_destination in _copy_instructions(containerfile):
        destination = raw_destination.removeprefix("./").rstrip("/")
        for raw_source in sources:
            source = raw_source.removeprefix("./").rstrip("/")
            if source == requested_text:
                if destination == requested_text:
                    return True
                if (root / requested).is_file() and destination == requested.parent.as_posix():
                    return True
            if requested_text.startswith(source + "/") and destination == source:
                return True
    return False


def _read_runtime_defaults(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or not key:
            raise ValueError(f"invalid runtime default: {raw}")
        values[key] = value
    return values


def _docker_context_root_allowline(path: str) -> str | None:
    parts = Path(path).parts
    if len(parts) >= 3 and parts[:2] == ("outputs", "evals"):
        return f"!outputs/evals/{parts[2]}/"
    if len(parts) >= 4 and parts[:3] == ("data", "derived", "rag"):
        return f"!data/derived/rag/{parts[3]}/"
    return None


def _docker_context_includes_path(dockerignore: str, path: str) -> bool:
    """Recognize exact and recursively reopened release-data directories."""

    lines = set(dockerignore.splitlines())
    if f"!{path}" in lines:
        return True
    return bool(
        (allowline := _docker_context_root_allowline(path))
        and (
            allowline in lines
            or f"{allowline}**" in lines
        )
    )


def validate(root: Path, runtime_manifest_path: Path | None = None) -> dict[str, Any]:
    errors: list[str] = []
    containerfile = (root / "Containerfile").read_text(encoding="utf-8")
    apple = (root / "container/apple.sh").read_text(encoding="utf-8")
    docker_script = (root / "container/docker.sh").read_text(encoding="utf-8")
    runtime_common = (root / "container/runtime-common.sh").read_text(encoding="utf-8")
    image_builder = (root / "container/build-image.sh").read_text(encoding="utf-8")
    overlay_builder = (root / "container/build-overlay-image.sh").read_text(
        encoding="utf-8"
    )
    model_host = (root / "container/model-host.sh").read_text(encoding="utf-8")
    dockerignore = (root / ".dockerignore").read_text(encoding="utf-8")
    compose_text = (root / "docker-compose.edge.yml").read_text(encoding="utf-8")
    compose = yaml.safe_load(compose_text) or {}
    resolved_runtime_manifest = runtime_manifest_path or (root / "container/runtime_manifest.json")
    if not resolved_runtime_manifest.is_absolute():
        resolved_runtime_manifest = root / resolved_runtime_manifest
    manifest = json.loads(resolved_runtime_manifest.read_text(encoding="utf-8"))
    try:
        current_manifest = _build_current_runtime_manifest(root)
        errors.extend(_runtime_manifest_drift(manifest, current_manifest))
    except (FileNotFoundError, OSError, RuntimeError, ValueError) as exc:
        errors.append(f"cannot recompute current runtime manifest: {exc}")
    corpus_audit = audit_runtime_corpora(
        root=root,
        rag_config_path=root / str(manifest.get("rag_config") or ""),
    )
    if corpus_audit["status"] != "pass":
        errors.append(
            "runtime corpus governance failed: "
            + ", ".join(corpus_audit.get("errors") or [])
        )
    runtime_defaults = _read_runtime_defaults(root / "container/runtime-defaults.env")
    import_release = (root / "container/import-release.sh").read_text(encoding="utf-8")
    app = ((compose.get("services") or {}).get("app") or {})

    if app.get("build"):
        errors.append("Docker Compose must run the image built by the shared canonical builder")
    if any("build-image.sh" not in launcher for launcher in (apple, docker_script)):
        errors.append("Apple and Docker launchers must use the shared image builder")
    if "stage_edge_build_context.py" not in image_builder:
        errors.append("Shared image builder must stage the canonical build context")
    if 'ENGINE=${1:-}' not in image_builder or "apple|docker" not in image_builder:
        errors.append("Shared image builder must support both Apple and Docker engines")
    if '--file "$BUILD_CONTEXT/Containerfile"' not in image_builder:
        errors.append("Shared image builder must build the canonical staged Containerfile")
    if "validate_edge_overlay_base.py" not in overlay_builder:
        errors.append("Overlay builder must validate the approved base runtime contract")
    if "stage_edge_build_context.py" not in overlay_builder or "--overlay" not in overlay_builder:
        errors.append("Overlay builder must stage the canonical governed overlay context")
    if not (root / "Containerfile.overlay").is_file():
        errors.append("Canonical overlay Containerfile is missing")
    else:
        overlay_containerfile = (root / "Containerfile.overlay").read_text(
            encoding="utf-8"
        )
        for contract_fragment in (
            "EXPOSE 8080",
            'VOLUME ["/state"]',
            'ENTRYPOINT ["/app/container/entrypoint.sh"]',
            'CMD ["uvicorn", "agronomy_agent.server.app:create_app"',
        ):
            if contract_fragment not in overlay_containerfile:
                errors.append(
                    "Overlay Containerfile must restate runtime image metadata: "
                    + contract_fragment
                )
    if "Library/Caches/OpenAgronomyAgent" not in image_builder:
        errors.append("Shared image builder must stage inputs on the internal user filesystem")
    if "docker-compose.edge.yml" not in docker_script:
        errors.append("Docker launcher must use docker-compose.edge.yml")
    if "ensure_local_image()" not in docker_script or "docker image tag" not in docker_script:
        errors.append("Docker launcher must normalize Apple-exported nested OCI index tags")
    if "host.container.internal" not in apple:
        errors.append("Apple launcher is missing the host model alias")
    if "host.docker.internal" not in str(app.get("environment") or {}):
        errors.append("Docker translation is missing the host model alias")
    if any("runtime-common.sh" not in launcher for launcher in (apple, docker_script)):
        errors.append("Apple and Docker launchers must source the shared runtime contract")
    profile_contract = "AGRONOMY_AGENT_RUNTIME_PROFILE"
    if profile_contract not in runtime_common:
        errors.append("Shared runtime contract is missing runtime-profile configuration")
    profile_root = "Library/Application Support/OpenAgronomyAgent/profiles/$PROFILE"
    if profile_root not in runtime_common:
        errors.append("Shared runtime contract must isolate named profiles under the same state root")
    state_default = "Library/Application Support/OpenAgronomyAgent/state"
    if state_default not in runtime_common:
        errors.append("Shared runtime contract is missing the internal-volume state default")
    model_state = "Library/Application Support/OpenAgronomyAgent/model-host"
    if model_state not in runtime_common or model_state not in model_host:
        errors.append("Both runtimes must share a profile-independent native model state root")
    if "AGRONOMY_AGENT_MODEL_STATE_DIR" not in runtime_common or "AGRONOMY_AGENT_MODEL_STATE_DIR" not in model_host:
        errors.append("Shared model state must be configurable through AGRONOMY_AGENT_MODEL_STATE_DIR")
    if "model-host.config" not in model_host or "configuration_matches()" not in model_host:
        errors.append("Shared model host must restart when Apple and Docker require different bind contracts")
    if "${AGRONOMY_AGENT_CONTAINER_STATE_MOUNT:-/state}" not in compose_text:
        errors.append("Docker translation must persist the canonical /state mount")
    if '--volume "$STATE_DIR:$CONTAINER_STATE_MOUNT"' not in apple:
        errors.append("Apple launcher must persist the canonical /state mount")
    expected_defaults = {
        "AGRONOMY_AGENT_CONTAINER_CPUS": "4",
        "AGRONOMY_AGENT_CONTAINER_MEMORY": "4g",
        "AGRONOMY_AGENT_CONTAINER_PORT": "8080",
        "AGRONOMY_AGENT_CONTAINER_STATE_MOUNT": "/state",
        "AGRONOMY_AGENT_SPATIAL_PACK_ROOT": "/state/spatial-pack",
        "AGRONOMY_AGENT_NETWORK_MODE": "online",
    }
    if runtime_defaults != expected_defaults:
        errors.append("shared runtime defaults do not match the image contract")
    for variable in expected_defaults:
        if variable not in compose_text:
            errors.append(f"Docker translation does not consume shared runtime value: {variable}")
        if variable not in runtime_common:
            errors.append(f"Apple runtime does not consume shared runtime value: {variable}")
    if '--cpus "$CONTAINER_CPUS"' not in apple or '--memory "$CONTAINER_MEMORY"' not in apple:
        errors.append("Apple launcher does not consume shared CPU and memory values")
    if "verify_edge_release.py" not in import_release or "SHA256SUMS" not in (
        root / "scripts/verify_edge_release.py"
    ).read_text(encoding="utf-8"):
        errors.append("release importer must verify the checksummed release package")
    for launcher in (apple, docker_script):
        if 'COMMAND\" = \"import' not in launcher and 'COMMAND" = "import' not in launcher:
            errors.append("both runtime launchers must expose the shared release importer")
    environment = app.get("environment") or {}
    if "AGRONOMY_AGENT_RUNTIME_ENGINE" not in environment or "AGRONOMY_AGENT_RUNTIME_PROFILE" not in environment:
        errors.append("Docker translation must report the runtime engine and profile")
    if "AGRONOMY_AGENT_RUNTIME_ENGINE=apple-container" not in apple:
        errors.append("Apple runtime must report its engine inside the application container")
    if "mlx-lm" in (root / "requirements-container.txt").read_text(encoding="utf-8").lower():
        errors.append("Linux image must not install MLX")
    if "requirements-container.txt" not in containerfile:
        errors.append("Containerfile must use the container-specific dependencies")
    for path in GEOSPATIAL_LINEAGE_MANIFESTS:
        if not _containerfile_copies_path(root, containerfile, path):
            errors.append(f"Containerfile does not copy geospatial lineage manifest: {path}")
    if "chmod -R a+rX /app" not in containerfile:
        errors.append("Containerfile must make bundled runtime assets readable by the app user")
    for value in REQUIRED_RUNTIME_ENV:
        if value not in containerfile.replace(" \\\n", " "):
            errors.append(f"Containerfile is missing runtime environment contract: {value}")

    for entry in manifest.get("control_files") or []:
        path = str(entry.get("path") or "")
        if path.startswith("docs/") and not _containerfile_copies_path(
            root, containerfile, path
        ):
            errors.append(f"Containerfile does not copy manifested release evidence: {path}")
    control_paths = {
        str(entry.get("path") or "") for entry in manifest.get("control_files") or []
    }
    for path in REQUIRED_DISCOVERY_CONTROL_FILES:
        if path not in control_paths:
            errors.append(
                f"runtime manifest does not hash required source-discovery control: {path}"
            )
        if not _containerfile_copies_path(root, containerfile, path):
            errors.append(
                f"Containerfile does not copy required source-discovery control: {path}"
            )
    smoke_receipt_status: dict[str, dict[str, Any]] = {}
    for path, expected in REQUIRED_PUBLIC_ADAPTER_SMOKE_RECEIPTS.items():
        receipt_errors: list[str] = []
        if path not in control_paths:
            receipt_errors.append("not runtime-manifest bound")
        if not _containerfile_copies_path(root, containerfile, path):
            receipt_errors.append("not copied by Containerfile")
        if f"!{path}" not in dockerignore.splitlines():
            receipt_errors.append("excluded from Docker build context")
        try:
            payload = json.loads((root / path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            receipt_errors.append(f"unreadable: {exc}")
            payload = {}
        for field in ("schema_version", "mode", "case_count"):
            if payload.get(field) != expected[field]:
                receipt_errors.append(
                    f"{field}={payload.get(field)!r}, expected {expected[field]!r}"
                )
        if payload.get("passed") is not True or payload.get("failures") != []:
            receipt_errors.append("receipt does not record a clean pass")
        smoke_receipt_status[path] = {
            "status": "pass" if not receipt_errors else "fail",
            "errors": receipt_errors,
            "schema_version": payload.get("schema_version"),
            "mode": payload.get("mode"),
            "case_count": payload.get("case_count"),
        }
        errors.extend(
            f"public-adapter smoke receipt {path}: {error}"
            for error in receipt_errors
        )

    knowledge = manifest.get("runtime_knowledge") or []
    missing_assets = [entry.get("path") for entry in knowledge if not (root / str(entry.get("path"))).is_file()]
    if missing_assets:
        errors.append("runtime manifest references missing knowledge: " + ", ".join(map(str, missing_assets)))
    if manifest.get("image_contract", {}).get("model_weights_in_image") is not False:
        errors.append("runtime manifest must explicitly exclude model weights")
    if not knowledge:
        errors.append("runtime manifest contains no RAG/KG assets")
    missing_docker_context = [
        str(entry.get("path"))
        for entry in knowledge
        if str(entry.get("path")).startswith("data/derived/rag/")
        and not _docker_context_includes_path(dockerignore, str(entry.get("path") or ""))
    ]
    if missing_docker_context:
        errors.append(
            "Docker context excludes manifested knowledge: " + ", ".join(missing_docker_context)
        )
    benchmark_evidence = manifest.get("benchmark_evidence") or []
    missing_benchmark_context = [
        str(entry.get("path"))
        for entry in benchmark_evidence
        if (allowline := _docker_context_root_allowline(str(entry.get("path") or "")))
        and allowline not in dockerignore.splitlines()
    ]
    if missing_benchmark_context:
        errors.append(
            "Docker context excludes manifested benchmark evidence: "
            + ", ".join(missing_benchmark_context)
        )
    for entry in benchmark_evidence:
        path = str(entry.get("path") or "")
        if path and not _containerfile_copies_path(root, containerfile, path):
            errors.append(f"Containerfile does not copy manifested benchmark evidence: {path}")
    policies = manifest.get("runtime_policies") or []
    runtime_assets = manifest.get("runtime_assets") or []
    required_asset_roots = {"src/agronomy_agent", "frontend/src", "scripts"}
    hashed_asset_roots = {str(entry.get("path")) for entry in runtime_assets}
    if not required_asset_roots <= hashed_asset_roots:
        errors.append("runtime manifest does not hash the backend, frontend, and script trees")
    bundled_geo_layers = manifest.get("bundled_geo_layers") or {}
    if (
        bundled_geo_layers.get("path") != "data/derived/geo_layers"
        or int(bundled_geo_layers.get("file_count") or 0) < len(GEOSPATIAL_LINEAGE_MANIFESTS)
        or bundled_geo_layers.get("content_class") != "lineage_manifests_only"
        or bundled_geo_layers.get("runtime_layer_assets_included") is not False
    ):
        errors.append(
            "runtime manifest must bind geospatial lineage manifests without claiming external layer assets"
        )
    for path in GEOSPATIAL_LINEAGE_MANIFESTS:
        if not (root / path).is_file():
            errors.append(f"geospatial lineage manifest is missing: {path}")
        if f"!{path}" not in dockerignore.splitlines():
            errors.append(f"Docker context excludes geospatial lineage manifest: {path}")

    try:
        manifest_display = str(resolved_runtime_manifest.relative_to(root))
    except ValueError:
        manifest_display = str(resolved_runtime_manifest)

    return {
        "schema_version": "open_agronomy_agent.edge_container_validation.v1",
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "canonical_containerfile": "Containerfile",
        "runtime_manifest": manifest_display,
        "apple_primary_launcher": "container/apple.sh",
        "docker_translation": "docker-compose.edge.yml",
        "contract_sha256": manifest.get("contract_sha256"),
        "runtime_knowledge_file_count": len(knowledge),
        "runtime_knowledge_bytes": manifest.get("runtime_knowledge_bytes"),
        "runtime_corpus_governance_status": corpus_audit["status"],
        "public_adapter_smoke_receipts": smoke_receipt_status,
        "provincial_applied_guidance_boundary": corpus_audit[
            "provincial_applied_guidance_boundary"
        ],
        "runtime_policy_file_count": sum(int(entry.get("file_count") or 0) for entry in policies),
        "runtime_asset_file_count": sum(int(entry.get("file_count") or 0) for entry in runtime_assets),
        "bundled_geo_layer_file_count": int(bundled_geo_layers.get("file_count") or 0),
        "bundled_geo_layer_bytes": int(bundled_geo_layers.get("bytes") or 0),
        "geospatial_content_class": bundled_geo_layers.get("content_class"),
        "geospatial_runtime_layer_assets_included": bundled_geo_layers.get(
            "runtime_layer_assets_included"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument(
        "--runtime-manifest",
        type=Path,
        help="Validate an alternate manifest before promoting it to container/runtime_manifest.json.",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = validate(args.root.resolve(), args.runtime_manifest)
    rendered = json.dumps(report, indent=2) + "\n"
    if args.output:
        output = args.output if args.output.is_absolute() else args.root.resolve() / args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
