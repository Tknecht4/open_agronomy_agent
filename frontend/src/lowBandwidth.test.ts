import { describe, expect, it } from 'vitest'
import {
  detectPhase6LowBandwidth,
  isPhase6LowBandwidthActive,
  loadPhase6LowBandwidthPreference,
  PHASE6_LOW_BANDWIDTH_STORAGE_KEY,
  phase6LowBandwidthSummary,
  savePhase6LowBandwidthPreference,
} from './lowBandwidth'

const storage = () => {
  const values = new Map<string, string>()
  return {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => values.set(key, value),
  }
}

describe('Phase 6 low-bandwidth mode', () => {
  it('detects data-saver and slow browser connections', () => {
    expect(detectPhase6LowBandwidth({ connection: { saveData: true } })).toMatchObject({
      detected: true,
      reason: 'save_data',
    })
    expect(detectPhase6LowBandwidth({ connection: { effectiveType: '2g' } })).toMatchObject({
      detected: true,
      reason: 'slow_effective_type',
    })
    expect(detectPhase6LowBandwidth({ connection: { downlink: 0.8 } })).toMatchObject({
      detected: true,
      reason: 'low_downlink',
    })
    expect(detectPhase6LowBandwidth({ connection: { rtt: 900 } })).toMatchObject({
      detected: true,
      reason: 'high_rtt',
    })
  })

  it('keeps unsupported or normal links in auto mode without forcing the low-data path', () => {
    expect(detectPhase6LowBandwidth(undefined)).toMatchObject({
      detected: false,
      reason: 'unsupported',
    })
    expect(detectPhase6LowBandwidth({ connection: { effectiveType: '4g', downlink: 10, rtt: 80 } })).toMatchObject({
      detected: false,
      reason: 'not_detected',
    })
  })

  it('persists explicit user preference and falls back to auto for invalid values', () => {
    const fakeStorage = storage()

    savePhase6LowBandwidthPreference('on', fakeStorage)
    expect(fakeStorage.getItem(PHASE6_LOW_BANDWIDTH_STORAGE_KEY)).toBe('on')
    expect(loadPhase6LowBandwidthPreference(fakeStorage)).toBe('on')

    fakeStorage.setItem(PHASE6_LOW_BANDWIDTH_STORAGE_KEY, 'surprise')
    expect(loadPhase6LowBandwidthPreference(fakeStorage)).toBe('auto')
  })

  it('combines user preference and detection into an active mode', () => {
    const detected = detectPhase6LowBandwidth({ connection: { saveData: true } })
    const normal = detectPhase6LowBandwidth({ connection: { effectiveType: '4g', downlink: 20 } })

    expect(isPhase6LowBandwidthActive('auto', detected)).toBe(true)
    expect(isPhase6LowBandwidthActive('auto', normal)).toBe(false)
    expect(isPhase6LowBandwidthActive('on', normal)).toBe(true)
    expect(isPhase6LowBandwidthActive('off', detected)).toBe(false)
    expect(phase6LowBandwidthSummary('on', normal)).toContain('private upload attachments are skipped')
  })
})
