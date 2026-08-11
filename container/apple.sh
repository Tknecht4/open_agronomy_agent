#!/bin/sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
. "$ROOT_DIR/container/runtime-common.sh"
runtime_load_env
COMMAND=${1:-status}
if [ "$COMMAND" = "import" ]; then
  exec "$ROOT_DIR/container/import-release.sh" apple "${2:-}"
fi
runtime_configure "${2:-${AGRONOMY_AGENT_RUNTIME_PROFILE:-default}}"
if [ -n "${AGRONOMY_AGENT_CONTAINER_NAME:-}" ]; then
  NAME=$AGRONOMY_AGENT_CONTAINER_NAME
elif [ "$PROFILE" = "default" ]; then
  NAME=open-agronomy-agent
else
  NAME="open-agronomy-agent-$PROFILE"
fi
OFFLINE_NETWORK=${AGRONOMY_AGENT_OFFLINE_NETWORK:-open-agronomy-agent-offline}
require_cli() {
  if ! command -v container >/dev/null 2>&1; then
    printf 'Apple Container is not installed. Install the signed package from https://github.com/apple/container/releases and rerun.\n' >&2
    exit 1
  fi
}

build_image() {
  "$ROOT_DIR/container/build-image.sh" apple
}

network_ready() {
  container system dns list 2>/dev/null | grep -q 'host.container.internal'
}

network_exists() {
  container network list 2>/dev/null | awk 'NR > 1 {print $1}' | grep -Fxq "$1"
}

ensure_offline_network() {
  if ! network_exists "$OFFLINE_NETWORK"; then
    container network create --internal "$OFFLINE_NETWORK" >/dev/null
  fi
  RUNTIME_NETWORK=$OFFLINE_NETWORK
  MODEL_BIND=$(
    container network inspect "$OFFLINE_NETWORK" \
      | sed -n 's/.*"ipv4Gateway" : "\([^"]*\)".*/\1/p' \
      | head -n 1
  )
  if [ -z "$MODEL_BIND" ]; then
    printf 'Could not resolve the host gateway for offline network %s.\n' "$OFFLINE_NETWORK" >&2
    exit 1
  fi
  MODEL_BASE_HOST=$MODEL_BIND
}

configure_field_lan() {
  FIELD_LAN_BIND_ADDRESS=${AGRONOMY_AGENT_FIELD_LAN_BIND_ADDRESS:-}
  FIELD_LAN_ADVERTISE_HOST=${AGRONOMY_AGENT_FIELD_LAN_ADVERTISE_HOST:-}
  FIELD_LAN_TLS_DIR=${AGRONOMY_AGENT_FIELD_LAN_TLS_DIR:-}
  FIELD_LAN_PORT=${AGRONOMY_AGENT_FIELD_LAN_PORT:-8443}
  if [ -z "$FIELD_LAN_BIND_ADDRESS" ] ||
     [ -z "$FIELD_LAN_ADVERTISE_HOST" ] ||
     [ -z "$FIELD_LAN_TLS_DIR" ]; then
    printf 'start-field-lan requires AGRONOMY_AGENT_FIELD_LAN_BIND_ADDRESS, AGRONOMY_AGENT_FIELD_LAN_ADVERTISE_HOST, and AGRONOMY_AGENT_FIELD_LAN_TLS_DIR.\n' >&2
    exit 2
  fi
  case "$FIELD_LAN_PORT" in
    ""|*[!0-9]*)
      printf 'AGRONOMY_AGENT_FIELD_LAN_PORT must be an integer from 1024 through 65535.\n' >&2
      exit 2
      ;;
  esac
  if [ "$FIELD_LAN_PORT" -lt 1024 ] || [ "$FIELD_LAN_PORT" -gt 65535 ]; then
    printf 'AGRONOMY_AGENT_FIELD_LAN_PORT must be an integer from 1024 through 65535.\n' >&2
    exit 2
  fi
  if [ "${FIELD_LAN_TLS_DIR#/}" = "$FIELD_LAN_TLS_DIR" ]; then
    printf 'AGRONOMY_AGENT_FIELD_LAN_TLS_DIR must be an absolute path.\n' >&2
    exit 2
  fi
  PYTHONPATH="$ROOT_DIR:$ROOT_DIR/src" "$ROOT_DIR/.venv/bin/python" \
    "$ROOT_DIR/scripts/validate_field_lan_launch.py" \
    --bind-address "$FIELD_LAN_BIND_ADDRESS" \
    --advertise-host "$FIELD_LAN_ADVERTISE_HOST" \
    --tls-dir "$FIELD_LAN_TLS_DIR" \
    --require-pass >/dev/null
  FIELD_LAN_PAIRING_TOKEN=$(
    "$ROOT_DIR/.venv/bin/python" -c 'import secrets; print(secrets.token_urlsafe(32))'
  )
  FIELD_LAN_PAIRING_TOKEN_SHA256=$(
    printf '%s' "$FIELD_LAN_PAIRING_TOKEN" | shasum -a 256 | awk '{print $1}'
  )
  FIELD_LAN_SESSION_SECRET=$(
    "$ROOT_DIR/.venv/bin/python" -c 'import secrets; print(secrets.token_urlsafe(48))'
  )
  AGRONOMY_AGENT_LOCAL_PAIRING_TOKEN_SHA256=$FIELD_LAN_PAIRING_TOKEN_SHA256
  AGRONOMY_AGENT_OIDC_SESSION_SECRET=$FIELD_LAN_SESSION_SECRET
  export AGRONOMY_AGENT_LOCAL_PAIRING_TOKEN_SHA256
  export AGRONOMY_AGENT_OIDC_SESSION_SECRET
  APP_PORT=$FIELD_LAN_PORT
  export AGRONOMY_AGENT_APP_PORT=$APP_PORT
}

