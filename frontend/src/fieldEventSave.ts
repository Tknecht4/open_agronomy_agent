import { ApiError, apiGet, apiPost } from './api'

export const FIELD_EVENT_OPERATION_CHANGED = 'open-agronomy-field-event-operation-changed'
export const FIELD_EVENT_OPERATION_PROTOCOL = 'open_agronomy_agent.field_event_operation.v2'
const PREFIX = 'open-agronomy-agent.field-event-operation.v2:'
const MAX_PENDING = 16
const MAX_RECEIPTS = 64
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
export type OperationScope = { protocol: string; actor_user_id: string; workspace_id: string; field_context_id: string }
export type PendingFieldEvent = {
  operationId: string; scope: OperationScope; payloadKey: string; payload: Record<string, unknown>
  state: 'uncertain' | 'rejected'; attempts: number; createdAt: number
}
type Receipt = { operationId: string; scope: OperationScope; state: 'acknowledged' | 'resolved'; eventId?: string; createdAt: number }
type Stored = PendingFieldEvent | Receipt
type SaveResponse = { event: { id: string; field_context_id?: string }; operation?: OperationScope & { operation_id: string; event_id: string } }
type SaveOptions = { operation?: PendingFieldEvent; onPrepared?: (operation: PendingFieldEvent) => void }
const inFlight = new Map<string, Promise<SaveResponse>>()

