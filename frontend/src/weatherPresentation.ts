type PowerMetric = { days?: number; mean?: number; sum?: number }
export type PowerCoverageInput = {
  status?: string
  requested_day_count?: number
  observed_day_count?: number
  observation_start?: string | null
  observation_end?: string | null
  parameter_summary?: Record<string, PowerMetric>
}
const parameters = ['T2M', 'PRECTOTCORR', 'WS2M'] as const
const validNumber = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value)
const usable = (metric?: PowerMetric) => !!metric && validNumber(metric.days) && metric.days > 0 && (validNumber(metric.mean) || validNumber(metric.sum))

export function powerCoverage(payload?: PowerCoverageInput) {
  const requested = payload?.requested_day_count && payload.requested_day_count > 0 ? payload.requested_day_count : 3
  const metrics = parameters.map(key => payload?.parameter_summary?.[key])
  const observed = payload?.observed_day_count ?? Math.max(0, ...metrics.filter(usable).map(metric => metric?.days || 0))
  const permittedStatus = !payload?.status || ['available', 'partial_available'].includes(payload.status)
  const hasData = permittedStatus && observed > 0 && metrics.some(usable)
  const complete = hasData && payload?.status !== 'partial_available' && metrics.every(metric => usable(metric) && (metric?.days || 0) >= requested)
  const status = hasData ? complete ? 'available' : 'partial_available' : 'unavailable'
  const first = payload?.observation_start
  const last = payload?.observation_end
  return {
    status,
    hasData,
    observed,
    requested,
    label: hasData ? `${observed} of ${requested} requested days available` : 'No usable observations in this window',
    observationLabel: first && last ? `Observed UTC ${first}${last !== first ? `–${last}` : ''}` : 'Actual observation dates were not reported',
  } as const
}
