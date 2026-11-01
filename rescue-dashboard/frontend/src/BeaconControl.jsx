import { useState, useEffect } from 'react'
import { api } from './api.js'

export default function BeaconControl({
  officer = 'Duty Officer',
  shelters = [],
  onUpdate = () => {},
  selectedBeaconId = null,
  onClose = null,
  onFlyTo = () => {},
}) {
  const [beacons, setBeacons] = useState([])
  const [activeId, setActiveId] = useState(selectedBeaconId)
  const [capacity, setCapacity] = useState(50)
  const [status, setStatus] = useState('OPEN')
  const [note, setNote] = useState('')
  const [name, setName] = useState('')
  const [token, setToken] = useState('')
  const [feedback, setFeedback] = useState(null)
  const [busy, setBusy] = useState(false)
  const [creating, setCreating] = useState(false)

  // New beacon form
  const [newName, setNewName] = useState('')
  const [newLat, setNewLat] = useState('30.3165')
  const [newLon, setNewLon] = useState('78.0322')
  const [newCap, setNewCap] = useState(50)
  const [newNote, setNewNote] = useState('')
  const [fetchingGps, setFetchingGps] = useState(false)

  // Load beacons list from props or API
  useEffect(() => {
    loadBeacons()
  }, [shelters])

  const loadBeacons = async () => {
    try {
      const data = await api.beacons()
      setBeacons(data)
      // If activeId was specified or we have a saved beacon
      const targetId = activeId || selectedBeaconId || localStorage.getItem('resq_last_beacon_id') || data[0]?.id
      if (targetId && (!activeId || !data.some((b) => b.id === activeId))) {
        const found = data.find((b) => b.id === targetId) || data[0]
        if (found) selectBeacon(found)
      }
    } catch {
      // fallback to shelters filter
      const bList = shelters.filter(
        (s) => s.is_beacon || (s.role || '').toUpperCase() === 'CIVILIAN' || (s.name || '').toLowerCase().includes('beacon')
      )
      setBeacons(bList)
      if (bList.length > 0 && !activeId) selectBeacon(bList[0])
    }
  }

  const selectBeacon = (b) => {
    if (!b) return
    setActiveId(b.id)
    setCapacity(b.capacity ?? 50)
    setStatus((b.status || 'OPEN').toUpperCase())
    setNote(b.note || '')
    setName(b.name || '')
    setFeedback(null)
    const savedToken = localStorage.getItem(`resq_beacon_token_${b.id}`) || ''
    setToken(savedToken)
    localStorage.setItem('resq_last_beacon_id', b.id)
    if (b.lat && b.lon) {
      onFlyTo([b.lat, b.lon])
    }
  }

  const handleUpdate = async () => {
    if (!activeId) return
    setBusy(true)
    setFeedback(null)
    try {
      const payload = {
        capacity: Number(capacity),
        status,
        note,
        name,
        creator_token: token || undefined,
      }
      const res = await api.updateBeacon(activeId, payload)
      if (res.creator_token) {
        localStorage.setItem(`resq_beacon_token_${activeId}`, res.creator_token)
        setToken(res.creator_token)
      }
      setFeedback({ type: 'success', text: `Capacity updated to ${capacity} · Synced across COP map and mesh` })
      onUpdate()
      loadBeacons()
    } catch (err) {
      setFeedback({ type: 'error', text: err.message || 'Failed to update beacon' })
    } finally {
      setBusy(false)
    }
  }

  const handleStandDown = async () => {
    if (!activeId) return
    const confirmed = window.confirm(`Stand down and close SOS Beacon "${name || activeId}"?`)
    if (!confirmed) return
    setBusy(true)
    setFeedback(null)
    try {
      await api.closeBeacon(activeId, token)
      setStatus('CLOSED')
      setFeedback({ type: 'success', text: `Beacon "${name || activeId}" stood down and closed.` })
      onUpdate()
      await loadBeacons()
    } catch (err) {
      // Fallback: try patching status to CLOSED directly
      try {
        await api.updateBeacon(activeId, { status: 'CLOSED', creator_token: token || undefined })
        setStatus('CLOSED')
        setFeedback({ type: 'success', text: `Beacon "${name || activeId}" stood down and marked CLOSED.` })
        onUpdate()
        await loadBeacons()
      } catch (err2) {
        setFeedback({ type: 'error', text: err2.message || 'Failed to stand down beacon' })
      }
    } finally {
      setBusy(false)
    }
  }

  const handleCreate = async (e) => {
    e.preventDefault()
    setBusy(true)
    setFeedback(null)
    try {
      const res = await api.createBeacon({
        name: newName.trim() || 'Emergency SOS Beacon',
        lat: parseFloat(newLat),
        lon: parseFloat(newLon),
        capacity: parseInt(newCap, 10) || 50,
        status: 'OPEN',
        role: 'CIVILIAN',
        note: newNote.trim(),
      })
      if (res.creator_token && res.beacon?.id) {
        localStorage.setItem(`resq_beacon_token_${res.beacon.id}`, res.creator_token)
        localStorage.setItem('resq_last_beacon_id', res.beacon.id)
      }
      setFeedback({ type: 'success', text: `SOS Beacon "${res.beacon.name}" deployed with capacity ${res.beacon.capacity}!` })
      setCreating(false)
      setNewName('')
      setNewNote('')
      onUpdate()
      await loadBeacons()
      if (res.beacon) selectBeacon(res.beacon)
    } catch (err) {
      setFeedback({ type: 'error', text: err.message || 'Failed to deploy beacon' })
    } finally {
      setBusy(false)
    }
  }

  const handleUseGps = () => {
    if (!navigator.geolocation) {
      alert('Geolocation not supported by your browser')
      return
    }
    setFetchingGps(true)
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setNewLat(pos.coords.latitude.toFixed(6))
        setNewLon(pos.coords.longitude.toFixed(6))
        setFetchingGps(false)
      },
      () => {
        setFetchingGps(false)
        alert('Could not obtain current GPS location')
      },
      { timeout: 8000, enableHighAccuracy: true }
    )
  }

  const adjustCap = (delta) => {
    setCapacity((prev) => Math.max(0, (Number(prev) || 0) + delta))
  }

  const currentBeacon = beacons.find((b) => b.id === activeId)

  return (
    <div className="beacon-control-page">
      <div className="beacon-head">
        <div>
          <h3>🚨 SOS Beacon Live Control</h3>
          <p className="muted">Deploy beacons & adjust live capacity in real time across the control room</p>
        </div>
        {onClose && (
          <button className="fold-x" onClick={onClose} title="Close panel">✕</button>
        )}
      </div>

      {feedback && (
        <div className={`beacon-alert ${feedback.type}`}>
          {feedback.text}
        </div>
      )}

      {/* Selector and tabs */}
      <div className="beacon-top-actions">
        <div className="beacon-selector-wrap">
          <label>Active Beacon:</label>
          <select
            value={activeId || ''}
            onChange={(e) => {
              const b = beacons.find((item) => item.id === e.target.value)
              if (b) selectBeacon(b)
            }}
          >
            {beacons.map((b) => (
              <option key={b.id} value={b.id}>
                {b.name} ({b.capacity != null ? `${b.capacity} cap` : 'no cap'} · {b.status || 'OPEN'})
              </option>
            ))}
            {beacons.length === 0 && <option value="">No active SOS beacons found</option>}
          </select>
        </div>

        <button
          type="button"
          className="btn-create-beacon"
          onClick={() => setCreating(!creating)}
        >
          {creating ? '✕ Cancel' : '➕ Deploy New Beacon'}
        </button>
      </div>

      {creating ? (
        <form className="beacon-create-card" onSubmit={handleCreate}>
          <h4>Deploy New SOS Beacon</h4>
          <label>
            Beacon Name / Location:
            <input
              type="text"
              required
              placeholder="e.g. Clock Tower Shelter, Community Center"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
            />
          </label>

          <div className="geo-row">
            <label>
              Latitude:
              <input
                type="text"
                required
                value={newLat}
                onChange={(e) => setNewLat(e.target.value)}
              />
            </label>
            <label>
              Longitude:
              <input
                type="text"
                required
                value={newLon}
                onChange={(e) => setNewLon(e.target.value)}
              />
            </label>
            <button
              type="button"
              className="gps-btn"
              onClick={handleUseGps}
              disabled={fetchingGps}
              title="Use current device GPS"
            >
              {fetchingGps ? '📍 Locating…' : '📍 My GPS'}
            </button>
          </div>

          <label>
            Initial Evacuee Capacity (People):
            <input
              type="number"
              min="1"
              max="5000"
              required
              value={newCap}
              onChange={(e) => setNewCap(e.target.value)}
            />
          </label>

          <label>
            Emergency Needs / Situation Note:
            <textarea
              rows="2"
              placeholder="e.g. Sheltering 12 families; need clean drinking water and baby food"
              value={newNote}
              onChange={(e) => setNewNote(e.target.value)}
            />
          </label>

          <button type="submit" className="beacon-submit-btn" disabled={busy}>
            {busy ? 'Deploying…' : '🚨 Launch SOS Beacon onto Map'}
          </button>
        </form>
      ) : currentBeacon ? (
        <div className="beacon-manage-card">
          <div className="beacon-card-meta">
            <div className="meta-left">
              <strong>{currentBeacon.name}</strong>
              <div className="geo-tag">
                📍 {Number(currentBeacon.lat).toFixed(4)}°, {Number(currentBeacon.lon).toFixed(4)}°
                <button
                  type="button"
                  className="link-fly"
                  onClick={() => onFlyTo([currentBeacon.lat, currentBeacon.lon])}
                >
                  Locate on map
                </button>
              </div>
            </div>
            <div className="meta-right">
              <span className={`beacon-pill ${status.toLowerCase()}`}>
                {status}
              </span>
            </div>
          </div>

          {/* Big Live Capacity Controller */}
          <div className="capacity-controller-box">
            <div className="cap-label-row">
              <span className="cap-title">LIVE CAPACITY</span>
              <span className="cap-help">People actively accommodated</span>
            </div>

            <div className="cap-stepper-row">
              <button type="button" className="step-btn" onClick={() => adjustCap(-10)}>-10</button>
              <button type="button" className="step-btn" onClick={() => adjustCap(-1)}>-1</button>
              <div className="cap-readout-wrap">
                <input
                  type="number"
                  min="0"
                  max="10000"
                  value={capacity}
                  onChange={(e) => setCapacity(e.target.value)}
                  className="cap-number-input"
                />
                <span className="cap-unit">people</span>
              </div>
              <button type="button" className="step-btn" onClick={() => adjustCap(1)}>+1</button>
              <button type="button" className="step-btn" onClick={() => adjustCap(10)}>+10</button>
            </div>

            <input
              type="range"
              min="0"
              max="250"
              value={capacity || 0}
              onChange={(e) => setCapacity(Number(e.target.value))}
              className="cap-slider"
            />
          </div>

          {/* Operational Status */}
          <div className="beacon-status-selector">
            <span className="section-label">Beacon Operational Status:</span>
            <div className="status-button-group">
              <button
                type="button"
                className={`st-btn open ${status === 'OPEN' ? 'selected' : ''}`}
                onClick={() => setStatus('OPEN')}
              >
                🟢 OPEN (Accepting)
              </button>
              <button
                type="button"
                className={`st-btn full ${status === 'FULL' ? 'selected' : ''}`}
                onClick={() => setStatus('FULL')}
              >
                🔴 FULL (At Capacity)
              </button>
              <button
                type="button"
                className={`st-btn closed ${status === 'CLOSED' ? 'selected' : ''}`}
                onClick={() => setStatus('CLOSED')}
              >
                ⚪ CLOSED (Stood Down)
              </button>
            </div>
          </div>

          {/* Emergency note */}
          <div className="beacon-note-field">
            <label>
              Field Situation & Supplies Request:
              <textarea
                rows="2"
                placeholder="e.g. Drinking water delivered, power generator working, need 20 blankets"
                value={note}
                onChange={(e) => setNote(e.target.value)}
              />
            </label>
          </div>

          {/* Creator token & authorization */}
          <div className="beacon-token-row">
            <label>
              Creator Authorization Token:
              <input
                type="text"
                placeholder="Optional / Auto-saved for creator"
                value={token}
                onChange={(e) => setToken(e.target.value)}
              />
            </label>
          </div>

          {/* Action Buttons */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', marginTop: '4px' }}>
            <button
              type="button"
              className="beacon-save-btn"
              onClick={handleUpdate}
              disabled={busy}
            >
              {busy ? 'Updating…' : '💾 Update Live Capacity & Broadcast to Map'}
            </button>

            <button
              type="button"
              className="beacon-standdown-btn"
              onClick={handleStandDown}
              disabled={busy || status === 'CLOSED'}
              title="Deactivate and close this SOS Beacon"
            >
              🛑 Stand Down / Close Beacon
            </button>
          </div>
        </div>
      ) : (
        <div className="beacon-empty-state">
          <p>No SOS beacon currently deployed.</p>
          <button
            type="button"
            className="beacon-submit-btn"
            onClick={() => setCreating(true)}
          >
            Deploy First Beacon
          </button>
        </div>
      )}
    </div>
  )
}
