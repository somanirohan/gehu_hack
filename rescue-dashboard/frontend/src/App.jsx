import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  MapContainer,
  TileLayer,
  CircleMarker,
  Tooltip,
  Polyline,
  useMap,
} from 'react-leaflet'
import { api, liveUpdates } from './api.js'

import LiveLayers, { liveApi } from './LiveLayers'
import FeedPanel from './FeedPanel'
import CityLayers from './CityLayers'
import PlannerPanel from './PlannerPanel'
import RouteAlerts from './RouteAlerts'

// Dehradun. Replaced by /api/v1/places once it loads (same value by default).
const CENTER = [30.316496, 78.032188]
const CENTER_ZOOM = 12

function beep() {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)()
    const o = ctx.createOscillator()
    const g = ctx.createGain()
    o.frequency.value = 880
    g.gain.setValueAtTime(0.15, ctx.currentTime)
    g.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.4)
    o.connect(g); g.connect(ctx.destination)
    o.start(); o.stop(ctx.currentTime + 0.4)
  } catch { /* sound is optional */ }
}

function syncText(sync) {
  const last = sync?.last?.[0]
  if (!last) return 'No phone has synced yet'
  const m = Math.max(0, Math.round((Date.now() - Date.parse(last.received_at)) / 60000))
  return `Phones last synced ${m < 1 ? 'just now' : `${m} min ago`} · ${sync.items_received} items total`
}

// Responder kinds containing these terms are treated as aerial units.
// All other responders use road routing.
function isDroneResponder(responder) {
  const description = `${responder?.kind || ''} ${responder?.name || ''}`.toLowerCase()
  return /drone|uav|aerial|air unit|quadcopter|helicopter/.test(description)
}

function distanceMeters(a, b) {
  const radians = (degrees) => (degrees * Math.PI) / 180
  const dLat = radians(b[0] - a[0])
  const dLon = radians(b[1] - a[1])
  const lat1 = radians(a[0])
  const lat2 = radians(b[0])
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon / 2) ** 2
  return 6371000 * 2 * Math.atan2(Math.sqrt(h), Math.sqrt(1 - h))
}

// Interpolate along a route by distance so movement speed is not tied to
// how many coordinates the routing service returns.
function pointAlongRoute(points, progress) {
  if (!points?.length) return null
  if (points.length === 1 || progress <= 0) return points[0]
  if (progress >= 1) return points[points.length - 1]

  const segmentLengths = []
  let totalLength = 0
  for (let index = 1; index < points.length; index += 1) {
    const length = distanceMeters(points[index - 1], points[index])
    segmentLengths.push(length)
    totalLength += length
  }

  if (!totalLength) return points[0]

  let remaining = totalLength * progress
  for (let index = 0; index < segmentLengths.length; index += 1) {
    const segmentLength = segmentLengths[index]
    if (remaining <= segmentLength) {
      const fraction = segmentLength ? remaining / segmentLength : 0
      const start = points[index]
      const end = points[index + 1]
      return [
        start[0] + (end[0] - start[0]) * fraction,
        start[1] + (end[1] - start[1]) * fraction,
      ]
    }
    remaining -= segmentLength
  }
  return points[points.length - 1]
}

const SEVERITY_COLOR = {
  critical: '#e5484d',
  high: '#f76b15',
  medium: '#e2a336',
  low: '#3e8ed0',
}

const STATUS_LABEL = {
  new: 'New',
  suggested: 'Awaiting approval',
  dispatched: 'Dispatched',
  en_route: 'En route',
  on_site: 'On site',
  resolved: 'Resolved',
  held: 'On hold',
}

const SOURCE_LABEL = {
  mesh: 'Mesh SOS',
  camera: 'Camera AI',
  sensor: 'Sensor',
  manual: 'Manual',
  simulator: 'Simulator',
}

function ago(iso) {
  const min = Math.max(
    0,
    Math.round((Date.now() - Date.parse(iso)) / 60000),
  )

  if (min < 1) return 'just now'
  if (min < 60) return `${min} min ago`

  return `${Math.floor(min / 60)} h ${min % 60} min ago`
}

function FlyTo({ target }) {
  const map = useMap()

  useEffect(() => {
    if (target) {
      map.flyTo(
        [target.lat, target.lon],
        Math.max(map.getZoom(), 15),
        { duration: 0.6 },
      )
    }
  }, [target, map])

  return null
}

