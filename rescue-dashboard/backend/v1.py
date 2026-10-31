"""API v1: everything the field sends and everything responders need.

- /api/v1/events   one envelope for every kind of data the mesh app sends
                   (sos, message, photo, road_block, and any future kind)
- /api/v1/media    photos, uploaded separately and in any order
- /api/v1/hazards  blocked roads / flooded zones that routing must avoid
- /api/v1/units    responder login, live location, current task, status
- /api/v1/outbox   replies that go back to the field (received, help coming, alerts, hazards)
- /api/v1/feed     everything that arrived, newest first, for the dashboard

Built to be extended: a new kind of event from the app is stored and shown on the
dashboard immediately; adding it to event_kinds.json gives it a label, an icon and
(optionally) turns it into an incident, with no code change.
"""
from __future__ import annotations

import base64
import io
import json
import os
import secrets
import uuid
from pathlib import Path
from typing import Any, Literal, Optional, Union

from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

import logic
import main as core
import routing

router = APIRouter(prefix="/api/v1")

KINDS_FILE = Path(__file__).parent / "event_kinds.json"
MEDIA = core.MEDIA
HAZARD_MERGE_M = 100           # citizen road-block reports this close are the same hazard
AERIAL_KINDS = {"drone"}          # fly straight; road blocks do not affect them
CITIZEN_CONFIRMS_NEEDED = int(os.environ.get("CITIZEN_CONFIRMS_NEEDED", "2"))
ATTACH_RADIUS_M = 200          # a message/photo this close to an open incident joins it
ATTACH_WINDOW_MIN = 60

SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS events (
  event_id TEXT PRIMARY KEY, kind TEXT, v INTEGER, created_at TEXT, received_at TEXT,
  device_id TEXT, lat REAL, lon REAL, acc REAL, via TEXT, payload TEXT, media TEXT,
  incident_id INTEGER, hazard_id INTEGER, handled_as TEXT);
CREATE TABLE IF NOT EXISTS media (
  media_id TEXT PRIMARY KEY, path TEXT, thumb TEXT, mime TEXT, size INTEGER, received_at TEXT);
CREATE TABLE IF NOT EXISTS hazards (
  id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, lat REAL, lon REAL, radius_m REAL,
  status TEXT, source TEXT, note TEXT, reports INTEGER, created_at TEXT, updated_at TEXT, by TEXT);
