#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Sequence

from huggingface_hub import snapshot_download
import yaml

from agronomy_agent.runtime_profiles import DEFAULT_MODEL_CONFIG

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CACHE_DIR = Path(__file__).resolve().parents[1] / ".hf_cache/hub"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Download a Hugging Face model into the repo-local cache, optionally "
            "binding the request to an exact model profile and revision."
        )
    )
    parser.add_argument("--model", default=None)
    parser.add_argument("--revision", default=None)
    parser.add_argument(
        "--model-config",
        default=None,
        help=(
            "YAML model profile. The serving model ID and model_revision are used, "
            "and conflicting --model/--revision values are rejected. When neither "
            f"--model nor --model-config is supplied, {DEFAULT_MODEL_CONFIG} is used."
        ),
    )
    parser.add_argument(
        "--cache-dir",
        default=str(DEFAULT_CACHE_DIR),
    )
    parser.add_argument("--local-dir", default=None)
    return parser


def resolve_download_request(args: argparse.Namespace) -> tuple[str, str | None]:
    configured_model: str | None = None
    configured_revision: str | None = None
    model_config = args.model_config
    if not model_config and not args.model:
        model_config = DEFAULT_MODEL_CONFIG
    if model_config:
        config_path = Path(model_config).expanduser()
        if not config_path.is_absolute():
            config_path = REPO_ROOT / config_path
        config_path = config_path.resolve()
        config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        if not isinstance(config, dict):
            raise ValueError("model configuration must contain a YAML mapping")
        configured_model = str(
            config.get("serving_model_id") or config.get("model_id") or ""
        ).strip()
        configured_revision = str(config.get("model_revision") or "").strip() or None
        if not configured_model:
            raise ValueError("model configuration does not define a serving model ID")
        if args.model and args.model != configured_model:
            raise ValueError(
                f"--model {args.model} conflicts with configured serving model "
                f"{configured_model}"
            )
        if (
            args.revision
            and configured_revision
            and args.revision != configured_revision
        ):
            raise ValueError(
                f"--revision {args.revision} conflicts with configured revision "
                f"{configured_revision}"
            )
    model = str(args.model or configured_model or "").strip()
    revision = str(args.revision or configured_revision or "").strip() or None
    if not model:
        raise ValueError("model ID must not be empty")
    return model, revision


def download_model(args: argparse.Namespace) -> str:
    model, revision = resolve_download_request(args)
    cache_dir = Path(args.cache_dir).resolve()
    os.environ.setdefault("HF_HOME", str(cache_dir.parent))
    path = snapshot_download(
        repo_id=model,
        revision=revision,
        cache_dir=str(cache_dir),
        local_dir=args.local_dir,
    )
    return str(path)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    print(download_model(args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
