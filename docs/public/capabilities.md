# Capability status

Capability claims use five separate questions:

1. **Implemented:** executable code exists on a supported path.
2. **Available:** required model, asset, credential, provider, network, and configuration are present now.
3. **Tested:** a named automated or operator contract has been exercised.
4. **Benchmark-exercised:** a frozen benchmark actually invoked the capability through the claimed interface.
5. **Validated:** evidence supports the intended real-world claim. No current capability is validated as agronomist-equivalent or field-outcome reliable.

These states must not be collapsed into a single checkmark.

## Capability matrix

| Capability | Implementation | Availability | Test evidence | Benchmark evidence | Known limit |
|---|---|---|---|---|---|
| Gemma 4 E2B local generation | MLX model adapter and pinned profile | Requires explicit ~3.34 GiB snapshot provision and Apple Silicon runtime | Model identity/profile and generation-path checks | RC1 candidate at frozen revision/commit | Current checkout requires a fresh run; generated advice remains advisory |
| Fast optional local model | Selectable pinned profile | Requires separate download | Profile/UI contracts | Not part of RC1 final matrix | Quality and role are profile-specific |
| Governed corpus retrieval | Policy partition plus local/Agno search | Admitted checked-in corpus available; optional private overlay local only | Corpus governance and retrieval tests | Governed text arm | Uneven Canadian applied-guidance depth; context is not local calibration |
| Knowledge graph search | Manifest-bound graph composition and name/token search | Seed and released SoilWise manifests are present | Manifest, checksum, collision, provenance, and retrieval tests | Governed context included graph hits | Graph authority roles are contextual; a relationship is not a field observation or recommendation |
| Agronomic calculator | Typed decimal executor, CLI/API adapters, and bounded explicit-request planner | Offline with supplied inputs | Deterministic operations, services, registry parity, and natural-language end-to-end path | Objective lane exposed the historical routing failure: 0/16 governed | Does not choose target rates; repaired path has no completed post-RC1 benchmark outcome |
| Guard capabilities | Query-triggered decision checks | Offline | Router/guard/evidence regressions | No current per-capability execution receipt under the canonical interface | Broad triggers can produce unnecessary caution; risk-conditioned policy is required |
| Weather and climate adapters | NASA POWER, Daymet and related adapters | Network/provider/cache dependent | Offline-fixture/readiness smokes | Adapters traced, not live-executed in RC1 | Gridded context is not field sensor or guaranteed forecast |
| Soil/crop map adapters | Local pack and public soil/crop-cover adapters | Varies by installed pack, network, geography | Fixture, package, and intersection gates | No primary executable-geometry cases | Map class/component is a regional prior |
| Statistics adapters | Canadian/US regional statistics paths | Snapshot/cache/provider dependent | Fixture/readiness tests | Not live-executed in RC1 | Regional distributions do not establish a field value |
| Label metadata adapters | PMRA/EPA metadata search paths | Network/cache/provider/jurisdiction dependent | Fixture/readiness tests | Not live-executed in RC1 | Metadata is not the current full label or legal interpretation |
| Field history | Append-oriented field/session/event persistence | Local DB by default; optional hosted dependencies | Field event, measurement, and storage tests | Lineage regression lane | User records are observations; reuse must preserve time/source |
| Image observation/RAG | Service and UI paths exist | Backend/model/config dependent | Focused image/service contracts | Not a primary RC1 capability | Image inference is not diagnosis and needs representative context |
| Offline/field-LAN | Explicit offline network mode, TLS/pairing path | Requires built client, trusted cert, operator setup | Launcher/topology/package tests | Not portable-field outcome proof | A lab topology is not an independently witnessed field deployment |

## Source of truth

The canonical internal capability registry supplies shared IDs, policies, executors, the generic HTTP/CLI dispatch path, Agno loading, readiness identity, and the generated documentation catalog. Parity tests compare the independent router, Agno, and readiness inventories. Status claims fail closed: natural-language availability requires named conversational-path test evidence, and benchmark exercise requires a frozen execution receipt. The current registry therefore makes no per-capability benchmark-exercised claim. Public-adapter preflight rules exist, but their individual natural-language flags remain false until selection, execution, evidence admission, and final-answer use are each tested. Some ergonomic named CLI parsers and legacy HTTP argument normalizers remain explicit adapters; they are tested, but are not generated wholesale from the registry. This page deliberately reports broad capability families; the exact catalog is checked against the runtime registry on every documentation build. The checker can also validate an exported registry manifest supplied with `--capability-manifest`.

See the exact [generated capability catalog](capability-catalog.md), [Tools and adapters](tools-and-adapters.md), and the [developer extension guide](developer/extending.md).
