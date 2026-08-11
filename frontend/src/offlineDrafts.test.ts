import { describe, expect, it } from 'vitest'
import {
  PHASE6_CHAT_DRAFT_MAX_CHARS,
  PHASE6_CHAT_DRAFT_STORAGE_KEY,
  clearPhase6ChatDraft,
  loadPhase6ChatDraft,
  savePhase6ChatDraft,
} from './offlineDrafts'
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

describe('Phase 6 offline chat drafts', () => {
  it('persists a session-scoped draft with timestamp metadata', () => {
    const storage = makeStorage()

    const draft = savePhase6ChatDraft('sess_1', 'Can I plant after this rain?', storage, () => '2026-06-01T00:00:00.000Z')

    expect(draft).toEqual({
      sessionId: 'sess_1',
      message: 'Can I plant after this rain?',
      updatedAt: '2026-06-01T00:00:00.000Z',
    })
    expect(loadPhase6ChatDraft('sess_1', storage)).toEqual(draft)
    expect(loadPhase6ChatDraft('sess_2', storage)).toBeNull()
  })

  it('clears blank and sent drafts without disturbing other sessions', () => {
    const storage = makeStorage()

    savePhase6ChatDraft('sess_1', 'first draft', storage)
    savePhase6ChatDraft('sess_2', 'second draft', storage)
    savePhase6ChatDraft('sess_1', '   ', storage)

    expect(loadPhase6ChatDraft('sess_1', storage)).toBeNull()
    expect(loadPhase6ChatDraft('sess_2', storage)?.message).toBe('second draft')

    clearPhase6ChatDraft('sess_2', storage)
    expect(storage.raw.has(PHASE6_CHAT_DRAFT_STORAGE_KEY)).toBe(false)
  })

  it('self-heals corrupt draft storage and caps draft size', () => {
    const storage = makeStorage()
    const repairs: CustomEvent[] = []
    const onRepair = (event: Event) => repairs.push(event as CustomEvent)
    window.addEventListener(PHASE6_OFFLINE_STORAGE_REPAIRED_EVENT, onRepair)
    storage.setItem(PHASE6_CHAT_DRAFT_STORAGE_KEY, '{not valid json with Private field note')

    try {
      expect(loadPhase6ChatDraft('sess_1', storage)).toBeNull()
      expect(storage.raw.has(PHASE6_CHAT_DRAFT_STORAGE_KEY)).toBe(false)
      expect(repairs.map((event) => event.detail)).toEqual([
        {
          store: 'chat_draft',
          storageKey: PHASE6_CHAT_DRAFT_STORAGE_KEY,
          reason: 'invalid_json',
          disposition: 'quarantined',
          recoveryRecordId: expect.any(String),
          capturedAt: expect.any(String),
          rawCharacters: 39,
        },
      ])
      expect(JSON.stringify(repairs.map((event) => event.detail))).not.toContain('Private field note')
      expect(storage.raw.has(PHASE6_OFFLINE_STORAGE_QUARANTINE_KEY)).toBe(true)
      expect(listPhase6OfflineStorageQuarantine(storage)).toEqual([
        expect.objectContaining({
          store: 'chat_draft',
          sourceStorageKey: PHASE6_CHAT_DRAFT_STORAGE_KEY,
          raw: '{not valid json with Private field note',
        }),
      ])
    } finally {
      window.removeEventListener(PHASE6_OFFLINE_STORAGE_REPAIRED_EVENT, onRepair)
    }

    const saved = savePhase6ChatDraft('sess_1', 'x'.repeat(PHASE6_CHAT_DRAFT_MAX_CHARS + 20), storage)
    expect(saved?.message).toHaveLength(PHASE6_CHAT_DRAFT_MAX_CHARS)
  })

  it('fails loudly when saving without a session id', () => {
    const storage = makeStorage()

    expect(() => savePhase6ChatDraft('', 'draft', storage)).toThrow('sessionId is required')
  })
})
