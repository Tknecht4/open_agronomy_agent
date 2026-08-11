import { StructuredEvidenceCard, ToolInvocation, Turn } from './types'

export type PublicToolCard = {
  name: string
  title: string
  provider: string
  status: string
  statusLabel: string
  statusTone: 'ok' | 'attention' | 'unavailable'
  facts: string[]
  limitation: string
  sourceLabel?: string
  sourceUrl?: string
  links?: { label: string; url: string }[]
}

export type SourceCheckSummary = {
  tone: 'ok' | 'attention' | 'unavailable'
  label: string
  mapEvidenceCount: number
  publicCheckCount: number
  availableCount: number
  attentionCount: number
  unavailableCount: number
  items: Array<{ label: string; value: string; tone: 'ok' | 'attention' | 'unavailable' }>
}

export type TraceToolGroup = {
  id: 'map_context' | 'live_public_sources' | 'guard_checks' | 'other_tools'
  label: string
  count: number
  summary: string
  statusTone: 'ok' | 'attention' | 'unavailable'
  items: Array<{
    name: string
    label: string
    detail: string
    statusTone: 'ok' | 'attention' | 'unavailable'
  }>
}

type JsonRecord = Record<string, unknown>

const asRecord = (value: unknown): JsonRecord => (value && typeof value === 'object' && !Array.isArray(value) ? value as JsonRecord : {})

const asString = (value: unknown): string | undefined => (typeof value === 'string' && value.trim() ? value.trim() : undefined)

const asNumber = (value: unknown): number | undefined => (typeof value === 'number' && Number.isFinite(value) ? value : undefined)

const asArray = (value: unknown): unknown[] => (Array.isArray(value) ? value : [])

const asStringArray = (value: unknown): string[] => {
  if (Array.isArray(value)) return value.map(String).map((item) => item.trim()).filter(Boolean)
  const single = asString(value)
  return single ? [single] : []
}

const formatNumber = (value: number): string => {
  if (Math.abs(value) >= 100) return Math.round(value).toLocaleString()
  if (Number.isInteger(value)) return String(value)
  return value.toFixed(2).replace(/\.?0+$/, '')
}

export const formatToolName = (name: string): string =>
  name
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (letter) => letter.toUpperCase())

export const buildPublicToolCard = (tool: ToolInvocation): PublicToolCard => {
  const payload = asRecord(tool.payload)
  const summary = asRecord(payload.summary)
  const freshness = asRecord(payload.freshness)
  const freshnessStatus = asString(freshness.status)
  const status = freshnessStatus === 'stale' || freshnessStatus === 'future_invalid'
    ? 'stale'
    : asString(payload.status) || 'unknown'
  const source = asString(payload.source)
  const sourceUrl = source && /^https?:\/\//i.test(source) ? source : undefined
  const freshnessDeclaration = asString(freshness.declaration)
  const limitation = toolLimitation(tool.name, payload, status)
  return {
    name: tool.name,
    title: toolTitle(tool.name, summary),
    provider: toolProvider(tool.name, summary),
    status,
    statusLabel: statusLabel(status),
    statusTone: statusTone(status),
    facts: toolFacts(tool.name, summary, status),
    limitation: freshnessDeclaration ? `${freshnessDeclaration} ${limitation}` : limitation,
    sourceLabel: sourceUrl ? undefined : source,
    sourceUrl,
    links: toolLinks(tool.name, summary),
  }
}

export const summarizePublicToolCards = (tools: ToolInvocation[]): string => {
  if (tools.length === 0) return 'need point/boundary'
  const cards = tools.map(buildPublicToolCard)
  const available = cards.filter((card) => card.statusTone === 'ok').length
  const attention = cards.length - available
  return attention ? `${available} available / ${attention} attention` : `${available} available`
}

