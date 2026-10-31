// Keeps the responder site usable on a weak or dead connection:
// the app shell and any map tiles already seen are served from cache.
const SHELL = 'responder-shell-v1'
const TILES = 'responder-tiles-v1'

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(SHELL).then((c) => c.addAll(['/responder/', '/responder/index.html'])))
  self.skipWaiting()
})
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()))

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url)
  if (e.request.method !== 'GET') return
  if (url.hostname.endsWith('tile.openstreetmap.org')) {
    // map tiles: cache first, then network
    e.respondWith(caches.open(TILES).then(async (c) => {
      const hit = await c.match(e.request)
      if (hit) return hit
      const res = await fetch(e.request)
      if (res.ok) c.put(e.request, res.clone())
      return res
    }))
    return
  }
  if (url.pathname.startsWith('/responder/')) {
    // app shell: network first, cache as fallback
    e.respondWith(fetch(e.request).then((res) => {
      const copy = res.clone()
      caches.open(SHELL).then((c) => c.put(e.request, copy))
      return res
    }).catch(() => caches.match(e.request).then((r) => r || caches.match('/responder/index.html'))))
  }
})
