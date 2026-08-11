import { quarantinePhase6OfflineStorage } from './offlineStorageRepair'

export const PHASE6_SCRATCHPAD_STORAGE_KEY = 'agronomy-agent.phase6.local-scratchpads.v1'
export const PHASE6_SCRATCHPAD_MAX_CHARS = 12000

export type Phase6Scratchpad = {
  sessionId: string
  notes: string
  updatedAt: string
  syncState: 'local_only'
}

type ScratchpadStore = Record<string, Phase6Scratchpad>
type BrowserStorage = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>

const nowIso = () => new Date().toISOString()

const readScratchpadStore = (storage: BrowserStorage): ScratchpadStore => {
  const raw = storage.getItem(PHASE6_SCRATCHPAD_STORAGE_KEY)
  if (!raw) {
    return {}
  }
  let repairReason: 'invalid_json' | 'invalid_shape' = 'invalid_json'
  try {
    const parsed = JSON.parse(raw) as unknown
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      repairReason = 'invalid_shape'
      throw new Error('scratchpad store must be an object')
    }
    return parsed as ScratchpadStore
  } catch {
    quarantinePhase6OfflineStorage(
      {
        store: 'scratchpad',
        storageKey: PHASE6_SCRATCHPAD_STORAGE_KEY,
        reason: repairReason,
        raw,
      },
      storage,
    )
    return {}
  }
}

const writeScratchpadStore = (storage: BrowserStorage, store: ScratchpadStore) => {
  const keys = Object.keys(store)
  if (keys.length === 0) {
    storage.removeItem(PHASE6_SCRATCHPAD_STORAGE_KEY)
    return
  }
  storage.setItem(PHASE6_SCRATCHPAD_STORAGE_KEY, JSON.stringify(store))
}

export function loadPhase6Scratchpad(
  sessionId: string,
  storage: BrowserStorage = window.localStorage,
): Phase6Scratchpad | null {
  if (!sessionId.trim()) {
    return null
  }
  const scratchpad = readScratchpadStore(storage)[sessionId]
  return scratchpad && typeof scratchpad.notes === 'string' ? scratchpad : null
}

export function savePhase6Scratchpad(
  sessionId: string,
  notes: string,
  storage: BrowserStorage = window.localStorage,
  timestamp: () => string = nowIso,
): Phase6Scratchpad | null {
  const key = sessionId.trim()
  if (!key) {
    throw new Error('sessionId is required to save a Phase 6 scratchpad')
  }
  const trimmed = notes.trim()
  if (!trimmed) {
    clearPhase6Scratchpad(key, storage)
    return null
  }
  const scratchpad = {
    sessionId: key,
    notes: notes.slice(0, PHASE6_SCRATCHPAD_MAX_CHARS),
    updatedAt: timestamp(),
    syncState: 'local_only' as const,
  }
  const store = readScratchpadStore(storage)
  store[key] = scratchpad
  writeScratchpadStore(storage, store)
  return scratchpad
}

export function clearPhase6Scratchpad(sessionId: string, storage: BrowserStorage = window.localStorage): void {
  const key = sessionId.trim()
  if (!key) {
    return
  }
  const store = readScratchpadStore(storage)
  delete store[key]
  writeScratchpadStore(storage, store)
}
