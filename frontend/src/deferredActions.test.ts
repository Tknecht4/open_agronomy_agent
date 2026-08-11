import { describe, expect, it } from 'vitest'
import {
  PHASE6_DEFERRED_ACTION_BODY_MAX_CHARS,
  PHASE6_DEFERRED_ACTION_LIMIT,
  PHASE6_DEFERRED_ACTION_STORAGE_KEY,
  enqueuePhase6DeferredAction,
  listPhase6DeferredActions,
  removePhase6DeferredAction,
} from './deferredActions'
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

describe('Phase 6 deferred offline actions', () => {
  it('queues hosted feedback with stable metadata for explicit retry', () => {
    const storage = makeStorage()

    const queued = enqueuePhase6DeferredAction(
      {
        kind: 'hosted_feedback',
        path: '/messages/msg_1/feedback',
        method: 'POST',
        body: { rating: 'needs_work' },
        workspaceId: 'workspace_1',
        threadId: 'thread_1',
      },
      storage,
      () => 'queued_1',
      () => '2026-06-01T00:00:00.000Z',
    )

    expect(queued).toMatchObject({ id: 'queued_1', kind: 'hosted_feedback', method: 'POST' })
    expect(listPhase6DeferredActions(storage)).toEqual([queued])
  })

  it('omits raw user text from deferred feedback bodies stored in localStorage', () => {
    const storage = makeStorage()

    const queued = enqueuePhase6DeferredAction(
      {
        kind: 'hosted_feedback',
        path: '/messages/msg_1/feedback',
        method: 'POST',
        body: {
          rating: 'needs_work',
          failure_tags: ['missing_context'],
          human_correction: 'Private field note about west low spot after rain.',
          ideal_answer: 'Full answer text that should not be cached offline.',
          uploaded_file_text: 'Raw upload content',
        },
      },
      storage,
      () => 'queued_1',
    )

    expect(queued.body).toEqual({
      rating: 'needs_work',
      failure_tags: ['missing_context'],
      deferred_text_omitted: true,
    })
    const raw = storage.raw.get(PHASE6_DEFERRED_ACTION_STORAGE_KEY) || ''
    expect(raw).not.toContain('Private field note')
    expect(raw).not.toContain('Full answer text')
    expect(raw).not.toContain('Raw upload content')
  })

  it('removes actions after successful replay and clears storage when empty', () => {
    const storage = makeStorage()
    enqueuePhase6DeferredAction(
      { kind: 'hosted_thread_export', path: '/threads/thread_1/exports', method: 'POST', body: { export_type: 'json' } },
      storage,
      () => 'queued_1',
    )

    removePhase6DeferredAction('queued_1', storage)

    expect(listPhase6DeferredActions(storage)).toEqual([])
    expect(storage.raw.has(PHASE6_DEFERRED_ACTION_STORAGE_KEY)).toBe(false)
  })

  it('self-heals corrupt storage and keeps only the newest bounded queue entries', () => {
    const storage = makeStorage()
    const repairs: CustomEvent[] = []
    const onRepair = (event: Event) => repairs.push(event as CustomEvent)
    window.addEventListener(PHASE6_OFFLINE_STORAGE_REPAIRED_EVENT, onRepair)
    storage.setItem(PHASE6_DEFERRED_ACTION_STORAGE_KEY, '{"bad":"Private raw feedback"}')

    try {
      expect(listPhase6DeferredActions(storage)).toEqual([])
      expect(storage.raw.has(PHASE6_DEFERRED_ACTION_STORAGE_KEY)).toBe(false)
      expect(repairs.map((event) => event.detail)).toEqual([
        {
          store: 'deferred_action',
          storageKey: PHASE6_DEFERRED_ACTION_STORAGE_KEY,
          reason: 'invalid_shape',
          disposition: 'quarantined',
          recoveryRecordId: expect.any(String),
          capturedAt: expect.any(String),
          rawCharacters: 30,
        },
      ])
      expect(JSON.stringify(repairs.map((event) => event.detail))).not.toContain('Private raw feedback')
      expect(storage.raw.has(PHASE6_OFFLINE_STORAGE_QUARANTINE_KEY)).toBe(true)
      expect(listPhase6OfflineStorageQuarantine(storage)).toEqual([
        expect.objectContaining({
          store: 'deferred_action',
          sourceStorageKey: PHASE6_DEFERRED_ACTION_STORAGE_KEY,
          raw: '{"bad":"Private raw feedback"}',
        }),
      ])
    } finally {
      window.removeEventListener(PHASE6_OFFLINE_STORAGE_REPAIRED_EVENT, onRepair)
    }

    for (let index = 0; index < PHASE6_DEFERRED_ACTION_LIMIT + 2; index += 1) {
      enqueuePhase6DeferredAction(
        { kind: 'hosted_thread_export', path: `/threads/thread_${index}/exports`, method: 'POST', body: { export_type: 'json' } },
        storage,
        () => `queued_${index}`,
      )
    }

    const actions = listPhase6DeferredActions(storage)
    expect(actions).toHaveLength(PHASE6_DEFERRED_ACTION_LIMIT)
    expect(actions[0].id).toBe('queued_2')
  })

  it('fails loudly for unsafe action shapes', () => {
    const storage = makeStorage()

    expect(() =>
      enqueuePhase6DeferredAction({ kind: 'hosted_feedback', path: '/api/feedback', method: 'POST', body: {} }, storage),
    ).toThrow('unsupported deferred action path')
    expect(() =>
      enqueuePhase6DeferredAction(
        { kind: 'hosted_feedback', path: '/messages/msg_1/feedback/extra', method: 'POST', body: { rating: 'needs_work' } },
        storage,
      ),
    ).toThrow('unsupported deferred action path')
    expect(() =>
      enqueuePhase6DeferredAction(
        { kind: 'hosted_feedback', path: '/threads/thread_1/exports', method: 'POST', body: { rating: 'needs_work' } },
        storage,
      ),
    ).toThrow('unsupported deferred action path')
    expect(() =>
      enqueuePhase6DeferredAction(
        { kind: 'hosted_thread_export', path: '/messages/msg_1/feedback', method: 'POST', body: { export_type: 'json' } },
        storage,
      ),
    ).toThrow('unsupported deferred action path')
    expect(() =>
      enqueuePhase6DeferredAction(
        { kind: 'hosted_feedback', path: '/messages/msg_1/feedback', method: 'POST', body: { rating: 'x'.repeat(PHASE6_DEFERRED_ACTION_BODY_MAX_CHARS + 1) } },
        storage,
      ),
    ).toThrow('too large')
  })
})
