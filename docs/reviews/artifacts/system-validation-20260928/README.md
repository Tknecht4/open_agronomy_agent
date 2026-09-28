# System-validation evidence, 2026-09-28

This is exposed development evidence. None of these files is an admitted runtime
retrieval source, training source, field recommendation or release qualification.
The report is [two directories above](../../system-validation-20260928.md).

## Evidence identities

- `gemma-v1-*` and `qwen-v1-partial-*` preserve the superseded instrument. It passed
  legacy field keys directly instead of using the product context schema. Qwen v1
  was deliberately stopped: 51 completed observations, one additional started cell,
  and 44 untouched planned cells. All 45 without a completed result remain unknown.
- `gemma-field-v2-*` and `qwen-field-v2-*` identify corrected, separate model runs.
  Per-cell field receipts bind original inputs, explicit canonical projection,
  compiled fields and actual generation prompts. Model scores must remain separate.
- Raw `.jsonl.gz` exports retain complete execution JSON and ledger observations,
  including original stale bypass statistics. Mechanics audits exclude those
  stale rows from model-call timing and token totals. Original isolated SQLite
  stores remain in the local collection; published table audits record exact
  source, row, import, snapshot and query joins.
- `.publication.json` files bind path-normalized JSON derivatives to their original
  local bytes. Only repository path prefixes and JSON formatting are changed.
- The problem-setup audit identifies rubric limitations prospectively. The frozen
  questions, reference answers and scoring criteria have not been rewritten.

## Reproduction boundary

The model runs used production source commit
`2b4028560c18def902463b4da44ef2c5c69467b1`. The later separately tested telemetry
repair at `0ca14343eea2c74133b30a573d4e9d17a9cfa3e8` is not retroactive model evidence.
Run manifests bind 147 production Python files, the corpus, fixture, model revision,
runner and generation settings. Runtime receipts identify NVIDIA L4/MLX CUDA;
these results do not measure 27B inference on a laptop.

Extract instrument archives at the repository root to recover the original
ignored `outputs/system-validation-20260928/` paths. The old instrument is retained
for reproducibility; use the separately identified field-v2 runner for corrected
comparisons. Verify the supplied file hashes before executing it. Each run needs
its own new output directory; resume is allowed only with an identical manifest.

The corrected instrument archive is `instrument-field-v2.tar.gz` (SHA-256
`4a75fdeb3a37d6e9fd05a2d8bcbacce48d22aecb7e67f08f3d2553f8aa39c383`).
`run-metadata-field-v2.tar.gz` preserves the **original bytes** of each of the
four run manifests and cell plans; the `*-run-manifest.json` files beside the
raw exports are normalized derivatives. `runtime-receipts.tar.gz` preserves
35 explicitly selected collection-root capsule inventories, environment,
status, provisioning, delta, mock and driver receipts. It does not contain
run outputs or model weights. From the repository root, verify and extract the
four archives (the fourth contains local-only evaluation material):

```bash
python3 - <<'PY'
import hashlib, io, json, tarfile
from pathlib import Path
base = Path('docs/reviews/artifacts/system-validation-20260928')
for manifest_name in ('instrument-field-v2-manifest.json',
                      'run-metadata-field-v2-manifest.json',
                      'runtime-receipts-manifest.json',
                      'grading-analysis-manifest.json'):
    manifest = json.loads((base / manifest_name).read_text())
    archive = (base / manifest['archive']).read_bytes()
    assert hashlib.sha256(archive).hexdigest() == manifest['sha256']
    assert len(archive) == manifest['bytes']
    with tarfile.open(fileobj=io.BytesIO(archive), mode='r:gz') as tar:
        members = tar.getmembers()
        assert [m.name for m in members] == sorted(manifest['files'])
        for member in members:
            assert member.isfile() and member.mtime == member.uid == member.gid == 0
            data = tar.extractfile(member).read()
            assert len(data) == manifest['files'][member.name]['bytes']
            assert hashlib.sha256(data).hexdigest() == manifest['files'][member.name]['sha256']
    print(manifest['archive'], manifest['sha256'])
PY
tar -xzf docs/reviews/artifacts/system-validation-20260928/instrument-field-v2.tar.gz -C .
tar -xzf docs/reviews/artifacts/system-validation-20260928/run-metadata-field-v2.tar.gz -C .
tar -xzf docs/reviews/artifacts/system-validation-20260928/runtime-receipts.tar.gz -C .
tar -xzf docs/reviews/artifacts/system-validation-20260928/grading-analysis.tar.gz -C .
python3 outputs/system-validation-20260928/analysis/package_evaluation_artifacts.py verify
python3 outputs/system-validation-20260928/analysis/package_evaluation_artifacts.py verify-metadata
```

The following commands restore the original execution/setup JSON bytes and
ledger from each published raw export. Field-v2 execution records also restore
the separate `field_delivery.json` bytes. Each output directory must be new;
the metadata copies complete the run directories for aggregation.

