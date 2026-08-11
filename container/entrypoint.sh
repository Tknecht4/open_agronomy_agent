#!/bin/sh
set -eu

mkdir -p /state/db /state/artifacts /state/cache/geo /state/cache/agno_lexical_index /state/cache/public_tools /state/logs

if [ -d /app/data/derived/geo_cache ]; then
  cp -n /app/data/derived/geo_cache/*.json /state/cache/geo/ 2>/dev/null || true
fi

if [ "${AGRONOMY_AGENT_FIELD_LAN:-false}" = "true" ]; then
  if [ ! -f /field-lan-source/tls.crt ] || [ ! -f /field-lan-source/tls.key ]; then
    printf 'Field-LAN mode requires read-only tls.crt and tls.key mounts.\n' >&2
    exit 1
  fi
  install -d -o agronomy -g agronomy -m 0700 /run/open-agronomy-field-lan
  install -o agronomy -g agronomy -m 0444 \
    /field-lan-source/tls.crt /run/open-agronomy-field-lan/tls.crt
  install -o agronomy -g agronomy -m 0400 \
    /field-lan-source/tls.key /run/open-agronomy-field-lan/tls.key
fi

if chown -R agronomy:agronomy /state 2>/dev/null; then
  exec gosu agronomy "$@"
fi

if [ ! -w /state ]; then
  printf 'The /state mount is not writable by the container runtime.\n' >&2
  exit 1
fi

# Apple Container host mounts reject chown but remain writable inside the
# per-container VM, so keep the VM-local root identity for this process.
exec "$@"
