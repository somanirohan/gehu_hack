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
  cancelRoute: (aid, officer, reason) => getJSON(`/api/v1/assignments/${aid}/cancel`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ officer, reason }),
  }),
  completeRoute: (aid, officer) => getJSON(`/api/v1/assignments/${aid}/complete`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ officer }),
  }),
  alert: (lat, lon, radius_m, text, officer) => getJSON('/api/v1/alerts', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ lat, lon, radius_m, text, officer }),
  }),
}

function ClickCatcher({ active, onPick, onEmptyClick }) {
  useMapEvents({ click: (e) => (active ? onPick([e.latlng.lat, e.latlng.lng]) : onEmptyClick()) })
  return null
}

export default function LiveLayers({ tick, officer = 'Duty Officer', pickMode = null, onPick = () => {}, showUnits = true, showRoutes = true,
  selectedRoute = null, onSelectRoute = () => {}, onUnits = () => {} }) {
  const [hazards, setHazards] = useState([])
  const [units, setUnits] = useState([])

  useEffect(() => {
    liveApi.hazards().then(setHazards).catch(() => {})
    liveApi.units().then((u) => { setUnits(u); onUnits(u) }).catch(() => {})
  }, [tick]) // eslint-disable-line react-hooks/exhaustive-deps

  const anySelected = selectedRoute != null && units.some((u) => u.assignment?.id === selectedRoute)
  const routeClick = (aid) => (e) => {
    // while picking a spot (e.g. "Mark road blocked"), a click on a route is a pick, not a selection
    if (pickMode) onPick([e.latlng.lat, e.latlng.lng])
    else onSelectRoute(aid)
  }

  return (
    <>
      <ClickCatcher active={Boolean(pickMode)} onPick={onPick} onEmptyClick={() => anySelected && onSelectRoute(null)} />

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
      {showRoutes && units.map((u) => {
        const a = u.assignment
        if (!(a?.route?.length > 1) || u.kind === 'drone') return null
        const sel = a.id === selectedRoute
        const dim = anySelected && !sel
        return (
          <Polyline key={`rc${u.id}-${a.route_version}-${sel}-${dim}`} positions={a.route} interactive={false}
            className={sel ? 'route-casing route-casing-selected' : 'route-casing'}
            pathOptions={{ weight: sel ? 14 : 9, opacity: dim ? 0.35 : 1, lineCap: 'round', lineJoin: 'round' }} />
        )
      })}

      {showRoutes && units.map((u) => {
        const a = u.assignment
        if (!(a?.route?.length > 1)) return null
        const sel = a.id === selectedRoute
        const dim = anySelected && !sel
        const base = a.reroute_reason ? 'route-rerouted' : (u.kind === 'drone' ? 'route-drone' : 'route-line')
        return (
          <Polyline key={`rt${u.id}-${a.route_version}-${sel}-${dim}`} positions={a.route} interactive={false}
            className={sel ? `${base} route-selected` : base}
            pathOptions={{ weight: sel ? 8 : 5, opacity: dim ? 0.3 : 0.92, dashArray: u.kind === 'drone' ? '4 8' : null, lineCap: 'round', lineJoin: 'round' }} />
        )
      })}

      {/* invisible, wide line on top of each route: easy to click (a 5 px line is hard to hit) */}
      {showRoutes && units.map((u) => {
        const a = u.assignment
        if (!(a?.route?.length > 1)) return null
        return (
          <Polyline key={`rh${u.id}-${a.route_version}`} positions={a.route} className="route-hit"
            pathOptions={{ weight: 22, opacity: 0, bubblingMouseEvents: false }}
            eventHandlers={{ click: routeClick(a.id) }}>
            <Tooltip sticky>
              {u.name} → incident #{a.incident_id} · ETA {a.eta_min ?? '?'} min · {a.route_source}
              {a.reroute_reason ? ` · REROUTED: ${a.reroute_reason}` : ''}
              {pickMode ? '' : ' · click for details'}
            </Tooltip>
          </Polyline>
        )
      })}

      {showUnits && units.map((u) => (
        <CircleMarker key={`u${u.id}`} center={[u.lat, u.lon]} radius={8}
          className={u.status === 'available' ? 'shelter-open' : 'hz-unverified'} pathOptions={{ weight: 2, fillOpacity: 1 }}>
          <Tooltip>{u.name} ({u.code}) · {u.status}{u.last_seen ? ' · live GPS' : ''}</Tooltip>
        </CircleMarker>
      ))}
    </>
  )
}
