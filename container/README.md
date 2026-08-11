# Open Agronomy Agent Containers

This package has one OCI image contract and two host runtimes:

- **Apple Container** is the exercised macOS and Apple silicon release.
- **Docker Compose** is the direct translation for Docker Desktop and other
  Docker hosts.

Both launchers build the same staged context from `Containerfile`, publish the
normal desktop app only on `127.0.0.1:8080`, mount profile state at `/state`,
and call the same native OpenAI-compatible MLX model service. Apple Container
also has an explicit fail-closed field-LAN mode described below. Model weights
and user data are not included in the image.

The optional Prairie spatial pack is also outside the image. Verify it with
`scripts/build_prairie_spatial_pack.py --verify-only` and
`scripts/verify_prairie_spatial_pack.py`, then extract it to `spatial-pack/`
inside the selected profile's host state directory. Both launchers expose that
directory to the app as `/state/spatial-pack`.

## Release state

Versioned OCI archives are immutable. Do not relabel or overwrite one after it
has been exported. The authoritative version, archive hash, OCI index digest,
runtime-contract hash, source counts, and engine parity record live beside each
archive in `outputs/releases/open-agronomy-agent-VERSION/`. Keeping those values
out of this in-image control file avoids a self-referential release digest.

The launchers record the native model-host configuration and restart it when
switching between Apple's loopback bind and Docker's host bridge bind. Corpus,
model-control, and geospatial promotion decisions are release-specific and must
be read from that version's manifest and review packet.

## Portable release

Apple Container is the release builder. This command builds, validates, and
seals one versioned `linux/arm64` OCI archive for both runtimes:

```bash
./container/release.sh VERSION
```

The output is written under `outputs/releases/open-agronomy-agent-VERSION/`
and includes `SHA256SUMS`, `release_manifest.json`, package validation, and OCI
blob/contract validation. Before export, the release workflow stops and
deletes only Apple Container's disposable builder VM/cache. This leaves the
completed image and all application/user state intact while avoiding the
internal-disk pressure that can otherwise break the final archive write.
Import the same archive into either engine:

When internal disk headroom cannot support a second full dependency build, a
release may use a previously sealed local image as a base. The overlay path is
fail-closed: it compares the base image's embedded runtime manifest with the
current manifest and permits changes only in the declared backend, frontend,
script, and release-control trees. It replaces those trees completely, updates
the OCI lineage labels, and then runs the same package, translation, archive,
SBOM, readiness, and checksum workflow:

```bash
AGRONOMY_AGENT_IMAGE_BUILD_MODE=overlay \
AGRONOMY_AGENT_BASE_IMAGE=open-agronomy-agent:PREVIOUS_VERSION \
AGRONOMY_AGENT_BASE_RUNTIME_CONTRACT_SHA256=PREVIOUS_CONTRACT_SHA256 \
  ./container/release.sh NEW_VERSION
```

This is a standard OCI image build from a named immutable base, not an archive
rewrite. Any knowledge, policy, model, geospatial, benchmark, configuration, or
undeclared asset drift aborts before the new image is built.

### Rejected-overlay archive recovery

`scripts/repair_edge_oci_archive.py` is a narrow incident-recovery path for an
otherwise valid Apple Container archive that fails only because an overlay
build dropped the inherited `8080/tcp` port and `/state` volume metadata. It
refuses every other input-validation failure and refuses to overwrite its
input or an existing output. The tool appends one deterministic opaque layer
containing the complete current backend, frontend build, script, and container
trees; embeds the current runtime manifest; restates the runtime metadata; and
validates every referenced OCI blob before writing a new archive.

```bash
./scripts/repair_edge_oci_archive.py \
  --input /absolute/path/to/rejected.oci.tar \
  --output /absolute/path/to/NEW_VERSION.oci.tar \
  --version NEW_VERSION \
  --receipt outputs/current_source_readiness_20260725/oci_archive_repair_NEW_VERSION.json
```

The resulting archive is still unpromoted. Import it under its new immutable
version and run the exact cold-start, offline-asset, packaged workflow, browser,
translation, and attestation gates before building a release manifest. This
recovery path must never be used to relabel a passing archive or to bypass a
failed source, knowledge, model, policy, security, or test gate.

