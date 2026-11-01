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

      {showShelters && shelters.filter((s) => (s.status || '').toUpperCase() !== 'CLOSED').map((s) => {
        if (isBeacon(s)) {
          return (
            <Marker
              key={`beacon-${s.id}-${s.status}-${s.capacity}`}
              position={[s.lat, s.lon]}
              icon={beaconIcon(s)}
              zIndexOffset={3000}
              eventHandlers={{
                click: () => onManageBeacon(s.id),
              }}
            >
              <Tooltip permanent direction="top" offset={[0, -26]} className="beacon-map-label">
                🚨 {s.name} · 👥 {s.capacity != null ? s.capacity : '—'}
              </Tooltip>
              <Popup>
                <div className="beacon-popup">
                  <div className="beacon-popup-head">
                    <span className="beacon-badge">🚨 SOS Beacon</span>
                    <span className={`beacon-status-pill ${(s.status || 'open').toLowerCase()}`}>
                      {s.status || 'OPEN'}
                    </span>
                  </div>
                  <strong style={{ fontSize: '15px' }}>{s.name}</strong>
                  <div className="beacon-cap-box">
                    <span>Live Shelter Capacity:</span>
                    <span className="beacon-cap-val">👥 {s.capacity ?? '—'} people</span>
                  </div>
                  {s.note && (
                    <div style={{ margin: '6px 0', fontSize: '12px', background: 'var(--sage)', padding: '4px 8px', borderRadius: '4px' }}>
                      <strong>Situation Note:</strong> {s.note}
                    </div>
                  )}
                  <div className="muted" style={{ fontSize: '11px', marginTop: '4px' }}>
                    Origin: {s.origin || 'Field node'} · Version {s.version || 1}
                  </div>
                  <div style={{ marginTop: '8px' }}>
                    <button
                      type="button"
                      className="popup-beacon-btn"
                      onClick={() => onManageBeacon(s.id)}
                    >
                      🎛️ Control Beacon & Update Capacity
                    </button>
                  </div>
                </div>
              </Popup>
            </Marker>
          )
        }

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

