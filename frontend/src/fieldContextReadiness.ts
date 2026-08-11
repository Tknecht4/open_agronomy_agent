import type { HostedFieldContext } from './types'

export type FieldContextReadiness = {
  status: 'none' | 'insufficient' | 'conceptual' | 'diagnostic'
  headline: string
  readyUses: string[]
  blockedUses: string[]
  missingData: string[]
  nextMeasurements: string[]
  decisionBoundary: string
}

const PRODUCT_RATE_BOUNDARY = 'Product/rate decision requires current label evidence and local recommendation authority.'

export const buildFieldContextReadiness = (fieldContext: HostedFieldContext | null): FieldContextReadiness => {
  if (!fieldContext?.quality_meter) {
    return {
      status: 'none',
      headline: 'Add crop or region before using field-context-aware answers.',
      readyUses: [],
      blockedUses: ['Conceptual answer', 'Diagnostic triage', 'Product/rate decision'],
      missingData: ['crop_current or region_text'],
      nextMeasurements: ['Add the crop or generalized region first.'],
      decisionBoundary: PRODUCT_RATE_BOUNDARY,
    }
  }

  const meter = fieldContext.quality_meter
  const conceptualReady = meter.ready.conceptual_answer
  const diagnosticReady = meter.ready.diagnostic_triage
  const status = diagnosticReady ? 'diagnostic' : conceptualReady ? 'conceptual' : 'insufficient'
  const missingData = uniqueValues(
    meter.checks
      .filter((check) => check.id !== 'product_rate_decision' && check.status !== 'ready')
      .flatMap((check) => check.missing_fields),
  )
  const readyUses = [
    conceptualReady ? 'Conceptual answer' : '',
    diagnosticReady ? 'Diagnostic triage' : '',
  ].filter(Boolean)
  const blockedUses = [
    conceptualReady ? '' : 'Conceptual answer',
    diagnosticReady ? '' : 'Diagnostic triage',
    'Product/rate decision',
  ].filter(Boolean)

  return {
    status,
    headline: headlineFor(status),
    readyUses,
    blockedUses,
    missingData,
    nextMeasurements: meter.missing_minimum_next_prompts.length
      ? meter.missing_minimum_next_prompts
      : ['Add the smallest missing crop, location, or field note before narrowing the answer.'],
    decisionBoundary: PRODUCT_RATE_BOUNDARY,
  }
}

const headlineFor = (status: FieldContextReadiness['status']): string => {
  if (status === 'diagnostic') {
    return 'Ready for conceptual answers and diagnostic triage.'
  }
  if (status === 'conceptual') {
    return 'Ready for conceptual answers; diagnostic triage needs one more field detail.'
  }
  if (status === 'insufficient') {
    return 'Not enough context yet for field-specific answers.'
  }
  return 'Add crop or region before using field-context-aware answers.'
}

const uniqueValues = (values: string[]): string[] => Array.from(new Set(values.filter((value) => value.trim())))
