import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { StrictMode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { OpenAgronomyApp } from './OpenAgronomyApp'
import { PHASE6_SCRATCHPAD_STORAGE_KEY } from './offlineScratchpad'
import { PHASE6_OFFLINE_STORAGE_QUARANTINE_KEY } from './offlineStorageRepair'

vi.mock('./fieldGeometry', async () => {
  const actual = await vi.importActual<typeof import('./fieldGeometry')>('./fieldGeometry')
  return {
    ...actual,
    estimatePolygonAcres: (points: Array<{ lat: number; lon: number }>): number => points.length * 12.5,
  }
})

vi.mock('./LeafletFieldMap', async () => {
  const React = await import('react')
  return {
    LeafletFieldMap: ({
      geometry,
      onGeometryChange,
      onStatusChange,
    }: {
      geometry: { kind: string; point?: { lon: number }; points?: Array<{ lon: number }> }
      onGeometryChange?: (geometry: unknown) => void
      onStatusChange?: (status: string) => void
    }) =>
      React.createElement(
        'div',
        {
          'data-testid': 'mock-leaflet-map',
          'data-geometry-kind': geometry.kind,
          'data-point-count': geometry.points?.length || 0,
          'data-first-lon': geometry.kind === 'polygon' ? geometry.points?.[0]?.lon : geometry.point?.lon || '',
        },
        React.createElement('span', null, 'mock map'),
        React.createElement(
          'button',
          {
            type: 'button',
            onClick: () => {
              onGeometryChange?.({
                kind: 'polygon',
                points: [
                  { lat: 42.08, lon: -93.68 },
                  { lat: 42.08, lon: -93.66 },
                  { lat: 42.1, lon: -93.66 },
                  { lat: 42.1, lon: -93.68 },
                ],
                acres: 50,
              })
              onStatusChange?.('Drawn boundary ready for intersection.')
            },
          },
          'Mock draw boundary',
        ),
        React.createElement(
          'button',
          {
            type: 'button',
            onClick: () => {
              onGeometryChange?.({ kind: 'point', point: { lat: 42.02, lon: -93.72 } })
              onStatusChange?.('Point ready for intersection.')
            },
          },
          'Mock drop point',
        ),
      ),
  }
})

vi.mock('./FieldSyncPanel', async () => {
  const React = await import('react')
  return {
    FieldSyncPanel: () => React.createElement('div', { 'data-testid': 'mock-field-sync-panel' }, 'record transfer'),
    SoilTestEntryPanel: () => null,
  }
})

const createTestStorage = (): Storage => {
  const values = new Map<string, string>()
  return {
    get length() {
      return values.size
    },
    clear: () => values.clear(),
    getItem: (key: string) => values.get(key) ?? null,
    key: (index: number) => Array.from(values.keys())[index] ?? null,
    removeItem: (key: string) => values.delete(key),
    setItem: (key: string, value: string) => values.set(key, String(value)),
  }
}

const jsonResponse = (payload: unknown): Response =>
  ({
    ok: true,
    status: 200,
    json: async () => payload,
    text: async () => JSON.stringify(payload),
  }) as Response

const northRing = [
  [-93.72, 42.02],
  [-93.71, 42.02],
  [-93.71, 42.03],
  [-93.72, 42.03],
  [-93.72, 42.02],
]

const southRing = [
  [-93.68, 42.08],
  [-93.66, 42.08],
  [-93.66, 42.1],
  [-93.68, 42.1],
  [-93.68, 42.08],
]

const bootConfig = {
  modes: ['baseline', 'agronomic_rag', 'mock'],
  models: ['mock'],
  model_profiles: [{ id: 'mock', role: 'test', max_tokens: 120 }],
  rag_configs: ['configs/rag_governed_runtime_v2.yaml'],
  default_rag_config: 'configs/rag_governed_runtime_v2.yaml',
  network: { mode: 'online', external_calls_allowed: true, telemetry_enabled: false },
}

const adapterReadiness = {
  schema_version: 'open_agronomy_agent.public_adapter_readiness.v1',
  summary: {
    adapter_count: 0,
    ready_count: 0,
    needs_key_count: 0,
    key_gated_count: 0,
    field_context_required_count: 0,
    smoke_check_count: 0,
    smoke_passed_count: 0,
    smoke_missing_count: 0,
    smoke_failed_count: 0,
  },
  smoke_checks: [],
  adapters: [],
  boundary: 'Test adapter readiness.',
}

const emptyDemoFields = {
  schema_version: 'open_agronomy_agent.demo_fields.v1',
  storage: {
    mode: 'account_workspace',
    workspace_id: 'workspace-demo',
    workspace_name: 'My agronomy workspace',
    boundary: 'Stored fields are local workspace records.',
  },
  fields: [],
}

const uploadPayload = {
  schema_version: 'open_agronomy_agent.boundary_upload.v1',
  filename: 'two-fields.geojson',
  content_type: 'application/geo+json',
  source_format: 'geojson',
  feature_count: 2,
  parsed_feature_count: 2,
  selected_feature_id: 'geojson:0',
  geometry: { type: 'Polygon', coordinates: [northRing] },
  geometry_type: 'Polygon',
  bbox: [-93.72, 42.02, -93.71, 42.03],
  acres: 25,
  feature_collection: {
    type: 'FeatureCollection',
    features: [
      {
        type: 'Feature',
        id: 'geojson:0',
        properties: { name: 'North field' },
        geometry: { type: 'Polygon', coordinates: [northRing] },
      },
      {
        type: 'Feature',
        id: 'geojson:1',
        properties: { name: 'South field' },
        geometry: { type: 'Polygon', coordinates: [southRing] },
      },
    ],
  },
  feature_summaries: [
    {
      id: 'geojson:0',
      label: 'North field',
      geometry_type: 'Polygon',
      bbox: [-93.72, 42.02, -93.71, 42.03],
      acres: 25,
      selected: true,
      properties: { name: 'North field' },
    },
    {
      id: 'geojson:1',
      label: 'South field',
      geometry_type: 'Polygon',
      bbox: [-93.68, 42.08, -93.66, 42.1],
      acres: 100,
      selected: false,
      properties: { name: 'South field' },
    },
  ],
  regional_intersections: [
    {
      layer_id: 'nrcs_mlra',
      layer_label: 'USDA NRCS Major Land Resource Areas',
      system: 'NRCS MLRA',
      code: 'MLRA_103',
      name: 'Central Iowa and Minnesota Till Prairies',
      label: 'Central Iowa and Minnesota Till Prairies',
      source_url: 'https://www.nrcs.usda.gov/resources/data-and-reports/major-land-resource-area-mlra',
      confidence: 0.94,
      coverage_estimate: 1,
      match_reason: 'Official ArcGIS FeatureServer spatial intersection',
      source: 'official_arcgis_feature_service',
    },
  ],
  regional_feature_collection: { type: 'FeatureCollection', features: [] },
  geo_errors: [],
  official_layer_status: [
    {
      layer_id: 'nrcs_mlra',
      label: 'USDA NRCS Major Land Resource Areas',
      system: 'NRCS MLRA',
      status: 'matched',
      match_count: 1,
      message: 'matched official polygon',
    },
  ],
  warnings: ['2 upload features were detected; the largest polygon or first point was selected by default.'],
  coordinate_reference: { assumed: 'EPSG:4326', label: 'WGS84 longitude/latitude', reprojected: false },
  status_message: 'two-fields.geojson loaded with 2 features.',
  boundary: 'Uploaded boundaries are field context, not legal boundary evidence.',
}

const uploadLayerErrorPayload = {
  ...uploadPayload,
  regional_intersections: [],
  regional_feature_collection: { type: 'FeatureCollection', features: [] },
  geo_errors: [{ layer_id: 'nrcs_mlra', message: 'NRCS MLRA FeatureServer timeout' }],
  official_layer_status: [
    {
      layer_id: 'nrcs_mlra',
      label: 'USDA NRCS Major Land Resource Areas',
      system: 'NRCS MLRA',
      status: 'error',
      match_count: 0,
      message: 'NRCS MLRA FeatureServer timeout',
      source_url: 'https://www.nrcs.usda.gov/resources/data-and-reports/major-land-resource-area-mlra',
    },
  ],
  status_message: 'two-fields.geojson loaded; official regional layer intersection needs attention.',
}

const peiRing = [
  [-63.14, 46.24],
  [-63.12, 46.24],
  [-63.12, 46.26],
  [-63.14, 46.26],
  [-63.14, 46.24],
]

const peiUploadPayload = {
  ...uploadPayload,
  filename: 'pei-field.geojson',
  feature_count: 1,
  parsed_feature_count: 1,
  geometry: { type: 'Polygon', coordinates: [peiRing] },
  bbox: [-63.14, 46.24, -63.12, 46.26],
  feature_collection: {
    type: 'FeatureCollection',
    features: [{
      type: 'Feature',
      id: 'geojson:0',
      properties: { name: 'PEI field' },
      geometry: { type: 'Polygon', coordinates: [peiRing] },
    }],
  },
  feature_summaries: [{
    id: 'geojson:0',
    label: 'PEI field',
    geometry_type: 'Polygon',
    bbox: [-63.14, 46.24, -63.12, 46.26],
    acres: 62,
    selected: true,
    properties: { name: 'PEI field' },
  }],
  regional_intersections: [{
    layer_id: 'pei_detailed_soil',
    layer_label: 'PEI Detailed Soil Survey (1:75,000)',
    system: 'AAFC PEI Detailed Soil Survey',
    code: 'PEI_SOIL_1270',
    name: 'PEI detailed soil map unit PEPED103Ch:6-Ti:3/CD: 60% Charlottetown; 30% Tignish',
    label: 'PEI detailed soil map unit PEPED103Ch:6-Ti:3/CD: 60% Charlottetown; 30% Tignish',
    source_url: 'https://open.canada.ca/data/en/dataset/7fa18ce7-6c14-438a-95c6-bb0906ddfb30',
    confidence: 0.94,
    coverage_estimate: 1,
    match_reason: 'Bundled OGL-Canada PEI detailed-soil intersection',
    source: 'bundled_official_geospatial_layer',
    source_scale_range: '1:75,000',
    map_unit: 'PEPED103Ch:6-Ti:3/CD',
    dominant_components: [
      { soil_name: 'Charlottetown', proportion_percent: 60, drainage_class: 'well drained' },
      { soil_name: 'Tignish', proportion_percent: 30, drainage_class: 'well drained' },
    ],
    publication_year: 2013,
    boundary: 'Historical mapped prior, not current field truth or a management rate.',
  }],
  regional_feature_collection: { type: 'FeatureCollection', features: [] },
  official_layer_status: [{
    layer_id: 'pei_detailed_soil',
    label: 'PEI Detailed Soil Survey (1:75,000)',
    system: 'AAFC PEI Detailed Soil Survey',
    status: 'matched',
    match_count: 1,
    message: 'matched bundled official polygon',
  }],
  warnings: [],
  status_message: 'pei-field.geojson loaded with one historical mapped-soil match.',
}

const nsPictouUploadPayload = {
  ...peiUploadPayload,
  filename: 'pictou-field.geojson',
  regional_intersections: [{
    layer_id: 'ns_pictou_detailed_soil',
    layer_label: 'Pictou County Detailed Soil Survey (1:50,000)',
    system: 'AAFC Nova Scotia Detailed Soil Survey',
    code: 'NS_PICTOU_SOIL_1',
    name: 'Pictou County detailed soil map unit NSNSD005Qu4/C: 70% Queens; 30% Queens',
    label: 'Pictou County detailed soil map unit NSNSD005Qu4/C: 70% Queens; 30% Queens',
    source_url: 'https://open.canada.ca/data/en/dataset/083534ca-d5b0-46f5-b540-f3a706dbc2de',
    confidence: 0.94,
    coverage_estimate: 1,
    match_reason: 'Bundled OGL-Canada Pictou County detailed-soil intersection',
    source: 'bundled_official_geospatial_layer',
    source_scale_range: '1:50,000',
    map_unit: 'NSNSD005Qu4/C',
    coverage_area: 'Pictou County only',
    dominant_components: [
      { soil_name: 'Queens', proportion_percent: 70, drainage_class: 'imperfectly drained' },
      { soil_name: 'Queens', proportion_percent: 30, drainage_class: 'poorly drained' },
    ],
    publication_year: 2013,
    boundary: 'Historical Pictou County mapped prior; not province-wide coverage or current field truth.',
  }],
  official_layer_status: [{
    layer_id: 'ns_pictou_detailed_soil',
    label: 'Pictou County Detailed Soil Survey (1:50,000)',
    system: 'AAFC Nova Scotia Detailed Soil Survey',
    status: 'matched',
    match_count: 1,
    message: 'matched bundled official polygon',
  }],
  status_message: 'pictou-field.geojson loaded with one historical mapped-soil match.',
}

const southPriors = {
  location_text: 'Iowa Des Moines Lobe corn soil phosphorus boundary 4 vertices 50 acres',
  candidate_regions: [
    {
      label: 'Southern Iowa Drift Plain',
      name: 'Southern Iowa Drift Plain',
      layer: 'epa_l3_us',
      system: 'EPA Level III Ecoregion',
      code: '47',
      confidence: 0.92,
    },
  ],
  boosted_namespaces: ['regional_environment_context'],
  evidence: ['official_polygon_intersection'],
  missing_context: [],
  uncertainty: 'low',
  used_as_prior_only: true,
  not_field_specific_fact: true,
  disclaimer: 'Official regional polygons are context priors.',
  ui_notice: 'Official regional polygons intersected the uploaded or drawn field geometry.',
  recommended_followups: ['Confirm the field boundary.'],
  regional_intersections: [
    {
      layer_id: 'epa_l3_us',
      layer_label: 'EPA Level III Ecoregions of the Continental United States',
      system: 'EPA Level III Ecoregion',
      code: '47',
      name: 'Southern Iowa Drift Plain',
      label: 'Southern Iowa Drift Plain',
      source_url: 'https://www.epa.gov/eco-research/level-iii-and-iv-ecoregions-continental-united-states',
      confidence: 0.92,
      coverage_estimate: 1,
      match_reason: 'Official ArcGIS FeatureServer spatial intersection',
      source: 'official_arcgis_feature_service',
    },
  ],
  regional_feature_collection: { type: 'FeatureCollection', features: [] },
  geo_errors: [],
  official_layer_status: [
    {
      layer_id: 'epa_l3_us',
      label: 'EPA Level III Ecoregions of the Continental United States',
      system: 'EPA Level III Ecoregion',
      status: 'matched',
      match_count: 1,
      message: 'matched official polygon',
    },
  ],
}

const pointPriors = {
  location_text: 'Iowa Des Moines Lobe corn soil phosphorus point',
  candidate_regions: [
    {
      label: 'Central Iowa and Minnesota Till Prairies',
      name: 'Central Iowa and Minnesota Till Prairies',
      layer: 'nrcs_mlra',
      system: 'NRCS MLRA',
      code: 'MLRA_103',
      confidence: 0.94,
    },
  ],
  boosted_namespaces: ['regional_environment_context', 'soil_water'],
  evidence: ['official_polygon_intersection'],
  missing_context: [],
  uncertainty: 'low',
  used_as_prior_only: true,
  not_field_specific_fact: true,
  disclaimer: 'Official regional polygons are context priors.',
  ui_notice: 'Official regional polygons intersected the uploaded or drawn field geometry.',
  recommended_followups: ['Confirm the point is inside the field before acting.'],
  regional_intersections: [
    {
      layer_id: 'nrcs_mlra',
      layer_label: 'USDA NRCS Major Land Resource Areas',
      system: 'NRCS MLRA',
      code: 'MLRA_103',
      name: 'Central Iowa and Minnesota Till Prairies',
      label: 'Central Iowa and Minnesota Till Prairies',
      source_url: 'https://www.nrcs.usda.gov/resources/data-and-reports/major-land-resource-area-mlra',
      confidence: 0.94,
      coverage_estimate: 1,
      match_reason: 'Official ArcGIS FeatureServer spatial intersection',
      source: 'official_arcgis_feature_service',
    },
  ],
  regional_feature_collection: { type: 'FeatureCollection', features: [] },
  geo_errors: [],
  official_layer_status: [
    {
      layer_id: 'nrcs_mlra',
      label: 'USDA NRCS Major Land Resource Areas',
      system: 'NRCS MLRA',
      status: 'matched',
      match_count: 1,
      message: 'matched official polygon',
    },
  ],
}

const bcPriors = {
  location_text: 'British Columbia Fraser Valley mixed cropping boundary 4 vertices 96 acres',
  candidate_regions: [
    {
      label: 'BC agriculture capability: 70% class 2; 30% class 2',
      name: 'BC agriculture capability: 70% class 2; 30% class 2',
      layer: 'bc_agriculture_capability',
      system: 'BC Agriculture Capability',
      code: 'CAPABILITY_2',
      confidence: 1,
    },
  ],
  boosted_namespaces: ['regional_environment_context', 'soil_water', 'crop_management'],
  evidence: ['official_polygon_intersection'],
  missing_context: [],
  uncertainty: 'low',
  used_as_prior_only: true,
  not_field_specific_fact: true,
  disclaimer: 'Legacy capability polygons are context priors, not current field truth.',
  ui_notice: 'Official regional polygons intersected the sample field geometry.',
  recommended_followups: ['Confirm current soil, drainage, field history, and crop goals.'],
  regional_intersections: [
    {
      layer_id: 'bc_agriculture_capability',
      layer_label: 'BC Agriculture Capability Mapping',
      system: 'BC Agriculture Capability',
      code: 'CAPABILITY_2',
      name: 'BC agriculture capability: 70% class 2; 30% class 2',
      label: 'BC agriculture capability: 70% class 2; 30% class 2',
      source_url: 'https://catalogue.data.gov.bc.ca/dataset/agriculture-capability-mapping',
      confidence: 1,
      coverage_estimate: 0.78,
      match_reason: 'Bundled official geospatial layer intersection',
      source: 'bundled_official_geospatial_layer',
      source_scale_range: '1:20,000 to 1:100,000',
      boundary: 'Legacy regional context, not current field truth.',
    },
  ],
  regional_feature_collection: { type: 'FeatureCollection', features: [] },
  geo_errors: [],
  official_layer_status: [
    {
      layer_id: 'bc_agriculture_capability',
      label: 'BC Agriculture Capability Mapping',
      system: 'BC Agriculture Capability',
      status: 'matched',
      match_count: 1,
      message: 'matched bundled official polygon',
    },
  ],
}

const abPriors = {
  ...bcPriors,
  location_text: 'Alberta Leduc County barley boundary 4 vertices 160 acres',
  candidate_regions: [{
    label: 'Alberta detailed soil map unit MMNV9/U1l',
    name: 'Alberta detailed soil map unit MMNV9/U1l',
    layer: 'ab_detailed_soil',
    system: 'AAFC Alberta Detailed Soil Survey',
    code: 'AB_SOIL_ABD192014361',
    confidence: 1,
  }],
  regional_intersections: [{
    layer_id: 'ab_detailed_soil',
    layer_label: 'AAFC Alberta Detailed Soil Survey',
    system: 'AAFC Alberta Detailed Soil Survey',
    code: 'AB_SOIL_ABD192014361',
    name: 'Alberta detailed soil map unit MMNV9/U1l',
    label: 'Alberta detailed soil map unit MMNV9/U1l',
    confidence: 1,
    coverage_estimate: 1,
    match_reason: 'Bundled official geospatial layer intersection',
    source: 'bundled_official_geospatial_layer',
    soil_summary: '35% Malmo; 35% Navarre; 15% Ponoka',
    drainage_class: 'well to imperfectly drained',
    slope_class: '1%',
  }],
  official_layer_status: [{
    layer_id: 'ab_detailed_soil',
    label: 'AAFC Alberta Detailed Soil Survey',
    system: 'AAFC Alberta Detailed Soil Survey',
    status: 'matched',
    match_count: 1,
    message: 'matched bundled official polygon',
  }],
}

const skPriors = {
  location_text: 'Saskatchewan Regina Plain spring wheat boundary 4 vertices 96 acres',
  candidate_regions: [
    {
      label: 'Saskatchewan thematic soil: capability class 2; well drainage; 0 - 2% slope',
      name: 'Saskatchewan thematic soil: capability class 2; well drainage; 0 - 2% slope',
      layer: 'sk_thematic_soil',
      system: 'AAFC Saskatchewan Thematic Soil',
      code: 'SK_SOIL_40147',
      confidence: 0.94,
    },
  ],
  boosted_namespaces: ['regional_environment_context', 'soil_water', 'crop_management'],
  evidence: ['official_polygon_intersection'],
  missing_context: [],
  uncertainty: 'low',
  used_as_prior_only: true,
  not_field_specific_fact: true,
  disclaimer: 'Thematic soil polygons are context priors, not current field truth.',
  ui_notice: 'The bundled Saskatchewan thematic soil polygon intersected the sample field geometry.',
  recommended_followups: ['Confirm field variability, soil profile, nutrient status, salinity, and drainage performance.'],
  regional_intersections: [
    {
      layer_id: 'sk_thematic_soil',
      layer_label: 'Saskatchewan Thematic Soil Maps',
      system: 'AAFC Saskatchewan Thematic Soil',
      code: 'SK_SOIL_40147',
      name: 'Saskatchewan thematic soil: capability class 2; well drainage; 0 - 2% slope',
      label: 'Saskatchewan thematic soil: capability class 2; well drainage; 0 - 2% slope',
      source_url: 'https://open.canada.ca/data/en/dataset/ed36f4f3-2fb9-4241-8e29-6741e8b9e400',
      confidence: 0.94,
      coverage_estimate: 1,
      match_reason: 'Bundled OGL-Canada thematic-soil intersection',
      source: 'bundled_official_geospatial_layer',
      source_scale_note: 'Revised and condensed from the Saskatchewan Detailed Soils Database.',
      drainage_class: 'Well',
      capability_class: '2',
      capability_interpretation: 'moderate limitations or moderate conservation needs',
      erosion_risk: 'Very Low',
      slope_class: '0 - 2%',
      surface_texture_group: 'Fine',
      boundary: 'Generalized regional context, not current field truth.',
    },
  ],
  regional_feature_collection: { type: 'FeatureCollection', features: [] },
  geo_errors: [],
  official_layer_status: [
    {
      layer_id: 'sk_thematic_soil',
      label: 'Saskatchewan Thematic Soil Maps',
      system: 'AAFC Saskatchewan Thematic Soil',
      status: 'matched',
      match_count: 1,
      message: 'matched bundled official polygon',
    },
  ],
}

const mbPriors = {
  location_text: 'Manitoba Aspen Parkland canola boundary 4 vertices 320 acres',
  candidate_regions: [
    {
      label: '2021 soil erosion risk: Very Low',
      name: '2021 soil erosion risk: Very Low',
      layer: 'ca_soil_erosion_risk',
      system: 'AAFC Soil Erosion Risk',
      code: 'CA_ERI_511002',
      confidence: 0.94,
    },
  ],
  boosted_namespaces: ['regional_environment_context', 'soil_water', 'crop_management'],
  evidence: ['official_polygon_intersection'],
  missing_context: [],
  uncertainty: 'low',
  used_as_prior_only: true,
  not_field_specific_fact: true,
  disclaimer: 'AAFC erosion-risk polygons are regional historical context, not current field truth.',
  ui_notice: 'The bundled AAFC erosion-risk polygon intersected the sample field geometry.',
  recommended_followups: ['Confirm present cover, slope, residue, drainage, and erosion evidence in the field.'],
  regional_intersections: [
    {
      layer_id: 'ca_soil_erosion_risk',
      layer_label: 'AAFC Soil Erosion Risk 2021',
      system: 'AAFC Soil Erosion Risk',
      code: 'CA_ERI_511002',
      name: '2021 soil erosion risk: Very Low',
      label: '2021 soil erosion risk: Very Low',
      source_url: 'https://open.canada.ca/data/en/dataset/b52b3c91-e0eb-47d1-aea5-fa5428254512',
      confidence: 0.94,
      coverage_estimate: 1,
      match_reason: 'Bundled OGL-Canada soil-erosion-risk intersection',
      source: 'bundled_official_geospatial_layer',
      source_scale: 'Generalized Soil Landscapes of Canada polygons; not a field-scale erosion survey.',
      erosion_risk: 'Very Low',
      erosion_indicator_2021: 4.002,
      erosion_risk_1981: 'Low',
      erosion_indicator_1981: 7.191,
      erosion_change_1981_2021: 'Decrease',
      erosion_change_indicator: -3.189,
      erosion_summary: 'AAFC modelled soil erosion risk for Soil Landscape 511002: Very Low in 2021; 1981-2021 change class decrease.',
      soil_landscape_id: 511002,
      source_year: 2021,
      boundary: 'Regional historical context, not current erosion observation or field diagnosis.',
    },
  ],
  regional_feature_collection: { type: 'FeatureCollection', features: [] },
  geo_errors: [],
  official_layer_status: [
    {
      layer_id: 'ca_soil_erosion_risk',
      label: 'AAFC Soil Erosion Risk 2021',
      system: 'AAFC Soil Erosion Risk',
      status: 'matched',
      match_count: 1,
      message: 'matched bundled official polygon',
    },
  ],
}

const nasdiConditions = {
  tool: 'aafc_nasdi_agroclimate',
  status: 'available',
  source: 'https://open.canada.ca/data/en/dataset/2b72996a-2905-4cea-a565-8bfb85cd42ac',
  source_name: 'AAFC National Agroclimate Data Service',
  observation_end: '2026-07-12',
  data_age_days: 7,
  freshness_status: 'current',
  sample_point_count: 3,
  indicator_summary: {
    spi: { label: 'Standardized Precipitation Index', units: 'standardized anomaly', time_window: '013w', value: 0.43 },
    spei: { label: 'Standardized Precipitation Evapotranspiration Index', units: 'standardized anomaly', time_window: '013w', value: 0.79 },
    temperature_anomaly: { label: 'Difference from normal temperature', units: 'degrees C', time_window: '004w', value: 2.02 },
    percent_of_average_precipitation: { label: 'Percent of average precipitation', units: 'percent', time_window: '013w', value: 103.875 },
  },
  boundary: 'Regional grid context, not a field measurement or prescription.',
}

const nasaPowerConditions = {
  tool: 'nasa_power_daily',
  source: 'https://power.larc.nasa.gov/api/temporal/daily/point?example=true',
  cache_hit: true,
  latitude: 53.25,
  longitude: -113.6,
  start: '20260809',
  end: '20260811',
  parameter_summary: {
    T2M: { days: 3, mean: 19.25, sum: 57.75 },
    PRECTOTCORR: { days: 3, mean: 1.075, sum: 3.225 },
    WS2M: { days: 3, mean: 2.875, sum: 8.625 },
  },
  boundary: 'NASA POWER is gridded weather context, not an on-field sensor.',
}

const privateKnowledgeInspection = {
  schema_version: 'open_agronomy_agent.ephemeral_private_knowledge.v1',
  filename: 'manitoba-note.txt',
  content_type: 'text/plain',
  raw_sha256: 'a'.repeat(64),
  parse_status: 'ready',
  persisted: false,
  training_eligible: false,
  retrieval_policy: 'context_only',
  quality_flags: [],
  chunks: [
    {
      doc_id: 'private-aaaaaaaaaaaaaaaa-001',
      title: 'manitoba-note.txt · local private excerpt 1',
      text: 'Inspect five sites and keep the pesticide decision tied to the current label.',
      source: 'private-upload:manitoba-note.txt',
      source_id: 'private-aaaaaaaaaaaaaaaa',
      source_type: 'user_upload_private',
      score: 0,
      tags: ['private local reference'],
      jurisdictions: [],
      languages: [],
      retrieval_policy: 'context_only',
      content_risk_tags: ['workspace_source_unverified_for_decisive_use'],
      license_status: 'user_supplied_private_unverified',
      raw_sha256: 'a'.repeat(64),
      chunk_sha256: 'b'.repeat(64),
      visibility: 'ephemeral_browser_session',
      chunk_index: 0,
      training_eligible: false,
      retrieval_method: 'browser_query_lexical_rank_v1',
    },
  ],
  boundary: 'Parsed locally and not retained.',
}

const installFetchMock = (
  demoFields: { schema_version: string; storage: typeof emptyDemoFields.storage; fields: Array<Record<string, unknown>> } = emptyDemoFields,
  boundaryUpload: typeof uploadPayload = uploadPayload,
  initialSessions: Array<Record<string, unknown>> = [],
) => {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url === '/api/sessions?include_archived=true&include_turns=false') return jsonResponse(initialSessions)
    if (url === '/api/configs') return jsonResponse(bootConfig)
    if (url === '/api/tools/public-adapter-readiness') return jsonResponse(adapterReadiness)
    if (url === '/api/demo/fields' && (!init?.method || init.method === 'GET')) return jsonResponse(demoFields)
    if (url === '/api/demo/fields' && init?.method === 'POST') {
      const body = JSON.parse(String(init.body || '{}'))
      return jsonResponse({
        schema_version: 'open_agronomy_agent.demo_field_saved.v1',
        storage: emptyDemoFields.storage,
        field: {
          id: 'field-context-1',
          field_context_id: 'field-context-1',
          name: body.name,
          crop: body.field.crop,
          region: body.field.region,
          jurisdiction: body.field.jurisdiction,
          acres: body.field.acres,
          concern: body.field.concern,
          notes: body.field.notes,
          geometry: body.geometry,
          regionalContext: body.regionalContext,
          geoPriors: body.geoPriors,
          sourceBoundary: body.sourceBoundary,
          createdAt: '2026-07-10T18:00:00Z',
          storageMode: 'account_workspace',
        },
      })
    }
    if (url.startsWith('/api/demo/fields/') && init?.method === 'PATCH') {
      const body = JSON.parse(String(init.body || '{}'))
      const fieldContextId = url.split('/').pop() || 'field-context-1'
      return jsonResponse({
        schema_version: 'open_agronomy_agent.demo_field_updated.v1',
        storage: emptyDemoFields.storage,
        field: {
          id: fieldContextId,
          field_context_id: fieldContextId,
          name: body.name,
          crop: body.field.crop,
          region: body.field.region,
          jurisdiction: body.field.jurisdiction,
          acres: body.field.acres,
          concern: body.field.concern,
          notes: body.field.notes,
          geometry: body.geometry,
          regionalContext: body.regionalContext,
          geoPriors: body.geoPriors,
          sourceBoundary: body.sourceBoundary,
          createdAt: '2026-07-10T18:00:00Z',
          updatedAt: '2026-08-12T18:00:00Z',
          storageMode: 'account_workspace',
        },
      })
    }
    if (
      url.endsWith('/context-packs/quebec-lidar/plan')
      && init?.method === 'POST'
    ) {
      return jsonResponse({
        schema_version: 'open_agronomy_agent.demo_quebec_lidar_pack_plan.v1',
        status: 'ready_to_download',
        field_context_id: 'field-quebec',
        plan_sha256: 'a'.repeat(64),
        receipt: {
          matched_tile_count: 1,
          field_geometry_sha256: 'd'.repeat(64),
          exact_geometry_included: false,
          tile_identifiers_included: false,
          download_urls_included: false,
          retrieval_policy: 'context_only',
          query_ready: false,
          boundary: 'Availability only.',
        },
        preparation: {
          planning_network_request_attempted: false,
          private_plan_retained_by_server: false,
          automatic_download_started: false,
          download_requires_explicit_operator_network_permission: true,
          operator_workflow: 'docs/quebec_lidar_offline_pack_workflow_20260725.md',
        },
        boundary: 'This local check reports source availability only.',
      })
    }
    if (url === '/api/geo/boundary-upload?intersect=true') return jsonResponse(boundaryUpload)
    if (url === '/api/private-knowledge/inspect') return jsonResponse(privateKnowledgeInspection)
    if (url === '/api/tools/weather-power') return jsonResponse(nasaPowerConditions)
    if (url === '/api/geo/priors') {
      const body = JSON.parse(String(init?.body || '{}'))
      if (body.geometry?.type === 'Point') return jsonResponse(pointPriors)
      const firstLongitude = body.geometry?.coordinates?.[0]?.[0]?.[0]
      if (firstLongitude < -120) return jsonResponse(bcPriors)
      if (firstLongitude < -110) return jsonResponse(abPriors)
      if (firstLongitude < -100) return jsonResponse(skPriors)
      if (firstLongitude < -95) return jsonResponse(mbPriors)
      return jsonResponse(southPriors)
    }
    if (url === '/api/tools/aafc-nasdi-agroclimate') return jsonResponse(nasdiConditions)
    return jsonResponse({})
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

const installDegradedFetchMock = () => {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url === '/api/sessions?include_archived=true&include_turns=false') return jsonResponse([])
    if (url === '/api/configs') return jsonResponse(bootConfig)
    if (url === '/api/tools/public-adapter-readiness') throw new Error('adapter readiness unavailable')
    if (url === '/api/demo/fields' && (!init?.method || init.method === 'GET')) throw new Error('field storage unavailable')
    if (url === '/api/geo/boundary-upload?intersect=true') return jsonResponse(uploadLayerErrorPayload)
    return jsonResponse({})
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

const installConversationFetchMock = () => {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url === '/api/sessions?include_archived=true&include_turns=false') {
      return jsonResponse([
        {
          session_id: 'session-conversation',
          name: 'Conference field review',
          context: { field_conversation_key: 'sample:central-alberta-barley' },
          turns: [
            {
              turn_id: 'turn-conversation',
              user_message: 'Should I add nitrogen after this wet spring?',
              answer: 'Check crop stage, application history, drainage, and current crop condition before changing the rate.',
              answer_status: 'draft',
              trace: {
                route: { question_type: 'fertility_diagnostic', risk_level: 'medium' },
                retrieved_docs: Array.from({ length: 6 }, (_, index) => ({
                  rank: index + 1,
                  doc_id: `doc-${index + 1}`,
                  title: `Agronomy source ${index + 1}`,
                  source_type: 'applied_guidance',
                  score: 1 - index * 0.05,
                })),
                graph_hits: [{
                  rank: 1,
                  node_id: 'soil-water-node',
                  name: 'Soil water status',
                  kind: 'concept',
                  neighbors: [],
                  evidence: 'Soil water status changes nutrient availability and field trafficability.',
                }],
                tool_invocations: [],
              },
            },
          ],
        },
      ])
    }
    if (url === '/api/configs') return jsonResponse(bootConfig)
    if (url === '/api/tools/public-adapter-readiness') return jsonResponse(adapterReadiness)
    if (url === '/api/demo/fields') return jsonResponse(emptyDemoFields)
    return jsonResponse({})
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

beforeEach(() => {
  Object.defineProperty(window, 'localStorage', {
    value: createTestStorage(),
    configurable: true,
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
  window.location.hash = ''
})

const openPrimaryPage = (name: 'Map' | 'Fields') => {
  const navigation = screen.getByRole('navigation', { name: 'Primary' })
  fireEvent.click(within(navigation).getByRole('button', { name: name === 'Map' ? 'Workspace' : name }))
  if (name === 'Map') fireEvent.click(screen.getByRole('button', { name: 'Map' }))
}

const selectExample = async (id = 'central-alberta-barley', returnToMap = false) => {
  await screen.findByText('Local runtime · connected mode')
  openPrimaryPage('Fields')
  fireEvent.change(screen.getByRole('combobox', { name: /example/i }), { target: { value: id } })
  if (returnToMap) openPrimaryPage('Map')
}

const openFieldTab = (name: 'Overview' | 'Records & soil tests' | 'Map context') => {
  const group = screen.getByRole('group', { name: 'Field information' })
  fireEvent.click(within(group).getByRole('button', { name }))
}

describe('Open Agronomy map upload workflow', () => {
  it('keeps field tasks primary while preserving secondary pages behind one disclosure', async () => {
    installFetchMock()
    render(<OpenAgronomyApp />)

    const navigation = screen.getByRole('navigation', { name: 'Primary' })
    const primaryButtons = Array.from(navigation.querySelectorAll(':scope > button'))
    expect(primaryButtons.map((button) => button.textContent)).toEqual(['Workspace', 'Fields', 'Data'])
    expect(within(navigation).getByRole('button', { name: 'Workspace' })).toHaveAttribute('aria-current', 'page')

    const more = screen.getByText('More', { selector: 'summary' })
    fireEvent.click(more)
    expect(within(navigation).getByRole('button', { name: 'Evidence' })).toBeVisible()
    expect(within(navigation).getByRole('button', { name: 'Benchmarks' })).toBeVisible()
    expect(within(navigation).getByRole('button', { name: 'Privacy' })).toBeVisible()
    expect(within(navigation).getByRole('button', { name: 'About' })).toBeVisible()

    fireEvent.click(within(navigation).getByRole('button', { name: 'Evidence' }))
    expect(await screen.findByRole('heading', { name: 'Behind the answer' })).toBeInTheDocument()
    expect(more.closest('details')).not.toHaveAttribute('open')
  })

  it('keeps the general question blank until the Alberta example is explicitly selected', async () => {
    const fetchMock = installFetchMock()
    render(<OpenAgronomyApp />)

    expect(await screen.findByRole('button', { name: /Explore an example field/i })).toBeInTheDocument()
    openPrimaryPage('Map')
    expect(screen.getByRole('combobox', { name: 'Active field' })).toHaveValue('')
    expect(fetchMock.mock.calls.some(([url]) => String(url) === '/api/geo/priors')).toBe(false)
    fireEvent.click(screen.getByRole('button', { name: /Explore an example field/i }))
    expect(await screen.findByText(/Regional context refreshed: AAFC Alberta Detailed Soil Survey AB_SOIL_ABD192014361 matched at 100% confidence/i)).toBeInTheDocument()
    expect(await screen.findByTestId('mock-leaflet-map')).toHaveAttribute('data-geometry-kind', 'polygon')
    expect(screen.getByTestId('mock-leaflet-map')).toHaveAttribute('data-first-lon', '-113.608')
    openPrimaryPage('Fields')
    openFieldTab('Map context')
    expect(screen.getAllByText(/Alberta detailed soil map unit MMNV9\/U1l/i).length).toBeGreaterThan(0)
    expect(await screen.findByTestId('agroclimate-spi')).toHaveTextContent('13 wk SPI0.43')

    const priorsCall = fetchMock.mock.calls.find(([url, init]) => {
      if (String(url) !== '/api/geo/priors' || init?.method !== 'POST') return false
      const body = JSON.parse(String(init.body || '{}'))
      return body.geometry?.coordinates?.[0]?.[0]?.[0] === -113.608
    })
    expect(priorsCall).toBeTruthy()
  })

  it('runs field insights only on demand and keeps unsaved drawing edits out of analysis', async () => {
    const fetchMock = installFetchMock()
    const base = fetchMock.getMockImplementation()!
    fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => String(input) === '/api/geo/field-analysis'
      ? jsonResponse({ schema_version: 'open_agronomy_agent.field_map_analysis.v1', status: 'complete',
          geometry: { type: 'Polygon', status: 'complete', area_ha: 95, area_ac: 234.7, perimeter_m: 3910,
            location: { latitude: 53.3, longitude: -113.6 }, method: 'WGS84 ellipsoid' }, layers: [], warnings: [], elapsed_ms: 1 })
      : base(input, init))
    render(<OpenAgronomyApp />)
    await screen.findByText('Local runtime · connected mode')
    await waitFor(() => expect(screen.getByLabelText('Active field')).toBeEnabled())
    fireEvent.change(screen.getByLabelText('Active field'), { target: { value: 'sample:central-alberta-barley' } })
    openPrimaryPage('Map')
    expect(fetchMock.mock.calls.filter(([url]) => String(url) === '/api/geo/field-analysis')).toHaveLength(0)
    fireEvent.click(screen.getByRole('button', { name: 'Field insights' }))
    expect(await screen.findByText('95 ha')).toBeVisible()
    const analysisCall = fetchMock.mock.calls.find(([url]) => String(url) === '/api/geo/field-analysis')!
    const body = JSON.parse(String(analysisCall[1]?.body))
    expect(body.geometry.type).toBe('Polygon')
    expect(body.geometry.coordinates[0][0]).toEqual([-113.608, 53.296])
    expect(body).not.toHaveProperty('acres')
    fireEvent.click(screen.getByRole('button', { name: 'Close Field insights' }))
    expect((analysisCall[1]?.signal as AbortSignal).aborted).toBe(true)
    fireEvent.click(screen.getByLabelText('Set field'))
    fireEvent.click(screen.getByRole('button', { name: 'Draw boundary' }))
    expect(screen.getByRole('button', { name: 'Field insights' })).toBeDisabled()
    expect(fetchMock.mock.calls.filter(([url]) => String(url) === '/api/geo/field-analysis')).toHaveLength(1)
  })

  it('labels an online partial weather window with observed dates rather than requested dates', async () => {
    const base = installFetchMock()
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL, init?: RequestInit) => String(input) === '/api/tools/weather-power'
      ? Promise.resolve(jsonResponse({ ...nasaPowerConditions, cache_hit: false, status: 'partial_available', requested_day_count: 3, observed_day_count: 1,
          observation_start: '2026-09-25', observation_end: '2026-09-25', parameter_summary: {
            T2M: { days: 1, mean: 12.5 }, PRECTOTCORR: { days: 1, sum: 0 }, WS2M: { days: 1, mean: 2.4 },
          } })) : base(input, init)))
    render(<OpenAgronomyApp />)
    await selectExample('central-alberta-barley', true)
    expect(await screen.findByTestId('map-nasa-power-summary')).toHaveTextContent('1/3 days')
    fireEvent.click(screen.getByLabelText('NASA POWER field weather'))
    expect(screen.getByText('1 of 3 requested days available')).toBeVisible()
    expect(screen.getByText('Observed UTC 2026-09-25')).toBeVisible()
    expect(screen.getByText('0.0 mm')).toBeVisible()
    expect(screen.getByText(/Totals include only published observations/)).toBeVisible()
  })

  it('does not present an empty successful weather response as available observations', async () => {
    const base = installFetchMock()
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL, init?: RequestInit) => String(input) === '/api/tools/weather-power'
      ? Promise.resolve(jsonResponse({ ...nasaPowerConditions, status: 'no_data', requested_day_count: 3, observed_day_count: 0, parameter_summary: {} })) : base(input, init)))
    render(<OpenAgronomyApp />)
    await selectExample('central-alberta-barley', true)
    await screen.findByText('unavailable', { selector: '.map-weather-pill small' })
    expect(screen.queryByTestId('map-nasa-power-summary')).not.toBeInTheDocument()
    fireEvent.click(screen.getByLabelText('NASA POWER field weather'))
    expect(screen.getByText('No usable observations in this window')).toBeVisible()
    expect(screen.getByText(/No usable weather observations have been published/)).toBeVisible()
  })

  it('shows recent NASA POWER field weather beside Set field and refreshes it on demand', async () => {
    const fetchMock = installFetchMock()
    render(<OpenAgronomyApp />)

    await selectExample('central-alberta-barley', true)

    expect(await screen.findByTestId('map-nasa-power-summary')).toHaveTextContent('3.2 mm · 2.9 m/s')
    const weatherSummary = screen.getByLabelText('NASA POWER field weather')
    fireEvent.click(weatherSummary)
    expect(screen.getByText('Recent gridded weather')).toBeInTheDocument()
    expect(screen.getByText('19.3 °C')).toBeInTheDocument()
    expect(screen.getByText('3.2 mm')).toBeInTheDocument()
    expect(screen.getByText('2.9 m/s')).toBeInTheDocument()
    expect(screen.getByText(/NASA POWER is gridded weather context, not an on-field sensor/i)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Official NASA POWER response' })).toHaveAttribute('href', nasaPowerConditions.source)

    fireEvent.click(screen.getByRole('button', { name: 'Refresh NASA POWER field weather' }))
    await waitFor(() => {
      expect(
        fetchMock.mock.calls.filter(([url]) => String(url) === '/api/tools/weather-power'),
      ).toHaveLength(2)
    })
    const weatherCall = fetchMock.mock.calls.find(([url]) => String(url) === '/api/tools/weather-power')
    const weatherBody = JSON.parse(String(weatherCall?.[1]?.body || '{}'))
    expect(weatherBody).toMatchObject({
      parameters: ['T2M', 'PRECTOTCORR', 'WS2M'],
    })
    expect(weatherBody.lat).toBeCloseTo(53.3, 6)
    expect(weatherBody.lon).toBeCloseTo(-113.6, 6)
  })

  it('keeps regional evidence available but collapsed by default on the Fields page', async () => {
    installFetchMock()
    render(<OpenAgronomyApp />)

    await selectExample()
    openFieldTab('Map context')
    const regionalSummary = await screen.findByText('Regional context', { selector: 'summary' })
    const regionalDisclosure = regionalSummary.closest('details')
    const conditionsSummary = screen.getByText('Current regional conditions', { selector: 'summary' })
    const conditionsDisclosure = conditionsSummary.closest('details')

    expect(regionalDisclosure).not.toHaveAttribute('open')
    expect(regionalSummary).toHaveTextContent('1 match')
    expect(regionalSummary).toHaveTextContent('low')
    expect(conditionsDisclosure).not.toHaveAttribute('open')

    fireEvent.click(regionalSummary)
    expect(regionalDisclosure).toHaveAttribute('open')
    fireEvent.click(conditionsSummary)
    expect(conditionsDisclosure).toHaveAttribute('open')
  })

  it('loads the Saskatchewan sample with classified offline soil context', async () => {
    const fetchMock = installFetchMock()
    render(<OpenAgronomyApp />)

    await selectExample('regina-thematic-soil')
    openFieldTab('Map context')

    expect(
      (await screen.findAllByText(/Saskatchewan thematic soil: capability class 2; well drainage; 0 - 2% slope/i)).length,
    ).toBeGreaterThan(0)
    expect(
      screen.getByText(/Source resolution: Revised and condensed from the Saskatchewan Detailed Soils Database/i),
    ).toBeInTheDocument()
    expect(screen.getAllByText(/Generalized regional context, not current field truth/i).length).toBeGreaterThan(0)
    expect(await screen.findByText('Current regional conditions')).toBeInTheDocument()
    expect(screen.getByTestId('agroclimate-spi')).toHaveTextContent('13 wk SPI0.43')
    expect(screen.getByTestId('agroclimate-temperature_anomaly')).toHaveTextContent('4 wk temperature+2.0 C')
    expect(screen.getByTestId('agroclimate-percent_of_average_precipitation')).toHaveTextContent('13 wk precipitation104%')
    expect(screen.getByText(/Observed through/i)).toHaveTextContent('2026-07-12 · 7 days old')
    expect(screen.getByText(/Regional grid context, not a field measurement or prescription/i)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /official source/i })).toHaveAttribute('href', nasdiConditions.source)

    const nasdiCall = fetchMock.mock.calls.find(
      ([url, init]) => String(url) === '/api/tools/aafc-nasdi-agroclimate' && init?.method === 'POST',
    )
    expect(nasdiCall).toBeTruthy()
    const body = JSON.parse(String(nasdiCall?.[1]?.body || '{}'))
    expect(body.geometry.type).toBe('Polygon')
    expect(body.province).toBe('Saskatchewan')
    expect(body.sample_points).toBe(3)
    openPrimaryPage('Map')
    expect(screen.getByTestId('mock-leaflet-map')).toHaveAttribute('data-first-lon', '-104.734')
  })

  it('resolves a fresh offline agroclimate miss instead of leaving the field panel loading', async () => {
    const fetchMock = installFetchMock()
    const defaultFetch = fetchMock.getMockImplementation()
    fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input) === '/api/tools/aafc-nasdi-agroclimate') {
        return jsonResponse({
          ...nasdiConditions,
          status: 'unavailable',
          observation_end: null,
          data_age_days: null,
          indicator_summary: {},
          observations: [],
          sample_errors: [{ indicator: 'spi', stage: 'catalog', error_type: 'URLError' }],
        })
      }
      return defaultFetch!(input, init)
    })
    render(<OpenAgronomyApp />)

    await selectExample()
    openFieldTab('Map context')
    expect(
      await screen.findByText('Current AAFC regional conditions are unavailable for this geometry.'),
    ).toBeInTheDocument()
    expect(screen.queryByText('Loading the latest official grid observations...')).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: /official source/i })).toHaveAttribute('href', nasdiConditions.source)
  })

  it('loads the Manitoba sample with national soil-erosion context', async () => {
    const fetchMock = installFetchMock()
    render(<OpenAgronomyApp />)

    await selectExample('canola-acidity')
    openFieldTab('Map context')

    expect((await screen.findAllByText(/2021 soil erosion risk: Very Low/i)).length).toBeGreaterThan(0)
    expect(screen.getByText(/1981-2021 change class decrease/i)).toBeInTheDocument()
    expect(screen.getByText(/Generalized regional context, not current field truth/i)).toBeInTheDocument()
    const priorsCall = fetchMock.mock.calls.find(([url, init]) => {
      if (String(url) !== '/api/geo/priors' || init?.method !== 'POST') return false
      const body = JSON.parse(String(init.body || '{}'))
      return body.geometry?.coordinates?.[0]?.[0]?.[0] === -99.959
    })
    expect(priorsCall).toBeTruthy()
    openPrimaryPage('Map')
    expect(screen.getByTestId('mock-leaflet-map')).toHaveAttribute('data-geometry-kind', 'polygon')
    expect(screen.getByTestId('mock-leaflet-map')).toHaveAttribute('data-first-lon', '-99.959')
  })

  it('renders PEI mapped-soil context as historical rather than field truth', async () => {
    installFetchMock(emptyDemoFields, peiUploadPayload)
    render(<OpenAgronomyApp />)

    openPrimaryPage('Fields')
    fireEvent.change(await screen.findByLabelText('Boundary upload'), {
      target: { files: [new File([JSON.stringify({ type: 'Polygon', coordinates: [peiRing] })], 'pei-field.geojson')] },
    })
    openFieldTab('Map context')

    expect(
      (await screen.findAllByText(/PEI detailed soil map unit PEPED103Ch:6-Ti:3\/CD/i)).length,
    ).toBeGreaterThan(0)
    expect(screen.getByText('Source mapping scale 1:75,000')).toBeInTheDocument()
    expect(screen.getByText('Historical mapped context, not current field truth.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Official layer source' })).toHaveAttribute(
      'href',
      'https://open.canada.ca/data/en/dataset/7fa18ce7-6c14-438a-95c6-bb0906ddfb30',
    )
  })

  it('renders Nova Scotia soil context as Pictou County only', async () => {
    installFetchMock(emptyDemoFields, nsPictouUploadPayload)
    render(<OpenAgronomyApp />)

    openPrimaryPage('Fields')
    fireEvent.change(await screen.findByLabelText('Boundary upload'), {
      target: {
        files: [new File([JSON.stringify({ type: 'Polygon', coordinates: [peiRing] })], 'pictou-field.geojson')],
      },
    })
    openFieldTab('Map context')

    expect(
      (await screen.findAllByText(/Pictou County detailed soil map unit NSNSD005Qu4\/C/i)).length,
    ).toBeGreaterThan(0)
    expect(screen.getByText('Source mapping scale 1:50,000')).toBeInTheDocument()
    expect(
      screen.getByText('Pictou County only historical context—not province-wide or current field truth.'),
    ).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Official layer source' })).toHaveAttribute(
      'href',
      'https://open.canada.ca/data/en/dataset/083534ca-d5b0-46f5-b540-f3a706dbc2de',
    )
  })

  it('does not let a stale sample-layer response overwrite a newer uploaded field', async () => {
    let releaseInitialLookup!: (response: Response) => void
    const initialLookup = new Promise<Response>((resolve) => {
      releaseInitialLookup = resolve
    })
    let lookupCount = 0
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url === '/api/sessions?include_archived=true&include_turns=false') return jsonResponse([])
      if (url === '/api/configs') return jsonResponse(bootConfig)
      if (url === '/api/tools/public-adapter-readiness') return jsonResponse(adapterReadiness)
      if (url === '/api/demo/fields') return jsonResponse(emptyDemoFields)
      if (url === '/api/geo/priors') {
        lookupCount += 1
        return lookupCount === 1 ? initialLookup : jsonResponse(bcPriors)
      }
      if (url === '/api/geo/boundary-upload?intersect=true') return jsonResponse(nsPictouUploadPayload)
      if (url === '/api/tools/aafc-nasdi-agroclimate') return jsonResponse(nasdiConditions)
      return jsonResponse({})
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<OpenAgronomyApp />)

    await selectExample()
    fireEvent.change(await screen.findByLabelText('Boundary upload'), {
      target: {
        files: [new File([JSON.stringify({ type: 'Polygon', coordinates: [peiRing] })], 'pictou-field.geojson')],
      },
    })
    openFieldTab('Map context')
    expect(
      (await screen.findAllByText(/Pictou County detailed soil map unit NSNSD005Qu4\/C/i)).length,
    ).toBeGreaterThan(0)

    releaseInitialLookup(jsonResponse(bcPriors))
    await waitFor(() => {
      expect(
        screen.getByText('Pictou County only historical context—not province-wide or current field truth.'),
      ).toBeInTheDocument()
    })
    expect(screen.queryByText(/BC agriculture capability:/i)).not.toBeInTheDocument()
  })

  it('shows plain-language regional priors for drawn boundaries and dropped points', async () => {
    const fetchMock = installFetchMock()
    render(<OpenAgronomyApp />)

    openPrimaryPage('Map')
    fireEvent.click(screen.getByLabelText('Set field'))
    fireEvent.click(screen.getByRole('button', { name: 'Draw boundary' }))
    fireEvent.click(await screen.findByRole('button', { name: /mock draw boundary/i }))
    expect(screen.getByRole('button', { name: 'Save edits' })).toBeEnabled()
    fireEvent.click(screen.getByRole('button', { name: 'Save edits' }))

    expect(await screen.findByText(/Regional context refreshed: EPA Level III Ecoregion 47 matched at 92% confidence/i)).toBeInTheDocument()
    openPrimaryPage('Fields')
    openFieldTab('Map context')
    expect(screen.getByText('Southern Iowa Drift Plain')).toBeInTheDocument()
    expect(screen.getByText(/EPA Level III Ecoregion 47/i)).toBeInTheDocument()
    expect(screen.getByText(/Use this as regional guidance for retrieval and source checks/i)).toBeInTheDocument()
    expect(screen.getByText(/not as soil-test, scouting, yield, legal-boundary, or product-rate evidence/i)).toBeInTheDocument()
    openPrimaryPage('Map')
    expect(screen.getByTestId('mock-leaflet-map')).toHaveAttribute('data-geometry-kind', 'polygon')
    expect(screen.getByText(/50 ac · boundary estimate/i)).toBeVisible()
    expect(screen.getByTestId('mock-leaflet-map')).toHaveAttribute('data-point-count', '4')

    const boundaryPriorsCall = fetchMock.mock.calls.find(([url, init]) => {
      if (String(url) !== '/api/geo/priors' || init?.method !== 'POST') return false
      const body = JSON.parse(String(init.body || '{}'))
      return body.geometry?.type === 'Polygon'
    })
    expect(boundaryPriorsCall).toBeTruthy()

    fireEvent.click(screen.getByLabelText('Set field'))
    fireEvent.click(screen.getByRole('button', { name: 'Select point' }))
    fireEvent.click(screen.getByRole('button', { name: /mock drop point/i }))
    expect(screen.getByRole('button', { name: 'Save edits' })).toBeEnabled()
    fireEvent.click(screen.getByRole('button', { name: 'Save edits' }))

    expect(await screen.findByText(/Regional context refreshed: NRCS MLRA MLRA_103 matched at 94% confidence/i)).toBeInTheDocument()
    const mapContextBar = screen
      .getByRole('button', { name: 'Open field details' })
      .closest('.map-context-bar')
    expect(mapContextBar).not.toBeNull()
    expect(
      within(mapContextBar as HTMLElement).getAllByText(/NRCS MLRA MLRA_103/i),
    ).toHaveLength(2)
    expect(screen.queryByText('Central Iowa and Minnesota Till Prairies')).not.toBeInTheDocument()
    expect(screen.getByText(/Point location · NRCS MLRA MLRA_103/i)).toBeVisible()
    expect(screen.getByTestId('mock-leaflet-map')).toHaveAttribute('data-geometry-kind', 'point')
    openPrimaryPage('Fields')
    openFieldTab('Map context')
    expect(screen.getByText('Central Iowa and Minnesota Till Prairies')).toBeInTheDocument()

    const pointPriorsCall = fetchMock.mock.calls.find(([url, init]) => {
      if (String(url) !== '/api/geo/priors' || init?.method !== 'POST') return false
      const body = JSON.parse(String(init.body || '{}'))
      return body.geometry?.type === 'Point'
    })
    expect(pointPriorsCall).toBeTruthy()
  })

  it('keeps map edits as a cancellable draft until they are saved', async () => {
    installFetchMock()
    render(<OpenAgronomyApp />)

    await selectExample('central-alberta-barley', true)
    await screen.findByText(/Regional context refreshed: AAFC Alberta Detailed Soil Survey AB_SOIL_ABD192014361 matched at 100% confidence/i)
    // Let the initial field-bound weather request settle before changing the geometry.
    // Otherwise it can complete during the draft/cancel interaction and leave React's
    // asynchronous state update outside the test's observed work.
    await screen.findByTestId('map-nasa-power-summary')
    const map = await screen.findByTestId('mock-leaflet-map')
    expect(map).toHaveAttribute('data-first-lon', '-113.608')

    fireEvent.click(screen.getByLabelText('Set field'))
    fireEvent.click(screen.getByRole('button', { name: 'Draw boundary' }))
    fireEvent.click(screen.getByRole('button', { name: /mock draw boundary/i }))

    expect(screen.getByRole('button', { name: 'Save edits' })).toBeEnabled()
    expect(screen.getByTestId('mock-leaflet-map')).toHaveAttribute('data-first-lon', '-93.68')

    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))

    await waitFor(() => {
      expect(screen.queryByRole('button', { name: 'Save edits' })).not.toBeInTheDocument()
      expect(screen.getByTestId('mock-leaflet-map')).toHaveAttribute('data-first-lon', '-113.608')
      expect(screen.getByText(/Field edits cancelled\. The prior geometry and map context were restored\./i)).toBeInTheDocument()
    })
  })

  it('lets reviewers select a different uploaded feature and refreshes regional context from that geometry', async () => {
    const fetchMock = installFetchMock()
    render(<OpenAgronomyApp />)

    openPrimaryPage('Fields')
    const fileInput = await screen.findByLabelText('Boundary upload')
    fireEvent.change(fileInput, {
      target: { files: [new File([JSON.stringify({ type: 'FeatureCollection', features: [] })], 'two-fields.geojson')] },
    })

    const northButton = await screen.findByTestId('upload-feature-geojson:0')
    const southButton = await screen.findByTestId('upload-feature-geojson:1')
    expect(northButton).toHaveAttribute('aria-pressed', 'true')
    expect(southButton).toHaveAttribute('aria-pressed', 'false')

    fireEvent.click(southButton)

    await waitFor(() => expect(screen.getByTestId('upload-feature-geojson:1')).toHaveAttribute('aria-pressed', 'true'))
    const selectedPanel = screen.getByText('Selected feature').parentElement
    expect(selectedPanel).not.toBeNull()
    expect(within(selectedPanel as HTMLElement).getByText('South field')).toBeInTheDocument()
    openPrimaryPage('Map')
    expect(await screen.findByText(/Regional context refreshed: EPA Level III Ecoregion 47 matched/i)).toBeInTheDocument()
    expect(screen.getByTestId('mock-leaflet-map')).toHaveAttribute('data-first-lon', '-93.68')
    openPrimaryPage('Fields')
    openFieldTab('Map context')
    expect(screen.getByText(/Use this as regional guidance for retrieval and source checks/i)).toBeInTheDocument()
    expect(screen.getByText('Southern Iowa Drift Plain')).toBeInTheDocument()
    expect(screen.getByText('EPA Level III Ecoregion 47')).toBeInTheDocument()
    expect(screen.getAllByText('Official layer source')[0]).toHaveAttribute(
      'href',
      'https://www.epa.gov/eco-research/level-iii-and-iv-ecoregions-continental-united-states',
    )

    const priorsCall = fetchMock.mock.calls.find(([url, init]) => {
      if (String(url) !== '/api/geo/priors' || init?.method !== 'POST') return false
      const body = JSON.parse(String(init.body || '{}'))
      return body.geometry?.coordinates?.[0]?.[0]?.[0] === -93.68
    })
    expect(priorsCall).toBeTruthy()
    const body = JSON.parse(String(priorsCall?.[1]?.body || '{}'))
    expect(body.geometry.type).toBe('Polygon')
    expect(body.geometry.coordinates[0][0]).toEqual([-93.68, 42.08])
    openPrimaryPage('Map')
    expect(screen.getByTestId('mock-leaflet-map')).toHaveAttribute('data-first-lon', '-93.68')
  })

  it('stores uploaded map context through the local workspace field API', async () => {
    const fetchMock = installFetchMock()
    render(<OpenAgronomyApp />)

    await selectExample()
    await screen.findAllByText(/Saved to My agronomy workspace/i)
    const fileInput = await screen.findByLabelText('Boundary upload')
    fireEvent.change(fileInput, {
      target: { files: [new File([JSON.stringify({ type: 'FeatureCollection', features: [] })], 'two-fields.geojson')] },
    })
    await screen.findByTestId('upload-feature-geojson:0')

    fireEvent.click(screen.getByRole('button', { name: /save field/i }))

    await waitFor(() =>
      expect(screen.getByText('barley · Leduc County')).toBeInTheDocument(),
    )
    const saveCall = fetchMock.mock.calls.find(
      ([url, init]) => String(url) === '/api/demo/fields' && init?.method === 'POST',
    )
    expect(saveCall).toBeTruthy()
    const body = JSON.parse(String(saveCall?.[1]?.body || '{}'))
    expect(body.geometry.kind).toBe('polygon')
    expect(body.regionalContext).toBe('NRCS MLRA MLRA_103')
    expect(body.sourceBoundary).toContain('context priors')
  })

  it('checks saved Quebec offline context from the Fields tab without starting a download', async () => {
    const quebecField = {
      id: 'field-quebec',
      field_context_id: 'field-quebec',
      name: 'Quebec field',
      crop: 'maïs',
      region: 'Chaudière-Appalaches',
      jurisdiction: 'Québec',
      acres: '20',
      concern: 'écoulement de surface',
      notes: '',
      geometry: {
        kind: 'polygon',
        points: [
          { lat: 46.80, lon: -70.39 },
          { lat: 46.80, lon: -70.38 },
          { lat: 46.81, lon: -70.38 },
          { lat: 46.81, lon: -70.39 },
        ],
        acres: 20,
      },
      regionalContext: 'Quebec regional context',
      geoPriors: null,
      sourceBoundary: 'Regional context is not field truth.',
      createdAt: '2026-07-25T12:00:00Z',
      storageMode: 'account_workspace',
    }
    const fetchMock = installFetchMock({ ...emptyDemoFields, fields: [quebecField] })
    render(<OpenAgronomyApp />)

    openPrimaryPage('Fields')
    await screen.findAllByText(/Saved to My agronomy workspace/i)
    fireEvent.click(screen.getAllByRole('button', { name: /Quebec field/i })[0])
    openFieldTab('Map context')
    fireEvent.click(await screen.findByText('Offline terrain context'))
    fireEvent.click(await screen.findByRole('button', { name: 'Check saved field' }))

    expect(await screen.findByText('1 official MAPAQ source tile')).toBeInTheDocument()
    expect(screen.getByText('Context only · not downloaded · not recommendation grade')).toBeInTheDocument()
    expect(screen.getByText(/Field binding dddddddddddd/i)).toBeInTheDocument()
    expect(
      fetchMock.mock.calls.some(
        ([url, init]) =>
          String(url) === '/api/demo/fields/field-quebec/context-packs/quebec-lidar/plan'
          && init?.method === 'POST',
      ),
    ).toBe(true)
  })

  it('restores the selected account field after reload so new turns retain field lineage', async () => {
    const storedField = {
      id: 'field-restored',
      field_context_id: 'field-restored',
      name: 'Restored Fraser Valley field',
      crop: 'mixed cropping',
      region: 'Fraser Valley',
      jurisdiction: 'British Columbia',
      acres: '96',
      concern: 'standing water in the northeast corner',
      notes: '',
      geometry: {
        kind: 'polygon',
        points: [
          { lat: 49.04, lon: -122.31 },
          { lat: 49.04, lon: -122.29 },
          { lat: 49.06, lon: -122.29 },
          { lat: 49.06, lon: -122.31 },
        ],
        acres: 96,
      },
      regionalContext: 'AAFC Canada Ecozone 13',
      geoPriors: bcPriors,
      sourceBoundary: 'Regional context is not field truth.',
      createdAt: '2026-07-25T12:00:00Z',
      updatedAt: '2026-07-26T12:00:00Z',
      storageMode: 'account_workspace',
    }
    window.localStorage.setItem('open-agronomy-agent.active-field.v1', 'field-restored')
    const fetchMock = installFetchMock(
      { ...emptyDemoFields, fields: [storedField] },
      uploadPayload,
      [{
        session_id: 'session-restored',
        context: {
          field_context_id: 'field-restored',
          field_conversation_key: 'field:field-restored',
        },
        turns: [],
      }],
    )

    render(<OpenAgronomyApp />)
    openPrimaryPage('Fields')

    expect(await screen.findByText('Restored Fraser Valley field')).toBeInTheDocument()
    openFieldTab('Records & soil tests')
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(
        ([url]) => String(url) === '/api/demo/fields/field-restored/history',
      )).toBe(true),
    )
    expect(screen.getByText(/0 field records · 0 answers/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Refresh field timeline' })).toBeEnabled()
    await waitFor(() =>
      expect(screen.queryByText('Save or load the field in this workspace first.')).not.toBeInTheDocument(),
    )
    expect(window.localStorage.getItem('open-agronomy-agent.active-field.v1')).toBe('field-restored')
  })

  it('uses the field library to load, update, and start a clean field without crossing chat context', async () => {
    const northField = {
      id: 'field-north', field_context_id: 'field-north', name: 'North field', crop: 'canola',
      region: 'Leduc County', jurisdiction: 'Alberta', acres: '80', concern: 'wet spots', notes: '',
      geometry: { kind: 'point', point: { lat: 53.3, lon: -113.6 } }, regionalContext: 'Alberta soil context',
      geoPriors: null, sourceBoundary: 'Regional context is not field truth.',
      createdAt: '2026-07-10T12:00:00Z', updatedAt: '2026-08-10T12:00:00Z', storageMode: 'account_workspace',
    }
    const southField = {
      ...northField,
      id: 'field-south', field_context_id: 'field-south', name: 'South field', crop: 'barley',
      region: 'Beaumont', updatedAt: '2026-08-11T12:00:00Z',
    }
    const fetchMock = installFetchMock(
      { ...emptyDemoFields, fields: [northField, southField] },
      uploadPayload,
      [
        {
          session_id: 'north-session',
          context: { field_context_id: 'field-north', field_conversation_key: 'field:field-north' },
          turns: [{ turn_id: 'north-turn', user_message: 'North question', answer: 'North answer', trace: { retrieved_docs: [], graph_hits: [], tool_invocations: [] } }],
        },
        {
          session_id: 'south-session',
          context: { field_context_id: 'field-south', field_conversation_key: 'field:field-south' },
          turns: [{ turn_id: 'south-turn', user_message: 'South question', answer: 'South answer', trace: { retrieved_docs: [], graph_hits: [], tool_invocations: [] } }],
        },
      ],
    )
    render(<OpenAgronomyApp />)

    openPrimaryPage('Fields')
    await screen.findByText('North field')
    fireEvent.change(screen.getByRole('textbox', { name: 'Search saved fields' }), { target: { value: 'south' } })
    expect(screen.queryByText('North field')).not.toBeInTheDocument()
    fireEvent.change(screen.getByRole('textbox', { name: 'Search saved fields' }), { target: { value: '' } })

    fireEvent.click(screen.getByRole('button', { name: /^North field/ }))
    openPrimaryPage('Map')
    expect(await screen.findByText('North answer')).toBeInTheDocument()
    openPrimaryPage('Fields')
    fireEvent.change(screen.getByLabelText('Crop'), { target: { value: 'peas' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save field' }))
    await waitFor(() => expect(fetchMock.mock.calls.some(
      ([url, init]) => String(url) === '/api/demo/fields/field-north' && init?.method === 'PATCH',
    )).toBe(true))
    openPrimaryPage('Map')
    expect(screen.getByText('North answer')).toBeInTheDocument()

    openPrimaryPage('Fields')
    fireEvent.click(screen.getByRole('button', { name: 'Save as new field' }))
    await waitFor(() => expect(fetchMock.mock.calls.some(
      ([url, init]) => String(url) === '/api/demo/fields' && init?.method === 'POST'
        && JSON.parse(String(init.body || '{}')).name === 'North field copy',
    )).toBe(true))
    fireEvent.click(screen.getByRole('button', { name: /^South field/ }))
    openPrimaryPage('Map')
    expect(await screen.findByText('South answer')).toBeInTheDocument()
    expect(screen.queryByText('North answer')).not.toBeInTheDocument()

    openPrimaryPage('Fields')
    fireEvent.click(screen.getByRole('button', { name: 'New field' }))
    const setup = await screen.findByRole('dialog', { name: 'Add a field' })
    expect(within(setup).getByLabelText('Field name')).toHaveValue('')
    expect(within(setup).getByText('Step 1 of 3')).toBeInTheDocument()
    expect(screen.queryByText('South answer')).not.toBeInTheDocument()
  })

  it('creates a blank field through the guided boundary workflow before storing it', async () => {
    const fetchMock = installFetchMock()
    render(<OpenAgronomyApp />)

    openPrimaryPage('Fields')
    const newField = screen.getByRole('button', { name: 'New field' })
    await waitFor(() => expect(newField).toBeEnabled())
    fireEvent.click(newField)
    const setup = await screen.findByRole('dialog', { name: 'Add a field' })
    fireEvent.change(within(setup).getByLabelText('Field name'), { target: { value: 'West quarter' } })
    fireEvent.change(within(setup).getByLabelText(/Crop/), { target: { value: 'oats' } })
    fireEvent.click(within(setup).getByRole('button', { name: 'Continue' }))
    expect(within(setup).getByText('Step 2 of 3')).toBeInTheDocument()
    fireEvent.click(within(setup).getByRole('button', { name: 'Draw boundary' }))
    fireEvent.click(await within(setup).findByRole('button', { name: 'Mock draw boundary' }))
    fireEvent.click(within(setup).getByRole('button', { name: 'Continue' }))
    expect(within(setup).getByText('Step 3 of 3')).toBeInTheDocument()
    expect(within(setup).getByText(/calculated from boundary/i)).toBeInTheDocument()
    fireEvent.click(within(setup).getByRole('button', { name: 'Save field' }))
    await waitFor(() => expect(fetchMock.mock.calls.some(
      ([url, init]) => String(url) === '/api/demo/fields' && init?.method === 'POST'
        && JSON.parse(String(init.body || '{}')).name === 'West quarter',
    )).toBe(true))
    expect(screen.getByRole('heading', { name: 'West quarter' })).toBeInTheDocument()
  })

  it('creates a data-only field through the wizard without requesting regional map context', async () => {
    const fetchMock = installFetchMock()
    render(<OpenAgronomyApp />)

    openPrimaryPage('Fields')
    const newField = screen.getByRole('button', { name: 'New field' })
    await waitFor(() => expect(newField).toBeEnabled())
    fireEvent.click(newField)
    const setup = await screen.findByRole('dialog', { name: 'Add a field' })
    fireEvent.change(within(setup).getByLabelText('Field name'), { target: { value: 'Table-only field' } })
    fireEvent.click(within(setup).getByRole('button', { name: 'Continue' }))
    fireEvent.click(within(setup).getByRole('button', { name: 'No location yet · data only' }))
    fireEvent.click(within(setup).getByRole('button', { name: 'Continue' }))
    expect(within(setup).getByText('Unknown · data only')).toBeInTheDocument()
    const priorCalls = fetchMock.mock.calls.filter(([url]) => String(url) === '/api/geo/priors').length
    fireEvent.click(within(setup).getByRole('button', { name: 'Save field' }))
    await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) => String(url) === '/api/demo/fields' && init?.method === 'POST')).toBe(true))
    const saveCall = fetchMock.mock.calls.find(([url, init]) => String(url) === '/api/demo/fields' && init?.method === 'POST')
    expect(JSON.parse(String(saveCall?.[1]?.body || '{}'))).toMatchObject({
      name: 'Table-only field', geometry: { kind: 'none' }, regionalContext: '', geoPriors: null,
    })
    expect(fetchMock.mock.calls.filter(([url]) => String(url) === '/api/geo/priors')).toHaveLength(priorCalls)
    openPrimaryPage('Fields')
    expect(screen.getByText('Saved · no location')).toBeInTheDocument()
  })

  it('stores a named data-only field without inventing geometry or regional context', async () => {
    const fetchMock = installFetchMock()
    render(<OpenAgronomyApp />)

    openPrimaryPage('Fields')
    await screen.findByText('Saved to My agronomy workspace.')
    fireEvent.click(screen.getByRole('button', { name: 'New field' }))
    fireEvent.click(within(await screen.findByRole('dialog', { name: 'Add a field' })).getByRole('button', { name: 'Close Add a field' }))
    expect(screen.getByRole('button', { name: 'Save field' })).toBeDisabled()
    expect(screen.getByText('Boundary optional')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Field name'), { target: { value: 'Anonymous nitrate field' } })
    expect(screen.getByRole('button', { name: 'Save field' })).toBeEnabled()
    const priorCallsBeforeSave = fetchMock.mock.calls.filter(([url]) => String(url) === '/api/geo/priors').length
    fireEvent.click(screen.getByRole('button', { name: 'Save field' }))

    await waitFor(() => expect(fetchMock.mock.calls.map(([url, init]) => `${init?.method || 'GET'} ${String(url)}`)).toContain('POST /api/demo/fields'))
    const saveCall = fetchMock.mock.calls.find(
      ([url, init]) => String(url) === '/api/demo/fields' && init?.method === 'POST',
    )
    const body = JSON.parse(String(saveCall?.[1]?.body || '{}'))
    expect(body).toMatchObject({
      name: 'Anonymous nitrate field', geometry: { kind: 'none' }, geoPriors: null, regionalContext: '',
    })
    expect(body.sourceBoundary).toContain('No location or boundary supplied')
    expect(fetchMock.mock.calls.filter(([url]) => String(url) === '/api/geo/priors')).toHaveLength(priorCallsBeforeSave)
    expect(screen.getByText('Saved · no location')).toBeInTheDocument()
    openPrimaryPage('Map')
    expect(screen.getByText('No location selected')).toBeInTheDocument()
  })

  it('enables imagery for a saved polygon without acreage and blocks it after unsaved coordinate changes', async () => {
    const savedField = {
      id: 'field-public', field_context_id: 'field-public', name: 'Public support area', crop: '',
      region: 'Colorado', jurisdiction: 'United States', acres: '', concern: '', notes: '',
      geometry: { kind: 'polygon', points: southRing.slice(0, -1).map(([lon, lat]) => ({ lat, lon })) },
      regionalContext: '', geoPriors: null, sourceBoundary: 'Research support, not a surveyed field boundary.',
      createdAt: '2026-09-27T00:00:00Z', storageMode: 'account_workspace',
    }
    const fetchMock = installFetchMock({ ...emptyDemoFields, fields: [savedField] })
    const baseFetch = fetchMock.getMockImplementation()!
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) =>
      String(input) === '/api/demo/fields/field-public/imagery/analytics'
        ? Promise.resolve(jsonResponse({ status: 'ready', network_mode: 'online' }))
        : baseFetch(input, init))
    render(<OpenAgronomyApp />)

    openPrimaryPage('Fields')
    fireEvent.click(await screen.findByRole('button', { name: /^Public support area/ }))
    openFieldTab('Records & soil tests')
    fireEvent.click(await screen.findByText('Observed satellite indices'))
    fireEvent.change(screen.getByLabelText('Acquired from'), { target: { value: '2025-06-01' } })
    fireEvent.change(screen.getByLabelText('Acquired through'), { target: { value: '2025-06-30' } })
    await waitFor(() => expect(screen.getByRole('button', { name: 'Analyze scene' })).toBeEnabled())

    openFieldTab('Overview')
    fireEvent.change(screen.getByLabelText('Boundary upload'), {
      target: { files: [new File([JSON.stringify({ type: 'FeatureCollection', features: [] })], 'changed.geojson')] },
    })
    await screen.findByTestId('upload-feature-geojson:0')
    openFieldTab('Records & soil tests')
    expect(screen.getByRole('button', { name: 'Analyze scene' })).toBeDisabled()
    expect(screen.getByText(/Save a valid field polygon before analyzing imagery/)).toBeInTheDocument()
  })

  it('keeps the active field selected when deleting another field and clears context when deleting the active field', async () => {
    const northField = {
      id: 'field-north', field_context_id: 'field-north', name: 'North field', crop: 'canola',
      region: 'Leduc County', jurisdiction: 'Alberta', acres: '80', concern: '', notes: '',
      geometry: { kind: 'point', point: { lat: 53.3, lon: -113.6 } }, regionalContext: 'Alberta soil context',
      geoPriors: null, sourceBoundary: 'Regional context is not field truth.',
      createdAt: '2026-07-10T12:00:00Z', storageMode: 'account_workspace',
    }
    const southField = { ...northField, id: 'field-south', field_context_id: 'field-south', name: 'South field' }
    const fetchMock = installFetchMock({ ...emptyDemoFields, fields: [northField, southField] })
    render(<OpenAgronomyApp />)

    openPrimaryPage('Fields')
    fireEvent.click(await screen.findByRole('button', { name: /^North field/ }))
    expect(screen.getByLabelText('Field name')).toHaveValue('North field')
    fireEvent.click(screen.getByRole('button', { name: 'Delete South field' }))
    expect(screen.getByRole('dialog', { name: 'Delete field?' })).toHaveTextContent('South field')
    expect(fetchMock.mock.calls.some(([url, init]) => String(url).includes('field-south') && init?.method === 'DELETE')).toBe(false)
    fireEvent.click(within(screen.getByRole('dialog', { name: 'Delete field?' })).getByRole('button', { name: 'Delete field' }))
    await waitFor(() => expect(screen.queryByText('South field')).not.toBeInTheDocument())
    expect(screen.getByLabelText('Field name')).toHaveValue('North field')

    fireEvent.click(screen.getByRole('button', { name: 'Delete North field' }))
    fireEvent.click(within(screen.getByRole('dialog', { name: 'Delete field?' })).getByRole('button', { name: 'Delete field' }))
    await waitFor(() => expect(screen.getByLabelText('Field name')).toHaveValue(''))
    expect(screen.getByText('New field setup')).toBeInTheDocument()
    expect(fetchMock.mock.calls.filter(([url, init]) => String(url).startsWith('/api/demo/fields/') && init?.method === 'DELETE')).toHaveLength(2)
  })

  it('starts a new conversation identity instead of rebinding old answers to a saved field', async () => {
    const fetchMock = installFetchMock(emptyDemoFields, uploadPayload, [{
      session_id: 'session-old-sample',
      context: { field_conversation_key: 'sample:central-alberta-barley' },
      turns: [{
        turn_id: 'turn-old-sample',
        user_message: 'Old BC field question',
        answer: 'Old BC field answer',
        trace: { retrieved_docs: [], graph_hits: [], tool_invocations: [] },
      }],
    }])
    render(<OpenAgronomyApp />)

    await selectExample('central-alberta-barley', true)
    expect(await screen.findByText('Old BC field answer')).toBeInTheDocument()
    openPrimaryPage('Fields')
    fireEvent.change(await screen.findByLabelText('Boundary upload'), {
      target: { files: [new File([JSON.stringify({ type: 'Polygon', coordinates: [northRing] })], 'field.geojson')] },
    })
    await screen.findByTestId('upload-feature-geojson:0')
    fireEvent.click(screen.getByRole('button', { name: /save field/i }))

    await waitFor(() => expect(screen.queryByText('Old BC field answer')).not.toBeInTheDocument())
    expect(
      fetchMock.mock.calls.some(
        ([url, init]) => String(url) === '/api/sessions/session-old-sample' && init?.method === 'PATCH',
      ),
    ).toBe(false)
  })

  it('preserves account-backed fields beyond the device fallback cap when saving', async () => {
    window.localStorage.setItem(
      'open-agronomy-agent.fields.v1',
      JSON.stringify(Array.from({ length: 20 }, (_, index) => ({ id: `stale-device-${index}` }))),
    )
    const fields = Array.from({ length: 13 }, (_, index) => ({
      id: `existing-${index}`,
      field_context_id: `existing-${index}`,
      name: `Existing field ${index + 1}`,
      crop: 'wheat',
      region: 'Saskatchewan',
      jurisdiction: 'Saskatchewan',
      acres: '80',
      concern: '',
      notes: '',
      geometry: { kind: 'point', point: { lat: 50.4, lon: -104.6 } },
      regionalContext: 'regional context',
      geoPriors: null,
      sourceBoundary: 'Regional context is not field truth.',
      createdAt: `2026-07-${String(index + 1).padStart(2, '0')}T12:00:00Z`,
      storageMode: 'account_workspace',
    }))
    installFetchMock({ ...emptyDemoFields, fields })
    const { container } = render(<OpenAgronomyApp />)

    await selectExample()
    await waitFor(() => expect(container.querySelectorAll('.field-library-list article')).toHaveLength(13))
    expect(screen.queryByText('stale-device-1')).not.toBeInTheDocument()
    const fileInput = await screen.findByLabelText('Boundary upload')
    fireEvent.change(fileInput, {
      target: { files: [new File([JSON.stringify({ type: 'FeatureCollection', features: [] })], 'two-fields.geojson')] },
    })
    await screen.findByTestId('upload-feature-geojson:0')
    fireEvent.click(screen.getByRole('button', { name: /save field/i }))

    await waitFor(() => expect(container.querySelectorAll('.field-library-list article')).toHaveLength(14))
    expect(screen.getByText('Existing field 13')).toBeInTheDocument()
    expect(screen.getByText('barley · Leduc County')).toBeInTheDocument()
  })

  it('adds an immutable field record to the selected field timeline', async () => {
    const storedField = {
      id: 'field-context-1',
      field_context_id: 'field-context-1',
      name: 'North quarter',
      crop: 'canola',
      region: 'Regina Plain',
      jurisdiction: 'Saskatchewan',
      acres: '160',
      concern: '',
      notes: '',
      geometry: { kind: 'point', point: { lat: 50.4, lon: -104.6 } },
      regionalContext: 'Saskatchewan soil region',
      geoPriors: null,
      sourceBoundary: 'Regional context is not field truth.',
      createdAt: '2026-07-20T12:00:00Z',
      updatedAt: '2026-07-20T12:00:00Z',
      storageMode: 'account_workspace',
    }
    const otherField = { ...storedField, id: 'field-context-2', field_context_id: 'field-context-2', name: 'South quarter' }
    const records: Array<Record<string, unknown>> = []
    let rejectFirstRecord: ((error: Error) => void) | undefined
    let releaseCorrection: (() => void) | undefined
    let recordAttempts = 0
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url === '/api/sessions?include_archived=true&include_turns=false') return jsonResponse([])
      if (url === '/api/configs') return jsonResponse(bootConfig)
      if (url === '/api/tools/public-adapter-readiness') return jsonResponse(adapterReadiness)
      if (url === '/api/demo/fields') return jsonResponse({ ...emptyDemoFields, fields: [storedField, otherField] })
      if (url === '/api/demo/fields/field-context-1/events' && init?.method === 'POST') {
        recordAttempts += 1
        if (recordAttempts === 1) return new Promise<Response>((_resolve, reject) => { rejectFirstRecord = reject })
        if (recordAttempts === 3) await new Promise<void>((resolve) => { releaseCorrection = resolve })
        const body = JSON.parse(String(init.body || '{}'))
        records.push({
          id: 'event-1',
          event_type: body.event_type,
          occurred_at: body.occurred_at || '2026-07-21T14:00:00Z',
          payload: body.payload,
          provenance: body.provenance,
          corrects_event_id: body.corrects_event_id || null,
          previous_event_sha256: null,
          integrity_sha256: 'a'.repeat(64),
          recorded_at: '2026-07-21T14:00:00Z',
        })
        return jsonResponse({
          schema_version: 'open_agronomy_agent.demo_field_event_appended.v1',
          event: records[0],
          chain: { valid: true, event_count: 1, head_sha256: 'a'.repeat(64), failure_count: 0 },
        })
      }
      if (url === '/api/demo/fields/field-context-1/history') {
        return jsonResponse({
          schema_version: 'open_agronomy_agent.demo_field_history.v4',
          field: storedField,
          event_count: records.length,
          events: records,
          event_chain: {
            valid: true,
            event_count: records.length,
            head_sha256: records.length ? 'a'.repeat(64) : null,
            failure_count: 0,
          },
          turn_count: 0,
          turns: [],
          boundary: 'Field records are append-only.',
        })
      }
      if (url === '/api/demo/fields/field-context-2/history') return jsonResponse({
        schema_version: 'open_agronomy_agent.demo_field_history.v4',
        field: otherField,
        event_count: 0,
        events: [],
        event_chain: { valid: true, event_count: 0, head_sha256: null, failure_count: 0 },
        turn_count: 0,
        turns: [],
        boundary: 'Field records are append-only.',
      })
      if (url === '/api/geo/priors') return jsonResponse(skPriors)
      if (url === '/api/tools/aafc-nasdi-agroclimate') return jsonResponse(nasdiConditions)
      return jsonResponse({})
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<OpenAgronomyApp />)

    openPrimaryPage('Fields')
    fireEvent.click(await screen.findByText('North quarter'))
    openFieldTab('Records & soil tests')
    await screen.findByText('0 field records · 0 answers.')
    expect(screen.getByText(/Saved answers stay linked to the exact field snapshot/i)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Add record' }))
    expect((screen.getByLabelText('When it happened') as HTMLInputElement).value).not.toBe('')
    fireEvent.change(screen.getByLabelText('What happened'), {
      target: { value: 'Standing water observed in the northwest corner.' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save record' }))
    fireEvent.submit(screen.getByRole('form', { name: 'Add field record' }))
    expect(recordAttempts).toBe(1)
    expect(screen.getByRole('button', { name: 'Saving…' })).toBeDisabled()
    const draftDate = (screen.getByLabelText('When it happened') as HTMLInputElement).value
    fireEvent(screen.getByRole('dialog', { name: 'Add field record' }), new Event('cancel', { bubbles: true, cancelable: true }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    await act(async () => { rejectFirstRecord?.(new Error('offline')) })
    fireEvent.click(screen.getByRole('button', { name: 'Resume unsaved record' }))
    expect(screen.getByLabelText('When it happened')).toHaveValue(draftDate)
    expect(screen.getByLabelText('Record type')).toHaveValue('observation')
    expect(within(screen.getByRole('dialog', { name: 'Add field record' })).getByRole('alert')).toHaveTextContent('Save not confirmed: offline')
    expect(screen.getByLabelText('What happened')).toHaveValue('Standing water observed in the northwest corner.')
    fireEvent.click(screen.getByRole('button', { name: 'Save record' }))

    expect(await screen.findByText('Standing water observed in the northwest corner.')).toBeInTheDocument()
    fireEvent.click(screen.getByText('Record details'))
    expect(screen.getByText(/Immutable record · aaaaaaaaaa/)).toBeInTheDocument()
    const request = fetchMock.mock.calls.find(
      ([url, init]) => String(url) === '/api/demo/fields/field-context-1/events' && init?.method === 'POST',
    )
    expect(JSON.parse(String(request?.[1]?.body))).toMatchObject({
      event_type: 'observation',
      payload: { summary: 'Standing water observed in the northwest corner.' },
      provenance: { capture_method: 'user_entered', surface: 'fields_timeline' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Correct' }))
    expect(screen.getByLabelText('Record to correct')).toHaveValue('event-1')
    fireEvent.change(screen.getByLabelText('What happened'), { target: { value: 'Corrected location: southwest corner.' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save correction' }))
    await waitFor(() => expect(fetchMock.mock.calls.filter(([url, init]) => String(url) === '/api/demo/fields/field-context-1/events' && init?.method === 'POST')).toHaveLength(3))
    const correctionRequest = fetchMock.mock.calls.filter(([url, init]) => String(url) === '/api/demo/fields/field-context-1/events' && init?.method === 'POST')[2]
    expect(JSON.parse(String(correctionRequest?.[1]?.body))).toMatchObject({
      event_type: 'correction',
      corrects_event_id: 'event-1',
      payload: { summary: 'Corrected location: southwest corner.', correction_kind: 'user_entered' },
    })
    fireEvent(screen.getByRole('dialog', { name: 'Correct field record' }), new Event('cancel', { bubbles: true, cancelable: true }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Add record' })).toBeDisabled()
    fireEvent.click(screen.getByText('South quarter'))
    await act(async () => { releaseCorrection?.() })
    openFieldTab('Records & soil tests')
    expect(screen.queryByText('Corrected location: southwest corner.')).not.toBeInTheDocument()
    expect(await screen.findByText('0 field records · 0 answers.')).toBeInTheDocument()
  })

  it('refreshes verified field-linked answer history after a streamed turn completes', async () => {
    const storedField = {
      id: 'field-context-1',
      field_context_id: 'field-context-1',
      name: 'North quarter',
      crop: 'canola',
      region: 'Regina Plain',
      jurisdiction: 'Saskatchewan',
      acres: '160',
      concern: 'standing water after irrigation',
      notes: '',
      geometry: { kind: 'point', point: { lat: 50.4, lon: -104.6 } },
      regionalContext: 'Saskatchewan soil region',
      geoPriors: null,
      sourceBoundary: 'Regional context is not field truth.',
      createdAt: '2026-07-20T12:00:00Z',
      updatedAt: '2026-07-20T12:00:00Z',
      storageMode: 'account_workspace',
    }
    const completedTurn = {
      turn_id: 'turn-field-1',
      user_message: 'What should I check next?',
      answer: 'Check drainage and current soil moisture before field traffic.',
      answer_status: 'draft',
      answer_integrity_receipt: {
        schema_version: 'open_agronomy_agent.answer_integrity_receipt.v1',
        status: 'verified',
        receipt_sha256: 'c'.repeat(64),
        question_sha256: 'd'.repeat(64),
        answer_sha256: 'e'.repeat(64),
        trace_sha256: 'f'.repeat(64),
        system_state_sha256: '1'.repeat(64),
        field_snapshot_sha256: 'b'.repeat(64),
        boundary: 'Application-level immutable content receipt; not a digital signature.',
      },
      system_state: {
        mode: 'agronomic_rag',
        model_id: 'mlx-community/gemma-4-e2b-it-4bit',
        rag_config: 'configs/rag_governed_runtime_v2.yaml',
        prompt_version: 'conference',
        model_identity: {
          schema_version: 'open_agronomy_agent.model_identity_contract.v1',
          status: 'verified_runtime_receipt',
          configured_model_id: 'mlx-community/gemma-4-e2b-it-4bit',
          configured_model_revision: '238767527555cb75a05732a84dff5d6ba0dd6809',
          backend: 'openai_compatible_http',
          response_model_id: 'default_model',
        },
      },
      trace: {
        route: { question_type: 'field_data', risk_level: 'low' },
        retrieved_docs: [],
        graph_hits: [],
        tool_invocations: [],
        metadata: {
          canadian_coverage_boundaries: [{
            jurisdiction: 'Saskatchewan',
            status: 'live_reference_only',
            requires_prompt_boundary: true,
            registered_source_ids: ['sk-agriculture-crops'],
            distributable_source_ids: [],
            retrieved_source_ids: [],
            retrieved_context_source_ids: ['ca-regional-context-sk'],
          }],
          field_lineage: {
            field_context_id: 'field-context-1',
            field_snapshot_sha256: 'b'.repeat(64),
            field_history: { chain_valid: true, event_count: 0, head_sha256: null },
            field_answer_history: {
              total_bound_turn_count: 2,
              included_turn_count: 2,
              prior_model_answers_are_evidence: false,
            },
          },
        },
      },
      knowledge_coverage: {
        schema_version: 'open_agronomy_agent.answer_time_knowledge_coverage.v1',
        capture_status: 'captured',
        record_source: 'trace_metadata',
        boundaries: [{
          jurisdiction: 'Saskatchewan',
          status: 'live_reference_only',
          requires_prompt_boundary: true,
          registered_source_ids: ['sk-agriculture-crops'],
          distributable_source_ids: [],
          retrieved_source_ids: [],
          retrieved_context_source_ids: ['ca-regional-context-sk'],
        }],
      },
    }
    let historyRequestCount = 0
    let answerAccepted: boolean | null = null
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url === '/api/sessions?include_archived=true&include_turns=false') {
        return jsonResponse([{
          session_id: 'session-field-1',
          title: 'North quarter',
          context: {
            field_context_id: 'field-context-1',
            field_conversation_key: 'field:field-context-1',
          },
          turns: [],
        }])
      }
      if (url === '/api/configs') return jsonResponse(bootConfig)
      if (url === '/api/tools/public-adapter-readiness') return jsonResponse(adapterReadiness)
      if (url === '/api/demo/fields') return jsonResponse({ ...emptyDemoFields, fields: [storedField] })
      if (url === '/api/demo/fields/field-context-1/history') {
        historyRequestCount += 1
        const hasAnswer = historyRequestCount > 1
        return jsonResponse({
          schema_version: 'open_agronomy_agent.demo_field_history.v4',
          field: storedField,
          event_count: 0,
          events: [],
          event_chain: { valid: true, event_count: 0, head_sha256: null, failure_count: 0 },
          turn_count: hasAnswer ? 1 : 0,
          turns: hasAnswer
            ? [{
                session_id: 'session-field-1',
                turn_id: completedTurn.turn_id,
                question: completedTurn.user_message,
                answer: completedTurn.answer,
                answer_status: answerAccepted === null ? 'draft' : 'reviewed',
                answer_integrity_receipt: completedTurn.answer_integrity_receipt,
                feedback: answerAccepted === null
                  ? {}
                  : { accepted: answerAccepted, answer_status: answerAccepted ? 'reviewed' : 'rejected' },
                binding_status: 'verified_snapshot',
                knowledge_coverage: {
                  schema_version: 'open_agronomy_agent.answer_time_knowledge_coverage.v1',
                  capture_status: 'captured',
                  record_source: 'trace_metadata',
                  boundaries: [{
                    jurisdiction: 'Saskatchewan',
                    status: 'live_reference_only',
                    requires_prompt_boundary: true,
                    registered_source_ids: ['sk-agriculture-crops'],
                    distributable_source_ids: [],
                    retrieved_source_ids: [],
                    retrieved_context_source_ids: [],
                  }],
                },
                retrieved_document_count: 0,
                tool_invocation_count: 0,
                field_lineage: { field_snapshot_sha256: 'b'.repeat(64) },
              }]
            : [],
          boundary: 'Field answers preserve snapshot lineage.',
        })
      }
      if (url === '/api/sessions/session-field-1/turns/stream') {
        return {
          ok: true,
          status: 200,
          body: null,
          text: async () => (
            `event: answer.completed\n`
            + `data: ${JSON.stringify({ turn_id: completedTurn.turn_id, turn: completedTurn })}\n\n`
          ),
        } as Response
      }
      if (url === '/api/feedback' && init?.method === 'POST') {
        const payload = JSON.parse(String(init.body || '{}'))
        answerAccepted = payload.accepted
        return jsonResponse({ status: 'ok', feedback: payload })
      }
      if (url === '/api/tools/aafc-nasdi-agroclimate') return jsonResponse(nasdiConditions)
      return jsonResponse({})
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<OpenAgronomyApp />)

    openPrimaryPage('Fields')
    fireEvent.click(await screen.findByText('North quarter'))
    openFieldTab('Records & soil tests')
    await screen.findByText('0 field records · 0 answers.')
    openPrimaryPage('Map')
    fireEvent.change(screen.getByLabelText('Ask about this field'), {
      target: { value: completedTurn.user_message },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Ask' }))

    await screen.findByText(completedTurn.answer)
    openPrimaryPage('Fields')
    openFieldTab('Records & soil tests')
    expect(await screen.findByText('0 field records · 1 answer.')).toBeInTheDocument()
    expect(screen.getByText('Field snapshot verified')).toBeInTheDocument()
    expect(screen.getByText('Local guidance missing')).toBeInTheDocument()
    expect(screen.getByText('Unreviewed answer')).toBeInTheDocument()
    expect(screen.getByText(/answer receipt c{12}/i)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Mark useful' }))
    expect(await screen.findByText('Marked useful')).toBeInTheDocument()
    const feedbackRequest = fetchMock.mock.calls.find(
      ([url, init]) => String(url) === '/api/feedback' && init?.method === 'POST',
    )
    expect(JSON.parse(String(feedbackRequest?.[1]?.body))).toMatchObject({
      session_id: 'session-field-1',
      turn_id: 'turn-field-1',
      accepted: true,
      answer_status: 'reviewed',
    })
    fireEvent.click(screen.getByRole('button', { name: 'Review evidence' }))
    const lineage = await screen.findByText('Technical receipt & export', { selector: 'summary' })
    fireEvent.click(lineage)
    expect(lineage.closest('details')).toHaveAttribute('open')
    expect(screen.getByText('b'.repeat(64))).toBeInTheDocument()
    expect(screen.getByText(completedTurn.user_message)).toBeInTheDocument()
    expect(screen.getByText('Evidence at answer time')).toBeInTheDocument()
    expect(screen.getByText('Answer generation model')).toBeInTheDocument()
    expect(screen.getByText('Answer integrity receipt')).toBeInTheDocument()
    expect(screen.getByText('Prior answer context')).toBeInTheDocument()
    expect(screen.getByText(/2 reviewed\/history turns consulted · prior model outputs are not evidence/i)).toBeInTheDocument()
    expect(screen.getByText(/Content hashes verified/)).toBeInTheDocument()
    expect(screen.getByText((_, element) => (
      element?.tagName === 'DD'
      && element.textContent?.includes('Response identity bound') === true
      && element.textContent.includes('gemma-4-e2b-it-4bit')
      && element.textContent.includes('238767527555')
    ))).toBeInTheDocument()
    expect(screen.getByText('Local guidance missing')).toBeInTheDocument()
    expect(screen.getByText('Source IDs')).toBeInTheDocument()
    expect(screen.getByText('Saskatchewan · Retrieved: ca-regional-context-sk')).toBeInTheDocument()
    expect(historyRequestCount).toBe(3)
  })

  it('surfaces degraded geospatial and API availability states before review', async () => {
    installDegradedFetchMock()
    render(<OpenAgronomyApp />)

    openPrimaryPage('Fields')
    expect(await screen.findByText('Device')).toBeInTheDocument()
    expect(screen.queryByText('Data availability')).not.toBeInTheDocument()

    const fileInput = await screen.findByLabelText('Boundary upload')
    fireEvent.change(fileInput, {
      target: { files: [new File([JSON.stringify({ type: 'FeatureCollection', features: [] })], 'two-fields.geojson')] },
    })

    expect(await screen.findByText(/1 regional layer request failed/i)).toBeInTheDocument()
    expect(screen.getByText(/NRCS MLRA: NRCS MLRA FeatureServer timeout/i)).toBeInTheDocument()
    expect(screen.getByText(/Edit and save the field geometry to retry; answers should treat regional context as incomplete/i)).toBeInTheDocument()
    expect(screen.getAllByText(/Device-only fallback; backend field storage is unavailable/i).length).toBeGreaterThanOrEqual(1)
  })

  it('loads a private reference only into browser memory from the Data tab', async () => {
    const fetchMock = installFetchMock()
    render(<OpenAgronomyApp />)
    fireEvent.click(within(screen.getByRole('navigation', { name: 'Primary' })).getByRole('button', { name: 'Data' }))
    const input = await screen.findByLabelText('Choose private reference')
    fireEvent.change(input, {
      target: {
        files: [new File(['private note'], 'manitoba-note.txt', { type: 'text/plain' })],
      },
    })
    expect(await screen.findByText('manitoba-note.txt')).toBeInTheDocument()
    expect(screen.getByText(/1 excerpts · context only · not persisted/i)).toBeInTheDocument()
    expect(screen.getByText(`SHA-256 ${'a'.repeat(64)}`)).toBeInTheDocument()
    expect(
      fetchMock.mock.calls.some(([url]) => String(url) === '/api/private-knowledge/inspect'),
    ).toBe(true)
    fireEvent.click(screen.getByRole('button', { name: /Clear session references/i }))
    expect(screen.queryByText(`SHA-256 ${'a'.repeat(64)}`)).not.toBeInTheDocument()
  })

  it('presents field tools and prior turns as a focused map conversation', async () => {
    installConversationFetchMock()
    render(<OpenAgronomyApp />)

    await selectExample('central-alberta-barley', true)
    expect(await screen.findByRole('button', { name: 'Select point' })).toBeEnabled()
    expect(screen.getByRole('button', { name: 'Draw boundary' })).toBeEnabled()
    expect(screen.queryByRole('button', { name: 'Check map context' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByLabelText('Set field'))
    expect(screen.getByRole('button', { name: 'Pause editing' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: 'Edit boundary vertices' })).toBeEnabled()
    expect(screen.getByRole('button', { name: 'Start over' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Field details & history' })).toBeEnabled()
    expect(within(screen.getByRole('navigation', { name: 'Primary' })).getByRole('button', { name: 'Fields' })).toBeEnabled()

    const userText = await screen.findByText('Should I add nitrogen after this wet spring?')
    expect(userText.closest('article')).toHaveClass('user-message')
    const answerText = screen.getByText(/Check crop stage, application history, drainage/i)
    expect(answerText.closest('article')).toHaveClass('assistant-message')

    expect(within(answerText.closest('article') as HTMLElement).getByRole('button', { name: /Sources & checks/i })).toBeEnabled()
    expect(screen.queryByText(/^Context hash /)).not.toBeInTheDocument()
    expect(screen.queryByText('6 docs')).not.toBeInTheDocument()
    expect(screen.queryByText('Evidence checks')).not.toBeInTheDocument()
    expect(screen.getByLabelText('Model settings')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Ask about this field' })).toBeInTheDocument()
    expect(screen.getByLabelText('Ask about this field')).toHaveAttribute(
      'placeholder',
      'Ask a field question, compare observations, or request an evidence check…',
    )
    fireEvent.click(within(answerText.closest('article') as HTMLElement).getByRole('button', { name: /Sources & checks/i }))
    expect(screen.getByRole('dialog', { name: 'Sources & checks' })).toBeInTheDocument()
    expect(screen.getByText('Crop stress')).toHaveAttribute('title', 'fertility_diagnostic')
    expect(screen.getByText('Moderate')).toHaveAttribute('title', 'medium')
    expect(screen.getAllByText('6 used').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('1 linked').length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText('0 matched')).toBeInTheDocument()
    const checksDisclosure = screen.getAllByText('Evidence checks')
      .map((node) => node.closest('details'))
      .find((node): node is HTMLDetailsElement => node instanceof HTMLDetailsElement)
    const liveSourcesDisclosure = screen.getByText('Live public sources').closest('details')
    const retrievedEvidenceDisclosure = screen.getByText('Retrieved evidence').closest('details')
    expect(checksDisclosure).toBeDefined()
    expect(checksDisclosure).not.toHaveAttribute('open')
    expect(liveSourcesDisclosure).not.toHaveAttribute('open')
    expect(retrievedEvidenceDisclosure).not.toHaveAttribute('open')
    fireEvent.click(checksDisclosure!.querySelector('summary')!)
    expect(checksDisclosure).toHaveAttribute('open')
    expect(screen.getByText('Showing 4 of 6 documents.')).toBeInTheDocument()
    expect(screen.queryByText('fertility_diagnostic')).not.toBeInTheDocument()
  })

  it('resets the current field chat to a fresh local conversation without deleting the saved history', async () => {
    installConversationFetchMock()
    render(<OpenAgronomyApp />)

    await selectExample('central-alberta-barley', true)
    expect(await screen.findByText('Should I add nitrogen after this wet spring?')).toBeInTheDocument()
    const input = screen.getByLabelText('Ask about this field') as HTMLTextAreaElement
    fireEvent.change(input, { target: { value: 'Keep this only in the old draft.' } })
    fireEvent.click(screen.getByTestId('reset-chat'))

    await waitFor(() => {
      expect(screen.queryByText('Should I add nitrogen after this wet spring?')).not.toBeInTheDocument()
      expect(screen.getByText('What are you seeing in the field?')).toBeInTheDocument()
      expect(input).toHaveValue('')
    })
    expect(screen.getByTestId('reset-chat')).toBeEnabled()
  })

  it('keeps disconnected field work on-device and never presents the browser shell as an offline answer engine', async () => {
    installFetchMock()
    const firstRender = render(<OpenAgronomyApp />)

    expect(await screen.findByText('Local runtime · connected mode')).toBeInTheDocument()
    const question = screen.getByLabelText('Ask about this field')
    fireEvent.change(question, { target: { value: 'What should I inspect in the wet patch tomorrow?' } })
    fireEvent(window, new Event('offline'))

    expect(await screen.findByText('Runtime unavailable · notes only')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Ask' })).toBeDisabled()
    expect(screen.getByText(/This device cannot generate an answer/i)).toBeInTheDocument()

    openPrimaryPage('Fields')
    openFieldTab('Records & soil tests')
    const notes = screen.getByLabelText('Offline field notes')
    fireEvent.change(notes, { target: { value: 'Wet patch expanded after 18 mm rain; photograph roots.' } })
    expect(screen.getByTestId('local-field-notes-status')).toHaveTextContent('Local only')

    firstRender.unmount()
    window.location.hash = '#analyze'
    installFetchMock()
    render(<OpenAgronomyApp />)

    expect(await screen.findByLabelText('Ask about this field')).toHaveValue('What should I inspect in the wet patch tomorrow?')
    openPrimaryPage('Fields')
    openFieldTab('Records & soil tests')
    expect(screen.getByLabelText('Offline field notes')).toHaveValue('Wet patch expanded after 18 mm rain; photograph roots.')
  })

  it('surfaces unreadable local field data and preserves it for explicit recovery', async () => {
    const privateRaw = '{unreadable west-field notes after storm'
    window.localStorage.setItem(PHASE6_SCRATCHPAD_STORAGE_KEY, privateRaw)
    installFetchMock()
    render(<OpenAgronomyApp />)

    expect(await screen.findByText('Local runtime · connected mode')).toBeInTheDocument()
    openPrimaryPage('Fields')
    openFieldTab('Records & soil tests')
    const notice = await screen.findByTestId('offline-storage-recovery-notice')
    expect(notice).toHaveTextContent('Unreadable local data was preserved')
    expect(notice).toHaveTextContent('Download recovery file')
    expect(notice).not.toHaveTextContent('west-field notes after storm')
    expect(window.localStorage.getItem(PHASE6_SCRATCHPAD_STORAGE_KEY)).toBeNull()
    expect(window.localStorage.getItem(PHASE6_OFFLINE_STORAGE_QUARANTINE_KEY)).toContain(privateRaw)
  })

  it('keeps conversation history isolated to the selected field', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url === '/api/sessions?include_archived=true&include_turns=false') {
        return jsonResponse([
          {
            session_id: 'session-bc',
            context: { field_conversation_key: 'sample:central-alberta-barley' },
            turns: [{
              turn_id: 'turn-bc',
              user_message: 'BC field history only',
              answer: 'BC field answer',
              trace: { retrieved_docs: [], graph_hits: [], tool_invocations: [] },
            }],
          },
          {
            session_id: 'session-sk',
            context: { field_conversation_key: 'sample:regina-thematic-soil' },
            turns: [{
              turn_id: 'turn-sk',
              user_message: 'Saskatchewan field history only',
              answer: 'Saskatchewan field answer',
              trace: { retrieved_docs: [], graph_hits: [], tool_invocations: [] },
            }],
          },
        ])
      }
      if (url === '/api/configs') return jsonResponse(bootConfig)
      if (url === '/api/tools/public-adapter-readiness') return jsonResponse(adapterReadiness)
      if (url === '/api/demo/fields') return jsonResponse(emptyDemoFields)
      if (url === '/api/geo/priors') {
        const body = JSON.parse(String(init?.body || '{}'))
        const firstLongitude = body.geometry?.coordinates?.[0]?.[0]?.[0]
        return jsonResponse(firstLongitude < -110 ? bcPriors : skPriors)
      }
      if (url === '/api/tools/aafc-nasdi-agroclimate') return jsonResponse(nasdiConditions)
      return jsonResponse({})
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<OpenAgronomyApp />)

    await selectExample('central-alberta-barley', true)
    expect(await screen.findByText('BC field history only')).toBeInTheDocument()
    expect(screen.queryByText('Saskatchewan field history only')).not.toBeInTheDocument()

    openPrimaryPage('Fields')
    fireEvent.change(screen.getByRole('combobox', { name: /example/i }), {
      target: { value: 'regina-thematic-soil' },
    })
    openPrimaryPage('Map')
    expect(await screen.findByText('Saskatchewan field history only')).toBeInTheDocument()
    expect(screen.queryByText('BC field history only')).not.toBeInTheDocument()
  })

  it('positions a newly loaded answer at its opening instead of its tail', async () => {
    let releaseSessions!: (response: Response) => void
    const sessionsResponse = new Promise<Response>((resolve) => {
      releaseSessions = resolve
    })
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url === '/api/sessions?include_archived=true&include_turns=false') return sessionsResponse
      if (url === '/api/configs') return jsonResponse(bootConfig)
      if (url === '/api/tools/public-adapter-readiness') return jsonResponse(adapterReadiness)
      if (url === '/api/demo/fields') return jsonResponse(emptyDemoFields)
      if (url === '/api/geo/priors') return jsonResponse(bcPriors)
      if (url === '/api/tools/aafc-nasdi-agroclimate') return jsonResponse(nasdiConditions)
      return jsonResponse({})
    })
    vi.stubGlobal('fetch', fetchMock)
    const frames: Array<FrameRequestCallback | null> = []
    vi.spyOn(window, 'requestAnimationFrame').mockImplementation((callback) => {
      frames.push(callback)
      return frames.length
    })
    vi.spyOn(window, 'cancelAnimationFrame').mockImplementation((id) => { frames[id - 1] = null })

    const { container } = render(<OpenAgronomyApp />)
    releaseSessions(jsonResponse([
      {
        session_id: 'session-long-answer',
        context: { field_conversation_key: 'sample:central-alberta-barley' },
        turns: [
          {
            turn_id: 'turn-long-answer',
            user_message: 'What should I do first?',
            answer: 'Start with the field observation, then use the evidence to narrow the decision.',
            trace: { retrieved_docs: [], graph_hits: [], tool_invocations: [] },
          },
        ],
      },
    ]))

    await selectExample('central-alberta-barley', true)

    const answer = await screen.findByText(/Start with the field observation/i)
    const conversation = container.querySelector('.conversation-thread') as HTMLDivElement
    let scrollTop = 320
    Object.defineProperty(conversation, 'scrollTop', {
      configurable: true,
      get: () => scrollTop,
      set: (value: number) => { scrollTop = value },
    })
    conversation.getBoundingClientRect = () => ({ top: 100 } as DOMRect)
    const assistantMessage = answer.closest('article') as HTMLElement
    assistantMessage.getBoundingClientRect = () => ({ top: 248 } as DOMRect)
    await waitFor(() => expect(frames.length).toBeGreaterThan(0))
    // Drain the queued layout pass after the chat remounts with the selected field history.
    frames.splice(0).forEach((callback) => callback?.(0))

    expect(scrollTop).toBe(460)
  })

  it('reveals the complete older conversation on request', async () => {
    const turns = Array.from({ length: 26 }, (_, index) => ({
      turn_id: `turn-${index + 1}`,
      user_message: `Question ${index + 1}`,
      answer: `Answer ${index + 1}`,
      trace: { retrieved_docs: [], graph_hits: [], tool_invocations: [] },
    }))
    installFetchMock(emptyDemoFields, uploadPayload, [{
      session_id: 'session-long',
      context: { field_conversation_key: 'general' },
      turns,
    }])
    render(<OpenAgronomyApp />)

    expect(await screen.findByText('Answer 26')).toBeInTheDocument()
    expect(screen.queryByText('Answer 1')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Show earlier messages' }))
    expect(screen.getByText('Question 1')).toBeInTheDocument()
    expect(screen.getByText('Answer 1')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Show earlier messages' })).not.toBeInTheDocument()
  })

  it('keeps unsent question drafts with their own saved field', async () => {
    const baseField = {
      crop: 'canola', region: 'Leduc County', jurisdiction: 'Alberta', acres: '', concern: '', notes: '',
      geometry: { kind: 'point', point: { lat: 53.3, lon: -113.6 } },
      regionalContext: '', geoPriors: null, sourceBoundary: 'Regional context is not field truth.',
      createdAt: '2026-07-20T12:00:00Z', storageMode: 'account_workspace',
    }
    installFetchMock({ ...emptyDemoFields, fields: [
      { ...baseField, id: 'field-north', field_context_id: 'field-north', name: 'North field' },
      { ...baseField, id: 'field-south', field_context_id: 'field-south', name: 'South field' },
    ] })
    render(<OpenAgronomyApp />)

    openPrimaryPage('Fields')
    fireEvent.click(await screen.findByRole('button', { name: /^North field/ }))
    openPrimaryPage('Map')
    const question = screen.getByLabelText('Ask about this field')
    fireEvent.change(question, { target: { value: 'North-only scouting note' } })
    openPrimaryPage('Fields')
    fireEvent.click(screen.getByRole('button', { name: /^South field/ }))
    openPrimaryPage('Map')
    await waitFor(() => expect(screen.getByLabelText('Ask about this field')).toHaveValue(''))
    fireEvent.change(screen.getByLabelText('Ask about this field'), { target: { value: 'South-only soil note' } })
    openPrimaryPage('Fields')
    fireEvent.click(screen.getByRole('button', { name: /^North field/ }))
    openPrimaryPage('Map')
    await waitFor(() => expect(screen.getByLabelText('Ask about this field')).toHaveValue('North-only scouting note'))
    expect(screen.getByLabelText('Ask about this field')).not.toHaveValue('South-only soil note')
  })

  it('preserves an interrupted question without sending the same turn twice', async () => {
    const baseFetch = installFetchMock()
    const baseImplementation = baseFetch.getMockImplementation()!
    baseFetch.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url === '/api/sessions' && init?.method === 'POST') {
        return jsonResponse({ session_id: 'session-interrupted', context: { field_conversation_key: 'general' }, turns: [] })
      }
      if (url === '/api/sessions/session-interrupted/turns/stream' && init?.method === 'POST') {
        return { ok: true, status: 200, body: null, text: async () => 'event: generation.token\ndata: {"token":"Partial"}\n\n' } as Response
      }
      return baseImplementation(input, init)
    })
    render(<OpenAgronomyApp />)
    await screen.findByText('Local runtime · connected mode')
    const question = screen.getByLabelText('Ask about this field')
    fireEvent.change(question, { target: { value: 'What changed in the wet patch?' } })
    fireEvent.click(screen.getByRole('button', { name: 'Ask' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('The connection ended before the answer receipt arrived')
    expect(question).toHaveValue('What changed in the wet patch?')
    expect(baseFetch.mock.calls.filter(([url, init]) =>
      String(url) === '/api/sessions/session-interrupted/turns/stream' && init?.method === 'POST',
    )).toHaveLength(1)
    expect(screen.queryByText('Partial')).not.toBeInTheDocument()
  })

  it('ignores a delayed conversation refresh after switching fields or starting a new chat', async () => {
    const baseField = {
      crop: 'canola', region: 'Leduc County', jurisdiction: 'Alberta', acres: '', concern: '', notes: '',
      geometry: { kind: 'point', point: { lat: 53.3, lon: -113.6 } }, regionalContext: '',
      geoPriors: null, sourceBoundary: 'Regional context is not field truth.',
      createdAt: '2026-07-20T12:00:00Z', storageMode: 'account_workspace',
    }
    const session = (id: string, fieldId: string, answer: string) => ({
      session_id: id, turns_included: true,
      context: { field_context_id: fieldId, field_conversation_key: `field:${fieldId}` },
      turns: [{ turn_id: `${id}-turn`, user_message: `${fieldId} question`, answer,
        trace: { retrieved_docs: [], graph_hits: [], tool_invocations: [] } }],
    })
    const alpha = session('session-alpha', 'field-alpha', 'Alpha field answer')
    const beta = session('session-beta', 'field-beta', 'Beta field answer')
    const baseFetch = installFetchMock({ ...emptyDemoFields, fields: [
      { ...baseField, id: 'field-alpha', field_context_id: 'field-alpha', name: 'Alpha field' },
      { ...baseField, id: 'field-beta', field_context_id: 'field-beta', name: 'Beta field' },
    ] }, uploadPayload, [alpha, beta])
    const baseImplementation = baseFetch.getMockImplementation()!
    let releaseAlpha!: (value: Response) => void
    let releaseBeta!: (value: Response) => void
    const pendingAlpha = new Promise<Response>(resolve => { releaseAlpha = resolve })
    const pendingBeta = new Promise<Response>(resolve => { releaseBeta = resolve })
    baseFetch.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input) === '/api/sessions/session-alpha') return pendingAlpha
      if (String(input) === '/api/sessions/session-beta') return pendingBeta
      return baseImplementation(input, init)
    })
    render(<OpenAgronomyApp />)
    openPrimaryPage('Fields')
    fireEvent.click(await screen.findByRole('button', { name: /^Alpha field/ }))
    openPrimaryPage('Map')
    expect(await screen.findByText('Alpha field answer')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Refresh conversation' }))
    await waitFor(() => expect(baseFetch.mock.calls.some(([url]) => String(url) === '/api/sessions/session-alpha')).toBe(true))

    openPrimaryPage('Fields')
    fireEvent.click(screen.getByRole('button', { name: /^Beta field/ }))
    openPrimaryPage('Map')
    expect(await screen.findByText('Beta field answer')).toBeInTheDocument()
    await act(async () => {
      releaseAlpha(jsonResponse({ ...alpha, turns: [{ ...alpha.turns[0], answer: 'Late Alpha overwrite' }] }))
      await pendingAlpha
    })
    expect(screen.queryByText('Late Alpha overwrite')).not.toBeInTheDocument()
    expect(screen.getByText('Beta field answer')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Refresh conversation' }))
    await waitFor(() => expect(baseFetch.mock.calls.some(([url]) => String(url) === '/api/sessions/session-beta')).toBe(true))
    fireEvent.click(screen.getByTestId('reset-chat'))
    await act(async () => {
      releaseBeta(jsonResponse({ ...beta, turns: [{ ...beta.turns[0], answer: 'Late Beta overwrite' }] }))
      await pendingBeta
    })
    expect(screen.queryByText('Late Beta overwrite')).not.toBeInTheDocument()
    expect(screen.queryByText('Beta field answer')).not.toBeInTheDocument()
    expect(screen.getByText('What are you seeing in the field?')).toBeInTheDocument()
  })

  it('skips turn hydration without a selected session and hydrates a selected summary before asking', async () => {
    const staleSummary = {
      session_id: 'session-sample-only', turns_included: false,
      context: { field_conversation_key: 'sample:central-alberta-barley' }, turns: [],
    }
    const noSelectionFetch = installFetchMock(emptyDemoFields, uploadPayload, [staleSummary])
    const firstRender = render(<OpenAgronomyApp />)
    await screen.findByText('Local runtime · connected mode')
    expect(screen.getByText('Good questions start here.')).toBeInTheDocument()
    expect(noSelectionFetch.mock.calls.some(([url]) => String(url) === '/api/sessions/session-sample-only')).toBe(false)
    firstRender.unmount()

    const selectedSummary = { session_id: 'session-general-summary', turns_included: false,
      context: { field_conversation_key: 'general' }, turns: [] }
    const selectedFetch = installFetchMock(emptyDemoFields, uploadPayload, [selectedSummary])
    const selectedImplementation = selectedFetch.getMockImplementation()!
    let releaseSelected!: (value: Response) => void
    const pendingSelected = new Promise<Response>(resolve => { releaseSelected = resolve })
    selectedFetch.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) =>
      String(input) === '/api/sessions/session-general-summary'
        ? pendingSelected
        : selectedImplementation(input, init))
    render(<OpenAgronomyApp />)
    await waitFor(() => expect(selectedFetch.mock.calls.some(([url]) => String(url) === '/api/sessions/session-general-summary')).toBe(true))
    fireEvent.change(screen.getByLabelText('Ask about this field'), { target: { value: 'Is the summary ready?' } })
    expect(screen.getByRole('button', { name: 'Ask' })).toBeDisabled()
    releaseSelected(jsonResponse({ ...selectedSummary, turns: [{ turn_id: 'turn-hydrated',
      user_message: 'Prior general question', answer: 'Hydrated prior answer',
      trace: { retrieved_docs: [], graph_hits: [], tool_invocations: [] } }] }))
    expect(await screen.findByText('Hydrated prior answer')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Ask' })).toBeEnabled()
  })

  it('restores the selected general new chat and its unsent draft after reload', async () => {
    const oldSession = { session_id: 'session-old-general', turns_included: true,
      context: { field_conversation_key: 'general' },
      turns: [{ turn_id: 'old-turn', user_message: 'Old general question', answer: 'Old general answer',
        trace: { retrieved_docs: [], graph_hits: [], tool_invocations: [] } }] }
    const fetchMock = installFetchMock(emptyDemoFields, uploadPayload, [oldSession])
    const baseImplementation = fetchMock.getMockImplementation()!
    fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input) === '/api/sessions' && init?.method === 'POST') {
        const body = JSON.parse(String(init.body || '{}'))
        return jsonResponse({ session_id: 'session-new-general', context: body.context, turns: [] })
      }
      if (String(input) === '/api/sessions/session-new-general/turns/stream' && init?.method === 'POST') {
        return { ok: true, status: 200, body: null,
          text: async () => `event: answer.completed\ndata: ${JSON.stringify({ turn_id: 'new-turn', turn: {
            turn_id: 'new-turn', user_message: 'Draft for new general chat', answer: 'New general answer',
            trace: { retrieved_docs: [], graph_hits: [], tool_invocations: [] },
          } })}\n\n`,
        } as Response
      }
      return baseImplementation(input, init)
    })
    const firstRender = render(<OpenAgronomyApp />)
    expect(await screen.findByText('Old general answer')).toBeInTheDocument()
    fireEvent.click(screen.getByTestId('reset-chat'))
    fireEvent.change(screen.getByLabelText('Ask about this field'), { target: { value: 'Draft for new general chat' } })
    firstRender.unmount()

    render(<OpenAgronomyApp />)
    expect(await screen.findByLabelText('Ask about this field')).toHaveValue('Draft for new general chat')
    expect(screen.queryByText('Old general answer')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Ask' }))
    expect(await screen.findByText('New general answer')).toBeInTheDocument()
    const create = fetchMock.mock.calls.find(([url, init]) => String(url) === '/api/sessions' && init?.method === 'POST')
    const createdKey = JSON.parse(String(create?.[1]?.body || '{}')).context.field_conversation_key
    expect(createdKey).toMatch(/^general:chat:/)
  })

  it('edits a device field without dropping fields beyond the former list cap', async () => {
    const fields = Array.from({ length: 14 }, (_, index) => ({
      id: `device-${index}`, field_context_id: `device-${index}`, name: `Device field ${index}`,
      crop: 'wheat', region: 'Saskatchewan', jurisdiction: 'Saskatchewan', acres: '', concern: '', notes: '',
      geometry: { kind: 'point', point: { lat: 50.4, lon: -104.6 } }, regionalContext: '', geoPriors: null,
      sourceBoundary: 'Regional context is not field truth.', createdAt: '2026-07-20T12:00:00Z', storageMode: 'device',
    }))
    window.localStorage.setItem('open-agronomy-agent.fields.v1', JSON.stringify(fields))
    installDegradedFetchMock()
    const { container } = render(<OpenAgronomyApp />)
    openPrimaryPage('Fields')
    await waitFor(() => expect(container.querySelectorAll('.field-library-list article')).toHaveLength(14))
    fireEvent.click(screen.getByRole('button', { name: /^Device field 0/ }))
    fireEvent.change(screen.getByLabelText('Crop'), { target: { value: 'barley' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save field' }))
    await waitFor(() => {
      const saved = JSON.parse(window.localStorage.getItem('open-agronomy-agent.fields.v1') || '[]')
      expect(saved).toHaveLength(14)
      expect(saved.find((item: { id: string }) => item.id === 'device-0').crop).toBe('barley')
      expect(saved.some((item: { id: string }) => item.id === 'device-13')).toBe(true)
    })
  })

  it('restores an unsent draft when the selected saved field reloads', async () => {
    const field = {
      id: 'field-restored-draft', field_context_id: 'field-restored-draft', name: 'Draft field',
      crop: 'canola', region: 'Leduc County', jurisdiction: 'Alberta', acres: '', concern: '', notes: '',
      geometry: { kind: 'point', point: { lat: 53.3, lon: -113.6 } }, regionalContext: '', geoPriors: null,
      sourceBoundary: 'Regional context is not field truth.', createdAt: '2026-07-20T12:00:00Z',
      storageMode: 'account_workspace',
    }
    installFetchMock({ ...emptyDemoFields, fields: [field] })
    const firstRender = render(<OpenAgronomyApp />)
    openPrimaryPage('Fields')
    fireEvent.click(await screen.findByRole('button', { name: /^Draft field/ }))
    openPrimaryPage('Map')
    fireEvent.change(screen.getByLabelText('Ask about this field'), {
      target: { value: 'Inspect the north edge before making a rate decision.' },
    })
    firstRender.unmount()

    render(<OpenAgronomyApp />)
    await waitFor(() => expect(screen.getByRole('combobox', { name: 'Active field' })).toHaveValue('field-restored-draft'))
    await waitFor(() => expect(screen.getByLabelText('Ask about this field')).toHaveValue(
      'Inspect the north edge before making a rate decision.',
    ))
    expect(screen.getByRole('heading', { name: 'Draft field' })).toBeInTheDocument()
  })

  it('ignores the first StrictMode bootstrap when its session response arrives after the second', async () => {
    const current = { session_id: 'session-current', turns_included: true,
      context: { field_conversation_key: 'general' },
      turns: [{ turn_id: 'turn-current', user_message: 'Current question', answer: 'Current answer',
        trace: { retrieved_docs: [], graph_hits: [], tool_invocations: [] } }] }
    const stale = { session_id: 'session-stale', turns_included: true,
      context: { field_conversation_key: 'general' },
      turns: [{ turn_id: 'turn-stale', user_message: 'Stale question', answer: 'Stale answer',
        trace: { retrieved_docs: [], graph_hits: [], tool_invocations: [] } }] }
    const baseFetch = installFetchMock()
    const baseImplementation = baseFetch.getMockImplementation()!
    let releaseFirst!: (value: Response) => void
    const firstSessions = new Promise<Response>(resolve => { releaseFirst = resolve })
    let listingCount = 0
    baseFetch.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input) === '/api/sessions?include_archived=true&include_turns=false') {
        listingCount += 1
        return listingCount === 1 ? firstSessions : jsonResponse([current])
      }
      return baseImplementation(input, init)
    })
    render(<StrictMode><OpenAgronomyApp /></StrictMode>)
    expect(await screen.findByText('Current answer')).toBeInTheDocument()
    await act(async () => {
      releaseFirst(jsonResponse([stale]))
      await firstSessions
    })
    expect(screen.getByText('Current answer')).toBeInTheDocument()
    expect(screen.queryByText('Stale answer')).not.toBeInTheDocument()
    expect(listingCount).toBe(2)
  })

  it('binds delayed bootstrap sessions to the field selected while the list was loading', async () => {
    const field = {
      id: 'field-during-bootstrap', field_context_id: 'field-during-bootstrap', name: 'Bootstrap field',
      crop: 'barley', region: 'Leduc County', jurisdiction: 'Alberta', acres: '', concern: '', notes: '',
      geometry: { kind: 'point', point: { lat: 53.3, lon: -113.6 } }, regionalContext: '', geoPriors: null,
      sourceBoundary: 'Regional context is not field truth.', createdAt: '2026-07-20T12:00:00Z',
      storageMode: 'account_workspace',
    }
    const baseFetch = installFetchMock({ ...emptyDemoFields, fields: [field] })
    const baseImplementation = baseFetch.getMockImplementation()!
    let releaseSessions!: (value: Response) => void
    const pendingSessions = new Promise<Response>(resolve => { releaseSessions = resolve })
    baseFetch.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) =>
      String(input) === '/api/sessions?include_archived=true&include_turns=false'
        ? pendingSessions
        : baseImplementation(input, init))
    render(<OpenAgronomyApp />)
    openPrimaryPage('Fields')
    fireEvent.click(await screen.findByRole('button', { name: /^Bootstrap field/ }))
    openPrimaryPage('Map')
    await act(async () => {
      releaseSessions(jsonResponse([
        { session_id: 'session-general', turns_included: true,
          context: { field_conversation_key: 'general' },
          turns: [{ turn_id: 'turn-general', user_message: 'General question', answer: 'General answer',
            trace: { retrieved_docs: [], graph_hits: [], tool_invocations: [] } }] },
        { session_id: 'session-field', turns_included: true,
          context: { field_context_id: field.id, field_conversation_key: `field:${field.id}` },
          turns: [{ turn_id: 'turn-field', user_message: 'Field question', answer: 'Selected field answer',
            trace: { retrieved_docs: [], graph_hits: [], tool_invocations: [] } }] },
      ]))
      await pendingSessions
    })
    expect(await screen.findByText('Selected field answer')).toBeInTheDocument()
    expect(screen.queryByText('General answer')).not.toBeInTheDocument()
  })

  it('blocks Enter and direct form submission until the saved field identity is restored', async () => {
    const field = {
      id: 'field-chat-bootstrap', field_context_id: 'field-chat-bootstrap', name: 'Restored chat field',
      crop: 'barley', region: 'Leduc County', jurisdiction: 'Alberta', acres: '', concern: '', notes: '',
      geometry: { kind: 'point', point: { lat: 53.3, lon: -113.6 } }, regionalContext: '', geoPriors: null,
      sourceBoundary: 'Regional context is not field truth.', createdAt: '2026-07-20T12:00:00Z',
      storageMode: 'account_workspace',
    }
    window.localStorage.setItem('open-agronomy-agent.active-field.v1', field.id)
    const fetchMock = installFetchMock()
    const baseImplementation = fetchMock.getMockImplementation()!
    let releaseFields!: (value: Response) => void
    const pendingFields = new Promise<Response>(resolve => { releaseFields = resolve })
    fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) =>
      String(input) === '/api/demo/fields' && (!init?.method || init.method === 'GET')
        ? pendingFields : baseImplementation(input, init))
    render(<OpenAgronomyApp />)
    await screen.findByText('Local runtime · connected mode')
    const composer = screen.getByLabelText('Ask about this field') as HTMLTextAreaElement
    fireEvent.change(composer, { target: { value: 'Question while the saved field is loading' } })
    expect(screen.getByRole('button', { name: 'Ask' })).toBeDisabled()
    fireEvent.keyDown(composer, { key: 'Enter', code: 'Enter' })
    fireEvent.submit(composer.form!)
    await act(async () => { await Promise.resolve() })
    const sessionCreates = () => fetchMock.mock.calls.filter(([url, init]) => String(url) === '/api/sessions' && init?.method === 'POST')
    expect(sessionCreates()).toHaveLength(0)

    await act(async () => { releaseFields(jsonResponse({ ...emptyDemoFields, fields: [field] })); await pendingFields })
    await screen.findByRole('heading', { name: field.name })
    fireEvent.change(composer, { target: { value: 'Question for the restored field' } })
    await waitFor(() => expect(screen.getByRole('button', { name: 'Ask' })).toBeEnabled())
    fireEvent.keyDown(composer, { key: 'Enter', code: 'Enter' })
    await waitFor(() => expect(sessionCreates()).toHaveLength(1))
    const body = JSON.parse(String(sessionCreates()[0][1]?.body))
    expect(body.context).toMatchObject({ field_context_id: field.id, field_conversation_key: `field:${field.id}` })
  })

  it('keeps field creation closed until the initial field library response settles', async () => {
    const fetchMock = installFetchMock()
    const baseImplementation = fetchMock.getMockImplementation()!
    let releaseFields!: (value: Response) => void
    const pendingFields = new Promise<Response>(resolve => { releaseFields = resolve })
    fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) =>
      String(input) === '/api/demo/fields' && (!init?.method || init.method === 'GET')
        ? pendingFields
        : baseImplementation(input, init))
    render(<OpenAgronomyApp />)

    const addField = screen.getByRole('button', { name: 'Add field' })
    expect(addField).toBeDisabled()
    fireEvent.click(addField)
    expect(screen.queryByRole('dialog', { name: 'Add a field' })).not.toBeInTheDocument()
    openPrimaryPage('Fields')
    const newField = screen.getByRole('button', { name: 'New field' })
    expect(newField).toBeDisabled()
    fireEvent.click(newField)
    expect(screen.queryByRole('dialog', { name: 'Add a field' })).not.toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([url, init]) => String(url) === '/api/demo/fields' && init?.method === 'POST')).toBe(false)

    await act(async () => {
      releaseFields(jsonResponse(emptyDemoFields))
      await pendingFields
    })
    expect(addField).toBeEnabled()
    expect(newField).toBeEnabled()
  })

  it('keeps a newly created field when the first StrictMode field bootstrap resolves late', async () => {
    const fetchMock = installFetchMock()
    const baseImplementation = fetchMock.getMockImplementation()!
    let releaseFirst!: (value: Response) => void
    const firstFields = new Promise<Response>(resolve => { releaseFirst = resolve })
    let fieldGetCount = 0
    fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input) === '/api/demo/fields' && (!init?.method || init.method === 'GET')) {
        fieldGetCount += 1
        return fieldGetCount === 1 ? firstFields : jsonResponse(emptyDemoFields)
      }
      return baseImplementation(input, init)
    })
    render(<StrictMode><OpenAgronomyApp /></StrictMode>)
    const addField = await screen.findByRole('button', { name: 'Add field' })
    await waitFor(() => expect(addField).toBeEnabled())
    fireEvent.click(addField)
    const setup = await screen.findByRole('dialog', { name: 'Add a field' })
    fireEvent.change(within(setup).getByLabelText('Field name'), { target: { value: 'StrictMode field' } })
    fireEvent.click(within(setup).getByRole('button', { name: 'Continue' }))
    fireEvent.click(await within(setup).findByRole('button', { name: 'Mock drop point' }))
    fireEvent.click(within(setup).getByRole('button', { name: 'Continue' }))
    fireEvent.click(within(setup).getByRole('button', { name: 'Save field' }))
    await waitFor(() => expect(screen.getByRole('heading', { name: 'StrictMode field' })).toBeInTheDocument())
    expect(fetchMock.mock.calls.filter(([url, init]) => String(url) === '/api/demo/fields' && init?.method === 'POST')).toHaveLength(1)

    await act(async () => {
      releaseFirst(jsonResponse(emptyDemoFields))
      await firstFields
    })
    openPrimaryPage('Fields')
    expect(screen.getByRole('button', { name: /^StrictMode field/ })).toBeInTheDocument()
    expect(screen.getByLabelText('Field name')).toHaveValue('StrictMode field')
    expect(fieldGetCount).toBe(2)
  })
})
