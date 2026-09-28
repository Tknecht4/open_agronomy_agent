# US observed field-data candidates — metadata pass, 2026-09-27

Status: 13 additive source records in `us-candidates.json`; source metadata and file manifests were inspected, but this researcher did not download data files, inspect schemas, admit a source, or alter the 51-entry catalog. `independent_group_count` means verified distinct field/farm/station groups, not plots or site-years. `null` is intentional where repetitions cannot be resolved. Public pages establish source claims; proposed uses are interpretations that require file inspection and grouped validation.

## Highest-value handoff

- **Bronson Field 113 2016**: primary [Ag Data Commons record](https://agdatacommons.nal.usda.gov/articles/dataset/The_Bronson_Files_Dataset_8_Field_113_2016/25213130) documents plot polygons, yield, N/irrigation, spectra and soil nitrate, with U.S. Public Domain license. [Data.gov distribution](https://catalog.data.gov/dataset/the-bronson-files-dataset-8-field-113-2016) lists the file URLs. Exact [Figshare API](https://api.figshare.com/v2/articles/25213130/files) sizes: dictionary 5,192 B, activities log 5,249 B, MegaTable 717,730 B, README 23,099 B, map 1,379,539 B. The three sensor/intermediate ZIPs are 51,726,518 / 18,556,957 / 15,051,193 B and exceed or nearly consume the sample budget. Count all Bronson Field 113 years and related Maricopa fields as one farm family until physical independence is demonstrated.
- **Arkansas soybean P**: [primary record](https://agdatacommons.nal.usda.gov/articles/dataset/Soybean_Yield_Response_to_Fertilizer-Phosphorus_Rate_on_Soils_having_different_Mehlich-3_Phosphorus_Values_in_Arkansas/24667830) reports 39 trials/site-years with plot yield, P rates, soil chemistry and tissue nutrients. Its metadata includes many site points, but station/farm repetitions need deduplication. One public 656,705 B workbook: `https://ndownloader.figshare.com/files/44545148`. SoyMap R1 is predicted; do not treat as measured bloom date.
- **Ohio corn N**: [Dryad record](https://datadryad.org/dataset/doi:10.5061/dryad.3bk3j9kxg) reports 431 rainfed trial site-years, 5,778 yield/N rows and an on-farm/station flag. [Dataset API metadata](https://datadryad.org/api/v2/datasets/doi%3A10.5061%2Fdryad.3bk3j9kxg) reports CC0. Files: Crop_Data.csv 134,861 B (`https://datadryad.org/api/v2/files/4139094/download`), Experimental_Design.csv 36,120 B (`https://datadryad.org/api/v2/files/4139093/download`), README.md 6,460 B (`https://datadryad.org/api/v2/files/4139101/download`). Some observations are treatment means and location is county only; no honest field-imagery join.
- **Texas sugarcane**: [primary record](https://agdatacommons.nal.usda.gov/articles/dataset/Data_from_Sugarcane_Genotype_by_Environment_interaction_G_E_in_Clonal_Trials_in_the_U_S_Texas_Rio_Grande_Valley/28074515) describes off-station farms at 4–5 locations per planting series and measured cane/sugar yield. [Figshare API](https://api.figshare.com/v2/articles/28074515) gives U.S. Public Domain and a 337,026 B raw workbook (`https://ndownloader.figshare.com/files/51334985`). A second 100,797 B workbook is a derived ratooning index over the same records, not new independent observations.
- **Iowa stover trial**: [primary record](https://agdatacommons.nal.usda.gov/articles/dataset/Thirteen-year_Stover_Harvest_and_Tillage_Effects_on_Corn_Agroecosystem_Sustainability_in_Iowa/24856419) gives 13 years of plot yield/biomass/soil/treatments at one farm. Plot status changed; join `Field 70-71 Plot Status 2007-2021.xlsx` before analysis. Small corn yield CSV is 18,917 B (`https://ndownloader.figshare.com/files/44532917`), crop yield workbook 70,489 B (`https://ndownloader.figshare.com/files/44532929`).

## Screening and residuals

The JSON also records Nebraska P/K/S corn (34 site-years; main 51.5 MB XLS exceeds sample cap), NY/WI organic soybean starter N (five site-years), North Central Sclerotinia soybean trials (25 site-years), three-site high-tunnel tomato/vetch, two-site New Mexico chile cover crops, a selected maize robotic phenotyping workbook, two-station Oklahoma/Texas cotton spectra and measured growth, and Colorado maize water-productivity plots. These are source-distinct records, but many lack plot polygons or exact coordinates. Only Bronson has stated plot polygons; the Arkansas record has site points; Colorado has a plot-map PDF needing georeference review. The Nebraska and Ohio trials might overlap geographically with the existing Midwest N-rate archive, but are separate interventions/cohorts by source description; check site IDs and dates before evaluation merging. The robotic paper's 142 fields and ~200,000 units describe its overall study, while deposited files are selected case studies; accessible independent groups are unknown. The New Mexico Dryad source-specific license is pending because the repository API returned HTTP 429 during research; a repository-wide license assumption was deliberately not promoted. Several Dryad API endpoints briefly returned HTTP 429; file sizes/URLs already verified before the throttle are in JSON. Source pages showed direct links for the New Mexico files, but exact byte sizes remain null. USDA cotton source has measured 2019 Oklahoma and 2022 Texas spectra/growth but no verified yield column; it is not labeled a yield dataset.

Prior-catalog overlaps excluded from the new count: Akron, 10,675-field corn stalk nitrate survey, Transforming Drainage, Bushland crop-growth family, G2F 2016, Morrow, KBS, Dryad Midwest N-rate, Dryad multistate maize, DRIVES, GRACEnet network and station children. The owner is separately handling Dryad soybean `10.5061/dryad.hx3ffbgrk`, Zenodo `10.5281/zenodo.15367284`, Dryad global legumes `10.5061/dryad.mf42f`, and Bowles `10.6078/D1H409`; none appears in this JSON. A Zenodo farm-gradient search hit was Brazilian despite US instrument citations and was excluded. Modeled crop maps, county averages, and simulation outputs were excluded from the additive candidate count.

## Exact web search queries issued

Recovered from all 14 completed search calls in the local tool transcript, including empty-result searches (56 queries; no unrecoverable gaps):

```text
site:agdatacommons.nal.usda.gov/articles/dataset/ "Bronson Files" cotton yield irrigation
site:agdatacommons.nal.usda.gov/articles/dataset/ "on-farm" "yield" "field" nitrogen
site:agdatacommons.nal.usda.gov/articles/dataset/ "yield monitor" "field boundaries"
site:datadryad.org/dataset/doi "on-farm" "yield" corn field nitrogen
site:datadryad.org/dataset/doi "site-years" "yield" "nitrogen" corn dataset US
site:agdatacommons.nal.usda.gov/articles/dataset/ "on-farm" "plot" "yield"
site:agdatacommons.nal.usda.gov/articles/dataset/ "field" "yield" "soil" "irrigation"
site:datadryad.org/dataset/doi "on-farm experiments" "yield" "georeferenced"
site:agdatacommons.nal.usda.gov/articles/dataset/ "field experiments" "yield" "soil" "sites"
site:datadryad.org/dataset/doi "site-years" "soybean" "yield" fertilizer United States
site:datadryad.org/dataset/doi "site-years" "corn" "yield" "soil" Nebraska
site:agdatacommons.nal.usda.gov/articles/dataset/ "on-farm" "site-years" yield
https://api.figshare.com/v2/articles/25213130 files download_url
"The Bronson Files, Dataset 8" "files" "csv"
"The Bronson Files, Dataset 8" "plot" "csv"
"25213130" "ndownloader/files"
site:datadryad.org/dataset/doi "site-years" "yield" "plot" "phosphorus" soybean United States
site:datadryad.org/dataset/doi "site-years" "plot-level" "yield" corn cover crop
site:agdatacommons.nal.usda.gov/articles/dataset/ "multisite" "yield" "plot"
"Thirteen-year Stover Harvest and Tillage Effects" "Corn Yield"
site:datadryad.org/dataset/doi "plot-level" "site-years" "yield" soybean field
site:datadryad.org/dataset/doi "plot-level" "site-years" "yield" wheat United States
site:agdatacommons.nal.usda.gov/articles/dataset/ "field experiments" "sites" "yield" "soil" "2019"
site:zenodo.org/records/ "field" "plot" "yield" "nitrogen" "USA"
"10.5061/dryad.3bk3j9kxg" "CC0"
"10.5061/dryad.xksn02vn6" "CC0"
"10.5061/dryad.p30c6" "CC0"
"10.5061/dryad.3tn78n2" "CC0"
site:agdatacommons.nal.usda.gov/articles/dataset/ "field experiments" "yield" "sites" "phosphorus"
site:agdatacommons.nal.usda.gov/articles/dataset/ "site-years" "yield" "soybean"
site:datadryad.org/dataset/doi "site-years" "plot" "crop yield" soil
site:datadryad.org/dataset/doi "multi-site" "plot" "yield" cover crop
https://api.datacite.org/dois/10.5061%2Fdryad.3bk3j9kxg
doi 10.5061/dryad.3bk3j9kxg rightsList
doi 10.5061/dryad.p30c6 license
site:datadryad.org "Data is made available under the Creative Commons Public Domain Dedication"
site:agdatacommons.nal.usda.gov/articles/dataset/ "field experiments" "sites" "cotton" "yield"
site:agdatacommons.nal.usda.gov/articles/dataset/ "field experiments" "sites" "wheat" "yield"
site:datadryad.org/dataset/doi "site-years" "yield" "cover crop" "United States"
site:datadryad.org/dataset/doi "site-years" "yield" "corn" "on-farm"
site:agdatacommons.nal.usda.gov/articles/dataset/ "39 field experiments" soybean phosphorus
site:agdatacommons.nal.usda.gov/articles/dataset/ "experiments were conducted at" "sites" "yield"
site:datadryad.org/dataset/doi "site-years" "yield" "nitrogen" "soybean" "United States"
site:datadryad.org/dataset/doi "site-years" "yield" "disease" "corn"
site:datadryad.org/dataset/doi "plot-level yield" "site-years" maize
site:datadryad.org/dataset/doi "plot-level yield" "site-years" wheat
site:datadryad.org/dataset/doi "plot-level yield" "site-years" soybean
site:agdatacommons.nal.usda.gov/articles/dataset/ "on-farm experiments" "corn yield"
site:datadryad.org/dataset/doi "field experiments" "site-years" "yield" United States dataset 2025
site:agdatacommons.nal.usda.gov/articles/dataset/ "multi-location" "yield" "field"
site:datadryad.org/dataset/doi "on-farm" "site-years" "soybean yield"
site:datadryad.org/dataset/doi "sites" "corn yield" "soil" "cover crop"
LTAR Common Experiment crop yield field plot data public site:agdatacommons.nal.usda.gov/articles/dataset
LTAR farm field yield management data csv site:agdatacommons.nal.usda.gov/articles/dataset
site:agdatacommons.nal.usda.gov/articles/dataset/ "LTAR" "yield" "plot"
USDA on farm cover crop plot yield dataset multiple farms ag data commons
```

The four exact-DOI Dryad CC0 searches above returned empty; dataset-specific license status came from the API where available. Metadata API calls retrieved no dataset bytes. Observation = source pages and manifests. Model = no crop model run. Interpretation = proposed offline use and grouping caveats in JSON.
