// Vite fills these values from the completed bundle. Never install this raw template.
const BUILD_ID = 'unbuilt'
const BUILD_ASSETS = []
const BUILD_SHELL_ASSETS = []
const CACHE_PREFIX = 'open-agronomy-agent-build-v3-'
const CACHE_NAME = `${CACHE_PREFIX}${BUILD_ID}`
const PRECACHE_URLS = ['/index.html', '/offline.html', '/manifest.webmanifest', '/icons/agronomy-agent.svg', ...BUILD_ASSETS]
const PRIVATE_API_PREFIXES = [
  '/api',
  '/admin',
  '/auth',
  '/account',
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
  return request.method === 'GET' && url.origin === self.location.origin && !isPrivateApiPath(url.pathname)
    && (url.pathname === '/' || PRECACHE_URLS.includes(url.pathname) || url.pathname.startsWith('/assets/'))
}

self.addEventListener('install', (event) => {
  event.waitUntil((async () => {
    if (BUILD_ID === 'unbuilt' || !BUILD_SHELL_ASSETS.length) throw new Error('A production workspace build is required.')
    const cache = await caches.open(CACHE_NAME)
    try {
      // addAll publishes atomically: a failed lazy chunk cannot leave a partial build active.
      await cache.addAll(PRECACHE_URLS)
      const shell = await cache.match('/index.html')
      const html = shell && await shell.text()
      if (!html || !BUILD_SHELL_ASSETS.every(asset => html.includes(asset))) {
        throw new Error('The workspace changed during download. Retry the update.')
      }
    } catch (error) {
      await caches.delete(CACHE_NAME)
      throw error
    }
    await self.skipWaiting()
  })())
})

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys()
    // Keep the immediately previous complete build for tabs still using its hashed assets.
    const previous = keys.filter(key => key.startsWith(CACHE_PREFIX) && key !== CACHE_NAME).slice(-1)
    await Promise.all(keys.filter(key =>
      (key.startsWith(CACHE_PREFIX) && key !== CACHE_NAME && !previous.includes(key))
      || key === 'open-agronomy-agent-shell-v2' || key === 'open-agronomy-agent-runtime-v2',
    ).map(key => caches.delete(key)))
    await self.clients.claim()
  })())
})

const cachedAsset = async (request) => {
  const keys = [CACHE_NAME, ...(await caches.keys()).filter(key => key.startsWith(CACHE_PREFIX) && key !== CACHE_NAME).reverse()]
  for (const key of keys) {
    const cached = await (await caches.open(key)).match(request)
    if (cached) return cached
  }
}

self.addEventListener('fetch', (event) => {
  const { request } = event
  if (!isCacheableShellRequest(request)) return
  if (request.mode === 'navigate') {
    const installedShell = async () => {
      const cache = await caches.open(CACHE_NAME)
      return (await cache.match('/index.html')) || cache.match('/offline.html')
    }
    event.respondWith(fetch(request).then(async response => {
      if (!response.ok) return installedShell()
      // The local launcher can reuse a production origin for Vite development.
      // Give the explicitly marked live dev server control without clearing data.
      if (response.headers.get('X-Open-Agronomy-Workspace') === 'development') {
        await self.registration.unregister()
        return response
      }
      const html = await response.clone().text()
      // A newer deployment is usable only after its complete worker installs.
      // Until activation, keep the index paired with this worker's dependencies.
      return BUILD_SHELL_ASSETS.every(asset => html.includes(asset)) ? response : installedShell()
    }).catch(installedShell))
    return
  }
  event.respondWith(cachedAsset(request).then(cached => cached || fetch(request)))
})
