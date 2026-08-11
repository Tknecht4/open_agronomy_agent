#!/bin/sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
. "$ROOT_DIR/container/runtime-common.sh"
runtime_load_env

ENGINE=${1:-}
IMAGE=${AGRONOMY_AGENT_IMAGE:-}
RELEASE_VERSION=${AGRONOMY_AGENT_RELEASE_VERSION:-}
BASE_IMAGE=${AGRONOMY_AGENT_BASE_IMAGE:-}
BASE_RUNTIME_CONTRACT_SHA256=${AGRONOMY_AGENT_BASE_RUNTIME_CONTRACT_SHA256:-}
MANIFEST="$ROOT_DIR/container/runtime_manifest.json"
VALIDATION_OUTPUT=${AGRONOMY_AGENT_OVERLAY_VALIDATION_OUTPUT:-"$ROOT_DIR/outputs/current_source_readiness_20260725/overlay_base_validation.json"}

case "$ENGINE" in
  apple|docker) ;;
  *) printf 'Usage: %s {apple|docker}\n' "$0" >&2; exit 2 ;;
esac
for assignment in \
  "AGRONOMY_AGENT_IMAGE=$IMAGE" \
  "AGRONOMY_AGENT_RELEASE_VERSION=$RELEASE_VERSION" \
  "AGRONOMY_AGENT_BASE_IMAGE=$BASE_IMAGE" \
  "AGRONOMY_AGENT_BASE_RUNTIME_CONTRACT_SHA256=$BASE_RUNTIME_CONTRACT_SHA256"
do
  value=${assignment#*=}
  if [ -z "$value" ]; then
    printf '%s is required for an overlay build.\n' "${assignment%%=*}" >&2
    exit 1
  fi
done

if [ ! -x "$ROOT_DIR/.venv/bin/python" ]; then
  printf 'Repository Python environment is missing at %s/.venv.\n' "$ROOT_DIR" >&2
  exit 1
fi
if [ ! -d "$ROOT_DIR/frontend/node_modules" ]; then
  printf 'Frontend dependencies are missing. Run npm ci in %s/frontend first.\n' "$ROOT_DIR" >&2
  exit 1
fi

if [ "$(uname -s)" = "Darwin" ]; then
  BUILD_CONTEXT_ROOT=${AGRONOMY_AGENT_BUILD_CONTEXT_ROOT:-"$HOME/Library/Caches/OpenAgronomyAgent"}
else
  BUILD_CONTEXT_ROOT=${AGRONOMY_AGENT_BUILD_CONTEXT_ROOT:-"${TMPDIR:-/tmp}/OpenAgronomyAgent"}
fi
mkdir -p "$BUILD_CONTEXT_ROOT"
BUILD_CONTEXT=$(mktemp -d "$BUILD_CONTEXT_ROOT/open-agronomy-agent-overlay.XXXXXX")
cleanup() {
  rm -rf "$BUILD_CONTEXT"
}
trap cleanup EXIT HUP INT TERM

npm --prefix "$ROOT_DIR/frontend" run build
"$ROOT_DIR/.venv/bin/python" "$ROOT_DIR/scripts/build_edge_runtime_manifest.py"

case "$ENGINE" in
  apple)
    command -v container >/dev/null 2>&1 || { printf 'Apple Container is not installed.\n' >&2; exit 1; }
    container image inspect "$BASE_IMAGE" >/dev/null
    container run \
      --rm \
      --network none \
      --entrypoint /bin/cp \
      --volume "$BUILD_CONTEXT:/out" \
      "$BASE_IMAGE" \
      /app/container/runtime_manifest.json \
      /out/base_runtime_manifest.json
    ;;
  docker)
    command -v docker >/dev/null 2>&1 || { printf 'Docker is not installed.\n' >&2; exit 1; }
    docker image inspect "$BASE_IMAGE" >/dev/null
    docker run \
      --rm \
      --network none \
      --entrypoint /bin/cp \
      --volume "$BUILD_CONTEXT:/out" \
      "$BASE_IMAGE" \
      /app/container/runtime_manifest.json \
      /out/base_runtime_manifest.json
    ;;
esac

"$ROOT_DIR/.venv/bin/python" "$ROOT_DIR/scripts/validate_edge_overlay_base.py" \
  --base "$BUILD_CONTEXT/base_runtime_manifest.json" \
  --current "$MANIFEST" \
  --expected-base-contract-sha256 "$BASE_RUNTIME_CONTRACT_SHA256" \
  --output "$VALIDATION_OUTPUT" \
  --require-pass

"$ROOT_DIR/.venv/bin/python" "$ROOT_DIR/scripts/stage_edge_build_context.py" \
  --root "$ROOT_DIR" \
  --output "$BUILD_CONTEXT" \
  --overlay
MANIFEST_SHA256=$(shasum -a 256 "$MANIFEST" | awk '{print $1}')

case "$ENGINE" in
  apple)
    container build \
      --tag "$IMAGE" \
      --file "$BUILD_CONTEXT/Containerfile" \
      --build-arg "BASE_IMAGE=$BASE_IMAGE" \
      --build-arg "BASE_RUNTIME_CONTRACT_SHA256=$BASE_RUNTIME_CONTRACT_SHA256" \
      --build-arg "RUNTIME_MANIFEST_SHA256=$MANIFEST_SHA256" \
      --build-arg "RELEASE_VERSION=$RELEASE_VERSION" \
      "$BUILD_CONTEXT"
    ;;
  docker)
    docker build \
      --tag "$IMAGE" \
      --file "$BUILD_CONTEXT/Containerfile" \
      --build-arg "BASE_IMAGE=$BASE_IMAGE" \
      --build-arg "BASE_RUNTIME_CONTRACT_SHA256=$BASE_RUNTIME_CONTRACT_SHA256" \
      --build-arg "RUNTIME_MANIFEST_SHA256=$MANIFEST_SHA256" \
      --build-arg "RELEASE_VERSION=$RELEASE_VERSION" \
      "$BUILD_CONTEXT"
    ;;
esac

printf 'Built %s with %s as a validated overlay on %s.\n' "$IMAGE" "$ENGINE" "$BASE_IMAGE"
