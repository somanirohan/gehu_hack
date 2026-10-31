// Live feed of everything the field sent: SOS, messages, photos, road reports,
// and ANY new kind the mesh app adds later (shown with its fields automatically).
import { useEffect, useState } from 'react'

function ago(iso) {
  const m = Math.max(0, Math.round((Date.now() - Date.parse(iso)) / 60000))
  return m < 1 ? 'just now' : m < 60 ? `${m} min ago` : `${Math.floor(m / 60)} h ago`
}

function viaText(via) {
  if (!via || !Object.keys(via).length) return ''
  const parts = [via.path || 'mesh']
  if (via.hops != null) parts.push(`${via.hops} hops`)
  if (via.held_seconds) parts.push(`waited ${Math.round(via.held_seconds / 60)} min offline`)
  return parts.join(' · ')
}

export default function FeedPanel({ tick, onOpenIncident = () => {}, officer = 'Duty Officer' }) {
  const [items, setItems] = useState([])
  const [kind, setKind] = useState('all')

  useEffect(() => {
    fetch('/api/v1/feed?limit=80').then((r) => r.json()).then(setItems).catch(() => {})
  }, [tick])

  const kinds = ['all', ...new Set(items.map((i) => i.kind))]
  const shown = kind === 'all' ? items : items.filter((i) => i.kind === kind)

  const promote = async (e, type) => {
    await fetch(`/api/v1/events/${e.event_id}/promote?type=${type}&officer=${encodeURIComponent(officer)}`, { method: 'POST' })
  }

  return (
    <section className="panel feed" aria-label="Live feed from the field">
      <div className="panel-head">
        <h2>Live from the field</h2>
        <select value={kind} onChange={(e) => setKind(e.target.value)} aria-label="Filter by kind">
          {kinds.map((k) => <option key={k} value={k}>{k === 'all' ? 'Everything' : k.replaceAll('_', ' ')}</option>)}
        </select>
      </div>
      {shown.length === 0 && <p className="empty">Messages and photos from phones appear here the moment they reach the server.</p>}
      <ol className="feed-list">
        {shown.map((e) => (
          <li key={e.event_id} className={`fitem k-${e.kind}`}>
            <div className="fhead">
              <span className="ficon" aria-hidden="true">{e.display?.icon || '•'}</span>
              <strong>{e.display?.label || e.kind}</strong>
              <span className="fmeta">{ago(e.created_at)}</span>
            </div>
            {e.media?.length > 0 && (
              <div className="fphotos">
                {e.media.map((m) => m.pending
                  ? <span key={m.media_id} className="fpending">Photo arriving…</span>
                  : <a key={m.media_id} href={m.url} target="_blank" rel="noreferrer"><img src={m.thumb} alt="Photo from the field" /></a>)}
              </div>
            )}
            <dl className="fields">
              {(e.display?.fields || Object.keys(e.payload)).filter((f) => e.payload[f] != null && e.payload[f] !== '').map((f) => (
                <div key={f}><dt>{f.replaceAll('_', ' ')}</dt><dd>{String(e.payload[f])}</dd></div>
              ))}
            </dl>
            <div className="ffoot">
              <span>{viaText(e.via)}</span>
              <span className="handled">{e.handled_as}</span>
            </div>
            <div className="factions">
              {e.incident_id && <button onClick={() => onOpenIncident(e.incident_id)}>Open incident #{e.incident_id}</button>}
              {!e.incident_id && !e.hazard_id && e.lat != null && (
                <>
                  <button onClick={() => promote(e, 'other')}>Make incident</button>
                  <button onClick={() => promote(e, 'medical')}>Medical</button>
                </>
              )}
            </div>
          </li>
        ))}
      </ol>
    </section>
  )
}