container_exists() {
  container ls --all 2>/dev/null | awk 'NR > 1 {print $1}' | grep -Fxq "$NAME"
}

stop_container() {
  container stop "$NAME" >/dev/null 2>&1 || true
  attempt=0
  while container_exists; do
    if [ "$attempt" -ge 30 ]; then
      printf 'Timed out waiting for Apple Container to remove %s.\n' "$NAME" >&2
      return 1
    fi
    attempt=$((attempt + 1))
    sleep 1
  done
}

wait_offline_model() {
  attempt=0
  while [ "$attempt" -lt 180 ]; do
    if container exec "$NAME" curl --silent --fail --max-time 2 \
      "http://${MODEL_BASE_HOST}:${MODEL_PORT}/v1/models" >/dev/null 2>&1; then
      break
    fi
    attempt=$((attempt + 1))
    sleep 1
  done
  if [ "$attempt" -ge 180 ]; then
    printf 'Timed out waiting for the host model through the isolated container network.\n' >&2
    return 1
  fi
  if ! container exec "$NAME" curl --silent --fail --max-time 360 \
    --header 'Content-Type: application/json' \
    --data '{"model":"default_model","messages":[{"role":"user","content":"Reply only READY."}],"max_tokens":8,"temperature":0,"stream":false}' \
    "http://${MODEL_BASE_HOST}:${MODEL_PORT}/v1/chat/completions" >/dev/null; then
    printf 'Host model warm-up failed through the isolated container network.\n' >&2
    return 1
  fi
  printf 'Host model ready through isolated bridge %s:%s.\n' "$MODEL_BASE_HOST" "$MODEL_PORT"
}

