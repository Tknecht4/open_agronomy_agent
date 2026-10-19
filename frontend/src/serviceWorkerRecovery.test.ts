import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'
import { describe, expect, it, vi } from 'vitest'

const origin = 'http://workspace.test'
const source = readFileSync('public/service-worker.js', 'utf8')
const entry = '/assets/app-test.js'
const lazyChunk = '/assets/map-test.js'
const indexHtml = `<script type="module" src="${entry}"></script>`
const cacheName = 'open-agronomy-agent-build-v3-test'
type ResponseLike = { ok: boolean; headers: { get: (name: string) => string | null }; text: () => Promise<string>; clone: () => ResponseLike }
type RequestLike = { url: string; method: string; mode: string }
const response = (body: string, ok = true, development = false): ResponseLike => ({
  ok, headers: { get: name => development && name === 'X-Open-Agronomy-Workspace' ? 'development' : null },
  text: async () => body, clone: () => response(body, ok, development),
})

function worker() {
  const data = new Map<string, Map<string, ResponseLike>>()
  const key = (request: string | RequestLike) => new URL(typeof request === 'string' ? request : request.url, origin).href
  const resources = new Map<string, string>([['/index.html', indexHtml], [entry, 'entry module'], [lazyChunk, 'map module']])
  const fetcher = vi.fn(async (request: string | RequestLike) => response(resources.get(new URL(key(request)).pathname) || 'static file'))
  const caches = {
    keys: async () => [...data.keys()],
    delete: vi.fn(async (name: string) => data.delete(name)),
    open: async (name: string) => {
      if (!data.has(name)) data.set(name, new Map())
      const contents = data.get(name)!
      return {
        match: async (request: string | RequestLike) => contents.get(key(request)),
        addAll: async (urls: string[]) => {
          const fetched = await Promise.all(urls.map(async url => [key(url), await fetcher(url)] as const))
          fetched.forEach(([url, value]) => contents.set(url, value))
        },
      }
    },
  }
  const listeners = new Map<string, (event: any) => void>()
  const skipWaiting = vi.fn().mockResolvedValue(undefined)
  const claim = vi.fn().mockResolvedValue(undefined)
  const unregister = vi.fn().mockResolvedValue(true)
  runInNewContext(source
    .replace("const BUILD_ID = 'unbuilt'", "const BUILD_ID = 'test'")
    .replace('const BUILD_ASSETS = []', `const BUILD_ASSETS = ${JSON.stringify([entry, lazyChunk])}`)
    .replace('const BUILD_SHELL_ASSETS = []', `const BUILD_SHELL_ASSETS = ${JSON.stringify([entry])}`), {
    caches, fetch: fetcher, URL,
    self: { location: new URL(origin), addEventListener: (name: string, handler: (event: any) => void) => listeners.set(name, handler), skipWaiting, clients: { claim }, registration: { unregister } },
  })
  const lifecycle = (name: string): Promise<unknown> => {
    let pending: Promise<unknown> | undefined
    listeners.get(name)!({ waitUntil: (promise: Promise<unknown>) => { pending = promise } })
    return pending!
  }
  const request = (path: string, mode = 'cors') => {
    let pending: Promise<ResponseLike> | undefined
    listeners.get('fetch')!({ request: { url: origin + path, mode, method: 'GET' }, respondWith: (promise: Promise<ResponseLike>) => { pending = promise } })
    return pending
  }
  return { data, caches, fetcher, resources, skipWaiting, claim, unregister, lifecycle, request }
}

describe('production workspace cache recovery', () => {
  it('hands a reused production origin to the explicitly marked development server', async () => {
    const sw = worker()
    await sw.lifecycle('install')
    const devHtml = '<script type="module" src="/src/main.tsx"></script>'
    sw.fetcher.mockResolvedValue(response(devHtml, true, true))
    expect(await (await sw.request('/', 'navigate'))!.text()).toBe(devHtml)
    expect(sw.unregister).toHaveBeenCalledOnce()
    expect(sw.data.has(cacheName)).toBe(true)
    expect(sw.caches.delete).not.toHaveBeenCalled()
  })

  it('opens the shell and a previously unvisited map offline from a complete build', async () => {
    const sw = worker()
    await sw.lifecycle('install')
    expect(sw.skipWaiting).toHaveBeenCalledOnce()
    sw.fetcher.mockRejectedValue(new TypeError('Server stopped'))
    expect(await (await sw.request('/', 'navigate'))!.text()).toBe(indexHtml)
    expect(await (await sw.request(lazyChunk))!.text()).toBe('map module')
  })

  it('does not activate a build if any lazy dependency fails to download', async () => {
    const sw = worker()
    sw.data.set('open-agronomy-agent-build-v3-previous', new Map())
    sw.fetcher.mockImplementation(async request => {
      if (request === lazyChunk) throw new Error('Chunk unavailable')
      return response(indexHtml)
    })
    await expect(sw.lifecycle('install')).rejects.toThrow('Chunk unavailable')
    expect(sw.skipWaiting).not.toHaveBeenCalled()
    expect(sw.data.has(cacheName)).toBe(false)
    expect(sw.data.has('open-agronomy-agent-build-v3-previous')).toBe(true)
  })

  it('rejects an index from a different deployment during installation', async () => {
    const sw = worker()
    sw.resources.set('/index.html', '<script src="/assets/different-build.js"></script>')
    await expect(sw.lifecycle('install')).rejects.toThrow('changed during download')
    expect(sw.data.has(cacheName)).toBe(false)
    expect(sw.skipWaiting).not.toHaveBeenCalled()
  })

  it('does not boot a newer online shell before that deployment has a complete cache', async () => {
    const sw = worker()
    await sw.lifecycle('install')
    sw.resources.set('/', '<script src="/assets/new-build.js"></script>')
    expect(await (await sw.request('/', 'navigate'))!.text()).toBe(indexHtml)
    sw.fetcher.mockRejectedValue(new TypeError('Offline'))
    expect(await (await sw.request('/', 'navigate'))!.text()).toBe(indexHtml)
  })

  it('keeps the installed shell usable during server errors', async () => {
    const sw = worker()
    await sw.lifecycle('install')
    sw.fetcher.mockResolvedValue(response('Service unavailable', false))
    expect(await (await sw.request('/', 'navigate'))!.text()).toBe(indexHtml)
  })

  it('never intercepts private API, export or account navigation requests', () => {
    const sw = worker()
    for (const path of ['/api/health', '/account/export', '/account', '/auth/session', '/exports/a/download', '/chat/stream', '/attachments/a']) {
      expect(sw.request(path, 'navigate'), path).toBeUndefined()
    }
    expect(sw.fetcher).not.toHaveBeenCalled()
  })

  it('retains one previous build for open tabs and leaves unrelated browser caches alone', async () => {
    const sw = worker()
    for (const name of ['another-app', 'open-agronomy-agent-shell-v2', 'open-agronomy-agent-runtime-v2', 'open-agronomy-agent-build-v3-old', 'open-agronomy-agent-build-v3-previous']) sw.data.set(name, new Map())
    await sw.lifecycle('install')
    await sw.lifecycle('activate')
    expect([...sw.data.keys()]).toEqual(['another-app', 'open-agronomy-agent-build-v3-previous', cacheName])
    expect(sw.claim).toHaveBeenCalledOnce()
  })
})
