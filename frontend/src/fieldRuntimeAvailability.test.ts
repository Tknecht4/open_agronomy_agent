import { describe, expect, it } from 'vitest'
import { fieldAnswerCapability, isRuntimeTransportFailure } from './fieldRuntimeAvailability'

describe('farmer-facing runtime availability', () => {
  it('distinguishes an internet-blocked local runtime from a disconnected client', () => {
    expect(fieldAnswerCapability('available', 'offline')).toMatchObject({
      canGenerateAnswer: true,
      state: 'runtime_offline',
      badge: 'Local runtime · internet blocked',
    })
    expect(fieldAnswerCapability('unavailable', 'offline')).toMatchObject({
      canGenerateAnswer: false,
      state: 'notes_only',
      badge: 'Runtime unavailable · notes only',
    })
  })

  it('does not imply live-source availability when runtime source mode is unknown', () => {
    expect(fieldAnswerCapability('available', 'unknown')).toMatchObject({
      canGenerateAnswer: true,
      badge: 'Local runtime · source mode unknown',
    })
  })

  it('recognizes browser transport failures without treating every server error as disconnection', () => {
    expect(isRuntimeTransportFailure(new TypeError('Failed to fetch'))).toBe(true)
    expect(isRuntimeTransportFailure(new Error('Network request failed'))).toBe(true)
    expect(isRuntimeTransportFailure(new Error('500: model host unavailable'))).toBe(false)
  })
})
