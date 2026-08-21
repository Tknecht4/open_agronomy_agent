# Open Agronomy Agent containers

The repository packages one `linux/arm64` OCI image contract for two host
runtimes. Apple Container is the exercised release-builder path; Docker
Compose is a direct translation that consumes the same imported archive.
Model weights, private records, user state, and the optional Prairie spatial
pack remain outside the image.

| Path | Status | Boundary |
|---|---|---|
| Apple Container | Exercised Apple Silicon release path | A built archive is not promoted until its version-specific gates pass |
| Docker Compose | Translation of the Apple-built archive | Translation tests do not prove every host or network environment |
| Field-LAN | TLS, one-time pairing, and blocked-public-egress launch path | A successful launch is not portable-field proof |

## Build one immutable release candidate

From the repository root:

```bash
./container/release.sh VERSION
```

The candidate under `outputs/releases/open-agronomy-agent-VERSION/` contains
the OCI archive, checksums, release manifest, and validation evidence. Do not
overwrite or relabel it. Model and user data are not included.

`container/runtime_manifest.json` is a generated inventory, not a hand-edited
source contract. Regenerate it with `scripts/build_edge_runtime_manifest.py`
after the final model/RAG configuration, runtime code, scripts, public docs, or
admitted data changes. The builder binds active runtime v2 and the full governed
runtime trees; it preserves `generated_at` only when the resulting contract
hash is unchanged. Release preflight must reject a stale generated manifest.

## Apple Container quick start

```bash
./container/apple.sh setup-network
./container/apple.sh doctor PROFILE
./container/apple.sh import VERSION
AGRONOMY_AGENT_IMAGE=open-agronomy-agent:VERSION \
  ./container/apple.sh start PROFILE
```

Open `http://127.0.0.1:8080/`. Stop the complete profile with:

```bash
./container/apple.sh stop PROFILE
```

## Docker translation

```bash
./container/docker.sh doctor PROFILE
./container/docker.sh import VERSION
AGRONOMY_AGENT_IMAGE=open-agronomy-agent:VERSION \
  ./container/docker.sh up PROFILE
```

`up` never builds; it starts the imported Apple-built candidate. Inspect the
translated configuration with `./container/docker.sh config PROFILE` and stop
it with:

```bash
./container/docker.sh stop PROFILE
```

## Field-LAN boundary

Field-LAN requires a private IPv4 bind, a separately prepared client, and a
trusted certificate directory containing `tls.crt` and a mode-`0600`
`tls.key`. The certificate subject alternative name must cover the advertised
host.

```bash
AGRONOMY_AGENT_IMAGE=open-agronomy-agent:VERSION \
AGRONOMY_AGENT_FIELD_LAN_BIND_ADDRESS=192.168.50.10 \
AGRONOMY_AGENT_FIELD_LAN_ADVERTISE_HOST=field-runtime.example.local \
AGRONOMY_AGENT_FIELD_LAN_TLS_DIR=/absolute/path/to/field-lan-tls \
AGRONOMY_AGENT_FIELD_LAN_PORT=8443 \
  ./container/apple.sh start-field-lan PROFILE
```

Use the printed one-time pairing link only on the prepared client. Do not
bypass certificate warnings or retain the pairing URL in evidence. Stop the
profile to invalidate its in-memory session secret.

## State and optional assets

- Profiles isolate accounts, fields, chats, feedback, and artifacts under the
  selected host-state directory and mount it at `/state`.
- The native MLX model host is shared across profiles but retains only its
  process identity and logs.
- Verify the optional Prairie spatial pack separately, then extract it into
  the profile's `spatial-pack/` directory so it appears at
  `/state/spatial-pack`.
- Geospatial catalogue status is not proof that an asset is bundled. Only a
  selected profile manifest, install receipt, and passing validator establish
  installed bytes.
- The edge image's geospatial content class is `lineage_manifests_only` and
  `runtime_layer_assets_included=false`; offline profile installation is the
  authority for actual runtime layer bytes.
- Override runtime paths and ports through `container/.env`, using
  `container/.env.example` as the reference.

## Verify and recover

Confirm the exact archive checksum/release manifest, run the engine-specific
`doctor`, exercise UI and API paths separately, and verify listeners disappear
after stopping. Never treat a package/unit test as field evidence.

The implemented overlay path is a narrow, fail-closed recovery mechanism. It
creates a new unpromoted candidate and cannot repair knowledge, model, policy,
security, or test failures. This release has no supported archive-metadata
repair entrypoint.

See the public [edge container runbook](../docs/public/operations/edge-container-runbook.md)
for network, lineage, recovery, diagnosis, and promotion details.
