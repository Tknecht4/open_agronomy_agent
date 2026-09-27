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
from scripts.build_macos_app import _asset_manifest, _audit_macho_links, _tracked_asset_files


def test_runtime_asset_selection_uses_tracked_files_only(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    tracked = tmp_path / "data/seed/admitted.json"
    tracked.parent.mkdir(parents=True)
    tracked.write_text("{}", encoding="utf-8")
    untracked = tmp_path / "data/seed/private-record.json"
    untracked.write_text("private", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "data/seed/admitted.json"], check=True)

    assert _tracked_asset_files(tmp_path) == [Path("data/seed/admitted.json")]


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

    installed = backend.install_model(runtime, state, cache)
    assert installed["phase"] == "ready"
    receipt = json.loads((state / "receipts/model-install.json").read_text())
    assert receipt["revision"] == "a" * 40
    assert backend.verify_model_receipt(runtime, state, cache) == receipt

    weight.write_bytes(b"altered weights")
    with pytest.raises(ValueError, match="snapshot bytes differ"):
        backend.verify_model_receipt(runtime, state, cache)


def test_model_setup_stops_before_download_with_insufficient_space(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = tmp_path / "models/hub"
    cache.mkdir(parents=True)
    monkeypatch.setattr(backend, "_model_contract", lambda _: ("public/model", "a" * 40, "f" * 64))
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
    assert "accessible only" in json.loads(insecure.stderr)["detail"]
