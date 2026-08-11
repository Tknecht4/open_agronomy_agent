import { describe, expect, it } from 'vitest'
import { buildFieldContextReadiness } from './fieldContextReadiness'
import type { HostedFieldContext } from './types'

const baseContext: HostedFieldContext = {
  id: 'field_context_1',
  workspace_id: 'workspace_1',
  display_name: 'North field generalized',
  region_text: 'Iowa Des Moines Lobe',
  crop_current: 'corn',
  management_notes: 'Tile drained, spring manure history.',
  sensitivity: 'medium',
  quality_meter: {
    schema_version: 'phase6_field_context_quality_v1',
    summary: 'diagnostic_triage_ready',
    ready: {
      conceptual_answer: true,
      diagnostic_triage: true,
      product_rate_decision: false,
    },
    checks: [
      {
        id: 'conceptual_answer',
        label: 'Enough for conceptual answer',
        status: 'ready',
        available_fields: ['crop_current', 'region_text'],
        missing_fields: [],
      },
      {
        id: 'diagnostic_triage',
        label: 'Enough for diagnostic triage',
        status: 'ready',
        available_fields: ['crop_current', 'region_text', 'management_notes'],
        missing_fields: [],
      },
      {
        id: 'product_rate_decision',
        label: 'Not enough for product/rate decision',
        status: 'blocked',
        available_fields: ['crop_current', 'region_text', 'management_notes'],
        missing_fields: ['current product label', 'local jurisdiction and recommendation authority'],
      },
    ],
    missing_minimum_next_prompts: [
      'For product or rate decisions, attach the current label and local recommendation basis.',
    ],
    product_rate_boundary: 'Field profiles do not authorize product, label, or rate decisions.',
  },
  deleted_at: null,
}

describe('buildFieldContextReadiness', () => {
  it('asks for the smallest useful field context when no profile is selected', () => {
    const readiness = buildFieldContextReadiness(null)

    expect(readiness.status).toBe('none')
    expect(readiness.headline).toContain('Add crop or region')
    expect(readiness.missingData).toEqual(['crop_current or region_text'])
    expect(readiness.blockedUses).toContain('Diagnostic triage')
  })

  it('marks diagnostic triage as ready while keeping product and rate decisions blocked', () => {
    const readiness = buildFieldContextReadiness(baseContext)

    expect(readiness.status).toBe('diagnostic')
    expect(readiness.readyUses).toEqual(['Conceptual answer', 'Diagnostic triage'])
    expect(readiness.blockedUses).toEqual(['Product/rate decision'])
    expect(readiness.decisionBoundary).toContain('current label evidence')
  })

  it('surfaces missing diagnostic fields from the quality meter', () => {
    const readiness = buildFieldContextReadiness({
      ...baseContext,
      quality_meter: {
        ...baseContext.quality_meter!,
        summary: 'conceptual_answer_ready',
        ready: {
          conceptual_answer: true,
          diagnostic_triage: false,
          product_rate_decision: false,
        },
        checks: baseContext.quality_meter!.checks.map((check) =>
          check.id === 'diagnostic_triage'
            ? {
                ...check,
                status: 'missing',
                missing_fields: ['soil, drainage, weather, history, or constraint notes'],
              }
            : check,
        ),
        missing_minimum_next_prompts: [
          'Add one field note: soil texture, drainage, recent weather, soil test, rotation, or observed pressure.',
        ],
      },
    })

    expect(readiness.status).toBe('conceptual')
    expect(readiness.readyUses).toEqual(['Conceptual answer'])
    expect(readiness.blockedUses).toEqual(['Diagnostic triage', 'Product/rate decision'])
    expect(readiness.missingData).toEqual(['soil, drainage, weather, history, or constraint notes'])
    expect(readiness.nextMeasurements[0]).toContain('Add one field note')
  })
})
