// Map layers for the control room: blocked roads (hazards), live units and their
// routes. Drop <LiveLayers /> inside your <MapContainer>. Re-fetches whenever
// `tick` changes (bump it on every WebSocket message).
import { useEffect, useState } from 'react'
import { Circle, CircleMarker, Polyline, Popup, Tooltip, useMapEvents } from 'react-leaflet'

// Colours come from CSS tokens through classNames (route-line, route-rerouted, hz-active…); see styles.css.

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
          <Circle key={`hz${h.id}-${h.status}`} center={[h.lat, h.lon]} radius={h.radius_m}
            className={active ? 'hz-active' : 'hz-unverified'} pathOptions={{ fillOpacity: active ? 0.3 : 0.15, weight: 2, dashArray: active ? null : '6 6' }}>
            <Popup>
              <strong>{active ? 'Blocked' : 'Unverified report'}: {h.note || h.kind.replace('_', ' ')}</strong>
              <div>Source: {h.source} · {h.reports} report{h.reports > 1 ? 's' : ''}</div>
              {h.photo && (
                <a href={h.photo} target="_blank" rel="noreferrer" className="hz-proof">
                  <img src={h.photo} alt="Photo proof of the blockage" />
                  <span>Photo proof</span>
                </a>
              )}
              <div className="popup-actions">
                {!active && <button onClick={() => liveApi.confirm(h.id, officer)}>Confirm block</button>}
                <button onClick={() => liveApi.clear(h.id, officer)}>Road open again</button>
              </div>
            </Popup>
          </Circle>
        )
      })}

      {/* route casing: a wider light line under each route keeps it crisp on any map */}
      {showRoutes && units.map((u) => u.assignment?.route?.length > 1 && u.kind !== 'drone' && (
        <Polyline key={`rc${u.id}-${u.assignment.route_version}`} positions={u.assignment.route} interactive={false}
          className={'route-casing'} pathOptions={{ weight: 9, opacity: 1, lineCap: 'round', lineJoin: 'round' }} />
      ))}

      {showRoutes && units.map((u) => u.assignment?.route?.length > 1 && (
        <Polyline key={`rt${u.id}-${u.assignment.route_version}`} positions={u.assignment.route}
          className={u.assignment.reroute_reason ? 'route-rerouted' : (u.kind === 'drone' ? 'route-drone' : 'route-line')} pathOptions={{ weight: 5, opacity: 0.92, dashArray: u.kind === 'drone' ? '4 8' : null, lineCap: 'round', lineJoin: 'round' }}>
          <Tooltip sticky>
            {u.name} → incident #{u.assignment.incident_id} · ETA {u.assignment.eta_min ?? '?'} min · {u.assignment.route_source}
            {u.assignment.reroute_reason ? ` · REROUTED: ${u.assignment.reroute_reason}` : ''}
          </Tooltip>
        </Polyline>
      ))}

      {showUnits && units.map((u) => (
        <CircleMarker key={`u${u.id}`} center={[u.lat, u.lon]} radius={8}
          className={u.status === 'available' ? 'shelter-open' : 'hz-unverified'} pathOptions={{ weight: 2, fillOpacity: 1 }}>
          <Tooltip>{u.name} ({u.code}) · {u.status}{u.last_seen ? ' · live GPS' : ''}</Tooltip>
        </CircleMarker>
      ))}
    </>
  )
}
