"""Control-room backend: intake, merging, ranking, approval, status, tamper-evident log.

Run:  uvicorn main:app --reload --port 8000
Docs: http://localhost:8000/docs
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import sqlite3
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import logic

BASE = Path(__file__).parent
DB_PATH = Path(os.environ.get("RESCUE_DB", BASE / "rescue.db"))
MEDIA = BASE / "media"
MEDIA.mkdir(exist_ok=True)

IncidentType = Literal["flood", "injured", "trapped", "fire", "fall", "medical", "crowd", "sensor", "collapse", "landslide", "accident", "missing", "other"]
Source = Literal["mesh", "camera", "sensor", "manual", "simulator"]
Status = Literal["new", "suggested", "dispatched", "en_route", "on_site", "resolved", "held"]


# ---------- data contract ----------
class ReportIn(BaseModel):
    """One SOS / alert. Same shape from the mesh app, the camera AI, sensors and the simulator."""
    external_id: str = Field(default_factory=lambda: uuid.uuid4().hex, description="Unique id set by the sender; re-sending the same id is ignored")
    source: Source
    type: IncidentType
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    message: str = Field(default="", max_length=500)
    people: int = Field(default=1, ge=1, le=500)
    reported_at: Optional[str] = Field(default=None, description="ISO time the SOS was created on the device")
    lang: Optional[str] = Field(default=None, description="en / hi / mr")
    via: Optional[str] = Field(default=None, description="e.g. 'mesh: 3 hops, uploaded by phone C'")
    photo_b64: Optional[str] = Field(default=None, description="JPEG/PNG as base64 (data: URL allowed), keep under ~200 KB")


class ApproveIn(BaseModel):
    officer: str
    responder_id: Optional[int] = None  # leave empty to accept the suggestion


class HoldIn(BaseModel):
    officer: str
    reason: str = ""


class StatusIn(BaseModel):
    status: Literal["en_route", "on_site", "resolved"]
    actor: str


class ResponderIn(BaseModel):
    name: str
    kind: Literal["ambulance", "rescue", "fire", "boat","drone","police"]
    lat: float
    lon: float


# ---------- database ----------
SCHEMA = """
CREATE TABLE IF NOT EXISTS incidents (
  id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT, status TEXT, lat REAL, lon REAL, people INTEGER,
  source TEXT, report_count INTEGER, first_report_at TEXT, last_report_at TEXT, photo TEXT,
  responder_id INTEGER, suggested_responder_id INTEGER, suggestion_reason TEXT, summary TEXT);
CREATE TABLE IF NOT EXISTS reports (
  id INTEGER PRIMARY KEY AUTOINCREMENT, incident_id INTEGER, external_id TEXT UNIQUE, source TEXT,
  type TEXT, message TEXT, lat REAL, lon REAL, people INTEGER, reported_at TEXT, received_at TEXT,
  lang TEXT, via TEXT, photo TEXT);
CREATE TABLE IF NOT EXISTS responders (
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, kind TEXT, lat REAL, lon REAL, status TEXT);
CREATE TABLE IF NOT EXISTS log (
  seq INTEGER PRIMARY KEY, at TEXT, actor TEXT, action TEXT, incident_id INTEGER,
  detail TEXT, prev_hash TEXT, hash TEXT);
