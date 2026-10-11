import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from './api'
import { testLocks, testReceipt, testScope } from './fieldEventTestSupport'
import { pendingFieldEvents, resolveRejectedFieldEvent, submitFieldEvent } from './fieldEventSave'
const post = vi.hoisted(() => vi.fn())
const get = vi.hoisted(() => vi.fn())
vi.mock('./api', async original => ({ ...await original<typeof import('./api')>(), apiPost: post, apiGet: get }))
const request = { event_type: 'observation', payload: { summary: 'North edge scouted' }, provenance: {} }

describe('actor-scoped durable record operations', () => {
  beforeEach(() => {
    localStorage.clear(); post.mockReset(); get.mockReset()
    Object.defineProperty(navigator, 'locks', { configurable: true, value: testLocks() })
    get.mockImplementation(async (path: string) => testScope(path.split('/')[4]))
    post.mockImplementation(async (path: string, body: Record<string, unknown>) => testReceipt(path, body))
  })
  it('retries captured identity after restart or another tab confirms, preserving new identical intent', async () => {
    post.mockRejectedValueOnce(new Error('Lost response'))
    await expect(submitFieldEvent('field-A', request)).rejects.toThrow('Lost response')
    const captured = (await pendingFieldEvents('field-A'))[0]
    await submitFieldEvent('field-A', captured.payload, { operation: captured })
    expect(await pendingFieldEvents('field-A')).toEqual([])
    await submitFieldEvent('field-A', captured.payload, { operation: captured }) // stale render/click
    expect(post.mock.calls[2][1]).toEqual(post.mock.calls[0][1])
    await submitFieldEvent('field-A', request) // explicit new intent
    expect(post.mock.calls[3][1].client_operation_id).not.toBe(captured.operationId)
  })
  it('never displays or dispatches actor A pending payload under actor B', async () => {
    post.mockRejectedValueOnce(new Error('Lost response'))
    await expect(submitFieldEvent('field-A', request)).rejects.toThrow()
    const captured = (await pendingFieldEvents('field-A'))[0]
    get.mockResolvedValue(testScope('field-A', '10000000-0000-4000-8000-000000000003'))
    expect(await pendingFieldEvents('field-A')).toEqual([])
    await expect(submitFieldEvent('field-A', request, { operation: captured })).rejects.toThrow('account')
    expect(post).toHaveBeenCalledOnce()
    expect(JSON.stringify(localStorage)).toContain('North edge scouted')
  })
  it('serializes concurrent admission to 16 slots without losing another operation', async () => {
    post.mockRejectedValue(new Error('offline'))
    const outcomes = await Promise.allSettled(Array.from({ length: 20 }, (_, i) => submitFieldEvent('field-A', { ...request, payload: { summary: `entry ${i}` } })))
    expect(outcomes).toHaveLength(20)
    expect(await pendingFieldEvents('field-A')).toHaveLength(16)
    expect(post).toHaveBeenCalledTimes(16)
    expect(new Set((await pendingFieldEvents('field-A')).map(row => row.operationId)).size).toBe(16)
  })
  it('releases a definite rejected slot only through explicit resolution', async () => {
    post.mockRejectedValue(new ApiError(422, 'validation failed'))
    for (let i = 0; i < 16; i++) await expect(submitFieldEvent('field-A', request)).rejects.toThrow()
    const rejected = (await pendingFieldEvents('field-A'))[0]
    expect(rejected.state).toBe('rejected')
    await expect(submitFieldEvent('field-A', request)).rejects.toThrow('Recover')
    await resolveRejectedFieldEvent(rejected)
    expect(await pendingFieldEvents('field-A')).toHaveLength(15)
    await expect(submitFieldEvent('field-A', request, { operation: rejected })).rejects.toThrow('rejected')
    post.mockImplementation(async (path, body) => testReceipt(path, body))
    await submitFieldEvent('field-A', request)
    expect(await pendingFieldEvents('field-A')).toHaveLength(15)
  })
  it('cannot resolve transport uncertainty or a later validation failure', async () => {
    post.mockRejectedValueOnce(new Error('lost'))
    await expect(submitFieldEvent('field-A', request)).rejects.toThrow()
    const captured = (await pendingFieldEvents('field-A'))[0]
    post.mockRejectedValueOnce(new ApiError(422, 'changed validator'))
    await expect(submitFieldEvent('field-A', request, { operation: captured })).rejects.toThrow()
    expect((await pendingFieldEvents('field-A'))[0].state).toBe('uncertain')
    await expect(resolveRejectedFieldEvent(captured)).rejects.toThrow('Only a definite')
  })
  it('blocks unsupported coordination/server receipt and storage failures before unsafe dispatch', async () => {
    Object.defineProperty(navigator, 'locks', { configurable: true, value: undefined })
    await expect(submitFieldEvent('field-A', request)).rejects.toThrow('Web Locks')
    expect(post).not.toHaveBeenCalled()
    Object.defineProperty(navigator, 'locks', { configurable: true, value: testLocks() })
    get.mockResolvedValueOnce({})
    await expect(submitFieldEvent('field-A', request)).rejects.toThrow('server')
    const set = vi.spyOn(Storage.prototype, 'setItem').mockImplementationOnce(() => { throw new Error('quota') })
    await expect(submitFieldEvent('field-A', request)).rejects.toThrow('quota'); set.mockRestore()
    expect(post).not.toHaveBeenCalled()
    post.mockResolvedValueOnce({ event: { id: 'old-server-ignored-operation' } })
    await expect(submitFieldEvent('field-A', request)).rejects.toThrow('acknowledgement')
    expect(await pendingFieldEvents('field-A')).toHaveLength(1)
  })
  it('keeps the bound when a captured receipt was compacted before retry', async () => {
    let captured: import('./fieldEventSave').PendingFieldEvent | undefined
    await submitFieldEvent('field-A', request, { onPrepared: operation => { captured = operation } })
    localStorage.clear() // Simulate receipt compaction; the UI retains its captured exact request.
    post.mockRejectedValue(new Error('offline'))
    for (let i = 0; i < 16; i++) await expect(submitFieldEvent('field-A', request)).rejects.toThrow()
    await expect(submitFieldEvent('field-A', request, { operation: captured })).rejects.toThrow('local receipt')
    expect(await pendingFieldEvents('field-A')).toHaveLength(16)
    expect(post).toHaveBeenCalledTimes(17) // first accepted operation plus the 16 uncertain requests
  })
  it('does not skip pending keys when another workflow removes an unrelated key during reads', async () => {
    localStorage.setItem('unrelated-workflow-key', 'draft')
    post.mockRejectedValue(new Error('offline'))
    for (let i = 0; i < 16; i++) await expect(submitFieldEvent('field-A', request)).rejects.toThrow()
    const original = Storage.prototype.getItem
    let removed = false
    const read = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(function (this: Storage, storageKey) {
      if (!removed && storageKey.startsWith('open-agronomy-agent.field-event-operation.v2:')) {
        removed = true; localStorage.removeItem('unrelated-workflow-key')
      }
      return original.call(this, storageKey)
    })
    expect(await pendingFieldEvents('field-A')).toHaveLength(16)
    await expect(submitFieldEvent('field-A', request)).rejects.toThrow('Recover')
    expect(post).toHaveBeenCalledTimes(16)
    read.mockRestore()
  })
  it('preserves legacy unbound bytes without adopting their payload', async () => {
    const key = 'open-agronomy-agent.field-event-operations.v1:field-A'
    localStorage.setItem(key, 'unbound private original bytes')
    expect(await pendingFieldEvents('field-A')).toEqual([])
    await submitFieldEvent('field-A', request)
    expect(localStorage.getItem(key)).toBe('unbound private original bytes')
  })
})