export const buildSourceCheckSummary = (
  tools: ToolInvocation[],
  mapCards: StructuredEvidenceCard[] = [],
): SourceCheckSummary => {
  const publicCards = tools.map(buildPublicToolCard)
  const availableCount = publicCards.filter((card) => card.statusTone === 'ok').length
  const attentionCount = publicCards.filter((card) => card.statusTone === 'attention').length
  const unavailableCount = publicCards.filter((card) => card.statusTone === 'unavailable').length
  const mapEvidenceCount = mapCards.length
  const publicCheckCount = publicCards.length
  const tone: SourceCheckSummary['tone'] = unavailableCount
    ? 'unavailable'
    : attentionCount || (!mapEvidenceCount && !publicCheckCount)
      ? 'attention'
      : 'ok'
  const label = publicCheckCount
    ? summarizePublicToolCards(tools)
    : mapEvidenceCount
      ? `${mapEvidenceCount} map match${mapEvidenceCount === 1 ? '' : 'es'}`
      : 'need field context'
  const items: SourceCheckSummary['items'] = [
    {
      label: 'Map',
      value: mapEvidenceCount ? `${mapEvidenceCount} match${mapEvidenceCount === 1 ? '' : 'es'}` : 'pending',
      tone: mapEvidenceCount ? 'ok' : 'attention',
    },
    {
      label: 'Public',
      value: publicCheckCount ? `${publicCheckCount} check${publicCheckCount === 1 ? '' : 's'}` : 'pending',
      tone: publicCheckCount ? (attentionCount || unavailableCount ? 'attention' : 'ok') : 'attention',
    },
    {
      label: 'Attention',
      value: attentionCount || unavailableCount ? `${attentionCount + unavailableCount}` : 'clear',
      tone: unavailableCount ? 'unavailable' : attentionCount ? 'attention' : 'ok',
    },
  ]
  return {
    tone,
    label,
    mapEvidenceCount,
    publicCheckCount,
    availableCount,
    attentionCount,
    unavailableCount,
    items,
  }
}

export const structuredEvidenceCards = (turn: Turn | null): StructuredEvidenceCard[] => {
  const structured = turn?.trace?.structured_answer
  const cards = structured?.evidence_cards?.length ? structured.evidence_cards : structured?.evidence || []
  return cards.filter((card): card is StructuredEvidenceCard => Boolean(card && typeof card === 'object'))
}

export const mapContextEvidenceCards = (turn: Turn | null): StructuredEvidenceCard[] =>
  structuredEvidenceCards(turn).filter((card) => card.source_type === 'map_context')

export const buildStructuredEvidenceCard = (card: StructuredEvidenceCard): PublicToolCard => {
  const sourceType = asString(card.source_type) || 'structured_evidence'
  const status = asString(card.adapter_status) || (sourceType === 'map_context' ? 'available' : asString(card.license_status) || 'available')
  const url = asString(card.url) || asString(card.source)
  const sourceUrl = url && /^https?:\/\//i.test(url) ? url : undefined
  return {
    name: asString(card.doc_id) || asString(card.source_id) || sourceType,
    title: asString(card.title) || formatToolName(sourceType),
    provider: asString(card.publisher) || asString(card.source) || formatToolName(sourceType),
    status,
    statusLabel: structuredEvidenceStatusLabel(status, sourceType),
    statusTone: structuredEvidenceStatusTone(status),
    facts: structuredEvidenceFacts(card),
    limitation: structuredEvidenceLimitation(card),
    sourceLabel: sourceUrl ? undefined : asString(card.source) || asString(card.source_id) || undefined,
    sourceUrl,
  }
}

export const summarizeStructuredEvidenceCards = (cards: StructuredEvidenceCard[]): string => {
  if (cards.length === 0) return 'none yet'
  const mapCards = cards.filter((card) => card.source_type === 'map_context').length
  if (mapCards === cards.length) return `${mapCards} map match${mapCards === 1 ? '' : 'es'}`
  return `${cards.length} evidence card${cards.length === 1 ? '' : 's'}`
}

