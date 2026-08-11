import { describe, expect, it } from 'vitest'
import {
  PHASE6_SCRATCHPAD_MAX_CHARS,
  PHASE6_SCRATCHPAD_STORAGE_KEY,
  clearPhase6Scratchpad,
  loadPhase6Scratchpad,
  savePhase6Scratchpad,
} from './offlineScratchpad'
import {
  PHASE6_OFFLINE_STORAGE_QUARANTINE_KEY,
  PHASE6_OFFLINE_STORAGE_REPAIRED_EVENT,
  listPhase6OfflineStorageQuarantine,
} from './offlineStorageRepair'

const makeStorage = () => {
  const values = new Map<string, string>()
  return {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => values.set(key, value),
    removeItem: (key: string) => values.delete(key),
    raw: values,
  }
}

describe('Phase 6 local-only scratchpad', () => {
  it('stores field notes by session with an explicit local-only sync state', () => {
    const storage = makeStorage()

    const scratchpad = savePhase6Scratchpad('sess_1', 'Scouted west low spot after rain.', storage, () => '2026-06-01T00:00:00.000Z')

    expect(scratchpad).toEqual({
      sessionId: 'sess_1',
      notes: 'Scouted west low spot after rain.',
      updatedAt: '2026-06-01T00:00:00.000Z',
      syncState: 'local_only',
    })
    expect(loadPhase6Scratchpad('sess_1', storage)).toEqual(scratchpad)
    expect(loadPhase6Scratchpad('sess_2', storage)).toBeNull()
  })

  it('clears blank notes and leaves other session scratchpads intact', () => {
    const storage = makeStorage()

    savePhase6Scratchpad('sess_1', 'one', storage)
    savePhase6Scratchpad('sess_2', 'two', storage)
    savePhase6Scratchpad('sess_1', '   ', storage)

    expect(loadPhase6Scratchpad('sess_1', storage)).toBeNull()
    expect(loadPhase6Scratchpad('sess_2', storage)?.notes).toBe('two')

    clearPhase6Scratchpad('sess_2', storage)
    expect(storage.raw.has(PHASE6_SCRATCHPAD_STORAGE_KEY)).toBe(false)
  })

  it('self-heals corrupt storage and caps note size', () => {
    const storage = makeStorage()
    const repairs: CustomEvent[] = []
    const onRepair = (event: Event) => repairs.push(event as CustomEvent)
    window.addEventListener(PHASE6_OFFLINE_STORAGE_REPAIRED_EVENT, onRepair)
    storage.setItem(PHASE6_SCRATCHPAD_STORAGE_KEY, '[]')

    try {
      expect(loadPhase6Scratchpad('sess_1', storage)).toBeNull()
      expect(storage.raw.has(PHASE6_SCRATCHPAD_STORAGE_KEY)).toBe(false)
      expect(repairs.map((event) => event.detail)).toEqual([
        {
          store: 'scratchpad',
          storageKey: PHASE6_SCRATCHPAD_STORAGE_KEY,
          reason: 'invalid_shape',
          disposition: 'quarantined',
          recoveryRecordId: expect.any(String),
          capturedAt: expect.any(String),
          rawCharacters: 2,
        },
      ])
      expect(storage.raw.has(PHASE6_OFFLINE_STORAGE_QUARANTINE_KEY)).toBe(true)
      expect(listPhase6OfflineStorageQuarantine(storage)).toEqual([
        expect.objectContaining({
          store: 'scratchpad',
          sourceStorageKey: PHASE6_SCRATCHPAD_STORAGE_KEY,
          raw: '[]',
        }),
      ])
    } finally {
      window.removeEventListener(PHASE6_OFFLINE_STORAGE_REPAIRED_EVENT, onRepair)
    }

    const saved = savePhase6Scratchpad('sess_1', 'x'.repeat(PHASE6_SCRATCHPAD_MAX_CHARS + 10), storage)
    expect(saved?.notes).toHaveLength(PHASE6_SCRATCHPAD_MAX_CHARS)
  })

  it('fails loudly when saving without a session id', () => {
    const storage = makeStorage()

    expect(() => savePhase6Scratchpad('', 'notes', storage)).toThrow('sessionId is required')
  })
})