start_stack() {
  FIELD_LAN_MODE=${FIELD_LAN_MODE:-false}
  container system start
  RUNTIME_NETWORK=default
  MODEL_BIND=127.0.0.1
  MODEL_BASE_HOST=host.container.internal
  if [ "$NETWORK_MODE" = "offline" ]; then
    ensure_offline_network
  else
    if ! network_ready; then
      printf 'The host model bridge is not configured. Run: %s setup-network\n' "$0" >&2
      exit 1
    fi
    AGRONOMY_AGENT_MODEL_BIND="$MODEL_BIND" "$ROOT_DIR/container/model-host.sh" start
  fi
  mkdir -p "$STATE_DIR"
  stop_container
  if [ "$FIELD_LAN_MODE" = "true" ]; then
    container run \
      --name "$NAME" \
      --detach \
      --rm \
      --cpus "$CONTAINER_CPUS" \
      --memory "$CONTAINER_MEMORY" \
      --network "$RUNTIME_NETWORK" \
      --publish "${FIELD_LAN_BIND_ADDRESS}:${APP_PORT}:${CONTAINER_PORT}" \
      --volume "$STATE_DIR:$CONTAINER_STATE_MOUNT" \
      --volume "$MODEL_STATE_DIR:/model-host:ro" \
      --volume "$FIELD_LAN_TLS_DIR:/field-lan-source:ro" \
      --env AGRONOMY_AGENT_RUNTIME_ENGINE=apple-container \
      --env AGRONOMY_AGENT_RUNTIME_PROFILE="$PROFILE" \
      --env AGRONOMY_AGENT_MODEL_BASE_URL="http://${MODEL_BASE_HOST}:${MODEL_PORT}/v1" \
      --env AGRONOMY_AGENT_MODEL_IDENTITY_RECEIPT="/model-host/model-host.identity.json" \
      --env AGRONOMY_AGENT_MODEL_IDENTITY_REQUIRED="true" \
      --env AGRONOMY_AGENT_NETWORK_MODE=offline \
      --env AGRONOMY_AGENT_SPATIAL_PACK_ROOT="$SPATIAL_PACK_ROOT" \
      --env AGRONOMY_AGENT_FIELD_LAN=true \
      --env AGRONOMY_AGENT_ALLOW_LOCAL_DEV_AUTH=false \
      --env AGRONOMY_AGENT_LOCAL_PAIRING_TOKEN_SHA256 \
      --env AGRONOMY_AGENT_OIDC_SESSION_SECRET \
      "$IMAGE" \
      uvicorn agronomy_agent.server.app:create_app \
        --factory \
        --host 0.0.0.0 \
        --port "$CONTAINER_PORT" \
        --ssl-certfile /run/open-agronomy-field-lan/tls.crt \
        --ssl-keyfile /run/open-agronomy-field-lan/tls.key
  else
    container run \
      --name "$NAME" \
      --detach \
      --rm \
      --cpus "$CONTAINER_CPUS" \
      --memory "$CONTAINER_MEMORY" \
      --network "$RUNTIME_NETWORK" \
      --publish "127.0.0.1:${APP_PORT}:${CONTAINER_PORT}" \
      --volume "$STATE_DIR:$CONTAINER_STATE_MOUNT" \
      --volume "$MODEL_STATE_DIR:/model-host:ro" \
      --env AGRONOMY_AGENT_RUNTIME_ENGINE=apple-container \
      --env AGRONOMY_AGENT_RUNTIME_PROFILE="$PROFILE" \
      --env AGRONOMY_AGENT_MODEL_BASE_URL="http://${MODEL_BASE_HOST}:${MODEL_PORT}/v1" \
      --env AGRONOMY_AGENT_MODEL_IDENTITY_RECEIPT="/model-host/model-host.identity.json" \
      --env AGRONOMY_AGENT_MODEL_IDENTITY_REQUIRED="true" \
      --env AGRONOMY_AGENT_NETWORK_MODE="$NETWORK_MODE" \
      --env AGRONOMY_AGENT_SPATIAL_PACK_ROOT="$SPATIAL_PACK_ROOT" \
      "$IMAGE"
  fi
  if [ "$NETWORK_MODE" = "offline" ]; then
    if ! AGRONOMY_AGENT_MODEL_DEFER_READINESS=true \
      AGRONOMY_AGENT_MODEL_BIND="$MODEL_BIND" \
      "$ROOT_DIR/container/model-host.sh" start; then
      stop_container
      return 1
    fi
    if ! wait_offline_model; then
      stop_container
      return 1
    fi
  fi
  if [ "$FIELD_LAN_MODE" = "true" ]; then
    if ! curl --silent --fail \
      --cacert "$FIELD_LAN_TLS_DIR/tls.crt" \
      --resolve "${FIELD_LAN_ADVERTISE_HOST}:${APP_PORT}:${FIELD_LAN_BIND_ADDRESS}" \
      "https://${FIELD_LAN_ADVERTISE_HOST}:${APP_PORT}/health" >/dev/null; then
      container logs "$NAME" >&2 || true
      stop_container
      return 1
    fi
    printf 'Sealed field-LAN runtime is ready at https://%s:%s/ on %s.\n' \
      "$FIELD_LAN_ADVERTISE_HOST" "$APP_PORT" "$FIELD_LAN_BIND_ADDRESS"
    printf 'Open this one-time pairing link; do not copy it into retained logs or receipts:\n'
    printf 'https://%s:%s/#pair=%s\n' \
      "$FIELD_LAN_ADVERTISE_HOST" "$APP_PORT" "$FIELD_LAN_PAIRING_TOKEN"
  else
    smoke_stack
  fi
}

smoke_stack() {
  if runtime_smoke; then
    return 0
  fi
  container logs "$NAME" >&2 || true
  return 1
}

require_cli
case "$COMMAND" in
  setup-network)
    container system start
    if network_ready; then
      printf 'host.container.internal is already configured.\n'
    else
      sudo container system dns create host.container.internal --localhost 203.0.113.113
    fi
    ;;
  doctor)
    runtime_doctor
    container system status >/dev/null
    if network_ready; then
      printf 'Apple Container and the host model bridge are ready.\n'
    else
      printf 'Apple Container is running, but the host model bridge is missing. Run: %s setup-network\n' "$0" >&2
      exit 1
    fi
    ;;
  prepare-offline)
    runtime_doctor
    container image inspect "$IMAGE" >/dev/null
    runtime_prepare_offline
    printf 'Apple Container image %s is present. Run %s start-offline %s before disconnecting for the recorded smoke.\n' \
      "$IMAGE" "$0" "$PROFILE"
    ;;
  start-offline)
    NETWORK_MODE=offline
    export AGRONOMY_AGENT_NETWORK_MODE=offline
    start_stack
    ;;
  start-field-lan)
    NETWORK_MODE=offline
    FIELD_LAN_MODE=true
    export AGRONOMY_AGENT_NETWORK_MODE=offline
    configure_field_lan
    start_stack
    ;;
  build) build_image ;;
  start) start_stack ;;
  up) build_image; start_stack ;;
  stop) stop_container; "$ROOT_DIR/container/model-host.sh" stop ;;
  restart) start_stack ;;
  status)
    runtime_profile
    printf 'Container name: %s\n' "$NAME"
    container ls --all
    AGRONOMY_AGENT_MODEL_BIND=127.0.0.1 "$ROOT_DIR/container/model-host.sh" status
    ;;
  profile) runtime_profile; printf 'Container name: %s\n' "$NAME" ;;
  logs) container logs "$NAME" ;;
  smoke) smoke_stack ;;
  *) printf 'Usage: %s {setup-network|doctor|prepare-offline|start-offline|start-field-lan|build|start|up|stop|restart|status|profile|logs|smoke} [profile]\n       %s import {VERSION|RELEASE_DIR}\n' "$0" "$0" >&2; exit 2 ;;
esac
