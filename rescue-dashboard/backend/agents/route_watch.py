"""Route Watch Agent (LangGraph): new reports on the road a unit is driving.

For every NEW report (SOS, road block, message, photo) after Triage + Verifier:

  match (code)  Is it within 300 m of the part of an active route that is still AHEAD of a unit?
  graph per affected unit:
     read      AI: does it block the road (yes / maybe / no)? Does a person need help?  (rules if no AI)
     decide    FIXED RULES (not AI):
                 blocks road + on the route (<=100 m):
                     detour <= 5 min      -> re-route now (precaution) + tell the unit why
                     detour  > 5 min      -> heads-up to the unit now, officer approves the re-route
                     no road left         -> heads-up + officer alert (send boat / drone)
                 person needs help near the route (<=300 m) and the unit can help:
                     -> "stop-to-help" suggestion; officer approves the divert
     ⏸ officer  (LangGraph interrupt) only for the long detour / divert cases
     apply     re-route or divert using the existing dispatch code; everything is logged

Drones are never re-routed (they fly). A unit is never alerted about its own incident.
"""
from __future__ import annotations

import json
import math
import sqlite3
import time
from pathlib import Path
from typing import Literal, Optional, TypedDict

from pydantic import BaseModel, Field

import logic
import main as core
import routing
from agents import llm

ON_ROUTE_M = 100      # a road block this close to the route ahead affects the unit
HELP_M = 300          # a person needing help this close to the route ahead: suggest stopping
AUTO_MAX_MIN = 5      # detours up to this many extra minutes are applied at once, as a precaution
OBSTACLE_RADIUS_M = 60
BLOCK_TYPES = {"landslide", "collapse", "flood", "accident"}          # an SOS of these types may block the road
HELP_TYPES = {"injured", "accident", "medical", "trapped", "collapse", "fall"}
RUNS_DB = Path(__file__).resolve().parent.parent / "agent_runs.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS route_alerts (
  id INTEGER PRIMARY KEY AUTOINCREMENT, thread_id TEXT, event_id TEXT, assignment_id INTEGER, unit_id INTEGER,
  unit TEXT, incident_id INTEGER, new_incident_id INTEGER, hazard_id INTEGER, kind TEXT, status TEXT,
  text TEXT, extra_min INTEGER, distance_m INTEGER, photo TEXT, detail TEXT, created_at TEXT,
  decided_by TEXT, decided_at TEXT);
