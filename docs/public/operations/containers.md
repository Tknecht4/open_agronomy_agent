# Container operation

The repository packages one OCI image contract for Apple Container and Docker hosts. Model weights, user state, private records, and the optional Prairie spatial pack are not embedded in the image.

## Status

| Path | Status | Boundary |
|---|---|---|
| Apple Container | Exercised release-builder/native Apple path | A valid image/archive still requires version-specific release evidence |
| Docker Compose | Direct translation consuming the Apple-built archive | Translation tests do not prove every host/network environment |
| Field-LAN | Fail-closed TLS/pairing launch path | Not portable-field proof without separate client/link/power/egress/witness evidence |

Use the repository's [container quick reference](https://github.com/Tknecht4/open_agronomy_agent/blob/main/container/README.md) and [detailed edge runbook](edge-container-runbook.md). Release archives are immutable; repair outputs remain unpromoted until all cold-start, package, browser, translation, and attestation gates pass.
