"""Voice notes and photos from the field.

POST /api/v1/field/voice   audio (any language)  -> speech to text -> English -> the normal
                           pipeline (Triage Agent / word rules -> SOS, road block or message)
POST /api/v1/field/photo   photo -> stored + shown in the feed; a vision model checks whether it
                           shows a road hazard (fallen tree, landslide, flooded road...). If so,
                           a "photo hazard" suggestion with the photo's coordinates asks the officer
                           to add a road blockage there, with the photo kept as proof.
GET  /api/v1/field/suggestions                pending photo-hazard prompts
POST /api/v1/field/suggestions/{id}/accept    officer adds the blockage (photo attached as proof)
POST /api/v1/field/suggestions/{id}/dismiss   officer says it's not a blockage

Rules carried over from the rest of the system: AI output is a labelled suggestion, nothing is
blocked without an officer, and if the AI is unavailable the audio/photo is still stored and shown.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

import bridge
import main as core
import v1
from agents import media_ai, triage

router = APIRouter(prefix="/api/v1/field")

MAX_AUDIO = 20_000_000
MIN_CONFIDENCE = float(os.environ.get("PHOTO_HAZARD_MIN_CONF", "0.4"))
ROAD_HAZARDS = {"fallen_tree", "landslide", "flooded_road", "collapsed_structure", "damaged_bridge",
                "power_line_down", "fire", "vehicle_accident", "debris"}
HAZARD_LABEL = {"fallen_tree": "Fallen tree", "landslide": "Landslide", "flooded_road": "Flooded road",
                "collapsed_structure": "Collapsed structure", "damaged_bridge": "Damaged bridge",
                "power_line_down": "Power line down", "fire": "Fire", "vehicle_accident": "Vehicle accident",
                "debris": "Debris on road"}
# hazards.kind values the routing layer understands
HAZARD_KIND = {"landslide": "landslide", "flooded_road": "flood_zone", "fire": "fire_zone"}
PEOPLE_TYPE = {"collapsed_structure": "collapse", "landslide": "landslide", "flooded_road": "flood", "fire": "fire",
               "vehicle_accident": "accident"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS hazard_suggestions (
  id INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT, media_id TEXT, photo TEXT, photo_sha256 TEXT,
  lat REAL, lon REAL, loc_source TEXT, hazard TEXT, label TEXT, blocks_road INTEGER, confidence REAL,
  description TEXT, caption TEXT, radius_m REAL, model TEXT, status TEXT, hazard_id INTEGER,
  decided_by TEXT, decided_at TEXT, created_at TEXT);
"""


def init_field(con) -> None:
    con.executescript(SCHEMA)
    cols = {r["name"] for r in con.execute("PRAGMA table_info(hazards)")}
    if "photo" not in cols:
        con.execute("ALTER TABLE hazards ADD COLUMN photo TEXT")


# ---------- helpers ----------
def _event_id(given: Optional[str], prefix: str) -> str:
    return (given or "").strip()[:80] or f"{prefix}-{uuid.uuid4().hex[:12]}"


def _created(created_at: Optional[str]) -> str:
    return created_at or datetime.now(timezone.utc).isoformat(timespec="seconds")


def _check_coords(lat: Optional[float], lon: Optional[float]) -> tuple[Optional[float], Optional[float]]:
    if lat is None or lon is None:
        return None, None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise HTTPException(422, "lat/lon out of range")
    return lat, lon


def _seen(event_id: str) -> bool:
    with core.db() as con:
        return con.execute("SELECT 1 FROM events WHERE event_id=?", (event_id,)).fetchone() is not None


