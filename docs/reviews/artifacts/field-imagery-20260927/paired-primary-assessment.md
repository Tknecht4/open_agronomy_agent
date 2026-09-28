# Fixed imagery assessment — 2026-09-27

## Observed outcome

The fixed local spectral readout outperformed the frozen Prithvi readout for
crop classification on this source-bound, one-farm cohort. This does not show
external-farm accuracy or a general EO-model ranking. Twelve physical-unit
folds keep labels separate, while their 6.72 km imagery contexts overlap.
Source support is a research sampling hull, not a surveyed field boundary.

Of 29 frozen seasons, **21 have matched four-date features** and **8 are
unavailable** because no 2019 catalog scenes were returned in the frozen
window. No dates were repeated, windows extended, or missing predictions
imputed. Both EO arms and the location/year control use the same 21-success
training mask; training-only majority/crop-mean baselines use that mask too.
All 29 dispositions remain in `paired-primary-assessment.json`.

| Physical-unit holdout | Crop correct / 21 matched | Correct / all 29, failures incorrect | Balanced accuracy on 21 | Macro-F1 on 21 |
|---|---:|---:|---:|---:|
| Training majority | 12/21 (57.14%) | Not an EO coverage metric | 0.3333 | 0.2424 |
| Location/year control | 11/21 (52.38%) | 11/29 (37.93%) | 0.3056 | 0.2366 |
| Fixed spectral 32D | 20/21 (95.24%) | 20/29 (68.97%) | 0.8889 | 0.9077 |
| Frozen Prithvi 192D | 8/21 (38.10%) | 8/29 (27.59%) | 0.2500 | 0.2422 |

These proportions have different denominators from the earlier source-only
29-season assessments. They must not be silently compared or pooled.

| Per-crop sample-location yield MAE, kg/ha | Wheat, n=12 | Corn, n=6 | Millet, n=3 |
|---|---:|---:|---:|
| Training crop mean | 1331.57 | 1031.67 | 670.80 |
| Location/year control | 1905.18 | 1700.34 | 2768.08 |
| Fixed spectral 32D | 628.78 | 578.38 | 2016.53 |
| Frozen Prithvi 192D | 1914.08 | 690.24 | 9668.30 |

Regression conditions on observed crop. It predicts the arithmetic mean at
sample locations, not area-weighted or whole-field harvested yield. Moisture
bases remain wheat 12.5%, corn 15.5%, millet 12%; no pooled cross-crop yield
score is reported. Spectral MAE skill against crop means is +0.528 wheat,
+0.439 corn and −2.006 millet; Prithvi is −0.437/+0.331/−13.413.
The three millet seasons are too few for stable high-dimensional regression.
Negative predictions remain unclipped: spectral SB7-2020, Prithvi SCD5-2021,
and location/year SB4-2022. They are retained errors, not physically plausible
yield recommendations.

## Separate forward-year contrast

Train eligible 2020–2021 seasons, then test eight 2022 seasons, potentially on
previously observed units. The unavailable 2019 seasons contribute no training
features. This is temporal transfer on the same farm, not a new-field test.

| Forward 2022 | Crop correct / 8 | Wheat MAE, n=4 | Corn MAE, n=2 | Millet, n=2 |
|---|---:|---:|---:|---|
| Training majority / crop mean | 4/8 | 2244.71 | 997.81 | MAE 619.24 |
| Location/year control | 2/8 | 4264.14 | 2717.34 | 2 unavailable |
| Fixed spectral | 6/8 | 1339.74 | 2437.61 | 2 unavailable |
| Frozen Prithvi | 3/8 | 1058.31 | 1028.42 | 2 unavailable |

Only one eligible millet training season exists in this split, below the
frozen two-season regression minimum. All learned millet predictions therefore
remain failures. Apparent wheat gains across these four test cases do not
justify selecting a new model or tuning after evaluation.

## Observed representation aliases

