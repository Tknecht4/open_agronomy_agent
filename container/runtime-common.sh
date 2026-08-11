#!/bin/sh
set -eu

# Shared host-side runtime contract for Apple Container and Docker.

runtime_load_env() {
  set -a
  . "$ROOT_DIR/container/runtime-defaults.env"
  if [ -f "$ROOT_DIR/container/.env" ]; then
    . "$ROOT_DIR/container/.env"
  fi
  set +a
}

runtime_configure() {
  PROFILE=${1:-${AGRONOMY_AGENT_RUNTIME_PROFILE:-default}}
  case "$PROFILE" in
    ""|*[!A-Za-z0-9._-]*)
      printf 'Runtime profile must contain only letters, numbers, dot, underscore, or hyphen.\n' >&2
      exit 2
      ;;
  esac

  if [ -n "${AGRONOMY_AGENT_STATE_DIR:-}" ]; then
    STATE_DIR=$AGRONOMY_AGENT_STATE_DIR
  elif [ "$(uname -s)" = "Darwin" ]; then
    if [ "$PROFILE" = "default" ]; then
      STATE_DIR="$HOME/Library/Application Support/OpenAgronomyAgent/state"
    else
      STATE_DIR="$HOME/Library/Application Support/OpenAgronomyAgent/profiles/$PROFILE"
    fi
  elif [ "$PROFILE" = "default" ]; then
    STATE_DIR="$ROOT_DIR/.container-state/state"
  else
    STATE_DIR="$ROOT_DIR/.container-state/profiles/$PROFILE"
  fi

  if [ -n "${AGRONOMY_AGENT_MODEL_STATE_DIR:-}" ]; then
    MODEL_STATE_DIR=$AGRONOMY_AGENT_MODEL_STATE_DIR
  elif [ "$(uname -s)" = "Darwin" ]; then
    MODEL_STATE_DIR="$HOME/Library/Application Support/OpenAgronomyAgent/model-host"
  else
    MODEL_STATE_DIR="$ROOT_DIR/.container-state/model-host"
  fi

  IMAGE=${AGRONOMY_AGENT_IMAGE:-open-agronomy-agent:edge}
  APP_PORT=${AGRONOMY_AGENT_APP_PORT:-8080}
  MODEL_PORT=${AGRONOMY_AGENT_MODEL_PORT:-8081}
  CONTAINER_CPUS=${AGRONOMY_AGENT_CONTAINER_CPUS:-4}
  CONTAINER_MEMORY=${AGRONOMY_AGENT_CONTAINER_MEMORY:-4g}
  CONTAINER_PORT=${AGRONOMY_AGENT_CONTAINER_PORT:-8080}
  CONTAINER_STATE_MOUNT=${AGRONOMY_AGENT_CONTAINER_STATE_MOUNT:-/state}
  SPATIAL_PACK_ROOT=${AGRONOMY_AGENT_SPATIAL_PACK_ROOT:-/state/spatial-pack}
  NETWORK_MODE=${AGRONOMY_AGENT_NETWORK_MODE:-online}
  case "$NETWORK_MODE" in
    online|offline) ;;
    *) printf 'AGRONOMY_AGENT_NETWORK_MODE must be online or offline.\n' >&2; exit 2 ;;
  esac
  if [ "$CONTAINER_PORT" != "8080" ]; then
    printf 'The image contract requires AGRONOMY_AGENT_CONTAINER_PORT=8080.\n' >&2
    exit 2
  fi
  if [ "$CONTAINER_STATE_MOUNT" != "/state" ]; then
    printf 'The image contract requires AGRONOMY_AGENT_CONTAINER_STATE_MOUNT=/state.\n' >&2
    exit 2
  fi
  export AGRONOMY_AGENT_RUNTIME_PROFILE=$PROFILE
  export AGRONOMY_AGENT_STATE_DIR=$STATE_DIR
  export AGRONOMY_AGENT_MODEL_STATE_DIR=$MODEL_STATE_DIR
  export AGRONOMY_AGENT_IMAGE=$IMAGE
  export AGRONOMY_AGENT_APP_PORT=$APP_PORT
  export AGRONOMY_AGENT_MODEL_PORT=$MODEL_PORT
  export AGRONOMY_AGENT_CONTAINER_CPUS=$CONTAINER_CPUS
  export AGRONOMY_AGENT_CONTAINER_MEMORY=$CONTAINER_MEMORY
  export AGRONOMY_AGENT_CONTAINER_PORT=$CONTAINER_PORT
  export AGRONOMY_AGENT_CONTAINER_STATE_MOUNT=$CONTAINER_STATE_MOUNT
  export AGRONOMY_AGENT_SPATIAL_PACK_ROOT=$SPATIAL_PACK_ROOT
  export AGRONOMY_AGENT_NETWORK_MODE=$NETWORK_MODE
  mkdir -p "$STATE_DIR" "$MODEL_STATE_DIR"
}

runtime_doctor() {
  failed=0
  for path in \
    "$ROOT_DIR/.venv/bin/python" \
    "$ROOT_DIR/.venv/bin/mlx_lm.server" \
    "$ROOT_DIR/scripts/build_edge_runtime_manifest.py" \
    "$ROOT_DIR/scripts/write_model_host_identity.py" \
    "$ROOT_DIR/scripts/stage_edge_build_context.py" \
    "$ROOT_DIR/Containerfile"; do
    if [ ! -e "$path" ]; then
      printf 'Missing runtime prerequisite: %s\n' "$path" >&2
      failed=1
    fi
  done
  if [ ! -w "$STATE_DIR" ]; then
    printf 'Application state directory is not writable: %s\n' "$STATE_DIR" >&2
    failed=1
  fi
  if [ ! -w "$MODEL_STATE_DIR" ]; then
    printf 'Model state directory is not writable: %s\n' "$MODEL_STATE_DIR" >&2
    failed=1
  fi
  if [ "$failed" -ne 0 ]; then
    return 1
  fi
  printf 'Shared runtime prerequisites are ready.\n'
}

runtime_prepare_offline() {
  receipt="$STATE_DIR/offline-readiness.json"
  PYTHONPATH="$ROOT_DIR/src" "$ROOT_DIR/.venv/bin/python" \
    "$ROOT_DIR/scripts/prepare_offline_runtime.py" \
    --root "$ROOT_DIR" \
    --state-dir "$STATE_DIR" \
    --output "$receipt" \
    --require-ready >/dev/null
  printf 'Offline asset readiness verified without network access: %s\n' "$receipt"
}

runtime_profile() {
  printf 'Runtime profile: %s\nImage: %s\nState directory: %s\nModel state directory: %s\nModel identity receipt: %s\nNetwork mode: %s\nContainer resources: %s CPUs, %s memory\nApplication URL: http://127.0.0.1:%s/\n' \
    "$PROFILE" "$IMAGE" "$STATE_DIR" "$MODEL_STATE_DIR" "$MODEL_STATE_DIR/model-host.identity.json" "$NETWORK_MODE" "$CONTAINER_CPUS" "$CONTAINER_MEMORY" "$APP_PORT"
}

runtime_smoke() {
  attempt=0
  while [ "$attempt" -lt 90 ]; do
    if curl --silent --fail "http://127.0.0.1:${APP_PORT}/health" >/dev/null 2>&1; then
      curl --silent --fail "http://127.0.0.1:${APP_PORT}/" >/dev/null
      printf 'Open Agronomy Agent is ready at http://127.0.0.1:%s/\n' "$APP_PORT"
      return 0
    fi
    attempt=$((attempt + 1))
    sleep 1
  done
  return 1
}
