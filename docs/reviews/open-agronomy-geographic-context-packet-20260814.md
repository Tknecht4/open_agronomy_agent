# Trusted geographic context packet — 2026-08-14

## Purpose

`canada-context-boundaries-v1` is an optional offline spatial profile. It
turns a saved field geometry into three compact, versioned organizational
identifiers:

- a Statistics Canada 2021 province or territory (`PR_<PRUID>`);
- a Statistics Canada 2021 Census Agricultural Region (`CAR_<CARUID>`); and
- an AAFC terrestrial ecoregion v2.2 (`ECOREGION_<id>`).

The pack is deliberately not a gridded prediction store. It contains compact
SQLite/RTree boundary layers so a clone can locate a field without calling a
remote map service. The installer validates exact raw hashes, source-entry
hashes, geometry/schema contracts, and the installed pack receipt before the
application uses it.

## What reaches the model

For an authorized saved map field only, the server recomputes intersections
against locally installed source bytes and attaches a narrow
`open_agronomy_agent.trusted_geographic_context.v1` projection. The core
context packer renders that projection with an explicit `CONTEXT ONLY` label.
It contains only:

- source layer ID and official source label;
- stable code and name;
- province/CAR/ecoregion hierarchy identifiers; and
- rounded polygon-geometry coverage when available.

The compiler rejects client-only snapshots, non-bundled intersections, unknown
layers, malformed codes, and unallowlisted properties. It removes a
client-supplied projection before deciding whether to create a new one. Normal
chat avoids rendering the same three intersections a second time once the
trusted packet is present.

If a field crosses a CAR or ecoregion boundary, the packet retains up to two
mapped overlaps for that layer and states that no single regional label was
selected. It does not collapse a cross-boundary field to the largest overlap;
additional overlaps beyond the bounded display limit are called out explicitly.

## Role and current boundary

The packet lets a response identify the region behind an observation and lets
future source admission bind documents or structured snapshots to an exact
province, CAR, or ecoregion key. It does **not** currently change the lexical
RAG query, document eligibility, or evidence ranking. Documents remain
governed by their explicit crop, jurisdiction, date, rights, and geographic
applicability metadata.

It is not a surveyed field boundary, field observation, soil test, crop
production proof, farm-practice record, legal determination, diagnosis, or
management authority. A broad ecoregion or CAR must never be used to infer a
field soil property or a prescription.

## Next safe use

Add geography-aware retrieval only after source records declare machine-
resolvable applicability using the same versioned keys (or a separately
published boundary) and the retrieval filter proves both positive and
out-of-region controls. Basin plans with narrative-only scope and SLC/AESD
aggregate values do not satisfy that condition.
