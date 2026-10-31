// Map symbols: incidents as type icons (critical ones pulse), units as vehicle icons
// that glide smoothly between GPS updates. Pure display; no data logic here.
import { useEffect, useMemo, useRef } from 'react'
import L from 'leaflet'
import { Marker, Tooltip } from 'react-leaflet'

// Emergency status colours come from the design tokens (styles.css), identical in light and dark mode.
export const SEV = { critical: 'var(--crit)', high: 'var(--high)', medium: 'var(--med)', low: 'var(--low)' }

// 24x24 line glyphs (stroke = currentColor)
const G = {
  trapped: '<path d="M4 11l8-6 8 6"/><path d="M6 10v9h12v-9"/><path d="M3 21c2-1.5 4-1.5 6 0s4 1.5 6 0 4-1.5 6 0"/>',
  flood: '<path d="M3 15c2-1.5 4-1.5 6 0s4 1.5 6 0 4-1.5 6 0"/><path d="M3 19c2-1.5 4-1.5 6 0s4 1.5 6 0 4-1.5 6 0"/><path d="M12 3c2.5 3 4 5 4 7a4 4 0 0 1-8 0c0-2 1.5-4 4-7z"/>',
  fire: '<path d="M12 3c1 3 5 5 5 10a5 5 0 0 1-10 0c0-2 1-3.5 2-4.5 0 2 1 3 2 3 0-3-1-5 1-8.5z"/>',
  injured: '<path d="M12 5v14M5 12h14"/>',
  medical: '<path d="M12 5v14M5 12h14"/><circle cx="12" cy="12" r="9"/>',
  accident: '<path d="M5 16l1.5-5h11L19 16"/><path d="M4 16h16v3H4z"/><circle cx="7.5" cy="19" r="1"/><circle cx="16.5" cy="19" r="1"/><path d="M9 6l1.5 2M15 6l-1.5 2M12 4v3"/>',
  landslide: '<path d="M3 20h18L14 8l-3 4-2-2z"/><circle cx="16.5" cy="16" r="1"/><circle cx="12" cy="17" r="1"/>',
  collapse: '<path d="M4 20h16"/><path d="M6 20V9l6-4 6 4v11"/><path d="M9 20l3-6 3 6"/>',
  missing: '<circle cx="10.5" cy="10.5" r="5.5"/><path d="M15 15l5 5"/>',
  crowd: '<circle cx="8" cy="8" r="2.5"/><circle cx="16" cy="8" r="2.5"/><path d="M3.5 19c.5-3 2.3-5 4.5-5s4 2 4.5 5M11.5 19c.5-3 2.3-5 4.5-5s4 2 4.5 5"/>',
  fall: '<circle cx="12" cy="5" r="2"/><path d="M12 7l-2 6 4 2 1 5M10 13l-4 2M14 9l4 1"/>',
  other: '<path d="M12 4l9 16H3z"/><path d="M12 10v4M12 17v.5"/>',
  // units
  ambulance: '<path d="M3 16V8h11v8"/><path d="M14 11h4l3 3v2h-7"/><path d="M8.5 10v4M6.5 12h4"/><circle cx="7" cy="17.5" r="1.5"/><circle cx="17" cy="17.5" r="1.5"/>',
  rescue: '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3.5"/><path d="M6.5 6.5l3 3M17.5 6.5l-3 3M6.5 17.5l3-3M17.5 17.5l-3-3"/>',
  firetruck: '<path d="M3 16V9h12v7"/><path d="M15 12h3.5l2.5 2.5V16h-6"/><path d="M4 7l10-2"/><circle cx="7" cy="17.5" r="1.5"/><circle cx="17" cy="17.5" r="1.5"/>',
  boat: '<path d="M3 15h18l-3 4H6z"/><path d="M12 4v11M12 5l6 8h-6"/>',
  drone: '<circle cx="5" cy="6" r="2.5"/><circle cx="19" cy="6" r="2.5"/><circle cx="5" cy="18" r="2.5"/><circle cx="19" cy="18" r="2.5"/><rect x="9.5" y="9.5" width="5" height="5" rx="1"/><path d="M7 8l2.5 2.5M17 8l-2.5 2.5M7 16l2.5-2.5M17 16l-2.5-2.5"/>',
  police: '<path d="M12 3l7 3v5c0 4.5-3 8-7 10-4-2-7-5.5-7-10V6z"/><path d="M12 8l1.2 2.4 2.6.4-1.9 1.8.5 2.6-2.4-1.3-2.4 1.3.5-2.6-1.9-1.8 2.6-.4z"/>',
}

const svg = (glyph, size = 18) =>
  `<svg viewBox="0 0 24 24" width="${size}" height="${size}" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${glyph}</svg>`

export const glyph = (key) => G[key] || G.other

