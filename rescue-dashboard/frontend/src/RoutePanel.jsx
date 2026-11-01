// Details of the route the officer clicked on the map, with the two actions:
//   Mark complete  -> incident resolved, unit free (same as the ground team's "Done")
//   Cancel route   -> unit free, incident back in the queue with a fresh suggestion
import { useState } from 'react'
import { liveApi } from './LiveLayers'

const STAGES = [['dispatched', 'Dispatched'], ['en_route', 'On the way'], ['on_site', 'Reached']]

function ago(iso) {
  if (!iso) return ''
  const m = Math.max(0, Math.round((Date.now() - Date.parse(iso)) / 60000))
  return m < 1 ? 'just now' : m < 60 ? `${m} min ago` : `${Math.floor(m / 60)} h ${m % 60} min ago`
}

export default function RoutePanel({ assignmentId, units, incidents, officer, onClose, onOpenIncident, onDone }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const unit = units.find((u) => u.assignment?.id === assignmentId)

  if (!unit) {
    return (
      <section className="panel route-panel" aria-label="Selected route">
        <div className="panel-head">
          <h2>Route</h2>
          <button className="rp-close" onClick={onClose} aria-label="Close route details">✕</button>
        </div>
        <p className="empty">This route has ended (completed or cancelled).</p>
      </section>
    )
  }

  const a = unit.assignment
  const inc = incidents.find((i) => i.id === a.incident_id)
  const stage = STAGES.findIndex(([s]) => s === a.status)

  const run = async (fn) => {
    setBusy(true)
    setError(null)
    try { await fn(); onDone() } catch (e) { setError(e.message) } finally { setBusy(false) }
  }

  const complete = () => {
    // eslint-disable-next-line no-alert
    if (!window.confirm(`Mark incident #${a.incident_id} as complete? ${unit.name} becomes free for new tasks.`)) return
    run(() => liveApi.completeRoute(a.id, officer))
  }
  const cancel = () => {
    // eslint-disable-next-line no-alert
    const reason = window.prompt(`Cancel ${unit.name}'s route to incident #${a.incident_id}?\n`
      + 'The unit becomes free and the incident goes back to the waiting list.\n\nReason (optional, shown to the unit):', '')
    if (reason == null) return
    run(() => liveApi.cancelRoute(a.id, officer, reason.trim()))
  }

  return (
    <section className="panel route-panel" aria-label="Selected route">
      <div className="panel-head">
        <h2>{unit.name}</h2>
        <button className="rp-close" onClick={onClose} aria-label="Close route details">✕</button>
      </div>

      <div className="rp-dest">
        → Incident #{a.incident_id}{inc ? ` · ${inc.type} · ${inc.people} ${inc.people === 1 ? 'person' : 'people'} · priority ${inc.priority}` : ''}
      </div>

      <ol className="rp-stages" aria-label="Progress">
        {STAGES.map(([s, label], k) => (
          <li key={s} className={k < stage ? 'done' : k === stage ? 'now' : ''}>{label}</li>
        ))}
      </ol>

      <dl className="rp-facts">
        <div><dt>ETA</dt><dd>{a.eta_min != null ? `${a.eta_min} min` : '–'}</dd></div>
        <div><dt>Distance</dt><dd>{a.distance_m != null ? `${(a.distance_m / 1000).toFixed(1)} km` : '–'}</dd></div>
        <div><dt>Route</dt><dd>{a.route_source || '–'}</dd></div>
        <div><dt>Dispatched</dt><dd>{ago(a.created_at)}</dd></div>
        <div><dt>Unit GPS</dt><dd>{unit.last_seen ? `live, ${ago(unit.last_seen)}` : 'no live GPS yet'}</dd></div>
      </dl>

      {a.reroute_reason && <div className="rp-reroute">Re-routed: {a.reroute_reason}</div>}
      {a.status === 'on_site' && <div className="rp-onsite">The ground team has reached the incident.</div>}

      <div className="rp-actions">
        <button className="primary-btn" disabled={busy} onClick={complete}>Mark complete</button>
        <button className="rp-cancel" disabled={busy} onClick={cancel}>Cancel route</button>
        <button disabled={busy} onClick={() => onOpenIncident(a.incident_id)}>Open incident</button>
      </div>
      {error && <div className="ph-error" role="alert">{error}</div>}
      <p className="rp-hint">The ground team can also mark it done on the responder site (On the way → Reached → Done).</p>
    </section>
  )
}
