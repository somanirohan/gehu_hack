// Dispatch Planner Agent (LangGraph): gather → plan → check → ⏸ officer → execute.
// Shows each graph step live, the proposed plan, and lets the officer approve per line.
import { useState } from 'react'

const NODE_LABEL = { gather: 'Tools', plan: 'AI plan', check: 'Safety check', human_approval: 'Officer', execute: 'Dispatch' }
const VERDICT = { confirmed: '✓ confirmed', likely: 'likely', unverified: 'unverified', possible_fake: '⚠ possible fake' }

async function post(url, body) {
  const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
  const j = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(j.detail || r.statusText)
  return j
}

export default function PlannerPanel({ officer, liveSteps = [], onOpenIncident = () => {} }) {
  const [run, setRun] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [picked, setPicked] = useState({})

  const start = async () => {
    setBusy(true); setError(''); setRun(null)
    try {
      const r = await post('/api/v1/agents/plan', { officer })
      setRun(r)
      setPicked(Object.fromEntries((r.checked || []).map((a) => [a.incident_id, !a.added_by_check])))
    } catch (e) { setError(e.message) } finally { setBusy(false) }
  }

  const decide = async (approveSome) => {
    setBusy(true); setError('')
    try {
      const ids = approveSome ? Object.entries(picked).filter(([, v]) => v).map(([k]) => Number(k)) : []
      setRun(await post(`/api/v1/agents/plan/${run.run_id}/decide`, { approved_incident_ids: ids, officer }))
    } catch (e) { setError(e.message) } finally { setBusy(false) }
  }

  const steps = run?.steps?.length ? run.steps : liveSteps
  const waiting = run?.status === 'waiting_for_officer'
  const nPicked = Object.values(picked).filter(Boolean).length

  return (
    <section className="panel planner" aria-label="AI dispatch planner">
      <div className="panel-head">
        <h2>AI Dispatch Planner</h2>
        <button className="primary-btn" onClick={start} disabled={busy}>{busy && !run ? 'Planning…' : 'Plan with AI'}</button>
      </div>
      <p className="ai-note">A LangGraph agent: it calls tools for real road ETAs, the AI plans all incidents together,
        code rejects anything impossible, and the graph pauses until you approve. Nothing moves without you.</p>

      <div className="graph-strip">
        {['gather', 'plan', 'check', 'human_approval', 'execute'].map((n) => {
          const done = steps.some((s) => s.node === n)
          const now = steps.length && steps[steps.length - 1].node === n
          return <span key={n} className={`gnode ${done ? 'done' : ''} ${now ? 'now' : ''}`}>{NODE_LABEL[n]}</span>
        })}
      </div>

      {error && <div className="error small">{error}</div>}

      {steps.length > 0 && (
        <ol className="steps">
          {steps.map((s, i) => <li key={i}><span className="snode">{NODE_LABEL[s.node] || s.node}</span>{s.text}<span className="sat">{s.at}</span></li>)}
        </ol>
      )}

      {run?.proposal && (
        <div className="plan-box">
          <div className="ai-head"><span className="ai-badge">Plan</span><span className="ai-src">{run.proposal.source}</span></div>
          <p className="ai-summary">{run.proposal.summary}</p>

          {(run.checked || []).length > 0 && (
            <table className="plan-table">
              <thead><tr><th /><th>Incident</th><th>Unit</th><th>ETA</th><th>Why</th></tr></thead>
              <tbody>
                {run.checked.map((a) => {
                  const ex = (run.executed || []).find((e) => e.incident_id === a.incident_id)
                  return (
                    <tr key={a.incident_id} className={`${ex ? (ex.done ? 'ok' : 'skip') : ''} ${a.added_by_check ? 'added' : ''}`}>
                      <td>{waiting
                        ? <input type="checkbox" checked={!!picked[a.incident_id]} onChange={() => setPicked((p) => ({ ...p, [a.incident_id]: !p[a.incident_id] }))} aria-label={`Approve incident ${a.incident_id}`} />
                        : ex ? (ex.done ? '✓' : '—') : '—'}</td>
                      <td><button className="linkish" onClick={() => onOpenIncident(a.incident_id)}>#{a.incident_id} {a.type}</button>
                        <div className="sub">{a.people} ppl · P{a.priority}{a.ai_urgency ? ` · ${a.ai_urgency}` : ''}{a.verification ? ` · ${VERDICT[a.verification] || a.verification}` : ''}</div></td>
                      <td>{a.unit}<div className="sub">{a.kind}{a.capable ? '' : ' (not usual type)'}</div></td>
                      <td>{a.eta_min ?? '?'} min<div className="sub">{a.distance_km} km</div></td>
                      <td className="why-cell">{a.reason}{ex && !ex.done ? <div className="sub">Not sent: {ex.why}</div> : null}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )}

          {(run.rejected || []).length > 0 && (
            <div className="rejected">
              <strong>Rejected by the safety check:</strong>
              <ul>{run.rejected.map((b, i) => <li key={i}>#{b.incident_id} → unit {b.unit_id}: {b.problem}</li>)}</ul>
            </div>
          )}

          {(run.proposal.waiting || []).length > 0 && (
            <div className="waiting">
              <strong>Still waiting:</strong>
              <ul>{run.proposal.waiting.map((w) => <li key={w.incident_id}>#{w.incident_id}: {w.reason}</li>)}</ul>
            </div>
          )}

          {waiting && (
            <div className="plan-actions">
              <button className="primary-btn" disabled={busy || nPicked === 0} onClick={() => decide(true)}>Approve selected ({nPicked})</button>
              <button disabled={busy} onClick={() => decide(false)}>Reject plan</button>
            </div>
          )}
          {run.status === 'done' && <p className="ai-note">Decision recorded in the tamper-evident log. Approved units got their task and route.</p>}
          {run.status === 'nothing_to_approve' && <p className="ai-note">Nothing to approve.</p>}
        </div>
      )}
    </section>
  )
}