Three Prithvi exact-vector alias groups cover seven of the 21 cases:
SCD4/SCD5-2020; SCD4/SCD6-2022; and SCD5/SCD6/SCD7-2021.
Each group includes different observed crops. Their ROI masks differ but
coarse 480 m tokens overlap; identical vectors cannot distinguish these cases
with any deterministic readout of the vector alone. The spectral representation
has no exact-vector aliases. Nearby units also share encoder attention context;
physical label-group holdout is not spatially disjoint imagery holdout.

## Datum and geometry sensitivity

The 2020/2022 HLS headers mix EPSG:32613 and an unknown-datum WKT on the WGS84
ellipsoid. Formal CRS equality is **false**. The reviewed loader admits a
qualified shared numeric HLS lattice based on matching affine/shape,
projection, ellipsoid, axes and MGRS tile, without resampling. Original CRS
strings and formal-false receipts remain in feature provenance. This is an
explicit datum assumption, not proof of geographic equivalence. The raw
sampling CSV also leaves its UTM13N datum unresolved.

`spectral-spatial-sensitivity.json` retains all 29 bundle dispositions and
189 valid alternative-support calculations (21 cases × 9 alternatives).
The NAD83-to-WGS84 alternative produced identical pixel masks and spectral
features with the locally available transform, whose stated accuracy is 4 m;
that does not establish the source datum. Cardinal 15 m shifts reduced support
Jaccard as low as 0.5135 and changed a spectral component by up to 0.1601.
Cardinal 30 m shifts reduced Jaccard to 0.4737 and changed a component by up to
0.2542. Every alternative retained positive valid support on all four dates.
No shifted accuracy was scored, no offset was chosen by outcomes, and primary
scores were not changed. Small-field geolocation sensitivity is material.

## Numerical warning audit

The first scoring run emitted NumPy/sklearn divide-by-zero, overflow and
invalid-value warnings from matrix multiplication. It is preserved unchanged.
The observed runtime was NumPy 2.0.2 with Apple Accelerate, SciPy 1.18.1 and
scikit-learn 1.9.1. The cause of these warnings remains unresolved; they have
not been suppressed or recast as a clean numerical run.

Independent checks in `numerical-independent-audit-summary.json` verified all
168 linear/logistic prediction calls with Python `math.fsum`, without BLAS.
All inputs, coefficients, intercepts and outputs were finite; every crop class
matched exactly. Maximum decision difference was 1.82e-12 (scaled 1.47e-15).
All 114 Ridge fits passed independently calculated normal-equation residuals,
with maximum relative residual 7.39e-15. Two diagnostic replays reproduced every
metric exactly. This validates the reported numerical predictions and Ridge
solutions; it does not independently reproduce the logistic optimizer path.
Warning counts and fit/prediction checks remain explicit in audit artifacts.

## Frozen identities and scope

- Base protocol: `9714d8896c97092f81ac283d6ac2025d9460e3eed5733f85aa08776e4ce8455e`.
- Spectral recipe: `9e51786b72071f3ee3537fdbb85edfa5582a5b56ba48e85854c09976de6ed945`.
- Immutable context index SHA-256: `e8917e40783353ebbb5100d21eb88d1429f7d423e292205e94869975fea89c32`.
- Acquisition dates: 2020 May 3, May 17, June 7, June 12;
  2021 June 2, June 5, June 7, June 12;
  2022 May 13, June 7, June 8, June 12.
- Feature payloads bind input file hashes, source scenes, exact dates, support
  and valid-mask hashes, model weights/code and preprocessing identities.
  Pairing requires equal source/date/ROI/QA identities before any scoring.
- Label source is the pinned CC0 raw CSV, never field-QA answers. S2–S7 remain
  excluded in all years. No language-model fine-tuning or runtime admission.
- Seventeen focused contract tests pass. No feature, cutoff, split,
  hyperparameter or threshold was tuned to these EO scores. The two numerical
  replays were triggered solely by runtime warnings and preserved the metrics.

Unknown historical publication times and outcome-dependent sample cleanup
still make this retrospective. Results concern one farm, 12 related units,
three observed imagery years, and sample-location outcomes. They establish
neither agronomic validation nor operational forecast performance.
