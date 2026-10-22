#!/usr/bin/env python3
"""Inventory the frozen app's actual inputs and carry their original legal files.

Analysis-00.toc is produced by the same PyInstaller invocation as the bundle.
Unknown third-party owners, missing legal texts and unaudited native wheels fail
closed. Network access is only to acquire exact source archives during a build;
archives are hashed, retained with the app and never executed or extracted.
"""
from __future__ import annotations

import ast
import hashlib
import importlib.metadata as metadata
import json
import os
import re
import shutil
import sys
import sysconfig
import tarfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Iterable

KINDS = {"PYMODULE", "PYSOURCE", "EXTENSION", "BINARY", "DATA", "EXECUTABLE"}
LEGAL = re.compile(r"(?:^|[/_-])(licen[cs]e|copying|notice|authors|copyright|patents|readme\.ijg)(?:[./_-]|$)", re.I)
# The desktop profile is SQLite + the pinned MLX model. These optional stacks
# are absent from the frozen distribution, not relicensed by the project.
EXCLUDED_MODULES = (
    "cv2", "psycopg", "psycopg_binary", "pymupdf", "fitz", "torch",
    "torchvision", "torchaudio", "tensorflow", "jax", "numba", "llvmlite",
    "sounddevice", "miniaudio", "rasterio", "pyflwdir",
)
FORBIDDEN = re.compile(r"(?:^|[/_.-])(cv2|fitz|pymupdf|psycopg|psycopg_binary|libx264|libx265|libavcodec|libavformat)(?:[/_.-]|$)", re.I)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def analysis_inputs(path: Path) -> list[tuple[str, str, str]]:
    """Read tuples as data; never execute a generated spec or a TOC."""
    result: set[tuple[str, str, str]] = set()
    def visit(value: object) -> None:
        if isinstance(value, (tuple, list)):
            if len(value) == 3 and all(isinstance(x, str) for x in value) and value[2] in KINDS:
                result.add(tuple(value))
            else:
                for child in value:
                    visit(child)
    visit(ast.literal_eval(path.read_text()))
    if not result:
        raise ValueError("PyInstaller analysis has no collected inputs")
    return sorted(result)


def _download(url: str, target: Path, expected: str | None = None) -> str:
    if not url.startswith("https://"):
        raise ValueError("source downloads require HTTPS")
    algorithm = "sha512" if expected and len(expected) == 128 else "sha256"
    def matches(path: Path) -> bool:
        h = hashlib.new(algorithm)
        with path.open("rb") as f:
            for block in iter(lambda: f.read(1024 * 1024), b""):
                h.update(block)
        return h.hexdigest() == expected
    if target.exists():
        digest = sha256(target)
        if expected and not matches(target):
            raise ValueError(f"source archive hash mismatch: {target.name}")
        return digest
    target.parent.mkdir(parents=True, exist_ok=True)
    cache_root = os.environ.get("AGRONOMY_AGENT_LICENSE_SOURCE_CACHE")
    if cache_root and expected:
        cached = Path(cache_root) / target.name
        if cached.is_file() and matches(cached):
            try:
                import subprocess
                subprocess.run(["cp", "-c", str(cached), str(target)], check=True, capture_output=True)
            except (OSError, subprocess.CalledProcessError):
                shutil.copy2(cached, target)
            return sha256(target)
    partial = target.with_suffix(target.suffix + ".partial")
    with urllib.request.urlopen(url, timeout=90) as response, partial.open("wb") as f:
        if not response.url.startswith("https://"):
            raise ValueError("source download redirected away from HTTPS")
        shutil.copyfileobj(response, f)
    digest = sha256(partial)
    if expected and not matches(partial):
        raise ValueError(f"source archive hash mismatch: {target.name}")
    partial.rename(target)
    return digest


