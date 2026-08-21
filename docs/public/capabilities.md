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
| Gemma 4 E2B local generation | MLX model adapter and pinned profile | Requires explicit ~3.34 GiB snapshot provision and Apple Silicon runtime | Model identity/profile and generation-path checks | RC1 and the completed RC3 development checkpoint at their frozen revisions/commits | Generated advice remains advisory; RC3 includes no semantic-quality judgment |
| Fast optional local model | Selectable pinned profile | Requires separate download | Profile/UI contracts | Gemma 3 270M was exercised in RC1 and RC3; other optional profiles were not | Quality and role are profile-specific |
| Governed corpus retrieval | Policy partition plus local/Agno search | Admitted checked-in corpus available; optional private overlay local only | Corpus governance and retrieval tests | RC3 expected-source presence: 22/26 positive probes; required patterns: 46/50 | Presence is not relevance, use, answer quality, or local calibration |
| Knowledge graph search | Manifest-bound graph composition and name/token search | Seed and released SoilWise manifests are present | Manifest, checksum, collision, provenance, and retrieval tests | Governed context included graph hits | Graph authority roles are contextual; a relationship is not a field observation or recommendation |
| Agronomic calculator | Typed decimal executor, CLI/API adapters, and bounded explicit-request planner | Offline with supplied inputs | Deterministic operations, services, registry parity, and natural-language end-to-end path | RC1 route failed at 0/16; RC3 full-system frozen parser scored 14/16 and typed-payload audit found 16/16 within tolerance | The audit exposes two unit-alias false negatives; it is not a replacement for the frozen result and the calculator does not choose target rates |
| Guard capabilities | Query-triggered decision checks | Offline | Router/guard/evidence regressions | RC3 expected local guards were complete on 134/154 eligible case routes | Completeness is a trace contract, not evidence that each intervention improved the answer |
| Weather and climate adapters | NASA POWER, Daymet and related adapters | Network/provider/cache dependent | Offline-fixture/readiness smokes | Adapters traced, not live-executed in RC1 | Gridded context is not field sensor or guaranteed forecast |
| Soil/crop map adapters | Local pack and public soil/crop-cover adapters | Varies by installed pack, network, geography | Fixture, package, and intersection gates | No primary executable-geometry cases | Map class/component is a regional prior |
| Statistics adapters | Canadian/US regional statistics paths | Snapshot/cache/provider dependent | Fixture/readiness tests | Not live-executed in RC1 | Regional distributions do not establish a field value |
| Label metadata adapters | PMRA/EPA metadata search paths | Network/cache/provider/jurisdiction dependent | Fixture/readiness tests | Not live-executed in RC1 | Metadata is not the current full label or legal interpretation |
| Field history | Append-oriented field/session/event persistence | Local DB by default; optional hosted dependencies | Field event, measurement, and storage tests | Lineage regression lane | User records are observations; reuse must preserve time/source |
| Image observation/RAG | Service and UI paths exist | Backend/model/config dependent | Focused image/service contracts | Not a primary RC1 capability | Image inference is not diagnosis and needs representative context |
| Offline/field-LAN | Explicit offline network mode, TLS/pairing path | Requires built client, trusted cert, operator setup | Launcher/topology/package tests | Not portable-field outcome proof | A lab topology is not an independently witnessed field deployment |

## Source of truth

The canonical internal capability registry supplies shared IDs, policies, executors, the generic HTTP/CLI dispatch path, Agno loading, readiness identity, and the generated documentation catalog. Parity tests compare the independent router, Agno, and readiness inventories. Status claims fail closed: natural-language availability requires named conversational-path test evidence, and registry-level benchmark exercise requires a frozen per-capability execution receipt. RC3 supplies system-level observations and selected trace contracts, but it does not automatically promote the registry's individual benchmark-exercised flags. Public-adapter preflight rules exist, but their individual natural-language flags remain false until selection, execution, evidence admission, and final-answer use are each tested. Some ergonomic named CLI parsers and legacy HTTP argument normalizers remain explicit adapters; they are tested, but are not generated wholesale from the registry. This page deliberately reports broad capability families; the exact catalog is checked against the runtime registry on every documentation build. The checker can also validate an exported registry manifest supplied with `--capability-manifest`.

See the exact [generated capability catalog](capability-catalog.md), [Tools and adapters](tools-and-adapters.md), and the [developer extension guide](developer/extending.md).