function Stats({ stats, live, verify, sync }) {
  if (!stats) return null

  const items = [
    ['Open incidents', stats.open],
    ['Awaiting approval', stats.awaiting_approval],
    ['Reports received', stats.reports],
    ['Via offline mesh', stats.mesh_reports],
    ['Duplicates merged', stats.merged_reports],
    [
      'Median time to dispatch',
      stats.median_minutes_to_dispatch == null
        ? '—'
        : `${stats.median_minutes_to_dispatch} min`,
    ],
    [
      'Units free',
      `${stats.responders_available} / ${stats.responders_total}`,
    ],
  ]

  return (
    <header className="topbar">
      <div className="brand">
        <span className="brand-mark" aria-hidden="true" />
        <div>
          <div className="brand-name">Rescue Control Room · Dehradun</div>

          <div className="brand-sub">
            <span className={`dot ${live ? 'ok' : 'off'}`} />
            {live ? 'Live' : 'Reconnecting…'}

            <span
              className={`chain ${verify?.ok === false ? 'bad' : 'good'
                }`}
            >
              {verify == null
                ? ''
                : verify.ok
                  ? `Log intact · ${verify.entries} entries`
                  : `Log tampered at #${verify.broken_at.join(', #')}`}
            </span>
            <span className={`sync ${sync?.last?.length ? 'good' : ''}`}>{syncText(sync)}</span>
          </div>
        </div>
      </div>

      <div className="stats">
        {items.map(([label, value]) => (
          <div className="stat" key={label}>
            <div className="stat-value">{value}</div>
            <div className="stat-label">{label}</div>
          </div>
        ))}
      </div>
    </header>
  )
}

