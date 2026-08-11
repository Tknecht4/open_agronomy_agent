#!/bin/sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
. "$ROOT_DIR/container/runtime-common.sh"
runtime_load_env

ENGINE=${1:-}
IMAGE=${AGRONOMY_AGENT_IMAGE:-open-agronomy-agent:edge}
RELEASE_VERSION=${AGRONOMY_AGENT_RELEASE_VERSION:-development}
MANIFEST="$ROOT_DIR/container/runtime_manifest.json"

case "$ENGINE" in
  apple|docker) ;;
  *) printf 'Usage: %s {apple|docker}\n' "$0" >&2; exit 2 ;;
esac

if [ ! -x "$ROOT_DIR/.venv/bin/python" ]; then
  printf 'Repository Python environment is missing at %s/.venv.\n' "$ROOT_DIR" >&2
  exit 1
fi

if [ "$(uname -s)" = "Darwin" ]; then
  BUILD_CONTEXT_ROOT=${AGRONOMY_AGENT_BUILD_CONTEXT_ROOT:-"$HOME/Library/Caches/OpenAgronomyAgent"}
else
  BUILD_CONTEXT_ROOT=${AGRONOMY_AGENT_BUILD_CONTEXT_ROOT:-"${TMPDIR:-/tmp}/OpenAgronomyAgent"}
fi
mkdir -p "$BUILD_CONTEXT_ROOT"
BUILD_CONTEXT=$(mktemp -d "$BUILD_CONTEXT_ROOT/open-agronomy-agent-build.XXXXXX")
cleanup() {
  rm -rf "$BUILD_CONTEXT"
}
trap cleanup EXIT HUP INT TERM

"$ROOT_DIR/.venv/bin/python" "$ROOT_DIR/scripts/build_edge_runtime_manifest.py"
"$ROOT_DIR/.venv/bin/python" "$ROOT_DIR/scripts/stage_edge_build_context.py" \
  --root "$ROOT_DIR" \
  --output "$BUILD_CONTEXT"
MANIFEST_SHA256=$(shasum -a 256 "$MANIFEST" | awk '{print $1}')

case "$ENGINE" in
  apple)
    command -v container >/dev/null 2>&1 || { printf 'Apple Container is not installed.\n' >&2; exit 1; }
    container build \
      --tag "$IMAGE" \
      --file "$BUILD_CONTEXT/Containerfile" \
      --build-arg "RUNTIME_MANIFEST_SHA256=$MANIFEST_SHA256" \
      --build-arg "RELEASE_VERSION=$RELEASE_VERSION" \
      "$BUILD_CONTEXT"
    ;;
  docker)
    command -v docker >/dev/null 2>&1 || { printf 'Docker is not installed.\n' >&2; exit 1; }
    docker build \
      --tag "$IMAGE" \
      --file "$BUILD_CONTEXT/Containerfile" \
      --build-arg "RUNTIME_MANIFEST_SHA256=$MANIFEST_SHA256" \
      --build-arg "RELEASE_VERSION=$RELEASE_VERSION" \
      "$BUILD_CONTEXT"
    ;;
esac

printf 'Built %s with %s from the canonical staged OCI context.\n' "$IMAGE" "$ENGINE"