export const buildTraceToolGroups = (
  turn: Turn | null,
  mapCards: StructuredEvidenceCard[] = mapContextEvidenceCards(turn),
): TraceToolGroup[] => {
  const toolInvocations = turn?.trace?.tool_invocations || []
  const publicTools = toolInvocations.filter((tool) => asRecord(tool.payload).kind === 'public_adapter')
  const publicNames = new Set(publicTools.map((tool) => tool.name))
  const guardToolNames = Array.from(
    new Set([
      ...toolInvocations
        .filter((tool) => !publicNames.has(tool.name) && isGuardToolName(tool.name))
        .map((tool) => tool.name),
      ...toolNoteNames(turn).filter(isGuardToolName),
    ]),
  )
  const guardNameSet = new Set(guardToolNames)
  const otherTools = toolInvocations.filter(
    (tool) => !publicNames.has(tool.name) && !guardNameSet.has(tool.name),
  )
  return [
    mapTraceGroup(mapCards),
    publicSourceTraceGroup(publicTools),
    guardTraceGroup(guardToolNames, toolInvocations),
    otherToolTraceGroup(otherTools),
  ]
}

const mapTraceGroup = (mapCards: StructuredEvidenceCard[]): TraceToolGroup => ({
  id: 'map_context',
  label: 'Map evidence',
  count: mapCards.length,
  summary: mapCards.length ? `${mapCards.length} visible map card${mapCards.length === 1 ? '' : 's'}` : 'pending field intersection',
  statusTone: mapCards.length ? 'ok' : 'attention',
  items: mapCards.slice(0, 4).map((card) => ({
    name: asString(card.doc_id) || asString(card.title) || 'map_context',
    label: asString(card.title) || 'Official regional polygon',
    detail: structuredEvidenceLimitation(card),
    statusTone: structuredEvidenceStatusTone(asString(card.adapter_status) || 'available'),
  })),
})

const publicSourceTraceGroup = (tools: ToolInvocation[]): TraceToolGroup => {
  const cards = tools.map(buildPublicToolCard)
  const unavailable = cards.filter((card) => card.statusTone === 'unavailable').length
  const attention = cards.filter((card) => card.statusTone === 'attention').length
  const statusTone: TraceToolGroup['statusTone'] = unavailable ? 'unavailable' : attention || !cards.length ? 'attention' : 'ok'
  return {
    id: 'live_public_sources',
    label: 'Public source checks',
    count: cards.length,
    summary: cards.length ? summarizePublicToolCards(tools) : 'no source checks yet',
    statusTone,
    items: cards.slice(0, 5).map((card) => ({
      name: card.name,
      label: card.title,
      detail: card.limitation,
      statusTone: card.statusTone,
    })),
  }
}

const guardTraceGroup = (guardNames: string[], tools: ToolInvocation[]): TraceToolGroup => ({
  id: 'guard_checks',
  label: 'Guard checks',
  count: guardNames.length,
  summary: guardNames.length ? `${guardNames.length} applied` : 'none triggered',
  statusTone: guardNames.length ? 'ok' : 'attention',
  items: guardNames.slice(0, 6).map((name) => {
    const tool = tools.find((candidate) => candidate.name === name)
    const payload = asRecord(tool?.payload)
    return {
      name,
      label: guardLabel(name),
      detail:
        asString(payload.boundary) ||
        asString(payload.text) ||
        asString(tool?.text) ||
        'Decision-support guardrail; asks for missing field evidence and prevents overclaiming.',
      statusTone: 'ok',
    }
  }),
})

const otherToolTraceGroup = (tools: ToolInvocation[]): TraceToolGroup => ({
  id: 'other_tools',
  label: 'Other tool work',
  count: tools.length,
  summary: tools.length ? `${tools.length} other trace item${tools.length === 1 ? '' : 's'}` : 'none',
  statusTone: tools.length ? 'attention' : 'ok',
  items: tools.slice(0, 5).map((tool) => ({
    name: tool.name,
    label: formatToolName(tool.name),
    detail: asString(tool.text) || asString(asRecord(tool.payload).status) || 'Auxiliary trace item.',
    statusTone: 'attention',
  })),
})

const toolNoteNames = (turn: Turn | null): string[] => {
  const metadata = asRecord(turn?.trace?.metadata)
  return asArray(metadata.tool_notes).map(String).map((item) => item.trim()).filter(Boolean)
}

const isGuardToolName = (name: string): boolean =>
  /(^|_)(guard|safety)($|_)/i.test(name) ||
  ['fertility_guard', 'label_guard', 'weather_guard', 'field_data_guard', 'photo_diagnosis_guard'].includes(name)

