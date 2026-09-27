#!/usr/bin/env python3
"""Build an unsigned, isolated Apple Silicon desktop candidate.

This command refuses an existing output and retains its private staging tree on
failure. Code signing here is ad hoc for local testing; distribution needs a
separate Developer ID and notarization gate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import plistlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "open_agronomy_agent.macos_app_runtime.v1"
MIN_BUILD_FREE_BYTES = 8 * 1024**3
ASSET_PATHS = (
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
    "pyproject.toml",
    "requirements.txt",
    "requirements-container.txt",
    "configs",
    "src",
    "scripts",
    "container",
    "docs/public",
    "data/seed",
    "data/manifests",
    "data/eval",
    "data/snapshots",
    "data/derived/rag",
    "data/derived/geo_layers",
)
MACHO_MAGICS = {
    b"\xfe\xed\xfa\xce", b"\xce\xfa\xed\xfe",
    b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe",
    b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca",
    b"\xca\xfe\xba\xbf", b"\xbf\xba\xfe\xca",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _existing_parent(path: Path) -> Path:
    candidate = path
    while not candidate.exists():
        if candidate == candidate.parent:
            raise ValueError(f"no existing parent for {path}")
        candidate = candidate.parent
    return candidate


def preflight(root: Path, output: Path, *, python: Path) -> dict[str, object]:
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        raise ValueError("Mac app builds require an Apple Silicon Mac")
    if not root.is_dir() or not (root / "AGENTS.md").is_file():
        raise ValueError("source root is not an Open Agronomy checkout")
    if output.exists():
        raise FileExistsError(f"refusing to overwrite an existing app: {output}")
    if not output.is_absolute():
        raise ValueError("output must be an absolute path")
    if not output.parent.is_dir():
        raise ValueError("output parent directory must already exist")
    if not python.is_file():
        raise ValueError(f"builder Python is missing: {python}")
    missing = [relative for relative in ASSET_PATHS if not (root / relative).exists()]
    if missing:
        raise ValueError("missing runtime inputs: " + ", ".join(missing))
    if not (root / "frontend/package.json").is_file() or not (root / "frontend/src/main.tsx").is_file():
        raise ValueError("frontend source is missing")
    free = shutil.disk_usage(_existing_parent(output.parent)).free
    return {
        "schema_version": "open_agronomy_agent.macos_app_preflight.v1",
        "source_root": str(root),
        "output": str(output),
        "python": str(python),
        "free_bytes": free,
        "estimated_scratch_floor_bytes": MIN_BUILD_FREE_BYTES,
        "space_ready": free >= MIN_BUILD_FREE_BYTES,
        "asset_roots": list(ASSET_PATHS),
    }


def _tracked_asset_files(root: Path) -> list[Path]:
    completed = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--cached", "-z"],
        check=True,
        capture_output=True,
    )
    tracked = [Path(os.fsdecode(value)) for value in completed.stdout.split(b"\0") if value]
    selected = [
        relative
        for relative in tracked
        if any(
            relative == Path(prefix) or relative.is_relative_to(Path(prefix))
            for prefix in ASSET_PATHS
        )
    ]
    if not selected:
        raise ValueError("Git returned no tracked runtime assets")
    return selected


def _copy_asset(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_symlink():
        raise ValueError(f"runtime asset must not be a symlink: {source}")
    if not source.is_file():
        raise ValueError(f"runtime asset is not a regular file: {source}")
    try:
        subprocess.run(["cp", "-c", str(source), str(destination)], check=True, capture_output=True)
    except subprocess.CalledProcessError:
        shutil.copy2(source, destination)


def _asset_manifest(runtime_root: Path) -> dict[str, object]:
    files = []
    for path in sorted(runtime_root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"staged runtime contains a symlink: {path}")
        if path.is_file():
            files.append(
                {
                    "path": path.relative_to(runtime_root).as_posix(),
                    "bytes": path.stat().st_size,
                    "sha256": _sha256(path),
                }
            )
    digest = hashlib.sha256(
        "\n".join(f"{row['path']} {row['sha256']}" for row in files).encode("utf-8")
    ).hexdigest()
    return {"schema_version": SCHEMA, "contract_sha256": digest, "files": files}


def _info_plist(version: str) -> bytes:
    return plistlib.dumps(
        {
            "CFBundleDevelopmentRegion": "en",
            "CFBundleDisplayName": "Open Agronomy",
            "CFBundleExecutable": "OpenAgronomy",
            "CFBundleIdentifier": "io.openagronomy.desktop",
            "CFBundleInfoDictionaryVersion": "6.0",
            "CFBundleName": "Open Agronomy",
            "CFBundlePackageType": "APPL",
            "CFBundleShortVersionString": version,
            "CFBundleVersion": version,
            "LSMinimumSystemVersion": "26.0",
            "NSHighResolutionCapable": True,
            "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True},
        }
    )


def _audit_macho_links(app: Path) -> int:
    checked = 0
    for path in sorted(app.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        with path.open("rb") as handle:
            if handle.read(4) not in MACHO_MAGICS:
                continue
        completed = subprocess.run(["otool", "-L", str(path)], check=True, capture_output=True, text=True)
        for line in completed.stdout.splitlines()[1:]:
            dependency = line.strip().split(" ", 1)[0]
            if dependency.startswith("/") and not dependency.startswith(
                ("/System/Library/", "/usr/lib/")
            ):
                raise ValueError(f"packaged binary depends on a non-system absolute path: {path}: {dependency}")
        checked += 1
    if checked == 0:
        raise ValueError("desktop app contained no Mach-O binaries to verify")
    return checked


def build(root: Path, output: Path, *, python: Path, version: str) -> dict[str, object]:
    report = preflight(root, output, python=python)
    if not report["space_ready"]:
        raise ValueError(
            f"insufficient build space: {report['free_bytes']} bytes free; "
            f"planning floor {MIN_BUILD_FREE_BYTES} bytes"
        )
    import PyInstaller  # fail before creating the staging directory

    if PyInstaller.__version__ != "6.22.3":
        raise ValueError("desktop builder requires PyInstaller 6.22.3")
    source_status = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=normal"],
        check=True,
        capture_output=True,
        text=True,
    )
    if source_status.stdout.strip():
        raise ValueError("desktop candidate builds require a clean committed checkout")
    source_commit = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    receipt_path = output.with_suffix(".build.json")
    if receipt_path.exists():
        raise FileExistsError(f"refusing to overwrite an existing build receipt: {receipt_path}")

    stage = Path(tempfile.mkdtemp(prefix="open-agronomy-macos-app-", dir=output.parent))
    app = stage / "Open Agronomy.app"
    contents = app / "Contents"
    resources = contents / "Resources/runtime"
    helpers = contents / "Helpers"
    executable = contents / "MacOS/OpenAgronomy"
    try:
        subprocess.run(["npm", "run", "build"], cwd=root / "frontend", check=True)
        if not (root / "frontend/dist/index.html").is_file():
            raise ValueError("frontend build did not produce an index.html")
        resources.mkdir(parents=True)
        helpers.mkdir(parents=True)
        executable.parent.mkdir(parents=True)
        for relative in _tracked_asset_files(root):
            _copy_asset(root / relative, resources / relative)
        for item in sorted((root / "frontend/dist").rglob("*")):
            if item.is_symlink():
                raise ValueError(f"production frontend contains a symlink: {item}")
            if item.is_file():
                relative = item.relative_to(root)
                _copy_asset(item, resources / relative)
        manifest = _asset_manifest(resources)
        (contents / "Resources/runtime-manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
        (contents / "Info.plist").write_bytes(_info_plist(version))
        subprocess.run(
            [
                str(python), "-m", "PyInstaller", "--onedir", "--noconfirm",
                "--name", "OpenAgronomyBackend",
                "--distpath", str(stage / "backend-dist"),
                "--workpath", str(stage / "pyinstaller-work"),
                "--specpath", str(stage / "pyinstaller-spec"),
                "--paths", str(root), "--paths", str(root / "src"),
                "--collect-all", "mlx", "--collect-all", "mlx_lm",
                "--collect-all", "mlx_vlm", "--collect-submodules", "agno",
                "--collect-submodules", "transformers",
                str(root / "macos_app/backend.py"),
            ],
            cwd=root,
            check=True,
        )
        shutil.move(str(stage / "backend-dist/OpenAgronomyBackend"), helpers)
        subprocess.run(
            [
                "swiftc", "-parse-as-library", str(root / "macos_app/Launcher.swift"),
                "-o", str(executable),
            ],
            check=True,
        )
        macho_count = _audit_macho_links(app)
        subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(app)], check=True)
        subprocess.run(["codesign", "--verify", "--deep", "--strict", str(app)], check=True)
        if not (helpers / "OpenAgronomyBackend/OpenAgronomyBackend").is_file():
            raise ValueError("PyInstaller did not produce the backend executable")
        app.rename(output)
    except Exception:
        print(f"Unpromoted failed build retained at {stage}", file=sys.stderr)
        raise
    result = {
        **report,
        "status": "built_unsigned_local_candidate",
        "source_commit": source_commit,
        "pyinstaller_version": PyInstaller.__version__,
        "code_signature": "ad_hoc_local_only",
        "runtime_contract_sha256": manifest["contract_sha256"],
        "asset_file_count": len(manifest["files"]),
        "audited_macho_file_count": macho_count,
        "output": str(output),
    }
    receipt_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    try:
        shutil.rmtree(stage)
    except OSError:
        result["scratch_retained"] = str(stage)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--version", default="0.1.0")
    parser.add_argument("--preflight", action="store_true")
    args = parser.parse_args()
    try:
        root = args.source_root.resolve(strict=True)
        output = args.output.expanduser()
        if args.preflight:
            report = preflight(root, output, python=args.python)
        else:
            report = build(root, output, python=args.python, version=args.version)
        print(json.dumps(report, indent=2))
        if args.preflight:
            return 0 if report["space_ready"] else 1
        return 0 if report["status"] == "built_unsigned_local_candidate" else 1
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(json.dumps({"status": "blocked", "detail": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