CREATE TABLE IF NOT EXISTS assignments (
  id INTEGER PRIMARY KEY AUTOINCREMENT, incident_id INTEGER, responder_id INTEGER, status TEXT,
  route TEXT, distance_m INTEGER, eta_min INTEGER, route_source TEXT, route_version INTEGER,
  reroute_reason TEXT, created_at TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS outbox (
  id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, ref TEXT, lat REAL, lon REAL, radius_m REAL,
  text TEXT, data TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS unit_tokens (token TEXT PRIMARY KEY, responder_id INTEGER, created_at TEXT);
"""


def init_v1(con) -> None:
    con.executescript(SCHEMA_V1)
    cols = {r["name"] for r in con.execute("PRAGMA table_info(responders)")}
    for col, typ in (("pin", "TEXT"), ("last_seen", "TEXT"), ("code", "TEXT")):
        if col not in cols:
            con.execute(f"ALTER TABLE responders ADD COLUMN {col} {typ}")
    for r in core.rows(con.execute("SELECT id, kind FROM responders WHERE code IS NULL")):
        con.execute("UPDATE responders SET code=?, pin=? WHERE id=?", (f"{r['kind'][:3].upper()}{r['id']}", "1234", r["id"]))


def now() -> str:
    return logic.now_utc().isoformat(timespec="seconds")


def kinds() -> dict:
    try:
        return json.loads(KINDS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


# ---------- contract ----------
class InlineMedia(BaseModel):
    media_id: str
    b64: Optional[str] = Field(default=None, description="Small image (thumbnail) as base64; the full photo can follow via POST /api/v1/media")
    mime: Optional[str] = "image/jpeg"


class Via(BaseModel):
    path: Optional[str] = Field(default=None, description="mesh / sms / internet / lora")
    hops: Optional[int] = None
    uploader: Optional[str] = Field(default=None, description="device id of the phone that uploaded it")
    held_seconds: Optional[int] = Field(default=None, description="how long it waited offline before upload")


class EventIn(BaseModel):
    """One envelope for everything the field sends. Unknown kinds are accepted and shown."""
    event_id: str = Field(description="UUID made on the phone that created it; uploads are idempotent")
    kind: str = Field(description="sos | message | photo | road_block | <any new kind>", max_length=40)
    v: int = 1
    created_at: Optional[str] = None
    device_id: Optional[str] = None
    lat: Optional[float] = Field(default=None, ge=-90, le=90)
    lon: Optional[float] = Field(default=None, ge=-180, le=180)
    acc: Optional[float] = None
    via: Optional[Via] = None
    payload: dict[str, Any] = Field(default_factory=dict)
    media: list[InlineMedia] = Field(default_factory=list)


class HazardIn(BaseModel):
    lat: float
    lon: float
    radius_m: float = Field(default=60, ge=10, le=3000)
    note: str = ""
    kind: Literal["road_block", "flood_zone", "landslide", "fire_zone", "other"] = "road_block"
    by: str = "Duty Officer"


class AlertIn(BaseModel):
    officer: str
    lat: float
    lon: float
    radius_m: float = Field(default=1000, ge=50, le=50000)
    text: str = Field(max_length=300)


class LoginIn(BaseModel):
    code: str
    pin: str


class LocationIn(BaseModel):
    lat: float
    lon: float
    acc: Optional[float] = None


class UnitStatusIn(BaseModel):
    status: Literal["en_route", "on_site", "resolved"]


class UnitHazardIn(BaseModel):
    lat: float
    lon: float
    radius_m: float = 60
    note: str = ""


# ---------- media ----------
def _store_media(con, media_id: str, raw: bytes, mime: str | None) -> None:
    if con.execute("SELECT 1 FROM media WHERE media_id=? AND path IS NOT NULL", (media_id,)).fetchone():
        return
    if len(raw) > 8_000_000:
        raise HTTPException(413, "Photo too large; send under 8 MB")
    ext = "png" if raw[:4] == b"\x89PNG" else "jpg"
    name = f"{uuid.uuid4().hex}.{ext}"
    (MEDIA / name).write_bytes(raw)
    thumb = None
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(raw))
        im.thumbnail((480, 480))
        tname = f"t_{name.rsplit('.', 1)[0]}.jpg"
        im.convert("RGB").save(MEDIA / tname, "JPEG", quality=75)
        thumb = f"/media/{tname}"
    except Exception:
        pass
    con.execute("INSERT OR REPLACE INTO media (media_id,path,thumb,mime,size,received_at) VALUES (?,?,?,?,?,?)",
                (media_id, f"/media/{name}", thumb, mime or "image/jpeg", len(raw), now()))


def media_urls(con, ids: list[str]) -> list[dict]:
    out = []
    for mid in ids:
        m = con.execute("SELECT * FROM media WHERE media_id=?", (mid,)).fetchone()
        out.append({"media_id": mid, "url": m["path"] if m else None, "thumb": (m["thumb"] or m["path"]) if m else None,
                    "pending": m is None})
    return out


@router.post("/media")
async def upload_media(media_id: str = Form(...), file: UploadFile = File(...)):
    """Full-size photo. Can arrive before or after the event that mentions it."""
    raw = await file.read()
    with core.db() as con:
        _store_media(con, media_id, raw, file.content_type)
        evs = core.rows(con.execute("SELECT event_id, incident_id FROM events WHERE media LIKE ?", (f'%"{media_id}"%',)))
        for e in evs:
            if e["incident_id"]:
                url = con.execute("SELECT path FROM media WHERE media_id=?", (media_id,)).fetchone()["path"]
                con.execute("UPDATE incidents SET photo=COALESCE(photo, ?) WHERE id=?", (url, e["incident_id"]))
    await core.hub.send("feed", {"media_id": media_id})
    return {"ok": True, "media_id": media_id}


@router.get("/media/{media_id}")
def get_media(media_id: str, thumb: bool = False):
    with core.db() as con:
        m = con.execute("SELECT * FROM media WHERE media_id=?", (media_id,)).fetchone()
    if not m:
        raise HTTPException(404, "Photo not received yet")
    rel = (m["thumb"] if thumb and m["thumb"] else m["path"]).replace("/media/", "")
    return FileResponse(MEDIA / rel)


# ---------- hazards and re-routing ----------
def hazard_objs(con) -> list[routing.Hazard]:
    return [routing.Hazard(h["id"], h["lat"], h["lon"], h["radius_m"])
            for h in core.rows(con.execute("SELECT * FROM hazards WHERE status='active'"))]


def unit_position(con, responder_id: int) -> tuple[float, float]:
    r = con.execute("SELECT lat, lon FROM responders WHERE id=?", (responder_id,)).fetchone()
    return (r["lat"], r["lon"])


def plan_assignment(con, a: dict, reason: str | None) -> list:
    """(Re)compute the route of one assignment. Returns notifications to send."""
    inc = con.execute("SELECT * FROM incidents WHERE id=?", (a["incident_id"],)).fetchone()
    start = unit_position(con, a["responder_id"])
    kind = con.execute("SELECT kind FROM responders WHERE id=?", (a["responder_id"],)).fetchone()["kind"]
    if kind in AERIAL_KINDS:
        r = routing.aerial(start, (inc["lat"], inc["lon"]))
    else:
        r = routing.plan(start, (inc["lat"], inc["lon"]), hazard_objs(con))
    version = (a.get("route_version") or 0) + 1
    con.execute("UPDATE assignments SET route=?, distance_m=?, eta_min=?, route_source=?, route_version=?, reroute_reason=?, updated_at=? WHERE id=?",
                (json.dumps(r["coords"]), r["distance_m"], r["eta_min"], r["source"], version, reason, now(), a["id"]))
    payload = {"assignment_id": a["id"], "unit_id": a["responder_id"], "incident_id": a["incident_id"],
               "route_version": version, "eta_min": r["eta_min"], "distance_m": r["distance_m"],
               "source": r["source"], "reason": reason, "no_road_route": r.get("no_road_route", False)}
    return [("reroute" if reason else "task_assigned", payload)]


def on_dispatch(con, incident_id: int, responder_id: int) -> list:
    """Called by core.approve after an officer approves."""
    con.execute("UPDATE assignments SET status='cancelled' WHERE incident_id=? AND status IN ('dispatched','en_route','on_site')", (incident_id,))
    cur = con.execute("INSERT INTO assignments (incident_id,responder_id,status,route_version,created_at,updated_at) VALUES (?,?,?,?,?,?)",
                      (incident_id, responder_id, "dispatched", 0, now(), now()))
    a = dict(con.execute("SELECT * FROM assignments WHERE id=?", (cur.lastrowid,)).fetchone())
    notes = plan_assignment(con, a, None)
    a = dict(con.execute("SELECT * FROM assignments WHERE id=?", (a["id"],)).fetchone())
    eta = f", about {a['eta_min']} min" if a["eta_min"] else ""
    unit = con.execute("SELECT name FROM responders WHERE id=?", (responder_id,)).fetchone()["name"]
    for r in core.rows(con.execute("SELECT external_id FROM reports WHERE incident_id=?", (incident_id,))):
        _outbox(con, "dispatched", r["external_id"], text=f"Help is coming: {unit}{eta}")
    return notes


def on_status(con, incident_id: int, status: str) -> list:
    final = "completed" if status == "resolved" else status
    con.execute("UPDATE assignments SET status=?, updated_at=? WHERE incident_id=? AND status IN ('dispatched','en_route','on_site')",
                (final, now(), incident_id))
    return [("assignment_status", {"incident_id": incident_id, "status": final})]


def reroute_affected(con, hazard: dict) -> list:
    """A road just became blocked: re-plan every active route that goes through it."""
    h = routing.Hazard(hazard["id"], hazard["lat"], hazard["lon"], hazard["radius_m"])
    notes = []
    for a in core.rows(con.execute(
            "SELECT a.* FROM assignments a JOIN responders r ON r.id=a.responder_id "
            "WHERE a.status IN ('dispatched','en_route') AND r.kind NOT IN ('drone')")):
        coords = json.loads(a["route"] or "[]")
        if coords and routing.route_hits(coords, h):
            why = f"Road blocked: {hazard['note'] or hazard['kind']} (hazard #{hazard['id']}, reported by {hazard['source']})"
            notes += plan_assignment(con, a, why)
            core.write_log(con, "system", "rerouted", a["incident_id"], unit=a["responder_id"], hazard=hazard["id"])
    return notes


def activate_hazard(con, hid: int, by: str) -> list:
    con.execute("UPDATE hazards SET status='active', by=?, updated_at=? WHERE id=?", (by, now(), hid))
    hz = dict(con.execute("SELECT * FROM hazards WHERE id=?", (hid,)).fetchone())
    core.write_log(con, by, "hazard_active", None, hazard=hid, note=hz["note"])
    _outbox(con, "hazard", str(hid), lat=hz["lat"], lon=hz["lon"], radius_m=hz["radius_m"],
            text=f"Avoid: {hz['note'] or hz['kind'].replace('_', ' ')}", data={"hazard_id": hid})
    return [("hazard", hz)] + reroute_affected(con, hz)


def add_hazard(con, *, lat, lon, radius_m, note, kind, source, by, trusted) -> tuple[dict, list]:
    """Trusted sources (officer, responder, camera) activate at once; citizen reports need
    CITIZEN_CONFIRMS_NEEDED nearby reports or an officer's confirmation."""
    for h in core.rows(con.execute("SELECT * FROM hazards WHERE status IN ('unverified','active') AND kind=?", (kind,))):
        if routing.haversine_m(h["lat"], h["lon"], lat, lon) <= HAZARD_MERGE_M:
            con.execute("UPDATE hazards SET reports=reports+1, radius_m=MAX(radius_m, ?), updated_at=?, note=CASE WHEN note='' THEN ? ELSE note END WHERE id=?",
                        (radius_m, now(), note, h["id"]))
            h = dict(con.execute("SELECT * FROM hazards WHERE id=?", (h["id"],)).fetchone())
            if h["status"] == "unverified" and (trusted or h["reports"] >= CITIZEN_CONFIRMS_NEEDED):
                notes = activate_hazard(con, h["id"], by if trusted else f"{h['reports']} citizen reports")
                return dict(con.execute("SELECT * FROM hazards WHERE id=?", (h["id"],)).fetchone()), notes
            return h, [("hazard", h)]
    cur = con.execute("INSERT INTO hazards (kind,lat,lon,radius_m,status,source,note,reports,created_at,updated_at,by) VALUES (?,?,?,?,?,?,?,1,?,?,?)",
                      (kind, lat, lon, radius_m, "unverified", source, note, now(), now(), by))
    hid = cur.lastrowid
    core.write_log(con, by, "hazard_reported", None, hazard=hid, source=source, note=note)
    h = dict(con.execute("SELECT * FROM hazards WHERE id=?", (hid,)).fetchone())
    if trusted or CITIZEN_CONFIRMS_NEEDED <= 1:
        notes = activate_hazard(con, hid, by)
        return dict(con.execute("SELECT * FROM hazards WHERE id=?", (hid,)).fetchone()), notes
    return h, [("hazard", h)]


@router.get("/hazards")
def list_hazards(include_cleared: bool = False):
    with core.db() as con:
        q = "SELECT * FROM hazards" + ("" if include_cleared else " WHERE status != 'cleared'")
        return core.rows(con.execute(q + " ORDER BY id DESC"))


@router.post("/hazards")
async def officer_hazard(body: HazardIn):
    with core.db() as con:
        h, notes = add_hazard(con, lat=body.lat, lon=body.lon, radius_m=body.radius_m, note=body.note,
                              kind=body.kind, source="officer", by=body.by, trusted=True)
    await _send(notes)
    return h


@router.post("/hazards/{hid}/confirm")
async def confirm_hazard(hid: int, by: str = "Duty Officer"):
    with core.db() as con:
        if not con.execute("SELECT 1 FROM hazards WHERE id=?", (hid,)).fetchone():
            raise HTTPException(404, "Hazard not found")
        notes = activate_hazard(con, hid, by)
    await _send(notes)
    return {"ok": True}


@router.post("/hazards/{hid}/clear")
async def clear_hazard(hid: int, by: str = "Duty Officer"):
    with core.db() as con:
        con.execute("UPDATE hazards SET status='cleared', by=?, updated_at=? WHERE id=?", (by, now(), hid))
        core.write_log(con, by, "hazard_cleared", None, hazard=hid)
        _outbox(con, "hazard_cleared", str(hid), text="Road open again", data={"hazard_id": hid})
    await _send([("hazard", {"id": hid, "status": "cleared"})])
    return {"ok": True}


# ---------- events (everything from the mesh app) ----------
def _attach_target(con, ev: dict) -> int | None:
    ref = ev["payload"].get("ref_event_id")
    if ref:
        row = con.execute("SELECT incident_id FROM events WHERE event_id=?", (ref,)).fetchone() or \
              con.execute("SELECT incident_id FROM reports WHERE external_id=?", (ref,)).fetchone()
        if row and row["incident_id"]:
            return row["incident_id"]
    if ev.get("lat") is None:
        return None
    t = logic.parse_time(ev.get("created_at"))
    best = None
    for i in core.rows(con.execute("SELECT * FROM incidents WHERE status != 'resolved'")):
        d = routing.haversine_m(i["lat"], i["lon"], ev["lat"], ev["lon"])
        gap = abs((t - logic.parse_time(i["last_report_at"])).total_seconds()) / 60
        if d <= ATTACH_RADIUS_M and gap <= ATTACH_WINDOW_MIN and (best is None or d < best[0]):
            best = (d, i["id"])
    return best[1] if best else None


def _attach_report(con, incident_id: int, ev: dict, text: str, photo_url: str | None):
    cur = con.execute(
        "INSERT OR IGNORE INTO reports (incident_id,external_id,source,type,message,lat,lon,people,reported_at,received_at,lang,via,photo) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (incident_id, ev["event_id"], "mesh", ev["kind"], text, ev.get("lat"), ev.get("lon"), 1,
         logic.parse_time(ev.get("created_at")).isoformat(timespec="seconds"), now(), ev["payload"].get("lang"),
         _via_text(ev), photo_url))
    if cur.rowcount == 0:
        return
    con.execute("UPDATE incidents SET report_count=report_count+1, photo=COALESCE(photo, ?), last_report_at=MAX(last_report_at, ?) WHERE id=?",
                (photo_url, logic.parse_time(ev.get("created_at")).isoformat(timespec="seconds"), incident_id))
    inc = dict(con.execute("SELECT * FROM incidents WHERE id=?", (incident_id,)).fetchone())
    reps = core.rows(con.execute("SELECT * FROM reports WHERE incident_id=? ORDER BY reported_at", (incident_id,)))
    con.execute("UPDATE incidents SET summary=? WHERE id=?", (logic.summarize(inc, reps), incident_id))


def _via_text(ev: dict) -> str | None:
    v = ev.get("via") or {}
    if not v:
        return None
    parts = [v.get("path") or "mesh"]
    if v.get("hops") is not None:
        parts.append(f"{v['hops']} hops")
    if v.get("held_seconds"):
        parts.append(f"held {round(v['held_seconds'] / 60)} min offline")
    return ", ".join(parts)


def _outbox(con, kind, ref, text="", lat=None, lon=None, radius_m=None, data=None):
    con.execute("INSERT INTO outbox (kind,ref,lat,lon,radius_m,text,data,created_at) VALUES (?,?,?,?,?,?,?,?)",
                (kind, ref, lat, lon, radius_m, text, json.dumps(data or {}), now()))


def handle_event(con, e: EventIn) -> tuple[dict, list]:
    if con.execute("SELECT 1 FROM events WHERE event_id=?", (e.event_id,)).fetchone():
        return {"event_id": e.event_id, "duplicate": True}, []
    ev = e.model_dump()
    ev["created_at"] = logic.parse_time(e.created_at).isoformat(timespec="seconds")
    for m in e.media:
        if m.b64:
            raw = base64.b64decode(m.b64.split(",", 1)[1] if m.b64.startswith("data:") else m.b64)
            _store_media(con, m.media_id, raw, m.mime)
    media_ids = [m.media_id for m in e.media]
    photo = next((x["url"] for x in media_urls(con, media_ids) if x["url"]), None)
    reg = kinds().get(e.kind, {})
    p = e.payload
    incident_id = hazard_id = None
    handled = "stored"
    notes: list = []

    if e.kind == "sos" or reg.get("creates_incident"):
        if e.lat is None or e.lon is None:
            raise HTTPException(422, f"{e.kind} needs lat and lon")
        itype = p.get("type") or reg.get("creates_incident") or "other"
        if itype not in logic.TYPE_WEIGHT:
            itype = "other"
        rep = core.ReportIn(external_id=e.event_id, source="mesh", type=itype, lat=e.lat, lon=e.lon,
                            message=str(p.get("message") or p.get("text") or "")[:500], people=int(p.get("people") or 1),
                            reported_at=ev["created_at"], lang=p.get("lang"), via=_via_text(ev))
        res = core.ingest(con, rep)
        incident_id = res["incident_id"]
        if photo and incident_id:
            con.execute("UPDATE incidents SET photo=COALESCE(photo, ?) WHERE id=?", (photo, incident_id))
            con.execute("UPDATE reports SET photo=? WHERE external_id=?", (photo, e.event_id))
        handled = "merged into incident" if res["merged"] else "new incident"
        _outbox(con, "received", e.event_id, text="Control room has your SOS")
    elif e.kind == "road_block":
        if e.lat is None or e.lon is None:
            raise HTTPException(422, "road_block needs lat and lon")
        h, notes = add_hazard(con, lat=e.lat, lon=e.lon, radius_m=float(p.get("radius_m") or 60),
                              note=str(p.get("note") or p.get("text") or "")[:200], kind=p.get("hazard_kind") or "road_block",
                              source=("responder" if (e.via and e.via.path == "responder")
                                      else f"official ({p['role']})" if p.get("trusted") and p.get("role") else "citizen"),
                              by=f"device {e.device_id or 'unknown'}", trusted=bool(p.get("trusted")))
        hazard_id = h["id"]
        handled = "hazard active" if h["status"] == "active" else f"hazard unverified ({h['reports']}/{CITIZEN_CONFIRMS_NEEDED})"
        _outbox(con, "received", e.event_id, text="Control room got your road report")
    elif e.kind in ("message", "photo"):
        incident_id = _attach_target(con, ev)
        text = str(p.get("text") or p.get("caption") or "")[:500]
        if incident_id:
            _attach_report(con, incident_id, ev, text or ("Photo" if e.kind == "photo" else ""), photo)
            handled = f"attached to incident #{incident_id}"
        elif e.kind == "photo" and p.get("type") and e.lat is not None:
            res = core.ingest(con, core.ReportIn(external_id=e.event_id, source="mesh", type=p["type"] if p["type"] in logic.TYPE_WEIGHT else "other",
                                                 lat=e.lat, lon=e.lon, message=text, reported_at=ev["created_at"], via=_via_text(ev)))
            incident_id = res["incident_id"]
            con.execute("UPDATE incidents SET photo=COALESCE(photo, ?) WHERE id=?", (photo, incident_id))
            handled = "new incident from photo"
        else:
            handled = "unlinked: officer can promote it"
        _outbox(con, "received", e.event_id, text="Control room has your message")

    con.execute("INSERT INTO events (event_id,kind,v,created_at,received_at,device_id,lat,lon,acc,via,payload,media,incident_id,hazard_id,handled_as) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (e.event_id, e.kind, e.v, ev["created_at"], now(), e.device_id, e.lat, e.lon, e.acc,
                 json.dumps(ev.get("via") or {}), json.dumps(p, ensure_ascii=False), json.dumps(media_ids), incident_id, hazard_id, handled))
    if e.kind not in ("sos", "road_block") and not reg.get("creates_incident"):
        core.write_log(con, e.device_id or "field", f"event_{e.kind}", incident_id, event_id=e.event_id, handled=handled)
    return {"event_id": e.event_id, "duplicate": False, "handled_as": handled, "incident_id": incident_id, "hazard_id": hazard_id}, notes


