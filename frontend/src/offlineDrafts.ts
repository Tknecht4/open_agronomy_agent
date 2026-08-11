import { quarantinePhase6OfflineStorage } from './offlineStorageRepair'

export const PHASE6_CHAT_DRAFT_STORAGE_KEY = 'agronomy-agent.phase6.chat-drafts.v1'
export const PHASE6_CHAT_DRAFT_MAX_CHARS = 8000

export type Phase6ChatDraft = {
  sessionId: string
  message: string
  updatedAt: string
}

type DraftStore = Record<string, Phase6ChatDraft>
type BrowserStorage = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>

const nowIso = () => new Date().toISOString()

const readDraftStore = (storage: BrowserStorage): DraftStore => {
  const raw = storage.getItem(PHASE6_CHAT_DRAFT_STORAGE_KEY)
  if (!raw) {
    return {}
  }
  let repairReason: 'invalid_json' | 'invalid_shape' = 'invalid_json'
  try {
    const parsed = JSON.parse(raw) as unknown
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      repairReason = 'invalid_shape'
      throw new Error('draft store must be an object')
    }
    return parsed as DraftStore
  } catch {
    quarantinePhase6OfflineStorage(
      {
        store: 'chat_draft',
        storageKey: PHASE6_CHAT_DRAFT_STORAGE_KEY,
        reason: repairReason,
        raw,
      },
      storage,
    )
    return {}
  }
}

const writeDraftStore = (storage: BrowserStorage, store: DraftStore) => {
  const keys = Object.keys(store)
  if (keys.length === 0) {
    storage.removeItem(PHASE6_CHAT_DRAFT_STORAGE_KEY)
    return
  }
  storage.setItem(PHASE6_CHAT_DRAFT_STORAGE_KEY, JSON.stringify(store))
}

export function loadPhase6ChatDraft(
  sessionId: string,
  storage: BrowserStorage = window.localStorage,
): Phase6ChatDraft | null {
  if (!sessionId.trim()) {
    return null
  }
  const draft = readDraftStore(storage)[sessionId]
  return draft && typeof draft.message === 'string' ? draft : null
}

export function savePhase6ChatDraft(
  sessionId: string,
  message: string,
  storage: BrowserStorage = window.localStorage,
  timestamp: () => string = nowIso,
): Phase6ChatDraft | null {
  const key = sessionId.trim()
  if (!key) {
    throw new Error('sessionId is required to save a Phase 6 chat draft')
  }
  const trimmed = message.trim()
  if (!trimmed) {
    clearPhase6ChatDraft(key, storage)
    return null
  }
  const draft = {
    sessionId: key,
    message: message.slice(0, PHASE6_CHAT_DRAFT_MAX_CHARS),
    updatedAt: timestamp(),
  }
  const store = readDraftStore(storage)
  store[key] = draft
  writeDraftStore(storage, store)
  return draft
}

export function clearPhase6ChatDraft(sessionId: string, storage: BrowserStorage = window.localStorage): void {
  const key = sessionId.trim()
  if (!key) {
    return
  }
  const store = readDraftStore(storage)
  delete store[key]
  writeDraftStore(storage, store)
}