```bash
container image load --input outputs/releases/open-agronomy-agent-VERSION/open-agronomy-agent-VERSION-linux-arm64.oci.tar
docker load --input outputs/releases/open-agronomy-agent-VERSION/open-agronomy-agent-VERSION-linux-arm64.oci.tar
```

Launch the imported version explicitly by setting
`AGRONOMY_AGENT_IMAGE=open-agronomy-agent:VERSION` for either launcher.
On Docker Desktop versions that import Apple's nested OCI index without a
name-resolvable tag, `docker.sh start` normalizes that existing digest locally
before Compose starts. It does not rebuild or modify the image bytes.

## Apple Container quick start

```bash
./container/apple.sh setup-network
./container/apple.sh doctor conference-rehearsal
./container/apple.sh import 0.1.0-rc13
AGRONOMY_AGENT_IMAGE=open-agronomy-agent:0.1.0-rc13 \
  ./container/apple.sh start conference-rehearsal
```

Use the explicit `apple.sh build` or `apple.sh up` commands only for source
development. The versioned import/start path is the exercised local release.

Open `http://127.0.0.1:8080/`. Stop the complete local stack with:

```bash
./container/apple.sh stop conference-rehearsal
```

### Sealed field-LAN mode

`start-field-lan` exposes the same imported image only on one operator-selected
private IPv4 address, forces the internal no-public-egress network, serves
HTTPS from the container, disables anonymous local-development auth, and
generates a new one-time pairing link on every launch.

Prepare a directory containing `tls.crt` and a mode-`0600` `tls.key`. The
certificate must already be trusted by the separate client and its subject
alternative name must cover the advertised host. Then run:

```bash
AGRONOMY_AGENT_IMAGE=open-agronomy-agent:VERSION \
AGRONOMY_AGENT_FIELD_LAN_BIND_ADDRESS=192.168.50.10 \
AGRONOMY_AGENT_FIELD_LAN_ADVERTISE_HOST=field-runtime.example.local \
AGRONOMY_AGENT_FIELD_LAN_TLS_DIR=/absolute/path/to/field-lan-tls \
AGRONOMY_AGENT_FIELD_LAN_PORT=8443 \
  ./container/apple.sh start-field-lan field-rehearsal
```

Open only the one-time pairing link printed by the launcher. Do not bypass a
certificate warning or retain the pairing URL in evidence. Stop the profile to
invalidate its in-memory session secret:

```bash
./container/apple.sh stop field-rehearsal
```

This supplies a sealed-runtime launch path; it is not portable-field proof.
A distinct field client, controlled local link, portable power, blocked public
egress and independent witness must still produce the governed receipt in
`data/manifests/field_offline_portable_runtime_receipt_schema_v2.json`. The
current auditor requires semantic validation of seven evidence types plus
distinct operator and witness Ed25519 signatures; a hash-only v1 receipt is
historical evidence and cannot clear the gate.

## Docker quick start

Start Docker Desktop, then run:

```bash
./container/docker.sh doctor conference-rehearsal
./container/docker.sh import 0.1.0-rc13
AGRONOMY_AGENT_IMAGE=open-agronomy-agent:0.1.0-rc13 \
  ./container/docker.sh up conference-rehearsal
```

`up` never builds under Docker. It starts an image already imported from the
Apple-built release archive, preserving the direct-translation contract. The
explicit `docker.sh build` command is reserved for local packaging development
and is not a release path.

The translated Compose model can be inspected even while Docker Desktop is
stopped:

```bash
./container/docker.sh config conference-rehearsal
```

The Docker runtime uses the same URL and profile data. Stop it with:

```bash
./container/docker.sh stop conference-rehearsal
```

## Profile and model state

Accounts, fields, chats, feedback, and artifacts are isolated by runtime
profile. The native Metal model is shared across profiles and keeps only its
PID and logs under the model-host state directory. Override paths and ports in
`container/.env` using `container/.env.example` as the reference.

See `docs/edge_container_runbook.md` for prerequisites, network details,
lineage verification, recovery, and release evidence.
