#!/bin/sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
if [ -f "$ROOT_DIR/container/.env" ]; then
  set -a
  . "$ROOT_DIR/container/.env"
  set +a
fi
if [ -n "${AGRONOMY_AGENT_MODEL_STATE_DIR:-}" ]; then
  STATE_DIR=$AGRONOMY_AGENT_MODEL_STATE_DIR
elif [ "$(uname -s)" = "Darwin" ]; then
  STATE_DIR="$HOME/Library/Application Support/OpenAgronomyAgent/model-host"
else
  STATE_DIR="$ROOT_DIR/.container-state/model-host"
fi
MODEL_ID=${AGRONOMY_AGENT_MODEL_ID:-mlx-community/gemma-4-e2b-it-4bit}
MODEL_CONFIG=${AGRONOMY_AGENT_MODEL_CONFIG:-configs/model_gemma4_e2b_interface_v2.yaml}
MODEL_REVISION=${AGRONOMY_AGENT_MODEL_REVISION:-}
case "$MODEL_CONFIG" in
  /*) MODEL_CONFIG_PATH=$MODEL_CONFIG ;;
  *) MODEL_CONFIG_PATH="$ROOT_DIR/$MODEL_CONFIG" ;;
esac
MODEL_HOST=${AGRONOMY_AGENT_MODEL_BIND:-127.0.0.1}
if [ "$MODEL_HOST" = "0.0.0.0" ]; then
  MODEL_PROBE_HOST=127.0.0.1
else
  MODEL_PROBE_HOST=$MODEL_HOST
fi
MODEL_PORT=${AGRONOMY_AGENT_MODEL_PORT:-8081}
MAX_TOKENS=${AGRONOMY_AGENT_MODEL_MAX_TOKENS:-640}
PREFILL_STEP_SIZE=${AGRONOMY_AGENT_MODEL_PREFILL_STEP_SIZE:-2048}
# Exact-request cache reuse can stall some Gemma/MLX-LM combinations. Keep the
# stable release default at zero; advanced users can opt in per model.
PROMPT_CACHE_SIZE=${AGRONOMY_AGENT_MODEL_PROMPT_CACHE_SIZE:-0}
DEFER_READINESS=${AGRONOMY_AGENT_MODEL_DEFER_READINESS:-false}
PID_FILE="$STATE_DIR/model-host.pid"
CONFIG_FILE="$STATE_DIR/model-host.config"
IDENTITY_FILE="$STATE_DIR/model-host.identity.json"
LOG_FILE="$STATE_DIR/logs/model-host.log"
MLX_SERVER="$ROOT_DIR/.venv/bin/mlx_lm.server"
SCREEN_NAME=${AGRONOMY_AGENT_MODEL_SCREEN_NAME:-open-agronomy-model-host}
HUB_CACHE=${HF_HUB_CACHE:-"$ROOT_DIR/.hf_cache/hub"}

mkdir -p "$STATE_DIR/logs"

# Adopt the PID from releases that stored model-host control files inside the
# default application profile. This is a one-time, non-destructive migration.
if [ "$(uname -s)" = "Darwin" ]; then
  LEGACY_STATE_DIR="$HOME/Library/Application Support/OpenAgronomyAgent/state"
else
  LEGACY_STATE_DIR="$ROOT_DIR/.container-state"
fi
if [ ! -f "$PID_FILE" ] && [ -f "$LEGACY_STATE_DIR/model-host.pid" ]; then
  legacy_pid=$(cat "$LEGACY_STATE_DIR/model-host.pid")
  if kill -0 "$legacy_pid" 2>/dev/null; then
    printf '%s\n' "$legacy_pid" >"$PID_FILE"
  fi
fi

uses_screen() {
  [ "$(uname -s)" = "Darwin" ] && command -v screen >/dev/null 2>&1
}

is_running() {
  [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null
}

service_pid() {
  cat "$PID_FILE"
}

expected_configuration() {
  printf '%s\n' \
    "model_id=$MODEL_ID" \
    "model_config=$MODEL_CONFIG" \
    "model_revision=$MODEL_REVISION" \
    "parametric_adaptation=base_only" \
    "bind=$MODEL_HOST" \
    "port=$MODEL_PORT" \
    "max_tokens=$MAX_TOKENS" \
    "prefill_step_size=$PREFILL_STEP_SIZE" \
    "prompt_cache_size=$PROMPT_CACHE_SIZE"
}

configuration_matches() {
  [ -f "$CONFIG_FILE" ] \
    && [ -f "$IDENTITY_FILE" ] \
    && [ "$(cat "$CONFIG_FILE")" = "$(expected_configuration)" ]
}

record_configuration() {
  expected_configuration >"$CONFIG_FILE"
}

record_identity() {
  server_command=$1
  set -- \
    "$ROOT_DIR/.venv/bin/python" "$ROOT_DIR/scripts/write_model_host_identity.py" \
    --output "$IDENTITY_FILE" \
    --model-config "$MODEL_CONFIG_PATH" \
    --model-id "$MODEL_ID" \
    --hub-cache "$HUB_CACHE" \
    --process-id "$(service_pid)" \
    --bind "$MODEL_HOST" \
    --port "$MODEL_PORT" \
    --server-command "$server_command"
  if [ -n "$MODEL_REVISION" ]; then
    set -- "$@" --model-revision "$MODEL_REVISION"
  fi
  PYTHONPATH="$ROOT_DIR/src" "$@" >/dev/null
}

wait_ready() {
  attempt=0
  while [ "$attempt" -lt 180 ]; do
    if curl --silent --fail --max-time 2 \
      "http://${MODEL_PROBE_HOST}:${MODEL_PORT}/v1/models" >/dev/null 2>&1; then
      break
    fi
    if ! is_running; then
      printf 'Host model exited before readiness. See %s\n' "$LOG_FILE" >&2
      tail -n 40 "$LOG_FILE" >&2 || true
      return 1
    fi
    attempt=$((attempt + 1))
    sleep 1
  done
  if [ "$attempt" -ge 180 ]; then
    printf 'Timed out waiting for host model HTTP service. See %s\n' "$LOG_FILE" >&2
    return 1
  fi
  printf 'Warming the host model with a real completion (cold Metal start can take several minutes).\n'
  if ! curl --silent --fail --max-time 360 \
    --header 'Content-Type: application/json' \
    --data '{"model":"default_model","messages":[{"role":"user","content":"Reply only READY."}],"max_tokens":8,"temperature":0,"stream":false}' \
    "http://${MODEL_PROBE_HOST}:${MODEL_PORT}/v1/chat/completions" >/dev/null; then
    printf 'Host model warm-up failed. See %s\n' "$LOG_FILE" >&2
    tail -n 40 "$LOG_FILE" >&2 || true
    return 1
  fi
  printf 'Host model ready at http://%s:%s/v1\n' "$MODEL_PROBE_HOST" "$MODEL_PORT"
}

start_server() {
  if [ ! -x "$MLX_SERVER" ]; then
    printf 'MLX-LM server is missing at %s. Create the repo venv and install requirements.txt first.\n' "$MLX_SERVER" >&2
    return 1
  fi
  if is_running; then
    if configuration_matches; then
      printf 'Host model already running with PID %s using bind %s.\n' "$(service_pid)" "$MODEL_HOST"
      if [ "$DEFER_READINESS" = "true" ]; then
        return
      fi
      wait_ready
      return
    fi
    printf 'Host model configuration changed; restarting for bind %s.\n' "$MODEL_HOST"
    stop_server
  fi
  rm -f "$PID_FILE"
  rm -f "$LOG_FILE"
  set -- "$MLX_SERVER" \
    --model "$MODEL_ID" \
    --host "$MODEL_HOST" \
    --port "$MODEL_PORT" \
    --max-tokens "$MAX_TOKENS" \
    --temp 0 \
    --top-p 0.9 \
    --top-k 0 \
    --chat-template-args '{"enable_thinking":false}' \
    --prefill-step-size "$PREFILL_STEP_SIZE" \
    --prompt-cache-size "$PROMPT_CACHE_SIZE"
  SERVER_COMMAND=$*
  : >"$LOG_FILE"
  if uses_screen; then
    screen -S "$SCREEN_NAME" -X quit >/dev/null 2>&1 || true
    screen -dmS "$SCREEN_NAME" /bin/sh -c \
      'pid_file=$1; log_file=$2; shift 2; echo $$ >"$pid_file"; exec "$@" >>"$log_file" 2>&1' \
      sh "$PID_FILE" "$LOG_FILE" /usr/bin/env \
      "HF_HOME=${HF_HOME:-"$ROOT_DIR/.hf_cache"}" \
      "HF_HUB_CACHE=${HF_HUB_CACHE:-"$ROOT_DIR/.hf_cache/hub"}" \
      "$@"
    attempt=0
    while ! is_running && [ "$attempt" -lt 10 ]; do
      attempt=$((attempt + 1))
      sleep 1
    done
    if ! is_running; then
      printf 'Host model service failed to start. See %s\n' "$LOG_FILE" >&2
      tail -n 40 "$LOG_FILE" >&2 || true
      return 1
    fi
  else
    nohup /usr/bin/env \
      "HF_HOME=${HF_HOME:-"$ROOT_DIR/.hf_cache"}" \
      "HF_HUB_CACHE=${HF_HUB_CACHE:-"$ROOT_DIR/.hf_cache/hub"}" \
      "$@" >"$LOG_FILE" 2>&1 &
    echo "$!" >"$PID_FILE"
  fi
  record_configuration
  if [ "$DEFER_READINESS" = "true" ]; then
    record_identity "$SERVER_COMMAND"
    printf 'Host model started on %s:%s; readiness is delegated to the isolated container path.\n' \
      "$MODEL_HOST" "$MODEL_PORT"
    return
  fi
  wait_ready
  record_identity "$SERVER_COMMAND"
  printf 'Verified model identity receipt: %s\n' "$IDENTITY_FILE"
}

stop_server() {
  if ! is_running; then
    rm -f "$PID_FILE"
    printf 'Host model is not running.\n'
    return
  fi
  pid=$(service_pid)
  kill "$pid"
  attempt=0
  while is_running && [ "$attempt" -lt 30 ]; do
    attempt=$((attempt + 1))
    sleep 1
  done
  if is_running; then
    printf 'Host model did not stop cleanly (PID %s).\n' "$pid" >&2
    return 1
  fi
  if uses_screen; then
    screen -S "$SCREEN_NAME" -X quit >/dev/null 2>&1 || true
  fi
  rm -f "$PID_FILE" "$CONFIG_FILE" "$IDENTITY_FILE"
  printf 'Host model stopped.\n'
}

case "${1:-status}" in
  start) start_server ;;
  stop) stop_server ;;
  restart) stop_server; start_server ;;
  status)
    if is_running; then
      printf 'Host model running with PID %s on %s:%s (host client: http://127.0.0.1:%s/v1)\n' \
        "$(service_pid)" "$MODEL_HOST" "$MODEL_PORT" "$MODEL_PORT"
    else
      printf 'Host model is not running.\n'
      exit 1
    fi
    ;;
  logs) tail -n 100 -f "$LOG_FILE" ;;
  *) printf 'Usage: %s {start|stop|restart|status|logs}\n' "$0" >&2; exit 2 ;;
esac
