import { quarantinePhase6OfflineStorage } from './offlineStorageRepair'

export const PHASE6_DEFERRED_ACTION_STORAGE_KEY = 'agronomy-agent.phase6.deferred-actions.v1'
export const PHASE6_DEFERRED_ACTION_LIMIT = 50
export const PHASE6_DEFERRED_ACTION_BODY_MAX_CHARS = 16000

export type Phase6DeferredActionKind = 'hosted_feedback' | 'hosted_thread_export'

export type Phase6DeferredAction = {
  id: string
  kind: Phase6DeferredActionKind
  path: string
  method: 'POST'
  body: Record<string, unknown>
  workspaceId?: string
  threadId?: string
  createdAt: string
}

type BrowserStorage = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>
type IdFactory = () => string
type TimestampFactory = () => string

const allowedKinds = new Set<Phase6DeferredActionKind>(['hosted_feedback', 'hosted_thread_export'])
const safeFeedbackBodyKeys = new Set(['rating', 'issue_tag', 'failure_tags', 'training_consent'])
const safeThreadExportBodyKeys = new Set(['export_type'])
const hostedFeedbackPathRe = /^\/messages\/[^/]+\/feedback$/
const hostedThreadExportPathRe = /^\/threads\/[^/]+\/exports$/
const nowIso = () => new Date().toISOString()
const defaultId = () => `deferred_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`

const readActions = (storage: BrowserStorage): Phase6DeferredAction[] => {
  const raw = storage.getItem(PHASE6_DEFERRED_ACTION_STORAGE_KEY)
  if (!raw) {
    return []
  }
  let repairReason: 'invalid_json' | 'invalid_shape' = 'invalid_json'
  try {
    const parsed = JSON.parse(raw) as unknown
    if (!Array.isArray(parsed)) {
      repairReason = 'invalid_shape'
      throw new Error('deferred action store must be an array')
    }
    return parsed.filter(isStoredAction)
  } catch {
    quarantinePhase6OfflineStorage(
      {
        store: 'deferred_action',
        storageKey: PHASE6_DEFERRED_ACTION_STORAGE_KEY,
        reason: repairReason,
        raw,
      },
      storage,
    )
    return []
  }
}

const writeActions = (storage: BrowserStorage, actions: Phase6DeferredAction[]) => {
  if (actions.length === 0) {
    storage.removeItem(PHASE6_DEFERRED_ACTION_STORAGE_KEY)
    return
  }
  storage.setItem(PHASE6_DEFERRED_ACTION_STORAGE_KEY, JSON.stringify(actions.slice(-PHASE6_DEFERRED_ACTION_LIMIT)))
}

const isStoredAction = (value: unknown): value is Phase6DeferredAction => {
  const item = value as Partial<Phase6DeferredAction>
  return Boolean(
    item &&
      typeof item.id === 'string' &&
      typeof item.path === 'string' &&
      item.method === 'POST' &&
      typeof item.createdAt === 'string' &&
      typeof item.body === 'object' &&
      item.body &&
      allowedKinds.has(item.kind as Phase6DeferredActionKind),
  )
}

const validateAction = (action: Omit<Phase6DeferredAction, 'id' | 'createdAt'>) => {
  if (!allowedKinds.has(action.kind)) {
    throw new Error(`unsupported deferred action kind: ${String(action.kind)}`)
  }
  if (action.method !== 'POST') {
    throw new Error('only POST actions can be deferred in Phase 6')
  }
  if (action.kind === 'hosted_feedback' && !hostedFeedbackPathRe.test(action.path)) {
    throw new Error(`unsupported deferred action path: ${action.path}`)
  }
  if (action.kind === 'hosted_thread_export' && !hostedThreadExportPathRe.test(action.path)) {
    throw new Error(`unsupported deferred action path: ${action.path}`)
  }
  if (JSON.stringify(action.body).length > PHASE6_DEFERRED_ACTION_BODY_MAX_CHARS) {
    throw new Error('deferred action body is too large')
  }
}

const sanitizeDeferredBody = (action: Omit<Phase6DeferredAction, 'id' | 'createdAt'>): Record<string, unknown> => {
  const allowedKeys = action.kind === 'hosted_thread_export' ? safeThreadExportBodyKeys : safeFeedbackBodyKeys
  const sanitized: Record<string, unknown> = {}
  let omitted = false
  for (const [key, value] of Object.entries(action.body)) {
    if (allowedKeys.has(key)) {
      sanitized[key] = value
    } else {
      omitted = true
    }
  }
  if (omitted) {
    sanitized.deferred_text_omitted = true
  }
  return sanitized
}

export function listPhase6DeferredActions(storage: BrowserStorage = window.localStorage): Phase6DeferredAction[] {
  return readActions(storage)
}

export function enqueuePhase6DeferredAction(
  action: Omit<Phase6DeferredAction, 'id' | 'createdAt'>,
  storage: BrowserStorage = window.localStorage,
  idFactory: IdFactory = defaultId,
  timestamp: TimestampFactory = nowIso,
): Phase6DeferredAction {
  const safeAction = { ...action, body: sanitizeDeferredBody(action) }
  validateAction(safeAction)
  const queued = {
    ...safeAction,
    id: idFactory(),
    createdAt: timestamp(),
  }
  writeActions(storage, [...readActions(storage), queued])
  return queued
}

export function removePhase6DeferredAction(id: string, storage: BrowserStorage = window.localStorage): void {
  writeActions(
    storage,
    readActions(storage).filter((action) => action.id !== id),
  )
}
