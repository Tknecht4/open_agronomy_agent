const CACHE_NAME = 'open-agronomy-agent-shell-v2'
const RUNTIME_CACHE_NAME = 'open-agronomy-agent-runtime-v2'
const PHASE6_RUNTIME_CACHE_MAX_ENTRIES = 32
const ACTIVE_CACHE_NAMES = [CACHE_NAME, RUNTIME_CACHE_NAME]
const PRECACHE_URLS = ['/', '/index.html', '/offline.html', '/manifest.webmanifest', '/icons/agronomy-agent.svg']
const PRIVATE_API_PREFIXES = [
  '/api',
  '/admin',
  '/auth',
  '/orgs',
  '/workspaces',
  '/field-contexts',
  '/geo',
  '/threads',
  '/chat',
  '/route',
  '/retrieve',
  '/tools',
  '/attachments',
  '/messages',
  '/eval-candidates',
  '/eval-runs',
  '/change-proposals',
  '/data-sources',
  '/ingest-jobs',
  '/corpus-health',
  '/quotas',
  '/audit-events',
  '/exports',
  '/export-jobs',
  '/image-rag',
]

const isPrivateApiPath = (pathname) => PRIVATE_API_PREFIXES.some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`))

const isCacheableShellRequest = (request) => {
  const url = new URL(request.url)
  if (request.method !== 'GET') {
    return false
  }
  if (url.origin !== self.location.origin) {
    return false
  }
  if (isPrivateApiPath(url.pathname)) {
    return false
  }
  return request.mode === 'navigate' || url.pathname.startsWith('/assets/') || PRECACHE_URLS.includes(url.pathname)
}

const cachePhase6ShellIndex = async (response) => {
  const cache = await caches.open(CACHE_NAME)
  await cache.put('/index.html', response)
}

const trimPhase6RuntimeCache = async (cache) => {
  const keys = await cache.keys()
  const deleteCount = keys.length - PHASE6_RUNTIME_CACHE_MAX_ENTRIES
  if (deleteCount <= 0) {
    return
  }
  for (let index = 0; index < deleteCount; index += 1) {
    await cache.delete(keys[index])
  }
}

const cachePhase6RuntimeAsset = async (request, response) => {
  const cache = await caches.open(RUNTIME_CACHE_NAME)
  await cache.put(request, response)
  await trimPhase6RuntimeCache(cache)
}

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(PRECACHE_URLS)))
  self.skipWaiting()
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((key) => !ACTIVE_CACHE_NAMES.includes(key)).map((key) => caches.delete(key))))
      .then(() => self.clients.claim()),
  )
})

self.addEventListener('fetch', (event) => {
  const { request } = event
  if (!isCacheableShellRequest(request)) {
    return
  }

  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request)
        .then((response) => {
          const copy = response.clone()
          event.waitUntil(cachePhase6ShellIndex(copy))
          return response
        })
        .catch(() => caches.match('/index.html').then((cached) => cached || caches.match('/offline.html'))),
    )
    return
  }

  event.respondWith(
    caches.match(request).then((cached) => {
      if (cached) {
        return cached
      }
      return fetch(request).then((response) => {
        if (response.ok && response.type === 'basic') {
          const copy = response.clone()
          event.waitUntil(cachePhase6RuntimeAsset(request, copy))
        }
        return response
      })
    }),
  )
})
