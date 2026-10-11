import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { FieldEventRecoveryPanel } from './FieldSyncPanel'
import { pendingFieldEvents, submitFieldEvent } from './fieldEventSave'
import { ApiError } from './api'
import { testLocks, testReceipt, testScope } from './fieldEventTestSupport'
const post = vi.hoisted(() => vi.fn())
const get = vi.hoisted(() => vi.fn())
vi.mock('./api', async original => ({ ...await original<typeof import('./api')>(), apiPost: post, apiGet: get }))
const request = { event_type: 'sample', payload: { summary: 'Soil pH: 7 · sample S-1' }, provenance: {} }
describe('scoped record recovery', () => {
  beforeEach(() => {
    localStorage.clear(); post.mockReset(); get.mockReset()
    Object.defineProperty(navigator, 'locks', { configurable: true, value: testLocks() })
    get.mockImplementation(async (path: string) => testScope(path.split('/')[4]))
    post.mockImplementation(async (path, body) => testReceipt(path, body))
  })
  it('recovers an interrupted request with its exact identity', async () => {
    post.mockRejectedValueOnce(new Error('lost'))
    await expect(submitFieldEvent('field-A', request)).rejects.toThrow()
    const body = post.mock.calls[0][1]
    const onRecovered = vi.fn()
    render(<FieldEventRecoveryPanel fieldContextId="field-A" onRecovered={onRecovered} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Retry saved record' }))
    expect(await screen.findByText('Saved record confirmed.')).toBeInTheDocument()
    expect(post.mock.calls[1][1]).toEqual(body)
    expect(await pendingFieldEvents('field-A')).toEqual([])
    expect(onRecovered).toHaveBeenCalledOnce()
  })
  it('offers explicit rejected resolution, never an uncertain discard', async () => {
    post.mockRejectedValueOnce(new ApiError(422, 'invalid'))
    await expect(submitFieldEvent('field-A', request)).rejects.toThrow()
    render(<FieldEventRecoveryPanel fieldContextId="field-A" onRecovered={vi.fn()} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Resolve rejected request' }))
    expect(await screen.findByText(/Rejected request resolved/)).toBeInTheDocument()
    expect(await pendingFieldEvents('field-A')).toEqual([])
    expect(post).toHaveBeenCalledOnce()
  })
  it('refreshes on cross-tab storage changes and hides another actor queue', async () => {
    post.mockRejectedValueOnce(new Error('lost'))
    await expect(submitFieldEvent('field-A', request)).rejects.toThrow()
    render(<FieldEventRecoveryPanel fieldContextId="field-A" onRecovered={vi.fn()} />)
    await screen.findByText('Soil pH: 7 · sample S-1')
    get.mockResolvedValue(testScope('field-A', '10000000-0000-4000-8000-000000000003'))
    fireEvent(window, new StorageEvent('storage'))
    await waitFor(() => expect(screen.queryByText('Soil pH: 7 · sample S-1')).not.toBeInTheDocument())
    expect(post).toHaveBeenCalledOnce()
  })
  it('hides a cached rejection after account changes during explicit resolution', async () => {
    post.mockRejectedValueOnce(new ApiError(422, 'invalid'))
    await expect(submitFieldEvent('field-A', request)).rejects.toThrow()
    render(<FieldEventRecoveryPanel fieldContextId="field-A" onRecovered={vi.fn()} />)
    await screen.findByRole('button', { name: 'Resolve rejected request' })
    get.mockResolvedValue(testScope('field-A', '10000000-0000-4000-8000-000000000003'))
    fireEvent.click(screen.getByRole('button', { name: 'Resolve rejected request' }))
    await screen.findByText(/signed-in account changed/)
    expect(screen.queryByText('Soil pH: 7 · sample S-1')).not.toBeInTheDocument()
    expect(post).toHaveBeenCalledOnce()
  })
  it('preserves unscoped legacy bytes and explains manual review', async () => {
    const key = 'open-agronomy-agent.field-event-operations.v1:field-A'
    localStorage.setItem(key, 'original bytes')
    render(<FieldEventRecoveryPanel fieldContextId="field-A" onRecovered={vi.fn()} />)
    expect(await screen.findByRole('status')).toHaveTextContent('Older unscoped requests are preserved')
    expect(localStorage.getItem(key)).toBe('original bytes')
  })
})
