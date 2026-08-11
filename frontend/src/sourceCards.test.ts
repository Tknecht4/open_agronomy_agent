import { describe, expect, it } from 'vitest'
import {
  buildSourceCheckSummary,
  buildPublicToolCard,
  buildStructuredEvidenceCard,
  buildTraceToolGroups,
  mapContextEvidenceCards,
  summarizePublicToolCards,
  summarizeStructuredEvidenceCards,
} from './sourceCards'
import type { ToolInvocation, Turn } from './types'

describe('source card normalization', () => {
  it('summarizes NRCS geometry as soil-survey evidence with a clear limitation', () => {
    const card = buildPublicToolCard({
      name: 'nrcs_soil_survey_geometry',
      payload: {
        kind: 'public_adapter',
        status: 'available',
        source: 'USDA NRCS Soil Data Access',
        summary: {
          map_unit_count: 12,
          component_summary: {
            dominant_components: [
              { component: 'Clarion', drainagecl: 'Well drained', hydgrp: 'B' },
              { component: 'Nicollet', drainagecl: 'Somewhat poorly drained', hydgrp: 'B/D' },
            ],
            hydric_ratings: { Yes: 3 },
          },
        },
      },
    })

    expect(card.title).toBe('Boundary soil survey (12 map units)')
    expect(card.provider).toBe('USDA NRCS')
    expect(card.statusTone).toBe('ok')
    expect(card.facts).toContain('Clarion: Well drained, HSG B / Nicollet: Somewhat poorly drained, HSG B/D')
    expect(card.limitation).toContain('map-unit prior')
    expect(card.sourceLabel).toBe('USDA NRCS Soil Data Access')
  })

  it('summarizes CDL geometry as sampled crop-cover context instead of acreage proof', () => {
    const card = buildPublicToolCard({
      name: 'cropland_data_layer_geometry',
      payload: {
        kind: 'public_adapter',
        status: 'available',
        summary: {
          sample_point_count: 4,
          years: [2024, 2023],
          year_summary: {
            '2024': { sample_count: 4, dominant_class: { cdl_label: 'Corn', count: 3 } },
            '2023': { sample_count: 4, dominant_class: { cdl_label: 'Soybeans', count: 4 } },
          },
        },
      },
    })

    expect(card.title).toBe('CDL boundary crop-cover sample (2024, 2023)')
    expect(card.facts).toEqual(['4 sample points', '2024: Corn 3/4 / 2023: Soybeans 4/4'])
    expect(card.limitation).toContain('not a planting record')
  })

  it('marks missing Quick Stats credentials as attention instead of available evidence', () => {
    const card = buildPublicToolCard({
      name: 'nass_quickstats_crop_stats',
      payload: {
        kind: 'public_adapter',
        status: 'not_configured',
        summary: {
          required_env_vars: ['AGRONOMY_AGENT_NASS_QUICKSTATS_API_KEY', 'NASS_API_KEY'],
        },
      },
    })

    expect(card.statusLabel).toBe('needs key')
    expect(card.statusTone).toBe('attention')
    expect(card.facts).toEqual(['Needs AGRONOMY_AGENT_NASS_QUICKSTATS_API_KEY or NASS_API_KEY'])
    expect(card.limitation).toContain('missing')
  })

  it('shows Canadian planned source lanes as attention, not broken adapters', () => {
    const planned = buildPublicToolCard({
      name: 'cansis_soil_landscapes_canada',
      payload: {
        kind: 'public_adapter',
        status: 'canada_source_lane_planned',
        source: 'https://sis.agr.gc.ca/cansis/nsdb/index.html',
        boundary: 'CanSIS source lane is identified; live intersected facts are not returned yet.',
        summary: {
          source_lane_id: 'cansis_soil_landscapes_canada',
          source_name: 'CanSIS National Soil Database / Soil Landscapes of Canada',
          coverage: 'Canadian soil and landscape geospatial context.',
          context: { crop: 'canola', province: 'SK' },
        },
      },
    })
    const needed = buildPublicToolCard({
      name: 'canada_et_or_water_use_source_needed',
      payload: {
        kind: 'public_adapter',
        status: 'canada_source_lane_needed',
        boundary: 'No Canada-appropriate ET source lane has been selected.',
        summary: {
          source_name: 'Canada-appropriate ET or agricultural water-use source needed',
          coverage: 'Canadian ET source selection.',
          context: { crop: 'canola', province: 'SK' },
        },
      },
    })

    expect(planned.title).toBe('Canadian soil source lane')
    expect(planned.provider).toBe('Agriculture and Agri-Food Canada')
    expect(planned.statusLabel).toBe('Canada source planned')
    expect(planned.statusTone).toBe('attention')
    expect(planned.facts).toContain('CanSIS National Soil Database / Soil Landscapes of Canada')
    expect(planned.limitation).toContain('live intersected facts')
    expect(needed.title).toBe('Canadian ET source needed')
    expect(needed.statusLabel).toBe('Canada source needed')
    expect(needed.statusTone).toBe('attention')
  })

  it('summarizes Daymet and OpenET values for water-window review', () => {
    const daymet = buildPublicToolCard({
      name: 'daymet_single_pixel_daily',
      payload: {
        kind: 'public_adapter',
        status: 'available',
        summary: {
          start: '2024-05-01',
          end: '2024-06-14',
          record_count: 45,
          variable_summary: {
            prcp: { sum: 42 },
            tmax: { mean: 23.5 },
            tmin: { mean: 11.25 },
          },
        },
      },
    })
    const openet = buildPublicToolCard({
      name: 'openet_point_timeseries',
      payload: {
        kind: 'public_adapter',
        status: 'available',
        summary: {
          start: '2024-04-01',
          end: '2024-09-30',
          interval: 'monthly',
          model: 'Ensemble',
          variable: 'ET',
          units: 'mm',
          record_count: 6,
          timeseries_summary: { sum: 612.4, mean: 102.07 },
        },
      },
    })

    expect(daymet.title).toBe('Climate-window context')
    expect(daymet.facts).toEqual(['2024-05-01 to 2024-06-14', '45 daily records', '42 mm precip', '23.5 C mean Tmax', '11.25 C mean Tmin'])
    expect(openet.title).toBe('Evapotranspiration context')
    expect(openet.facts).toEqual(['2024-04-01 to 2024-09-30', 'Ensemble ET', '612 mm total', '102 mm mean/monthly'])
  })

  it('summarizes EPA PPLS metadata without implying label interpretation', () => {
    const card = buildPublicToolCard({
      name: 'epa_ppls_product_search',
      payload: {
        kind: 'public_adapter',
        status: 'available',
        summary: {
          search_kind: 'ingredient_name',
          search_value: 'glyphosate',
          result_count: 2,
          current_product_count: 1,
          inactive_product_count: 1,
          needs_product_disambiguation: true,
          disambiguation_note:
            'PPLS returned candidate product records. Ask for the exact product name or EPA registration number before use.',
          top_candidate: {
            product_name: 'Example Glyphosate',
            epa_reg_no: '123-45',
            status: 'Active',
            status_bucket: 'current',
            label_pdf_urls: ['https://example.test/label-123-45.pdf'],
          },
          products: [
            {
              product_name: 'Example Glyphosate',
              epa_reg_no: '123-45',
              status: 'Active',
              status_bucket: 'current',
              label_pdf_urls: ['https://example.test/label-123-45.pdf'],
            },
            { product_name: 'Old Glyphosate', epa_reg_no: '999-00', status: 'Cancelled', status_bucket: 'inactive' },
          ],
        },
      },
    })

    expect(card.title).toBe('Product metadata')
    expect(card.provider).toBe('EPA')
    expect(card.facts).toEqual([
      'Ingredient Name: glyphosate',
      '2 product records',
      '1 current / 1 inactive',
      'Top candidate: Example Glyphosate · EPA Reg. 123-45 · Active',
      'Needs exact product or EPA reg no',
    ])
    expect(card.limitation).toContain('exact product name or EPA registration number')
    expect(card.links).toEqual([{ label: 'Label PDF', url: 'https://example.test/label-123-45.pdf' }])
  })

  it('summarizes deterministic public source cards as available decision frameworks', () => {
    const card = buildPublicToolCard({
      name: 'partial_budget_calculator',
      payload: {
        kind: 'public_adapter',
        status: 'source_lane_available',
        source: 'https://www.extension.iastate.edu/agdm/wholefarm/html/c1-50.html',
        boundary:
          'This source card frames partial-budget arithmetic. It is not proof of profitability without farm-specific records.',
        summary: {
          source_lane_id: 'partial_budget_calculator',
          source_name: 'Partial-budget decision frame',
          provider: 'Extension farm management decision tools',
          coverage:
            'Added returns, reduced costs, added costs, reduced returns, and break-even framing for incremental changes.',
          context: { crop: 'corn', region: 'Iowa' },
          decision_checks: [
            'baseline practice and proposed change described as an incremental comparison',
            'break-even yield, price, adoption, or cost threshold shown before claiming the practice pays',
          ],
        },
      },
    })

    expect(card.title).toBe('Partial-budget source card')
    expect(card.provider).toBe('Extension farm management decision tools')
    expect(card.statusLabel).toBe('source card')
    expect(card.statusTone).toBe('ok')
    expect(card.facts).toContain('Partial-budget decision frame')
    expect(card.facts).toContain('Crop: corn')
    expect(card.facts.join(' ')).toContain('break-even yield')
    expect(card.limitation).toContain('not proof of profitability')
    expect(card.sourceUrl).toBe('https://www.extension.iastate.edu/agdm/wholefarm/html/c1-50.html')
  })

  it('shows related official links for jurisdiction source cards', () => {
    const card = buildPublicToolCard({
      name: 'saskatchewan_official_crop_guidance',
      text: 'Official Saskatchewan live reference.',
      payload: {
        kind: 'public_adapter',
        status: 'source_lane_available',
        source: 'https://www.saskatchewan.ca/soils',
        boundary: 'Live-reference card only; guidance is not copied into the distributable corpus.',
        summary: {
          source_name: 'Saskatchewan official crop guidance live reference',
          provider: 'Government of Saskatchewan',
          source_urls: [
            'https://www.saskatchewan.ca/soils',
            'https://www.saskatchewan.ca/crop-guides',
          ],
          coverage: 'Current official source hubs.',
        },
      },
    })

    expect(card.sourceUrl).toBe('https://www.saskatchewan.ca/soils')
    expect(card.links).toEqual([{ label: 'Related official source', url: 'https://www.saskatchewan.ca/crop-guides' }])
    expect(card.limitation).toContain('not copied into the distributable corpus')
  })

  it('summarizes card availability for the chat header', () => {
    const tools: ToolInvocation[] = [
      { name: 'nrcs_soil_survey_geometry', payload: { kind: 'public_adapter', status: 'available', summary: {} } },
      { name: 'nasa_power_daily', payload: { kind: 'public_adapter', status: 'available', summary: {} } },
      { name: 'nass_quickstats_crop_stats', payload: { kind: 'public_adapter', status: 'not_configured', summary: {} } },
    ]

    expect(summarizePublicToolCards(tools)).toBe('2 available / 1 attention')
  })

  it('builds a compact source-check summary for the map-first chat panel', () => {
    const tools: ToolInvocation[] = [
      { name: 'nrcs_soil_survey_geometry', payload: { kind: 'public_adapter', status: 'available', summary: {} } },
      { name: 'nasa_power_daily', payload: { kind: 'public_adapter', status: 'available', summary: {} } },
      { name: 'openet_point_timeseries', payload: { kind: 'public_adapter', status: 'not_configured', summary: {} } },
    ]
    const summary = buildSourceCheckSummary(tools, [
      { doc_id: 'map:nrcs_mlra:MLRA_103', source_type: 'map_context', title: 'MLRA 103' },
    ])

    expect(summary.tone).toBe('attention')
    expect(summary.label).toBe('2 available / 1 attention')
    expect(summary.mapEvidenceCount).toBe(1)
    expect(summary.publicCheckCount).toBe(3)
    expect(summary.availableCount).toBe(2)
    expect(summary.attentionCount).toBe(1)
    expect(summary.unavailableCount).toBe(0)
    expect(summary.items).toEqual([
      { label: 'Map', value: '1 match', tone: 'ok' },
      { label: 'Public', value: '3 checks', tone: 'attention' },
      { label: 'Attention', value: '1', tone: 'attention' },
    ])
  })

  it('keeps the source-check summary honest before field context exists', () => {
    const summary = buildSourceCheckSummary([], [])

    expect(summary.tone).toBe('attention')
    expect(summary.label).toBe('need field context')
    expect(summary.items).toEqual([
      { label: 'Map', value: 'pending', tone: 'attention' },
      { label: 'Public', value: 'pending', tone: 'attention' },
      { label: 'Attention', value: 'clear', tone: 'ok' },
    ])
  })

  it('normalizes structured map-context cards as visible evidence', () => {
    const card = buildStructuredEvidenceCard({
      doc_id: 'map:nrcs_mlra:MLRA_103',
      title: 'NRCS MLRA MLRA_103: Central Iowa and Minnesota Till Prairies',
      publisher: 'NRCS MLRA',
      source: 'official_arcgis_feature_service',
      source_type: 'map_context',
      adapter_status: 'available',
      why_used: 'Official regional polygon intersection used as map context. Coverage estimate: 100%.',
      known_limitations: [
        'Official map context is a regional prior, not a replacement for soil tests, scouting, labels, grower records, or legal boundary evidence.',
      ],
      summary: {
        code: 'MLRA_103',
        name: 'Central Iowa and Minnesota Till Prairies',
        confidence: 0.94,
        coverage_estimate: 1,
      },
    })

    expect(card.statusLabel).toBe('map match')
    expect(card.statusTone).toBe('ok')
    expect(card.provider).toBe('NRCS MLRA')
    expect(card.facts).toContain('MLRA_103 · Central Iowa and Minnesota Till Prairies')
    expect(card.facts).toContain('100% field coverage')
    expect(card.facts).toContain('94% match confidence')
    expect(card.limitation).toContain('regional prior')
    expect(card.sourceLabel).toBe('official_arcgis_feature_service')
  })

  it('extracts only map-context structured evidence from a turn trace', () => {
    const turn = {
      turn_id: 'turn_1',
      user_message: 'What does this field context mean?',
      answer: 'Field read...',
      answer_status: 'ok',
      trace: {
        structured_answer: {
          evidence_cards: [
            { doc_id: 'map:nrcs_mlra:MLRA_103', source_type: 'map_context', title: 'MLRA 103' },
            { doc_id: 'tool:nrcs_soil_survey_geometry', source_type: 'public_adapter', title: 'NRCS SDA' },
          ],
        },
      },
    } satisfies Turn

    expect(mapContextEvidenceCards(turn)).toHaveLength(1)
    expect(mapContextEvidenceCards(turn)[0].doc_id).toBe('map:nrcs_mlra:MLRA_103')
    expect(summarizeStructuredEvidenceCards(mapContextEvidenceCards(turn))).toBe('1 map match')
  })

  it('groups map evidence, public source checks, guard checks, and other trace tools separately', () => {
    const turn = {
      turn_id: 'turn_2',
      user_message: 'Can I spray this product before rain?',
      answer: 'Use label and forecast boundaries.',
      answer_status: 'ok',
      trace: {
        tool_invocations: [
          {
            name: 'nasa_power_daily',
            payload: {
              kind: 'public_adapter',
              status: 'available',
              summary: { record_count: 7, variable_summary: { prcp: { sum: 22 } } },
            },
          },
          {
            name: 'label_guard',
            payload: { boundary: 'Exact product label and EPA registration number are required before rate or interval advice.' },
          },
          {
            name: 'retrieval_debug_probe',
            text: 'Auxiliary retrieval trace',
          },
        ],
        metadata: {
          tool_notes: ['weather_guard'],
        },
        structured_answer: {
          evidence_cards: [
            {
              doc_id: 'map:nrcs_mlra:MLRA_103',
              source_type: 'map_context',
              title: 'NRCS MLRA 103',
              adapter_status: 'available',
              known_limitations: ['Regional prior, not field truth.'],
            },
          ],
        },
      },
    } satisfies Turn

    const groups = buildTraceToolGroups(turn, mapContextEvidenceCards(turn))
    const byId = Object.fromEntries(groups.map((group) => [group.id, group]))

    expect(byId.map_context.count).toBe(1)
    expect(byId.live_public_sources.label).toBe('Public source checks')
    expect(byId.live_public_sources.count).toBe(1)
    expect(byId.guard_checks.items.map((item) => item.name)).toEqual(expect.arrayContaining(['label_guard', 'weather_guard']))
    expect(byId.other_tools.count).toBe(1)
    expect(byId.other_tools.items[0].label).toBe('Retrieval Debug Probe')
  })
})
