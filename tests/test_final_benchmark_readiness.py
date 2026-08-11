from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/audit_final_benchmark_readiness.py"


def _module():
    spec = importlib.util.spec_from_file_location("audit_final_benchmark_readiness", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_benchmark_commands_preserve_four_arms_and_backend_boundary(tmp_path: Path) -> None:
    module = _module()
    plan = json.loads((ROOT / "configs/final_benchmark_round_rc1.json").read_text(encoding="utf-8"))
    egress = tmp_path / "egress.json"
    egress.write_text("{}", encoding="utf-8")

    local = module.build_benchmark_command(plan, plan["models"][0], egress)
    remote = module.build_benchmark_command(plan, plan["models"][2], egress)

    assert local[local.index("--modes") + 1] == "raw_model,baseline,kernel_field_context,agronomic_rag"
    assert "--codex-app-server" not in local
    assert "--codex-app-server" in remote
    assert "--build-review-packet" in local
    assert "--resume-partial-runs" in local


def test_egress_receipt_rejects_private_payload_authorization(tmp_path: Path) -> None:
    module = _module()
    receipt = tmp_path / "egress.json"
    receipt.write_text(
        json.dumps(
            {
                "schema_version": "open_agronomy_agent.benchmark_egress_authorization.v1",
                "benchmark_id": "benchmark",
                "benchmark_suite_sha256": "suite",
                "authorization_source": "test",
                "authorized_at": "2026-08-11T00:00:00Z",
                "authorized_payload_classes": ["questions", "private_field_history"],
                "excluded_payload_classes": [],
            }
        ),
        encoding="utf-8",
    )

    result = module.verify_egress_authorization(
        receipt,
        benchmark_id="benchmark",
        suite_sha256="suite",
        required_payloads=["questions"],
        forbidden_payloads=["private_field_history"],
    )

    assert result["status"] == "blocked"
    assert "forbidden_payload_class_authorized" in result["failures"]


def test_output_start_state_rejects_existing_benchmark_results(tmp_path: Path) -> None:
    module = _module()

    assert module.verify_output_start_state(tmp_path, "outputs/final")["status"] == "pass"
    output = tmp_path / "outputs/final"
    output.mkdir(parents=True)
    assert module.verify_output_start_state(tmp_path, "outputs/final")["status"] == "pass"
    (output / "responses.sqlite").write_bytes(b"not fresh")

    result = module.verify_output_start_state(tmp_path, "outputs/final")
    assert result["status"] == "blocked"
    assert result["files"] == ["responses.sqlite"]
