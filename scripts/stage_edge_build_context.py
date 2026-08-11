#!/usr/bin/env python3
"""Stage the canonical edge image context without scanning the full checkout."""
from __future__ import annotations

import argparse
import json
import shlex
import shutil
from pathlib import Path


IGNORED_NAMES = {
    ".DS_Store",
    ".env",
    ".git",
    ".hf_cache",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "dist",
    "node_modules",
}
MANIFEST_FILTERED_KNOWLEDGE_ROOTS = {
    Path("data/seed"),
    Path("data/derived/rag"),
}


def _copy_ignore(_directory: str, names: list[str]) -> set[str]:
    return {name for name in names if name in IGNORED_NAMES or name.endswith(".pyc")}


def _copy_path(root: Path, output: Path, relative: Path) -> None:
    source = (root / relative).resolve()
    if root != source and root not in source.parents:
        raise ValueError(f"COPY source escapes checkout: {relative}")
    if not source.exists():
        raise FileNotFoundError(f"COPY source is missing: {relative}")
    destination = output / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, destination, dirs_exist_ok=True, ignore=_copy_ignore)
    else:
        shutil.copy2(source, destination)


def _copy_sources(containerfile: str) -> list[Path]:
    sources: list[Path] = []
    normalized = containerfile.replace("\\\n", " ")
    for raw_line in normalized.splitlines():
        line = raw_line.strip()
        if not line.startswith("COPY "):
            continue
        tokens = shlex.split(line)
        if any(token.startswith("--from=") for token in tokens[1:]):
            continue
        operands = [token for token in tokens[1:] if not token.startswith("--")]
        if len(operands) < 2:
            raise ValueError(f"Unsupported COPY instruction: {raw_line}")
        sources.extend(Path(token.rstrip("/")) for token in operands[:-1])
    return sources


def stage(root: Path, output: Path) -> dict[str, int | str]:
    root = root.resolve()
    output = output.resolve()
    containerfile_path = root / "Containerfile"
    containerfile = containerfile_path.read_text(encoding="utf-8")
    manifest = json.loads((root / "container/runtime_manifest.json").read_text(encoding="utf-8"))

    shutil.copy2(containerfile_path, output / "Containerfile")

    copied_sources = 0
    for relative in dict.fromkeys(_copy_sources(containerfile)):
        if relative in MANIFEST_FILTERED_KNOWLEDGE_ROOTS:
            for entry in manifest.get("runtime_knowledge") or []:
                knowledge_path = Path(str(entry.get("path") or ""))
                if knowledge_path.is_relative_to(relative):
                    _copy_path(root, output, knowledge_path)
            copied_sources += 1
            continue
        _copy_path(root, output, relative)
        copied_sources += 1

    files = [path for path in output.rglob("*") if path.is_file()]
    return {
        "status": "pass",
        "mode": "full",
        "source_count": copied_sources,
        "file_count": len(files),
        "bytes": sum(path.stat().st_size for path in files),
    }


def stage_overlay(root: Path, output: Path) -> dict[str, int | str]:
    root = root.resolve()
    output = output.resolve()
    overlay_containerfile = root / "Containerfile.overlay"
    shutil.copy2(overlay_containerfile, output / "Containerfile")
    sources = (
        Path("src/agronomy_agent"),
        Path("scripts"),
        Path("container"),
        Path("frontend/dist"),
    )
    for relative in sources:
        _copy_path(root, output, relative)
    files = [path for path in output.rglob("*") if path.is_file()]
    return {
        "status": "pass",
        "mode": "overlay",
        "source_count": len(sources),
        "file_count": len(files),
        "bytes": sum(path.stat().st_size for path in files),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--overlay", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    stager = stage_overlay if args.overlay else stage
    print(json.dumps(stager(args.root, args.output), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