function Queue({
  incidents,
  selectedId,
  onSelect,
  filter,
  setFilter,
}) {
  const shown = incidents.filter((incident) =>
    filter === 'open'
      ? incident.status !== 'resolved'
      : filter === 'approval'
        ? ['new', 'suggested'].includes(incident.status)
        : true,
  )

  return (
    <section className="panel queue">
      <div className="panel-head">
        <h2>Incidents</h2>

        <div className="seg" role="tablist">
          {[
            ['open', 'Open'],
            ['approval', 'Needs approval'],
            ['all', 'All'],
          ].map(([key, label]) => (
            <button
              key={key}
              className={filter === key ? 'on' : ''}
              onClick={() => setFilter(key)}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {shown.length === 0 && (
        <p className="empty">
          No incidents here. Reports from the mesh app, cameras
          or simulator appear automatically.
        </p>
      )}

      <ol className="queue-list">
        {shown.map((incident) => (
          <li key={incident.id}>
            <button
              className={`qitem ${selectedId === incident.id ? 'sel' : ''
                } ${incident.status === 'resolved' ? 'done' : ''}`}
              onClick={() => onSelect(incident.id)}
            >
              <span
                className="sev"
                style={{
                  background: SEVERITY_COLOR[incident.severity],
                }}
              >
                {incident.priority}
              </span>

              <span className="qbody">
                <span className="qtitle">
                  #{incident.id} {incident.type}
                  {incident.drill && <span className="pill drill">DRILL</span>}
                  {incident.verification && <span className={`pill vf vf-${incident.verification}`} title="Verifier Agent">{VERDICT_LABEL[incident.verification]}</span>}
                  {incident.ai_urgency && <span className={`pill ai u-${incident.ai_urgency}`} title="Triage Agent reading (AI suggestion)">AI · {incident.ai_urgency}</span>}

                  <span
                    className={`pill st-${incident.status}`}
                  >
                    {STATUS_LABEL[incident.status] ||
                      incident.status}
                  </span>
                </span>

                <span className="qmeta">
                  {incident.people}{' '}
                  {incident.people === 1 ? 'person' : 'people'}
                  {' · '}
                  {incident.report_count} report
                  {incident.report_count > 1 ? 's' : ''}
                  {' · '}
                  {SOURCE_LABEL[incident.source] ||
                    incident.source}
                  {' · '}
                  {ago(incident.first_report_at)}
                </span>
              </span>
            </button>
          </li>
        ))}
      </ol>
    </section>
  )
}

const VERDICT_LABEL = {
  confirmed: '✓ Confirmed',
  likely: 'Likely real',
  unverified: 'Unverified',
  possible_fake: '⚠ Possible fake',
}

// Verifier Agent verdict: evidence gathered by code, verdict by AI (or rules). Never hides an SOS.
function Verification({ v, incidentId }) {
  const [busy, setBusy] = useState(false)
  const recheck = async () => {
    setBusy(true)
    try { await fetch(`/api/v1/agents/verify/${incidentId}`, { method: 'POST' }) } finally { setBusy(false) }
  }
  if (!v) {
    return (
      <div className="vf-card">
        <div className="ai-head"><span className="ai-badge vf-badge">Verifier Agent</span>
          <button className="mini" onClick={recheck} disabled={busy}>{busy ? 'Checking…' : 'Check now'}</button></div>
        <p className="ai-note">Not checked yet.</p>
      </div>
    )
  }
  const e = v.evidence || {}
  const facts = [
    ['Reports', e.reports],
    ['Different senders', e.different_senders],
    ['Official / camera', e.official_confirmation ? 'yes' : 'no'],
    ['Other reports nearby (1 h)', e.other_incidents_within_500m_1h],
    ['Inside Dehradun area', e.inside_dehradun_area ? 'yes' : 'NO'],
    ['Test words', (e.test_words_in_text || []).join(', ') || 'none'],
    ['Spam signals', (e.spam_signals || []).length ? `${e.spam_signals.length} sender(s)` : 'none'],
  ]
  return (
    <div className={`vf-card vf-${v.verdict}`}>
      <div className="ai-head">
        <span className="ai-badge vf-badge">Verifier Agent</span>
        <button className="mini" onClick={recheck} disabled={busy}>{busy ? 'Checking…' : 'Re-check'}</button>
      </div>
      <p className="ai-summary"><span className={`pill vf vf-${v.verdict}`}>{VERDICT_LABEL[v.verdict] || v.verdict}</span> {v.reasons}</p>
      <dl className="ai-rows">
        {facts.map(([k, val]) => <div key={k}><dt>{k}</dt><dd>{String(val ?? '—')}</dd></div>)}
      </dl>
      <p className="ai-note">{v.source}. Warning only: no SOS is hidden or down-ranked.</p>
    </div>
  )
}

// Triage Agent reading for one incident. Always labelled as an AI suggestion.
function AiTriage({ t }) {
  const rows = [
    ['Urgency', t.ai_urgency],
    ['Vulnerable', t.ai_vulnerable],
    ['Injured', t.ai_injured],
    ['Needs', t.ai_needs],
    ['Landmarks', t.ai_landmarks],
    ['Language', t.ai_language],
  ].filter(([, v]) => v != null && v !== '')
  return (
    <div className="ai-card">
      <div className="ai-head">
        <span className="ai-badge">AI Triage Agent</span>
        <span className="ai-src">{t.category_source}{t.confidence != null ? ` · confidence ${Math.round(t.confidence * 100)}%` : ''}</span>
      </div>
      <p className="ai-summary">{t.ai_summary}</p>
      <dl className="ai-rows">
        {rows.map(([k, v]) => <div key={k}><dt>{k}</dt><dd className={k === 'Urgency' ? `u-${v}` : ''}>{String(v)}</dd></div>)}
      </dl>
      {t.ai_reasons && <p className="ai-why">Why: {t.ai_reasons}</p>}
      <p className="ai-note">Suggestion only. The officer decides.{t.rule_guess ? ` Word rules said: ${t.rule_guess}.` : ''}</p>
    </div>
  )
}

function Detail({
  incident,
  responders,
  officer,
  onAction,
  busy,
  onStartSimulation,
  simulation,
}) {
  const [pick, setPick] = useState('')

  useEffect(() => {
    setPick('')
  }, [incident?.id])

  if (!incident) {
    return (
      <section className="panel detail">
        <p className="empty">
          Select an incident to see its reports, suggested unit
          and dispatch reasoning.
        </p>
      </section>
    )
  }

  const suggested = responders.find(
    (responder) =>
      responder.id === incident.suggested_responder_id,
  )

  const assigned = responders.find(
    (responder) => responder.id === incident.responder_id,
  )

  const free = responders.filter(
    (responder) => responder.status === 'available',
  )

  const awaiting = ['new', 'suggested', 'held'].includes(
    incident.status,
  )

  const next = {
    dispatched: 'en_route',
    en_route: 'on_site',
    on_site: 'resolved',
  }[incident.status]

  const isSimulating =
    simulation?.incidentId === incident.id

  return (
    <section className="panel detail">
      <div className="panel-head">
        <h2>
          #{incident.id} {incident.type}
        </h2>

        <span className={`pill st-${incident.status}`}>
          {STATUS_LABEL[incident.status] || incident.status}
        </span>
      </div>

      {incident.photo && (
        <img
          className="snap"
          src={incident.photo}
          alt={`Snapshot for incident ${incident.id}`}
        />
      )}

      <p className="summary">{incident.summary}</p>

      {incident.ai_triage && <AiTriage t={incident.ai_triage} />}

      <Verification v={incident.verification} incidentId={incident.id} />

      <div className="why">
        <div className="why-label">
          Priority {incident.priority} · {incident.severity}
        </div>

        <div className="why-text">
          {incident.priority_reason}
        </div>
      </div>

      {awaiting && (
        <div className="decision">
          <div className="why-label">Suggested unit</div>

          <div className="why-text">
            {incident.suggestion_reason || 'No suggestion yet'}
          </div>

          <label className="field">
            <span>Send instead (optional)</span>

            <select
              value={pick}
              onChange={(event) => setPick(event.target.value)}
            >
              <option value="">
                {suggested
                  ? `Accept suggestion: ${suggested.name}`
                  : 'Choose a unit'}
              </option>

              {free.map((responder) => (
                <option
                  key={responder.id}
                  value={responder.id}
                >
                  {responder.name} ({responder.kind})
                </option>
              ))}
            </select>
          </label>

          <div className="actions">
            <button
              className="primary"
              disabled={busy || (!suggested && !pick)}
              onClick={() =>
                onAction(
                  'approve',
                  incident.id,
                  pick ? Number(pick) : null,
                )
              }
            >
              Approve dispatch
            </button>

            <button
              disabled={busy || incident.status === 'held'}
              onClick={() => onAction('hold', incident.id)}
            >
              Hold
            </button>

            <button
              disabled={busy}
              onClick={() => onAction('resuggest', incident.id)}
            >
              Re-check units
            </button>
          </div>

          <p className="fine">
            Signed as {officer}. Nothing is dispatched without
            your approval.
          </p>
        </div>
      )}

      {assigned && !awaiting && (
        <div className="decision">
          <div className="why-label">Assigned unit</div>

          <div className="why-text">
            {assigned.name} ({assigned.kind})
          </div>

          {incident.status === 'en_route' && (
            <div className="actions">
              <button
                className="primary"
                disabled={busy}
                onClick={() =>
                  onStartSimulation(incident.id, assigned.id)
                }
              >
                {isSimulating
                  ? 'Restart rescue simulation'
                  : 'Start rescue simulation'}
              </button>
            </div>
          )}

          {isSimulating && (
            <div className="why">
              <div className="why-label">
                Rescue simulation progress
              </div>

              <div className="why-text">
                {simulation.progress >= 1
                  ? 'Demo arrival reached. Update the incident status when appropriate.'
                  : `${Math.round(
                    simulation.progress * 100,
                  )}% of the demo route completed`}
              </div>

              <div
                style={{
                  height: 7,
                  marginTop: 10,
                  overflow: 'hidden',
                  borderRadius: 8,
                  background: '#273449',
                }}
              >
                <div
                  style={{
                    height: '100%',
                    width: `${simulation.progress * 100}%`,
                    background: '#38bdf8',
                    transition: 'width 150ms linear',
                  }}
                />
              </div>
            </div>
          )}

          {next && (
            <div className="actions">
              <button
                className="primary"
                disabled={busy}
                onClick={() =>
                  onAction('status', incident.id, next)
                }
              >
                Mark {STATUS_LABEL[next].toLowerCase()}
              </button>
            </div>
          )}
        </div>
      )}

      <h3>Reports ({incident.reports?.length || 0})</h3>

      <ul className="reports">
        {incident.reports?.map((report) => (
          <li key={report.id}>
            <div className="rhead">
              {SOURCE_LABEL[report.source] || report.source}
              {' · '}
              {ago(report.reported_at)}
              {report.lang ? ` · ${report.lang}` : ''}
            </div>

            {report.message && (
              <div className="rmsg">{report.message}</div>
            )}

            {report.via && (
              <div className="rvia">{report.via}</div>
            )}
          </li>
        ))}
      </ul>

      <h3>Decision history</h3>

      <ul className="history">
        {incident.history?.map((entry) => (
          <li key={entry.seq}>
            <span className="hseq">#{entry.seq}</span>{' '}
            {entry.action.replaceAll('_', ' ')}
            {' · '}
            {entry.actor}
            {entry.detail?.responder
              ? ` · ${entry.detail.responder}`
              : ''}
          </li>
        ))}
      </ul>
    </section>
  )
}

function LogPanel({ log }) {
  return (
    <section className="panel log">
      <div className="panel-head">
        <h2>Action log</h2>
        <span className="fine">hash-chained</span>
      </div>

      <ol className="log-list">
        {log.map((entry) => (
          <li key={entry.seq}>
            <span className="hseq">#{entry.seq}</span>

            <span className="laction">
              {entry.action.replaceAll('_', ' ')}
            </span>

            <span className="lactor">
              {entry.actor}
              {entry.incident_id
                ? ` · #${entry.incident_id}`
                : ''}
            </span>

            <code className="lhash" title={entry.hash}>
              {entry.hash.slice(0, 8)}
            </code>
          </li>
        ))}
      </ol>
    </section>
  )
}

export default function App() {
  const [incidents, setIncidents] = useState([])
  const [responders, setResponders] = useState([])
  const [stats, setStats] = useState(null)
  const [log, setLog] = useState([])
  const [verify, setVerify] = useState(null)
  const [selectedId, setSelectedId] = useState(null)
  const [selected, setSelected] = useState(null)
  const [filter, setFilter] = useState('open')
  const [live, setLive] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [officer, setOfficer] = useState('Duty Officer')

  const [simulation, setSimulation] = useState(null)

  const [tick, setTick] = useState(0)
  const [places, setPlaces] = useState({ center: null, places: [] })
  const [shelters, setShelters] = useState([])
  const [sync, setSync] = useState(null)
  const [toast, setToast] = useState(null)
  const [layers, setLayers] = useState({ risk: true, shelters: true, routes: true })
  const [pickMode, setPickMode] = useState(null)
  const [sideTab, setSideTab] = useState('incident')
  const [agentSteps, setAgentSteps] = useState([])

  const refresh = useCallback(async () => {
    try {
      const [inc, resp, st, lg, vf] = await Promise.all([
        api.incidents(),
        api.responders(),
        api.stats(),
        api.log(),
        api.verify(),
      ])

      setIncidents(inc)
      setResponders(resp)
      setStats(st)
      setLog(lg)
      setVerify(vf)
      setError('')
      api.syncStatus().then(setSync).catch(() => {})
    } catch (e) {
      setError(
        `Cannot reach the backend: ${e.message}. Check that the backend is running on port 8001.`,
      )
    }
  }, [])

  useEffect(() => {
    refresh()

    api.places().then(setPlaces).catch(() => {})
    api.shelters().then(setShelters).catch(() => {})

    const onMessage = (msg) => {
      refresh()
      setTick((t) => t + 1)
      if (msg?.event === 'feed') {
        const n = msg.data?.count || 1
        setToast((cur) => (cur?.kind === 'reroute' && Date.now() - cur.at < 5000 ? cur : { kind: 'feed', text: `${n} new report${n > 1 ? 's' : ''} from the field${msg.data?.source === 'bitchat' ? ' (mesh app)' : ''}`, at: Date.now() }))
        beep()
      }
      if (msg?.event === 'reroute') {
        setToast({ kind: 'reroute', text: 'A unit was re-routed around a blocked road', at: Date.now() })
        beep()
      }
      if (msg?.event === 'route_alert' && msg.data?.status !== 'approved' && msg.data?.kind !== 'info') {
        setToast({ kind: 'reroute', text: `Route Watch: ${msg.data.text}`, at: Date.now() })
        beep()
      }
      if (msg?.event === 'agent_step') {
        setAgentSteps((s) => (s.length && s[0].run_id !== msg.data.run_id ? [msg.data] : [...s, msg.data]))
      }
      if (msg?.event === 'shelters') api.shelters().then(setShelters).catch(() => {})
    }
    const stop = liveUpdates(onMessage, setLive)
    const timer = setInterval(() => { refresh(); setTick((t) => t + 1) }, 15000)

    return () => {
      stop()
      clearInterval(timer)
    }
  }, [refresh])

  useEffect(() => {
    if (selectedId == null) {
      setSelected(null)
      return
    }

    let cancelled = false

    api.incident(selectedId)
      .then((incident) => {
        if (!cancelled) setSelected(incident)
      })
      .catch(() => {
        if (!cancelled) setSelected(null)
      })

    return () => {
      cancelled = true
    }
  }, [selectedId, incidents])

  useEffect(() => {
    if (!toast) return undefined
    const t = setTimeout(() => setToast(null), 6000)
    return () => clearTimeout(t)
  }, [toast])

  const onPick = async ([lat, lon]) => {
    if (pickMode !== 'block') return
    setPickMode(null)
    const note = window.prompt('What is blocking the road? (e.g. landslide debris, water over road)', 'Road blocked') // eslint-disable-line no-alert
    if (note == null) return
    try {
      await liveApi.addHazard(lat, lon, note, 80, officer)
      setTick((t) => t + 1)
    } catch (e) {
      setError(e.message)
    }
  }

  const openIncident = (id) => { setSelectedId(id); setSideTab('incident') }

  // Run a frontend-only visual simulation.
  // It does not change backend incident status or audit history.
  useEffect(() => {
    if (!simulation || simulation.progress >= 1) return undefined

    const timer = setInterval(() => {
      setSimulation((current) => {
        if (!current || current.progress >= 1) return current

        return {
          ...current,
          progress: Math.min(1, current.progress + 0.01),
        }
      })
    }, 150)

    return () => clearInterval(timer)
  }, [simulation?.incidentId, simulation?.responderId, simulation?.progress >= 1])

  const startSimulation = async (incidentId, responderId) => {
    const responder = responders.find((item) => item.id === responderId)
    const incident = incidents.find((item) => item.id === incidentId)
    if (!responder || !incident) {
      setError('Cannot start simulation: responder or incident coordinates are missing.')
      return
    }

    const start = [Number(responder.lat), Number(responder.lon)]
    const end = [Number(incident.lat), Number(incident.lon)]
    if (![...start, ...end].every(Number.isFinite)) {
      setError('Cannot start simulation: responder or incident coordinates are invalid.')
      return
    }

    if (isDroneResponder(responder)) {
      setSimulation({
        incidentId,
        responderId,
        progress: 0,
        route: [start, end],
        mode: 'aerial',
        routeMessage: 'Direct aerial demo path · no obstacle avoidance',
      })
      return
    }

    // OSRM returns coordinates as [longitude, latitude]; Leaflet expects
    // [latitude, longitude]. The public OSRM demo server requires internet.
    try {
      const url =
        `https://router.project-osrm.org/route/v1/driving/` +
        `${start[1]},${start[0]};${end[1]},${end[0]}` +
        '?overview=full&geometries=geojson'
      const response = await fetch(url)
      if (!response.ok) throw new Error(`Routing service returned ${response.status}`)
      const data = await response.json()
      const coordinates = data?.routes?.[0]?.geometry?.coordinates
      if (data.code !== 'Ok' || !Array.isArray(coordinates) || coordinates.length < 2) {
        throw new Error('No road route was returned')
      }

      setSimulation({
        incidentId,
        responderId,
        progress: 0,
        route: coordinates.map(([lon, lat]) => [lat, lon]),
        mode: 'road',
        routeMessage: 'Road route · OSRM',
      })
    } catch (routingError) {
      setSimulation({
        incidentId,
        responderId,
        progress: 0,
        route: [start, end],
        mode: 'fallback',
        routeMessage: 'Road routing unavailable · showing a straight-line fallback',
      })
    }
  }

  const onAction = async (kind, id, arg) => {
    setBusy(true)

    try {
      if (kind === 'approve') {
        await api.approve(id, officer, arg)
      }

      if (kind === 'hold') {
        await api.hold(id, officer, 'Held by officer')
      }

      if (kind === 'resuggest') {
        await api.resuggest(id)
      }

      if (kind === 'status') {
        await api.status(id, arg, officer)

        if (arg === 'resolved') {
          setSimulation((current) =>
            current?.incidentId === id ? null : current,
          )
        }
      }

      await refresh()
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  const flyTarget = useMemo(
    () => incidents.find((incident) => incident.id === selectedId) || null,
    [incidents, selectedId],
  )

  const simResponder = simulation
    ? responders.find(
      (responder) => responder.id === simulation.responderId,
    )
    : null

  const simIncident = simulation
    ? incidents.find(
      (incident) => incident.id === simulation.incidentId,
    )
    : null

  const simRoute = simulation?.route || []
  const simCurrent = simRoute.length
    ? pointAlongRoute(simRoute, simulation.progress)
    : null

  return (
    <div className="app">
      <Stats stats={stats} live={live} verify={verify} sync={sync} />

      {error && (
        <div className="error" role="alert">
          {error}
        </div>
      )}

      <main className="grid">
        <Queue
          incidents={incidents}
          selectedId={selectedId}
          onSelect={openIncident}
          filter={filter}
          setFilter={setFilter}
        />

        <section className="mapwrap" aria-label="Incident map">
          <MapContainer
            center={places.center ? [places.center.lat, places.center.lon] : CENTER}
            zoom={places.center?.zoom || CENTER_ZOOM}
            className="map"
            scrollWheelZoom
          >
            <TileLayer
              attribution="&copy; OpenStreetMap contributors"
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            />

            <FlyTo target={flyTarget} />

            <CityLayers places={places.places} shelters={shelters} showRisk={layers.risk} showShelters={layers.shelters} />
            <LiveLayers tick={tick} officer={officer} pickMode={pickMode} onPick={onPick} showUnits={false} showRoutes={layers.routes} />

            {responders.map((responder) => (
              <CircleMarker
                key={`r${responder.id}`}
                center={[responder.lat, responder.lon]}
                radius={6}
                pathOptions={{
                  color: '#0f172a',
                  weight: 2,
                  fillColor:
                    responder.status === 'available'
                      ? '#2fb67c'
                      : '#8792a2',
                  fillOpacity: 1,
                }}
              >
                <Tooltip>
                  {responder.name} · {responder.kind} · {responder.status}
                </Tooltip>
              </CircleMarker>
            ))}

            {incidents
              .filter((incident) => incident.status !== 'resolved')
              .map((incident) => (
                <CircleMarker
                  key={incident.id}
                  center={[incident.lat, incident.lon]}
                  radius={8 + Math.min(incident.report_count, 6) * 2}
                  eventHandlers={{
                    click: () => openIncident(incident.id),
                  }}
                  pathOptions={{
                    color:
                      selectedId === incident.id
                        ? '#ffffff'
                        : SEVERITY_COLOR[incident.severity],
                    weight: selectedId === incident.id ? 3 : 2,
                    fillColor: SEVERITY_COLOR[incident.severity],
                    fillOpacity: 0.55,
                  }}
                >
                  <Tooltip>
                    #{incident.id} {incident.type} · priority{' '}
                    {incident.priority} · {STATUS_LABEL[incident.status]}
                  </Tooltip>
                </CircleMarker>
              ))}

            {simRoute.length > 1 && simCurrent && (
              <>
                <Polyline
                  positions={simRoute}
                  pathOptions={{
                    color: simulation.mode === 'aerial' ? '#a78bfa' : simulation.mode === 'fallback' ? '#f59e0b' : '#38bdf8',
                    weight: 4,
                    dashArray: simulation.mode === 'aerial' ? '4 7' : undefined,
                    opacity: 0.9,
                  }}
                />

                <CircleMarker
                  center={simCurrent}
                  radius={10}
                  pathOptions={{
                    color: '#ffffff',
                    weight: 3,
                    fillColor: simulation.mode === 'aerial' ? '#a78bfa' : simulation.mode === 'fallback' ? '#f59e0b' : '#38bdf8',
                    fillOpacity: 1,
                  }}
                >
                  <Tooltip permanent>
                    Rescue unit · {Math.round(simulation.progress * 100)}%
                  </Tooltip>
                </CircleMarker>
              </>
            )}
          </MapContainer>

          {simulation && (
            <div
              style={{
                position: 'absolute',
                top: 12,
                left: 12,
                zIndex: 1000,
                padding: '10px 14px',
                borderRadius: 10,
                background: '#111827',
                border: '1px solid #38bdf8',
                color: '#e5f3ff',
                maxWidth: 260,
                pointerEvents: 'none',
              }}
            >
              <strong>{simulation.mode === 'aerial' ? 'Drone simulation' : simulation.mode === 'fallback' ? 'Rescue simulation · fallback' : 'Road rescue simulation'}</strong>

              <div style={{ marginTop: 4, fontSize: 12 }}>
                {simResponder?.name || 'Rescue unit'}
                {' → '}
                Incident #{simulation.incidentId}
              </div>

              <div style={{ marginTop: 4, fontSize: 12 }}>
                {simulation.progress >= 1
                  ? 'Demo arrival reached'
                  : `${Math.round(simulation.progress * 100)}% route completed`}
              </div>
              <div style={{ marginTop: 4, fontSize: 11, opacity: 0.85 }}>
                {simulation.routeMessage}
              </div>
            </div>
          )}

          <div className="maptools">
            <button className={pickMode === 'block' ? 'on' : ''} onClick={() => setPickMode(pickMode === 'block' ? null : 'block')}>
              {pickMode === 'block' ? 'Click the road on the map…' : 'Mark road blocked'}
            </button>
            <button
              onClick={async () => {
                if (!window.confirm('Reset demo data? This deletes all incidents, messages and road blocks.')) return // eslint-disable-line no-alert
                await fetch('/api/demo/reset', { method: 'POST' })
                setSelectedId(null)
                setSimulation(null)
                await refresh()
                setTick((t) => t + 1)
              }}
            >
              Reset demo
            </button>
            {[['risk', 'Risk spots'], ['shelters', 'Shelters'], ['routes', 'Unit routes']].map(([k, label]) => (
              <label key={k}>
                <input type="checkbox" checked={layers[k]} onChange={() => setLayers((l) => ({ ...l, [k]: !l[k] }))} />
                {label}
              </label>
            ))}
          </div>

          <RouteAlerts tick={tick} officer={officer} />

          {toast && (
            <button className="toast" onClick={() => { setSideTab('feed'); setToast(null) }}>
              {toast.text} · <u>open feed</u>
            </button>
          )}

          <div className="legend">
            {Object.entries(SEVERITY_COLOR).map(([key, color]) => (
              <span key={key}>
                <i style={{ background: color }} />
                {key}
              </span>
            ))}

            <span>
              <i style={{ background: '#2fb67c' }} />
              unit free
            </span>

            <span>
              <i style={{ background: '#8792a2' }} />
              unit busy
            </span>

            <span><i style={{ background: '#27b5c9' }} />flood-prone</span>
            <span><i style={{ background: '#f5a524' }} />accident-prone</span>
            <span><i style={{ background: '#e5484d', borderRadius: 0 }} />road blocked</span>

            {simulation && (
              <span>
                <i style={{ background: simulation.mode === 'aerial' ? '#a78bfa' : simulation.mode === 'fallback' ? '#f59e0b' : '#38bdf8' }} />
                {simulation.mode === 'aerial' ? 'drone route' : simulation.mode === 'fallback' ? 'fallback route' : 'road route'}
              </span>
            )}
          </div>
        </section>

        <div className="side">
          <label className="officer">
            <span>Officer</span>

            <input
              value={officer}
              onChange={(event) =>
                setOfficer(event.target.value || 'Duty Officer')
              }
            />
          </label>

          <div className="seg sidetabs" role="tablist">
            {[['incident', 'Incident'], ['planner', 'AI Planner'], ['feed', 'Live feed'], ['log', 'Action log']].map(([k, label]) => (
              <button key={k} className={sideTab === k ? 'on' : ''} onClick={() => setSideTab(k)}>{label}</button>
            ))}
          </div>

          {sideTab === 'incident' && incidents.find((i) => i.id === selectedId)?.drill && (
            <div className="drill-banner">DRILL: practice data from the drill script, not a real call</div>
          )}

          {sideTab === 'incident' && <Detail
            incident={selected}
            responders={responders}
            officer={officer}
            onAction={onAction}
            busy={busy}
            onStartSimulation={startSimulation}
            simulation={simulation}
          />}

          {sideTab === 'feed' && <FeedPanel tick={tick} officer={officer} onOpenIncident={openIncident} />}

          {sideTab === 'planner' && <PlannerPanel officer={officer} liveSteps={agentSteps} onOpenIncident={openIncident} />}

          {sideTab === 'log' && <LogPanel log={log} />}
        </div>
      </main>
    </div>
  )
}
