import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { MapContainer, TileLayer, CircleMarker, Circle, Polyline, Tooltip, useMap, useMapEvents } from 'react-leaflet'
import { api, liveUpdates, queue, session } from './api.js'

const DEFAULT_CENTER = [30.316496, 78.032188] // Dehradun
const NEXT = { dispatched: ['en_route', 'On the way'], en_route: ['on_site', 'Reached'], on_site: ['resolved', 'Done'] }
const STATUS_TEXT = { dispatched: 'New task', en_route: 'On the way', on_site: 'On site' }
const OFF_ROUTE_M = 150

// ---------- helpers ----------
function meters(a, b) {
  const R = 6371000, toR = (d) => (d * Math.PI) / 180
  const dLat = toR(b[0] - a[0]), dLon = toR(b[1] - a[1])
  const x = Math.sin(dLat / 2) ** 2 + Math.cos(toR(a[0])) * Math.cos(toR(b[0])) * Math.sin(dLon / 2) ** 2
  return 2 * R * Math.asin(Math.sqrt(x))
}
function densify(coords, step = 25) {
  const out = []
  for (let i = 0; i < coords.length - 1; i++) {
    const a = coords[i], b = coords[i + 1]
    const n = Math.max(1, Math.round(meters(a, b) / step))
    for (let k = 0; k < n; k++) out.push([a[0] + ((b[0] - a[0]) * k) / n, a[1] + ((b[1] - a[1]) * k) / n])
  }
  if (coords.length) out.push(coords[coords.length - 1])
  return out
}
function distToRoute(p, route) {
  if (!route?.length) return 0
  return Math.min(...densify(route, 30).map((q) => meters(p, q)))
}
function beep(pattern = [880, 660, 880]) {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)()
    pattern.forEach((f, i) => {
      const o = ctx.createOscillator(), g = ctx.createGain()
      o.frequency.value = f; o.connect(g); g.connect(ctx.destination)
      g.gain.setValueAtTime(0.25, ctx.currentTime + i * 0.22)
      o.start(ctx.currentTime + i * 0.22); o.stop(ctx.currentTime + i * 0.22 + 0.18)
    })
  } catch { /* audio blocked */ }
}
function notify(title, body) {
  try { navigator.vibrate?.([300, 120, 300, 120, 600]) } catch { /* ignore */ }
  beep()
  try {
    if ('Notification' in window && Notification.permission === 'granted') new Notification(title, { body, icon: '/responder/icon.svg' })
  } catch { /* ignore */ }
}
function ago(iso) {
  const m = Math.max(0, Math.round((Date.now() - Date.parse(iso)) / 60000))
  return m < 1 ? 'just now' : m < 60 ? `${m} min ago` : `${Math.floor(m / 60)} h ago`
}

// ---------- map helpers ----------
function FitRoute({ route, version }) {
  const map = useMap()
  useEffect(() => {
    const fit = () => { map.invalidateSize(); if (route?.length > 1) map.fitBounds(route, { padding: [40, 40] }) }
    fit()
    const t = setTimeout(fit, 350) // after banners/sheets change the map's size
    return () => clearTimeout(t)
  }, [version]) // eslint-disable-line react-hooks/exhaustive-deps
  return null
}
function TapToReport({ active, onTap }) {
  useMapEvents({ click: (e) => active && onTap([e.latlng.lat, e.latlng.lng]) })
  return null
}

// ---------- login ----------
function Login({ onDone }) {
  const [code, setCode] = useState('')
  const [pin, setPin] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const submit = async (e) => {
    e.preventDefault()
    setBusy(true); setErr('')
    try {
      const r = await api.login(code, pin)
      session.save(r.token, r.unit)
      try { if ('Notification' in window && Notification.permission === 'default') await Notification.requestPermission() } catch { /* ignore */ }
      beep([660])
      onDone()
    } catch (e2) { setErr(e2.message) } finally { setBusy(false) }
  }
  return (
    <main className="login">
      <div className="login-card">
        <img src="/responder/icon.svg" alt="" width="56" height="56" />
        <h1>Rescue Responder</h1>
        <p className="muted">For ambulance, fire, police, SDRF and boat teams</p>
        <form onSubmit={submit}>
          <label htmlFor="code">Unit code</label>
          <input id="code" value={code} onChange={(e) => setCode(e.target.value)} placeholder="e.g. AMB1" autoCapitalize="characters" required />
          <label htmlFor="pin">PIN</label>
          <input id="pin" value={pin} onChange={(e) => setPin(e.target.value)} inputMode="numeric" type="password" required />
          {err && <p className="err" role="alert">{err}</p>}
          <button className="big primary" disabled={busy}>{busy ? 'Signing in…' : 'Start shift'}</button>
        </form>
      </div>
    </main>
  )
}

