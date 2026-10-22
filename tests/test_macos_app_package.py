from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from macos_app import backend
from scripts.build_macos_app import _asset_manifest, _audit_macho_links, _check_lgpl_replacement, _tracked_asset_files
from scripts.smoke_macos_app import _startup_summary


@pytest.mark.parametrize('loaded_from', ['changed-copy', 'original-app', 'missing-quadmath', 'backend-error'])
def test_library_replacement_requires_loading_every_changed_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, loaded_from: str,
) -> None:
    import shutil
    app = tmp_path / 'Original.app'
    frameworks = Path('Contents/Helpers/OpenAgronomyBackend.app/Contents/Frameworks')
    libraries = [frameworks / name for name in ('libgeos.dylib', 'libgdal.dylib', 'libquadmath.dylib')]
    for relative in libraries:
        path = app / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'original signed library')
    stage = tmp_path / 'stage'
    stage.mkdir()
    copy = stage / 'Library Replacement Check.app'
    def run(command, **_kwargs):
        if command[0] == 'cp':
            shutil.copytree(app, copy)
        elif command[0] == 'codesign' and '--identifier' in command:
            Path(command[-1]).write_bytes(b'changed signed library')
        elif 'dependency-check' in command:
            if loaded_from == 'backend-error':
                return SimpleNamespace(returncode=1, stdout='dependency import failed', stderr='exact loader error')
            base = app if loaded_from == 'original-app' else copy
            loaded = [str(base / path) for path in libraries
                      if loaded_from != 'missing-quadmath' or 'libquadmath' not in path.name]
            return SimpleNamespace(returncode=0, stdout=json.dumps({'phase': 'verified', 'loaded_lgpl_libraries': loaded}), stderr='')
        return SimpleNamespace(stdout='')
    monkeypatch.setattr('scripts.build_macos_app.subprocess.run', run)
    if loaded_from == 'changed-copy':
        assert _check_lgpl_replacement(app, stage)['status'] == 'verified'
        assert not copy.exists()
    elif loaded_from == 'backend-error':
        with pytest.raises(ValueError, match='exact loader error'):
            _check_lgpl_replacement(app, stage)
        assert json.loads((stage / 'library-replacement-check.json').read_text())['returncode'] == 1
    else:
        with pytest.raises(ValueError, match='did not load every changed library from its app copy'):
            _check_lgpl_replacement(app, stage)


def test_runtime_asset_selection_uses_tracked_files_only(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    tracked = tmp_path / "data/seed/admitted.json"
    tracked.parent.mkdir(parents=True)
    tracked.write_text("{}", encoding="utf-8")
    untracked = tmp_path / "data/seed/private-record.json"
    untracked.write_text("private", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "data/seed/admitted.json"], check=True)

    assert _tracked_asset_files(tmp_path) == [Path("data/seed/admitted.json")]



def test_runtime_assets_copy_only_the_nested_container_requirements(tmp_path: Path) -> None:
    from scripts.build_macos_app import _copy_asset

    source = tmp_path / "source"
    source.mkdir()
    subprocess.run(["git", "init", "-q", str(source)], check=True)
    payload = b"fastapi==0.1\n"
    files = {
        "requirements.txt": b"base dependencies\n",
        "requirements/requirements-container.txt": payload,
        "requirements/requirements-macos-app-build.txt": b"build-only dependency\n",
    }
    for relative, data in files.items():
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    subprocess.run(["git", "-C", str(source), "add", "."], check=True)
    selected = _tracked_asset_files(source)
    assert selected == [Path("requirements.txt"), Path("requirements/requirements-container.txt")]
    runtime = tmp_path / "runtime"
    for relative in selected:
        _copy_asset(source / relative, runtime / relative)
    manifest = _asset_manifest(runtime)
    assert {row["path"] for row in manifest["files"]} == {str(path) for path in selected}
    assert (runtime / "requirements/requirements-container.txt").read_bytes() == payload
    assert not (runtime / "requirements-container.txt").exists()
    assert not (runtime / "requirements/requirements-macos-app-build.txt").exists()

