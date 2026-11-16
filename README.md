# Open Agronomy Agent

**A local-first GIS workspace for agronomy.** Map a field, ask a question, and inspect the evidence behind the answer. The application brings field maps, local-agent conversations, deterministic calculations, and private field records into one workspace.

**Source-available for non-commercial use, including research and evaluation, under [PolyForm Noncommercial 1.0.0](LICENSE).** Its standard institutional permissions also apply. See [licensing and permitted use](docs/public/licensing.md).

![Desktop workspace with a demonstration field, conversation, and full map](docs/public/assets/workspace-desktop.jpg)

A synthetic demonstration field and a deterministic calculation in the desktop workspace. Geometry is illustrative; mapped context is not a field measurement.

[Workspace guide](docs/public/operations/workspace.md) · [Setup](docs/public/operations/native-setup.md) · [Customize the agent](docs/public/developer/customizing-the-harness.md)

## Explore the workspace

- **Map and explore:** draw or import a boundary, choose satellite or street maps, compare mapped layers, and inspect field geometry and coverage.
- **Ask and inspect:** work with the pinned local model and typed tools, then open sources, assumptions, missing evidence, and the answer trace.
- **Keep field records:** save dated observations and soil tests, review imported tables, and attach private references.
- **Extend the system:** add registered capabilities, admitted sources, or model profiles through the React/FastAPI foundation and governed retrieval pipeline.

## Get started

The exercised source-checkout target is an Apple Silicon Mac with Python 3.11 or 3.12 and Node 24 LTS. Follow [native setup](docs/public/operations/native-setup.md) to install dependencies and explicitly provision the pinned model, then launch:

```bash
PYTHONPATH=src .venv/bin/python scripts/run_cockpit.py \
  --host 127.0.0.1 --port 8000 \
  --frontend --frontend-port 5173 \
  --model-config configs/model.yaml --warm-model
```

Open <http://127.0.0.1:5173>. Stop with **Ctrl+C**. Setup, health checks, storage, and recovery details stay in the [operator guide](docs/public/operations/native-setup.md).

The active document and graph corpus is included. Optional Prairie soil maps use a separately verified [offline spatial pack](docs/public/operations/offline-data-setup.md); unavailable coverage is reported explicitly.

The [Mac app candidate](macos_app/README.md) bundles the workspace and runtime, but is not yet a notarized, downloadable release.

## Build and contribute

Start with the [architecture](docs/public/architecture.md), [customization guide](docs/public/developer/customizing-the-harness.md), and [release-readiness checks](docs/public/developer/release-readiness.md). The supported product path enters through `server/app.py` and `server/services/chat_service.py::execute_agent_request`.

See [contributing](CONTRIBUTING.md), [support](SUPPORT.md), and [security reporting](SECURITY.md). Public screenshots and reports must use synthetic or redacted examples. Keep private records, credentials, and local filesystem paths out of publication.

## Evaluate the current agent

The [evaluation guide](docs/public/operations/release-evaluation.md) explains the
complete comparison of raw models, the full system and hosted Luna. Results bind
the exact source, model, cohort, arm and runtime. The [current campaign record](docs/reviews/full-evaluation-20261112.md)
separates completed observations, diagnostic attempts and pending scientific
review. Historical smoke panels retain their original scope.

The current development suite contains 560 original cases and 48 refusal and
crop-scope regressions. It compares raw and full-system answers with two trials
per case on pinned E2B and E4B models and hosted Luna. The cases are exposed
development material; automated labels and different backend runtimes do not
establish field accuracy or a general model ranking.

The current software supports these bounded workflows:

- **Calculate from supplied inputs:** nutrient and product quantities, water,
  sprayer calibration, grain moisture, thermal time, harvest index, sampling
  area and explicitly supplied soil, crop and budget models, with units and assumptions. A calculation does not select a field target
  or authorize a product. Named inputs such as laboratory germination,
  permanent wilting point and harvested yield use shared role definitions in
  parsing and request checks. Extra quantities and unsupported compound units
  stay in the whole request and cannot inherit a calculator-only answer;
  clarification or ordinary model handling may be required.
  Supplied area and kg/ha can produce a total mass; supplied total available
  water and depletion fraction can produce an allowable depletion amount.
  Neither calculation chooses the rate or depletion fraction for a field.
- **Resolve seed-establishment ambiguity:** distinguish overall emergence from
  survival after germination. Otherwise complete inputs with an unclear
  denominator produce two labelled scenarios; a short reply can select the
  supplied basis without model use.
- **Explain and collect useful evidence:** definitions, methods, hypothetical
  arithmetic examples and scouting questions can receive bounded help. Disease
  history informs soil precautions across rotations; current symptoms and
  diagnoses keep their own evidence requirements. Experimental soil drying and
  harvest grain drying retain their distinct meanings in variety comparisons.
  Sampling design, comparable soil-test depths, forecast bookkeeping and
  marginal-return explanations retain their analytical scope; incidental crop
  or nutrient words do not turn them into a field prescription.
- **Explain safety and evidence:** general pesticide safety checks, task-specific
  PPE sources and the distinctions between efficacy, crop tolerance and registration can receive
  bounded explanations. These questions do not authorize a use. Stored-grain
  probe monitoring retains its own object and method.
- **Interpret the named source:** product identity and requested passage content
  control regional-source interpretation. Crop-stage code questions do not
  require unrelated raster metadata. Regional alerts can inform preventive
  potato disease planning before visible symptoms, with current crop, target
  and product restrictions checked separately.
- **Keep the whole request:** a calculation or definition cannot silently replace
  additional requested help. Field actions, product selection and use
  restrictions retain their applicable evidence and current authority checks.

These are software contracts under evaluation. Tests, a fluent answer and a
refusal each require interpretation; none establishes general agronomic accuracy.

## Evidence and licensing

This is development and research software. Regional map context is a prior, calculated area is an estimate, and model output is not field truth or pesticide-label authority. Confirm consequential decisions with current local evidence and qualified professional judgment.

Tests and benchmarks establish only their declared scope, not general agronomic competence. Historical experiments and non-active candidates retain their original identities; evaluation cases never enter runtime retrieval or training. Read the [evaluation contract](docs/public/evaluation.md), [governance](docs/public/governance.md), and [retained research record](docs/reviews/residual-polish-checkpoint-20260928.md) for evidence and limitations.

Project-authored software and documentation use [PolyForm Noncommercial 1.0.0](LICENSE), except explicit separate licences and preserved earlier grants. Data, dependencies, and model weights retain their own terms; see [third-party notices](THIRD_PARTY_NOTICES.md) and [licensing](docs/public/licensing.md). Earlier Apache grants remain valid.
