# Edge container runbook

This runbook supplements `container/README.md`. It describes the stable operational boundary; exact image versions, hashes, and release gates come from the selected release manifest.

## Prerequisites

- Apple Silicon host with Apple Container for the release-builder path, or Docker Desktop for translated runtime operation.
- A previously built and validated versioned `linux/arm64` OCI archive.
- Native MLX model host with the exact pinned model already provisioned.
- Free loopback ports and sufficient disk for the archive, model, image layers, and profile state.
- For field-LAN: operator-controlled private IPv4 address, trusted TLS certificate/key whose SAN covers the advertised host, separate client, and explicit physical/network controls.

## Build and seal

Apple Container is the release builder:

```bash
./container/release.sh VERSION
```

The versioned output under `outputs/releases/open-agronomy-agent-VERSION/` must contain the archive, checksum file, release manifest, and validation evidence. Do not overwrite or relabel it.

## Apple Container

```bash
./container/apple.sh setup-network
./container/apple.sh doctor PROFILE
./container/apple.sh import VERSION
AGRONOMY_AGENT_IMAGE=open-agronomy-agent:VERSION \
  ./container/apple.sh start PROFILE
```

Open `http://127.0.0.1:8080/`. Stop the complete profile:

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

`up` consumes an imported archive and does not build. Inspect translation without starting it:

```bash
./container/docker.sh config PROFILE
```

Stop the profile:

```bash
./container/docker.sh stop PROFILE
```

## Field-LAN

Provide a trusted certificate directory containing `tls.crt` and mode-`0600` `tls.key`, then use `container/apple.sh start-field-lan` with explicit bind/advertise host and port variables as shown in `container/README.md`. Use the one-time pairing link only on the prepared client. Never bypass a certificate warning or store the pairing URL in evidence.

Stopping the profile invalidates the in-memory session secret. Passing the launcher checks does not prove portable-field operation. That requires the separately signed/witnessed portable runtime receipt and blocked public egress.

## State and networks

- The application binds to loopback in normal desktop/container mode.
- Profile state mounts at `/state`; profiles isolate accounts, fields, chats, feedback, and artifacts.
- The native Metal model service is shared but retains only model-host process/log state.
- Extract the optional Prairie pack under the profile host-state `spatial-pack/` so it appears at `/state/spatial-pack`.
- The image declares geospatial content class `lineage_manifests_only` and
  `runtime_layer_assets_included=false`; the selected offline profile manifest,
  install receipt, and validator are the authority for installed layer bytes.
- Field-LAN uses an explicit no-public-egress network and HTTPS.

## Recovery and promotion

Overlay builds are the implemented narrow, fail-closed recovery path. They
create a new immutable candidate and cannot repair knowledge, model, policy,
security, or test failures. After an overlay build, import under a new version
and rerun the full release/package/cold-start/browser/translation/attestation
gates before promotion. There is no supported archive-metadata repair
entrypoint in this release.

Use an already sealed local image as an overlay base only when its embedded
runtime contract matches and the change is confined to the declared code,
frontend, script, and release-control trees:

```bash
AGRONOMY_AGENT_IMAGE_BUILD_MODE=overlay \
AGRONOMY_AGENT_BASE_IMAGE=open-agronomy-agent:PREVIOUS_VERSION \
AGRONOMY_AGENT_BASE_RUNTIME_CONTRACT_SHA256=PREVIOUS_CONTRACT_SHA256 \
  ./container/release.sh NEW_VERSION
```

## Verify and diagnose

1. Check the release manifest and SHA-256 for the exact archive.
2. Run the engine-specific `doctor` command.
3. Confirm only the intended bind/listener and profile are active.
4. Check the application health endpoint inside the exposed UI path.
5. Confirm the model-host identity/revision and corpus/runtime manifests.
6. Exercise one UI and one API question path separately.
7. Stop the profile and confirm listeners/state ownership.

Do not delete VM/cache, images, archives, or profile state outside the exact release script/recovery contract. Preserve failed evidence for diagnosis.