"""


def init(con) -> None:
    con.executescript(SCHEMA)


class Impact(BaseModel):
    blocks_road: Literal["yes", "maybe", "no"] = Field(
        description="yes = the message says a road/bridge is blocked, broken or under water; maybe = something "
                    "that often blocks roads (landslide, collapse, flooding, a crash on the road) but not said; no = otherwise")
    person_needs_help: bool = Field(description="true if a person at that spot needs rescue or medical help")
    short_text: str = Field(description="max 12 words for a driver, e.g. 'Tree fallen across Kaulagarh Road'")
    reason: str = Field(description="max 20 words: which words led to this")


SYSTEM = """You help ambulance and rescue drivers in Dehradun. A new report arrived near the road a unit is
driving. Read it (Hindi, English, Hinglish, typos) and say whether it blocks the road and whether a person
there needs help. Base it only on the report. Never invent places or numbers."""


# ---------------------------------------------------------------- geometry
def _xy(lat0, lat, lon):
    return lon * 111_320 * math.cos(math.radians(lat0)), lat * 111_320


def dist_to_segment(p, a, b) -> float:
    px, py = _xy(p[0], p[0], p[1])
    ax, ay = _xy(p[0], a[0], a[1])
    bx, by = _xy(p[0], b[0], b[1])
    dx, dy = bx - ax, by - ay
    t = 0.0 if dx == dy == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def route_ahead(coords: list, pos) -> list:
    """The part of the route the unit has not driven yet."""
    if len(coords) < 2:
        return coords
    i = min(range(len(coords)), key=lambda k: routing.haversine_m(coords[k][0], coords[k][1], pos[0], pos[1]))
    return coords[i:] if len(coords[i:]) >= 2 else coords[-2:]


def distance_to_route(p, coords) -> float:
    if len(coords) < 2:
        return float("inf")
    return min(dist_to_segment(p, a, b) for a, b in zip(coords, coords[1:]))


# ---------------------------------------------------------------- read (AI or rules)
def _report_text(ev: dict) -> str:
    p = ev["payload"]
    return str(p.get("message") or p.get("text") or p.get("note") or p.get("caption") or p.get("ai_summary") or "")


def rule_impact(ev: dict) -> Impact:
    p, kind = ev["payload"], ev["kind"]
    t = p.get("type")
    blocks = "yes" if kind == "road_block" else ("maybe" if kind == "sos" and t in BLOCK_TYPES else "no")
    help_ = kind == "sos" and t in HELP_TYPES
    text = (p.get("ai_summary") or _report_text(ev) or kind)
    text = text if len(text) <= 60 else text[:57].rsplit(" ", 1)[0] + "…"
    return Impact(blocks_road=blocks, person_needs_help=help_, short_text=text, reason="rule check")


_read_cache: dict = {}


def read_impact(ev: dict) -> tuple[Impact, str]:
    if ev["event_id"] in _read_cache:
        return _read_cache[ev["event_id"]]
    user = json.dumps({"kind": ev["kind"], "text": _report_text(ev), "ai_triage": {
        k: ev["payload"].get(k) for k in ("type", "people", "ai_summary", "ai_needs", "ai_urgency")}}, ensure_ascii=False)
    r = llm.structured(Impact, SYSTEM, user)
    out = (r, llm.label()) if r is not None else (rule_impact(ev), "rule check")
    _read_cache[ev["event_id"]] = out
    return out


# ---------------------------------------------------------------- helpers using the existing dispatch code
def _unit(con, uid):
    return dict(con.execute("SELECT id, name, kind, status FROM responders WHERE id=?", (uid,)).fetchone())


def _apply_route(con, a: dict, r: dict, reason: str) -> list:
    version = (a.get("route_version") or 0) + 1
    con.execute("UPDATE assignments SET route=?, distance_m=?, eta_min=?, route_source=?, route_version=?, reroute_reason=?, updated_at=? WHERE id=?",
                (json.dumps(r["coords"]), r["distance_m"], r["eta_min"], r["source"], version, reason, _now(), a["id"]))
    return [("reroute", {"assignment_id": a["id"], "unit_id": a["responder_id"], "incident_id": a["incident_id"],
                         "route_version": version, "eta_min": r["eta_min"], "distance_m": r["distance_m"],
                         "source": r["source"], "reason": reason, "no_road_route": r.get("no_road_route", False)})]


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _alert(con, st: dict, kind: str, status: str, text: str, **extra) -> dict:
    cur = con.execute(
        "INSERT INTO route_alerts (thread_id,event_id,assignment_id,unit_id,unit,incident_id,new_incident_id,hazard_id,kind,status,text,extra_min,distance_m,photo,detail,created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (st["thread_id"], st["event"]["event_id"], st["assignment"]["id"], st["unit"]["id"], st["unit"]["name"],
         st["assignment"]["incident_id"], extra.get("new_incident_id"), extra.get("hazard_id"), kind, status, text,
         extra.get("extra_min"), round(st["distance_m"]), st.get("photo"), json.dumps(extra.get("detail") or {}), _now()))
    return dict(con.execute("SELECT * FROM route_alerts WHERE id=?", (cur.lastrowid,)).fetchone())


def _note(alert: dict) -> tuple:
    return ("route_alert", {"id": alert["id"], "unit_id": alert["unit_id"], "kind": alert["kind"],
                            "status": alert["status"], "text": alert["text"], "photo": alert["photo"],
                            "incident_id": alert["incident_id"], "new_incident_id": alert["new_incident_id"]})


def _obstacle(con, ev: dict, text: str, by: str) -> int:
    """Hazard for the reported obstacle: reuse the report's own hazard, else create an UNVERIFIED one."""
    if ev.get("hazard_id"):
        return ev["hazard_id"]
    import v1
    h, _ = v1.add_hazard(con, lat=ev["lat"], lon=ev["lon"], radius_m=OBSTACLE_RADIUS_M, note=text[:200],
                         kind="reported_obstacle", source="citizen", by=by, trusted=False)
    return h["id"]


# ---------------------------------------------------------------- graph
class State(TypedDict, total=False):
    thread_id: str
    event: dict
    assignment: dict
    unit: dict
    distance_m: float
    photo: Optional[str]
    impact: dict
    impact_source: str
    action: str          # none | auto_reroute | ask_reroute | ask_divert | no_road
    plan: dict
    alert_ids: list
    decision: dict
    notes: list


def n_read(st: State) -> State:
    imp, src = read_impact(st["event"])
    return {**st, "impact": imp.model_dump(), "impact_source": src}


