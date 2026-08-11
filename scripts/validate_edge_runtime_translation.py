#!/usr/bin/env python3
"""Render Docker Compose and compare it with the Apple runtime contract."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path
from typing import Any


def _read_defaults(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator:
            raise ValueError(f"invalid runtime default: {raw}")
        values[key] = value
    return values


def _memory_bytes(value: str) -> int:
    units = {"b": 1, "k": 1024, "m": 1024**2, "g": 1024**3}
    normalized = value.strip().lower()
    suffix = normalized[-1]
    if suffix in units:
        return int(normalized[:-1]) * units[suffix]
    return int(normalized)


def validate_rendered(
    root: Path,
    rendered: dict[str, Any],
    *,
    image: str,
    app_port: int,
    model_port: int,
    profile: str,
    state_dir: Path,
) -> dict[str, Any]:
    defaults = _read_defaults(root / "container/runtime-defaults.env")
    expected = {
        "image": image,
        "cpus": float(defaults["AGRONOMY_AGENT_CONTAINER_CPUS"]),
        "memory_bytes": _memory_bytes(defaults["AGRONOMY_AGENT_CONTAINER_MEMORY"]),
        "host_ip": "127.0.0.1",
        "published_port": app_port,
        "container_port": int(defaults["AGRONOMY_AGENT_CONTAINER_PORT"]),
        "state_source": str(state_dir),
        "state_target": defaults["AGRONOMY_AGENT_CONTAINER_STATE_MOUNT"],
        "model_url": f"http://host.docker.internal:{model_port}/v1",
        "runtime_profile": profile,
    }
    app = ((rendered.get("services") or {}).get("app") or {})
    ports = app.get("ports") or []
    volumes = app.get("volumes") or []
    environment = app.get("environment") or {}
    port = ports[0] if len(ports) == 1 else {}
    state_volumes = [item for item in volumes if item.get("target") == "/state"]
    model_identity_volumes = [item for item in volumes if item.get("target") == "/model-host"]
    volume = state_volumes[0] if len(state_volumes) == 1 else {}
    observed = {
        "image": app.get("image"),
        "cpus": float(app.get("cpus") or 0),
        "memory_bytes": int(app.get("mem_limit") or 0),
        "host_ip": port.get("host_ip"),
        "published_port": int(port.get("published") or 0),
        "container_port": int(port.get("target") or 0),
        "state_source": volume.get("source"),
        "state_target": volume.get("target"),
        "model_url": environment.get("AGRONOMY_AGENT_MODEL_BASE_URL"),
        "runtime_profile": environment.get("AGRONOMY_AGENT_RUNTIME_PROFILE"),
    }
    checks = {key: observed[key] == value for key, value in expected.items()}
    checks.update({
        "runtime_engine_is_docker": environment.get("AGRONOMY_AGENT_RUNTIME_ENGINE") == "docker",
        "single_loopback_port": len(ports) == 1 and port.get("host_ip") == "127.0.0.1",
        "single_state_mount": len(state_volumes) == 1,
        "read_only_model_identity_mount": (
            len(model_identity_volumes) == 1
            and model_identity_volumes[0].get("read_only") is True
        ),
        "only_expected_mounts": len(volumes) == 2,
        "no_compose_build": app.get("build") is None,
        "no_new_privileges": "no-new-privileges:true" in (app.get("security_opt") or []),
    })
    failed = sorted(name for name, passed in checks.items() if not passed)
    apple_reference = dict(expected)
    apple_reference["model_url"] = f"http://host.container.internal:{model_port}/v1"
    return {
        "schema_version": "open_agronomy_agent.edge_runtime_translation.v1",
        "status": "pass" if not failed else "fail",
        "failed_checks": failed,
        "contract_source": "container/runtime-defaults.env",
        "apple_container": {
            "role": "reference_runtime",
            "contract": apple_reference,
        },
        "docker": {
            "role": "direct_translation",
            "contract": observed,
        },
        "identity_checks": checks,
    }


def render_compose(
    root: Path,
    *,
    image: str,
    app_port: int,
    model_port: int,
    profile: str,
    state_dir: Path,
) -> dict[str, Any]:
    defaults = _read_defaults(root / "container/runtime-defaults.env")
    environment = os.environ.copy()
    environment.update(defaults)
    environment.update({
        "AGRONOMY_AGENT_IMAGE": image,
        "AGRONOMY_AGENT_APP_PORT": str(app_port),
        "AGRONOMY_AGENT_MODEL_PORT": str(model_port),
        "AGRONOMY_AGENT_RUNTIME_ENGINE": "docker",
        "AGRONOMY_AGENT_RUNTIME_PROFILE": profile,
        "AGRONOMY_AGENT_STATE_DIR": str(state_dir),
    })
    command = [
        "docker", "compose",
        "--project-name", f"open-agronomy-agent-{profile}",
        "--project-directory", str(root),
        "--file", str(root / "docker-compose.edge.yml"),
        "config", "--format", "json",
    ]
    completed = subprocess.run(
        command,
        cwd=root,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--image", default="open-agronomy-agent:edge")
    parser.add_argument("--app-port", type=int, default=18080)
    parser.add_argument("--model-port", type=int, default=18081)
    parser.add_argument("--profile", default="release-translation")
    parser.add_argument("--state-dir", type=Path, default=Path("/tmp/open-agronomy-agent-translation"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    state_dir = args.state_dir.resolve()
    try:
        rendered = render_compose(
            root,
            image=args.image,
            app_port=args.app_port,
            model_port=args.model_port,
            profile=args.profile,
            state_dir=state_dir,
        )
        report = validate_rendered(
            root,
            rendered,
            image=args.image,
            app_port=args.app_port,
            model_port=args.model_port,
            profile=args.profile,
            state_dir=state_dir,
        )
    except (OSError, ValueError, KeyError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        report = {
            "schema_version": "open_agronomy_agent.edge_runtime_translation.v1",
            "status": "fail",
            "failed_checks": [str(exc)],
        }
    rendered_report = json.dumps(report, indent=2) + "\n"
    if args.output:
        output = args.output if args.output.is_absolute() else root / args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered_report, encoding="utf-8")
    print(rendered_report, end="")
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