def _archive_notices(archive: Path) -> dict[str, bytes]:
    """Read bounded regular legal members without extracting untrusted paths."""
    result = {}
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as z:
            for member in z.infolist():
                if not member.is_dir() and LEGAL.search(member.filename) and member.file_size <= 2_000_000:
                    result[member.filename] = z.read(member)
    else:
        with tarfile.open(archive, "r:*") as t:
            for member in t:
                if member.isfile() and LEGAL.search(member.name) and member.size <= 2_000_000:
                    f = t.extractfile(member)
                    if f:
                        result[member.name] = f.read()
    return {k: v for k, v in result.items() if v.strip()}


def _sdist(name: str, version: str, destination: Path) -> dict:
    url = f"https://pypi.org/pypi/{name}/{version}/json"
    with urllib.request.urlopen(url, timeout=60) as response:
        release = json.load(response)
    candidates = [x for x in release["urls"] if x["packagetype"] == "sdist" and not x.get("yanked")]
    if len(candidates) != 1:
        raise ValueError(f"exactly one unyanked source archive required: {name}=={version}")
    item = candidates[0]
    filename = item["filename"]
    if Path(filename).name != filename:
        raise ValueError("unsafe source filename")
    target = destination / filename
    digest = _download(item["url"], target, item["digests"]["sha256"])
    return {"path": f"sources/{filename}", "sha256": digest, "url": item["url"], "metadata_url": url}


def _legal_files(dist: metadata.Distribution) -> dict[str, bytes]:
    result = {}
    for entry in dist.files or ():
        if LEGAL.search(str(entry)):
            path = Path(dist.locate_file(entry))
            if path.is_file() and path.stat().st_size <= 2_000_000:
                data = path.read_bytes()
                if data.strip():
                    result[str(entry)] = data
    return result


def _write_notices(target: Path, notices: dict[str, bytes], *, require_license: bool = True) -> list[dict]:
    full_terms = re.compile(rb"Permission (?:is hereby granted|to use, copy)|Redistribution and use in source|TERMS AND CONDITIONS FOR USE|Mozilla Public License", re.I)
    if require_license and not any(re.search(r"(?:licen[cs]e|copying)", Path(name).name, re.I) or (len(data) > 300 and full_terms.search(data)) for name, data in notices.items()):
        raise ValueError(f"no full upstream licence files for {target.name}")
    target.mkdir(parents=True, exist_ok=True)
    rows = []
    for number, (original, data) in enumerate(sorted(notices.items())):
        # Original paths remain provenance only; they never select a write path.
        filename = f"{number:03d}-{Path(original).name}"
        (target / filename).write_bytes(data)
        rows.append({"original": original, "file": f"notices/{target.name}/{filename}", "sha256": hashlib.sha256(data).hexdigest()})
    return rows


