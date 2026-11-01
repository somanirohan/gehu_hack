// Dehradun context layers: known flood / accident-prone spots (with the news or
// police source for each) and relief shelters / live SOS beacons synced from the mesh app.
import L from 'leaflet'
import { CircleMarker, Marker, Popup, Tooltip } from 'react-leaflet'

// Colours come from CSS tokens through classNames (see styles.css).
const RISK = {
  risk_flood: { cls: 'risk-flood', label: 'Flood-prone' },
  risk_accident: { cls: 'risk-accident', label: 'Accident-prone' },
}

const SHELTER_CLASS = { OPEN: 'shelter-open', FULL: 'shelter-full', CLOSED: 'shelter-closed' }

export function isBeacon(s) {
  if (s.is_beacon) return true
  const role = (s.role || '').toUpperCase()
  const name = (s.name || '').toLowerCase()
  return role === 'CIVILIAN' || role === 'SOS' || name.includes('beacon') || (s.id && s.id.startsWith('beacon-'))
}

function beaconIcon(s) {
  const status = (s.status || 'OPEN').toUpperCase()
  const cap = s.capacity != null ? s.capacity : '—'
  const isFull = status === 'FULL'
  const isClosed = status === 'CLOSED'
  const color = isClosed ? '#6B7280' : (isFull ? '#DC2626' : '#EF4444')
  const pulseClass = isClosed ? '' : 'beacon-pulsing'

  return L.divIcon({
    className: 'beacon-marker-container',
    iconSize: [52, 52],
    iconAnchor: [26, 26],
    html: `
      <div class="mk-beacon-wrap ${pulseClass} ${isFull ? 'beacon-full' : ''} ${isClosed ? 'beacon-closed' : ''}" style="--b-color:${color}">
        <div class="beacon-pulse-ring"></div>
        <div class="beacon-pulse-ring-outer"></div>
        <div class="beacon-center-pin">
          <span class="beacon-icon">🚨</span>
        </div>
        <div class="beacon-cap-tag ${isFull ? 'full' : ''}">
          <span class="cap-num">👥 ${cap}</span>
        </div>
      </div>
    `,
  })
}

export default function CityLayers({
  places = [],
  shelters = [],
  showRisk = true,
  showShelters = true,
  onManageBeacon = () => {},
}) {
  return (
    <>
      {showRisk && places.filter((p) => RISK[p.kind]).map((p) => (
        <CircleMarker key={`risk-${p.id}`} center={[p.lat, p.lon]} radius={7}
          className={RISK[p.kind].cls} pathOptions={{ weight: 2, fillOpacity: 0.18, dashArray: '3 4' }}>
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

      {showShelters && shelters.filter((s) => (s.status || '').toUpperCase() !== 'CLOSED' && !isBeacon(s)).map((s) => {

        return (
          <CircleMarker key={`sh-${s.id}-${s.status}`} center={[s.lat, s.lon]} radius={9}
            className={SHELTER_CLASS[(s.status || '').toUpperCase()] || 'shelter-open'} pathOptions={{ weight: 2, fillOpacity: 0.95 }}>
            <Tooltip>Shelter: {s.name} · {s.status || 'unknown'}</Tooltip>
            <Popup>
              <strong>Shelter: {s.name}</strong>
              <div>Status: {s.status || 'unknown'}{s.capacity ? ` · capacity ${s.capacity}` : ''}</div>
              <div className="muted">
                From the mesh app · version {s.version} · {s.verified ? 'verified by an official' : 'not verified'}
              </div>
            </Popup>
          </CircleMarker>
        )
      })}
    </>
  )
}