def _store_audio(con, media_id: str, raw: bytes, mime: Optional[str], filename: Optional[str]) -> str:
    if con.execute("SELECT path FROM media WHERE media_id=? AND path IS NOT NULL", (media_id,)).fetchone():
        return con.execute("SELECT path FROM media WHERE media_id=?", (media_id,)).fetchone()["path"]
    ext = _audio_name(filename, mime).rsplit(".", 1)[-1]
    name = f"{uuid.uuid4().hex}.{ext}"
    (core.MEDIA / name).write_bytes(raw)
    con.execute("INSERT OR REPLACE INTO media (media_id,path,thumb,mime,size,received_at) VALUES (?,?,?,?,?,?)",
                (media_id, f"/media/{name}", None, mime if (mime or "").startswith("audio/") else f"audio/{ext}",
                 len(raw), v1.now()))
    return f"/media/{name}"


AUDIO_EXT = ("m4a", "mp3", "wav", "ogg", "oga", "opus", "webm", "aac", "amr", "3gp", "flac", "mp4")
AUDIO_MIME_EXT = {"audio/mpeg": "mp3", "audio/wav": "wav", "audio/x-wav": "wav", "audio/ogg": "ogg",
                  "audio/webm": "webm", "audio/aac": "aac", "audio/amr": "amr", "audio/3gpp": "3gp"}


def _audio_name(filename: Optional[str], mime: Optional[str]) -> str:
    """Speech-to-text picks the decoder from the file name: never pass on 'x.bin' or no extension."""
    ext = filename.rsplit(".", 1)[-1].lower() if filename and "." in filename else ""
    if ext in AUDIO_EXT:
        return filename
    return f"voice.{AUDIO_MIME_EXT.get(mime or '', 'm4a')}"


def exif_gps(raw: bytes) -> tuple[Optional[float], Optional[float]]:
    """GPS position written into the photo by the phone's camera, if any."""
    try:
        from PIL import Image
        gps = Image.open(io.BytesIO(raw)).getexif().get_ifd(0x8825)
        if not gps or 2 not in gps or 4 not in gps:
            return None, None

        def deg(v) -> float:
            d, m, s = (float(x) for x in v)
            return d + m / 60 + s / 3600

        lat, lon = deg(gps[2]), deg(gps[4])
        if str(gps.get(1, "N")).upper().startswith("S"):
            lat = -lat
        if str(gps.get(3, "E")).upper().startswith("W"):
            lon = -lon
        if -90 <= lat <= 90 and -180 <= lon <= 180 and (lat, lon) != (0.0, 0.0):
            return round(lat, 6), round(lon, 6)
    except Exception:
        pass
    return None, None


async def _finish(results: list, notes: list) -> None:
    notes = notes + [("feed", {"count": 1, "source": "field-media"}), ("changed", {})]
    await v1._send(notes)
    await v1._after_events(results)


