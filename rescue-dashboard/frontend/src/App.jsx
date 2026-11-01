import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  MapContainer,
  TileLayer,
  CircleMarker,
  Tooltip,
  Polyline,
  Pane,
  useMap,
} from 'react-leaflet'
import { api, liveUpdates } from './api.js'

import LiveLayers, { liveApi } from './LiveLayers'
import FeedPanel from './FeedPanel'
import CityLayers, { isBeacon } from './CityLayers'
import BeaconControl from './BeaconControl'
import PlannerPanel from './PlannerPanel'
import CommanderPanel from './CommanderPanel'
import RouteAlerts from './RouteAlerts'
import RoutePanel from './RoutePanel'
import PhotoHazards, { PhotoHazardMarkers, usePhotoHazards, photoApi } from './PhotoHazards'
import { IncidentMarkers, UnitMarkers, SEV, TypeIcon } from './MapMarkers'
import AgentFeed, { useAgentItems } from './AgentFeed'

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

const SEVERITY_COLOR = SEV

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

// ---------------------------------------------------------------- base maps (no API key)
const ESRI = 'https://server.arcgisonline.com/ArcGIS/rest/services'
const ESRI_ATTR = 'Tiles &copy; Esri, HERE, Garmin, &copy; OpenStreetMap contributors'
const MAP_STYLES = {
  // base layer without names + a separate names layer drawn ABOVE our routes
  clean: {
    light: { base: `${ESRI}/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}`, names: `${ESRI}/Canvas/World_Light_Gray_Reference/MapServer/tile/{z}/{y}/{x}` },
    dark: { base: `${ESRI}/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}`, names: `${ESRI}/Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}` },
    attr: ESRI_ATTR, maxZoom: 16,
  },
  streets: {
    light: { base: `${ESRI}/World_Street_Map/MapServer/tile/{z}/{y}/{x}` },
    dark: { base: `${ESRI}/World_Street_Map/MapServer/tile/{z}/{y}/{x}` },
    attr: ESRI_ATTR, maxZoom: 19,
  },
  satellite: {
    light: { base: `${ESRI}/World_Imagery/MapServer/tile/{z}/{y}/{x}`, names: `${ESRI}/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}`, roads: `${ESRI}/Reference/World_Transportation/MapServer/tile/{z}/{y}/{x}` },
    dark: { base: `${ESRI}/World_Imagery/MapServer/tile/{z}/{y}/{x}`, names: `${ESRI}/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}`, roads: `${ESRI}/Reference/World_Transportation/MapServer/tile/{z}/{y}/{x}` },
    attr: 'Imagery &copy; Esri, Maxar, Earthstar Geographics', maxZoom: 19,
  },
  osm: {
    light: { base: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png' },
    dark: { base: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png' },
    attr: '&copy; OpenStreetMap contributors', maxZoom: 19,
  },
}
const MAP_FALLBACK = { osm: 'streets', clean: 'streets', satellite: 'streets' }

function BaseMap({ style, theme, showNames, onFail }) {
  const cfg = MAP_STYLES[style] || MAP_STYLES.clean
  const t = cfg[theme === 'dark' ? 'dark' : 'light']
  const errors = useMemo(() => ({ n: 0 }), [style, theme]) // eslint-disable-line react-hooks/exhaustive-deps
  const onError = () => { errors.n += 1; if (errors.n === 8) onFail() }
  return (
    <>
      <TileLayer key={`base-${style}-${theme}`} url={t.base} attribution={cfg.attr} maxNativeZoom={cfg.maxZoom} maxZoom={20}
        className={`basemap basemap-${style}`} eventHandlers={{ tileerror: onError }} />
      {t.roads && (
        <TileLayer key={`roads-${style}`} url={t.roads} maxNativeZoom={cfg.maxZoom} maxZoom={20} />
      )}
      <Pane name="map-labels" style={{ zIndex: 450, pointerEvents: 'none' }}>
        {showNames && t.names && (
          <TileLayer key={`names-${style}-${theme}`} url={t.names} maxNativeZoom={cfg.maxZoom} maxZoom={20} pane="map-labels" />
        )}
      </Pane>
    </>
  )
}

// Leaflet must re-measure when the layout changes (presentation mode, panels).
function MapResizer({ dep }) {
  const map = useMap()
  useEffect(() => {
    const t = [80, 350, 800].map((ms) => setTimeout(() => map.invalidateSize({ pan: true, debounceMoveend: true }), ms))
    return () => t.forEach(clearTimeout)
  }, [dep, map])
  return null
}

function FlyTo({ target }) {
  const map = useMap()

  useEffect(() => {
    if (target) {
      map.flyTo(
        [target.lat, target.lon],
        Math.max(map.getZoom(), 15),
        { duration: 1.3, easeLinearity: 0.2 },
      )
    }
  }, [target?.id, map]) // eslint-disable-line react-hooks/exhaustive-deps

  return null
}

const SUN = <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" aria-hidden="true"><circle cx="12" cy="12" r="4.2" /><path d="M12 2.5v2.2M12 19.3v2.2M2.5 12h2.2M19.3 12h2.2M5.3 5.3l1.6 1.6M17.1 17.1l1.6 1.6M5.3 18.7l1.6-1.6M17.1 6.9l1.6-1.6" /></svg>
const MOON = <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z" /></svg>

const ICON_LEFT = (on) => <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="2" /><rect x="3" y="4" width="6.5" height="16" rx="2" fill={on ? 'currentColor' : 'none'} /></svg>
const ICON_RIGHT = (on) => <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="2" /><rect x="14.5" y="4" width="6.5" height="16" rx="2" fill={on ? 'currentColor' : 'none'} /></svg>

function Stats({ stats, live, verify, sync, incidents = [], aiCount = 0, onPresent, present, theme, onTheme, panels, onPanel, beaconCount = 0, onOpenBeacons = () => {} }) {
  if (!stats) return null
  const open = incidents.filter((i) => i.status !== 'resolved')
  const lives = open.reduce((n, i) => n + (i.people || 1), 0)
  const critical = open.filter((i) => i.severity === 'critical').length

  const items = [
    ['Lives at risk', lives, 'hot'],
    ['Critical', critical, critical ? 'hot' : ''],
    ['Open incidents', stats.open, ''],
    ['Awaiting approval', stats.awaiting_approval, stats.awaiting_approval ? 'warn' : ''],
    ['Units free', `${stats.responders_available}/${stats.responders_total}`, ''],
    ['Median to dispatch', stats.median_minutes_to_dispatch == null ? '—' : `${stats.median_minutes_to_dispatch} min`, ''],
    ['AI actions', aiCount, 'ai'],
  ]

  return (
    <header className="topbar">
      <div className="brand">
        <span className="brand-mark" aria-hidden="true"><svg viewBox="0 0 24 24" width="18" height="18"><path d="M12 4v16M4 12h16" stroke="currentColor" strokeWidth="3.2" strokeLinecap="round"/></svg></span>
        <div>
          <div className="brand-name">RESQ <span className="brand-city">Dehradun Disaster Control Room</span></div>
          <div className="brand-sub">
            {verify != null && (
              <span className={`chip ${verify.ok ? '' : 'bad'}`}>
                {verify.ok ? `Log intact · ${verify.entries}` : `Log tampered at #${verify.broken_at.join(', #')}`}
              </span>
            )}
            <span className="chip">{syncText(sync)}</span>
          </div>
        </div>
      </div>

      <div className="stats">
        {items.map(([label, value, tone]) => (
          <div className={`stat ${tone}`} key={label}>
            <div className="stat-value">{value}</div>
            <div className="stat-label">{label}</div>
          </div>
        ))}
      </div>

      <div className="nav-actions">
        <div className="layout-btns" role="group" aria-label="Show or hide panels">
          <button className={`theme-btn ${panels?.left ? 'on' : ''}`} onClick={() => onPanel('left')}
            aria-pressed={!!panels?.left} title={`${panels?.left ? 'Hide' : 'Show'} incidents list (Ctrl+B)`}>{ICON_LEFT(panels?.left)}</button>
          <button className={`theme-btn ${panels?.right ? 'on' : ''}`} onClick={() => onPanel('right')}
            aria-pressed={!!panels?.right} title={`${panels?.right ? 'Hide' : 'Show'} details panel (Ctrl+Alt+B)`}>{ICON_RIGHT(panels?.right)}</button>
        </div>
        <button className="theme-btn" onClick={onTheme}
          aria-label={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
          title={theme === 'dark' ? 'Light mode' : 'Dark mode'}>
          {theme === 'dark' ? SUN : MOON}
        </button>
        <button className="present-btn" onClick={onPresent}>{present ? 'Exit presentation' : 'Present'}</button>
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
              className={`qitem sev-${incident.severity} ${selectedId === incident.id ? 'sel' : ''
                } ${incident.status === 'resolved' ? 'done' : ''}`}
              onClick={() => onSelect(incident.id)}
              style={{ '--c': SEVERITY_COLOR[incident.severity] }}
            >
              <span className="qico">
                <TypeIcon type={incident.type} size={20} />
                <span className="qprio">{incident.priority}</span>
              </span>

              <span className="qbody">
                <span className="qtitle">
                  <span className="qname">{incident.type}</span>
                  <span className="qid">#{incident.id}</span>
                  {['confirmed', 'possible_fake'].includes(incident.verification) && <span className={`vmark vf-${incident.verification}`} title={`Verifier Agent: ${VERDICT_LABEL[incident.verification]}`}>{incident.verification === 'confirmed' ? '✓' : incident.verification === 'possible_fake' ? '!' : incident.verification === 'likely' ? '◐' : '?'}</span>}
                  {incident.drill && <span className="tag">drill</span>}
                </span>

                <span className="qrow">
                  <span className={`pill st-${incident.status}`}>{STATUS_LABEL[incident.status] || incident.status}</span>
                  {incident.ai_urgency && <span className={`ai-u u-${incident.ai_urgency}`} title="Triage Agent reading (AI suggestion)">AI {incident.ai_urgency}</span>}
                </span>

                <span className="qmeta">
                  <b>{incident.people}</b> {incident.people === 1 ? 'person' : 'people'}
                  {' · '}
                  {incident.report_count} report{incident.report_count > 1 ? 's' : ''}
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

              <div className="sim-bar">
                <div style={{ width: `${simulation.progress * 100}%` }} />
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

            {report.transcript && (
              <div className="rtranscript">
                🎙️ {report.spoken_language ? `(${report.spoken_language}) ` : ''}{report.transcript}
                {report.transcript_en && <div className="ren">English: {report.transcript_en}</div>}
              </div>
            )}

            {report.ai_description && (
              <div className="rphoto-ai">Photo check: {report.ai_description}</div>
            )}

            {report.media?.length > 0 && (
              <div className="rmedia">
                {report.media.map((m, k) => (m.mime || '').startsWith('audio/')
                  ? <audio key={m.media_id || k} controls preload="none" src={m.url} aria-label="Voice note" />
                  : <a key={m.media_id || k} href={m.url} target="_blank" rel="noreferrer"><img src={m.thumb || m.url} alt="Photo from the field" /></a>)}
              </div>
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
  const photoHazards = usePhotoHazards(tick)
  const [places, setPlaces] = useState({ center: null, places: [] })
  const [shelters, setShelters] = useState([])
  const [selectedBeaconId, setSelectedBeaconId] = useState(null)
  const [customFlyTarget, setCustomFlyTarget] = useState(null)
  const [sync, setSync] = useState(null)
  const [toast, setToast] = useState(null)
  const [layers, setLayers] = useState({ risk: true, shelters: true, routes: true, names: true, labels: true })

  const [pickMode, setPickMode] = useState(null)  // 'block' | 'photo:<id>'
  const [selectedRoute, setSelectedRoute] = useState(null)  // assignment id of the route clicked on the map
  const [liveUnits, setLiveUnits] = useState([])
  const [photoFocus, setPhotoFocus] = useState(null)
  const [sideTab, setSideTab] = useState('incident')
  const [agentSteps, setAgentSteps] = useState([])
  // panels the officer can close and reopen (remembered in this browser)
  const [panels, setPanels] = useState(() => {
    const d = { left: true, right: true, routeWatch: true, agents: true, legend: true, tools: true }
    try { return { ...d, ...JSON.parse(localStorage.getItem('resq-panels') || '{}') } } catch { return d }
  })
  const togglePanel = (k) => setPanels((p) => {
    const n = { ...p, [k]: !p[k] }
    try { localStorage.setItem('resq-panels', JSON.stringify(n)) } catch { /* ignore */ }
    return n
  })
  useEffect(() => {
    const onKey = (e) => {
      if (!(e.ctrlKey || e.metaKey) || e.key.toLowerCase() !== 'b') return
      const tag = (e.target.tagName || '').toLowerCase()
      if (tag === 'input' || tag === 'textarea' || tag === 'select') return
      e.preventDefault()
      togglePanel(e.altKey ? 'right' : 'left')
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps
  const [theme, setTheme] = useState(() => document.documentElement.dataset.theme || 'light')
  const [mapStyle, setMapStyle] = useState(() => {
    try { return localStorage.getItem('resq-map2') || 'osm' } catch { return 'osm' }
  })
  useEffect(() => { try { localStorage.setItem('resq-map2', mapStyle) } catch { /* ignore */ } }, [mapStyle])

  const toggleTheme = () => {
    const next = theme === 'dark' ? 'light' : 'dark'
    document.documentElement.dataset.theme = next
    try { localStorage.setItem('resq-theme', next) } catch { /* private mode: still switches */ }
    setTheme(next)
  }

  // follow the system setting until the user picks a theme
  useEffect(() => {
    let saved = null
    try { saved = localStorage.getItem('resq-theme') } catch { /* ignore */ }
    if (saved) return undefined
    const mq = window.matchMedia?.('(prefers-color-scheme: dark)')
    if (!mq) return undefined
    const on = (e) => { const t = e.matches ? 'dark' : 'light'; document.documentElement.dataset.theme = t; setTheme(t) }
    mq.addEventListener?.('change', on)
    return () => mq.removeEventListener?.('change', on)
  }, [])
  const [present, setPresent] = useState(false)

  useEffect(() => {
    const onFs = () => { if (!document.fullscreenElement) setPresent(false) }
    document.addEventListener('fullscreenchange', onFs)
    return () => document.removeEventListener('fullscreenchange', onFs)
  }, [])

  const togglePresent = () => {
    setPresent((p) => {
      const next = !p
      try {
        if (next && !document.fullscreenElement) document.documentElement.requestFullscreen?.()
        if (!next && document.fullscreenElement) document.exitFullscreen?.()
      } catch { /* full screen is optional */ }
      return next
    })
  }

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
      if (msg?.event === 'shelters' || msg?.event === 'beacon_updated') {
        api.shelters().then(setShelters).catch(() => {})
        if (msg?.event === 'beacon_updated' && msg.data?.name) {
          const capText = msg.data.capacity != null ? ` · Live Capacity: ${msg.data.capacity}` : ''
          setToast({ kind: 'beacon', text: `🚨 SOS Beacon: ${msg.data.name}${capText}`, at: Date.now() })
          beep()
        }
      }
      if (msg?.event === 'photo_hazard' && msg.data?.status === 'pending') {
        setToast({ kind: 'photo', text: `Photo shows: ${msg.data.label}. Add a road blockage there?`, at: Date.now() })
        beep()
      }

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
    if (pickMode?.startsWith('photo:')) {
      const id = Number(pickMode.slice(6))
      setPickMode(null)
      try {
        await photoApi.accept(id, officer, [lat, lon])
        setTick((t) => t + 1)
      } catch (e) {
        setError(e.message)
      }
      return
    }
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

  const openIncident = (id) => { setSelectedId(id); setSideTab('incident'); setSelectedRoute(null) }

  const selectRoute = (aid) => {
    setSelectedRoute(aid)
    if (aid != null) {
      setSideTab('route')
      if (!panels.right) togglePanel('right')
    } else if (sideTab === 'route') {
      setSideTab('incident')
    }
  }

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
    () => customFlyTarget || incidents.find((incident) => incident.id === selectedId) || null,
    [customFlyTarget, incidents, selectedId],
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

  const agentItems = useAgentItems(tick, log)

  const simRoute = simulation?.route || []
  const simCurrent = simRoute.length
    ? pointAlongRoute(simRoute, simulation.progress)
    : null

  return (
    <div className={`app ${present ? 'presenting' : ''}`}>
      <Stats stats={stats} live={live} verify={verify} sync={sync} incidents={incidents}
        aiCount={agentItems.length} onPresent={togglePresent} present={present}
        theme={theme} onTheme={toggleTheme} panels={panels} onPanel={togglePanel}
        beaconCount={shelters.filter((s) => isBeacon(s) && (s.status || '').toUpperCase() !== 'CLOSED').length}
        onOpenBeacons={() => {
          setSideTab('beacons')
          if (!panels.right) togglePanel('right')
          const activeB = shelters.find((s) => isBeacon(s) && (s.status || '').toUpperCase() !== 'CLOSED') || shelters.find(isBeacon)
          if (activeB) {
            setSelectedBeaconId(activeB.id)
            setCustomFlyTarget({ lat: activeB.lat, lon: activeB.lon, id: `beacon-${activeB.id}-${Date.now()}` })
          }
        }} />

      {error && (
        <div className="error" role="alert">
          {error}
        </div>
      )}

      <main className={`grid ${panels.left ? '' : 'no-left'} ${panels.right ? '' : 'no-right'}`}>
        {panels.left && <Queue
          incidents={incidents}
          selectedId={selectedId}
          onSelect={openIncident}
          filter={filter}
          setFilter={setFilter}
        />}

        <section className="mapwrap" aria-label="Incident map">
          <MapContainer
            center={places.center ? [places.center.lat, places.center.lon] : CENTER}
            zoom={places.center?.zoom || CENTER_ZOOM}
            className="map"
            scrollWheelZoom
            zoomSnap={0.25}
            zoomDelta={0.5}
            wheelPxPerZoomLevel={110}
            wheelDebounceTime={30}
            inertiaDeceleration={2200}
          >
            {/* Crystal-clear map: base map without names at the bottom, our routes and
                areas above it, then street and place NAMES on top of the routes, then markers.
                Esri (ArcGIS) tiles need no API key. If a style fails to load, the next one is used. */}
            <BaseMap style={mapStyle} theme={theme} showNames={layers.names}
              onFail={() => setMapStyle((m) => MAP_FALLBACK[m] || m)} />

            <FlyTo target={flyTarget} />
            <MapResizer dep={`${present}-${panels.left}-${panels.right}`} />

            <CityLayers places={places.places} shelters={shelters} showRisk={layers.risk} showShelters={layers.shelters}
              onManageBeacon={(id) => { setSelectedBeaconId(id); setSideTab('beacons'); if (!panels.right) togglePanel('right') }} />
            <LiveLayers tick={tick} officer={officer} pickMode={pickMode} onPick={onPick} showUnits={false} showRoutes={layers.routes}
              selectedRoute={selectedRoute} onSelectRoute={selectRoute} onUnits={setLiveUnits} />

            <UnitMarkers responders={responders} showLabels={layers.labels} />

            <PhotoHazardMarkers items={photoHazards} onSelect={(id) => { setPhotoFocus(id); if (!panels.routeWatch) togglePanel('routeWatch') }} />

            <IncidentMarkers incidents={incidents} selectedId={selectedId} onSelect={openIncident} statusLabel={STATUS_LABEL} showLabels={layers.labels} />

            {simRoute.length > 1 && simCurrent && (
              <>
                <Polyline
                  positions={simRoute}
                  key={`sim-${simulation.mode}`}
                  className={`sim-${simulation.mode === 'aerial' ? 'aerial' : simulation.mode === 'fallback' ? 'fallback' : 'road'}`}
                  pathOptions={{
                    weight: 4,
                    dashArray: simulation.mode === 'aerial' ? '4 7' : undefined,
                    opacity: 0.9,
                  }}
                />

                <CircleMarker
                  center={simCurrent}
                  radius={10}
                  className={'sim-dot'} pathOptions={{ weight: 3,
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
            <div className="sim-box">
              <strong>{simulation.mode === 'aerial' ? 'Drone simulation' : simulation.mode === 'fallback' ? 'Rescue simulation · fallback' : 'Road rescue simulation'}</strong>

              <div className="sim-line">
                {simResponder?.name || 'Rescue unit'}
                {' → '}
                Incident #{simulation.incidentId}
              </div>

              <div className="sim-line">
                {simulation.progress >= 1
                  ? 'Demo arrival reached'
                  : `${Math.round(simulation.progress * 100)}% route completed`}
              </div>
              <div className="sim-note">
                {simulation.routeMessage}
              </div>
            </div>
          )}

          <div className={`maptools ${panels.tools ? '' : 'folded'}`}>
            <button className="fold-btn" onClick={() => togglePanel('tools')} aria-expanded={panels.tools}
              title={panels.tools ? 'Fold map layers' : 'Show map layers'}>
              {panels.tools ? 'Layers ▴' : 'Layers ▾'}
            </button>
            {panels.tools && <>
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
            <label className="map-style">
              Map
              <select value={mapStyle} onChange={(e) => setMapStyle(e.target.value)} aria-label="Map style">
                <option value="osm">OpenStreetMap</option>
                <option value="streets">Streets (Esri)</option>
                <option value="satellite">Satellite</option>
                <option value="clean">Clean (light)</option>
              </select>
            </label>
            {[['names', 'Street names'], ['labels', 'Unit & incident labels'], ['risk', 'Risk spots'], ['shelters', 'Shelters & SOS Beacons'], ['routes', 'Unit routes']].map(([k, label]) => (
              <label key={k}>
                <input type="checkbox" checked={layers[k]} onChange={() => setLayers((l) => ({ ...l, [k]: !l[k] }))} />
                {label}
              </label>
            ))}

            </>}
          </div>

          <div className="map-prompts">
            <RouteAlerts tick={tick} officer={officer} open={panels.routeWatch} onToggle={() => togglePanel('routeWatch')} />
            <PhotoHazards items={photoHazards} officer={officer} focusId={photoFocus}
              pickingId={pickMode?.startsWith('photo:') ? Number(pickMode.slice(6)) : null}
              onPickSpot={(id) => setPickMode(pickMode === `photo:${id}` ? null : `photo:${id}`)}
              onDone={() => setTick((t) => t + 1)} />
          </div>

          {pickMode && pickMode !== 'block' && (
            <div className="pick-hint" role="status">
              Click the map where the photo was taken; the road blockage goes there
              <button onClick={() => setPickMode(null)}>Cancel</button>
            </div>
          )}

          <AgentFeed items={agentItems} max={present ? 10 : 5} open={panels.agents} onToggle={() => togglePanel('agents')} />

          {toast && (
            <button className="toast" onClick={() => { setSideTab('feed'); setToast(null) }}>
              {toast.text} · <u>open feed</u>
            </button>
          )}

          {!panels.legend && (
            <button className="legend-tab" onClick={() => togglePanel('legend')} title="Show the legend">Legend ▴</button>
          )}
          {panels.legend && <div className="legend">
            <button className="fold-x" onClick={() => togglePanel('legend')} aria-label="Hide the legend" title="Hide">✕</button>
            {Object.entries(SEVERITY_COLOR).map(([key, color]) => (
              <span key={key}>
                <i style={{ background: color }} />
                {key}
              </span>
            ))}

            <span><i className="lg-unit" />unit free</span>
            <span><i className="lg-unit busy" />unit on task</span>
            <span><i className="lg-line" />route</span>
            <span><i className="lg-line red" />re-routed</span>
            <span><i className="lg-ring blue" />flood-prone</span>
            <span><i className="lg-ring amber" />accident-prone</span>
            <span><i className="lg-block" />road blocked</span>
            <span><i className="lg-beacon" />SOS beacon (👥 live capacity)</span>

            {simulation && (
              <span>
                <i className="lg-line" />
                {simulation.mode === 'aerial' ? 'drone route' : simulation.mode === 'fallback' ? 'fallback route' : 'road route'}
              </span>
            )}
          </div>}
        </section>

        {panels.right && <div className="side">
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
            {[['incident', 'Incident'], ['beacons', 'SOS Beacons'], ['planner', 'AI Planner'], ['ask', 'Ask AI'], ['feed', 'Live feed'], ['log', 'Action log']].map(([k, label]) => (
              <button key={k} className={sideTab === k ? 'on' : ''} onClick={() => { setSideTab(k); setSelectedRoute(null) }}>{label}</button>
            ))}
          </div>

          {sideTab === 'beacons' && (
            <BeaconControl
              officer={officer}
              shelters={shelters}
              selectedBeaconId={selectedBeaconId}
              onUpdate={() => {
                refresh()
                api.shelters().then(setShelters).catch(() => {})
                setTick((t) => t + 1)
              }}
              onFlyTo={([lat, lon]) => {
                setSelectedId(null)
                setCustomFlyTarget({ lat, lon, id: `beacon-${lat}-${lon}-${Date.now()}` })
              }}
            />
          )}

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

          {sideTab === 'route' && selectedRoute != null && <RoutePanel assignmentId={selectedRoute} units={liveUnits}
            incidents={incidents} officer={officer} onClose={() => selectRoute(null)} onOpenIncident={openIncident}
            onDone={() => { refresh(); setTick((t) => t + 1) }} />}

          {sideTab === 'feed' && <FeedPanel tick={tick} officer={officer} onOpenIncident={openIncident} />}

          {sideTab === 'planner' && <PlannerPanel officer={officer} liveSteps={agentSteps} onOpenIncident={openIncident} />}

          <div className="ask-wrap" hidden={sideTab !== 'ask'}><CommanderPanel officer={officer} onOpenIncident={openIncident} /></div>

          {sideTab === 'log' && <LogPanel log={log} />}
        </div>}
      </main>
    </div>
  )
}
