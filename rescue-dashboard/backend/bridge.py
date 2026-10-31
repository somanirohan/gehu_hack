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

from fastapi import APIRouter
from pydantic import BaseModel, Field

import classify
import main as core
import v1

router = APIRouter(prefix="/api/v1/bitchat")

OFFICIAL_ROLES = {"AMBULANCE", "FIRE", "GOV"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS shelters (
  id TEXT PRIMARY KEY, name TEXT, lat REAL, lon REAL, capacity INTEGER, status TEXT, role TEXT,
  version INTEGER, origin TEXT, verified INTEGER, source TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS sync_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, received_at TEXT, schema TEXT, produced_at TEXT,
  incidents INTEGER, new_incidents INTEGER, shelters INTEGER);
"""


def init_bridge(con) -> None:
    con.executescript(SCHEMA)


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


def to_event(inc: CivIncident, produced_at: Optional[int], drill: bool = False) -> v1.EventIn:
    c = classify.classify(inc.content)
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
    row = con.execute("SELECT version FROM shelters WHERE id=?", (s.id,)).fetchone()
    if row and (row["version"] or 0) > (s.version or 0):
        return False
    con.execute(
        "INSERT OR REPLACE INTO shelters (id,name,lat,lon,capacity,status,role,version,origin,verified,source,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (s.id, s.name, s.lat, s.lon, s.capacity, s.status, s.role, s.version or 0, s.originPeerID, int(bool(s.verified)), "mesh-sync", v1.now()))
    return True


def _is_drill(bundle: CivBundle) -> bool:
    """Practice data from simulator/drill_dehradun.py is marked so it is never mistaken for a real call."""
    return bool((bundle.model_extra or {}).get("drill"))


@router.post("/civ-sync")
async def civ_sync(bundle: CivBundle):
    """Receives the app's existing sync bundle. Always 2xx unless the body is invalid,
    so the phone marks the flush done; repeats are ignored."""
    results, notes, accepted = [], [], []
    with core.db() as con:
        for inc in bundle.incidents:
            try:
                r, n = v1.handle_event(con, to_event(inc, bundle.produced_at, _is_drill(bundle)))
            except Exception as exc:  # never lose the rest of the bundle because of one bad message
                core.write_log(con, "bitchat-sync", "sync_item_failed", None, id=inc.id, error=str(exc)[:200])
                continue
            results.append(r)
            accepted.append(inc.id)
            notes += n
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
    await v1._send(notes)
    return {"ok": True, "received": len(bundle.incidents), "new": new, "duplicates": len(results) - new,
            "shelters_changed": changed_shelters, "accepted_ids": accepted}


@router.get("/sync-status")
def sync_status():
    """When phones last synced: shown on the dashboard so officers know data is flowing."""
    with core.db() as con:
        last = core.rows(con.execute("SELECT * FROM sync_log ORDER BY id DESC LIMIT 10"))
        total = con.execute("SELECT COUNT(*), COALESCE(SUM(new_incidents),0) FROM sync_log").fetchone()
    return {"last": last, "syncs": total[0], "items_received": total[1]}


shelter_router = APIRouter(prefix="/api/v1")


@shelter_router.get("/shelters")
def shelters():
    with core.db() as con:
        return core.rows(con.execute("SELECT * FROM shelters ORDER BY name"))