```bash
base=docs/reviews/artifacts/system-validation-20260928
analysis=outputs/system-validation-20260928/analysis
remote=outputs/system-validation-20260928/colab
for spec in \
  'gemma-v1:gemma-retrieval-192:results-v1' \
  'qwen-v1-partial:qwen-retrieval-96:results-qwen-partial-v1' \
  'gemma-field-v2:gemma-field-v2-192:results-gemma-field-v2' \
  'qwen-field-v2:qwen-field-v2-96:results-qwen-field-v2'; do
  IFS=: read -r export_name run_name collection_name <<< "$spec"
  python3 "$analysis/restore_public_run.py" \
    --raw "$base/$export_name-raw.jsonl.gz" \
    --receipt "$base/$export_name-raw-receipt.json" \
    --output-dir "$analysis/public-reconstructed/$run_name"
  cp "$remote/$collection_name/outputs/$run_name/cell_plan.json" \
     "$remote/$collection_name/outputs/$run_name/run_manifest.json" \
     "$analysis/public-reconstructed/$run_name/"
done
```

The restore helper verifies the raw-export SHA, original execution/setup file
SHA values, ledger SHA, and field-delivery ledger receipt identity. The
metadata archive verifies the original plan/manifest file hashes and binds
each run identity to its public raw receipt. The receipt archive verifies each
member's original collection-root bytes, its explicit allowlist and a
deterministic rebuild. A separate native-byte check also
passed for all four retained collections: Gemma v1 restored 192 executions and
8 setup receipts; interrupted Qwen v1 restored 51 and 4; Gemma field-v2 restored
192 executions, 192 field-delivery receipts and 8 setups; Qwen field-v2 restored
96 executions, 96 field-delivery receipts and 4 setups. No SQLite file is in
these public archives; private table import/snapshot/query joins cannot be
rerun from these reconstructed files alone and rely on the separate table audit.

Together, the instrument, run-metadata and runtime-receipt archives plus restored
raw exports permit public
rechecks of run/plan identities, cell counts and status, prompt and field
delivery receipts, ledger timing and token arithmetic, runner/delta hashes,
capsule inventory, provisioned model identity, and available driver-end logs.
The retained Gemma field-v2 collection has no standalone driver log, so its
end-drift conclusion remains based on exit status and the runner contract.
The interrupted Qwen v1 run remains partial. A full mechanics-audit rerun also
needs the exact production source, configurations, corpus and fixture named in
the manifests, plus run-level offline RAG profiles and worker logs that are
not in those three mechanical-evidence archives. The original isolated SQLite stores are private;
their import, snapshot, query, and table-join checks cannot be independently
rerun from public raw exports. The published table-audit receipts preserve the
observed joins, not a substitute database.

The frozen `grading-analysis.tar.gz` contains the anonymous packets, their exact
mappings, A/B judgments, adjudications, current-run clearances and analysis code.
Its manifest supplies separate argument lists and expected summary hashes for the
two corrected runs. Historical/intermediate grades stay explicitly superseded;
they are not pooled into the corrected comparison. After the extraction and raw
restoration above, reproduce the two summaries independently:

```bash
python3 - <<'PYCODE'
import hashlib, json, subprocess, sys
from pathlib import Path
base = Path('docs/reviews/artifacts/system-validation-20260928')
manifest = json.loads((base / 'grading-analysis-manifest.json').read_text())
restored = Path('outputs/system-validation-20260928/analysis/public-reconstructed')
for label, original_argv in manifest['reproduction_commands'].items():
    argv = list(original_argv)
    argv[0] = sys.executable
    for index, value in enumerate(argv[:-1]):
        if value == '--run':
            argv[index + 1] = str(restored / Path(argv[index + 1]).name)
    subprocess.run(argv, check=True)
    summary = Path(argv[argv.index('--out') + 1]) / 'quality-summary.json'
    model = label.removesuffix('_corrected')
    assert hashlib.sha256(summary.read_bytes()).hexdigest() == manifest['expected_quality_summary_sha256'][model]
    print(label, 'exact summary hash verified')
PYCODE
```

Each reproduction output directory must be new. The reconciler preserves failed,
unattempted and source-unresolved observations; it does not infer agronomic
validation from execution success or a high score.

**Do not upload the complete instrument or grading archive to a model host.**
They contain evaluation rubrics and reference answers. Only the runtime input,
reviewed synthetic table setup and fixture, runner, required production code,
active public corpus/configuration and their integrity receipts belong in the
model capsule. The original frozen cohort and rubric stay local for grading.

Anonymous answer packets deduplicate only byte-identical answers within the same
case and premises. Semantic grade reuse additionally checks the entire question,
history, field premises, rubric, reference and source-availability record. It does
not transfer source-attribution clearances. Initial grader packets omitted arm
and stage identity; earlier filenames could reveal model family, and reused
judgments retain that limitation. Source adjudication may inspect supplied
evidence conditions. All grading is automated internal triage, not qualified
agronomic validation.

The small selected cohort mixes source-dependent questions with deterministic
calculations, table queries, user-provided observations and missing-authority
cases. Repeated trials are not independent cases. A null pooled difference does
not establish equivalence, justify removing a system, or demonstrate general
agronomic expertise.
