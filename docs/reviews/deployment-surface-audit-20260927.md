# Deployment surface audit and Mac-first release plan

**Source:** `main` at `fd590b57babca0666e24286315ec460877a59dac` (verified as live `origin/main` on 2026-09-27)

**Review branch:** `codex/deployment-surface`

**Date:** 2026-09-27

**Current target:** A user with an Apple Silicon Mac installs the app, opens it, and gets local answers without Git, Python, Node, Docker, or a terminal. Windows and Linux are deferred.

## Decision

Make a native macOS `.app` the only user-facing deployment surface for the first release. Retain the React workspace, FastAPI product path, pinned MLX model, governed corpus, and local data policy. The app owns startup, first-run model provisioning, readiness, the browser workspace, and shutdown. An app icon that starts the local service and opens the workspace in the user's browser meets the first interaction goal; an embedded webview can wait.

Do not make Docker Compose the first user runtime. It packages the API and UI but still needs a separate native MLX server on the Mac. The current Docker path also imports an Apple Container-built `linux/arm64` archive, so choosing Docker would not remove Apple from the release path. Freeze the container launch paths while the Mac app is proved. Historical receipts remain intact. The first desktop scope is one Mac on loopback; field-LAN requires a separate migration or later release.

## Observed reference state

| Area | Observation on `main` | Mac-first implication |
|---|---|---|
| Native path | `scripts/run_cockpit.py` runs FastAPI and optionally Vite. `requirements.txt` includes MLX, and `configs/model.yaml` pins the Gemma 4 E2B MLX snapshot. | Reuse the working local inference path. No model conversion is needed to solve packaging. |
| Production UI | `Containerfile` builds React static assets; FastAPI serves them with `AGRONOMY_AGENT_STATIC_DIR` or `--static-dir`. | Bundle the built UI; do not run npm or Vite in the installed app. |
| Container paths | `container/release.sh` builds with Apple Container; `container/docker.sh` consumes its archive through Compose; both use native host MLX. | Two engine launch and support paths are redundant for the intended single-user Mac app, but active checks still name them. |
| Field-LAN | `container/apple.sh` provides `start-field-lan`; `scripts/audit_field_offline_topology.py` names it. | Keep the operator path until a native replacement is qualified or field-LAN is explicitly deferred. |
| PWA | `frontend/public/manifest.webmanifest` and `service-worker.js` cache the browser shell, not the API or model. | Retain useful offline draft behavior; PWA installation alone does not install the product. |
| Assets | The repository tracks about 988 MiB of data; the documented model snapshot occupied about 3.34 GiB. `scripts/download_model.py` defaults to a checkout-local cache. | Installation needs a disk check, user-data paths, verified assets, and visible first-run download progress. |

The recent Apple image build recorded in `docs/reviews/repository-cleanup-investigation-20260926.md` exited nonzero with `ENOSPC`; it was not a completed final-source release. During this review the host had about 2.2 GiB free, Docker's daemon was stopped, its Compose plugin was absent, and Apple Container status failed with an operation-permitted error. No new image or installer was built.

## What can be simplified

1. **One user product:** the Mac app. Stop presenting Apple Container and Docker Compose as equally supported end-user starts.
2. **One model path:** native MLX with the exact active model revision. A cross-platform model port is no longer on the first-release critical path.
3. **One production UI:** a static React build served by FastAPI. The Vite launcher remains a maintainer command.
4. **Governed assets remain bound:** the corpus is a runtime asset and frozen receipts are evidence. Use a verified distribution before removing checked-in data.

## First implementation milestones

1. **Production-style native start.** Build the frontend, launch FastAPI with `--static-dir` and the pinned MLX model, then verify the UI, `/api/health`, one real source-bound answer, and clean shutdown independently. Record exact model, corpus, and runtime identities.
2. **Unsigned app prototype.** Bundle Python, MLX dependencies, backend, static UI, and admitted corpus behind a small macOS launcher. On open it owns one loopback-only backend, waits for readiness, shows setup or errors, and opens the workspace without a terminal. It stops only processes it owns. A status/setup window is enough; an embedded browser window is optional.
3. **Understandable first run.** Put private fields, SQLite data, traces, logs, and caches in the user's Application Support directory. Ask before downloading the pinned model, check free space, verify exact bytes, and show progress and retry. Never download while answering. Keep optional spatial packs separate and verified.
4. **Release candidate.** Establish the Apple Silicon, macOS, memory, and disk floor from measured clean-host runs. On a Mac without developer tools, test install, open, provision, a real answer, offline behavior, quit, reopen, update without data loss, and listener cleanup. Public distribution then needs Developer ID signing and notarization; see [Apple's distribution guidance](https://developer.apple.com/developer-id/).
5. **Retire old launch support separately.** After the app works, lead public setup guidance with the installer. Remove Apple/Docker user launch code only after replacing active release and field-LAN consumers, refreshing generated manifests, and running owning gates. Preserve historical receipts byte-for-byte.

## Acceptance and residuals

The next reviewable artifact is an **unsigned local Mac app prototype** that opens the production UI and completes a real model-backed question without Python, Node, Git, Docker, or a terminal installed on the test Mac. That proves packaging and lifecycle, not agronomic quality or public-release readiness.

This branch records a source audit and decision, not a working installer. The native model path has been exercised on an Apple Silicon Mac with 16 GiB unified memory, but that is not a measured minimum for users. More free disk is needed before packaging and clean-install trials.