const guardLabel = (name: string): string => {
  if (name === 'fertility_guard') return 'Fertility decision guard'
  if (name === 'label_guard') return 'Product label boundary guard'
  if (name === 'weather_guard') return 'Weather and drift guard'
  if (name === 'field_data_guard') return 'Field-data quality guard'
  if (name === 'photo_diagnosis_guard') return 'Diagnosis boundary guard'
  return formatToolName(name)
}

const statusTone = (status: string): PublicToolCard['statusTone'] => {
  if (status === 'available' || status === 'source_lane_available') return 'ok'
  if (status === 'stale' || status === 'not_configured' || status === 'no_records' || status === 'canada_source_lane_planned' || status === 'canada_source_lane_needed') return 'attention'
  return 'unavailable'
}

const statusLabel = (status: string): string => {
  if (status === 'available') return 'available'
  if (status === 'source_lane_available') return 'source card'
  if (status === 'not_configured') return 'needs key'
  if (status === 'no_records') return 'no records'
  if (status === 'stale') return 'stale'
  if (status === 'canada_source_lane_planned') return 'Canada source planned'
  if (status === 'canada_source_lane_needed') return 'Canada source needed'
  return status.replace(/_/g, ' ')
}

const structuredEvidenceStatusTone = (status: string): PublicToolCard['statusTone'] => {
  if (status === 'available' || status === 'source_lane_available' || status === 'public_endpoint') return 'ok'
  if (status === 'review_required' || status === 'not_configured' || status === 'no_records') return 'attention'
  return 'unavailable'
}

const structuredEvidenceStatusLabel = (status: string, sourceType: string): string => {
  if (sourceType === 'map_context' && status === 'available') return 'map match'
  if (status === 'public_endpoint') return 'public'
  return statusLabel(status)
}

const structuredEvidenceFacts = (card: StructuredEvidenceCard): string[] => {
  const sourceType = asString(card.source_type) || ''
  const summary = asRecord(card.summary)
  const facts: string[] = []
  if (sourceType === 'map_context') {
    const code = asString(summary.code)
    const name = asString(summary.name)
    if (code || name) facts.push([code, name].filter(Boolean).join(' · '))
    const coverage = asNumber(summary.coverage_estimate)
    if (coverage !== undefined) facts.push(`${formatNumber(coverage * 100)}% field coverage`)
    const confidence = asNumber(summary.confidence)
    if (confidence !== undefined) facts.push(`${formatNumber(confidence * 100)}% match confidence`)
  } else {
    const score = asNumber(card.score)
    if (score !== undefined) facts.push(`score ${formatNumber(score)}`)
    if (sourceType) facts.push(formatToolName(sourceType))
  }
  const whyUsed = asStringArray(card.why_used)[0]
  if (whyUsed && facts.length < 4) facts.push(whyUsed.replace(/\.$/, ''))
  return facts
}

const structuredEvidenceLimitation = (card: StructuredEvidenceCard): string => {
  const limitations = asStringArray(card.known_limitations)
  if (limitations.length) return limitations[0]
  if (card.source_type === 'map_context') {
    return 'Official map context is a regional prior, not a replacement for soil tests, scouting, labels, grower records, or legal boundary evidence.'
  }
  return 'Use as decision-support context only; verify against field records before acting.'
}