def n_decide(st: State) -> State:
    import v1
    imp, ev, a = st["impact"], st["event"], st["assignment"]
    notes, alert_ids, action, plan = [], [], "none", {}
    with core.db() as con:
        init(con)
        pos = v1.unit_position(con, a["responder_id"])
        inc = dict(con.execute("SELECT * FROM incidents WHERE id=?", (a["incident_id"],)).fetchone())
        dest = (inc["lat"], inc["lon"])
        tag = f"{imp['short_text']} ({'citizen' if ev.get('role') in (None, '', 'CIVILIAN', 'UNSET') else ev.get('role')} report"
        tag += ", photo)" if st.get("photo") else ")"

        # --- road blocked on the route ahead
        if imp["blocks_road"] in ("yes", "maybe") and st["distance_m"] <= ON_ROUTE_M:
            hz = con.execute("SELECT status FROM hazards WHERE id=?", (ev.get("hazard_id"),)).fetchone() if ev.get("hazard_id") else None
            if not (hz and hz["status"] == "active"):  # active hazards are already re-routed by the core
                hid = _obstacle(con, ev, imp["short_text"], f"route-watch ({st['impact_source']})")
                hrow = dict(con.execute("SELECT * FROM hazards WHERE id=?", (hid,)).fetchone())
                active = v1.hazard_objs(con)
                extra_h = routing.Hazard(hid, hrow["lat"], hrow["lon"], hrow["radius_m"])
                now_r = routing.plan(pos, dest, active)
                new_r = routing.plan(pos, dest, active + [extra_h])
                if new_r.get("no_road_route"):
                    action = "no_road"
                    al = _alert(con, st, "no_road", "pending", f"⚠ Reported ahead: {tag}. No road around it: control room is deciding.",
                                hazard_id=hid, detail={"reason": imp["reason"]})
                    alert_ids.append(al["id"])
                    notes.append(_note(al))
                else:
                    extra = max(0, (new_r["eta_min"] or 0) - (now_r["eta_min"] or 0))
                    plan = {"hazard_id": hid, "extra_min": extra, "new_eta": new_r["eta_min"]}
                    if extra <= AUTO_MAX_MIN:
                        action = "auto_reroute"
                        why = f"Precaution: {tag} on your road. New route +{extra} min."
                        notes += _apply_route(con, a, new_r, why)
                        al = _alert(con, st, "reroute", "auto", f"↻ {why}", hazard_id=hid, extra_min=extra,
                                    detail={"reason": imp["reason"], "source": st["impact_source"]})
                        core.write_log(con, "route-watch-agent", "rerouted_precaution", a["incident_id"], unit=st["unit"]["name"],
                                       hazard=hid, extra_min=extra, report=ev["event_id"], read_by=st["impact_source"])
                        alert_ids.append(al["id"])
                        notes.append(_note(al))
                    else:
                        action = "ask_reroute"
                        al = _alert(con, st, "reroute", "pending",
                                    f"⚠ Reported ahead: {tag}. Slow down. Control room is checking a new route (+{extra} min).",
                                    hazard_id=hid, extra_min=extra, detail={"reason": imp["reason"], "source": st["impact_source"]})
                        core.write_log(con, "route-watch-agent", "reroute_proposed", a["incident_id"], unit=st["unit"]["name"],
                                       hazard=hid, extra_min=extra, report=ev["event_id"])
                        alert_ids.append(al["id"])
                        notes.append(_note(al))

        # --- a person needing help near the route ahead: stop-to-help
        new_inc_id = ev.get("incident_id")
        if imp["person_needs_help"] and new_inc_id and new_inc_id != a["incident_id"] and st["distance_m"] <= HELP_M:
            ninc = con.execute("SELECT * FROM incidents WHERE id=?", (new_inc_id,)).fetchone()
            need = logic.CAPABLE.get(logic.family(ninc["type"]), logic.CAPABLE["other"]) if ninc else set()
            if ninc and ninc["status"] in ("new", "suggested", "held") and st["unit"]["kind"] in need:
                to_new = routing.plan(pos, (ninc["lat"], ninc["lon"]), v1.hazard_objs(con))
                others = [r for r in core.rows(con.execute("SELECT * FROM responders WHERE status='available'"))]
                alt, alt_reason = logic.suggest_responder(inc, others)
                alt_txt = f"Incident #{inc['id']} would be offered to {alt['name']}" if alt else f"No free unit for incident #{inc['id']} yet"
                al = _alert(con, st, "divert", "pending",
                            f"{st['unit']['name']} passes a person needing help ({ninc['type']}, {ninc['people']} {'person' if ninc['people'] == 1 else 'people'}) "
                            f"in about {to_new['eta_min']} min. Divert? {alt_txt}.",
                            new_incident_id=new_inc_id, extra_min=to_new["eta_min"],
                            detail={"alt_unit_id": alt["id"] if alt else None, "alt_reason": alt_reason, "reason": imp["reason"]})
                core.write_log(con, "route-watch-agent", "divert_proposed", a["incident_id"], unit=st["unit"]["name"],
                               new_incident=new_inc_id, report=ev["event_id"])
                alert_ids.append(al["id"])
                notes.append(_note(al))
                action = "ask_divert" if action in ("none", "auto_reroute") else action + "+divert"
    return {**st, "action": action, "plan": plan, "alert_ids": alert_ids, "notes": notes}


