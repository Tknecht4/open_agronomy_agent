# Open Agronomy Agent

Open Agronomy Agent is a local-first research system for evidence-grounded Canadian field questions. It joins field context, governed knowledge, graph relationships, deterministic capabilities, a downloadable model, validation, and an auditable trace.

It is not an agronomist replacement or a regulatory, diagnostic, or field-outcome authority. Its central design rule is to preserve the difference between **observation**, **model output**, and **interpretation**.

<div class="system-flow" aria-label="High-level request flow">
  <span>Field question<br><small>context + history</small></span><b aria-hidden="true">→</b>
  <span>Route and frame<br><small>intent + consequence</small></span><b aria-hidden="true">→</b>
  <span>Collect evidence<br><small>retrieval + graphs + tools</small></span><b aria-hidden="true">→</b>
  <span>Local model draft<br><small>bounded context</small></span><b aria-hidden="true">→</b>
  <span>Validate and trace<br><small>direct answer + sources</small></span>
</div>

## Current status at a glance

| Capability | Implemented | Automated tests | Frozen benchmark evidence | Boundary |
|---|---|---|---|---|
| Local text generation | Yes, with explicitly provisioned MLX profile | Model/profile and service contracts | Current-code A100 assessment: three four-arm trials each for Gemma 3 270M and Gemma 4 E2B; 5,784 retained responses | Model output is advisory; the assessment is exposed development evidence without calibrated semantic or agronomist review |
| Governed retrieval | Yes, local policy-admitted lexical/Agno path | Retrieval and corpus policy tests | RC3 surfaced the expected source in 22/26 positive probes and 46/50 required patterns | Retrieval presence is not answer use, quality, or field truth |
| Knowledge graphs | Multiple manifest-bound JSON graphs configured and merged | Manifest, checksum, collision, provenance, and routing tests | Graph hints present in governed arm | Relationship context, not decision authority; runtime profiles require admitted manifests |
| Structured calculator | Typed offline executor plus bounded explicit-request planner | Deterministic, service, and natural-language end-to-end tests | Current-code full system scored 16/16 in every trial for both assessed models | Computes supplied inputs only; this does not validate target selection or broader advice quality |
| Public adapters | Several provider/cache contracts exist | Offline-fixture and readiness tests | Traced but live service orchestration not executed | Optional, date/provider/jurisdiction dependent |
| Field history and traces | Local persistence and trace APIs exist | Field-event/storage/service tests | Interface/lineage lanes exercised | Local records remain private; historical trace does not validate a later answer |
| Prairie spatial pack | Optional verified local asset | Package/intersection gates | Not a primary RC1 geometry capability | Mapped historical prior, not a sample or point truth |
| Risk/evidence validation | Implemented and intervention-visible | Safety/evidence regression tests | RC3 retained verifier, hold, rewrite, fallback, and guard traces | Activation counts do not establish whether answers improved; validation cannot create evidence |

“Automated tests” means a named contract has coverage, not that every combination or live provider was exercised. RC1 and RC3 retain their historical identities. The current-code two-Gemma assessment binds evaluated commit `d43ade7`; its checked-in report was added afterward and does not alter that evaluated system identity.

## Where to go

- [System architecture](architecture.md): request lifecycle, trust boundary, model independence, and traces.
- [Capabilities](capabilities.md): status vocabulary and capability matrix.
- [Knowledge and data](knowledge-and-data.md): source admission, retrieval, graphs, and geospatial priors.
- [Tools and adapters](tools-and-adapters.md): calculator, public adapters, offline behavior, and extension rules.
- [Evaluation](evaluation.md): the four benchmark arms, RC1 history, completed RC3 checkpoint, and claim limits.
- [Current two-Gemma assessment](two-gemma-colab-assessment-20260926.md): current-code A100 results, merge decision, residual fallback dependence, and reproducibility limits.
- [RC3 development checkpoint](development-benchmark-rc3-20260815/README.md): paper, scientific figures, public-safe measurements, and reproducibility receipts.
- [Developer guide](developer/index.md): code map and how to add a graph, tool, source, or service.
- [Native setup](operations/native-setup.md), [offline operation](offline-operation.md), and [containers](operations/containers.md).
- [Governance](governance.md): privacy, egress, licensing, contribution, and publication boundaries.

## Safety and data boundary

Do not use the system as the sole basis for pesticide use, legal compliance, diagnosis, fertilizer prescription, financial commitment, or another high-consequence action. Confirm current labels/regulations and representative field evidence and involve a qualified local professional when warranted.

Runtime databases, traces, model caches, raw benchmark answers, private overlays, credentials, and generated spatial databases are excluded from this documentation site.
