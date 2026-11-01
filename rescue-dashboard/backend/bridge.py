"""Bridge for the Android app's EXISTING sync (bitchat.civ.sync/v1).

The app already posts this bundle when a phone gets internet (SyncFlushWorker ->
CivilizationSyncClient). No app change is needed: set the app's Sync endpoint to

    https://<your-public-address>/api/v1/bitchat/civ-sync

Bundle shape (from SyncBundleBuilder.kt):
    {"bundle_schema": "bitchat.civ.sync/v1", "produced_at": <ms>,
     "incidents": [{"id","timestamp"(ms),"sender","role","lat","lon","content"}],
     "shelters":  [{"id","name","lat","lon","capacity","status","role","version","originPeerID","verified"}]}

Each incident is a mesh message that carried a geo:lat,lon tag. The app re-sends the
last 200 messages on every flush, so ids are de-duplicated here. Message text is read
by rule-based classify.py and turned into a v1 event (sos / road_block / message);
the result is labelled "rule suggestion" until an officer confirms.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from concurrent.futures import ThreadPoolExecutor
import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

import classify
from agents import triage
import main as core
import v1

router = APIRouter(prefix="/api/v1/bitchat")

OFFICIAL_ROLES = {"AMBULANCE", "FIRE", "GOV"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS shelters (
  id TEXT PRIMARY KEY, name TEXT, lat REAL, lon REAL, capacity INTEGER, status TEXT, role TEXT,
  version INTEGER, origin TEXT, verified INTEGER, source TEXT, updated_at TEXT,
  creator_token TEXT, note TEXT);
CREATE TABLE IF NOT EXISTS sync_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, received_at TEXT, schema TEXT, produced_at TEXT,
  incidents INTEGER, new_incidents INTEGER, shelters INTEGER);
"""


def init_bridge(con) -> None:
    con.executescript(SCHEMA)
    cols = {r["name"] for r in con.execute("PRAGMA table_info(shelters)")}
    for col, typ in (("creator_token", "TEXT"), ("note", "TEXT")):
        if col not in cols:
            con.execute(f"ALTER TABLE shelters ADD COLUMN {col} {typ}")



class CivIncident(BaseModel):
    id: str
    timestamp: Optional[int] = None
    sender: Optional[str] = None
    role: Optional[str] = "UNSET"
    lat: float
    lon: float
    content: str = ""
    # Optional fields the app MAY add later. When present they win over the text rules.
    category: Optional[str] = None   # e.g. "trapped", "medical", "road_block"
    people: Optional[int] = None
    media_ids: list[str] = Field(default_factory=list)  # photos uploaded separately to /api/v1/media
    model_config = {"extra": "allow"}


class CivShelter(BaseModel):
    id: str
    name: Optional[str] = ""
    lat: float
    lon: float
    capacity: Optional[int] = None
    status: Optional[str] = None
    role: Optional[str] = None
    version: Optional[int] = 0
    originPeerID: Optional[str] = None
    verified: Optional[bool] = False
    note: Optional[str] = None
    creator_token: Optional[str] = None


class CivBundle(BaseModel):
    bundle_schema: Optional[str] = "bitchat.civ.sync/v1"
    produced_at: Optional[int] = None
    incidents: list[CivIncident] = Field(default_factory=list)
    shelters: list[CivShelter] = Field(default_factory=list)
    model_config = {"extra": "allow"}  # tolerate fields the app adds later


def _iso(ms: Optional[int]) -> str:
    if not ms:
        return v1.now()
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat(timespec="seconds")


