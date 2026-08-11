export const PHASE6_OFFLINE_STORAGE_REPAIRED_EVENT = 'phase6:offline-storage-repaired'
export const PHASE6_OFFLINE_STORAGE_QUARANTINE_KEY = 'agronomy-agent.phase6.offline-storage-quarantine.v1'

export type Phase6OfflineStorageRepairDetail = {
  store: 'chat_draft' | 'scratchpad' | 'deferred_action'
  storageKey: string
  reason: 'invalid_json' | 'invalid_shape'
  disposition: 'quarantined' | 'preserved_in_place' | 'preserved_in_memory'
  recoveryRecordId: string | null
  capturedAt: string
  rawCharacters: number
}

export type Phase6OfflineStorageQuarantineRecord = {
  id: string
  store: Phase6OfflineStorageRepairDetail['store']
  sourceStorageKey: string
  reason: Phase6OfflineStorageRepairDetail['reason']
  capturedAt: string
  raw: string
}

type BrowserStorage = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>

const nowIso = () => new Date().toISOString()
const emergencyRecoveryRecords: Phase6OfflineStorageQuarantineRecord[] = []
const defaultRecordId = () =>
  typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
    ? `offline_recovery_${crypto.randomUUID()}`
    : `offline_recovery_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`

export const emitPhase6OfflineStorageRepair = (detail: Phase6OfflineStorageRepairDetail): void => {
  if (typeof window === 'undefined' || typeof CustomEvent === 'undefined') {
    return
  }
  window.dispatchEvent(new CustomEvent(PHASE6_OFFLINE_STORAGE_REPAIRED_EVENT, { detail }))
}

const readQuarantine = (storage: BrowserStorage): Phase6OfflineStorageQuarantineRecord[] | null => {
  const raw = storage.getItem(PHASE6_OFFLINE_STORAGE_QUARANTINE_KEY)
  if (!raw) {
    return []
  }
  try {
    const parsed = JSON.parse(raw) as unknown
    if (!Array.isArray(parsed)) {
      return null
    }
    const valid = parsed.every((item) => {
      const row = item as Partial<Phase6OfflineStorageQuarantineRecord>
      return Boolean(
        row &&
          typeof row.id === 'string' &&
          typeof row.store === 'string' &&
          typeof row.sourceStorageKey === 'string' &&
          typeof row.reason === 'string' &&
          typeof row.capturedAt === 'string' &&
          typeof row.raw === 'string',
      )
    })
    return valid ? (parsed as Phase6OfflineStorageQuarantineRecord[]) : null
  } catch {
    return null
  }
}

export function listPhase6OfflineStorageQuarantine(
  storage: BrowserStorage = window.localStorage,
): Phase6OfflineStorageQuarantineRecord[] {
  return readQuarantine(storage) || []
}

export function quarantinePhase6OfflineStorage(
  input: Pick<Phase6OfflineStorageRepairDetail, 'store' | 'storageKey' | 'reason'> & { raw: string },
  storage: BrowserStorage = window.localStorage,
  timestamp: () => string = nowIso,
  recordId: () => string = defaultRecordId,
): Phase6OfflineStorageRepairDetail {
  const capturedAt = timestamp()
  const existing = readQuarantine(storage)
  const record: Phase6OfflineStorageQuarantineRecord = {
    id: recordId(),
    store: input.store,
    sourceStorageKey: input.storageKey,
    reason: input.reason,
    capturedAt,
    raw: input.raw,
  }
  let disposition: Phase6OfflineStorageRepairDetail['disposition'] = 'preserved_in_place'
  let recoveryRecordId: string | null = null

  if (existing !== null) {
    storage.removeItem(input.storageKey)
    try {
      storage.setItem(PHASE6_OFFLINE_STORAGE_QUARANTINE_KEY, JSON.stringify([...existing, record]))
      disposition = 'quarantined'
      recoveryRecordId = record.id
    } catch {
      // localStorage setItem is atomic. Put the unreadable source back if the
      // quarantine write fails so a storage-pressure event cannot destroy it.
      try {
        storage.setItem(input.storageKey, input.raw)
      } catch {
        emergencyRecoveryRecords.push(record)
        disposition = 'preserved_in_memory'
        recoveryRecordId = record.id
      }
    }
  }

  const detail: Phase6OfflineStorageRepairDetail = {
    store: input.store,
    storageKey: input.storageKey,
    reason: input.reason,
    disposition,
    recoveryRecordId,
    capturedAt,
    rawCharacters: input.raw.length,
  }
  emitPhase6OfflineStorageRepair(detail)
  return detail
}

export function buildPhase6OfflineStorageRecoveryExport(
  latestRepair?: Phase6OfflineStorageRepairDetail | null,
  storage: BrowserStorage = window.localStorage,
): string | null {
  const records = [
    ...listPhase6OfflineStorageQuarantine(storage),
    ...emergencyRecoveryRecords,
  ]
  if (latestRepair?.disposition === 'preserved_in_place') {
    const raw = storage.getItem(latestRepair.storageKey)
    if (raw !== null) {
      records.push({
        id: `preserved_${latestRepair.capturedAt}`,
        store: latestRepair.store,
        sourceStorageKey: latestRepair.storageKey,
        reason: latestRepair.reason,
        capturedAt: latestRepair.capturedAt,
        raw,
      })
    }
  }
  if (records.length === 0) {
    return null
  }
  return JSON.stringify(
    {
      schema_version: 'open_agronomy_agent.offline_storage_recovery_export.v1',
      exported_at: nowIso(),
      boundary:
        'This file contains device-local recovery data that the application could not parse. It may contain private field notes. Review it locally before sharing.',
      records,
    },
    null,
    2,
  )
}

export function downloadPhase6OfflineStorageRecovery(
  latestRepair?: Phase6OfflineStorageRepairDetail | null,
  storage: BrowserStorage = window.localStorage,
): boolean {
  const payload = buildPhase6OfflineStorageRecoveryExport(latestRepair, storage)
  if (!payload || typeof document === 'undefined' || typeof URL === 'undefined') {
    return false
  }
  const url = URL.createObjectURL(new Blob([payload], { type: 'application/json' }))
  const link = document.createElement('a')
  link.href = url
  link.download = `open-agronomy-offline-recovery-${new Date().toISOString().replace(/[:.]/g, '-')}.json`
  link.click()
  URL.revokeObjectURL(url)
  return true
}
