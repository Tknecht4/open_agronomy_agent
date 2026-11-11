# Prepare Quebec terrain context

The saved field's **Soil & terrain** tab can check which official MAPAQ LiDAR
tiles intersect its Quebec polygon. Prepare the pinned tile index once on the
device running the server. The index is optional and is downloaded only by an
explicit operator command.

From the source checkout, using the environment configured in the
[native setup guide](native-setup.md), run the following while connected.

```bash
PYTHONPATH=src .venv/bin/python scripts/manage_quebec_lidar_field_pack.py fetch-index --online
```

This downloads about 3.7 MB and verifies the bytes against
`data/manifests/quebec_lidar_context.json`. The source pin was observed on
November 11, 2026 and contains 613 tile footprints. A changed download fails
verification and preserves the existing index. Review source drift and update
the manifest deliberately before accepting new bytes.

Return to the saved Quebec polygon and select **Check saved field**. The
availability check uses the local index. A match identifies downloadable tiles.
An empty match reports the retained index's result. Neither result establishes
pixel coverage or present conditions on the farm. A missing or changed local
index produces a setup message.

## Download and derive a private summary

Keep the field geometry, plans, archives and derived records in a private
operator directory. Use a WGS84 Polygon or MultiPolygon GeoJSON geometry and
new output filenames.

```bash
PYTHONPATH=src .venv/bin/python scripts/manage_quebec_lidar_field_pack.py plan \
  --geometry /absolute/private/field.geojson --output /absolute/private/plan.json

PYTHONPATH=src .venv/bin/python scripts/manage_quebec_lidar_field_pack.py download \
  --plan /absolute/private/plan.json --directory /absolute/private/tiles \
  --output /absolute/private/frozen.json --online

PYTHONPATH=src .venv/bin/python scripts/manage_quebec_lidar_field_pack.py derive \
  --plan /absolute/private/plan.json --frozen /absolute/private/frozen.json \
  --geometry /absolute/private/field.geojson --directory /absolute/private/tiles \
  --output /absolute/private/derived.json
```

Only `fetch-index` and `download` accept network access. The download reveals
the requested tile identifiers and network metadata to the official host.
Planning and derivation retain the exact boundary locally. The plan allows at
most four tiles, with a 250 MiB archive limit per tile. Derivation also needs
temporary extraction space and the serving environment's GeoPandas/Shapely
dependencies.

The downloader validates bounded ZIP members and freezes their SHA256 hashes.
The publisher's tile index supplies no independent archive checksum. Derivation
rechecks those hashes, validates projected metre-based vector CRS and geometry,
clips depression and flow-path features to the exact hash-bound field, and
reports their area and length. Feature parts at tile boundaries can represent
the same landscape feature. The slope raster remains unprocessed.

The derived JSON is a private operator artifact. Automatic import into a field
record or chat is outside this workflow. Its values describe source-derived
terrain context. Field inspection, source coverage and acquisition age still
matter when assessing water, erosion or drainage. Use the
[DTM terrain operator](geospatial-foundation.md) for separately prepared local
elevation data and its own processing contract.

The source is MAPAQ's *Relief agricole issu du LiDAR*, published through Données
Québec under CC BY 4.0. Retain its attribution when sharing derived material.
[Official source and coverage description](https://www.donneesquebec.ca/recherche/dataset/relief-agricole-issu-du-lidar).