// ---------- main screen ----------
function Duty({ onLogout }) {
  const [data, setData] = useState(null)
  const [live, setLive] = useState(false)
  const [online, setOnline] = useState(navigator.onLine)
  const [pos, setPos] = useState(null)
  const [serverPos, setServerPos] = useState(null)
  const [gpsState, setGpsState] = useState('waiting')
  const [banner, setBanner] = useState(null)
  const [overlay, setOverlay] = useState(null)
  const [reportMode, setReportMode] = useState(false)
  const [demo, setDemo] = useState(false)
  const [pending, setPending] = useState(queue.items().length)
  const [busy, setBusy] = useState(false)
  const unit = session.unit
  const lastSent = useRef({ t: 0, p: null })
  const offCount = useRef(0)
  const posRef = useRef(null)
  const lastVersion = useRef(null)

  const task = data?.task
  const route = task?.route || []

  const load = useCallback(async () => {
    try {
      const d = await api.task()
      setData(d)
      if (d.task && lastVersion.current === null) lastVersion.current = d.task.route_version
    } catch (e) {
      if (e.auth) onLogout()
    }
  }, [onLogout])

  // first load + live events
  useEffect(() => {
    load()
    return liveUpdates((msg) => {
      const d = msg.data || {}
      if ((msg.event === 'task_assigned') && d.unit_id === unit.id) {
        notify('New rescue task', `ETA ${d.eta_min ?? '?'} min`)
        setOverlay({ kind: 'task', eta: d.eta_min, dist: d.distance_m })
        load()
      } else if (msg.event === 'reroute' && d.unit_id === unit.id) {
        notify('Route changed', d.reason || 'New route')
        setBanner({ kind: d.no_road_route ? 'danger' : 'warn', text: d.no_road_route ? 'No road route left. Ask control room for a boat or drone.' : `Route changed: ${d.reason}. New ETA ${d.eta_min} min.` })
        load()
      } else if (msg.event === 'route_alert' && d.unit_id === unit.id) {
        notify(d.kind === 'divert' ? 'Person needing help on your way' : 'Route Watch', d.text)
        if (d.kind !== 'divert') setBanner({ kind: d.status === 'pending' ? 'danger' : 'warn', text: d.text })
        load()
      } else if (msg.event === 'alert') {
        const near = !posRef.current || meters(posRef.current, [d.lat, d.lon]) <= d.radius_m
        if (near) { notify('Control room alert', d.text); setBanner({ kind: 'info', text: `Alert: ${d.text}` }) }
      } else if (msg.event === 'unit_moved' && d.unit_id === unit.id && !posRef.current) {
        setServerPos([d.lat, d.lon])
      } else if (msg.event === 'assignment_status' && d.unit_id === unit.id && d.status === 'cancelled') {
        notify('Task cancelled', d.text || 'Control room cancelled this task')
        setBanner({ kind: 'warn', text: d.text || 'Control room cancelled this task.' })
        load()
      } else if (msg.event === 'assignment_status' && d.unit_id === unit.id && d.status === 'completed' && d.by !== unit.name) {
        notify('Task closed', `Control room marked it complete${d.by ? ` (${d.by})` : ''}`)
        setBanner({ kind: 'info', text: `Control room marked this task complete${d.by ? ` (${d.by})` : ''}. You are free for new tasks.` })
        load()
      } else if (['hazard', 'changed', 'assignment_status'].includes(msg.event)) {
        load()
      }
    }, setLive)
  }, [load, unit.id])

  // connection + offline queue
  useEffect(() => {
    const up = async () => { setOnline(true); setPending(await queue.flush()); load() }
    const down = () => setOnline(false)
    window.addEventListener('online', up); window.addEventListener('offline', down)
    const t = setInterval(async () => { if (navigator.onLine && queue.items().length) setPending(await queue.flush()) }, 10000)
    return () => { window.removeEventListener('online', up); window.removeEventListener('offline', down); clearInterval(t) }
  }, [load])

  // share position: real GPS, or demo drive along the route
  const report = useCallback(async (p, acc, force = false) => {
    posRef.current = p
    setPos(p)
    const last = lastSent.current
    if (force || !last.p || Date.now() - last.t > 15000 || meters(last.p, p) > 30) {
      lastSent.current = { t: Date.now(), p }
      await api.location(p[0], p[1], acc)
      setPending(queue.items().length)
    }
  }, [])

  useEffect(() => {
    if (demo || !('geolocation' in navigator)) return
    const id = navigator.geolocation.watchPosition(
      (g) => { setGpsState(`GPS ±${Math.round(g.coords.accuracy)} m`); report([g.coords.latitude, g.coords.longitude], g.coords.accuracy) },
      () => setGpsState('GPS off'),
      { enableHighAccuracy: true, maximumAge: 5000, timeout: 20000 },
    )
    return () => navigator.geolocation.clearWatch(id)
  }, [demo, report])

  const demoPath = useMemo(() => densify(route, 40), [task?.route_version, task?.id]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!demo || demoPath.length < 2) return
    setGpsState('Demo drive')
    let i = 0
    if (posRef.current) {
      let best = Infinity
      demoPath.forEach((q, k) => { const d = meters(posRef.current, q); if (d < best) { best = d; i = k } })
    }
    const t = setInterval(() => {
      i = Math.min(i + 1, demoPath.length - 1)
      report(demoPath[i], 5, true)
      if (i === demoPath.length - 1) setDemo(false)
    }, 1200)
    return () => clearInterval(t)
  }, [demo, demoPath, report])

  // off-route: ask for a fresh route automatically (like a delivery app)
  useEffect(() => {
    if (!pos || !task || !['dispatched', 'en_route'].includes(task.status) || demo) return
    if (distToRoute(pos, route) > OFF_ROUTE_M) {
      offCount.current += 1
      if (offCount.current >= 2 && online) {
        offCount.current = 0
        api.reroute(pos[0], pos[1]).then(load).catch(() => {})
      }
    } else offCount.current = 0
  }, [pos]) // eslint-disable-line react-hooks/exhaustive-deps

  const act = async (fn, okText) => {
    setBusy(true)
    try {
      const r = await fn()
      if (r?.queued) setBanner({ kind: 'info', text: 'No signal: saved on this phone, will send automatically.' })
      else if (okText) setBanner({ kind: 'ok', text: okText })
      setPending(queue.items().length)
      await load()
    } catch (e) {
      if (e.auth) onLogout(); else setBanner({ kind: 'danger', text: e.message })
    } finally { setBusy(false) }
  }

  const [spot, setSpot] = useState(null)
  const reportAt = (p) => { setReportMode(false); setSpot(p) }
  const sendHazard = (note) => {
    const p = spot
    setSpot(null)
    act(() => api.hazard(p[0], p[1], note), 'Blocked road sent. Routes will avoid it.')
  }

  const inc = task?.incident
  const photos = (inc?.reports || []).map((r) => r.photo).filter(Boolean)
  if (inc?.photo && !photos.includes(inc.photo)) photos.unshift(inc.photo)
  const me = pos || serverPos || (data?.unit ? [data.unit.lat, data.unit.lon] : null)
  const center = me || (inc ? [inc.lat, inc.lon] : DEFAULT_CENTER)

  return (
    <div className="duty">
      <header className="bar">
        <div>
          <div className="unit">{unit.name}</div>
          <div className="chips">
            <span className={`chip ${online && live ? 'ok' : 'bad'}`}>{online ? (live ? 'Live' : 'Connecting…') : 'No signal'}</span>
            <span className="chip">{gpsState}</span>
            {pending > 0 && <span className="chip warn">{pending} waiting to send</span>}
          </div>
        </div>
        <button className="ghost" onClick={onLogout}>End shift</button>
      </header>

      {banner && (
        <div className={`banner ${banner.kind}`} role="alert" onClick={() => setBanner(null)}>
          {banner.text}<span className="x" aria-hidden="true">×</span>
        </div>
      )}

      <section className="mapbox" aria-label="Map">
        <MapContainer center={center} zoom={15} className="map" zoomControl={false}>
          <TileLayer attribution="Tiles &copy; Esri, HERE, Garmin, &copy; OpenStreetMap contributors" url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}" maxNativeZoom={19} maxZoom={20} />
          <FitRoute route={route} version={`${task?.id}-${task?.route_version}`} />
          <TapToReport active={reportMode} onTap={reportAt} />
          {(data?.hazards || []).map((h) => (
            <Circle key={`h${h.id}`} center={[h.lat, h.lon]} radius={h.radius_m} pathOptions={{ color: '#e5484d', fillColor: '#e5484d', fillOpacity: 0.3, weight: 2 }}>
              <Tooltip>Blocked: {h.note || h.kind}</Tooltip>
            </Circle>
          ))}
          {route.length > 1 && <Polyline positions={route} pathOptions={{ color: task?.reroute_reason ? '#f5a524' : '#3e8ed0', weight: 7, opacity: 0.9 }} />}
          {inc && (
            <CircleMarker center={[inc.lat, inc.lon]} radius={12} pathOptions={{ color: '#fff', weight: 3, fillColor: '#e5484d', fillOpacity: 1 }}>
              <Tooltip permanent direction="top">Help needed</Tooltip>
            </CircleMarker>
          )}
          {me && <CircleMarker center={me} radius={9} pathOptions={{ color: '#fff', weight: 3, fillColor: '#3e8ed0', fillOpacity: 1 }}><Tooltip>You</Tooltip></CircleMarker>}
        </MapContainer>
        {reportMode && <div className="tap-hint">Tap the blocked spot on the map</div>}
      </section>

      <section className="sheet">
        {!task && (
          <div className="idle">
            <h2>Standing by</h2>
            <p className="muted">You will get an alert with sound and vibration when the control room assigns you a task. Keep this page open.</p>
          </div>
        )}
        {task && inc && (
          <>
            <div className="task-head">
              <span className="sev" data-sev={inc.severity}>{inc.priority}</span>
              <div>
                <h2>{inc.type.charAt(0).toUpperCase() + inc.type.slice(1)} · {inc.people} {inc.people === 1 ? 'person' : 'people'}</h2>
                <div className="muted">{STATUS_TEXT[task.status] || task.status} · reported {ago(inc.first_report_at)}</div>
              </div>
            </div>
            <div className="eta">
              <div><strong>{task.eta_min ?? '–'}</strong><span>min</span></div>
              <div><strong>{task.distance_m != null ? (task.distance_m / 1000).toFixed(1) : '–'}</strong><span>km</span></div>
              <div className="src">{task.route_source}</div>
            </div>
            {task.reroute_reason && <p className="reroute">↻ {task.reroute_reason}</p>}
            {(data?.route_alerts || []).filter((x) => x.kind !== 'divert' && (Date.now() - Date.parse(x.created_at)) < 30 * 60 * 1000).slice(0, 2).map((x) => (
              <div key={x.id} className="route-alert">
                <strong>Route Watch:</strong> {x.text}
                {x.photo && <a href={x.photo} target="_blank" rel="noreferrer"><img src={x.photo} alt="Photo from the report" /></a>}
              </div>
            ))}
            <p className="summary">{inc.summary}</p>
            {photos.length > 0 && (
              <div className="photos">{photos.slice(0, 4).map((p) => <a key={p} href={p} target="_blank" rel="noreferrer"><img src={p} alt="Photo from the scene" /></a>)}</div>
            )}
            <ul className="msgs">
              {inc.reports.slice(-3).reverse().map((r, i) => r.message && <li key={i}><span className="muted">{ago(r.reported_at)}{r.lang ? ` · ${r.lang}` : ''}</span> {r.message}</li>)}
            </ul>
            {NEXT[task.status] && (
              <button className="big primary" disabled={busy} onClick={() => act(() => api.status(NEXT[task.status][0]), `Marked ${NEXT[task.status][1].toLowerCase()}`)}>
                {NEXT[task.status][1]}
              </button>
            )}
            <div className="row">
              <button className="big" disabled={busy} onClick={() => setReportMode((m) => !m)}>{reportMode ? 'Cancel' : '⛔ Road blocked'}</button>
              <button className="big" disabled={busy || !me} onClick={() => act(() => api.reroute(me[0], me[1]), 'New route from your position')}>↻ New route</button>
            </div>
            <div className="row small">
              <a className="ghost link" href={`https://www.google.com/maps/dir/?api=1&destination=${inc.lat},${inc.lon}`} target="_blank" rel="noreferrer">Open in Google Maps</a>
              <button className="ghost" onClick={() => setDemo((d) => !d)}>{demo ? 'Stop demo drive' : 'Demo drive'}</button>
            </div>
          </>
        )}
      </section>

      {spot && (
        <div className="overlay" role="dialog" aria-modal="true" aria-label="What is blocking the road?">
          <div className="overlay-card">
            <h2>What is blocking the road?</h2>
            <div className="choices">
              {['Flooded road', 'Bridge broken', 'Tree down', 'Landslide / debris', 'Fire', 'Crowd / jam'].map((n) => (
                <button key={n} className="big" onClick={() => sendHazard(n)}>{n}</button>
              ))}
            </div>
            <button className="ghost" onClick={() => setSpot(null)}>Cancel</button>
          </div>
        </div>
      )}

      {overlay && (
        <div className="overlay" role="dialog" aria-modal="true">
          <div className="overlay-card">
            <div className="pulse" aria-hidden="true" />
            <h2>New rescue task</h2>
            {inc && <p>{inc.type} · {inc.people} people · priority {inc.priority}</p>}
            <p className="muted">ETA {overlay.eta ?? '–'} min · {overlay.dist != null ? (overlay.dist / 1000).toFixed(1) : '–'} km</p>
            <button className="big primary" onClick={() => setOverlay(null)}>Show route</button>
          </div>
        </div>
      )}
    </div>
  )
}

export default function App() {
  const [loggedIn, setLoggedIn] = useState(Boolean(session.token))
  const logout = useCallback(() => { session.clear(); setLoggedIn(false) }, [])
  return loggedIn ? <Duty onLogout={logout} /> : <Login onDone={() => setLoggedIn(true)} />
}