# ---------- voice ----------
@router.post("/voice")
async def voice(file: UploadFile = File(...), lat: Optional[float] = Form(None), lon: Optional[float] = Form(None),
                sender: Optional[str] = Form(None), role: Optional[str] = Form("UNSET"),
                language: Optional[str] = Form(None, description="optional ISO hint, e.g. hi, ta, te, mr, bn, ne"),
                event_id: Optional[str] = Form(None), created_at: Optional[str] = Form(None)):
    """A voice note in any language. Transcribed, translated to English, then handled exactly like a
    typed message from the mesh app (SOS / road block / message)."""
    eid = _event_id(event_id, "voice")
    if _seen(eid):
        return {"event_id": eid, "duplicate": True}
    raw = await file.read()
    if not raw:
        raise HTTPException(422, "Empty audio file")
    if len(raw) > MAX_AUDIO:
        raise HTTPException(413, "Audio too large; send under 20 MB")
    lat, lon = _check_coords(lat, lon)
    mime = file.content_type or "audio/mp4"

    stt = await run_in_threadpool(media_ai.transcribe, raw, _audio_name(file.filename, mime), mime, language)
    text = (stt or {}).get("text") or ""
    spoken = (stt or {}).get("language")
    english = None
    if text:
        english = text if media_ai.is_english(spoken) else await run_in_threadpool(media_ai.translate_en, text, spoken)

    stt_fields = {"transcript": text or None,
                  "transcript_en": english if english and english != text else None,
                  "spoken_language": spoken, "stt_model": (stt or {}).get("model"),
                  "stt_error": None if stt else (
                      (media_ai.last_error.get("error") or "no speech recognised in the recording")
                      if media_ai.enabled() else "speech-to-text off: no AI key on the server")}
    media_id = f"{eid}-audio"
    created = _created(created_at)

    if text and lat is not None:
        # Same path as a typed message: Triage Agent (or word rules) decides SOS / road block / message.
        content = f"{english}\n[{spoken}] {text}" if stt_fields["transcript_en"] else text
        reading = await run_in_threadpool(triage.read, content, role)
        inc = bridge.CivIncident(id=eid, sender=sender, role=role or "UNSET", lat=lat, lon=lon, content=content,
                                 media_ids=[media_id])
        ev = bridge.to_event(inc, None, False, reading)
        ev.event_id = eid
        ev.created_at = created
        ev.device_id = f"voice:{sender or 'unknown'}"
        ev.via = v1.Via(path="voice note")
        ev.payload.update({k: v for k, v in stt_fields.items() if v})
    else:
        ev = v1.EventIn(event_id=eid, kind="voice", created_at=created, device_id=f"voice:{sender or 'unknown'}",
                        lat=lat, lon=lon, via=v1.Via(path="voice note"),
                        payload={**{k: v for k, v in stt_fields.items() if v}, "sender": sender, "role": role,
                                 "note": ("no location: officer can listen and act" if text else
                                          "could not transcribe: listen to the recording")},
                        media=[v1.InlineMedia(media_id=media_id)])

    with core.db() as con:
        audio_url = _store_audio(con, media_id, raw, mime, file.filename)
        r, notes = v1.handle_event(con, ev)
    await _finish([r], notes)
    return {**r, "audio": audio_url, **stt_fields}


# ---------- photo ----------
@router.post("/photo")
async def photo(file: UploadFile = File(...), lat: Optional[float] = Form(None), lon: Optional[float] = Form(None),
                caption: Optional[str] = Form(""), sender: Optional[str] = Form(None), role: Optional[str] = Form("UNSET"),
                event_id: Optional[str] = Form(None), created_at: Optional[str] = Form(None)):
    """A photo from the field. Saved and shown at once; the AI photo check runs in a queue
    (one at a time, waiting out provider rate limits). If it shows a road hazard, the officer
    is asked to add a blockage there."""
    eid = _event_id(event_id, "photo")
    if _seen(eid):
        return {"event_id": eid, "duplicate": True}
    raw = await file.read()
    if not raw:
        raise HTTPException(422, "Empty photo")
    lat, lon = _check_coords(lat, lon)
    loc_source = "phone GPS" if lat is not None else None
    if lat is None:
        lat, lon = exif_gps(raw)
        loc_source = "photo GPS (EXIF)" if lat is not None else None
    caption = (caption or "")[:300]

    ai_on = media_ai.enabled()
    payload = {"caption": caption or None, "sender": sender, "role": role, "location_source": loc_source,
               "ai_status": "queued" if ai_on else None,
               "ai_error": None if ai_on else "photo check off: no AI key on the server"}
    media_id = f"{eid}-photo"
    ev = v1.EventIn(event_id=eid, kind="photo", created_at=_created(created_at), device_id=f"photo:{sender or 'unknown'}",
                    lat=lat, lon=lon, via=v1.Via(path="photo upload"), payload={k: v for k, v in payload.items() if v is not None},
                    media=[v1.InlineMedia(media_id=media_id)])
    with core.db() as con:
        v1._store_media(con, media_id, raw, file.content_type)
        r, notes = v1.handle_event(con, ev)
        url = con.execute("SELECT path FROM media WHERE media_id=?", (media_id,)).fetchone()["path"]
    await _finish([r], notes)

    out = {**r, "photo": url, "location_source": loc_source, "ai_status": payload["ai_status"] or "off",
           "ai": None, "suggestion": None}
    if ai_on:
        if os.environ.get("PHOTO_CHECK_INLINE") == "1":  # tests / debugging: check inside the request
            res = await run_in_threadpool(check_photo, eid, False)
            await _publish_check(res)
            out.update(ai=res["ai"], suggestion=res["suggestion"], ai_status=res["status"],
                       incident_id=res["incident_id"] or out.get("incident_id"))
        else:
            enqueue_photo(eid)
    return out


