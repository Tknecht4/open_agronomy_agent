import { StrictMode, Suspense, useState } from 'react'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { recoverableLazy, WorkspaceSectionBoundary } from './WorkspaceSectionBoundary'
import { checkWorkspaceConnection, WorkspaceRecoveryActions } from './WorkspaceRecovery'

const handledError = (event: ErrorEvent) => event.preventDefault()
beforeEach(() => window.addEventListener('error', handledError))
afterEach(() => { cleanup(); window.removeEventListener('error', handledError); vi.restoreAllMocks(); vi.unstubAllGlobals() })

describe('workspace failure recovery', () => {
  it('retries a rejected lazy import while preserving the composer and navigation', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    const load = vi.fn()
      .mockRejectedValueOnce(new TypeError('Importing a module script failed.'))
      .mockResolvedValue({ default: ({ name }: { name: string }) => <p>Map for {name}</p> })
    const Map = recoverableLazy(load, 'Field map')
    function Workspace() {
      const [draft, setDraft] = useState('unsent observation')
      const [tab, setTab] = useState('map')
      return <><button onClick={() => setTab(tab === 'map' ? 'data' : 'map')}>Switch tab</button>
        <textarea aria-label="Question" value={draft} onChange={event => setDraft(event.target.value)} />
        {tab === 'map' ? <Suspense fallback={<p>Loading map</p>}><Map name="North" /></Suspense> : <p>Data view</p>}</>
    }
    render(<StrictMode><Workspace /></StrictMode>)
    expect(await screen.findByRole('alert', { name: 'Field map unavailable' })).toBeVisible()
    fireEvent.change(screen.getByLabelText('Question'), { target: { value: 'keep this draft' } })
    fireEvent.click(screen.getByRole('button', { name: 'Retry field map' }))
    expect(await screen.findByText('Map for North')).toBeVisible()
    expect(load).toHaveBeenCalledTimes(2)
    expect(screen.getByLabelText('Question')).toHaveValue('keep this draft')
    fireEvent.click(screen.getByRole('button', { name: 'Switch tab' }))
    expect(screen.getByText('Data view')).toBeVisible()
  })

  it('contains render exceptions and resets when another page is selected', () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    const Broken = () => { throw new Error('Panel rendering failed') }
    function Workspace() {
      const [page, setPage] = useState('broken')
      return <><button onClick={() => setPage('working')}>Fields</button>
        <WorkspaceSectionBoundary key={page} label="This page">
          {page === 'broken' ? <Broken /> : <p>Field library</p>}
        </WorkspaceSectionBoundary></>
    }
    render(<Workspace />)
    expect(screen.getByRole('alert')).toHaveTextContent('This page is unavailable')
    fireEvent.click(screen.getByRole('button', { name: 'Fields' }))
    expect(screen.getByText('Field library')).toBeVisible()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('keeps a disconnected cached page and its drafts instead of reloading into the same failure', async () => {
    const fetcher = vi.fn().mockRejectedValue(new TypeError('Load failed'))
    vi.stubGlobal('fetch', fetcher)
    const clear = vi.spyOn(Storage.prototype, 'clear')
    render(<WorkspaceRecoveryActions />)
    fireEvent.click(screen.getByRole('button', { name: 'Check connection' }))
    expect(await screen.findByRole('status')).toHaveTextContent('This page has been kept open')
    expect(fetcher).toHaveBeenCalledWith('/api/health', expect.objectContaining({ cache: 'no-store', signal: expect.any(AbortSignal) }))
    expect(clear).not.toHaveBeenCalled()
    expect(screen.getByRole('button')).toBeEnabled()
    expect(screen.getByText(window.location.origin)).toBeVisible()
  })

  it.each([
    { ok: false, json: async () => ({ status: 'ok' }) },
    { ok: true, json: async () => ({ status: 'unavailable' }) },
    { ok: true, json: async () => { throw new SyntaxError('HTML fallback') } },
  ])('does not accept HTTP errors, unavailable runtimes or an HTML shell as a health check', async response => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response))
    await expect(checkWorkspaceConnection()).rejects.toThrow()
  })

  it('accepts a live API health receipt', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({ status: 'ok' }) }))
    await expect(checkWorkspaceConnection()).resolves.toBeUndefined()
  })

  it('requires an explicit reload choice so unsaved field setup can stay open', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({ status: 'ok' }) }))
    render(<><input aria-label="Unsaved field name" defaultValue="North field" /><WorkspaceRecoveryActions /></>)
    fireEvent.click(screen.getByRole('button', { name: 'Check connection' }))
    expect(await screen.findByRole('status')).toHaveTextContent('Reloading closes unsaved field setup')
    expect(screen.getByRole('button', { name: 'Reload workspace' })).toBeVisible()
    fireEvent.click(screen.getByRole('button', { name: 'Keep this page open' }))
    expect(screen.getByLabelText('Unsaved field name')).toHaveValue('North field')
    expect(screen.queryByRole('button', { name: 'Reload workspace' })).not.toBeInTheDocument()
  })
})
