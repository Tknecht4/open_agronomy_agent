# Deployment surface audit and first desktop release plan

**Source:** `main` at `fd590b57babca0666e24286315ec460877a59dac` (also verified as live `origin/main` on 2026-09-27)

**Review branch:** `codex/deployment-surface`

**Date:** 2026-09-27

**Requested outcome:** An ordinary user on macOS, Windows, or Linux opens an installed app and gets local inference, without cloning the repository or running commands.

## Decision

Make an installable desktop app the **single user-facing deployment surface**. Keep the React UI, FastAPI application, evidence policy, and local data contract. Bundle the production frontend and backend in per-OS installers and have the app own the local model process. A single cross-platform inference implementation, such as a pinned `llama.cpp` build and a qualified GGUF model, is the leading candidate, **not an approved replacement** for the current MLX model. The model, quantization, prompt/template behavior, response trace, speed, and quality must be measured on each target before selecting it.

Stop extending Apple Container and Docker Compose as parallel user launch paths. Freeze their current contracts while the replacement is built; retire them only after a tested replacement covers their active consumers, including field-LAN or an explicit decision to defer that capability. Historical receipts stay immutable. Docker may remain an internal integration/build tool, but would no longer be an advertised way for an end user to run the product.

## Observed reference state

| Area | Observation on `main` | Consequence |
|---|---|---|
| Native development | `scripts/run_cockpit.py` runs FastAPI and optionally a Vite development server; `requirements.txt` includes `mlx-lm` and `mlx-vlm`. | The documented local start still requires Python, npm, model provisioning, and a terminal. Vite is a development tool, not a release runtime. |
| Production web app | `Containerfile` builds the React app and FastAPI serves the resulting static files via `AGRONOMY_AGENT_STATIC_DIR`. | The user interface can be reused in a desktop package without a runtime Node dependency. |
| Model | `configs/model.yaml` pins `mlx-community/gemma-4-e2b-it-4bit` and a specific revision. The native product defaults to MLX; the image uses `mlx_http` to call `container/model-host.sh` on the Mac. | The OCI image does not contain the model or a portable inference engine. A Docker-only switch cannot deliver local answers on all three OSes. |
| Container release | `container/release.sh` requires Apple Container to build/export the reference `linux/arm64` archive. `container/docker.sh` imports and runs that archive through Compose. `scripts/validate_edge_runtime_translation.py` compares Docker with the Apple runtime. | The two engines are one image contract but two launch/release/support paths. Docker is currently downstream of Apple, not an independently qualified release builder. The current ARM image is also not a qualified native x86-64 Windows/Linux artifact. |
| Field use | `container/apple.sh` has `start-field-lan`; `scripts/audit_field_offline_topology.py` names that launcher. | Deleting Apple files now would break a declared capability and its evidence path. |
| PWA | `frontend/public/manifest.webmanifest` and `frontend/public/service-worker.js` install/cache the browser shell and exclude private API routes. | An installed PWA does not start FastAPI or run the local model. It cannot satisfy the requested install experience by itself. |
| Assets | The repository architecture records about 988 MiB of tracked data. The current Mac model snapshot is documented at about 3.34 GiB. `scripts/download_model.py` defaults to a repository-local cache. | Model and corpus distribution, first-run space checks, progress, checksums, and user-data placement are central release work. |

The most recent recorded Apple image build registered a runnable image but exited nonzero with `ENOSPC`; it was **not** a successful final-source release export (`docs/reviews/repository-cleanup-investigation-20260926.md`). During this review, the host had about 2.2 GiB available, Docker's daemon was unavailable, the installed Docker CLI lacked the Compose plugin, and Apple Container status returned an operation-permitted error. The Docker translation validator exited with status 1: `docker compose config` exited 125 because `docker compose` was unavailable. No image build, cold start, or cross-OS model run was performed here.

## What is redundant, and what is not

The **support obligation** for two container engines is the primary redundancy: `container/apple.sh` and `container/docker.sh`, both import commands, Apple-to-Docker translation validation, engine-specific documentation, and release parity fields in `scripts/build_edge_container_release.py`. They do not duplicate the application implementation, and they cannot be removed with a script deletion alone. `scripts/build_edge_runtime_manifest.py`, `scripts/validate_edge_container_package.py`, `scripts/build_portable_agent_bundle.py`, public package selection, tests, and runbooks name these paths.

The native development launcher and production static frontend serve different purposes. The PWA shell provides browser caching and offline drafts, not local generation. The governed corpus, frozen benchmark outputs, and release receipts are evidence or runtime assets, not excess copies to delete for a smaller checkout. The 988 MiB data distribution issue needs a verified, content-addressed replacement before removal.