# ---------- photo check (runs in the queue) ----------
def _load_photo(con, eid: str):
    ev = con.execute("SELECT * FROM events WHERE event_id=?", (eid,)).fetchone()
    if not ev:
        return None, None, None
    m = con.execute("SELECT * FROM media WHERE media_id=?", (f"{eid}-photo",)).fetchone()
    if not m or not m["path"]:
        return ev, None, None
    path = core.MEDIA / m["path"].replace("/media/", "")
    return ev, (path.read_bytes() if path.exists() else None), m


def _update_payload(con, eid: str, **fields) -> dict:
    p = json.loads(con.execute("SELECT payload FROM events WHERE event_id=?", (eid,)).fetchone()["payload"])
    p.update(fields)
    p = {k: v for k, v in p.items() if v is not None}
    con.execute("UPDATE events SET payload=? WHERE event_id=?", (json.dumps(p, ensure_ascii=False), eid))
    return p


def check_photo(eid: str, raise_rate_limit: bool = True) -> dict:
    """Run the AI photo check for one stored photo and apply the result. Raises
    media_ai.RateLimited (when asked) so the queue can wait and retry."""
    with core.db() as con:
        ev, raw, m = _load_photo(con, eid)
    res = {"event_id": eid, "status": "failed", "ai": None, "suggestion": None, "incident_id": None, "notes": []}
    if ev is None or raw is None:
        return res
    payload = json.loads(ev["payload"])
    caption = payload.get("caption") or ""
    ai = media_ai.analyze_photo(raw, (m["mime"] if m else None) or "image/jpeg", caption,
                                raise_rate_limit=raise_rate_limit)

    with core.db() as con:
        if not ai:
            _update_payload(con, eid, ai_status="failed",
                            ai_error=media_ai.last_error.get("error") or "photo check failed")
            res["notes"] = [("feed", {"count": 0, "source": "photo-check"})]
            return res
        _update_payload(con, eid, ai_status="done", ai_error=None,
                        ai_hazard=HAZARD_LABEL.get(ai["hazard"], "Nothing blocking"), ai_description=ai["description"],
                        ai_blocks_road=ai["blocks_road"], ai_confidence=ai["confidence"], ai_model=ai["model"])
        res.update(status="done", ai=ai)
        lat, lon, url = ev["lat"], ev["lon"], (m["path"] if m else None)
        handled = ev["handled_as"]
        notes: list = [("feed", {"count": 0, "source": "photo-check"})]

        # people visibly in danger and the photo has a place: make it an incident (unless already in one)
        if ai["people_in_danger"] and lat is not None and not ev["incident_id"]:
            itype = PEOPLE_TYPE.get(ai["hazard"], "other")
            ing = core.ingest(con, core.ReportIn(external_id=eid, source="mesh", type=itype, lat=lat, lon=lon,
                                                 message=(ai["description"] or caption)[:500],
                                                 reported_at=ev["created_at"]))
            res["incident_id"] = ing["incident_id"]
            con.execute("UPDATE incidents SET photo=COALESCE(photo, ?) WHERE id=?", (url, ing["incident_id"]))
            handled = "new incident from photo" if not ing["merged"] else f"merged into incident #{ing['incident_id']}"
            con.execute("UPDATE events SET incident_id=? WHERE event_id=?", (ing["incident_id"], eid))

        if ai["hazard"] in ROAD_HAZARDS and (ai["blocks_road"] or ai["hazard"] in ("fallen_tree", "landslide", "debris")) \
                and ai["confidence"] >= MIN_CONFIDENCE:
            cur = con.execute(
                "INSERT INTO hazard_suggestions (event_id,media_id,photo,photo_sha256,lat,lon,loc_source,hazard,label,blocks_road,"
                "confidence,description,caption,radius_m,model,status,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (eid, f"{eid}-photo", url, hashlib.sha256(raw).hexdigest(), lat, lon, payload.get("location_source"),
                 ai["hazard"], HAZARD_LABEL[ai["hazard"]], int(ai["blocks_road"]), ai["confidence"], ai["description"],
                 caption, ai["radius_m"], ai["model"], "pending", v1.now()))
            sug = dict(con.execute("SELECT * FROM hazard_suggestions WHERE id=?", (cur.lastrowid,)).fetchone())
            res["suggestion"] = sug
            handled = f"{handled} · photo hazard suggested: {HAZARD_LABEL[ai['hazard']]}"
            core.write_log(con, "photo-check", "photo_hazard_suggested", res["incident_id"] or ev["incident_id"],
                           suggestion=sug["id"], hazard=ai["hazard"], confidence=ai["confidence"],
                           photo_sha256=sug["photo_sha256"], lat=lat, lon=lon)
            notes.append(("photo_hazard", sug))
        con.execute("UPDATE events SET handled_as=? WHERE event_id=?", (handled, eid))
    res["notes"] = notes
    return res