@router.post("/events")
async def post_events(body: Union[EventIn, list[EventIn]]):
    """Single event or a batch (a phone uploading everything it held offline). Idempotent."""
    items = body if isinstance(body, list) else [body]
    results, notes = [], []
    with core.db() as con:
        for e in items:
            r, n = handle_event(con, e)
            results.append(r)
            notes += n
    notes.append(("feed", {"count": len(items)}))
    notes.append(("changed", {}))
    await _send(notes)
    await _after_events(results)
    return results[0] if not isinstance(body, list) else {"received": len(items), "results": results}


async def _after_events(results) -> None:
    """After new reports are saved and shown: Verifier Agent, then Route Watch Agent."""
    fresh = [r for r in results if r and not r.get("duplicate")]
    await _verify_after([r.get("incident_id") for r in fresh])
    ids = [r.get("event_id") for r in fresh if r.get("event_id")]
    if ids:
        from fastapi.concurrency import run_in_threadpool
        from agents import route_watch
        notes = await run_in_threadpool(route_watch.watch, ids)
        if notes:
            await _send(notes + [("changed", {"route_watch": len(notes)})])


async def _verify_after(incident_ids) -> None:
    """Verifier Agent runs AFTER the SOS is saved and shown, so it never delays an SOS."""
    ids = [i for i in incident_ids if i]
    if not ids:
        return
    from fastapi.concurrency import run_in_threadpool
    from agents import verifier
    await run_in_threadpool(verifier.verify_many, ids)
    await _send([("changed", {"verified": ids})])