## Options against the requested experience

| Option | User steps after download | Local inference on all three OSes | Assessment |
|---|---|---|---|
| Docker Compose as the only runtime | Install/start Docker, import or build image, install/provision a separate model host, run launcher | Not with the current MLX host and image | Useful for operators, but does not meet “open it.” Docker Desktop documents Mac container GPU support as unavailable; the current Mac model therefore stays outside the container. |
| PWA alone | Open/install website | No | Retain as a client feature; backend and model lifecycle still need an owner. |
| Desktop installer owning local services | Install, open, consent to first-run model download | Possible after model/runtime qualification on each OS | Recommended user surface. Packaging and cross-platform model evidence are the largest work items. |

Official references: [Docker Desktop GPU support](https://docs.docker.com/desktop/features/gpu/), [Docker Desktop license terms](https://docs.docker.com/subscription-billing/desktop-license/), [`llama.cpp` supported backends](https://github.com/ggml-org/llama.cpp), [Tauri sidecar packaging](https://v2.tauri.app/develop/sidecar/), and [Apple Developer ID distribution](https://developer.apple.com/developer-id/). These establish available mechanisms, not this project's runtime or quality readiness.

## Smallest proof that resolves the model uncertainty

1. Freeze one local model candidate and its exact source/quantized bytes, prompt template, inference binary, settings, license, and target hardware. `llama.cpp` is a candidate because it exposes an OpenAI-compatible server and has Metal, CPU, CUDA, and Vulkan backends; it has not been qualified for this application.
2. Run the existing product request path on the candidate through `OpenAICompatibleGenerator` on one Mac, one Windows machine, and one Linux machine. Compare full answers **and** 17-stage traces, selected evidence, verifier/fallback behavior, citation integrity, refusals, and deterministic-tool results with the MLX reference. Record latency, memory, cold start, and repeated-run variation separately. Do not transfer the current Gemma/MLX benchmark claims to new weights or a new engine.
3. Establish the supported hardware floor from measurements. OS support alone does not establish usable local inference on low-memory or CPU-only machines. If no candidate meets the product gate on all three, the first cross-platform local release is blocked; keep the existing Mac development path rather than silently substituting a cloud model.

## Implementation sequence after that gate

1. **Package the existing app path.** Produce the React static build, package FastAPI and dependencies, and run both under a desktop supervisor. Tauri with bundled sidecars is one candidate shell; select it after a minimal launch/shutdown spike. Keep `execute_agent_request` as the production seam.
2. **Own the entire lifecycle.** On click, start or reconnect to one loopback-only backend and model process, wait for separate API/model readiness, show useful setup and error states, open the workspace, and stop owned processes on quit. Use an app-held token for local HTTP access and avoid exposing model endpoints to the LAN by default.
3. **Make first run explicit.** Check OS/architecture, memory and disk; download only user-approved, pinned model assets into an OS user-data directory; verify hashes; show progress and resumable failure. Never initiate a model download while answering a question. Keep private fields, databases, traces, and caches outside the installed program directory; preserve them across updates.
4. **Package and verify assets.** Supply the admitted corpus and static UI with manifests; migrate the repository-local model cache carefully. Support optional spatial packs as separately verified downloads. Produce per-OS signed installers and an update/rollback path; document third-party licenses and user-data removal.
5. **Prove a clean-user path on every OS.** On fresh supported hosts, install without Python, Node, Git, or Docker; open the app; perform first-run provisioning; get one real source-bound answer; disconnect the network and observe the correct offline state; quit/reopen; upgrade without losing private data; verify model/corpus identity and that owned listeners stop. Keep release and agronomic-quality claims separate.
6. **Retire old launch surfaces in a separate change.** Replace active field-LAN and offline audit consumers or explicitly defer them, update the runtime manifest and public package, remove active Apple/Docker launch directions, and run the owning tests and release gates. Preserve historical evidence byte-for-byte.

## Acceptance and current limits

A reviewable next implementation milestone is an **unsigned local prototype** that launches a bundled production UI and backend on all three OSes using a pinned model candidate, with an exact receipt for every host. That proves packaging and process ownership only. User release requires the model qualification, clean-host setup test, security/upgrade checks, and platform signing above.

This branch records a source audit and recommendation. It does not change runtime selection, claim Docker parity, certify cross-platform model quality, remove launchers, or produce an installer. The next discriminating evidence is the cross-platform model/runtime spike; the current host's free space, inactive Docker daemon, and missing Compose plugin preclude a meaningful container build and validation here.