async def _publish_check(res: dict) -> None:
    await v1._send(res["notes"] + [("changed", {})])
    if res.get("incident_id"):
        await v1._verify_after([res["incident_id"]])


QUEUE_ATTEMPTS = int(os.environ.get("PHOTO_CHECK_ATTEMPTS", "8"))
MAX_WAIT_S = 65.0
_sleep = asyncio.sleep  # replaced in tests
_queue_state: dict = {"loop": None, "queue": None, "task": None}


def _queue() -> asyncio.Queue:
    loop = asyncio.get_running_loop()
    st = _queue_state
    if st["loop"] is not loop or st["task"] is None or st["task"].done():
        st["loop"], st["queue"] = loop, asyncio.Queue()
        st["task"] = loop.create_task(_worker(st["queue"]))
    return st["queue"]


def enqueue_photo(eid: str) -> None:
    _queue().put_nowait(eid)


async def _worker(q: asyncio.Queue) -> None:
    """One photo at a time. On a rate limit, wait what the provider asks (max 65 s) and retry."""
    while True:
        eid = await q.get()
        try:
            res = None
            for _ in range(QUEUE_ATTEMPTS):
                try:
                    res = await run_in_threadpool(check_photo, eid, True)
                    break
                except media_ai.RateLimited as rl:
                    await _sleep(min(max(rl.wait, 2.0) + 1.0, MAX_WAIT_S))
            if res is None:
                with core.db() as con:
                    _update_payload(con, eid, ai_status="failed",
                                    ai_error=f"AI kept rate-limiting after {QUEUE_ATTEMPTS} tries; look at the photo")
                res = {"notes": [("feed", {"count": 0})], "incident_id": None}
            await _publish_check(res)
        except Exception as exc:  # never let one bad photo stop the queue
            try:
                with core.db() as con:
                    _update_payload(con, eid, ai_status="failed", ai_error=f"{type(exc).__name__}: {str(exc)[:160]}")
            except Exception:
                pass
        finally:
            q.task_done()


def resume_queue() -> int:
    """After a restart: queue every photo whose check never finished."""
    with core.db() as con:
        ids = [r["event_id"] for r in con.execute(
            "SELECT event_id FROM events WHERE kind='photo' AND payload LIKE ? ORDER BY received_at",
            ('%"ai_status": "queued"%',))]
    if ids and media_ai.enabled():
        for eid in ids:
            enqueue_photo(eid)
    return len(ids)