@router.post("/events/{event_id}/promote")
async def promote(event_id: str, type: str = "other", officer: str = "Duty Officer"):
    """Officer turns an unlinked message/photo into an incident."""
    with core.db() as con:
        ev = con.execute("SELECT * FROM events WHERE event_id=?", (event_id,)).fetchone()
        if not ev or ev["lat"] is None:
            raise HTTPException(404, "Event not found or has no location")
        p = json.loads(ev["payload"])
        res = core.ingest(con, core.ReportIn(external_id=f"promoted-{event_id}", source="manual", type=type if type in logic.TYPE_WEIGHT else "other",
                                             lat=ev["lat"], lon=ev["lon"], message=str(p.get("text") or p.get("caption") or "")[:500],
                                             reported_at=ev["created_at"]))
        photo = next((x["url"] for x in media_urls(con, json.loads(ev["media"])) if x["url"]), None)
        con.execute("UPDATE incidents SET photo=COALESCE(photo, ?) WHERE id=?", (photo, res["incident_id"]))
        con.execute("UPDATE events SET incident_id=?, handled_as=? WHERE event_id=?", (res["incident_id"], f"promoted by {officer}", event_id))
        core.write_log(con, officer, "event_promoted", res["incident_id"], event_id=event_id)
    await _send([("feed", {}), ("changed", {})])
    return res