"""

import places as _places  # noqa: E402  (Dehradun staging points; see dehradun_places.json)

DEMO_RESPONDERS = _places.demo_units()


def db() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_db(reset: bool = False) -> None:
    with db() as con:
        if reset:
            con.executescript(
                "DROP TABLE IF EXISTS incidents; "
                "DROP TABLE IF EXISTS reports; "
                "DROP TABLE IF EXISTS responders; "
                "DROP TABLE IF EXISTS log; "
                "DROP TABLE IF EXISTS events; DROP TABLE IF EXISTS media; DROP TABLE IF EXISTS hazards; "
                "DROP TABLE IF EXISTS assignments; DROP TABLE IF EXISTS outbox; DROP TABLE IF EXISTS unit_tokens; "
                "DROP TABLE IF EXISTS shelters; DROP TABLE IF EXISTS verifications; DROP TABLE IF EXISTS route_alerts; "
                "DROP TABLE IF EXISTS hazard_suggestions;")
        con.executescript(SCHEMA)
        if con.execute("SELECT COUNT(*) FROM responders").fetchone()[0] == 0:
            con.executemany("INSERT INTO responders (name, kind, lat, lon, status) VALUES (?,?,?,?, 'available')", DEMO_RESPONDERS)
        # Upgrade older databases in place (adds v1 tables and unit login codes)
        import v1  # noqa: PLC0415  (v1 imports this module, so import it late)
        import bridge  # noqa: PLC0415
        import field_media  # noqa: PLC0415
        v1.init_v1(con)
        bridge.init_bridge(con)
        field_media.init_field(con)


def rows(cur) -> list[dict]:
    return [dict(r) for r in cur.fetchall()]


# ---------- tamper-evident log ----------
def entry_hash(prev_hash: str, seq: int, at: str, actor: str, action: str, incident_id, detail: str) -> str:
    body = json.dumps([prev_hash, seq, at, actor, action, incident_id, detail], separators=(",", ":"))
    return hashlib.sha256(body.encode()).hexdigest()


def write_log(con, actor: str, action: str, incident_id=None, **detail) -> dict:
    last = con.execute("SELECT seq, hash FROM log ORDER BY seq DESC LIMIT 1").fetchone()
    seq = (last["seq"] + 1) if last else 1
    prev = last["hash"] if last else "0" * 64
    at = logic.now_utc().isoformat(timespec="seconds")
    d = json.dumps(detail, sort_keys=True, ensure_ascii=False)
    h = entry_hash(prev, seq, at, actor, action, incident_id, d)
    con.execute("INSERT INTO log VALUES (?,?,?,?,?,?,?,?)", (seq, at, actor, action, incident_id, d, prev, h))
    return {"seq": seq, "at": at, "actor": actor, "action": action, "incident_id": incident_id, "detail": detail, "hash": h}


def verify_log(con) -> dict:
    prev = "0" * 64
    broken = []
    entries = rows(con.execute("SELECT * FROM log ORDER BY seq"))
    for e in entries:
        expect = entry_hash(prev, e["seq"], e["at"], e["actor"], e["action"], e["incident_id"], e["detail"])
        if e["prev_hash"] != prev or e["hash"] != expect:
            broken.append(e["seq"])
        prev = e["hash"]
    return {"ok": not broken, "entries": len(entries), "broken_at": broken}


# ---------- live updates ----------
class Hub:
    def __init__(self):
        self.clients: set[WebSocket] = set()

    async def send(self, event: str, data) -> None:
        dead = []
        for ws in self.clients:
            try:
                await ws.send_json({"event": event, "data": data})
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)


hub = Hub()


@asynccontextmanager
async def lifespan(_app):
    init_db()
    field_media.resume_queue()  # photo checks still waiting when the server stopped
    yield


app = FastAPI(title="Rescue control room API", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/media", StaticFiles(directory=MEDIA), name="media")


def save_photo(b64: str | None) -> str | None:
    if not b64:
        return None
    if b64.startswith("data:"):
        b64 = b64.split(",", 1)[1]
    raw = base64.b64decode(b64)
    if len(raw) > 2_000_000:
        raise HTTPException(413, "Photo too large; send under 2 MB")
    ext = "png" if raw[:4] == b"\x89PNG" else "jpg"
    name = f"{uuid.uuid4().hex}.{ext}"
    (MEDIA / name).write_bytes(raw)
    return f"/media/{name}"


def enrich(inc: dict) -> dict:
    score, reason = logic.priority(inc)
    inc["priority"] = score
    inc["priority_reason"] = reason
    inc["severity"] = logic.severity_label(score)
    return inc


def suggest(con, inc: dict) -> dict:
    responders = rows(con.execute("SELECT * FROM responders"))
    best, reason = logic.suggest_responder(inc, responders)
    con.execute(
        "UPDATE incidents SET suggested_responder_id=?, suggestion_reason=?, status=CASE WHEN status IN ('new','held','suggested') THEN 'suggested' ELSE status END WHERE id=?",
        (best["id"] if best else None, reason, inc["id"]),
    )
    write_log(con, "system", "suggested", inc["id"], responder=best["name"] if best else None, reason=reason)
    return dict(con.execute("SELECT * FROM incidents WHERE id=?", (inc["id"],)).fetchone())


WAITING_STATUSES = ("new", "suggested", "held")


def ingest(con, r: ReportIn, waiting_only: bool = False) -> dict:
    """waiting_only: merge only into incidents that still wait for a unit (used for photos, voice
    notes and messages, so they never disappear into an incident a unit is already handling)."""
    if con.execute("SELECT 1 FROM reports WHERE external_id=?", (r.external_id,)).fetchone():
        return {"duplicate": True, "merged": False, "incident_id": None}
    rep = r.model_dump()
    rep["reported_at"] = logic.parse_time(r.reported_at).isoformat(timespec="seconds")
    photo = save_photo(r.photo_b64)
    open_incidents = rows(con.execute("SELECT * FROM incidents WHERE status != 'resolved'"))
    if waiting_only:
        open_incidents = [i for i in open_incidents if i["status"] in WAITING_STATUSES]
    target = next((i for i in open_incidents if logic.should_merge(rep, i)), None)
    if target:
        inc_id = target["id"]
        con.execute(
            "UPDATE incidents SET report_count=report_count+1, people=MAX(people, ?), last_report_at=MAX(last_report_at, ?), photo=COALESCE(photo, ?), source=CASE WHEN ?='camera' THEN 'camera' ELSE source END WHERE id=?",
            (r.people, rep["reported_at"], photo, r.source, inc_id),
        )
    else:
        cur = con.execute(
            "INSERT INTO incidents (type,status,lat,lon,people,source,report_count,first_report_at,last_report_at,photo) VALUES (?,?,?,?,?,?,1,?,?,?)",
            (r.type, "new", r.lat, r.lon, r.people, r.source, rep["reported_at"], rep["reported_at"], photo),
        )
        inc_id = cur.lastrowid
    con.execute(
        "INSERT INTO reports (incident_id,external_id,source,type,message,lat,lon,people,reported_at,received_at,lang,via,photo) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (inc_id, r.external_id, r.source, r.type, r.message, r.lat, r.lon, r.people, rep["reported_at"],
         logic.now_utc().isoformat(timespec="seconds"), r.lang, r.via, photo),
    )
    inc = dict(con.execute("SELECT * FROM incidents WHERE id=?", (inc_id,)).fetchone())
    reps = rows(con.execute("SELECT * FROM reports WHERE incident_id=? ORDER BY reported_at", (inc_id,)))
    con.execute("UPDATE incidents SET summary=? WHERE id=?", (logic.summarize(inc, reps), inc_id))
    write_log(con, f"{r.source}", "report_merged" if target else "incident_created", inc_id,
              external_id=r.external_id, type=r.type, via=r.via)
    inc = dict(con.execute("SELECT * FROM incidents WHERE id=?", (inc_id,)).fetchone())
    if inc["status"] in ("new", "suggested"):
        suggest(con, inc)
    return {"duplicate": False, "merged": bool(target), "incident_id": inc_id}


# ---------- routes ----------
@app.get("/api/health")
def health():
    return {"ok": True}


@app.post("/api/reports")
async def post_report(r: ReportIn):
    with db() as con:
        result = ingest(con, r)
    if not result["duplicate"]:
        await hub.send("changed", result)
    return result


@app.post("/api/reports/batch")
async def post_reports(items: list[ReportIn]):
    """For a phone that regains internet and uploads every SOS it was holding."""
    with db() as con:
        results = [ingest(con, r) for r in items]
    await hub.send("changed", {"count": len(results)})
    return {"received": len(items), "new": sum(not x["duplicate"] for x in results), "results": results}


@app.get("/api/incidents")
def list_incidents(include_resolved: bool = True):
    with db() as con:
        q = "SELECT * FROM incidents" + ("" if include_resolved else " WHERE status != 'resolved'")
        urg = _ai_urgency_map(con)
        items = []
        for i in rows(con.execute(q)):
            i["ai_urgency"] = urg.get(i["id"])  # Triage Agent reading of the latest report
            items.append(enrich(i))
        drill = {r[0] for r in con.execute("SELECT DISTINCT incident_id FROM reports WHERE via LIKE 'drill%'")}
        from agents import verifier
        checked = verifier.latest_map(con)
    for i in items:
        i["drill"] = i["id"] in drill  # practice data, shown with a DRILL badge
        i["verification"] = checked.get(i["id"])  # Verifier Agent verdict
    items.sort(key=lambda i: (i["status"] == "resolved", -i["priority"]))
    return items


def _ai_urgency_map(con, incident_id: int | None = None) -> dict:
    q = "SELECT incident_id, payload FROM events WHERE incident_id IS NOT NULL AND payload LIKE '%ai_urgency%'"
    args: tuple = ()
    if incident_id is not None:
        q += " AND incident_id=?"
        args = (incident_id,)
    out: dict = {}
    for iid, payload in con.execute(q + " ORDER BY rowid", args):
        out[iid] = json.loads(payload).get("ai_urgency")
    return out


def _ai_triage(con, incident_id: int):
    """Latest Triage Agent reading among this incident's reports (None if only word rules were used)."""
    row = con.execute("SELECT payload, created_at FROM events WHERE incident_id=? AND payload LIKE '%ai_summary%' ORDER BY rowid DESC LIMIT 1",
                      (incident_id,)).fetchone()
    if not row:
        return None
    p = json.loads(row[0])
    keys = ("ai_summary", "ai_urgency", "ai_injured", "ai_vulnerable", "ai_landmarks", "ai_needs", "ai_language",
            "ai_reasons", "category_source", "rule_guess", "confidence")
    return {k: p.get(k) for k in keys} | {"at": row[1]}


