const FIELD_EVENT_OPERATION_PROTOCOL = 'open_agronomy_agent.field_event_operation.v2'
export const testScope = (fieldId = 'field-A', actor = '10000000-0000-4000-8000-000000000001') => ({
  protocol: FIELD_EVENT_OPERATION_PROTOCOL, actor_user_id: actor,
  workspace_id: '20000000-0000-4000-8000-000000000002', field_context_id: fieldId,
})
export const testReceipt = (path: string, body: Record<string, unknown>, eventId = 'event-1') => ({
  event: { id: eventId, field_context_id: path.split('/')[4] },
  operation: { ...testScope(path.split('/')[4], String(body.expected_actor_user_id)), operation_id: body.client_operation_id, event_id: eventId },
})
// Test double for admission/update serialization only. Actual browser tests exercise native Web Locks.
export function testLocks() {
  const queues = new Map<string, Promise<unknown>>()
  return { request: <T>(name: string, action: () => T) => {
    const result = (queues.get(name) || Promise.resolve()).catch(() => {}).then(action)
    queues.set(name, result)
    return result
  } }
}
