import { describe, expect, it } from 'vitest'
import {
  PHASE6_OFFLINE_STORAGE_QUARANTINE_KEY,
  PHASE6_OFFLINE_STORAGE_REPAIRED_EVENT,
  buildPhase6OfflineStorageRecoveryExport,
  listPhase6OfflineStorageQuarantine,
  quarantinePhase6OfflineStorage,
} from './offlineStorageRepair'

const makeStorage = (failOnSet = new Set<string>()) => {
  const values = new Map<string, string>()
  return {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => {
      if (failOnSet.has(key)) {
        throw new DOMException('Storage quota exceeded', 'QuotaExceededError')
      }
      values.set(key, value)
    },
    removeItem: (key: string) => values.delete(key),
    raw: values,
  }
}

describe('offline storage recovery quarantine', () => {
  it('moves unreadable private data to a local recovery record without placing raw data in the event', () => {
    const storage = makeStorage()
    const sourceKey = 'private-field-notes'
    const raw = '{unreadable Private west-field observation'
    storage.setItem(sourceKey, raw)
    const events: CustomEvent[] = []
    const onRepair = (event: Event) => events.push(event as CustomEvent)
    window.addEventListener(PHASE6_OFFLINE_STORAGE_REPAIRED_EVENT, onRepair)

    try {
      const detail = quarantinePhase6OfflineStorage(
        { store: 'scratchpad', storageKey: sourceKey, reason: 'invalid_json', raw },
        storage,
        () => '2026-07-27T15:00:00.000Z',
        () => 'offline_recovery_test',
      )

      expect(detail).toEqual({
        store: 'scratchpad',
        storageKey: sourceKey,
        reason: 'invalid_json',
        disposition: 'quarantined',
        recoveryRecordId: 'offline_recovery_test',
        capturedAt: '2026-07-27T15:00:00.000Z',
        rawCharacters: raw.length,
      })
      expect(storage.getItem(sourceKey)).toBeNull()
      expect(listPhase6OfflineStorageQuarantine(storage)).toEqual([
        {
          id: 'offline_recovery_test',
          store: 'scratchpad',
          sourceStorageKey: sourceKey,
          reason: 'invalid_json',
          capturedAt: '2026-07-27T15:00:00.000Z',
          raw,
        },
      ])
      expect(JSON.stringify(events.map((event) => event.detail))).not.toContain('Private west-field observation')

      const recovery = JSON.parse(buildPhase6OfflineStorageRecoveryExport(detail, storage) || '{}')
      expect(recovery.schema_version).toBe('open_agronomy_agent.offline_storage_recovery_export.v1')
      expect(recovery.boundary).toContain('private field notes')
      expect(recovery.records[0].raw).toBe(raw)
    } finally {
      window.removeEventListener(PHASE6_OFFLINE_STORAGE_REPAIRED_EVENT, onRepair)
    }
  })

  it('keeps the unreadable source in place when the recovery quarantine cannot be written', () => {
    const storage = makeStorage(new Set([PHASE6_OFFLINE_STORAGE_QUARANTINE_KEY]))
    const sourceKey = 'private-question-draft'
    const raw = 'unreadable but still recoverable'
    storage.setItem(sourceKey, raw)

    const detail = quarantinePhase6OfflineStorage(
      { store: 'chat_draft', storageKey: sourceKey, reason: 'invalid_shape', raw },
      storage,
      () => '2026-07-27T15:01:00.000Z',
      () => 'offline_recovery_quota',
    )

    expect(detail).toMatchObject({
      disposition: 'preserved_in_place',
      recoveryRecordId: null,
      rawCharacters: raw.length,
    })
    expect(storage.getItem(sourceKey)).toBe(raw)
    expect(storage.getItem(PHASE6_OFFLINE_STORAGE_QUARANTINE_KEY)).toBeNull()
    const recovery = JSON.parse(buildPhase6OfflineStorageRecoveryExport(detail, storage) || '{}')
    expect(recovery.records).toEqual([
      expect.objectContaining({
        sourceStorageKey: sourceKey,
        raw,
      }),
    ])
  })

  it('does not overwrite an unreadable recovery quarantine', () => {
    const storage = makeStorage()
    const sourceKey = 'private-deferred-action'
    const raw = 'unreadable deferred action'
    storage.setItem(PHASE6_OFFLINE_STORAGE_QUARANTINE_KEY, '{broken recovery store')
    storage.setItem(sourceKey, raw)

    const detail = quarantinePhase6OfflineStorage(
      { store: 'deferred_action', storageKey: sourceKey, reason: 'invalid_json', raw },
      storage,
      () => '2026-07-27T15:02:00.000Z',
      () => 'offline_recovery_existing_corrupt',
    )

    expect(detail.disposition).toBe('preserved_in_place')
    expect(storage.getItem(sourceKey)).toBe(raw)
    expect(storage.getItem(PHASE6_OFFLINE_STORAGE_QUARANTINE_KEY)).toBe('{broken recovery store')
  })
})
