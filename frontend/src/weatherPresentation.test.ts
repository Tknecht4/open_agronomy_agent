import { describe, expect, it } from 'vitest'
import { powerCoverage } from './weatherPresentation'

describe('weather coverage presentation', () => {
  it('does not turn an empty successful response into available weather', () => {
    expect(powerCoverage({})).toMatchObject({ status: 'unavailable', hasData: false })
    expect(powerCoverage({ status: 'available', parameter_summary: { PRECTOTCORR: { days: 0, sum: 0 } } }).hasData).toBe(false)
  })
  it('shows the actual one-day coverage and retains a valid zero rainfall', () => {
    const coverage = powerCoverage({ status: 'partial_available', requested_day_count: 3, observed_day_count: 1,
      observation_start: '2026-09-25', observation_end: '2026-09-25', parameter_summary: {
        T2M: { days: 1, mean: 9 }, PRECTOTCORR: { days: 1, sum: 0 }, WS2M: { days: 1, mean: 2 },
      } })
    expect(coverage).toMatchObject({ status: 'partial_available', hasData: true, label: '1 of 3 requested days available', observationLabel: 'Observed UTC 2026-09-25' })
  })
  it('does not invent dates for legacy receipts or ignore a declared unavailable status', () => {
    const parameter_summary = { T2M: { days: 3, mean: 0 }, PRECTOTCORR: { days: 3, sum: 0 }, WS2M: { days: 3, mean: 0 } }
    expect(powerCoverage({ parameter_summary })).toMatchObject({ status: 'available', observationLabel: 'Actual observation dates were not reported' })
    expect(powerCoverage({ status: 'no_data', parameter_summary }).hasData).toBe(false)
  })
})
