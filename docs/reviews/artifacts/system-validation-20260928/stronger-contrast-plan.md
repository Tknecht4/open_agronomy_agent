# Stronger-model retained contrast

Frozen after Gemma execution completion and before full blind grades/adjudication.
2026-09-28. Source unchanged from capsule v2.

Question: Does the full document+graph retrieval setting improve final task
completion relative to neither source under the same production core on a
stronger pinned model? All other field/tool/policy/editor behavior stays enabled.
The contrast is selected for its interpretation and practical decision boundary,
not by selecting the best Gemma score. Do not select a subset of favorable cases.

Use all 24 frozen cases, retrieval_neither/retrieval_both, trials 1 and 2 in the
existing counterbalanced order: 96 attempted cells. Separate Qwen3.5 27B 4-bit,
revision 45797d2985a12c55e6473686e9ea91b95e959553, MLX CUDA on the same L4.
The existing diagnostic configuration has prefill_step_size=512 for memory fit;
8192 context, cache off, 640 draft/220 editor output cap. First run the two separate
setup prompts to verify fit, bounded latency and cap behavior. Do not pool model
scores or claim architecture effects separated from model/runtime configuration.

Hard job limit 7200 seconds, per-cell 600 seconds. Use setup timing to forecast
96 cells before launch. If setup cannot fit or fails, retain that outcome and stop
this contrast; do not silently reduce model precision or alter main case inputs.
No active profile, corpus or prompt changes. Same draft/post-verification/final
blind triage, with source-based adjudication and all-attempt denominators.

This exposed cohort is a development diagnostic; no held-out generalization,
qualified agronomic review, or production activation follows from it alone.
