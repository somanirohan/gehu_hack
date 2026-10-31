// Dehradun context layers: known flood / accident-prone spots (with the news or
// police source for each) and relief shelters synced from the mesh app.
import { CircleMarker, Popup, Tooltip } from 'react-leaflet'

const RISK = {
  risk_flood: { color: '#27b5c9', label: 'Flood-prone' },
  risk_accident: { color: '#f5a524', label: 'Accident-prone' },
}

const SHELTER_COLOR = { OPEN: '#2fb67c', FULL: '#e5484d', CLOSED: '#8792a2' }

export default function CityLayers({ places = [], shelters = [], showRisk = true, showShelters = true }) {
  return (
    <>
      {showRisk && places.filter((p) => RISK[p.kind]).map((p) => (
        <CircleMarker key={`risk-${p.id}`} center={[p.lat, p.lon]} radius={7}
          pathOptions={{ color: RISK[p.kind].color, weight: 2, fillColor: RISK[p.kind].color, fillOpacity: 0.18, dashArray: '3 4' }}>
          <Tooltip>{RISK[p.kind].label}: {p.name}</Tooltip>
          <Popup>
            <strong>{RISK[p.kind].label}: {p.name}</strong>
            {p.note && <div>{p.note}</div>}
            <div className="muted">
              Position: {p.coord_source === 'approximate' ? 'approximate (refine with tools/dehradun_places.py)' : p.coord_source}
            </div>
            {p.source_url && <a href={p.source_url} target="_blank" rel="noreferrer">Source</a>}
          </Popup>
        </CircleMarker>
      ))}

      {showShelters && shelters.map((s) => (
        <CircleMarker key={`sh-${s.id}`} center={[s.lat, s.lon]} radius={9}
          pathOptions={{ color: '#0d1117', weight: 2, fillColor: SHELTER_COLOR[(s.status || '').toUpperCase()] || '#2fb67c', fillOpacity: 0.95 }}>
          <Tooltip>Shelter: {s.name} · {s.status || 'unknown'}</Tooltip>
          <Popup>
            <strong>Shelter: {s.name}</strong>
            <div>Status: {s.status || 'unknown'}{s.capacity ? ` · capacity ${s.capacity}` : ''}</div>
            <div className="muted">
              From the mesh app · version {s.version} · {s.verified ? 'verified by an official' : 'not verified'}
            </div>
          </Popup>
        </CircleMarker>
      ))}
    </>
  )
}
