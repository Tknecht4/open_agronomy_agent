# Mac desktop candidate

The first user target is an Apple Silicon Mac. `Launcher.swift` owns a small
native status window, starts the frozen FastAPI/MLX backend on loopback, checks
the exact child through the health launch ID, and opens the existing production
React workspace in the default browser. `backend.py` handles explicit pinned
model setup, local asset verification, and serving. It never downloads a model
while serving a question.

This is an **unsigned local candidate**, not a distributable release. The
current installed MLX wheels target macOS 26 arm64, so the prototype declares
macOS 26.0 as its minimum until a different dependency set is tested. The
current 16 GiB Apple Silicon machine is an exercised host, not a qualified
minimum memory requirement.

## Build on a clean Apple Silicon builder

Create an isolated Python 3.12 build environment, install
`requirements-macos-app-runtime.txt`, the local package, and
`requirements-macos-app-build.txt`. Install frontend dependencies with
`npm ci`. The builder regenerates `frontend/dist` from the current source.

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -c requirements-macos-app-constraints.txt \
  -r requirements-macos-app-runtime.txt
.venv/bin/python -m pip install -e .
.venv/bin/python -m pip install -r requirements-macos-app-build.txt
cd frontend && npm ci && cd ..
mkdir -p outputs/macos

.venv/bin/python scripts/build_macos_app.py \
  --preflight --python "$PWD/.venv/bin/python" \
  --output "$PWD/outputs/macos/Open Agronomy.app"

.venv/bin/python scripts/build_macos_app.py \
  --python "$PWD/.venv/bin/python" \
  --output "$PWD/outputs/macos/Open Agronomy.app"
```

The output path must not exist. The builder requires at least 8 GiB free as a
conservative scratch estimate, copies only Git-tracked runtime source/assets
plus the freshly built static UI, writes their byte manifest, freezes a Python
backend with PyInstaller, compiles the Swift launcher, and applies ad hoc local
signing. It retains the staging directory on failure. Do not interpret an ad
hoc signature as Developer ID signing or notarization.

## First run and state

Opening the app checks its bundled runtime manifest and the pinned model
receipt. If the model is absent, the user chooses **Install local model**;
setup checks disk, downloads the pinned revision, hashes all snapshot files,
compares them with `configs/model_assets_gemma4_e2b_mlx.json`, and writes a
receipt only after exact agreement. A corrupt cached snapshot is recorded and
force-refetched; it cannot become the new expected version. The app then starts the backend and opens the browser
workspace using a one-time fragment token. API/model readiness, browser
rendering, and a real answer are separate checks.

Private state is under `~/Library/Application Support/OpenAgronomyAgent/desktop/`:
the SQLite database, artifacts, model cache, receipts, and logs. The installed
app bundle is read-only. Existing checkout and container state are not silently
migrated. The first release is loopback-only; field-LAN remains a separate
operator contract. The app keeps one saved loopback port across launches so
browser-local drafts stay on the same origin; a port collision fails with a
retry message instead of silently changing that origin.

## Qualification before merging or distributing

Run the focused desktop/auth tests, the repository's full backend/frontend/docs
gates, a PyInstaller build on a clean macOS 26 arm64 host, and an installed-app
smoke with no Homebrew/Python/Node/Docker dependencies. The CI path first opens
the actual Swift app in empty state and invokes its **Install local model**
button, then checks default-browser pairing, a real model turn, and Quit and
reopen with a persisted session. A separate packaged-backend smoke denies
public TCP/UDP egress at the OS level while keeping loopback available and
requires an offline, source-bound local answer. Exercise port conflicts and
bundled file/model identity as well.
Developer ID signing,
notarization, quarantine launch, and an update/rollback path are separate
distribution gates.

The cookie session currently expires after eight hours. **Reopen and reconnect**
restarts the owned backend and issues fresh pairing credentials, so an expired
or deleted browser cookie can be recovered without quitting the app. This
interrupts any in-flight answer; background browser tabs do not renew themselves.
