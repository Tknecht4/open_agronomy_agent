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
and writes a receipt. The app then starts the backend and opens the browser
workspace using a one-time fragment token. API/model readiness, browser
rendering, and a real answer are separate checks.

Private state is under `~/Library/Application Support/OpenAgronomyAgent/desktop/`:
the SQLite database, artifacts, model cache, receipts, and logs. The installed
app bundle is read-only. Existing checkout and container state are not silently
migrated. The first release is loopback-only; field-LAN remains a separate
operator contract.

## Qualification before merging or distributing

Run the focused desktop/auth tests, the repository's full backend/frontend/docs
gates, a PyInstaller build on a clean macOS 26 arm64 host, and an installed-app
smoke with no Homebrew/Python/Node/Docker dependencies. Exercise model setup,
one real source-bound answer, offline behavior, restart persistence, port
conflicts, Quit cleanup, and bundled file/model identity. Developer ID signing,
notarization, quarantine launch, and an update/rollback path are separate
distribution gates.

The cookie session currently expires after eight hours. The launcher restarts
its owned backend and issues new pairing credentials when **Open workspace** is
used after seven hours; background browser tabs do not renew themselves.
