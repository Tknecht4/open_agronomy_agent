# Final controlled development benchmark — 2026-08-12

This package records the final pre-conference controlled benchmark for the Open Agronomy Agent implementation at commit `76644dcab85ac635cb9f976ff6c769b4a6cd4da8`. The four-page [technical paper](paper.pdf) is the concise interpretation; the accompanying tables and scripts preserve the plot-ready evidence behind it.

## Primary internal result

The internal suite contains 241 frozen Canadian cases and four causal arms: raw model, kernel only, kernel plus structured field context, and the governed full system. The primary semantic lane contains 90 Canadian decision-quality cases. Scores below are advisory Luna High semantic-judge means on that lane; the interval is a paired, fixed-suite case-bootstrap interval for full system minus raw model.

| Candidate | Raw model | Full system | Paired change (95% interval) |
|---|---:|---:|---:|
| Gemma 3 270M 4-bit | 2.50 | 73.13 | +70.63 (+65.46 to +75.71) |
| Gemma 4 E2B 4-bit | 54.71 | 77.93 | +23.22 (+17.60 to +28.59) |
| Luna High | 89.82 | 83.38 | -6.45 (-11.52 to -1.18) |

The result is model-dependent. Governed evidence and answer constraints substantially helped the two local candidates, especially the very small Gemma 3 model, while the same full intervention degraded the stronger remote generator. Intermediate-arm and task-family files should be used to diagnose that interaction; the pooled numbers are not a universal “agent uplift” claim.

## Preserved negative findings

- The registered typed calculator was not invoked by the benchmark orchestration path. All three governed candidates therefore scored 0/16 on the objective calculation lane. This is an integration failure, not evidence that the calculator implementation cannot solve the tasks.
- Luna High produced both candidate answers and semantic judgments in part of the matrix. Those judgments are retained as development triage, with a known self-preference risk, and have no promotion authority.
- The 256-question held-out AgroQA run is an Uganda-source geographic-transfer diagnostic. The frozen Gemma 4 finalist improved normalized reference-token F1 from 0.0508 to 0.0595, but this is not Canadian validation and the exposed implementation must not be repaired and retested on the same external-set version.
- No result here establishes agronomist equivalence, professional-exam readiness, Canadian population validity, or field outcomes. Independent blinded agronomist review remains required.

## Package map

- `paper.pdf`, `main.tex`, `references.bib` — rendered paper and reproducible manuscript source;
- `figures/benchmark_results.pdf` — vector result figure;
- `source_data/arm_lane_summary.csv` — arm-by-lane aggregates;
- `source_data/paired_semantic_deltas.csv` — paired effects and fixed-suite intervals;
- `source_data/task_family_summary.csv` — task-family heterogeneity;
- `source_data/orchestration_summary.csv` — rewrite, fallback, and intervention behavior;
- `source_data/resource_summary.csv` — latency and token diagnostics;
- `source_data/response_level_metrics.csv` — response identities and metrics, without generated answer text;
- `source_data/external_*` — frozen finalist identity and one-time external diagnostic;
- `source_data/protocol.md` and `source_data/final_validation_receipt.json` — experiment contract and completion receipt;
- `scripts/` — deterministic analysis and manuscript-fragment generators.

The full SQLite databases, exact model responses, exact judge exchanges, private field data, credentials, model weights, and local execution logs are intentionally excluded from Git. Database hashes and record counts are retained in the validation receipt so a separately transferred local artifact can be checked without making it public.

## Reproduction

From this directory, with a benchmark database supplied separately:

```bash
python scripts/analyze_final_benchmark.py \
  --database /path/to/full_system_benchmark.sqlite3 \
  --paper-root .
python scripts/build_generated_table.py --paper-root .
tectonic main.tex
```

Regenerating the manuscript macros additionally requires the separately retained cost-ledger manifest:

```bash
python scripts/build_generated_results.py \
  --paper-root . \
  --cost-ledger-manifest /path/to/cost_ledger_manifest.json \
  --external-summary source_data/external_finalist_summary.json
```

The external diagnostic is summarized separately to preserve the no-mixing boundary:

```bash
python scripts/summarize_external_finalist.py \
  --database /path/to/external_full_system_benchmark.sqlite3 \
  --freeze source_data/external_finalist_freeze.json \
  --output source_data/external_finalist_summary.json \
  --response-output source_data/external_response_metrics.csv
```

See [the repository evaluation contract](../evaluation.md) for suite roles, causal arms, identity gates, and claim limits.
