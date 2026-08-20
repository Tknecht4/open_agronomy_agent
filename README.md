# Open Agronomy Agent

Open Agronomy Agent is a local-first research system for evidence-grounded Canadian field questions. It combines a downloadable language model, governed retrieval and graph context, structured field history, deterministic capabilities, validation, and an auditable answer trace.

It is **not** an agronomist replacement, diagnostic authority, pesticide-label authority, or proof that a recommendation will work in a field. It is a development system that makes source identity, missing evidence, assumptions, and intervention visible.

> Project-authored contents are licensed under [Apache-2.0](LICENSE). Third-party data, evaluation material, dependencies, and model weights retain their own terms; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Quick start

The exercised local target is an Apple Silicon Mac with 16 GB unified memory. Use Python 3.11 or 3.12 and Node 20 or newer.

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

Model weights are not committed and are never downloaded while answering a question. Provision the exact pinned serving model:

```bash
python scripts/download_model.py \
  --model-config configs/model.yaml
```

The profile currently pins `mlx-community/gemma-4-e2b-it-4bit` at revision `238767527555cb75a05732a84dff5d6ba0dd6809`. That snapshot occupied approximately 3.34 GiB in the exercised local cache; reserve additional disk and unified memory for dependencies, indexes, context, and generation.

Launch the API and React cockpit:

```bash
PYTHONPATH=src python scripts/run_cockpit.py \
  --host 127.0.0.1 \
  --port 8000 \
  --frontend \
  --frontend-port 5173 \
  --model-config configs/model.yaml \
  --rag-config configs/rag.yaml \
  --warm-model
```

Open `http://127.0.0.1:5173`. In another terminal, verify the API itself rather than inferring readiness from the page:

```bash
curl --fail --silent http://127.0.0.1:8000/api/health | python -m json.tool
```

The response must include `"status": "ok"`. Press **Ctrl+C** in the launch terminal to stop the API and frontend. Confirm both listeners are gone:

```bash
lsof -nP -iTCP:8000 -iTCP:5173 -sTCP:LISTEN
```

No output means both development listeners have stopped.

## Need to know

- **Local-first is not automatically offline.** The model, admitted corpus, graph, calculator, history, and traces can run locally. Weather, current labels, regulations, and other live adapters require an authorized connection and must report when unavailable.
- **Regional data is not field truth.** Soil maps, statistics, and historical guidance are priors. They do not replace representative samples, current observations, verified geometry, or local calibration.
- **Private state stays local by default.** Runtime databases, traces, model caches, raw benchmark answers, private overlays, and generated spatial databases are excluded from Git and the documentation site.
- **Consequential decisions need authority.** Confirm current labels and regulations and involve a qualified local professional when a decision carries material agronomic, legal, environmental, safety, or financial consequences.
- **Knowledge is cumulative but explicitly admitted.** The active offline profile contains source-exact Canadian evidence, project policy, and SoilWise context. A 218,258-row USDA NRCS pack is available only for an explicit MLRA-scoped U.S. analogue request; it never establishes Canadian decisive authority. Adding a file does not make it model-visible; source rights, policy, registry admission, and corpus validation remain required.
- **Benchmark claims are bounded.** RC1 and RC2 are frozen historical development identities. The completed RC3 development checkpoint contains 8,676 observations, but only 49 of 241 cases per arm have a defined deterministic score. Its later Luna semantic review is advisory instrumentation, not agronomist ground truth or a model leaderboard; sealed successor evaluation remains blocked on an independent held-out retrieval suite and release gates.
- **Optional assets remain explicit.** Public adapters need provider/network availability; the Prairie spatial pack is a separately built local asset; unavailable capabilities must not be simulated.

## Documentation

- [Documentation home](docs/public/index.md) and the future [GitHub Pages site](https://tknecht4.github.io/open_agronomy_agent/)
- [System architecture](docs/public/architecture.md)
- [Knowledge and evidence governance](docs/public/knowledge-and-data.md)
- [Tools and adapters](docs/public/tools-and-adapters.md)
- [Evaluation contract](docs/public/evaluation.md)
- [RC3 development benchmark checkpoint and paper](docs/public/development-benchmark-rc3-20260815/README.md)
- [Academic benchmark and system review](docs/reviews/open-agronomy-benchmark-system-review-20260813.md)
- [Upgrade implementation record](docs/reviews/open-agronomy-upgrade-implementation-20260813.md)
- [Historical benchmark RC2 readiness record](docs/reviews/open-agronomy-benchmark-rc2-readiness-record-20260814.md)
- [Developer guide](docs/public/developer/index.md)
- [Release-candidate checkout gates](docs/public/developer/release-readiness.md)
- [Native operations](docs/public/operations/native-setup.md), [offline operation](docs/public/offline-operation.md), and [containers](container/README.md)

Subsystem extension contracts live beside the code: [Python package](src/agronomy_agent/README.md), [server](src/agronomy_agent/server/README.md), [Agno runtime](src/agronomy_agent/agno_runtime/README.md), [tools](src/agronomy_agent/tools/README.md), [frontend](frontend/README.md), [configuration](configs/README.md), [data](data/README.md), [manifests](data/manifests/README.md), [scripts](scripts/README.md), and [tests](tests/README.md).

## Verify changes

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q
PYTHONPATH=src .venv/bin/python scripts/check_public_docs.py

cd frontend
npm run typecheck
npm test
npm run build
```

A focused check proves only its named contract. Do not describe a partial test run as full-system, field, agronomist, or release validation.

Before a benchmark release candidate, use the [clean-checkout and environment-receipt procedure](docs/public/developer/release-readiness.md). Most Python dependencies are range-declared; the RC3 analysis file pins its direct plotting dependencies, and the generated receipt records the exact exercised environment. Neither is a complete portable lock.
