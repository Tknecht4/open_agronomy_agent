import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
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
    default: () => React.createElement('div', { 'data-testid': 'mock-field-sync-panel' }, 'record transfer'),
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
  rag_configs: ['configs/rag_final_mvp.yaml'],
  default_rag_config: 'configs/rag_final_mvp.yaml',
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
    if (url === '/api/sessions?include_archived=true') return jsonResponse(initialSessions)
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
    if (url === '/api/sessions?include_archived=true') return jsonResponse([])
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
    if (url === '/api/sessions?include_archived=true') {
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
}

describe('Open Agronomy map upload workflow', () => {
  it('keeps field tasks primary while preserving secondary pages behind one disclosure', async () => {
    installFetchMock()
    render(<OpenAgronomyApp />)

    const navigation = screen.getByRole('navigation', { name: 'Primary' })
    const primaryButtons = Array.from(navigation.querySelectorAll(':scope > button'))
    expect(primaryButtons.map((button) => button.textContent)).toEqual(['Workspace', 'Fields', 'Evidence'])
    expect(within(navigation).getByRole('button', { name: 'Workspace' })).toHaveAttribute('aria-current', 'page')

    const more = screen.getByText('More', { selector: 'summary' })
    fireEvent.click(more)
    expect(within(navigation).getByRole('button', { name: 'Sources' })).toBeVisible()
    expect(within(navigation).getByRole('button', { name: 'Benchmarks' })).toBeVisible()
    expect(within(navigation).getByRole('button', { name: 'Privacy' })).toBeVisible()
    expect(within(navigation).getByRole('button', { name: 'About' })).toBeVisible()

    fireEvent.click(within(navigation).getByRole('button', { name: 'Sources' }))
    expect(await screen.findByRole('heading', { name: /Sources/i })).toBeInTheDocument()
    expect(more.closest('details')).not.toHaveAttribute('open')
  })

  it('hydrates the default Alberta sample as live geometry and intersects it before the first question', async () => {
    const fetchMock = installFetchMock()
    render(<OpenAgronomyApp />)

    expect(await screen.findByText(/Regional context refreshed: AAFC Alberta Detailed Soil Survey AB_SOIL_ABD192014361 matched at 100% confidence/i)).toBeInTheDocument()
    expect(screen.getByTestId('mock-leaflet-map')).toHaveAttribute('data-geometry-kind', 'polygon')
    expect(screen.getByTestId('mock-leaflet-map')).toHaveAttribute('data-first-lon', '-113.608')
    openPrimaryPage('Fields')
    expect(screen.getAllByText(/Alberta detailed soil map unit MMNV9\/U1l/i).length).toBeGreaterThan(0)
    expect(await screen.findByTestId('agroclimate-spi')).toHaveTextContent('13 wk SPI0.43')

    const priorsCall = fetchMock.mock.calls.find(([url, init]) => {
      if (String(url) !== '/api/geo/priors' || init?.method !== 'POST') return false
      const body = JSON.parse(String(init.body || '{}'))
      return body.geometry?.coordinates?.[0]?.[0]?.[0] === -113.608
    })
    expect(priorsCall).toBeTruthy()
  })

  it('keeps regional evidence available but collapsed by default on the Fields page', async () => {
    installFetchMock()
    render(<OpenAgronomyApp />)

    openPrimaryPage('Fields')
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

    openPrimaryPage('Fields')
    const picker = screen.getByRole('combobox', { name: /example/i })
    fireEvent.change(picker, { target: { value: 'regina-thematic-soil' } })

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

    openPrimaryPage('Fields')
    expect(
      await screen.findByText('Current AAFC regional conditions are unavailable for this geometry.'),
    ).toBeInTheDocument()
    expect(screen.queryByText('Loading the latest official grid observations...')).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: /official source/i })).toHaveAttribute('href', nasdiConditions.source)
  })

  it('loads the Manitoba sample with national soil-erosion context', async () => {
    const fetchMock = installFetchMock()
    render(<OpenAgronomyApp />)

    openPrimaryPage('Fields')
    const picker = screen.getByRole('combobox', { name: /example/i })
    fireEvent.change(picker, { target: { value: 'canola-acidity' } })

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
      if (url === '/api/sessions?include_archived=true') return jsonResponse([])
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

    openPrimaryPage('Fields')
    fireEvent.change(await screen.findByLabelText('Boundary upload'), {
      target: {
        files: [new File([JSON.stringify({ type: 'Polygon', coordinates: [peiRing] })], 'pictou-field.geojson')],
      },
    })
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

    fireEvent.click(await screen.findByRole('button', { name: /mock draw boundary/i }))
    fireEvent.click(screen.getByRole('button', { name: /check map context/i }))

    expect(await screen.findByText(/Regional context refreshed: EPA Level III Ecoregion 47 matched at 92% confidence/i)).toBeInTheDocument()
    openPrimaryPage('Fields')
    expect(screen.getByText('Southern Iowa Drift Plain')).toBeInTheDocument()
    expect(screen.getByText(/EPA Level III Ecoregion 47/i)).toBeInTheDocument()
    expect(screen.getByText(/Use this as regional guidance for retrieval and source checks/i)).toBeInTheDocument()
    expect(screen.getByText(/not as soil-test, scouting, yield, legal-boundary, or product-rate evidence/i)).toBeInTheDocument()
    openPrimaryPage('Map')
    expect(screen.getByTestId('mock-leaflet-map')).toHaveAttribute('data-geometry-kind', 'polygon')
    expect(screen.getByText(/4 vertices · approx 50 ac · editable boundary/i)).toBeInTheDocument()

    const boundaryPriorsCall = fetchMock.mock.calls.find(([url, init]) => {
      if (String(url) !== '/api/geo/priors' || init?.method !== 'POST') return false
      const body = JSON.parse(String(init.body || '{}'))
      return body.geometry?.type === 'Polygon'
    })
    expect(boundaryPriorsCall).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: /mock drop point/i }))
    fireEvent.click(screen.getByRole('button', { name: /check map context/i }))

    expect(await screen.findByText(/Regional context refreshed: NRCS MLRA MLRA_103 matched at 94% confidence/i)).toBeInTheDocument()
    const mapContextBar = screen
      .getByRole('button', { name: 'Open field details' })
      .closest('.map-context-bar')
    expect(mapContextBar).not.toBeNull()
    expect(
      within(mapContextBar as HTMLElement).getAllByText(/NRCS MLRA MLRA_103/i),
    ).toHaveLength(2)
    expect(screen.queryByText('Central Iowa and Minnesota Till Prairies')).not.toBeInTheDocument()
    expect(screen.getByText(/point 42\.02000, -93\.72000 · prior-only match/i)).toBeInTheDocument()
    expect(screen.getByTestId('mock-leaflet-map')).toHaveAttribute('data-geometry-kind', 'point')
    openPrimaryPage('Fields')
    expect(screen.getByText('Central Iowa and Minnesota Till Prairies')).toBeInTheDocument()

    const pointPriorsCall = fetchMock.mock.calls.find(([url, init]) => {
      if (String(url) !== '/api/geo/priors' || init?.method !== 'POST') return false
      const body = JSON.parse(String(init.body || '{}'))
      return body.geometry?.type === 'Point'
    })
    expect(pointPriorsCall).toBeTruthy()
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

    openPrimaryPage('Fields')
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
    fireEvent.click(screen.getByText('Saved fields'))
    fireEvent.click(screen.getAllByRole('button', { name: /Quebec field/i })[0])
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
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(
        ([url]) => String(url) === '/api/demo/fields/field-restored/history',
      )).toBe(true),
    )
    expect(screen.getByText(/0 field records · 0 answers/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Refresh field timeline' })).toBeEnabled()
    expect(screen.queryByText('Save or load the field in this workspace first.')).not.toBeInTheDocument()
    expect(window.localStorage.getItem('open-agronomy-agent.active-field.v1')).toBe('field-restored')
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

    openPrimaryPage('Fields')
    await waitFor(() => expect(container.querySelector('.stored-fields-disclosure summary span')).toHaveTextContent('13'))
    expect(screen.queryByText('stale-device-1')).not.toBeInTheDocument()
    const fileInput = await screen.findByLabelText('Boundary upload')
    fireEvent.change(fileInput, {
      target: { files: [new File([JSON.stringify({ type: 'FeatureCollection', features: [] })], 'two-fields.geojson')] },
    })
    await screen.findByTestId('upload-feature-geojson:0')
    fireEvent.click(screen.getByRole('button', { name: /save field/i }))

    await waitFor(() => expect(container.querySelector('.stored-fields-disclosure summary span')).toHaveTextContent('14'))
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
    const records: Array<Record<string, unknown>> = []
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url === '/api/sessions?include_archived=true') return jsonResponse([])
      if (url === '/api/configs') return jsonResponse(bootConfig)
      if (url === '/api/tools/public-adapter-readiness') return jsonResponse(adapterReadiness)
      if (url === '/api/demo/fields') return jsonResponse({ ...emptyDemoFields, fields: [storedField] })
      if (url === '/api/demo/fields/field-context-1/events' && init?.method === 'POST') {
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
      if (url === '/api/geo/priors') return jsonResponse(skPriors)
      if (url === '/api/tools/aafc-nasdi-agroclimate') return jsonResponse(nasdiConditions)
      return jsonResponse({})
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<OpenAgronomyApp />)

    expect(screen.queryByTestId('mock-field-sync-panel')).not.toBeInTheDocument()
    openPrimaryPage('Fields')
    fireEvent.click(await screen.findByText('North quarter'))
    await screen.findByText('0 field records · 0 answers.')
    expect(await screen.findByTestId('mock-field-sync-panel')).toBeInTheDocument()
    expect(screen.getByText(/Saved answers stay linked to the exact field snapshot/i)).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('What happened'), {
      target: { value: 'Standing water observed in the northwest corner.' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Add record' }))

    expect(await screen.findByText('Standing water observed in the northwest corner.')).toBeInTheDocument()
    expect(screen.getByText('Immutable record · aaaaaaaaaaaa')).toBeInTheDocument()
    const request = fetchMock.mock.calls.find(
      ([url, init]) => String(url) === '/api/demo/fields/field-context-1/events' && init?.method === 'POST',
    )
    expect(JSON.parse(String(request?.[1]?.body))).toMatchObject({
      event_type: 'observation',
      payload: { summary: 'Standing water observed in the northwest corner.' },
      provenance: { capture_method: 'user_entered', surface: 'fields_timeline' },
    })
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
        rag_config: 'configs/rag_governed_runtime_v1.yaml',
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
      if (url === '/api/sessions?include_archived=true') {
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
    await screen.findByText('0 field records · 0 answers.')
    openPrimaryPage('Map')
    fireEvent.change(screen.getByLabelText('Ask about this field'), {
      target: { value: completedTurn.user_message },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Ask' }))

    await screen.findByText(completedTurn.answer)
    openPrimaryPage('Fields')
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
    expect(await screen.findByRole('region', { name: 'Answer lineage' })).toBeInTheDocument()
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
    expect(screen.getByText(/Retry Check map context; answers should treat regional context as incomplete/i)).toBeInTheDocument()
    expect(screen.getAllByText(/Device-only fallback; backend field storage is unavailable/i).length).toBeGreaterThanOrEqual(1)
  })

  it('loads a private reference only into browser memory from the Sources tab', async () => {
    const fetchMock = installFetchMock()
    render(<OpenAgronomyApp />)
    fireEvent.click(screen.getByText('More', { selector: 'summary' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Sources' }))
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

    expect(await screen.findByRole('button', { name: 'Select point' })).toBeEnabled()
    expect(screen.getByRole('button', { name: 'Draw boundary' })).toBeEnabled()
    expect(screen.getByRole('button', { name: 'Check map context' })).toBeEnabled()
    fireEvent.click(screen.getByLabelText('Set field'))
    expect(screen.getByRole('button', { name: 'Move and inspect map' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: 'Edit boundary vertices' })).toBeEnabled()
    expect(screen.getByRole('button', { name: 'Clear geometry' })).toBeEnabled()
    expect(screen.getByRole('button', { name: 'Field details & history' })).toBeEnabled()
    expect(within(screen.getByRole('navigation', { name: 'Primary' })).getByRole('button', { name: 'Fields' })).toBeEnabled()

    const userText = await screen.findByText('Should I add nitrogen after this wet spring?')
    expect(userText.closest('article')).toHaveClass('user-message')
    const answerText = screen.getByText(/Check crop stage, application history, drainage/i)
    expect(answerText.closest('article')).toHaveClass('assistant-message')

    expect(screen.getByText('Evidence and trace available')).toBeInTheDocument()
    expect(screen.queryByText(/^Context hash /)).not.toBeInTheDocument()
    expect(screen.queryByText('6 docs')).not.toBeInTheDocument()
    expect(screen.queryByText('Evidence checks')).not.toBeInTheDocument()
    expect(screen.getByLabelText('Model settings')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Ask about this field' })).toBeInTheDocument()
    expect(screen.getByLabelText('Ask about this field')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Review evidence' }))
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
    const notes = screen.getByLabelText('Offline field notes')
    fireEvent.change(notes, { target: { value: 'Wet patch expanded after 18 mm rain; photograph roots.' } })
    expect(screen.getByTestId('local-field-notes-status')).toHaveTextContent('Local only')

    firstRender.unmount()
    window.location.hash = '#analyze'
    installFetchMock()
    render(<OpenAgronomyApp />)

    expect(await screen.findByLabelText('Ask about this field')).toHaveValue('What should I inspect in the wet patch tomorrow?')
    openPrimaryPage('Fields')
    expect(screen.getByLabelText('Offline field notes')).toHaveValue('Wet patch expanded after 18 mm rain; photograph roots.')
  })

  it('surfaces unreadable local field data and preserves it for explicit recovery', async () => {
    const privateRaw = '{unreadable west-field notes after storm'
    window.localStorage.setItem(PHASE6_SCRATCHPAD_STORAGE_KEY, privateRaw)
    installFetchMock()
    render(<OpenAgronomyApp />)

    expect(await screen.findByText('Local runtime · connected mode')).toBeInTheDocument()
    openPrimaryPage('Fields')
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
      if (url === '/api/sessions?include_archived=true') {
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
      if (url === '/api/sessions?include_archived=true') return sessionsResponse
      if (url === '/api/configs') return jsonResponse(bootConfig)
      if (url === '/api/tools/public-adapter-readiness') return jsonResponse(adapterReadiness)
      if (url === '/api/demo/fields') return jsonResponse(emptyDemoFields)
      if (url === '/api/geo/priors') return jsonResponse(bcPriors)
      if (url === '/api/tools/aafc-nasdi-agroclimate') return jsonResponse(nasdiConditions)
      return jsonResponse({})
    })
    vi.stubGlobal('fetch', fetchMock)
    const frames: FrameRequestCallback[] = []
    vi.spyOn(window, 'requestAnimationFrame').mockImplementation((callback) => {
      frames.push(callback)
      return frames.length
    })
    vi.spyOn(window, 'cancelAnimationFrame').mockImplementation(() => undefined)

    const { container } = render(<OpenAgronomyApp />)
    const conversation = container.querySelector('.conversation-thread') as HTMLDivElement
    let scrollTop = 320
    Object.defineProperty(conversation, 'scrollTop', {
      configurable: true,
      get: () => scrollTop,
      set: (value: number) => {
        scrollTop = value
      },
    })
    conversation.getBoundingClientRect = () => ({ top: 100 } as DOMRect)

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

    const answer = await screen.findByText(/Start with the field observation/i)
    const assistantMessage = answer.closest('article') as HTMLElement
    assistantMessage.getBoundingClientRect = () => ({ top: 248 } as DOMRect)
    await waitFor(() => expect(frames.length).toBeGreaterThan(0))
    frames.splice(0).forEach((callback) => callback(0))

    expect(scrollTop).toBe(460)
  })
})
