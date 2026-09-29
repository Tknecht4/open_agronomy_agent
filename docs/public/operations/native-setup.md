# Native setup and operation

## Prerequisites

- Apple Silicon Mac; the exercised target has 16 GB unified memory.
- Python 3.11 or 3.12.
- Node 24 or newer.
- At least several additional GiB of disk for the model, dependencies, local indexes, and runtime state.

## Install

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -e .

cd frontend
npm ci
cd ..
```

Provision the pinned model explicitly:

```bash
python scripts/download_model.py \
  --model-config configs/model.yaml
```

The profile pins `mlx-community/gemma-4-e2b-it-4bit` revision `238767527555cb75a05732a84dff5d6ba0dd6809`. The exercised snapshot occupied approximately 3.34 GiB in the local Hugging Face cache. The download command requires network access; question answering never triggers it.

Prompt KV caching remains disabled by default. Its bounded, conversation-scoped
implementation is experimental: a CUDA diagnostic observed saved-prefix reuse
but different cached and uncached answer text. A cache hit therefore does not
establish answer equivalence or a speed benefit. Qualify a pinned model, backend,
and cache configuration before enabling it. The non-active 27B diagnostic profile
is not a claim that the model fits a particular laptop; weights, KV state, working
memory, and other applications share the available memory.

## Launch

```bash
PYTHONPATH=src python scripts/run_cockpit.py \
  --host 127.0.0.1 \
  --port 8000 \
  --frontend \
  --frontend-port 5173 \
  --model-config configs/model.yaml \
  --warm-model
```

Open `http://127.0.0.1:5173`.

## Verify UI and API separately

```bash
curl --fail --silent http://127.0.0.1:8000/api/health | python -m json.tool
curl --fail --silent --output /dev/null http://127.0.0.1:5173/
```

The API JSON must include `"status": "ok"`; this proves application health/configuration, not successful model generation or public-provider availability. Ask one low-risk question and inspect its source/trace before treating the answer path as exercised.

## Stop

Press **Ctrl+C** in the launch terminal. Verify the backend and Vite listener are gone:

```bash
lsof -nP -iTCP:8000 -iTCP:5173 -sTCP:LISTEN
```

If a development process remains, inspect the reported PID/command and terminate that exact process. Do not use a broad process-name kill that could stop unrelated work.

## Troubleshooting

- **Model setup required:** rerun the pinned download and restart the API. Missing or incomplete model files are checked when the model loads, including lazy loading for a question. Chat reports the setup error without saving a substitute answer; it does not download model files automatically.
- **Page loads but questions fail:** check `/api/health` and the API listener independently.
- **Port occupied:** inspect `lsof` output and stop the owning development process or choose different ports.
- **Adapter blocked:** check network mode, credential/provider readiness, and source timestamp. Do not substitute a stale/current-looking value.
- **Prairie layer unavailable:** follow [compact offline data setup](offline-data-setup.md) to install and verify the external DSS pack, or continue with the reported `not_installed` boundary.
