# Local browser setup

## Prerequisites

- Apple Silicon Mac; the exercised target has 16 GB unified memory.
- Python 3.11 or 3.12.
- Node 24 LTS.
- At least several additional GiB of disk for the model, dependencies, local indexes, and runtime state.

## Install

Clone the repository, then install from its root:

```bash
git clone https://github.com/Tknecht4/open_agronomy_agent.git
cd open_agronomy_agent
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -e .

cd frontend
npm ci
cd ..
```

On this local runtime, install a model from **Questions → Model settings** after launch. Click the download button beside Gemma 4 E2B (3.6 GB) or Gemma 4 E4B (5.2 GB). The app verifies the pinned files before enabling the model. Downloads require a connection and free space in the local model cache.

To provision the default model from a terminal:

```bash
python scripts/download_model.py \
  --model-config configs/model.yaml
```

The default profile pins `mlx-community/gemma-4-e2b-it-4bit` at revision `238767527555cb75a05732a84dff5d6ba0dd6809`. The optional profile uses the `mlx-community/gemma-4-e4b-it-4bit` revision `475b9088d29754a3379866cf5aeb6b41acd313c2` from the frozen benchmark.

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
  --model-config configs/model.yaml
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

- **Model setup required:** open **Model settings** and click the download button. After verification, select the model and send your question. If the download reports a storage or connection error, resolve it and click the button again.
- **Page loads but questions fail:** check `/api/health` and the API listener independently.
- **Port occupied:** inspect `lsof` output and stop the owning development process or choose different ports.
- **Adapter blocked:** check network mode, credential/provider readiness, and source timestamp. Do not substitute a stale/current-looking value.
- **Prairie layer unavailable:** follow [compact offline data setup](offline-data-setup.md) to install and verify the external DSS pack, or continue with the reported `not_installed` boundary.

## Field location and imagery

Set up field services once in a private directory outside the checkout. Build the
boundary pack with the cockpit Python environment and the dependencies in
`requirements-geospatial.txt`. It installs pinned Canadian province and
municipality boundaries, Alberta municipal districts, and U.S. states and
counties. The lookup runs locally after installation.

```bash
FIELD_SERVICES="$HOME/Library/Application Support/OpenAgronomyAgent/field-services"
.venv/bin/python -m pip install -r requirements/requirements-geospatial.txt
PYTHONPATH=src .venv/bin/python scripts/setup_offline_data.py \
  --profile field-location-v1 --data-root "$FIELD_SERVICES" \
  --download --build --verify
python3.12 -m venv "$FIELD_SERVICES/imagery"
"$FIELD_SERVICES/imagery/bin/python" -m pip install -r requirements/requirements-geospatial.txt
PYTHONPATH=src .venv/bin/python scripts/run_cockpit.py \
  --frontend --field-services-root "$FIELD_SERVICES"
```

On macOS the browser launcher discovers this directory on later launches. Pass
`--field-services-root` for a custom directory. The spatial pack, worker and
imagery cache use `spatial-pack/field-location-v1`, `imagery/bin/python` and
`cache/imagery` under that root. Set `AGRONOMY_AGENT_ADMINISTRATIVE_PACK_ROOT`,
`AGRONOMY_AGENT_IMAGERY_PYTHON`, or `AGRONOMY_AGENT_IMAGERY_CACHE_ROOT` to
configure those locations individually. The Prairie soil pack has its own
[setup instructions](offline-data-setup.md).

In **Imagery**, choose **Analyze date range** to search Sentinel-2 and Landsat
and calculate NDVI and NDMI. Select a chart point to load its index on the field
map or choose **Preview image** for true color. Preview and analysis use a
private cache. Check the worker setup from the Imagery pane when controls are
unavailable.
