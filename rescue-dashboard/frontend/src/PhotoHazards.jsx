// Photo hazards: a photo from the field that the vision check thinks shows a road hazard
// (fallen tree, landslide, flooded road…). The officer decides: add a road blockage at the
// photo's coordinates (the photo is kept as proof) or dismiss it. Nothing is blocked automatically.
import { useEffect, useState } from 'react'
import L from 'leaflet'
import { Marker, Tooltip } from 'react-leaflet'

async function post(url, body) {
  const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
  const j = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(j.detail || r.statusText)
  return j
}

export const photoApi = {
  pending: () => fetch('/api/v1/field/suggestions').then((r) => r.json()),
  accept: (id, officer, spot) => post(`/api/v1/field/suggestions/${id}/accept`, { officer, ...(spot ? { lat: spot[0], lon: spot[1] } : {}) }),
  dismiss: (id, officer) => post(`/api/v1/field/suggestions/${id}/dismiss`, { officer }),
}

export function usePhotoHazards(tick) {
  const [items, setItems] = useState([])
  useEffect(() => { photoApi.pending().then(setItems).catch(() => {}) }, [tick])
  return items
}

const fmt = (n) => (n == null ? '' : Number(n).toFixed(5))

const cameraIcon = L.divIcon({
  className: 'mk-wrap',
  iconSize: [30, 30],
  iconAnchor: [15, 15],
  html: '<div class="mk-photo" aria-hidden="true">📷</div>',
})

export function PhotoHazardMarkers({ items, onSelect = () => {} }) {
  return items.filter((s) => s.lat != null).map((s) => (
    <Marker key={`ph${s.id}`} position={[s.lat, s.lon]} icon={cameraIcon} zIndexOffset={700}
      eventHandlers={{ click: () => onSelect(s.id) }}>
      <Tooltip direction="top">{s.label} · photo report, waiting for officer</Tooltip>
    </Marker>
  ))
}

export default function PhotoHazards({ items, officer, pickingId = null, onPickSpot = () => {}, onDone = () => {}, focusId = null }) {
  const [busy, setBusy] = useState(null)
  const [error, setError] = useState(null)
  if (!items.length) return null

  const act = async (id, fn) => {
    setBusy(id)
    setError(null)
    try { await fn(); onDone() } catch (e) { setError(e.message) } finally { setBusy(null) }
  }

  return (
    <div className="photo-hazards" role="region" aria-label="Photo reports waiting for a decision">
      {items.map((s) => (
        <div key={s.id} className={`ph-item ${focusId === s.id ? 'focus' : ''}`}>
          <div className="ph-title">
            <span className="ai-badge">Photo check</span>
            <span>{s.label} reported{s.blocks_road ? ' · road looks blocked' : ''}</span>
          </div>
          <a href={s.photo} target="_blank" rel="noreferrer"><img className="ph-photo" src={s.photo} alt={`Photo of ${s.label.toLowerCase()}`} /></a>
          {s.description && <div className="ph-text">{s.description}</div>}
          {s.caption && <div className="ph-caption">Sender wrote: “{s.caption}”</div>}
          <div className="ph-meta">
            {s.lat != null
              ? <>📍 {fmt(s.lat)}, {fmt(s.lon)} · {s.loc_source}</>
              : <strong className="ph-noloc">No location in this photo: pick the spot on the map</strong>}
          </div>
          <div className="ph-meta">AI confidence {Math.round((s.confidence || 0) * 100)}% · {s.model} · suggestion only</div>
          <div className="ra-actions">
            {s.lat != null && (
              <button className="primary-btn" disabled={busy === s.id} onClick={() => act(s.id, () => photoApi.accept(s.id, officer))}>
                Add road blockage here
              </button>
            )}
            <button className={s.lat == null ? 'primary-btn' : ''} disabled={busy === s.id} onClick={() => onPickSpot(s.id)}>
              {pickingId === s.id ? 'Click the map…' : s.lat == null ? 'Pick spot on map' : 'Different spot'}
            </button>
            <button disabled={busy === s.id} onClick={() => act(s.id, () => photoApi.dismiss(s.id, officer))}>Not a blockage</button>
          </div>
        </div>
      ))}
      {error && <div className="ph-error" role="alert">{error}</div>}
    </div>
  )
}