def to_event(inc: CivIncident, produced_at: Optional[int], drill: bool = False,
             reading: Optional[dict] = None) -> v1.EventIn:
    """reading = Triage Agent result (agents.triage.read); falls back to the word rules."""
    c = dict(reading) if reading else classify.classify(inc.content)
    if inc.category:  # chosen by the person in the app: not a guess
        cat = inc.category.strip().lower()
        if cat in ("road_block", "road_blocked", "blocked"):
            c.update(kind="road_block", type=None)
        elif cat in ("message", "info", "safe"):
            c.update(kind="message")
        else:
            c.update(kind="sos", type=cat)
        c["label"] = "chosen in app"
        c["confidence"] = 1.0
    if inc.people:
        c["people"] = inc.people
    text = classify.clean(inc.content)
    role = (inc.role or "UNSET").upper()
    official = role in OFFICIAL_ROLES
    held = max(0, round(((produced_at or 0) - (inc.timestamp or 0)) / 1000)) if produced_at and inc.timestamp else None
    meta: dict[str, Any] = {"drill": drill or None, "sender": inc.sender, "role": role, "category_source": c["label"],
                            "matched_words": ", ".join(c["matched"]) or None, "confidence": c["confidence"]}
    ai = c.get("ai")
    if ai:  # Triage Agent extras, shown on the dashboard as an AI suggestion
        meta.update(ai_summary=ai["summary"], ai_urgency=ai["urgency"], ai_injured=ai["injured"],
                    ai_vulnerable=", ".join(ai["vulnerable"]) or None, ai_landmarks=", ".join(ai["landmarks"]) or None,
                    ai_needs=", ".join(ai["needs"]) or None, ai_language=ai["language"], ai_reasons=ai["reasons"],
                    rule_guess=c.get("rule_guess"))
    elif c.get("ai_error"):
        meta["ai_error"] = c["ai_error"][:160]
    if c["kind"] == "sos":
        payload = {"type": c["type"], "people": c["people"] or 1, "message": text, **meta}
    elif c["kind"] == "road_block":
        payload = {"note": text[:200], "radius_m": 80, "trusted": official,
                   "hazard_kind": "landslide" if c["type"] == "landslide" else "road_block", **meta}
    else:
        payload = {"text": text, **meta}
    return v1.EventIn(
        event_id=f"bitchat-{inc.id}", kind=c["kind"], created_at=_iso(inc.timestamp),
        device_id=f"bitchat:{inc.sender or 'unknown'}", lat=inc.lat, lon=inc.lon,
        via=v1.Via(path="drill" if drill else "mesh-sync", uploader=None, held_seconds=held), payload=payload,
        media=[v1.InlineMedia(media_id=m) for m in inc.media_ids[:4]])