@router.get("/feed")
def feed(limit: int = 80):
    reg = kinds()
    with core.db() as con:
        evs = core.rows(con.execute("SELECT * FROM events ORDER BY received_at DESC, rowid DESC LIMIT ?", (limit,)))
        for e in evs:
            e["payload"] = json.loads(e["payload"])
            e["via"] = json.loads(e["via"])
            e["media"] = media_urls(con, json.loads(e["media"]))
            e["display"] = reg.get(e["kind"], {"label": e["kind"].replace("_", " ").title(), "icon": "•", "fields": list(e["payload"].keys())[:4]})
    return evs


@router.get("/event-kinds")
def event_kinds():
    return kinds()


# ---------- area alerts and outbox (back to the field) ----------
@router.post("/alerts")
async def area_alert(body: AlertIn):
    with core.db() as con:
        _outbox(con, "alert", None, text=body.text, lat=body.lat, lon=body.lon, radius_m=body.radius_m, data={"officer": body.officer})
        core.write_log(con, body.officer, "area_alert", None, text=body.text, radius_m=body.radius_m)
    await _send([("alert", body.model_dump())])
    return {"ok": True}


@router.get("/outbox")
def outbox(since: Optional[str] = None, limit: int = 500):
    """Phones with internet pull this after uploading and broadcast it into the mesh."""
    with core.db() as con:
        q, args = "SELECT * FROM outbox", []
        if since:
            q += " WHERE created_at > ?"
            args.append(logic.parse_time(since).isoformat(timespec="seconds"))
        items = core.rows(con.execute(q + " ORDER BY id LIMIT ?", (*args, limit)))
    for i in items:
        i["data"] = json.loads(i["data"])
    return {"server_time": now(), "items": items}