export function canonicalFieldEvent(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonicalFieldEvent).join(',')}]`
  if (value && typeof value === 'object') return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${canonicalFieldEvent((value as Record<string, unknown>)[key])}`).join(',')}}`
  const encoded = JSON.stringify(value)
  if (encoded === undefined) throw new Error('Field record contains an unsupported value.')
  return encoded
}
function namespace(scope: OperationScope): string {
  return PREFIX + [scope.actor_user_id, scope.workspace_id, scope.field_context_id].map(encodeURIComponent).join(':') + ':'
}
function key(operation: { scope: OperationScope; operationId: string }): string { return namespace(operation.scope) + operation.operationId }
function sameScope(a: OperationScope, b: OperationScope): boolean { return canonicalFieldEvent(a) === canonicalFieldEvent(b) }
async function scopeFor(fieldId: string): Promise<OperationScope> {
  const scope = await apiGet<OperationScope>(`/api/demo/fields/${encodeURIComponent(fieldId)}/events/operation-scope`)
  if (scope.protocol !== FIELD_EVENT_OPERATION_PROTOCOL || scope.field_context_id !== fieldId
    || !UUID.test(scope.actor_user_id) || !UUID.test(scope.workspace_id)) {
    throw new Error('This server cannot verify field-record retries. Update the server before saving.')
  }
  return scope
}
async function locked<T>(_scope: OperationScope, action: () => T): Promise<T> {
  if (!navigator.locks?.request) throw new Error('Safe record storage needs Web Locks in a supported secure browser. Keep existing requests and use a supported browser.')
  // localStorage enumerates all origin keys. One origin-wide mutex prevents another field's compaction from shifting indices during admission.
  return navigator.locks.request(PREFIX + 'storage', action)
}
function read(storageKey: string, scope: OperationScope): Stored | null {
  const raw = window.localStorage.getItem(storageKey)
  if (!raw) return null
  let row: Stored
  try { row = JSON.parse(raw) as Stored } catch { throw new Error('Unconfirmed field-record storage cannot be read. Preserve it before repairing browser storage.') }
  if (!row || !UUID.test(row.operationId) || !row.scope || !sameScope(row.scope, scope) || key(row) !== storageKey
    || !Number.isFinite(row.createdAt) || !['uncertain', 'rejected', 'acknowledged', 'resolved'].includes(row.state)
    || ('payload' in row && (!row.payload || typeof row.payload !== 'object' || Array.isArray(row.payload) || canonicalFieldEvent(row.payload) !== row.payloadKey
      || !Number.isInteger(row.attempts) || row.attempts < 0))
    || ((row.state === 'uncertain' || row.state === 'rejected') && !('payload' in row))
    || (row.state === 'acknowledged' && (typeof row.eventId !== 'string' || !row.eventId))) {
    throw new Error('Unconfirmed field-record storage is invalid. Preserve it before repairing browser storage.')
  }
  return row
}
function rows(scope: OperationScope): Stored[] {
  const result: Stored[] = []
  const prefix = namespace(scope)
  // Freeze the native storage key list before reads: unrelated application keys do not participate in this protocol's lock.
  const storageKeys = Object.keys(window.localStorage)
  for (const storageKey of storageKeys) {
    if (storageKey.startsWith(prefix)) { const row = read(storageKey, scope); if (row) result.push(row) }
  }
  return result
}
function changed(): void { window.dispatchEvent(new Event(FIELD_EVENT_OPERATION_CHANGED)) }
function write(row: Stored): void { window.localStorage.setItem(key(row), JSON.stringify(row)); changed() }
function compact(scope: OperationScope): void {
  const receipts = rows(scope).filter(row => row.state === 'acknowledged' || row.state === 'resolved').sort((a, b) => b.createdAt - a.createdAt)
  for (const row of receipts.slice(MAX_RECEIPTS)) window.localStorage.removeItem(key(row))
}
export function legacyFieldEventWarning(fieldId: string): boolean {
  // Identity cannot be recovered safely from the v1 field-only queue. Preserve its bytes, never adopt or display its payload.
  return window.localStorage.getItem('open-agronomy-agent.field-event-operations.v1:' + encodeURIComponent(fieldId)) !== null
}
export async function pendingFieldEvents(fieldId: string): Promise<PendingFieldEvent[]> {
  const scope = await scopeFor(fieldId)
  return locked(scope, () => rows(scope).filter((row): row is PendingFieldEvent => row.state === 'uncertain' || row.state === 'rejected'))
}
export async function resolveRejectedFieldEvent(operation: PendingFieldEvent): Promise<void> {
  const scope = await scopeFor(operation.scope.field_context_id)
  if (!sameScope(scope, operation.scope)) throw new Error('The signed-in account changed. Return to the original account to review this request.')
  await locked(scope, () => {
    const stored = read(key(operation), scope)
    if (stored?.state !== 'rejected') throw new Error('Only a definite first-attempt rejection can be resolved. Keep uncertain requests for retry.')
    write({ operationId: operation.operationId, scope, state: 'resolved', createdAt: Date.now() })
    compact(scope)
  })
}
/** New submissions always get a new identity. Retry callers must carry the exact captured operation. */
export async function submitFieldEvent<T extends SaveResponse>(fieldId: string, payload: Record<string, unknown>, options: SaveOptions = {}): Promise<T> {
  if (!fieldId || ['client_operation_id', 'expected_actor_user_id', 'expected_workspace_id', 'expected_operation_protocol'].some(k => k in payload)) {
    throw new Error('Field-record operation scope must be assigned by the save client.')
  }
  const payloadKey = canonicalFieldEvent(payload)
  if (payloadKey.length > 100_000) throw new Error('Field record exceeds the local retry limit.')
  const scope = await scopeFor(fieldId)
  if (options.operation && (!sameScope(scope, options.operation.scope) || payloadKey !== options.operation.payloadKey)) {
    throw new Error('The account or saved request changed. Return to the original account to retry its exact request.')
  }
  const operation = options.operation || await locked(scope, () => {
    if (rows(scope).filter(row => row.state === 'uncertain' || row.state === 'rejected').length >= MAX_PENDING) {
      throw new Error('Recover unconfirmed records or resolve definite rejections before starting another save.')
    }
    const prepared: PendingFieldEvent = { operationId: crypto.randomUUID(), scope, payloadKey, payload: JSON.parse(payloadKey) as Record<string, unknown>, state: 'uncertain', attempts: 0, createdAt: Date.now() }
    write(prepared) // Durable identity precedes any POST; quota failures prevent dispatch.
    return prepared
  })
  options.onPrepared?.(operation)
  const flightKey = key(operation)
  const existing = inFlight.get(flightKey)
  if (existing) return existing as Promise<T>
  const promise = (async () => {
    const firstAttempt = await locked(scope, () => {
      const stored = read(flightKey, scope)
      if (stored?.state === 'resolved' || stored?.state === 'rejected') throw new Error('This request was rejected. Resolve it and start a corrected record.')
      if (stored && 'payloadKey' in stored && stored.payloadKey !== payloadKey) throw new Error('Saved request contents conflict. Preserve the original request.')
      // A stale view must replay its captured ID even after another tab confirms or compacts the receipt.
      if (stored?.state === 'acknowledged') return false
      if (!stored && rows(scope).filter(row => row.state === 'uncertain' || row.state === 'rejected').length >= MAX_PENDING) {
        throw new Error('Recover unconfirmed records or resolve definite rejections before retrying a request without its local receipt.')
      }
      const attempt = stored && 'attempts' in stored ? stored.attempts : Math.max(1, operation.attempts)
      write({ ...operation, state: 'uncertain', attempts: attempt + 1 })
      return attempt === 0
    })
    try {
      const result = await apiPost<T>(`/api/demo/fields/${encodeURIComponent(fieldId)}/events`, {
        ...operation.payload, client_operation_id: operation.operationId, expected_actor_user_id: scope.actor_user_id,
        expected_workspace_id: scope.workspace_id, expected_operation_protocol: scope.protocol,
      })
      const receipt = result.operation
      if (!result.event?.id || !receipt || !sameScope(scope, {
        protocol: receipt.protocol, actor_user_id: receipt.actor_user_id, workspace_id: receipt.workspace_id, field_context_id: receipt.field_context_id,
      }) || receipt.operation_id !== operation.operationId || receipt.event_id !== result.event.id
        || result.event.field_context_id && result.event.field_context_id !== fieldId) {
        throw new Error('The field-record acknowledgement could not be verified; retry the saved request.')
      }
      await locked(scope, () => { write({ operationId: operation.operationId, scope, state: 'acknowledged', eventId: result.event.id, createdAt: Date.now() }); compact(scope) })
      return result
    } catch (error) {
      // A first explicit validation rejection proves this immutable request was not accepted. A later 422 after response loss proves no such thing.
      if (firstAttempt && error instanceof ApiError && error.status === 422) {
        await locked(scope, () => {
          const stored = read(flightKey, scope)
          if (stored?.state === 'uncertain' && stored.attempts === 1) write({ ...stored, state: 'rejected' })
        })
      }
      throw error
    }
  })().finally(() => { inFlight.delete(flightKey) })
  inFlight.set(flightKey, promise)
  return promise
}
/** Reconcile only a form's captured operation; unrelated edits remain intact. Receipt lookup is account-checked. */
export function watchFieldEventConfirmation(getOperation: () => PendingFieldEvent | undefined, onConfirmed: (operation: PendingFieldEvent) => void, onResolved?: (operation: PendingFieldEvent) => void): () => void {
  let active = true
  const check = async () => {
    const operation = getOperation()
    if (!operation) return
    try {
      const scope = await scopeFor(operation.scope.field_context_id)
      if (!sameScope(scope, operation.scope)) return
      const row = await locked(scope, () => read(key(operation), scope))
      if (active && getOperation()?.operationId === operation.operationId) {
        if (row?.state === 'acknowledged') onConfirmed(operation)
        if (row?.state === 'resolved') onResolved?.(operation)
      }
    } catch { /* Recovery owns user-visible errors; never clear a draft on an unreadable receipt. */ }
  }
  const refresh = () => { void check() }
  window.addEventListener(FIELD_EVENT_OPERATION_CHANGED, refresh)
  window.addEventListener('storage', refresh)
  window.addEventListener('focus', refresh)
  // A parent refresh can replace the subscriber while an account lookup is pending. Re-read a durable receipt on subscription as well as on notifications.
  void check()
  return () => { active = false; window.removeEventListener(FIELD_EVENT_OPERATION_CHANGED, refresh); window.removeEventListener('storage', refresh); window.removeEventListener('focus', refresh) }
}