def _upsert_shelter(con, s: CivShelter) -> bool:
    row = con.execute("SELECT version, creator_token, note FROM shelters WHERE id=?", (s.id,)).fetchone()
    if row and (row["version"] or 0) > (s.version or 0):
        return False
    tok = (row["creator_token"] if row else None) or getattr(s, "creator_token", None)
    note = getattr(s, "note", None) or (row["note"] if row else None)
    con.execute(
        "INSERT OR REPLACE INTO shelters (id,name,lat,lon,capacity,status,role,version,origin,verified,source,updated_at,creator_token,note) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (s.id, s.name, s.lat, s.lon, s.capacity, s.status, s.role, s.version or 0, s.originPeerID, int(bool(s.verified)), "mesh-sync", v1.now(), tok, note))
    return True



def _is_drill(bundle: CivBundle) -> bool:
    """Practice data from simulator/drill_dehradun.py is marked so it is never mistaken for a real call."""
    return bool((bundle.model_extra or {}).get("drill"))


AI_MAX_PER_BUNDLE = 12  # the AI reads at most this many NEW messages per upload; the rest use the word rules
AI_PARALLEL = 3         # read up to 3 new messages at once (one by one took 40 s for 8: the phone gives up at 30 s)


def _triage_new(bundle: CivBundle) -> dict:
    """Triage Agent on messages the server has NOT seen before (the app re-sends old ones every time)."""
    ids = [f"bitchat-{i.id}" for i in bundle.incidents]
    if not ids:
        return {}
    with core.db() as con:
        seen = {r[0] for r in con.execute(
            f"SELECT event_id FROM events WHERE event_id IN ({','.join('?' * len(ids))})", ids)}
    todo = [inc for inc in bundle.incidents if f"bitchat-{inc.id}" not in seen and not inc.category]
    todo = list({inc.id: inc for inc in todo}.values())[:AI_MAX_PER_BUNDLE]
    if not todo:
        return {}
    with ThreadPoolExecutor(max_workers=AI_PARALLEL) as pool:
        readings = list(pool.map(lambda inc: triage.read(inc.content, inc.role), todo))
    return {inc.id: r for inc, r in zip(todo, readings)}


@router.post("/civ-sync")
async def civ_sync(bundle: CivBundle, background: BackgroundTasks):
    """Receives the app's existing sync bundle. Always 2xx unless the body is invalid,
    so the phone marks the flush done; repeats are ignored."""
    results, notes, accepted = [], [], []
    readings = await run_in_threadpool(_triage_new, bundle)
    with core.db() as con:
        for inc in bundle.incidents:
            try:
                r, n = v1.handle_event(con, to_event(inc, bundle.produced_at, _is_drill(bundle), readings.get(inc.id)))
            except Exception as exc:  # never lose the rest of the bundle because of one bad message
                core.write_log(con, "bitchat-sync", "sync_item_failed", None, id=inc.id, error=str(exc)[:200])
                continue
            results.append(r)
            accepted.append(inc.id)
            notes += n

            # When an incoming incident is an SOS distress / beacon, ensure it appears as an active SOS Beacon with live capacity
            content_str = (inc.content or "").strip()
            cat_str = (inc.category or "").lower()
            if ("🆘" in content_str or "beacon" in content_str.lower() or cat_str in ("sos", "beacon")) and inc.lat is not None and inc.lon is not None:
                mesh_b_id = f"beacon-{inc.id}"
                existing_b = con.execute("SELECT id, capacity, status FROM shelters WHERE id=?", (mesh_b_id,)).fetchone()
                if not existing_b:
                    clean_title = content_str.replace("🆘", "").split("geo:")[0].strip()
                    if not clean_title or len(clean_title) < 3:
                        clean_title = f"SOS Beacon ({inc.sender or 'Field Peer'})"
                    initial_cap = inc.people if (inc.people and inc.people > 1) else 50
                    now_ts = int(time.time() * 1000)
                    con.execute(
                        "INSERT OR IGNORE INTO shelters (id, name, lat, lon, capacity, status, role, version, origin, verified, source, updated_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (mesh_b_id, clean_title[:80], inc.lat, inc.lon, initial_cap, "OPEN", "SOS", now_ts, inc.sender or "mesh-sync", 0, "mesh-sos", v1.now())
                    )
                    changed_shelters_flag = True
                    notes.append(("beacon_updated", {
                        "id": mesh_b_id, "name": clean_title[:80], "capacity": initial_cap, "status": "OPEN",
                        "lat": inc.lat, "lon": inc.lon, "role": "SOS", "origin": inc.sender or "mesh-sync", "is_beacon": True
                    }))

        changed_shelters = sum(_upsert_shelter(con, s) for s in bundle.shelters)
        new = sum(1 for r in results if not r.get("duplicate"))
        con.execute("INSERT INTO sync_log (received_at,schema,produced_at,incidents,new_incidents,shelters) VALUES (?,?,?,?,?,?)",
                    (v1.now(), bundle.bundle_schema, _iso(bundle.produced_at), len(bundle.incidents), new, len(bundle.shelters)))
        if new or changed_shelters:
            core.write_log(con, "bitchat-sync", "sync_bundle", None, new_items=new, shelters_changed=changed_shelters)
    if new:
        notes += [("feed", {"count": new, "source": "bitchat"}), ("changed", {})]
    if changed_shelters:
        notes.append(("shelters", {"changed": changed_shelters}))
        for s in bundle.shelters:
            role = (s.role or "").upper()
            if role in ("CIVILIAN", "SOS") or "beacon" in (s.name or "").lower():
                notes.append(("beacon_updated", {
                    "id": s.id, "name": s.name, "capacity": s.capacity, "status": s.status,
                    "lat": s.lat, "lon": s.lon, "role": s.role, "origin": s.originPeerID,
                    "note": getattr(s, "note", None)
                }))
    await v1._send(notes)
    # Verifier + Route Watch run right AFTER the phone gets its answer: the SOS is already saved
    # and on the dashboard, and the phone must not wait (or time out) for the extra AI calls.
    background.add_task(v1._after_events, results)
    return {"ok": True, "received": len(bundle.incidents), "new": new, "duplicates": len(results) - new,
            "shelters_changed": changed_shelters, "accepted_ids": accepted}


@router.get("/sync-status")
def sync_status():
    """When phones last synced: shown on the dashboard so officers know data is flowing."""
    with core.db() as con:
        last = core.rows(con.execute("SELECT * FROM sync_log ORDER BY id DESC LIMIT 10"))
        total = con.execute("SELECT COUNT(*), COALESCE(SUM(new_incidents),0) FROM sync_log").fetchone()
    return {"last": last, "syncs": total[0], "items_received": total[1]}


class BeaconIn(BaseModel):
    name: str = "SOS Beacon"
    lat: float
    lon: float
    capacity: int = 50
    status: str = "OPEN"
    role: str = "CIVILIAN"
    note: Optional[str] = ""
    origin: Optional[str] = None


class BeaconUpdate(BaseModel):
    capacity: Optional[int] = None
    status: Optional[str] = None
    note: Optional[str] = None
    name: Optional[str] = None
    creator_token: Optional[str] = None
    origin: Optional[str] = None


shelter_router = APIRouter(prefix="/api/v1")


@shelter_router.get("/shelters")
def shelters():
    with core.db() as con:
        items = core.rows(con.execute("SELECT * FROM shelters ORDER BY name"))
    for item in items:
        role = (item.get("role") or "").upper()
        name = (item.get("name") or "").lower()
        item["is_beacon"] = role in ("CIVILIAN", "SOS") or "beacon" in name
    return items


@shelter_router.get("/beacons")
def beacons():
    with core.db() as con:
        items = core.rows(con.execute(
            "SELECT * FROM shelters WHERE UPPER(role) IN ('CIVILIAN', 'SOS') OR LOWER(name) LIKE '%beacon%' ORDER BY updated_at DESC"
        ))
    for item in items:
        item["is_beacon"] = True
    return items


@shelter_router.get("/beacons/{id}")
def get_beacon(id: str):
    with core.db() as con:
        row = con.execute("SELECT * FROM shelters WHERE id=?", (id,)).fetchone()
        if not row:
            raise HTTPException(404, "Beacon not found")
        data = dict(row)
        if data.get("creator_token"):
            data["has_token"] = True
            data["creator_token_preview"] = data["creator_token"][:6] + "..."
        data["is_beacon"] = (data.get("role") or "").upper() in ("CIVILIAN", "SOS") or "beacon" in (data.get("name") or "").lower()
        return data


@shelter_router.post("/beacons")
async def create_beacon(beacon: BeaconIn):
    beacon_id = f"beacon-{uuid.uuid4().hex[:8]}"
    creator_token = uuid.uuid4().hex
    now_str = v1.now()
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    with core.db() as con:
        con.execute(
            "INSERT INTO shelters (id, name, lat, lon, capacity, status, role, version, origin, verified, source, updated_at, creator_token, note) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (beacon_id, beacon.name, beacon.lat, beacon.lon, beacon.capacity, (beacon.status or "OPEN").upper(),
             beacon.role or "CIVILIAN", now_ms, beacon.origin or "web-beacon", 0, "beacon-control", now_str, creator_token, beacon.note or "")
        )
        core.write_log(con, "beacon_creator", "beacon_started", None,
                       beacon_id=beacon_id, name=beacon.name, capacity=beacon.capacity, lat=beacon.lat, lon=beacon.lon)
        saved = dict(con.execute("SELECT * FROM shelters WHERE id=?", (beacon_id,)).fetchone())

    saved["is_beacon"] = True
    await core.hub.send("shelters", {"action": "create", "id": beacon_id})
    await core.hub.send("beacon_updated", saved)
    return {"ok": True, "beacon": saved, "creator_token": creator_token}