const toolTitle = (name: string, summary: JsonRecord): string => {
  if (name === 'nrcs_soil_survey_geometry') {
    const count = asNumber(summary.map_unit_count)
    return count ? `Boundary soil survey (${formatNumber(count)} map units)` : 'Boundary soil survey'
  }
  if (name === 'nrcs_soil_survey_point') return 'Point soil survey'
  if (name === 'cropland_data_layer_geometry') {
    const years = asArray(summary.years).slice(0, 3).map(String)
    return years.length ? `CDL boundary crop-cover sample (${years.join(', ')})` : 'CDL boundary crop-cover sample'
  }
  if (name === 'cropland_data_layer_point') return 'CDL point crop-cover class'
  if (name === 'nasa_power_daily') return 'Daily gridded weather'
  if (name === 'daymet_single_pixel_daily') return 'Climate-window context'
  if (name === 'openet_point_timeseries') return 'Evapotranspiration context'
  if (name === 'nass_quickstats_crop_stats') return 'Regional crop statistics'
  if (name === 'epa_ppls_product_search') return 'Product metadata'
  if (name === 'cansis_soil_landscapes_canada') return 'Canadian soil source lane'
  if (name === 'aafc_annual_crop_inventory') return 'Canadian crop-cover source lane'
  if (name === 'statcan_field_crop_statistics') return 'Canadian crop-statistics source lane'
  if (name === 'health_canada_pmra_label_search') return 'Canadian label source lane'
  if (name === 'canada_et_or_water_use_source_needed') return 'Canadian ET source needed'
  if (name === 'disease_risk_context_adapter') return 'Disease risk source card'
  if (name === 'public_variety_trial_ingest') return 'Variety trial source card'
  if (name === 'specialty_crop_extension_corpus') return 'Specialty-crop extension source card'
  if (name === 'conservation_practice_context_adapter') return 'Conservation practice source card'
  if (name === 'canada_conservation_practice_context_source') return 'Canadian conservation source card'
  if (name === 'field_record_audit_card') return 'Field-record audit source card'
  if (name === 'partial_budget_calculator') return 'Partial-budget source card'
  if (name === 'public_program_context_source') return 'Public program source card'
  if (name === 'forage_livestock_extension_corpus') return 'Forage and livestock safety source card'
  if (name === 'postharvest_storage_quality_corpus') return 'Storage and grain-quality source card'
  const sourceName = asString(summary.source_name)
  if (sourceName) return sourceName
  return formatToolName(name)
}

const toolProvider = (name: string, summary: JsonRecord = {}): string => {
  const provider = asString(summary.provider)
  if (provider) return provider
  if (name.startsWith('nrcs_')) return 'USDA NRCS'
  if (name.startsWith('cropland_data_layer') || name.startsWith('nass_')) return 'USDA NASS'
  if (name.startsWith('nasa_')) return 'NASA POWER'
  if (name.startsWith('daymet_')) return 'ORNL Daymet'
  if (name.startsWith('openet_')) return 'OpenET'
  if (name.startsWith('epa_')) return 'EPA'
  if (name === 'cansis_soil_landscapes_canada' || name === 'aafc_annual_crop_inventory') return 'Agriculture and Agri-Food Canada'
  if (name === 'statcan_field_crop_statistics') return 'Statistics Canada'
  if (name === 'health_canada_pmra_label_search') return 'Health Canada PMRA'
  if (name === 'canada_et_or_water_use_source_needed') return 'Source-lane backlog'
  return 'Public source'
}

const toolFacts = (name: string, summary: JsonRecord, status: string): string[] => {
  if (isCanadaSourceLane(name)) return canadaSourceLaneFacts(summary)
  if (isPublicSourceCard(name)) return publicSourceCardFacts(summary)
  if (status !== 'available') return unavailableFacts(name, summary, status)
  if (name === 'nrcs_soil_survey_geometry') return nrcsGeometryFacts(summary)
  if (name === 'nrcs_soil_survey_point') return nrcsPointFacts(summary)
  if (name === 'cropland_data_layer_geometry') return cdlGeometryFacts(summary)
  if (name === 'cropland_data_layer_point') return cdlPointFacts(summary)
  if (name === 'nasa_power_daily') return nasaPowerFacts(summary)
  if (name === 'daymet_single_pixel_daily') return daymetFacts(summary)
  if (name === 'openet_point_timeseries') return openEtFacts(summary)
  if (name === 'nass_quickstats_crop_stats') return quickStatsFacts(summary)
  if (name === 'epa_ppls_product_search') return epaPplsFacts(summary)
  return []
}

const isCanadaSourceLane = (name: string): boolean =>
  [
    'cansis_soil_landscapes_canada',
    'aafc_annual_crop_inventory',
    'statcan_field_crop_statistics',
    'health_canada_pmra_label_search',
    'canada_et_or_water_use_source_needed',
  ].includes(name)

const isPublicSourceCard = (name: string): boolean =>
  [
    'disease_risk_context_adapter',
    'public_variety_trial_ingest',
    'specialty_crop_extension_corpus',
    'conservation_practice_context_adapter',
    'canada_conservation_practice_context_source',
    'field_record_audit_card',
    'partial_budget_calculator',
    'public_program_context_source',
    'forage_livestock_extension_corpus',
    'postharvest_storage_quality_corpus',
    'saskatchewan_official_crop_guidance',
  ].includes(name)

