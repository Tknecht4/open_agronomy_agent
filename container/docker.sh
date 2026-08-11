#!/bin/sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
. "$ROOT_DIR/container/runtime-common.sh"
runtime_load_env
COMMAND=${1:-status}
if [ "$COMMAND" = "import" ]; then
  exec "$ROOT_DIR/container/import-release.sh" docker "${2:-}"
fi
runtime_configure "${2:-${AGRONOMY_AGENT_RUNTIME_PROFILE:-default}}"
if [ "$PROFILE" = "default" ]; then
  COMPOSE_PROJECT=open-agronomy-agent
else
  COMPOSE_PROJECT="open-agronomy-agent-$PROFILE"
fi
export AGRONOMY_AGENT_RUNTIME_ENGINE=docker

require_docker() {
  command -v docker >/dev/null 2>&1 || { printf 'Docker is not installed.\n' >&2; exit 1; }
  docker info >/dev/null 2>&1 || { printf 'Docker Desktop is not running.\n' >&2; exit 1; }
}

compose() {
  docker compose --project-name "$COMPOSE_PROJECT" --project-directory "$ROOT_DIR" --file "$ROOT_DIR/docker-compose.edge.yml" "$@"
}

ensure_local_image() {
  if docker image inspect "$IMAGE" >/dev/null 2>&1; then
    return 0
  fi
  image_id=$(docker image ls --no-trunc --format '{{.Repository}}:{{.Tag}} {{.ID}}' \
    | awk -v image="$IMAGE" '$1 == image {print $2; exit}')
  if [ -n "$image_id" ] && docker image inspect "$image_id" >/dev/null 2>&1; then
    docker image tag "$image_id" "$IMAGE"
    printf 'Normalized imported OCI index %s to Docker tag %s.\n' "$image_id" "$IMAGE"
  fi
}

smoke_stack() {
  if runtime_smoke; then
    return 0
  fi
  compose logs app >&2 || true
  return 1
}

case "$COMMAND" in
  profile)
    runtime_profile
    printf 'Compose project: %s\n' "$COMPOSE_PROJECT"
    exit 0
    ;;
  config)
    command -v docker >/dev/null 2>&1 || { printf 'Docker is not installed.\n' >&2; exit 1; }
    compose config
    exit 0
    ;;
esac

require_docker
case "$COMMAND" in
  doctor)
    runtime_doctor
    printf 'Docker daemon and Compose are ready.\n'
    ;;
  prepare-offline)
    runtime_doctor
    ensure_local_image
    docker image inspect "$IMAGE" >/dev/null
    runtime_prepare_offline
    printf 'Docker image %s is present. Run %s start-offline %s before disconnecting for the recorded smoke.\n' \
      "$IMAGE" "$0" "$PROFILE"
    ;;
  build)
    "$ROOT_DIR/container/build-image.sh" docker
    ;;
  start)
    AGRONOMY_AGENT_MODEL_BIND=0.0.0.0 "$ROOT_DIR/container/model-host.sh" start
    ensure_local_image
    compose up --detach --no-build
    smoke_stack
    ;;
  start-offline)
    AGRONOMY_AGENT_NETWORK_MODE=offline
    export AGRONOMY_AGENT_NETWORK_MODE
    AGRONOMY_AGENT_MODEL_BIND=0.0.0.0 "$ROOT_DIR/container/model-host.sh" start
    ensure_local_image
    compose up --detach --no-build
    smoke_stack
    ;;
  up) "$0" start "$PROFILE" ;;
  stop) compose down; "$ROOT_DIR/container/model-host.sh" stop ;;
  restart) compose down; "$0" start "$PROFILE" ;;
  status)
    runtime_profile
    printf 'Compose project: %s\n' "$COMPOSE_PROJECT"
    compose ps
    AGRONOMY_AGENT_MODEL_BIND=0.0.0.0 "$ROOT_DIR/container/model-host.sh" status
    ;;
  logs) compose logs --follow app ;;
  smoke) smoke_stack ;;
  *) printf 'Usage: %s {doctor|prepare-offline|start-offline|config|build|start|up|stop|restart|status|profile|logs|smoke} [profile]\n       %s import {VERSION|RELEASE_DIR}\n' "$0" "$0" >&2; exit 2 ;;
esac
