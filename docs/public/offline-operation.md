# Offline operation

Offline mode is an explicit operating condition, not an assumption that every online fact has been cached.

## Available without internet

- downloaded MLX model weights;
- policy-admitted RAG and knowledge-graph artifacts;
- deterministic routing, evidence packaging and calculation;
- field/session history and answer traces;
- a separately installed and verified external geospatial pack when the operator selects one;
- governed static snapshots whose provider, date and resolution remain visible.

## Blocked or limited offline

- current weather and forecasts;
- current pesticide registration and label text;
- live regulation or program eligibility;
- uncached public-data queries;
- claims that a regional map or historical statistic describes the present field.

An unavailable external adapter returns `blocked_offline` before a network request. The answer must state the missing live evidence and avoid manufacturing a current value.

## Prairie spatial pack

The clone contains the source/profile contract and installer, not large generated SQLite/RTree databases. The first supported local profile, `prairie-dss-v1`, contains only AAFC Detailed Soil Survey layers for Alberta, Saskatchewan, and Manitoba. It deliberately does not require erosion, national grids, or other incomplete layers.

Use the explicit [compact offline data setup](operations/offline-data-setup.md) procedure to download pinned source bytes once into a user-managed state directory, derive the flat pack, and export `AGRONOMY_AGENT_SPATIAL_PACK_ROOT`. No application startup, readiness check, or RAG validation initiates that download. The installer validates hashes, lineage, SQLite/RTree integrity, and fixed application-path intersections before it promotes the pack.

Passing those gates validates packaging and application-path operation. It does not prove that a mapped component occurs at a point or convert historical survey attributes into current field truth.

## Field-LAN mode

Build the frontend, provision an operator-controlled TLS certificate for the LAN host, and launch with `--field-lan`. The launcher requires HTTPS, validates the certificate identity, generates a one-time pairing token, disables development authentication, and blocks public network adapters.

The grower remains responsible for device access, backups, and deletion/export of local field records. Secrets, traces, model caches, user databases, and private knowledge overlays are ignored by Git and excluded from the public repository checkpoint.