def route_after_decide(st: State) -> str:
    return "officer" if st["action"] not in ("none", "auto_reroute") else "end"


def n_officer(st: State) -> State:
    from langgraph.types import interrupt
    decision = interrupt({"alert_ids": st["alert_ids"]})
    return {**st, "decision": decision}


def n_apply(st: State) -> State:
    """Officer decided. decision = {alert_id, approve, officer}."""
    import v1
    d = st.get("decision") or {}
    notes = []
    with core.db() as con:
        init(con)
        al = con.execute("SELECT * FROM route_alerts WHERE id=?", (d.get("alert_id"),)).fetchone()
        if not al or al["status"] != "pending":
            return {**st, "notes": []}
        al = dict(al)
        officer = d.get("officer") or "Duty Officer"
        a = con.execute("SELECT * FROM assignments WHERE id=?", (al["assignment_id"],)).fetchone()
        still = a and a["status"] in ("dispatched", "en_route")
        if not d.get("approve") or not still:
            status = "ignored" if still else "expired"
            con.execute("UPDATE route_alerts SET status=?, decided_by=?, decided_at=? WHERE id=?", (status, officer, _now(), al["id"]))
            core.write_log(con, officer, f"route_alert_{status}", al["incident_id"], alert=al["id"], kind=al["kind"])
            if al["kind"] in ("reroute", "no_road") and still:
                notes.append(("route_alert", {"id": al["id"], "unit_id": al["unit_id"], "kind": "info", "status": status,
                                              "text": "Control room: keep your current route, drive carefully."}))
            return {**st, "notes": notes}
        a = dict(a)
        if al["kind"] in ("reroute", "no_road"):
            # officer confirms the obstacle: hazard becomes active -> the core re-routes every unit through it
            notes += v1.activate_hazard(con, al["hazard_id"], officer)
            txt = "Control room confirmed the block: follow the new route."
        else:  # divert to the person on the way
            con.execute("UPDATE assignments SET status='cancelled', updated_at=? WHERE id=?", (_now(), a["id"]))
            con.execute("UPDATE incidents SET status='suggested', responder_id=NULL WHERE id=?", (a["incident_id"],))
            con.execute("UPDATE incidents SET status='dispatched', responder_id=? WHERE id=?", (al["unit_id"], al["new_incident_id"]))
            core.write_log(con, officer, "diverted", al["new_incident_id"], unit=al["unit"], from_incident=a["incident_id"],
                           via="Route Watch Agent", alert=al["id"])
            notes += v1.on_dispatch(con, al["new_incident_id"], al["unit_id"])
            orig = dict(con.execute("SELECT * FROM incidents WHERE id=?", (a["incident_id"],)).fetchone())
            core.suggest(con, orig)
            txt = f"Divert approved: go to the person on your way (incident #{al['new_incident_id']})."
        con.execute("UPDATE route_alerts SET status='approved', decided_by=?, decided_at=? WHERE id=?", (officer, _now(), al["id"]))
        core.write_log(con, officer, "route_alert_approved", al["incident_id"], alert=al["id"], kind=al["kind"])
        notes.append(("route_alert", {"id": al["id"], "unit_id": al["unit_id"], "kind": "info", "status": "approved", "text": txt}))
    return {**st, "notes": notes}


_graph = None


def graph():
    global _graph
    if _graph is None:
        from langgraph.checkpoint.sqlite import SqliteSaver
        from langgraph.graph import END, START, StateGraph
        g = StateGraph(State)
        g.add_node("read", n_read)
        g.add_node("decide", n_decide)
        g.add_node("officer", n_officer)
        g.add_node("apply", n_apply)
        g.add_edge(START, "read")
        g.add_edge("read", "decide")
        g.add_conditional_edges("decide", route_after_decide, {"officer": "officer", "end": END})
        g.add_edge("officer", "apply")
        g.add_edge("apply", END)
        _graph = g.compile(checkpointer=SqliteSaver(sqlite3.connect(str(RUNS_DB), check_same_thread=False)))
    return _graph


