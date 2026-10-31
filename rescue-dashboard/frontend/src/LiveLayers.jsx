// Map layers for the control room: blocked roads (hazards), live units and their
// routes. Drop <LiveLayers /> inside your <MapContainer>. Re-fetches whenever
// `tick` changes (bump it on every WebSocket message).
import { useEffect, useState } from 'react'
import { Circle, CircleMarker, Polyline, Popup, Tooltip, useMapEvents } from 'react-leaflet'

const KIND_COLOR = { ambulance: '#2fb67c', rescue: '#3e8ed0', fire: '#e5484d', boat: '#27b5c9', police: '#8e7cf0', drone: '#a78bfa' }

async function getJSON(url, options) {
  const r = await fetch(url, options)
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText)
  return r.json()
}

export const liveApi = {
  hazards: () => getJSON('/api/v1/hazards'),
  units: () => getJSON('/api/v1/units'),
  addHazard: (lat, lon, note, radius_m, by) => getJSON('/api/v1/hazards', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ lat, lon, note, radius_m, by }),
  }),
  confirm: (id, by) => getJSON(`/api/v1/hazards/${id}/confirm?by=${encodeURIComponent(by)}`, { method: 'POST' }),
  clear: (id, by) => getJSON(`/api/v1/hazards/${id}/clear?by=${encodeURIComponent(by)}`, { method: 'POST' }),
  alert: (lat, lon, radius_m, text, officer) => getJSON('/api/v1/alerts', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ lat, lon, radius_m, text, officer }),
  }),
}

function ClickCatcher({ active, onPick }) {
  useMapEvents({ click: (e) => active && onPick([e.latlng.lat, e.latlng.lng]) })
  return null
}

export default function LiveLayers({ tick, officer = 'Duty Officer', pickMode = null, onPick = () => {}, showUnits = true, showRoutes = true }) {
  const [hazards, setHazards] = useState([])
  const [units, setUnits] = useState([])

  useEffect(() => {
    liveApi.hazards().then(setHazards).catch(() => {})
    liveApi.units().then(setUnits).catch(() => {})
  }, [tick])

  return (
    <>
      <ClickCatcher active={Boolean(pickMode)} onPick={onPick} />

      {hazards.map((h) => {
        const active = h.status === 'active'
        return (
          <Circle key={`hz${h.id}`} center={[h.lat, h.lon]} radius={h.radius_m}
            pathOptions={{ color: active ? '#e5484d' : '#f5a524', fillColor: active ? '#e5484d' : '#f5a524', fillOpacity: active ? 0.3 : 0.15, weight: 2, dashArray: active ? null : '6 6' }}>
            <Popup>
              <strong>{active ? 'Blocked' : 'Unverified report'}: {h.note || h.kind.replace('_', ' ')}</strong>
              <div>Source: {h.source} · {h.reports} report{h.reports > 1 ? 's' : ''}</div>
              <div className="popup-actions">
                {!active && <button onClick={() => liveApi.confirm(h.id, officer)}>Confirm block</button>}
                <button onClick={() => liveApi.clear(h.id, officer)}>Road open again</button>
              </div>
            </Popup>
          </Circle>
        )
      })}

      {showRoutes && units.map((u) => u.assignment?.route?.length > 1 && (
        <Polyline key={`rt${u.id}-${u.assignment.route_version}`} positions={u.assignment.route}
          pathOptions={{ color: u.assignment.reroute_reason ? '#f5a524' : (KIND_COLOR[u.kind] || '#3e8ed0'), weight: 5, opacity: 0.85, dashArray: u.kind === 'drone' ? '4 7' : null }}>
          <Tooltip sticky>
            {u.name} → incident #{u.assignment.incident_id} · ETA {u.assignment.eta_min ?? '?'} min · {u.assignment.route_source}
            {u.assignment.reroute_reason ? ` · REROUTED: ${u.assignment.reroute_reason}` : ''}
          </Tooltip>
        </Polyline>
      ))}

      {showUnits && units.map((u) => (
        <CircleMarker key={`u${u.id}`} center={[u.lat, u.lon]} radius={8}
          pathOptions={{ color: '#0d1117', weight: 2, fillColor: u.status === 'available' ? (KIND_COLOR[u.kind] || '#2fb67c') : '#f5a524', fillOpacity: 1 }}>
          <Tooltip>{u.name} ({u.code}) · {u.status}{u.last_seen ? ' · live GPS' : ''}</Tooltip>
        </CircleMarker>
      ))}
    </>
  )
}