const publicSourceCardFacts = (summary: JsonRecord): string[] => {
  const facts: string[] = []
  const sourceName = asString(summary.source_name)
  if (sourceName) facts.push(sourceName)
  const coverage = asString(summary.coverage)
  if (coverage) facts.push(coverage)
  const checks = asStringArray(summary.decision_checks).slice(0, 2)
  if (checks.length) facts.push(`Checks: ${checks.join(' / ')}`)
  const context = asRecord(summary.context)
  const contextBits = Object.entries(context)
    .map(([key, value]) => {
      const text = asString(value)
      return text ? `${formatToolName(key)}: ${text}` : ''
    })
    .filter(Boolean)
    .slice(0, 2)
  facts.push(...contextBits)
  return facts.slice(0, 4)
}

const canadaSourceLaneFacts = (summary: JsonRecord): string[] => {
  const facts: string[] = []
  const sourceName = asString(summary.source_name)
  if (sourceName) facts.push(sourceName)
  const coverage = asString(summary.coverage)
  if (coverage) facts.push(coverage)
  const context = asRecord(summary.context)
  const crop = asString(context.crop)
  const province = asString(context.province)
  const productTerm = asString(context.product_term)
  if (crop || province) facts.push([crop, province].filter(Boolean).join(' / '))
  if (productTerm) facts.push(`Query term: ${productTerm}`)
  return facts.slice(0, 4)
}

const nrcsGeometryFacts = (summary: JsonRecord): string[] => {
  const facts: string[] = []
  const count = asNumber(summary.map_unit_count)
  if (count) facts.push(`${formatNumber(count)} map units`)
  const componentSummary = asRecord(summary.component_summary)
  const dominantComponents = asArray(componentSummary.dominant_components)
    .map(asRecord)
    .slice(0, 2)
    .map((component) => {
      const name = asString(component.component)
      if (!name) return ''
      const drainage = asString(component.drainagecl)
      const hydgrp = asString(component.hydgrp)
      const details = [drainage, hydgrp ? `HSG ${hydgrp}` : ''].filter(Boolean).join(', ')
      return details ? `${name}: ${details}` : name
    })
    .filter(Boolean)
  if (dominantComponents.length) facts.push(dominantComponents.join(' / '))
  const hydric = asRecord(componentSummary.hydric_ratings)
  const hydricYes = asNumber(hydric.Yes)
  if (hydricYes) facts.push(`${formatNumber(hydricYes)} hydric components`)
  return facts
}

const nrcsPointFacts = (summary: JsonRecord): string[] => {
  const mapUnits = asArray(summary.map_units).map(asRecord)
  const first = mapUnits[0]
  const name = asString(first?.muname)
  return name ? [name] : []
}

const cdlGeometryFacts = (summary: JsonRecord): string[] => {
  const facts: string[] = []
  const sampleCount = asNumber(summary.sample_point_count)
  if (sampleCount) facts.push(`${formatNumber(sampleCount)} sample points`)
  const years = asArray(summary.years).slice(0, 3)
  const yearSummary = asRecord(summary.year_summary)
  const labels = years
    .map((year) => {
      const yearKey = String(year)
      const record = asRecord(yearSummary[yearKey])
      const dominant = asRecord(record.dominant_class)
      const label = asString(dominant.cdl_label)
      const count = asNumber(dominant.count)
      const total = asNumber(record.sample_count)
      if (!label) return ''
      return count && total ? `${yearKey}: ${label} ${formatNumber(count)}/${formatNumber(total)}` : `${yearKey}: ${label}`
    })
    .filter(Boolean)
  if (labels.length) facts.push(labels.join(' / '))
  const errors = asArray(summary.sample_errors)
  if (errors.length) facts.push(`${errors.length} sample errors`)
  return facts
}

const cdlPointFacts = (summary: JsonRecord): string[] => {
  const label = asString(summary.cdl_label) || asString(summary.label)
  const year = asNumber(summary.year)
  if (label && year) return [`${formatNumber(year)}: ${label}`]
  return label ? [label] : []
}

