#!/bin/sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
ENGINE=${1:-}
RELEASE_REF=${2:-}

case "$ENGINE" in
  apple|docker) ;;
  *) printf 'Usage: %s {apple|docker} {VERSION|RELEASE_DIR}\n' "$0" >&2; exit 2 ;;
esac
if [ -z "$RELEASE_REF" ]; then
  printf 'Usage: %s {apple|docker} {VERSION|RELEASE_DIR}\n' "$0" >&2
  exit 2
fi
if [ -d "$RELEASE_REF" ]; then
  RELEASE_DIR=$(CDPATH= cd -- "$RELEASE_REF" && pwd)
else
  case "$RELEASE_REF" in
    *[!A-Za-z0-9._-]*) printf 'Release version contains unsafe characters: %s\n' "$RELEASE_REF" >&2; exit 2 ;;
  esac
  RELEASE_DIR="$ROOT_DIR/outputs/releases/open-agronomy-agent-$RELEASE_REF"
fi

PYTHON="$ROOT_DIR/.venv/bin/python"
if [ ! -x "$PYTHON" ]; then
  printf 'Repository Python environment is missing at %s.\n' "$PYTHON" >&2
  exit 1
fi
if [ -n "${AGRONOMY_AGENT_RELEASE_PUBLIC_KEY:-}" ]; then
  DETAILS=$(
    PYTHONPATH="$ROOT_DIR/src" "$PYTHON" "$ROOT_DIR/scripts/verify_edge_release.py" \
      --release-dir "$RELEASE_DIR" \
      --public-key "$AGRONOMY_AGENT_RELEASE_PUBLIC_KEY" \
      --format lines
  )
elif [ "${AGRONOMY_AGENT_ALLOW_UNSIGNED_RELEASE:-0}" = "1" ]; then
  DETAILS=$(
    PYTHONPATH="$ROOT_DIR/src" "$PYTHON" "$ROOT_DIR/scripts/verify_edge_release.py" \
      --release-dir "$RELEASE_DIR" \
      --allow-unsigned \
      --format lines
  )
else
  printf 'Set AGRONOMY_AGENT_RELEASE_PUBLIC_KEY to a trusted Ed25519 public key.\n' >&2
  printf 'For an explicitly non-production rehearsal only, set AGRONOMY_AGENT_ALLOW_UNSIGNED_RELEASE=1.\n' >&2
  exit 1
fi
VERSION=$(printf '%s\n' "$DETAILS" | sed -n '1p')
IMAGE=$(printf '%s\n' "$DETAILS" | sed -n '2p')
ARCHIVE=$(printf '%s\n' "$DETAILS" | sed -n '3p')
ARCHIVE_SHA256=$(printf '%s\n' "$DETAILS" | sed -n '4p')

case "$ENGINE" in
  apple)
    command -v container >/dev/null 2>&1 || { printf 'Apple Container is not installed.\n' >&2; exit 1; }
    container system status >/dev/null
    container image load --input "$ARCHIVE"
    container image inspect "$IMAGE" >/dev/null
    ;;
  docker)
    command -v docker >/dev/null 2>&1 || { printf 'Docker is not installed.\n' >&2; exit 1; }
    docker info >/dev/null 2>&1 || { printf 'Docker Desktop is not running.\n' >&2; exit 1; }
    docker load --input "$ARCHIVE"
    if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
      image_id=$(docker image ls --no-trunc --format '{{.Repository}}:{{.Tag}} {{.ID}}' \
        | awk -v image="$IMAGE" '$1 == image {print $2; exit}')
      if [ -n "$image_id" ]; then
        docker image tag "$image_id" "$IMAGE"
      fi
    fi
    docker image inspect "$IMAGE" >/dev/null
    ;;
esac

printf 'Verified and imported %s into %s.\n' "$IMAGE" "$ENGINE"
printf 'Release: %s\nArchive SHA256: %s\n' "$VERSION" "$ARCHIVE_SHA256"
printf 'Launch: AGRONOMY_AGENT_IMAGE=%s ./container/%s.sh start release-verification\n' "$IMAGE" "$ENGINE"