@app.get("/api/incidents/{incident_id}")
def get_incident(incident_id: int):
    with db() as con:
        inc = con.execute("SELECT * FROM incidents WHERE id=?", (incident_id,)).fetchone()
        if not inc:
            raise HTTPException(404, "Incident not found")
        inc = dict(inc)
        inc["ai_urgency"] = _ai_urgency_map(con, incident_id).get(incident_id)
        inc = enrich(inc)
        inc["reports"] = rows(con.execute("SELECT * FROM reports WHERE incident_id=? ORDER BY reported_at", (incident_id,)))
        # Each report's own photo / voice note and transcript (from the event it came from), so the
        # incident panel shows everything the field sent, not only the incident's first photo.
        import v1  # noqa: PLC0415
        for rep in inc["reports"]:
            ev = con.execute("SELECT kind, media, payload FROM events WHERE event_id=?",
                             ((rep["external_id"] or "").removeprefix("promoted-"),)).fetchone()
            rep["media"], rep["kind"] = [], None
            if ev:
                rep["kind"] = ev["kind"]
                rep["media"] = [m for m in v1.media_urls(con, json.loads(ev["media"] or "[]")) if m["url"]]
                p = json.loads(ev["payload"] or "{}")
                for k in ("transcript", "transcript_en", "spoken_language", "ai_description", "ai_hazard"):
                    if p.get(k) not in (None, ""):
                        rep[k] = p[k]
            if rep.get("photo") and not any(m["url"] == rep["photo"] for m in rep["media"]):
                rep["media"].insert(0, {"media_id": None, "url": rep["photo"], "thumb": rep["photo"], "mime": "image/jpeg"})
        inc["ai_triage"] = _ai_triage(con, incident_id)
        from agents import verifier
        inc["verification"] = verifier.latest(con, incident_id)
        inc["history"] = [dict(e, detail=json.loads(e["detail"])) for e in rows(con.execute("SELECT * FROM log WHERE incident_id=? ORDER BY seq", (incident_id,)))]
    return inc