@router.post("/outbox/import")
def outbox_import(items: list[dict]):
    """Edge server: copy replies pulled from the cloud into the local outbox (deduplicated)."""
    added = 0
    with core.db() as con:
        for i in items:
            origin = f"cloud:{i.get('id')}"
            if con.execute("SELECT 1 FROM outbox WHERE data LIKE ?", (f'%"origin": "{origin}"%',)).fetchone():
                continue
            data = dict(i.get("data") or {}, origin=origin)
            _outbox(con, i.get("kind"), i.get("ref"), text=i.get("text") or "", lat=i.get("lat"), lon=i.get("lon"),
                    radius_m=i.get("radius_m"), data=data)
            added += 1
    return {"added": added}


# ---------- responder units ----------
def unit_from_token(authorization: str | None) -> int:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Log in first")
    with core.db() as con:
        row = con.execute("SELECT responder_id FROM unit_tokens WHERE token=?", (authorization[7:],)).fetchone()
    if not row:
        raise HTTPException(401, "Session expired; log in again")
    return row["responder_id"]


@router.post("/units/login")
def unit_login(body: LoginIn):
    with core.db() as con:
        r = con.execute("SELECT * FROM responders WHERE upper(code)=upper(?)", (body.code.strip(),)).fetchone()
        if not r or not secrets.compare_digest(str(r["pin"] or ""), body.pin.strip()):
            raise HTTPException(401, "Wrong unit code or PIN")
        token = secrets.token_urlsafe(24)
        con.execute("INSERT INTO unit_tokens VALUES (?,?,?)", (token, r["id"], now()))
    return {"token": token, "unit": {k: r[k] for k in ("id", "name", "kind", "code")}}


