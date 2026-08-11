import { describe, expect, it, vi } from 'vitest'
import { consumeLocalPairingFragment } from './localPairing'

function locationWith(hash: string): Location {
  return {
    hash,
    pathname: '/',
    search: '?field=west',
  } as Location
}

describe('local field-client pairing', () => {
  it('does nothing when no pairing fragment is present', async () => {
    const fetchImpl = vi.fn()
    const history = { replaceState: vi.fn() } as unknown as History

    await expect(
      consumeLocalPairingFragment({
        location: locationWith(''),
        history,
        fetchImpl: fetchImpl as typeof fetch,
      }),
    ).resolves.toEqual({ attempted: false, paired: false })
    expect(fetchImpl).not.toHaveBeenCalled()
    expect(history.replaceState).not.toHaveBeenCalled()
  })

  it('clears the fragment before exchanging a pairing token', async () => {
    const events: string[] = []
    const history = {
      replaceState: vi.fn(() => events.push('fragment-cleared')),
    } as unknown as History
    const fetchImpl = vi.fn(async (_path: string, init?: RequestInit) => {
      events.push('token-posted')
      expect(JSON.parse(String(init?.body))).toEqual({ token: 'x'.repeat(43) })
      return { ok: true, status: 200 } as Response
    })

    await expect(
      consumeLocalPairingFragment({
        location: locationWith(`#pair=${'x'.repeat(43)}`),
        history,
        fetchImpl: fetchImpl as typeof fetch,
      }),
    ).resolves.toEqual({ attempted: true, paired: true })
    expect(events).toEqual(['fragment-cleared', 'token-posted'])
    expect(history.replaceState).toHaveBeenCalledWith(null, '', '/?field=west')
  })

  it('fails closed when the server rejects the pairing token', async () => {
    const history = { replaceState: vi.fn() } as unknown as History
    const fetchImpl = vi.fn(async () => ({
      ok: false,
      status: 409,
      text: async () => '{"detail":"already consumed"}',
    } as Response))

    await expect(
      consumeLocalPairingFragment({
        location: locationWith(`#pair=${'y'.repeat(43)}`),
        history,
        fetchImpl: fetchImpl as typeof fetch,
      }),
    ).rejects.toThrow('This device could not be paired (409)')
    expect(history.replaceState).toHaveBeenCalled()
  })
})
