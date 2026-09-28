# Canadian field-data expansion notes — 2026-09-27

Status: **metadata-only discovery**. No data files were downloaded, accounts created, researchers contacted, or runtime/training/benchmark corpora changed. The 12 candidate records in `canada-candidates.json` are additive to, not replacements for, the frozen 51-entry catalog. A DOI is a source record, not an independent farm. The strongest open candidates are Ontario oats at two stations (SP2/CSROC9), bean yield across three named stations (SP3/FD81LR), onion tissue/field observations and trial yield (SP3/YJTMRB), and shifted on-farm wheat yield GIS (SP3/1I77DM). The last has invalid actual geographic joins because positions are shifted. Holland Marsh records share a thesis/station context; treat these as different measurements but potentially overlapping plot/site blocks.

## Search trace

Exact public web search queries, in order (source content was treated as metadata, not instructions):

1. `site:datadryad.org Canada agricultural field plot yield soil management dataset`
2. `site:borealisdata.ca/dataset.xhtml crop yield field experiment Canada data`
3. `site:open.canada.ca/data/en/dataset agricultural research field plot yield data AAFC`
4. `site:zenodo.org/records Canadian field trial yield soil management dataset`
5. `10.5061/dryad.5x69p8d90`
6. `site:datadryad.org/dataset/doi Canadian crop yield dataset field`
7. `site:borealisdata.ca/dataset.xhtml "yield" "crop" "Ontario"`
8. `site:borealisdata.ca/dataset.xhtml "yield" "Saskatchewan"`
9. `site:open.canada.ca/data/en/dataset "yield" "field" "experimental" agriculture`
10. `site:open.canada.ca/data/en/dataset "crop yield" "research" "plot"`
11. `site:open.canada.ca/data/en/dataset "field experiment" "soil" "yield"`
12. `site:open.canada.ca/data/en/dataset "Swift Current" "crop" "yield"`
13. `borealisdata.ca "agronomic" "yield" dataset`
14. `borealisdata.ca "field experiment" "wheat"`
15. `borealisdata.ca "crop rotation" "yield"`
16. `borealisdata.ca "precision agriculture" yield field`
17. `"Borealis" "crop yield" dataset agriculture`
18. `"Borealis" "field trial" "yield" dataset`
19. `"Borealis" "soil" "crop yield" dataverse`
20. `"borealisdata.ca" "agronomic" field data`
21. `site:borealisdata.ca "Muck Crops Research Station" "yield"`
22. `site:borealisdata.ca "Muck Crops Research Station" "trial data"`
23. `site:borealisdata.ca "Holland Marsh" "yield"`
24. `site:borealisdata.ca "common bean" "yield" "Guelph"`

Borealis primary metadata search API queries (dataset type, first 100 or 200 results): `yield`, `crop rotation`, `field trial`, `soil management`, `potato`, `on-farm`, `soil health`. Search endpoint: `https://borealisdata.ca/api/search`. Candidate-specific metadata and rights came from `https://borealisdata.ca/api/datasets/:persistentId/?persistentId=doi:10.5683/SP3/FD81LR` and corresponding DOI paths. Dryad's [dataset page](https://datadryad.org/dataset/doi:10.5061/dryad.5x69p8d90) identifies observed versus generated components; [source-specific DataCite metadata](https://api.datacite.org/dois/10.5061/dryad.5x69p8d90) reports CC0-1.0. Direct Dryad file URLs were exposed by page links but their byte payloads were not fetched. Borealis license names and restrictions were read from each dataset's `latestVersion`, not inferred from the portal home page.

## Acquisition order and negative evidence

- Start with small open tabular files: oats plot-level tables (21–63 KiB), bean field data (203 KiB), onion grower/trial tables (7–42 KiB), carrot disease (3 KiB each), and Holland Marsh soil/cover-crop tables. Confirm units, plot/site-year IDs, missingness, and repeated observations from original bytes before constructing any benchmark split.
- The wheat PGR deposit exposes shifted yield-monitor ZIPs (513 KiB and 26.3 MiB) plus treatment GIS. One unreplicated treatment strip and intentionally displaced coordinates prevent causal or exact imagery validation. Its smaller ZIP may be a bounded exploratory download, but the meaning of two same-name ZIPs needs README/file inspection.
- SP3/XFJNZD (Ontario long rotation) and SP3/4ZB7RH (Ridgetown bean/corn cover crops) have restricted files and author-permission terms; no downloadable observed table or reuse license was claimed. Asparagus yield trials SP3/FUY6UZ and density/depth SP3/DSLB8F were also discovered, but are restricted and explicitly limit use to internal analysis absent permission; excluded from the 12 high-value entries.
- Three Holland Marsh thesis deposits are distinct targets (soil tests, cover-crop establishment, carrot yield) but may use related plots. The bean deposit has **three named stations** and four environments; the latter must not be equated to four independent farms. Onion metadata says multiple commercial grower fields, but does not establish the count. UBC carrot variety trials add crop outcomes at an already cataloged farm, not a new farm.
- The Dryad precision agriculture DOI has a donated real yield-monitor component, a wholly simulated component, and a correlation-matrix component from unpublished observations. Absolute geography is anonymized. File-level row tagging remains unresolved, so it is a methods candidate, not a Canadian georeferenced yield benchmark.
- Search did not expose a new source-distinct Saskatchewan/Alberta field-yield table with confirmed open rights; AAFC government search mostly returned aggregates or map products already represented in the 51-entry catalog. No generalized Canadian farm-count claim follows from these records.