@router.get("/units")
def units():
    with core.db() as con:
        us = core.rows(con.execute("SELECT id,name,kind,lat,lon,status,code,last_seen FROM responders ORDER BY id"))
        for u in us:
            a = con.execute("SELECT id, incident_id, status, route, eta_min, route_version, route_source, reroute_reason FROM assignments WHERE responder_id=? AND status IN ('dispatched','en_route','on_site') ORDER BY id DESC LIMIT 1", (u["id"],)).fetchone()
            u["assignment"] = dict(a, route=json.loads(a["route"] or "[]")) if a else None
    return us


@router.post("/units/me/location")
async def unit_location(body: LocationIn, authorization: Optional[str] = Header(None)):
    uid = unit_from_token(authorization)
    with core.db() as con:
        con.execute("UPDATE responders SET lat=?, lon=?, last_seen=? WHERE id=?", (body.lat, body.lon, now(), uid))
    await core.hub.send("unit_moved", {"unit_id": uid, "lat": body.lat, "lon": body.lon})
    return {"ok": True}


def task_for(con, uid: int) -> dict | None:
    a = con.execute("SELECT * FROM assignments WHERE responder_id=? AND status IN ('dispatched','en_route','on_site') ORDER BY id DESC LIMIT 1", (uid,)).fetchone()
    if not a:
        return None
    a = dict(a)
    a["route"] = json.loads(a["route"] or "[]")
    inc = core.enrich(dict(con.execute("SELECT * FROM incidents WHERE id=?", (a["incident_id"],)).fetchone()))
    inc["reports"] = core.rows(con.execute("SELECT source,type,message,reported_at,lang,via,photo FROM reports WHERE incident_id=? ORDER BY reported_at", (a["incident_id"],)))
    a["incident"] = inc
    return a