def collect_licenses(root: Path, app: Path, toc: Path, *, distributions: Iterable[metadata.Distribution] | None = None) -> dict:
    inputs = analysis_inputs(toc)
    policy = json.loads((root / "macos_app/native_components.json").read_text())
    if sys.version.split()[0] != policy["python_version"]:
        raise ValueError("native interpreter version requires a reviewed source registry update")
    owners: dict[Path, list[metadata.Distribution]] = {}
    dists = list(metadata.distributions() if distributions is None else distributions)
    for dist in dists:
        if canonical(dist.metadata["Name"]) == "agronomy-agent":
            continue
        for entry in dist.files or ():
            owners.setdefault(Path(dist.locate_file(entry)).resolve(), []).append(dist)
    selected: dict[str, tuple[metadata.Distribution, list[tuple[str, str, str]]]] = {}
    interpreter_inputs = []
    interpreter_resources = []
    framework_plist = (Path(sys.base_prefix) / "Resources/Info.plist").resolve()
    framework_plist_destination = f"Python.framework/Versions/{sys.version_info.major}.{sys.version_info.minor}/Resources/Info.plist"
    stdlib = Path(sysconfig.get_path("stdlib")).resolve()
    source_root = root.resolve()
    for destination, source, kind in inputs:
        if FORBIDDEN.search(destination):
            raise ValueError(f"prohibited optional component in native app: {destination}")
        path = Path(source).resolve()
        matches = owners.get(path, [])
        if matches:
            names = {canonical(d.metadata["Name"]) for d in matches}
            if len(names) != 1:
                raise ValueError(f"ambiguous dependency ownership: {destination}")
            dist = matches[0]
            name = next(iter(names))
            selected.setdefault(name, (dist, []))[1].append((destination, source, kind))
        elif path.is_relative_to(source_root):
            continue
        elif path.is_relative_to(stdlib) and "site-packages" not in path.parts:
            if kind in {"BINARY", "EXTENSION"}:
                interpreter_inputs.append({"destination": destination, "source_basename": path.name, "sha256": sha256(path)})
            continue
        elif kind == "DATA" and path == framework_plist and destination == framework_plist_destination:
            # PyInstaller copies the active Homebrew Python framework's own
            # metadata outside stdlib. Its terms accompany the CPython source;
            # an unrelated file with the same basename is still unowned.
            interpreter_resources.append({"destination": destination, "source_basename": path.name, "sha256": sha256(path)})
        elif kind in {"BINARY", "EXTENSION"}:
            # Non-wheel interpreter libraries need an exact reviewed record too.
            name = "interpreter-libraries"
            if not any(re.fullmatch(x, path.name) for x in policy["interpreter_binary_patterns"]):
                raise ValueError(f"unowned native input: {destination} ({path.name})")
            interpreter_inputs.append({"destination": destination, "source_basename": path.name, "sha256": sha256(path)})
        else:
            raise ValueError(f"unowned third-party input: {destination}")
    legal = app / "Contents/Resources/legal"
    if legal.exists():
        raise FileExistsError(legal)
    (legal / "sources").mkdir(parents=True)
    packages = []
    for name, (dist, records) in sorted(selected.items()):
        declaration = dist.metadata.get("License-Expression") or dist.metadata.get("License") or "See upstream legal texts"
        if re.search(r"\bA?GPL|LGPL", declaration, re.I) and name not in {"pyinstaller", "scipy"}:
            raise ValueError(f"copyleft package requires a separately reviewed combination: {name}")
        native = [row for row in records if row[2] in {"BINARY", "EXTENSION"}]
        if native and f"{name}=={dist.version}" not in policy["native_packages"]:
            raise ValueError(f"unreviewed native wheel: {name}=={dist.version}")
        notices = _legal_files(dist)
        has_license = any(re.search(r"licen[cs]e|copying", Path(n).name, re.I) for n in notices)
        required_source = name in policy.get("source_required_packages", [])
        archive = None
        # Most permissive packages only require their complete notices. Retain
        # source only where terms require it; use an sdist to recover missing
        # upstream notice files without shipping unnecessary package sources.
        if not has_license or required_source or (native and name not in policy.get("source_overrides", {})):
            archive = _sdist(name, dist.version, legal / "sources")
            notices.update({"source/" + k: v for k, v in _archive_notices(legal / archive["path"]).items()})
            if not required_source:
                (legal / archive["path"]).unlink()
                archive = {k: v for k, v in archive.items() if k != "path"}
        package = {"name": name, "version": dist.version, "declared_license": declaration,
                   "source": archive, "notices": _write_notices(legal / "notices" / name, notices),
                   "collected_input_count": len(records),
                   "native_inputs": [{"destination": d, "source_basename": Path(s).name, "sha256": sha256(Path(s))} for d, s, _ in native]}
        packages.append(package)
    rust = json.loads((root / "macos_app/rust_dependency_licenses.json").read_text())
    rust_selected = set(selected) & set(rust["package_versions"])
    rust_files = []
    if rust_selected:
        for name in rust_selected:
            if selected[name][0].version != rust["package_versions"][name]:
                raise ValueError(f"Rust dependency notices require review: {name}")
            for destination, source, kind in selected[name][1]:
                if kind in {"BINARY", "EXTENSION"}:
                    commits = set(re.findall(rb"/rustc/([a-f0-9]{40})/", Path(source).read_bytes()))
                    if not commits or any(c.decode() not in rust["compiler_commits"] for c in commits):
                        raise ValueError(f"Rust runtime notices require review: {destination}")
        for entry in [{"file": rust["notice_file"], "sha256": rust["notice_sha256"]}] + rust["runtime_notices"]:
            source = root / "macos_app" / entry["file"]
            if sha256(source) != entry["sha256"]:
                raise ValueError("reviewed Rust notice payload changed")
            target = legal / entry["file"]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            rust_files.append({"file": entry["file"], "sha256": entry["sha256"]})
    # Capture the exact BUNDLE paths after PyInstaller relocation and signing.
    # Basenames alone cannot account for two different copies of a library.
    bundle_toc = toc.with_name("BUNDLE-00.toc")
    bundle_inputs = analysis_inputs(bundle_toc)
    helper = "Contents/Helpers/OpenAgronomyBackend.app/"
    bundled = []
    expected_paths = {}
    def framework_destination(destination: str) -> str:
        path = Path(destination)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("unsafe collected binary destination")
        parts = list(path.parts)
        inside_framework = False
        for index, part in enumerate(parts[:-1]):
            if part.endswith(".framework"):
                inside_framework = True
            if not inside_framework:
                parts[index] = part.replace(".", "__dot__")
        return "Contents/Frameworks/" + "/".join(parts)
    for package in packages:
        for row in package["native_inputs"]:
            expected_paths[framework_destination(row["destination"])] = {
                "owner": package["name"], "source_input_sha256": row["sha256"]}
    for row in interpreter_inputs:
        expected_paths[framework_destination(row["destination"])] = {
            "owner": "interpreter", "source_input_sha256": row["sha256"]}
    expected_paths["Contents/MacOS/OpenAgronomyBackend"] = {"owner": "project-entrypoint-and-pyinstaller-bootloader"}
    for destination, source, kind in bundle_inputs:
        if kind not in {"BINARY", "EXTENSION", "EXECUTABLE"}:
            continue
        if destination not in expected_paths:
            raise ValueError(f"unowned BUNDLE native input: {destination}")
        path = app / helper / destination
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"missing BUNDLE native input: {destination}")
        bundled.append({"path": helper + destination, "sha256": sha256(path), **expected_paths[destination]})
    if not bundled:
        raise ValueError("BUNDLE has no native inputs")
    sources = []
    for asset in policy["sources"]:
        if not set(asset.get("packages", [])) & set(selected) and asset.get("packages"):
            continue
        target = legal / "sources" / asset["filename"]
        digest = _download(asset["url"], target, asset.get("sha256") or asset["sha512"])
        notices = _archive_notices(target) if not asset.get("plain_text") else {asset["filename"]: target.read_bytes()}
        sources.append({**asset, "path": f"sources/{asset['filename']}", "sha256": digest,
                        "notices": _write_notices(legal / "notices" / asset["id"], notices, require_license=not (asset.get("legal_basis") or asset.get("notice_reference")))})
    for entry in policy.get("additional_notice_files", []):
        source = root / "macos_app" / entry["file"]
        if sha256(source) != entry["sha256"]:
            raise ValueError("reviewed native header notices changed")
        target = legal / entry["file"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        rust_files.append(entry)
    # The interpreter's OpenSSL can differ from the statically linked copies
    # in GDAL and cryptography. Preserve its actual release's own notices.
    import ssl
    openssl_version = ssl.OPENSSL_VERSION.split()[1]
    if not re.fullmatch(r"[34]\.\d+\.\d+", openssl_version):
        raise ValueError("unreviewed interpreter TLS licence family")
    ssl_notices = {}
    for filename in ("LICENSE.txt", "NOTICE"):
        target = legal / "sources" / ("python-openssl-" + openssl_version + "-" + filename)
        url = f"https://raw.githubusercontent.com/openssl/openssl/openssl-{openssl_version}/{filename}"
        _download(url, target)
        ssl_notices[filename] = target.read_bytes()
    sources.append({"id": "interpreter-openssl", "version": openssl_version,
                    "license": "Apache-2.0", "notices": _write_notices(legal / "notices/interpreter-openssl", ssl_notices)})
    shutil.copy2(root / "macos_app/THIRD_PARTY_RUNTIME.md", legal / "README.md")
    provenance_path = root / "macos_app/native_source_provenance.json"
    shutil.copy2(provenance_path, legal / "native-source-provenance.json")
    provenance = json.loads(provenance_path.read_text())
    for component in provenance.get("components", []):
        if component["name"] == "uriparser":
            overlay = legal / "build-overlays/uriparser"
            overlay.mkdir(parents=True)
            (overlay / "portfile.cmake").write_text(component["portfile"])
            (overlay / "vcpkg.json").write_text(json.dumps(component["metadata"], indent=2) + "\n")
    index = app / "Contents/Resources/runtime/frontend/dist/LICENSE_NOTICES.html"
    index.write_text(index.read_text().replace("<!-- native-notices -->",
        '<p><a href="native-legal/README.md">Native library rights, sources and replacement</a> · '
        '<a href="native-legal/inventory.json">Native dependency inventory</a></p>'))
    # The frontend serves these same complete notices from the About page.
    browser_legal = app / "Contents/Resources/runtime/frontend/dist/native-legal"
    shutil.copytree(legal / "notices", browser_legal / "notices")
    shutil.copy2(legal / "README.md", browser_legal / "README.md")
    report = {"schema_version": "open_agronomy_agent.native_licenses.v1", "project_license": "PolyForm-Noncommercial-1.0.0",
              "python_version": sys.version.split()[0], "packages": packages, "components": sources, "rust_notices": rust_files,
              "analysis_sha256": sha256(toc), "interpreter_inputs": interpreter_inputs, "interpreter_resources": interpreter_resources,
              "bundled_native_inputs": bundled, "excluded_modules": list(EXCLUDED_MODULES)}
    for target in (legal / "inventory.json", app / "Contents/Resources/runtime/frontend/dist/native-legal/inventory.json"):
        target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


def verify_bundle(app: Path, report: dict) -> dict:
    """Bind legal payloads and every actual Mach-O to collected package inputs."""
    legal = app / "Contents/Resources/legal"
    for package in report["packages"] + report["components"]:
        archive = package.get("source", package)
        if archive and "path" in archive and sha256(legal / archive["path"]) != archive["sha256"]:
            raise ValueError("source archive changed after collection")
        for notice in package["notices"]:
            if sha256(legal / notice["file"]) != notice["sha256"]:
                raise ValueError("upstream notice changed after collection")
    for notice in report.get("rust_notices", []):
        if sha256(legal / notice["file"]) != notice["sha256"]:
            raise ValueError("Rust notice payload changed after collection")
    allowed = {r["path"]: r["sha256"] for r in report["bundled_native_inputs"]}
    launcher = "Contents/MacOS/OpenAgronomy"
    binaries = []
    magics = {b"\xfe\xed\xfa\xce", b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca", b"\xca\xfe\xba\xbf", b"\xbf\xba\xfe\xca"}
    for path in sorted(app.rglob("*")):
        if path.is_symlink():
            if not path.resolve().is_relative_to(app.resolve()):
                raise ValueError("app symlink escapes its distribution")
            continue
        if not path.is_file():
            continue
        relative = path.relative_to(app).as_posix()
        if FORBIDDEN.search(relative):
            raise ValueError(f"prohibited bundled component: {relative}")
        with path.open("rb") as f:
            native = f.read(4) in magics
        if native:
            if relative not in allowed and relative != launcher:
                raise ValueError(f"unaccounted bundled Mach-O: {relative}")
            digest = sha256(path)
            if relative in allowed and digest != allowed[relative]:
                raise ValueError(f"bundled native input changed: {relative}")
            binaries.append({"path": relative, "sha256": digest})
    for relative, digest in allowed.items():
        if not (app / relative).is_file() or sha256(app / relative) != digest:
            raise ValueError(f"bundled native input missing or changed: {relative}")
    if not binaries:
        raise ValueError("native app contains no Mach-O payload")
    return {"status": "verified", "native_file_count": len(binaries), "binaries": binaries,
            "package_count": len(report["packages"]), "component_count": len(report["components"])}
