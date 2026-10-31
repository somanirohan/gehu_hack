// Route Watch Agent alerts on the map: reports that landed on a unit's route.
// Pending ones (long detour, stop-to-help, no road left) wait for the officer.
import { useEffect, useState } from 'react'

const KIND = { reroute: 'Road reported blocked', divert: 'Stop to help?', no_road: 'No road around' }

export default function RouteAlerts({ tick, officer }) {
  const [items, setItems] = useState([])
  const [busy, setBusy] = useState(null)

  useEffect(() => {
    fetch('/api/v1/agents/route-alerts?limit=20').then((r) => r.json()).then(setItems).catch(() => {})
  }, [tick])

  const decide = async (id, approve) => {
    setBusy(id)
    try {
      await fetch(`/api/v1/agents/route-alerts/${id}/decide`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ approve, officer }),
      })
      const r = await fetch('/api/v1/agents/route-alerts?limit=20')
      setItems(await r.json())
    } finally { setBusy(null) }
  }

  const fresh = (a) => Date.now() - Date.parse(a.created_at) < 10 * 60 * 1000
  const shown = items.filter((a) => a.status === 'pending' || (a.status === 'auto' && fresh(a)))
  if (!shown.length) return null

  return (
    <div className="route-alerts" role="region" aria-label="Route Watch alerts">
      <div className="ra-head"><span className="ai-badge">Route Watch Agent</span></div>
      {shown.map((a) => (
        <div key={a.id} className={`ra-item ra-${a.status} ra-${a.kind}`}>
          <div className="ra-title">{a.status === 'auto' ? 'Re-routed automatically' : KIND[a.kind] || a.kind} · {a.unit}</div>
          <div className="ra-text">{a.text}</div>
          {a.photo && <a href={a.photo} target="_blank" rel="noreferrer"><img className="ra-photo" src={a.photo} alt="Photo from the report" /></a>}
          <div className="ra-meta">{a.distance_m} m from the route{a.extra_min != null && a.kind === 'reroute' ? ` · detour +${a.extra_min} min` : ''}</div>
          {a.status === 'pending' && (
            <div className="ra-actions">
              <button className="primary-btn" disabled={busy === a.id} onClick={() => decide(a.id, true)}>
                {a.kind === 'divert' ? 'Approve divert' : 'Confirm block & re-route'}
              </button>
              <button disabled={busy === a.id} onClick={() => decide(a.id, false)}>{a.kind === 'divert' ? 'Keep going' : 'Ignore'}</button>
            </div>
          )}
        </div>
      ))}
    </div>
  )
}
