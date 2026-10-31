// Commander Assistant Agent (LangGraph ReAct): the officer asks about the live situation
// in English / Hindi / Hinglish. Read-only: it answers and suggests, never changes anything.
// Plus a one-click Situation Report (numbers by code, words by AI, checked by code).
import { useEffect, useRef, useState } from 'react'

const SUGGESTIONS = [
  'Which incidents have no unit yet?',
  'What should I handle first?',
  'Boat kahan hai abhi?',
  'Any road blocked?',
  'Any fake reports?',
]

const TOOL_LABEL = {
  situation_overview: 'overview', list_incidents: 'incidents', incident_details: 'incident detail',
  list_units: 'units', blocked_roads: 'roads', shelters: 'shelters',
}

async function post(url, body) {
  const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
  const j = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(j.detail || r.statusText)
  return j
}

// Turn "#14" in an answer into a button that opens that incident.
function Linked({ text, onOpen }) {
  const parts = String(text).split(/(#\d+)/g)
  return parts.map((p, k) => (/^#\d+$/.test(p)
    ? <button key={k} className="linkish idlink" onClick={() => onOpen(Number(p.slice(1)))}>{p}</button>
    : <span key={k}>{p}</span>))
}

function Sitrep({ rep, onClose }) {
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    try { await navigator.clipboard.writeText(rep.markdown); setCopied(true); setTimeout(() => setCopied(false), 1500) } catch { /* ignore */ }
  }
  const print = () => {
    const w = window.open('', '_blank')
    if (!w) return
    const esc = rep.markdown.replace(/&/g, '&amp;').replace(/</g, '&lt;')
    w.document.write(`<title>SITREP ${rep.generated_at}</title><pre style="font:13px/1.5 'IBM Plex Mono',monospace;white-space:pre-wrap;padding:24px">${esc}</pre>`)
    w.document.close(); w.focus(); w.print()
  }
  return (
    <div className="sitrep">
      <div className="sitrep-head">
        <strong>Situation Report</strong>
        <span className="muted">{rep.generated_at}</span>
        <button className="fold-btn small" onClick={onClose} aria-label="Close report" title="Close">✕</button>
      </div>
      <pre className="sitrep-body">{rep.markdown}</pre>
      <div className="plan-actions">
        <button className="primary-btn" onClick={copy}>{copied ? 'Copied ✓' : 'Copy'}</button>
        <button onClick={print}>Print / PDF</button>
      </div>
      <p className="ai-note">Numbers counted by code. Text: {rep.source}.
        {rep.removed_lines ? ` Safety check removed ${rep.removed_lines} AI line(s) with numbers not in the data.` : ''}</p>
    </div>
  )
}

export default function CommanderPanel({ officer, onOpenIncident = () => {} }) {
  const [msgs, setMsgs] = useState([])
  const [q, setQ] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [rep, setRep] = useState(null)
  const [repBusy, setRepBusy] = useState(false)
  const end = useRef(null)

  useEffect(() => { end.current?.scrollIntoView({ block: 'nearest' }) }, [msgs, busy])

  const ask = async (text) => {
    const question = (text ?? q).trim()
    if (!question || busy) return
    setQ(''); setError(''); setBusy(true)
    const history = msgs.map((m) => ({ role: m.role, text: m.text }))
    setMsgs((m) => [...m, { role: 'user', text: question }])
    try {
      const r = await post('/api/v1/agents/ask', { question, history, officer })
      setMsgs((m) => [...m, { role: 'ai', text: r.answer, tools: r.tools || [], source: r.source, ms: r.ms }])
    } catch (e) { setError(e.message) } finally { setBusy(false) }
  }

  const makeSitrep = async () => {
    setRepBusy(true); setError('')
    try { setRep(await post('/api/v1/agents/sitrep', { officer })) } catch (e) { setError(e.message) } finally { setRepBusy(false) }
  }

  return (
    <section className="panel commander" aria-label="Commander Assistant">
      <div className="panel-head">
        <h2>Commander Assistant</h2>
        <button className="primary-btn" onClick={makeSitrep} disabled={repBusy}>{repBusy ? 'Writing…' : 'Situation Report'}</button>
      </div>
      <p className="ai-note">A LangGraph ReAct agent: it thinks, picks a tool, reads live data and answers.
        Read-only: it can only suggest; you approve on the dashboard. English, Hindi or Hinglish.</p>

      {rep && <Sitrep rep={rep} onClose={() => setRep(null)} />}

      <div className="chat">
        {msgs.length === 0 && (
          <div className="chat-empty">
            Ask about the live situation. Try:
            <div className="chips">
              {SUGGESTIONS.map((s) => <button key={s} className="qchip" onClick={() => ask(s)}>{s}</button>)}
            </div>
          </div>
        )}
        {msgs.map((m, k) => (
          <div key={k} className={`bubble ${m.role}`}>
            <div className="btext"><Linked text={m.text} onOpen={onOpenIncident} /></div>
            {m.role === 'ai' && (
              <div className="bmeta">
                {m.tools?.length > 0 && <span>looked at: {m.tools.map((t) => TOOL_LABEL[t] || t).join(', ')}</span>}
                <span>{m.source}{m.ms ? ` · ${(m.ms / 1000).toFixed(1)} s` : ''}</span>
              </div>
            )}
          </div>
        ))}
        {busy && <div className="bubble ai thinking">Thinking… reading live data</div>}
        <div ref={end} />
      </div>

      {msgs.length > 0 && (
        <div className="chips small">
          {SUGGESTIONS.slice(0, 3).map((s) => <button key={s} className="qchip" onClick={() => ask(s)} disabled={busy}>{s}</button>)}
          <button className="qchip" onClick={() => setMsgs([])} disabled={busy}>Clear</button>
        </div>
      )}

      {error && <div className="error small">{error}</div>}

      <form className="ask-row" onSubmit={(e) => { e.preventDefault(); ask() }}>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Ask… e.g. #14 ka status kya hai?" aria-label="Question" maxLength={500} />
        <button className="primary-btn" type="submit" disabled={busy || !q.trim()}>Ask</button>
      </form>
    </section>
  )
}
