// One live strip of everything the AI agents did, newest first.
// Built only from data the backend already exposes (action log + field feed).
import { useEffect, useState } from 'react'

const AGENT = {
  triage: { name: 'Triage', cls: 'ag-triage' },
  verifier: { name: 'Verifier', cls: 'ag-verifier' },
  planner: { name: 'Planner', cls: 'ag-planner' },
  route: { name: 'Route Watch', cls: 'ag-route' },
  officer: { name: 'Officer', cls: 'ag-officer' },
  commander: { name: 'Commander', cls: 'ag-commander' },
}

const VERDICT = { confirmed: 'confirmed', likely: 'likely real', unverified: 'unverified', possible_fake: 'possible fake' }

function fromLog(e) {
  const d = e.detail || {}
  const id = e.incident_id ? `#${e.incident_id}` : ''
  switch (e.action) {
    case 'verified': return { agent: 'verifier', text: `${id} ${VERDICT[d.verdict] || d.verdict}` }
    case 'rerouted_precaution': return { agent: 'route', text: `${d.unit} re-routed (+${d.extra_min} min): obstacle reported on its road` }
    case 'reroute_proposed': return { agent: 'route', text: `${d.unit}: long detour (+${d.extra_min} min) waiting for officer` }
    case 'divert_proposed': return { agent: 'route', text: `${d.unit} passes #${d.new_incident}: stop-to-help suggested` }
    case 'diverted': return { agent: 'officer', text: `${d.unit} diverted to ${id}` }
    case 'route_alert_approved': return { agent: 'officer', text: `Approved Route Watch alert ${id}` }
    case 'route_alert_ignored': return { agent: 'officer', text: `Kept route for ${id}` }
    case 'ai_plan_decided': return { agent: 'planner', text: `Plan decided: ${d.approved} of ${d.proposed} approved by ${e.actor}` }
    case 'dispatch_approved': return d.via === 'AI dispatch plan' ? { agent: 'planner', text: `${d.responder} → ${id}` } : null
    case 'commander_asked': return { agent: 'commander', text: `${e.actor} asked: "${(d.question || '').slice(0, 60)}"` }
    case 'sitrep_generated': return { agent: 'commander', text: `Situation report: ${d.open} open, ${d.critical} critical` }
    case 'rerouted': return { agent: 'route', text: `Unit re-routed around a blocked road ${id}` }
    default: return null
  }
}

function fromFeed(ev) {
  const p = ev.payload || {}
  if (!p.ai_summary) return null
  return { agent: 'triage', text: `${ev.incident_id ? `#${ev.incident_id} ` : ''}${p.ai_urgency ? `${p.ai_urgency}: ` : ''}${p.ai_summary}` }
}

export function useAgentItems(tick, log) {
  const [feed, setFeed] = useState([])
  useEffect(() => {
    fetch('/api/v1/feed?limit=40').then((r) => r.json()).then(setFeed).catch(() => {})
  }, [tick])
  const items = [
    ...log.map((e) => { const x = fromLog(e); return x && { ...x, at: e.at, key: `l${e.seq}` } }),
    ...feed.map((ev) => { const x = fromFeed(ev); return x && { ...x, at: ev.received_at || ev.created_at, key: `f${ev.event_id}` } }),
  ].filter(Boolean)
  items.sort((a, b) => Date.parse(b.at) - Date.parse(a.at))
  return items
}

function hhmm(iso) {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

export default function AgentFeed({ items, max = 8, title = 'AI agents · live', open = true, onToggle = () => {} }) {
  if (!open) {
    return <button className="af-tab" onClick={onToggle} title="Show AI agent activity"><span className="af-live" />AI agents · {items.length} ▴</button>
  }
  return (
    <div className="agent-feed" aria-label="AI agent activity">
      <div className="af-head"><span className="af-live" />{title}
        <button className="fold-btn small" onClick={onToggle} aria-label="Fold AI agent activity" title="Fold">▾</button>
      </div>
      {items.length === 0 && <div className="af-empty">Agent actions appear here as reports arrive.</div>}
      <ol>
        {items.slice(0, max).map((x) => (
          <li key={x.key}>
            <span className={`af-tag ${AGENT[x.agent].cls}`}>{AGENT[x.agent].name}</span>
            <span className="af-text">{x.text}</span>
            <span className="af-at">{hhmm(x.at)}</span>
          </li>
        ))}
      </ol>
    </div>
  )
}
