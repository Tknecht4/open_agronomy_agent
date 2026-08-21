# Generated capability catalog

This table is generated from `src/agronomy_agent/capability_registry.py`. “Implemented” means an executor contract exists; “tested” means the registry names focused test evidence; “natural language” requires a named conversational-path test; “benchmark” requires a frozen execution receipt showing invocation through the claimed interface. These columns do not prove present availability, live-provider operation, agronomic validity, or field outcomes.

<!-- BEGIN GENERATED CAPABILITY REGISTRY -->

| Capability | Kind | Runtime surfaces | Network | Offline | Implemented | Tested | Natural language | Benchmark |
|---|---|---|---|---|---:|---:|---:|---:|
| `aafc_annual_crop_inventory` | public_adapter | cli, http, agno, readiness | required | blocked | yes | yes | no | no |
| `aafc_nasdi_agroclimate` | public_adapter | http, agno, readiness | required | cached | yes | yes | no | no |
| `agronomic_calculator` | calculator | cli, http, agno | none | native | yes | yes | yes | no |
| `canada_conservation_practice_context_source` | source_card | http, agno, readiness | none | native | yes | yes | no | no |
| `canada_et_or_water_use_source_needed` | public_adapter | cli, http, agno, readiness | required | cached | yes | yes | no | no |
| `cansis_soil_landscapes_canada` | public_adapter | cli, http, agno, readiness | required | blocked | yes | yes | no | no |
| `conservation_practice_context_adapter` | source_card | http, agno, readiness | none | native | yes | yes | no | no |
| `cropland_data_layer_geometry` | public_adapter | cli, http, agno, readiness | required | blocked | yes | yes | no | no |
| `cropland_data_layer_point` | public_adapter | cli, http, agno, readiness | required | blocked | yes | yes | no | no |
| `cross_border_crop_history_public_layers` | source_card | http, agno, readiness | none | native | yes | yes | no | no |
| `daymet_single_pixel_daily` | public_adapter | cli, http, agno, readiness | required | blocked | yes | yes | no | no |
| `diagnostic_frame` | decision_frame | cli, http, agno | none | native | yes | yes | no | no |
| `diagnostic_lab_and_sample_quality` | source_card | http, agno, readiness | none | native | yes | yes | no | no |
| `disease_risk_context_adapter` | source_card | http, agno, readiness | none | native | yes | yes | no | no |
| `epa_ppls_product_search` | public_adapter | cli, http, agno, readiness | required | blocked | yes | yes | no | no |
| `farm_economics_sensitivity_and_programs` | source_card | http, agno, readiness | none | native | yes | yes | no | no |
| `fertility_frame` | decision_frame | cli, http, agno | none | native | yes | yes | no | no |
| `fertility_guard` | guard | router, agno | none | native | yes | yes | yes | no |
| `field_data_guard` | guard | router, agno | none | native | yes | yes | yes | no |
| `field_record_audit_card` | source_card | http, agno, readiness | none | native | yes | yes | no | no |
| `forage_feed_safety_extension` | source_card | http, agno, readiness | none | native | yes | yes | no | no |
| `forage_livestock_extension_corpus` | source_card | http, agno, readiness | none | native | yes | yes | no | no |
| `guard_notes` | guard | agno | none | native | yes | yes | no | no |
| `health_canada_pmra_label_search` | public_adapter | cli, http, agno, readiness | required | blocked | yes | yes | no | no |
| `ipm_beneficials_and_thresholds` | source_card | http, agno, readiness | none | native | yes | yes | no | no |
| `label_guard` | guard | router, agno | none | native | yes | yes | yes | no |
| `nasa_power_daily` | public_adapter | cli, http, agno, readiness | required | blocked | yes | yes | no | no |
| `nass_quickstats_crop_stats` | public_adapter | cli, http, agno, readiness | required | blocked | yes | yes | no | no |
| `nrcs_soil_survey_geometry` | public_adapter | cli, http, agno, readiness | required | blocked | yes | yes | no | no |
| `nrcs_soil_survey_point` | public_adapter | cli, http, agno, readiness | required | blocked | yes | yes | no | no |
| `nutrient_4r_drainage_water_quality` | source_card | http, agno, readiness | none | native | yes | yes | no | no |
| `nutrient_4r_guard` | guard | router, agno | none | native | yes | yes | yes | no |
| `openet_point_timeseries` | public_adapter | cli, http, agno, readiness | required | blocked | yes | yes | no | no |
| `partial_budget_calculator` | source_card | http, agno, readiness | none | native | yes | yes | no | no |
| `pesticide_safety_and_drift_recordkeeping` | source_card | http, agno, readiness | none | native | yes | yes | no | no |
| `pesticide_safety_guard` | guard | router, agno | none | native | yes | yes | yes | no |
| `postharvest_quality_storage_mycotoxin` | source_card | http, agno, readiness | none | native | yes | yes | no | no |
| `postharvest_storage_quality_corpus` | source_card | http, agno, readiness | none | native | yes | yes | no | no |
| `precision_ag_audit_and_trial_design` | source_card | http, agno, readiness | none | native | yes | yes | no | no |
| `produce_safety_and_irrigation_water` | source_card | http, agno, readiness | none | native | yes | yes | no | no |
| `public_program_context_source` | source_card | http, agno, readiness | none | native | yes | yes | no | no |
| `public_statistics_context_boundary` | source_card | http, agno, readiness | none | native | yes | yes | no | no |
| `public_variety_trial_ingest` | source_card | http, agno, readiness | none | native | yes | yes | no | no |
| `resistance_management_guard` | guard | router, agno | none | native | yes | yes | yes | no |
| `retrieve_context` | retrieval | cli, http, agno | none | native | yes | yes | no | no |
| `route_question` | router | cli, http, agno | none | native | yes | yes | no | no |
| `salinity_sodicity_guard` | guard | router, agno | none | native | yes | yes | yes | no |
| `saskatchewan_official_crop_guidance` | source_card | http, agno, readiness | none | native | yes | yes | no | no |
| `seed_quality_and_trait_stewardship` | source_card | http, agno, readiness | none | native | yes | yes | no | no |
| `soil_context` | retrieval | cli, http | none | native | yes | yes | no | no |
| `soil_structure_guard` | guard | router, agno | none | native | yes | yes | yes | no |
| `soil_water_salinity_irrigation_quality` | source_card | http, agno, readiness | none | native | yes | yes | no | no |
| `source_availability_and_tool_choice` | source_card | http, agno, readiness | none | native | yes | yes | no | no |
| `specialty_crop_extension_corpus` | source_card | http, agno, readiness | none | native | yes | yes | no | no |
| `spray_window` | decision_frame | cli, http, agno | none | native | yes | yes | no | no |
| `statcan_field_crop_statistics` | public_adapter | cli, http, agno, readiness | required | snapshot | yes | yes | no | no |
| `weather_guard` | guard | router, agno | none | native | yes | yes | yes | no |

<!-- END GENERATED CAPABILITY REGISTRY -->

See [Capability status](capabilities.md) for availability and claim semantics and [Tools and adapters](tools-and-adapters.md) for evidence boundaries.