def test_runtime_manifest_hashes_bytes_and_rejects_symlinks(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    asset = runtime / "configs/model.yaml"
    asset.parent.mkdir(parents=True)
    asset.write_text("model_id: pinned\n", encoding="utf-8")
    manifest = _asset_manifest(runtime)
    assert manifest["files"] == [
        {
            "path": "configs/model.yaml",
            "bytes": asset.stat().st_size,
            "sha256": hashlib.sha256(asset.read_bytes()).hexdigest(),
        }
    ]
    (tmp_path / "runtime-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert backend.verify_runtime_manifest(runtime) == manifest
    asset.write_text("model_id: altered\n", encoding="utf-8")
    with pytest.raises(ValueError, match="files differ"):
        backend.verify_runtime_manifest(runtime)
    asset.write_text("model_id: pinned\n", encoding="utf-8")
    (runtime / "outside").symlink_to(asset)
    with pytest.raises(ValueError, match="symlink"):
        _asset_manifest(runtime)
    with pytest.raises(ValueError, match="symlink"):
        backend.verify_runtime_manifest(runtime)


def test_model_receipt_matches_pinned_bytes_and_detects_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = tmp_path / "models/hub"
    cache.mkdir(parents=True)
    state = tmp_path / "state"
    state.mkdir()
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    snapshot = cache / "snapshots" / ("a" * 40)
    snapshot.mkdir(parents=True)
    weight = snapshot / "model.safetensors"
    weight.write_bytes(b"original weights")
    monkeypatch.setattr(backend, "_model_contract", lambda _: ("public/model", "a" * 40, "f" * 64))
    monkeypatch.setattr(backend, "_snapshot", lambda *_: snapshot)
    expected_files = backend._snapshot_files(snapshot, cache)
    monkeypatch.setattr(backend, "_expected_model_files", lambda *_: expected_files)

    installed = backend.install_model(runtime, state, cache)
    assert installed["phase"] == "ready"
    receipt = json.loads((state / "receipts/model-install.json").read_text())
    assert receipt["revision"] == "a" * 40
    assert backend.verify_model_receipt(runtime, state, cache) == receipt

    weight.write_bytes(b"altered weights")
    with pytest.raises(ValueError, match="pinned asset manifest"):
        backend.verify_model_receipt(runtime, state, cache)
    monkeypatch.setattr(backend.shutil, "disk_usage", lambda _: SimpleNamespace(free=1024))
    with pytest.raises(ValueError, match="at least 6 GiB free"):
        backend.install_model(runtime, state, cache)
    assert json.loads((state / "receipts/model-install.json").read_text()) == receipt
    attempts = (state / "receipts/model-install-attempts.jsonl").read_text().splitlines()
    assert json.loads(attempts[-1])["reason"] == "cached snapshot did not match pinned asset identities"


def test_expected_model_manifest_is_bound_to_reviewed_bytes() -> None:
    root = Path(__file__).resolve().parents[1]
    model_id, revision, _ = backend._model_contract(root)
    files = backend._expected_model_files(root, model_id, revision)
    assert len(files) == 10
    assert next(row for row in files if row["path"] == "model.safetensors")["sha256"] == (
        "038e39a37a7667373d2c3991375446b10c96ae1d717a68674870343db376b76e"
    )


def test_model_setup_stops_before_download_with_insufficient_space(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = tmp_path / "models/hub"
    cache.mkdir(parents=True)
    monkeypatch.setattr(backend, "_model_contract", lambda _: ("public/model", "a" * 40, "f" * 64))
    monkeypatch.setattr(backend, "_expected_model_files", lambda *_: [{"path": "model.safetensors", "bytes": 7, "sha256": "a" * 64}])
    monkeypatch.setattr(backend, "_snapshot", lambda *_: (_ for _ in ()).throw(RuntimeError("missing")))
    monkeypatch.setattr(backend.shutil, "disk_usage", lambda _: SimpleNamespace(free=1024))

    with pytest.raises(ValueError, match="at least 6 GiB free"):
        backend.install_model(tmp_path, tmp_path, cache)


def test_macho_audit_rejects_developer_linked_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binary = tmp_path / "backend"
    binary.write_bytes(b"\xcf\xfa\xed\xfe" + b"fake")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            stdout=f"{binary}:\n\t/opt/example/libprivate.dylib (compatibility version 1.0)\n"
        ),
    )

    with pytest.raises(ValueError, match="non-system absolute path"):
        _audit_macho_links(tmp_path)


def test_startup_diagnostic_exposes_only_allowlisted_failure_identity(tmp_path: Path) -> None:
    error = ModuleNotFoundError("secret private path", name="missing.dynamic_module")
    safe = backend._safe_failure(error)
    assert safe["error_code"] == "missing_module"
    assert safe["missing_module"] == "missing.dynamic_module"
    assert "secret private path" not in json.dumps(safe)
    receipt = tmp_path / "receipts/backend-startup.json"
    receipt.parent.mkdir()
    receipt.write_text(json.dumps({
        **safe,
        "stage": "product_import",
        "origin_module": "agronomy_agent.server.app",
        "private_trace": "never leave runner state",
    }))
    assert _startup_summary(tmp_path) == {
        "phase": "error",
        "error_code": "missing_module",
        "stage": "product_import",
        "exception_type": "ModuleNotFoundError",
        "missing_module": "missing.dynamic_module",
        "origin_module": "agronomy_agent.server.app",
    }


def test_desktop_serve_can_select_explicit_offline_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AGRONOMY_AGENT_DESKTOP_PAIRING_TOKEN", "test-pairing-token-0123456789abcdef")
    monkeypatch.setenv("AGRONOMY_AGENT_DESKTOP_SESSION_SECRET", "test-session-secret-0123456789abcdef")
    monkeypatch.setenv("AGRONOMY_AGENT_NETWORK_MODE", "online")
    monkeypatch.setattr(backend, "verify_model_receipt", lambda *_: None)
    monkeypatch.setitem(sys.modules, "scripts.run_cockpit", SimpleNamespace(main=lambda: 0))
    monkeypatch.setattr(sys, "argv", ["pytest"])

    assert backend.serve(tmp_path, tmp_path, tmp_path, port=18080, network_mode="offline") == 0
    assert os.environ["AGRONOMY_AGENT_NETWORK_MODE"] == "offline"
    assert "--desktop-local" in sys.argv


def test_backend_status_never_downloads_without_receipt(tmp_path: Path) -> None:
    registry = tmp_path / "runtime/configs/runtime_profiles.json"
    registry.parent.mkdir(parents=True)
    registry.write_text("{}", encoding="utf-8")
    index = tmp_path / "runtime/frontend/dist/index.html"
    index.parent.mkdir(parents=True)
    index.write_text("ready", encoding="utf-8")
    source_root = Path(__file__).resolve().parents[1]
    command = [
        sys.executable, str(source_root / "macos_app/backend.py"),
        "status",
        "--runtime-root", str(tmp_path / "runtime"),
        "--state-root", str(tmp_path / "state"),
    ]
    environment = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join((str(source_root), str(source_root / "src"))),
    }
    completed = subprocess.run(
        command,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0
    assert json.loads(completed.stdout)["phase"] == "setup_required"
    assert not (tmp_path / "state/receipts/model-install.json").exists()

    (tmp_path / "state").chmod(0o755)
    insecure = subprocess.run(
        command, env=environment, capture_output=True, text=True, check=False
    )
    assert insecure.returncode == 1
    diagnostic = json.loads(insecure.stderr)
    assert diagnostic["error_code"] == "invalid_runtime_contract"
    assert diagnostic["exception_type"] == "ValueError"
    assert "detail" not in diagnostic


def test_desktop_startup_failure_keeps_traceback_private(tmp_path: Path) -> None:
    registry = tmp_path / "runtime/configs/runtime_profiles.json"
    registry.parent.mkdir(parents=True)
    registry.write_text("{}", encoding="utf-8")
    index = tmp_path / "runtime/frontend/dist/index.html"
    index.parent.mkdir(parents=True)
    index.write_text("ready", encoding="utf-8")
    source_root = Path(__file__).resolve().parents[1]
    state = tmp_path / "state"
    completed = subprocess.run(
        [
            sys.executable, str(source_root / "macos_app/backend.py"), "serve",
            "--runtime-root", str(tmp_path / "runtime"),
            "--state-root", str(state), "--port", "18080",
        ],
        env={
            **os.environ,
            "PYTHONPATH": os.pathsep.join((str(source_root), str(source_root / "src"))),
            "AGRONOMY_AGENT_DESKTOP_PAIRING_TOKEN": "test-pairing-token-0123456789abcdef",
            "AGRONOMY_AGENT_DESKTOP_SESSION_SECRET": "test-session-secret-0123456789abcdef",
        },
        capture_output=True, text=True, check=False,
    )
    assert completed.returncode == 1
    public = json.loads(completed.stderr)
    assert public["error_code"] == "invalid_runtime_contract"
    assert "detail" not in public
    assert _startup_summary(state)["error_code"] == "invalid_runtime_contract"
    assert _startup_summary(state)["stage"] == "model_receipt"
    private_logs = list((state / "logs").glob("backend-startup-error-*.log"))
    assert len(private_logs) == 1
    assert private_logs[0].stat().st_mode & 0o077 == 0
    assert "model has not been installed" in private_logs[0].read_text()