const nasaPowerFacts = (summary: JsonRecord): string[] => {
  const parameters = asRecord(summary.parameter_summary)
  const precip = asNumber(asRecord(parameters.PRECTOTCORR).sum)
  const temp = asNumber(asRecord(parameters.T2M).mean)
  const wind = asNumber(asRecord(parameters.WS2M).mean)
  const facts = []
  if (precip !== undefined) facts.push(`${formatNumber(precip)} mm precip`)
  if (temp !== undefined) facts.push(`${formatNumber(temp)} C mean temp`)
  if (wind !== undefined) facts.push(`${formatNumber(wind)} m/s mean wind`)
  return facts
}

const daymetFacts = (summary: JsonRecord): string[] => {
  const facts: string[] = []
  const start = asString(summary.start)
  const end = asString(summary.end)
  if (start && end) facts.push(`${start} to ${end}`)
  const count = asNumber(summary.record_count)
  if (count) facts.push(`${formatNumber(count)} daily records`)
  const variables = asRecord(summary.variable_summary)
  const precip = asNumber(asRecord(variables.prcp).sum)
  const tmax = asNumber(asRecord(variables.tmax).mean)
  const tmin = asNumber(asRecord(variables.tmin).mean)
  if (precip !== undefined) facts.push(`${formatNumber(precip)} mm precip`)
  if (tmax !== undefined) facts.push(`${formatNumber(tmax)} C mean Tmax`)
  if (tmin !== undefined) facts.push(`${formatNumber(tmin)} C mean Tmin`)
  return facts
}

const openEtFacts = (summary: JsonRecord): string[] => {
  const facts: string[] = []
  const start = asString(summary.start)
  const end = asString(summary.end)
  if (start && end) facts.push(`${start} to ${end}`)
  const model = asString(summary.model)
  const variable = asString(summary.variable) || 'ET'
  if (model) facts.push(`${model} ${variable}`)
  const timeseries = asRecord(summary.timeseries_summary)
  const units = asString(summary.units) || 'units'
  const interval = asString(summary.interval) || 'period'
  const total = asNumber(timeseries.sum)
  const mean = asNumber(timeseries.mean)
  if (total !== undefined) facts.push(`${formatNumber(total)} ${units} total`)
  if (mean !== undefined) facts.push(`${formatNumber(mean)} ${units} mean/${interval}`)
  const count = asNumber(summary.record_count)
  if (count && facts.length < 4) facts.push(`${formatNumber(count)} records`)
  return facts
}

const quickStatsFacts = (summary: JsonRecord): string[] => {
  const crop = asString(summary.crop)
  const state = asString(summary.state_alpha)
  const count = asNumber(summary.record_count)
  const facts = []
  if (crop || state) facts.push([crop, state].filter(Boolean).join(' / '))
  if (count) facts.push(`${formatNumber(count)} records`)
  const latest = asRecord(summary.latest_by_statistic)
  Object.entries(latest).slice(0, 2).forEach(([label, value]) => {
    const row = asRecord(value)
    const year = asNumber(row.year)
    const statValue = asString(row.value)
    const unit = asString(row.unit_desc)
    if (year && statValue && unit) facts.push(`${formatNumber(year)} ${label.toLowerCase()}: ${statValue} ${unit}`)
  })
  return facts
}

const epaPplsFacts = (summary: JsonRecord): string[] => {
  const facts: string[] = []
  const searchValue = asString(summary.search_value)
  const searchKind = asString(summary.search_kind)
  if (searchValue) facts.push(searchKind ? `${formatToolName(searchKind)}: ${searchValue}` : searchValue)
  const count = asNumber(summary.result_count)
  if (count !== undefined) facts.push(`${formatNumber(count)} product records`)
  const currentCount = asNumber(summary.current_product_count)
  const inactiveCount = asNumber(summary.inactive_product_count)
  if (currentCount !== undefined || inactiveCount !== undefined) {
    facts.push(`${formatNumber(currentCount || 0)} current / ${formatNumber(inactiveCount || 0)} inactive`)
  }
  const candidate = asRecord(summary.top_candidate)
  const productName = asString(candidate.product_name)
  const regNo = asString(candidate.epa_reg_no)
  const status = asString(candidate.status)
  const candidateLabel = [productName, regNo ? `EPA Reg. ${regNo}` : undefined, status].filter(Boolean).join(' · ')
  if (candidateLabel) facts.push(`Top candidate: ${candidateLabel}`)
  else {
    const first = asRecord(asArray(summary.products)[0])
    const firstName = asString(first.product_name)
    const firstReg = asString(first.epa_reg_no)
    if (firstName && firstReg) facts.push(`${firstName} (${firstReg})`)
    else if (firstName) facts.push(firstName)
  }
  if (summary.needs_product_disambiguation === true) facts.push('Needs exact product or EPA reg no')
  return facts
}