@app.post("/api/incidents/{incident_id}/suggest")
async def resuggest(incident_id: int):
    with db() as con:
        inc = con.execute("SELECT * FROM incidents WHERE id=?", (incident_id,)).fetchone()
        if not inc:
            raise HTTPException(404, "Incident not found")
        out = suggest(con, dict(inc))
    await hub.send("changed", {"incident_id": incident_id})
    return enrich(out)


@app.post("/api/incidents/{incident_id}/approve")
async def approve(incident_id: int, body: ApproveIn):
    with db() as con:
        inc = con.execute("SELECT * FROM incidents WHERE id=?", (incident_id,)).fetchone()
        if not inc:
            raise HTTPException(404, "Incident not found")
        rid = body.responder_id or inc["suggested_responder_id"]
        if not rid:
            raise HTTPException(409, "No responder suggested; pick one")
        resp = con.execute("SELECT * FROM responders WHERE id=?", (rid,)).fetchone()
        if not resp or resp["status"] != "available":
            raise HTTPException(409, "That responder is not available")
        con.execute("UPDATE incidents SET status='dispatched', responder_id=? WHERE id=?", (rid, incident_id))
        con.execute("UPDATE responders SET status='busy' WHERE id=?", (rid,))
        write_log(con, body.officer, "dispatch_approved", incident_id, responder=resp["name"],
                  overrode_suggestion=bool(body.responder_id and body.responder_id != inc["suggested_responder_id"]))
        import v1  # noqa: PLC0415
        notes = v1.on_dispatch(con, incident_id, rid)
    for event, data in notes:
        await hub.send(event, data)
    await hub.send("changed", {"incident_id": incident_id})
    return get_incident(incident_id)


@app.post("/api/incidents/{incident_id}/hold")
async def hold(incident_id: int, body: HoldIn):
    with db() as con:
        if not con.execute("SELECT 1 FROM incidents WHERE id=?", (incident_id,)).fetchone():
            raise HTTPException(404, "Incident not found")
        con.execute("UPDATE incidents SET status='held' WHERE id=?", (incident_id,))
        write_log(con, body.officer, "held", incident_id, reason=body.reason)
    await hub.send("changed", {"incident_id": incident_id})
    return get_incident(incident_id)