@router.get("/units/me/task")
def my_task(authorization: Optional[str] = Header(None)):
    uid = unit_from_token(authorization)
    with core.db() as con:
        me = dict(con.execute("SELECT id,name,kind,code,lat,lon,status FROM responders WHERE id=?", (uid,)).fetchone())
        return {"unit": me, "task": task_for(con, uid),
                "hazards": core.rows(con.execute("SELECT * FROM hazards WHERE status='active'")),
                "alerts": core.rows(con.execute("SELECT * FROM outbox WHERE kind='alert' ORDER BY id DESC LIMIT 5")),
                "route_alerts": _route_alerts(con, uid)}


def _route_alerts(con, uid):
    from agents import route_watch
    return route_watch.unit_alerts(con, uid)


@router.post("/units/me/status")
async def my_status(body: UnitStatusIn, authorization: Optional[str] = Header(None)):
    uid = unit_from_token(authorization)
    with core.db() as con:
        a = con.execute("SELECT * FROM assignments WHERE responder_id=? AND status IN ('dispatched','en_route','on_site') ORDER BY id DESC LIMIT 1", (uid,)).fetchone()
        name = con.execute("SELECT name FROM responders WHERE id=?", (uid,)).fetchone()["name"]
        if not a:
            raise HTTPException(409, "No active task")
        incident_id = a["incident_id"]
    return await core.set_status(incident_id, core.StatusIn(status=body.status, actor=name))


@router.post("/units/me/reroute")
async def my_reroute(body: LocationIn, authorization: Optional[str] = Header(None)):
    """Responder went off-route or wants a fresh route from where they are."""
    uid = unit_from_token(authorization)
    with core.db() as con:
        con.execute("UPDATE responders SET lat=?, lon=?, last_seen=? WHERE id=?", (body.lat, body.lon, now(), uid))
        a = con.execute("SELECT * FROM assignments WHERE responder_id=? AND status IN ('dispatched','en_route') ORDER BY id DESC LIMIT 1", (uid,)).fetchone()
        if not a:
            raise HTTPException(409, "No active task")
        notes = plan_assignment(con, dict(a), "New route from your current position")
    await _send(notes)
    return notes[0][1]


@router.post("/units/me/hazard")
async def my_hazard(body: UnitHazardIn, authorization: Optional[str] = Header(None)):
    """A responder on the ground reports a blocked road: trusted, active at once."""
    uid = unit_from_token(authorization)
    with core.db() as con:
        name = con.execute("SELECT name FROM responders WHERE id=?", (uid,)).fetchone()["name"]
        h, notes = add_hazard(con, lat=body.lat, lon=body.lon, radius_m=body.radius_m, note=body.note or f"reported by {name}",
                              kind="road_block", source="responder", by=name, trusted=True)
    await _send(notes + [("changed", {})])
    return h


@router.get("/routing/status")
def routing_status():
    net = routing.network()
    return {"engine": f"road graph: {net.name}, {len(net.node_ids)} junctions" if net else
            ("OSRM" if os.environ.get("USE_OSRM", "1") == "1" else "straight line"),
            "avoids_hazards": net is not None}


async def _send(notes: list) -> None:
    for event, data in notes:
        await core.hub.send(event, data)
