# Offline operation

Offline mode is an explicit operating condition, not an assumption that every online fact has been cached.

## Available without internet

- downloaded MLX model weights;
- policy-admitted RAG and knowledge-graph artifacts;
- deterministic routing, evidence packaging and calculation;
- field/session history and answer traces;
- packaged geospatial indexes when installed in the verified offline bundle;
- governed static snapshots whose provider, date and resolution remain visible.

## Blocked or limited offline

- current weather and forecasts;
- current pesticide registration and label text;
- live regulation or program eligibility;
- uncached public-data queries;
- claims that a regional map or historical statistic describes the present field.

An unavailable external adapter returns `blocked_offline` before a network request. The answer must state the missing live evidence and avoid manufacturing a current value.

## Field-LAN mode

Build the frontend, provision an operator-controlled TLS certificate for the LAN host, and launch with `--field-lan`. The launcher requires HTTPS, validates the certificate identity, generates a one-time pairing token, disables development authentication, and blocks public network adapters.

The grower remains responsible for device access, backups, and deletion/export of local field records. Secrets, traces, model caches, user databases, and private knowledge overlays are ignored by Git and excluded from the public repository checkpoint.