# ---------------------------------------------------------------- entry points
def _event(con, event_id: str) -> Optional[dict]:
    r = con.execute("SELECT * FROM events WHERE event_id=?", (event_id,)).fetchone()
    if not r:
        return None
    e = dict(r)
    e["payload"] = json.loads(e["payload"] or "{}")
    e["role"] = (e["payload"].get("role") or "").upper()
    return e


def match(con, ev: dict) -> list:
    """(assignment, unit, distance_m) for every non-drone unit whose route AHEAD passes near the report."""
    import v1
    out = []
    if ev.get("lat") is None or ev.get("lon") is None:
        return out
    p = (ev["lat"], ev["lon"])
    for a in core.rows(con.execute(
            "SELECT a.* FROM assignments a JOIN responders r ON r.id=a.responder_id "
            "WHERE a.status IN ('dispatched','en_route') AND r.kind NOT IN ('drone')")):
        if a["incident_id"] == ev.get("incident_id"):
            continue  # the report is about the unit's own destination
        coords = json.loads(a["route"] or "[]")
        d = distance_to_route(p, route_ahead(coords, v1.unit_position(con, a["responder_id"])))
        if d <= HELP_M:
            out.append((a, _unit(con, a["responder_id"]), d))
    return out


def watch(event_ids) -> list:
    """Run the agent for new events. Returns notifications to send. Never raises."""
    notes: list = []
    for eid in dict.fromkeys(e for e in event_ids if e):
        try:
            with core.db() as con:
                init(con)
                ev = _event(con, eid)
                if not ev or ev["kind"] not in ("sos", "road_block", "message", "photo"):
                    continue
                hits = match(con, ev)
                photo = None
                if hits and json.loads(ev.get("media") or "[]"):
                    import v1
                    urls = v1.media_urls(con, json.loads(ev["media"]))
                    photo = next((u["url"] for u in urls if u["url"]), None)
            for a, unit, d in hits:
                tid = f"rw-{eid}-{a['id']}"
                st = graph().invoke({"thread_id": tid, "event": ev, "assignment": a, "unit": unit, "distance_m": d,
                                     "photo": photo, "notes": []}, {"configurable": {"thread_id": tid}})
                notes += st.get("notes") or []
        except Exception as exc:  # the agent must never break incoming reports
            with core.db() as con:
                core.write_log(con, "route-watch-agent", "error", None, event=eid, error=str(exc)[:200])
    return notes


def decide(alert_id: int, approve: bool, officer: str) -> list:
    """Officer's answer to a pending alert: resume that alert's paused graph."""
    from langgraph.types import Command
    with core.db() as con:
        init(con)
        al = con.execute("SELECT thread_id, status FROM route_alerts WHERE id=?", (alert_id,)).fetchone()
    if not al:
        raise KeyError(alert_id)
    if al["status"] != "pending":
        return []
    cfg = {"configurable": {"thread_id": al["thread_id"]}}
    snap = graph().get_state(cfg)
    if snap.next:
        st = graph().invoke(Command(resume={"alert_id": alert_id, "approve": approve, "officer": officer}), cfg)
        notes = st.get("notes") or []
    else:  # the graph already finished (e.g. two alerts in one thread): apply directly
        notes = n_apply({"decision": {"alert_id": alert_id, "approve": approve, "officer": officer}}).get("notes") or []
    # a thread can carry two alerts (block + divert): keep it answerable for the other one
    return notes


def alerts(limit: int = 30) -> list:
    with core.db() as con:
        init(con)
        # expire pending alerts whose unit is no longer driving that assignment
        con.execute("UPDATE route_alerts SET status='expired' WHERE status='pending' AND assignment_id IN "
                    "(SELECT id FROM assignments WHERE status NOT IN ('dispatched','en_route'))")
        return core.rows(con.execute("SELECT * FROM route_alerts ORDER BY id DESC LIMIT ?", (limit,)))


def unit_alerts(con, unit_id: int, minutes: int = 30) -> list:
    init(con)
    return core.rows(con.execute(
        "SELECT id, kind, status, text, photo, created_at FROM route_alerts WHERE unit_id=? ORDER BY id DESC LIMIT 5", (unit_id,)))
