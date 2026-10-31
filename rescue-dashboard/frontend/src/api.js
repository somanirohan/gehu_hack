// Small wrapper around the backend API. All paths are relative, so the same
// build works behind the Vite dev proxy and when FastAPI serves the dist folder.
async function call(path, options = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  const body = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(body.detail || `Request failed (${res.status})`)
  return body
}

export const api = {
  incidents: () => call('/api/incidents'),
  incident: (id) => call(`/api/incidents/${id}`),
  responders: () => call('/api/responders'),
  stats: () => call('/api/stats'),
  log: () => call('/api/log?limit=60'),
  verify: () => call('/api/log/verify'),
  approve: (id, officer, responder_id) =>
    call(`/api/incidents/${id}/approve`, { method: 'POST', body: JSON.stringify({ officer, responder_id }) }),
  hold: (id, officer, reason) =>
    call(`/api/incidents/${id}/hold`, { method: 'POST', body: JSON.stringify({ officer, reason }) }),
  resuggest: (id) => call(`/api/incidents/${id}/suggest`, { method: 'POST' }),
  places: () => call('/api/v1/places'),
  shelters: () => call('/api/v1/shelters'),
  syncStatus: () => call('/api/v1/bitchat/sync-status'),
  status: (id, status, actor) =>
    call(`/api/incidents/${id}/status`, { method: 'POST', body: JSON.stringify({ status, actor }) }),
}

// Opens the live-update socket and reconnects if it drops.
export function liveUpdates(onChange, onState) {
  let socket
  let stopped = false
  const open = () => {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    socket = new WebSocket(`${proto}://${location.host}/ws`)
    socket.onopen = () => onState(true)
    socket.onmessage = (m) => {
      let msg = null
      try { msg = JSON.parse(m.data) } catch { /* plain ping */ }
      onChange(msg)
    }
    socket.onclose = () => {
      onState(false)
      if (!stopped) setTimeout(open, 2000)
    }
  }
  open()
  return () => { stopped = true; socket && socket.close() }
}