@router.get("/queue")
def queue_status():
    q = _queue_state["queue"]
    with core.db() as con:
        waiting = con.execute("SELECT COUNT(*) FROM events WHERE kind='photo' AND payload LIKE ?",
                              ('%"ai_status": "queued"%',)).fetchone()[0]
    return {"photos_waiting": waiting, "in_memory": q.qsize() if q else 0,
            "worker_running": bool(_queue_state["task"] and not _queue_state["task"].done())}


# ---------- officer decisions ----------
class DecideIn(BaseModel):
    officer: str = "Duty Officer"
    lat: Optional[float] = Field(None, ge=-90, le=90, description="needed when the photo had no location")
    lon: Optional[float] = Field(None, ge=-180, le=180)
    radius_m: Optional[float] = Field(None, ge=10, le=3000)
    note: Optional[str] = None


@router.get("/suggestions")
def suggestions(status: str = "pending", limit: int = 30):
    with core.db() as con:
        q = "SELECT * FROM hazard_suggestions" + ("" if status == "all" else " WHERE status=?") + " ORDER BY id DESC LIMIT ?"
        args = (limit,) if status == "all" else (status, limit)
        return core.rows(con.execute(q, args))


@router.post("/suggestions/{sid}/accept")
async def accept(sid: int, body: DecideIn):
    with core.db() as con:
        s = con.execute("SELECT * FROM hazard_suggestions WHERE id=?", (sid,)).fetchone()
        if not s:
            raise HTTPException(404, "Suggestion not found")
        if s["status"] != "pending":
            raise HTTPException(409, f"Already {s['status']}")
        lat = body.lat if body.lat is not None else s["lat"]
        lon = body.lon if body.lon is not None else s["lon"]
        if lat is None or lon is None:
            raise HTTPException(422, "This photo has no location: pick the spot on the map first")
        note = body.note or f"{s['label']} (photo proof #{sid})"
        h, notes = v1.add_hazard(con, lat=lat, lon=lon, radius_m=body.radius_m or s["radius_m"] or 60, note=note[:200],
                                 kind=HAZARD_KIND.get(s["hazard"], "road_block"), source="officer · photo evidence",
                                 by=body.officer, trusted=True)
        con.execute("UPDATE hazards SET photo=? WHERE id=?", (s["photo"], h["id"]))
        con.execute("UPDATE hazard_suggestions SET status='accepted', hazard_id=?, decided_by=?, decided_at=?, lat=?, lon=? WHERE id=?",
                    (h["id"], body.officer, v1.now(), lat, lon, sid))
        con.execute("UPDATE events SET hazard_id=?, handled_as=? WHERE event_id=?",
                    (h["id"], f"road blocked by {body.officer} from photo", s["event_id"]))
        core.write_log(con, body.officer, "photo_hazard_accepted", None, suggestion=sid, hazard=h["id"],
                       photo=s["photo"], photo_sha256=s["photo_sha256"], lat=lat, lon=lon)
    await v1._send(notes + [("photo_hazard", {"id": sid, "status": "accepted"}), ("changed", {})])
    return {"ok": True, "hazard_id": h["id"]}


@router.post("/suggestions/{sid}/dismiss")
async def dismiss(sid: int, body: DecideIn):
    with core.db() as con:
        s = con.execute("SELECT * FROM hazard_suggestions WHERE id=?", (sid,)).fetchone()
        if not s:
            raise HTTPException(404, "Suggestion not found")
        if s["status"] != "pending":
            raise HTTPException(409, f"Already {s['status']}")
        con.execute("UPDATE hazard_suggestions SET status='dismissed', decided_by=?, decided_at=? WHERE id=?",
                    (body.officer, v1.now(), sid))
        core.write_log(con, body.officer, "photo_hazard_dismissed", None, suggestion=sid, photo_sha256=s["photo_sha256"])
    await v1._send([("photo_hazard", {"id": sid, "status": "dismissed"}), ("changed", {})])
    return {"ok": True}


@router.get("/status")
def status():
    return {"ai": media_ai.enabled(), "last_error": media_ai.last_error}
