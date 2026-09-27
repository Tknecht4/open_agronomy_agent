# Workspace backend inventory and profiling, 2026-09-27

Status: development diagnostic on `codex/ui-workspace-redesign`, based on `main` `7a34111`. Synthetic data only. Timings are local observations, not agronomic, model-quality, throughput, or release claims. The machine ran other workspace tasks during parts of the comparison.

## Supported workspace surface

| Area | API path | UI boundary |
|---|---|---|
| Configuration/readiness | `/api/health`, `/api/configs`, `/api/knowledge/coverage`, `/api/tools/capabilities`, model readiness routes | Health means configured API availability; it does not prove generation or provider health. Active model/RAG profiles are operator-managed. |
| Field workspace | `/api/demo/fields` CRUD, `/{field_context_id}/events`, `/events/sync`, `/history` | Workspace-authorized, local records. Field events and corrections retain lineage. History binds a stored answer to a field snapshot, not answer correctness. |
| Conversation | `/api/sessions` CRUD, `/{session_id}/turns`, `/turns/stream`, `/events` | Session ownership enforced. Stream progress is incremental; the final answer is computed by the production core and then emitted in chunks. |
| Map context | `/api/geo/layers`, `/regions`, `/intersections`, `/boundary-upload`, `/priors` | Polygon/map matches are regional context, not a measurement or field-level truth. Optional map packs can be unavailable. |
| Private knowledge | `/api/private-knowledge/inspect`; attachment routes | Ephemeral inspection accepts PDF up to 5 MB and UTF-8 plain/Markdown/JSON up to 1 MB. Low-text PDFs are blocked without silent OCR. Parsed chunks are context-only and are not retained by this route. |
| Sources and outputs | `/api/data-sources`, `/api/exports`, `/api/feedback`, `/api/reflections` | Data source ingestion and exports have separate queued/durable paths; feedback and reflections are records, not automatic evidence promotion. |
| Diagnostics | `/api/admin/latency`, `/api/admin/traces/{trace_id}`, frontend RUM/events | Stage spans support operational diagnosis; unavailable stages stay explicitly skipped. |

The route inventory is from `src/agronomy_agent/server/app.py` and its service contracts. The exact OpenAPI document remains authoritative for request and response shapes. A UI should expose field history, event sync, source/trace inspection, private-context limits, export state, and unavailable capability states, without promoting map priors or private material into decisive authority.

## Reproducible measurements

The default profiler uses a new synthetic SQLite database, offline mode, a mock model, and no real provider calls:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python scripts/profile_workspace_backend.py \
  --output-dir /tmp/open-agronomy-backend-profile-new \
  --warm-repeats 7 --sessions 20 --turns-per-session 8
```

It rejects a nonempty destination and preserves every completed or failed cell in `receipt.json`. The receipt includes source/config/question hashes, cold and warm timings, cProfile summaries, and core stage spans. cProfile captures startup and direct production-core work; the in-process HTTP client runs endpoint code on a separate thread, so endpoint cProfile text primarily measures the client thread. Explicit full-turn load counts and endpoint wall-clock time characterize the history path.

At baseline, `create_app` took 9.916 seconds under cProfile; the governed corpus audit accounted for 9.544 seconds and parsed 221,348 JSON rows. A direct audit counted 56 SHA-256 calls over 56 unique paths, with zero duplicate paths. The audit also checks row shape, locators, jurisdiction, quality ledger, policy and admission state. There is no duplicate-hash-only repair to make without changing this authority gate.

With 20 synthetic sessions and 8 turns per session, the baseline field-history endpoint took 48.8 ms warm median over 4 calls. It loaded full detail for all 160 turns before selecting the 8 turns bound to the requested field. The code now checks field lineage first and loads full detail only for matching turns. A repeat run counted exactly 8 full-turn loads per call (56 over 7 calls), with a 34.6 ms warm median. This is a measured improvement in work done; the wall-clock comparison is provisional because other local activity changed substantially between runs. The first after run was slower in every cell, including unrelated session listing and mock core; that contrary evidence is retained.

The mock production core's first turn took 88 ms in the first baseline run, with 52.5 ms in route classification. In the later run, a cold turn took 196.8 ms and seven warm turns had a 21.1 ms median. These are diagnostic timings only; the host load and cold cache state differed. No route semantics were changed.

The explicit local-model profiler requires a pinned snapshot already in the cache and forces `HF_HUB_OFFLINE=1`:

```bash
HF_HUB_CACHE=/absolute/local/hf-cache/hub HF_HUB_OFFLINE=1 \
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python \
scripts/profile_workspace_model.py --execute-local-pinned \
  --output-dir /tmp/open-agronomy-model-profile-new \
  --max-tokens 120 --deadline-seconds 900
```

The exercised pinned Gemma 4 E2B snapshot was revision `238767527555cb75a05732a84dff5d6ba0dd6809`; the local preflight found it without a download. Two offline synthetic, non-claim production-core turns completed with 17/17 stage receipts each. The first took 37.52 s: 29.11 s in model drafting and 7.07 s in evidence verification. The second took 18.27 s: 10.19 s drafting and 7.72 s verification. Metal peak allocation was 3180.48 MiB and 3174.49 MiB, respectively; active allocation after each turn was about 2483.47 MiB. Process peak RSS was 973.92 MiB. These are separate allocator and process metrics and should not be added as a precise total unified-memory requirement.

The retained generation trace reports 2,022 prompt and 120 draft-generation tokens in the first turn, 2,287 and 120 in the second. The verification pass reports 1,662 prompt and 79 generated tokens, then 1,706 and 96. A post-run profiler edit now copies these selected counts into future receipts; it was checked against the retained synthetic traces without another model run, and the artifact records both script hashes. Draft generation hit the 120-token profiling cap on both turns, so this receipt cannot assess answer completeness. The model spans currently label `model.load_or_reuse` at under 1 ms, but actual lazy loading occurs inside `model.decode_stream`; that span is not a true loading cost. Tokenizer template and prefill-to-first-token spans are skipped as unobservable from this generator, so first-token latency is unknown. The dominant observed cost is generation plus verification; changing model, context, or verifier settings would change quality and was outside this optimization round.

## Change and verification

`src/agronomy_agent/server/app.py` now defers full turn loads until after the field binding matches. `tests/test_demo_field_library.py` asserts one matching full-turn load, preserved feedback, and a verified answer integrity receipt despite unrelated field turns. Profilers are `scripts/profile_workspace_backend.py` and `scripts/profile_workspace_model.py`. Full raw receipts remain in the local temporary profiling directory and are intentionally not published; `ui-backend-performance-20260927.json` is a minimized public-safe summary.

The focused field-library test passed 3/3. A broader serial focused run passed 38/38 across `test_demo_field_library.py`, `test_field_events.py`, and `test_execution_core.py` (`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python -m pytest -q -n 0 -p no:cacheprovider ...`). No model/corpus profile, policy, frozen benchmark, personal runtime database, or authority semantics were changed. The startup audit is still a real user-visible cold-start cost; the tested profile does not justify caching it across starts or omitting validation.