export function TypeIcon({ type, size = 16 }) {
  // eslint-disable-next-line react/no-danger
  return <span className="type-ico" dangerouslySetInnerHTML={{ __html: svg(glyph(type), size) }} />
}

function incidentIcon(inc, selected) {
  const c = SEV[inc.severity] || SEV.low
  const size = 34 + Math.min(inc.report_count || 1, 4) * 3
  const pulse = inc.severity === 'critical' && !['resolved'].includes(inc.status)
  const moving = ['dispatched', 'en_route', 'on_site'].includes(inc.status)
  return L.divIcon({
    className: 'mk-wrap',
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
    html: `<div class="mk-inc ${pulse ? 'pulse' : ''} ${selected ? 'sel' : ''} ${moving ? 'helped' : ''}" style="--c:${c};width:${size}px;height:${size}px">
      ${svg(glyph(inc.type), Math.round(size * 0.5))}
      <span class="mk-badge">${inc.priority}</span></div>`,
  })
}

const UNIT_GLYPH = { ambulance: 'ambulance', rescue: 'rescue', fire: 'firetruck', boat: 'boat', drone: 'drone', police: 'police' }

function unitIcon(u) {
  const busy = u.status !== 'available'
  return L.divIcon({
    className: 'mk-wrap',
    iconSize: [30, 30],
    iconAnchor: [15, 15],
    html: `<div class="mk-unit ${busy ? 'busy' : 'free'} k-${u.kind}">${svg(glyph(UNIT_GLYPH[u.kind] || 'rescue'), 17)}</div>`,
  })
}

export function IncidentMarkers({ incidents, selectedId, onSelect, statusLabel = {}, showLabels = true }) {
  return incidents.filter((i) => i.status !== 'resolved').map((i) => (
    <Marker key={`i${i.id}-${i.severity}-${i.priority}-${i.status}-${selectedId === i.id}-${showLabels}`} position={[i.lat, i.lon]}
      icon={incidentIcon(i, selectedId === i.id)} eventHandlers={{ click: () => onSelect(i.id) }}
      zIndexOffset={i.severity === 'critical' ? 600 : 400}>
      {showLabels ? (
        <Tooltip permanent direction="right" offset={[18, 0]} className={`map-label sev-${i.severity}`}>
          #{i.id} {i.type}
        </Tooltip>
      ) : (
        <Tooltip direction="top" offset={[0, -18]}>
          #{i.id} {i.type} · {i.people} {i.people === 1 ? 'person' : 'people'} · priority {i.priority} · {statusLabel[i.status] || i.status}
        </Tooltip>
      )}
    </Marker>
  ))
}

// A marker that glides to its new position instead of jumping (about 1.2 s, eased).
function GlidingMarker({ position, icon, children, zIndexOffset }) {
  const ref = useRef(null)
  const from = useRef(position)
  useEffect(() => {
    const m = ref.current
    if (!m) return undefined
    const a = from.current
    const b = position
    if (!a || (a[0] === b[0] && a[1] === b[1])) { from.current = b; return undefined }
    let raf
    const t0 = performance.now()
    const dur = 1200
    const step = (now) => {
      const k = Math.min(1, (now - t0) / dur)
      const e = k < 0.5 ? 2 * k * k : 1 - (-2 * k + 2) ** 2 / 2
      m.setLatLng([a[0] + (b[0] - a[0]) * e, a[1] + (b[1] - a[1]) * e])
      if (k < 1) raf = requestAnimationFrame(step)
      else from.current = b
    }
    raf = requestAnimationFrame(step)
    return () => { cancelAnimationFrame(raf); from.current = m.getLatLng ? [m.getLatLng().lat, m.getLatLng().lng] : b }
  }, [position[0], position[1]]) // eslint-disable-line react-hooks/exhaustive-deps
  return <Marker ref={ref} position={from.current || position} icon={icon} zIndexOffset={zIndexOffset}>{children}</Marker>
}

export function UnitMarkers({ responders, showLabels = true }) {
  const icons = useMemo(() => Object.fromEntries(responders.map((u) => [u.id, unitIcon(u)])),
    [responders.map((u) => `${u.id}${u.status}${u.kind}`).join()]) // eslint-disable-line react-hooks/exhaustive-deps
  return responders.map((u) => (
    <GlidingMarker key={`u${u.id}-${showLabels}`} position={[Number(u.lat), Number(u.lon)]} icon={icons[u.id]} zIndexOffset={800}>
      {showLabels ? (
        <Tooltip permanent direction="bottom" offset={[0, 14]} className={`map-label unit ${u.status === 'available' ? 'free' : 'busy'}`}>{u.name}</Tooltip>
      ) : (
        <Tooltip direction="top" offset={[0, -14]}>{u.name} · {u.kind} · {u.status === 'available' ? 'free' : 'on task'}</Tooltip>
      )}
    </GlidingMarker>
  ))
}