@shelter_router.patch("/beacons/{id}")
@shelter_router.patch("/shelters/{id}")
async def patch_beacon(id: str, body: BeaconUpdate):
    with core.db() as con:
        row = con.execute("SELECT * FROM shelters WHERE id=?", (id,)).fetchone()
        if not row:
            raise HTTPException(404, "Beacon / Shelter not found")

        expected_token = row["creator_token"]
        expected_origin = row["origin"]

        if expected_token and body.creator_token:
            if body.creator_token != expected_token and not (expected_origin and body.origin == expected_origin):
                raise HTTPException(403, "Invalid creator token for this beacon.")
        elif expected_token and not body.creator_token:
            if not (expected_origin and body.origin and body.origin == expected_origin):
                raise HTTPException(403, "Creator token required to update this beacon.")
        elif expected_origin and not expected_token:
            if body.origin and body.origin != expected_origin:
                raise HTTPException(403, "Origin device ID does not match beacon author.")

        new_capacity = body.capacity if body.capacity is not None else row["capacity"]
        new_status = (body.status.upper() if body.status else row["status"])
        new_note = body.note if body.note is not None else row["note"]
        new_name = body.name if body.name is not None else row["name"]
        new_token = expected_token or body.creator_token or uuid.uuid4().hex
        new_version = (row["version"] or 0) + 1
        now_str = v1.now()

        con.execute(
            "UPDATE shelters SET capacity=?, status=?, note=?, name=?, version=?, updated_at=?, creator_token=? WHERE id=?",
            (new_capacity, new_status, new_note, new_name, new_version, now_str, new_token, id)
        )
        core.write_log(con, "beacon_controller", "capacity_updated", None,
                       beacon_id=id, capacity=new_capacity, status=new_status, note=new_note)
        updated = dict(con.execute("SELECT * FROM shelters WHERE id=?", (id,)).fetchone())

    updated["is_beacon"] = (updated.get("role") or "").upper() in ("CIVILIAN", "SOS") or "beacon" in (updated.get("name") or "").lower()
    await core.hub.send("shelters", {"action": "update", "id": id, "capacity": new_capacity, "status": new_status})
    await core.hub.send("beacon_updated", updated)
    return {"ok": True, "beacon": updated, "creator_token": new_token}


@shelter_router.delete("/beacons/{id}")
async def close_beacon(id: str, creator_token: Optional[str] = None, origin: Optional[str] = None):
    with core.db() as con:
        row = con.execute("SELECT * FROM shelters WHERE id=?", (id,)).fetchone()
        if not row:
            raise HTTPException(404, "Beacon not found")
        # If a token is provided and doesn't match, verify origin or allow admin action
        if row["creator_token"] and creator_token and creator_token != row["creator_token"] and origin != row["origin"]:
            raise HTTPException(403, "Invalid creator token")
        now_str = v1.now()
        con.execute("UPDATE shelters SET status='CLOSED', updated_at=?, version=version+1 WHERE id=?", (now_str, id))
        core.write_log(con, "beacon_controller", "beacon_closed", None, beacon_id=id)
        updated = dict(con.execute("SELECT * FROM shelters WHERE id=?", (id,)).fetchone())

    updated["is_beacon"] = True
    await core.hub.send("shelters", {"action": "closed", "id": id, "status": "CLOSED"})
    await core.hub.send("beacon_updated", updated)
    return {"ok": True, "beacon": updated}