const toolLinks = (name: string, summary: JsonRecord): PublicToolCard['links'] => {
  if (isPublicSourceCard(name)) {
    return asStringArray(summary.source_urls)
      .filter((url) => /^https?:\/\//i.test(url))
      .slice(1, 3)
      .map((url, index) => ({ label: index === 0 ? 'Related official source' : `Official source ${index + 2}`, url }))
  }
  if (name !== 'epa_ppls_product_search') return undefined
  const urls: string[] = []
  const candidate = asRecord(summary.top_candidate)
  asStringArray(candidate.label_pdf_urls).forEach((url) => urls.push(url))
  asArray(summary.products).map(asRecord).forEach((product) => {
    asStringArray(product.label_pdf_urls).forEach((url) => urls.push(url))
  })
  return Array.from(new Set(urls))
    .filter((url) => /^https?:\/\//i.test(url))
    .slice(0, 3)
    .map((url, index) => ({ label: index === 0 ? 'Label PDF' : `Label PDF ${index + 1}`, url }))
}

const unavailableFacts = (name: string, summary: JsonRecord, status: string): string[] => {
  if (status === 'source_lane_available') return publicSourceCardFacts(summary)
  if (status === 'canada_source_lane_planned') return canadaSourceLaneFacts(summary).length ? canadaSourceLaneFacts(summary) : ['Canadian source lane identified']
  if (status === 'canada_source_lane_needed') return canadaSourceLaneFacts(summary).length ? canadaSourceLaneFacts(summary) : ['Source lane still needs selection']
  if (status === 'not_configured') {
    const required = asArray(summary.required_env_vars).map(String).slice(0, 2)
    return required.length ? [`Needs ${required.join(' or ')}`] : ['Needs demo credential']
  }
  if (status === 'no_records') return ['Provider returned no matching records']
  return [`Adapter status: ${statusLabel(status)}`]
}

const toolLimitation = (name: string, payload: JsonRecord, status: string): string => {
  if (isCanadaSourceLane(name)) return asString(payload.boundary) || 'Canadian source lane is identified for review; live intersected facts are not returned yet.'
  if (isPublicSourceCard(name)) return asString(payload.boundary) || 'Source card is a decision framework, not live field proof.'
  if (status !== 'available') {
    const boundary = asString(payload.boundary)
    return boundary
      ? `${boundary} Treat this source as missing until it is configured or returns records.`
      : 'The answer should treat this source as missing until it is configured or returns records.'
  }
  if (name.startsWith('nrcs_')) return 'Soil survey is a map-unit prior, not a lab result or field truth.'
  if (name.startsWith('cropland_data_layer')) return 'CDL is sampled crop-cover context, not a planting record, acreage proof, or crop-insurance evidence.'
  if (name === 'nasa_power_daily') return 'NASA POWER is gridded weather context, not an on-field sensor.'
  if (name === 'daymet_single_pixel_daily') return 'Daymet is historical gridded climate context, not a current forecast.'
  if (name === 'openet_point_timeseries') return 'OpenET is ET context, not an irrigation prescription.'
  if (name === 'nass_quickstats_crop_stats') return 'Quick Stats is regional statistics, not field yield prediction.'
  if (name === 'epa_ppls_product_search') {
    const summary = asRecord(payload.summary)
    const note = asString(summary.disambiguation_note)
    return note || 'PPLS metadata is not legal label interpretation.'
  }
  return asString(payload.boundary) || 'Use as public context only; verify against field records before acting.'
}
