// API client for the responder site, with an offline queue:
// status changes, locations and road reports made without signal are kept
// on the phone and sent, in order, as soon as the connection returns.

const TOKEN_KEY = 'responder_token'
const UNIT_KEY = 'responder_unit'
const QUEUE_KEY = 'responder_queue'

const read = (k, fallback) => {
  try { return JSON.parse(localStorage.getItem(k)) ?? fallback } catch { return fallback }
}
const write = (k, v) => {
  try { localStorage.setItem(k, JSON.stringify(v)) } catch { /* storage full or blocked */ }
}

export const session = {
  get token() { return read(TOKEN_KEY, null) },
  get unit() { return read(UNIT_KEY, null) },
  save(token, unit) { write(TOKEN_KEY, token); write(UNIT_KEY, unit) },
  clear() { try { localStorage.removeItem(TOKEN_KEY); localStorage.removeItem(UNIT_KEY) } catch { /* ignore */ } },
}

async function call(path, { method = 'GET', body } = {}) {
  const headers = { 'Content-Type': 'application/json' }
  if (session.token) headers.Authorization = `Bearer ${session.token}`
  const res = await fetch(path, { method, headers, body: body ? JSON.stringify(body) : undefined })
  const data = await res.json().catch(() => ({}))
  if (res.status === 401) { session.clear(); throw Object.assign(new Error(data.detail || 'Log in again'), { auth: true }) }
  if (!res.ok) throw new Error(data.detail || `Request failed (${res.status})`)
  return data
}

export const queue = {
  items: () => read(QUEUE_KEY, []),
  add(item) { write(QUEUE_KEY, [...read(QUEUE_KEY, []), { ...item, at: Date.now() }]) },
  async flush() {
    let items = read(QUEUE_KEY, [])
    while (items.length) {
      const [first, ...rest] = items
      try {
        await call(first.path, { method: 'POST', body: first.body })
      } catch (e) {
        if (!navigator.onLine || e.message.startsWith('Failed to fetch') || e instanceof TypeError) return items.length
        // server refused it (e.g. task already closed): drop it so the queue moves on
      }
      items = rest
      write(QUEUE_KEY, items)
    }
    return 0
  },
}

// POST that survives a dead connection
async function send(path, body) {
  try {
    return await call(path, { method: 'POST', body })
  } catch (e) {
    if (e.auth) throw e
    if (e instanceof TypeError || !navigator.onLine) {
      queue.add({ path, body })
      return { queued: true }
    }
    throw e
  }
}

export const api = {
  login: (code, pin) => call('/api/v1/units/login', { method: 'POST', body: { code, pin } }),
  task: () => call('/api/v1/units/me/task'),
  location: (lat, lon, acc) => send('/api/v1/units/me/location', { lat, lon, acc }),
  status: (status) => send('/api/v1/units/me/status', { status }),
  hazard: (lat, lon, note) => send('/api/v1/units/me/hazard', { lat, lon, note, radius_m: 60 }),
  reroute: (lat, lon) => call('/api/v1/units/me/reroute', { method: 'POST', body: { lat, lon } }),
}

export function liveUpdates(onEvent, onState) {
  let socket
  let stopped = false
  const open = () => {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    socket = new WebSocket(`${proto}://${location.host}/ws`)
    socket.onopen = () => onState(true)
    socket.onmessage = (m) => { try { onEvent(JSON.parse(m.data)) } catch { /* ignore */ } }
    socket.onclose = () => { onState(false); if (!stopped) setTimeout(open, 3000) }
  }
  open()
  return () => { stopped = true; socket && socket.close() }
}
