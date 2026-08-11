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

## Prairie spatial pack

The Prairie spatial pack is a separate release asset because its four SQLite/RTree databases are roughly 470 MiB and one file exceeds GitHub's per-file limit. It contains the AAFC Detailed Soil Survey layers for Alberta, Saskatchewan, and Manitoba plus the national 2021 soil-erosion-risk layer. After extraction, run both gates before relying on it offline:

```bash
python scripts/build_prairie_spatial_pack.py \
  --destination /absolute/path/to/prairie-spatial-pack \
  --verify-only
PYTHONPATH=src python scripts/verify_prairie_spatial_pack.py \
  --pack-root /absolute/path/to/prairie-spatial-pack
```

The first gate verifies hashes, derivation manifests, SQLite integrity, RTree counts, and the pack contract. The second sends fixed Alberta, Saskatchewan, and Manitoba field polygons through the same offline geospatial service used by the app and requires mapped components, declared source scales, and allowlisted terms for the SoilWise concept bridge. Set `AGRONOMY_AGENT_SPATIAL_PACK_ROOT` before a native launch. Container profiles use `/state/spatial-pack`; extract the pack into the profile's host state directory under `spatial-pack/` before launch.

Passing these gates validates packaging and application-path operation. It does not prove that a mapped component occurs at a point or convert historical survey attributes into current field truth.

## Field-LAN mode

Build the frontend, provision an operator-controlled TLS certificate for the LAN host, and launch with `--field-lan`. The launcher requires HTTPS, validates the certificate identity, generates a one-time pairing token, disables development authentication, and blocks public network adapters.

The grower remains responsible for device access, backups, and deletion/export of local field records. Secrets, traces, model caches, user databases, and private knowledge overlays are ignored by Git and excluded from the public repository checkpoint.