@app.post("/api/incidents/{incident_id}/status")
async def set_status(incident_id: int, body: StatusIn):
    with db() as con:
        inc = con.execute("SELECT * FROM incidents WHERE id=?", (incident_id,)).fetchone()
        if not inc:
            raise HTTPException(404, "Incident not found")
        if inc["status"] not in ("dispatched", "en_route", "on_site"):
            raise HTTPException(409, "Only a dispatched incident can change status")
        con.execute("UPDATE incidents SET status=? WHERE id=?", (body.status, incident_id))
        if body.status == "resolved" and inc["responder_id"]:
            con.execute("UPDATE responders SET status='available' WHERE id=?", (inc["responder_id"],))
        write_log(con, body.actor, f"status_{body.status}", incident_id)
        import v1  # noqa: PLC0415
        notes = v1.on_status(con, incident_id, body.status, body.actor)
    for event, data in notes:
        await hub.send(event, data)
    await hub.send("changed", {"incident_id": incident_id})
    return get_incident(incident_id)


@app.get("/api/responders")
def list_responders():
    with db() as con:
        return rows(con.execute("SELECT * FROM responders ORDER BY id"))


@app.post("/api/responders")
async def add_responder(body: ResponderIn):
    with db() as con:
        cur = con.execute("INSERT INTO responders (name,kind,lat,lon,status) VALUES (?,?,?,?,'available')",
                          (body.name, body.kind, body.lat, body.lon))
        write_log(con, "admin", "responder_added", None, name=body.name, kind=body.kind)
    await hub.send("changed", {})
    return {"id": cur.lastrowid}


@app.get("/api/log")
def get_log(limit: int = 200):
    with db() as con:
        items = rows(con.execute("SELECT * FROM log ORDER BY seq DESC LIMIT ?", (limit,)))
    return [dict(e, detail=json.loads(e["detail"])) for e in items]


@app.get("/api/log/verify")
def log_verify():
    with db() as con:
        return verify_log(con)


@app.get("/api/stats")
def stats():
    with db() as con:
        incs = rows(con.execute("SELECT * FROM incidents"))
        n_reports = con.execute("SELECT COUNT(*) FROM reports").fetchone()[0]
        mesh = con.execute("SELECT COUNT(*) FROM reports WHERE source='mesh'").fetchone()[0]
        disp = rows(con.execute(
            "SELECT i.first_report_at AS t0, l.at AS t1 FROM incidents i JOIN log l ON l.incident_id=i.id AND l.action='dispatch_approved'"))
        resp = rows(con.execute("SELECT status FROM responders"))
    waits = sorted((logic.parse_time(d["t1"]) - logic.parse_time(d["t0"])).total_seconds() / 60 for d in disp)
    median = round(waits[len(waits) // 2], 1) if waits else None
    by = lambda s: sum(i["status"] == s for i in incs)
    return {
        "incidents": len(incs), "open": len(incs) - by("resolved"), "resolved": by("resolved"),
        "awaiting_approval": by("suggested") + by("new"), "held": by("held"),
        "reports": n_reports, "mesh_reports": mesh, "merged_reports": n_reports - len(incs),
        "median_minutes_to_dispatch": median,
        "responders_available": sum(r["status"] == "available" for r in resp), "responders_total": len(resp),
    }


@app.post("/api/demo/reset")
async def demo_reset():
    for f in MEDIA.glob("*"):
        f.unlink()
    init_db(reset=True)
    with db() as con:
        write_log(con, "admin", "demo_reset", None)
    await hub.send("changed", {"reset": True})
    return {"ok": True}


@app.websocket("/ws")
async def ws(socket: WebSocket):
    await socket.accept()
    hub.clients.add(socket)
    try:
        while True:
            await socket.receive_text()
    except WebSocketDisconnect:
        hub.clients.discard(socket)


import bridge  # noqa: E402
import v1  # noqa: E402
import field_media  # noqa: E402

app.include_router(v1.router)
app.include_router(bridge.router)
app.include_router(bridge.shelter_router)
app.include_router(field_media.router)
import chat_proxy  # noqa: E402
app.include_router(chat_proxy.router)  # mesh app chatbot -> ai-surveillance chatbot server
app.include_router(_places.router)
from agents import api as _agents_api  # noqa: E402
app.include_router(_agents_api.router)

RESPONDER_DIST = BASE.parent / "responder" / "dist"
if RESPONDER_DIST.exists():
    app.mount("/responder", StaticFiles(directory=RESPONDER_DIST, html=True), name="responder")

DIST = BASE.parent / "frontend" / "dist"
if DIST.exists():
    app.mount("/", StaticFiles(directory=DIST, html=True), name="dashboard")
