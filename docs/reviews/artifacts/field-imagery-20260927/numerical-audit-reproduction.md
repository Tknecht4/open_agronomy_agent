# Reproducing the numerical diagnostic

`audit_imagery_numerics.py` is a portable, parameterized copy of the **executed
independent numerical diagnostic**, not a new assessment protocol. It performs
no network access or encoder inference. Explicitly running it refits the same
frozen small readouts, checks each linear/logistic decision with Python
`math.fsum`, checks Ridge normal equations, and compares metrics against the
retained original result. It does not tune, choose offsets, modify historical
receipts, or automatically accept new results. Warning causes remain unresolved.
Importing the script or requesting `--help` does not run the assessment.

`numerical-audit-source-lineage.json` binds the original executed source hash,
original full audit hash, this portable source, exact unchanged numerical-code
blocks, source inputs and retained public summaries. The raw full warning audit
and original source remain in ignored maintainer outputs; the parameterized
source and hash-bound summaries are preserved as explicit public research
artifacts. The earlier `numerical-warning-audit.json` came from an inline fit
probe whose standalone source was not retained. This portable file reproduces
the later independent arithmetic audit; it is not a fabricated original of
that earlier command.

The original diagnostic used Python 3.12, NumPy 2.0.2, SciPy 1.18.1,
scikit-learn 1.9.1 and Apple Accelerate. Other dependency/platform combinations
may produce different warnings or floating-point results. No supported serving
dependencies were changed for this reproduction artifact.

From the repository root, with the SHA-pinned CC0 CSV locally provisioned and
a **new** output filename, the minimal explicit reproduction command is:

```bash
PYTHONPATH=src .venv/bin/python \
  docs/reviews/artifacts/field-imagery-20260927/audit_imagery_numerics.py \
  --source data/raw/field_data_research/20260927/us/akron_modeling_data.csv \
  --protocol docs/reviews/artifacts/field-imagery-20260927/label-protocol.json \
  --spectral docs/reviews/artifacts/field-imagery-20260927/spectral-primary-final-features.json \
  --encoder docs/reviews/artifacts/field-imagery-20260927/prithvi-primary-final-features.json \
  --original-result docs/reviews/artifacts/field-imagery-20260927/paired-primary-assessment.json \
  --output numerical-audit-reproduction-new.json
```

The source loader checks CSV SHA-256
`a1599b9c523f4ed44efd9b7f0c3ba6baf9f263f7c274415c77b4eb81d623f38b`.
All six paths are explicit CLI arguments. Output overwrite is refused before
any fitting, and the output parent must exist. The result records the current
portable script hash plus original executed-script lineage. Its status is
`analysis_only_reproduction_requires_review`; independent review must assess
finite values, class equality, residuals, warning counts and metric identity.

Packaging verification was limited to compilation, `--help`, machine-local-path
checks and exact comparison of the unchanged numerical operation blocks.
**No scoring, readout fitting or model execution was repeated for packaging.**
