"""Pinned inputs for the existing controlled, nonclaim AppServer executor.

This wires its lazy phase factories into the canonical runner. It grants no
egress authority: the transport independently validates the human grant, public
artifact membership, source/case/prompt bindings and each outbound message.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

INPUT_NAMES = frozenset({"authorization", "suite", "artifacts", "static_prompts"})
TRIAL_AUTHORIZATION_SCHEMA = "open_agronomy_agent.trial_authorizations.v1"


def suite_inventory_sha256(plan: Mapping[str, Any]) -> str:
    from agronomy_agent.release_evaluation import digest
    return digest({"suite_id": plan["suite_id"], "cases": sorted(
        [{"case_id": row["case_id"], "case_sha256": row["case_sha256"]} for row in plan["cases"]],
        key=lambda row: row["case_id"])})


def validate_external_plan(inputs: Mapping[str, Any], plan: Mapping[str, Any]) -> None:
    suite = inputs["suite"]["value"]
    if (suite.get("source_sha256") != plan["source"]["source_sha256"]
            or suite.get("benchmark_suite_sha256") != suite_inventory_sha256(plan)
            or set(suite.get("cases", {})) != {row["case_id"] for row in plan["cases"]}):
        raise ValueError("external controls do not bind the actual source and full case inventory")


def read_external_inputs(declaration: Any, root: Path) -> dict[str, dict[str, Any]]:
    if not isinstance(declaration, Mapping) or set(declaration) != INPUT_NAMES:
        raise ValueError("external generation requires exactly four pinned control inputs")
    from agronomy_agent.release_evaluation import checked_path
    result = {}
    for name, binding in declaration.items():
        if not isinstance(binding, Mapping) or set(binding) != {"path", "sha256"}:
            raise ValueError("external control inputs require path and SHA256")
        path = checked_path(root, binding["path"])
        raw = path.read_bytes()
        if len(raw) > 32 * 1024 * 1024 or hashlib.sha256(raw).hexdigest() != binding["sha256"]:
            raise ValueError("external control input changed or exceeds its bound")
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError("external control input must be an object")
        result[name] = {"path": path, "bytes": raw, "sha256": binding["sha256"], "value": value}
    authority = result["authorization"]["value"]
    if authority.get("schema_version") == TRIAL_AUTHORIZATION_SCHEMA:
        if set(authority) != {"schema_version", "grants"} or not isinstance(authority["grants"], dict) or not 1 <= len(authority["grants"]) <= 32:
            raise ValueError("invalid trial authorization bundle")
        for config_sha, grant in authority["grants"].items():
            if (not isinstance(config_sha, str) or len(config_sha) != 64
                    or any(c not in "0123456789abcdef" for c in config_sha)
                    or not isinstance(grant, dict) or grant.get("model_config_sha256") != config_sha):
                raise ValueError("trial grant config binding mismatch")
            raw = (json.dumps(grant, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
            result["authorization-" + config_sha] = {"path": None, "bytes": raw,
                "sha256": hashlib.sha256(raw).hexdigest(), "value": grant}
    return result


def phase_factories(bindings: Mapping[str, Any], *, model_config: Path,
                    arm: str, max_tokens: int):
    import yaml
    from agronomy_agent.codex_app_server import CodexAppServerGenerator
    config_bytes = model_config.read_bytes()
    config = yaml.safe_load(config_bytes)
    if arm not in {"raw_model", "production_full"} or config.get("model_revision") is not None:
        raise ValueError("external reference requires supported arms and an explicitly unknown provider revision")
    records = {}
    for name in INPUT_NAMES:
        binding = bindings[name]
        raw = Path(binding["path"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != binding["sha256"]:
            raise ValueError("frozen external input changed before factory construction")
        records[name] = json.loads(raw)
    authority = records["authorization"]
    authorization_path = bindings["authorization"]["path"]
    if authority.get("schema_version") == TRIAL_AUTHORIZATION_SCHEMA:
        config_sha = hashlib.sha256(config_bytes).hexdigest()
        selected = bindings.get("authorization-" + config_sha)
        if not isinstance(selected, Mapping):
            raise ValueError("no frozen authorization for effective trial config")
        raw = Path(selected["path"]).read_bytes()
        grant = authority.get("grants", {}).get(config_sha)
        if hashlib.sha256(raw).hexdigest() != selected["sha256"] or json.loads(raw) != grant:
            raise ValueError("frozen trial authorization changed")
        authority = grant
        authorization_path = selected["path"]
    suite = records["suite"]
    editor = config.get("answer_verification") or {}
    command = config.get("app_server_command")
    if command is not None and (not isinstance(command, list) or not command or len(command) > 256
                               or any(not isinstance(part, str) or not part or len(part) > 4096 for part in command)):
        raise ValueError("external command must be a bounded explicit argument list")

    def make(phase: str):
        is_editor = phase == "verification"
        return CodexAppServerGenerator(
            model_id=editor.get("model_id", config["model_id"]) if is_editor else config["model_id"],
            reasoning_effort=editor.get("reasoning_effort", config.get("reasoning_effort")) if is_editor else config.get("reasoning_effort"),
            max_tokens=editor.get("max_tokens", 220) if is_editor else max_tokens,
            model_config_sha256=hashlib.sha256(config_bytes).hexdigest(), model_config_path=model_config,
            egress_authorization=authorization_path,
            benchmark_id=authority["benchmark_id"], benchmark_suite_sha256=suite["benchmark_suite_sha256"],
            egress_phase=phase, benchmark_arm=arm,
            suite_case_contract=suite, egress_artifact_contract=records["artifacts"],
            static_prompt_contract=records["static_prompts"],
            **({"command": command} if command is not None else {}),
        )
    return lambda: make("candidate_generation"), lambda: make("verification")
