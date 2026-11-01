"""Dispatch Planner Agent (LangGraph).

    gather ──▶ plan ──▶ check ──▶ ⏸ human_approval ──▶ execute ──▶ END
    (tools)    (AI)     (code)     (officer decides)    (existing dispatch)

gather   Calls tools (plain code): open incidents, free units, blocked roads, and the
         REAL road ETA from every capable unit to every incident (routes avoid blocked
         roads; drones fly straight).
plan     The AI proposes who goes where, looking at ALL incidents together, with a
         reason per decision. Without AI, a greedy rule does the same job.
check    Plain code rejects anything impossible (busy unit, wrong unit type, a unit
         used twice, a unit that does not exist). The AI cannot sneak anything past this.
human_approval
         The graph PAUSES (LangGraph interrupt). The officer ticks what to approve.
         Nothing moves without that. The paused state is saved (checkpointer), so a
         page reload does not lose the plan.
execute  Uses the same dispatch code as the "Approve dispatch" button, so responder
         phones get their task and route exactly as before. Every dispatch is written
         to the tamper-evident log as "approved by <officer> from AI plan <run>".
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Literal, Optional, TypedDict

from pydantic import BaseModel, Field

import logic
import main as core
import routing
from agents import llm

MAX_INCIDENTS = 12          # plan at most this many waiting incidents at once
CANDIDATES_PER_INCIDENT = 3  # road ETA is computed for the nearest N capable units
RUNS_DB = Path(os.environ.get("AGENT_RUNS_DB") or Path(__file__).resolve().parent.parent / "agent_runs.db")


# ---------------------------------------------------------------- AI output schema
class Assign(BaseModel):
    incident_id: int
    unit_id: int
    reason: str = Field(description="max 25 words: why this unit for this incident")


class Hold(BaseModel):
    incident_id: int
    reason: str = Field(description="max 20 words: why no unit now")


class Plan(BaseModel):
    assignments: list[Assign] = Field(default_factory=list)
    waiting: list[Hold] = Field(default_factory=list, description="incidents that get no unit in this plan")
    summary: str = Field(description="2 sentences for the officer: the overall plan and the main trade-off")


SYSTEM = """You are the dispatch planner of the Dehradun disaster control room.
You get every waiting incident and, for each, the candidate units with their REAL road ETA
(routes already avoid blocked roads; drones fly straight and are fast but carry nobody).
Make ONE plan for all incidents together.
Rules:
- Each unit can go to at most ONE incident. Only use unit ids listed as candidates for that incident.
- Life first: incidents with higher priority, 'critical' AI urgency, more people, children/elderly,
  or 'confirmed' verification come first.
- Prefer the fastest suitable unit, but do not waste the only boat or only fire tender on a minor
  case if a critical case needs it.
- If a road route is impossible (no_road_route), use a drone to assess or a boat for flood.
- 'possible_fake' incidents can still get a unit if nothing more urgent needs it; say so in the reason.
- Incidents you cannot cover go in 'waiting' with the reason.
- Never invent incidents, units or numbers. Keep reasons short and concrete (ETA, people, urgency).
- Describe a unit only by its kind and ETA as given. Never claim equipment it carries (e.g. "has a boat").
"""


class State(TypedDict, total=False):
    run_id: str
    officer: str
    incidents: list
    units: list
    hazards: list
    options: dict
    proposal: dict
    checked: list
    rejected: list
    decision: dict
    executed: list
    notes: list
    steps: list


# ---------------------------------------------------------------- step log (live panel)
_emit: dict[str, Callable[[dict], None]] = {}


def _step(state: State, node: str, text: str, **data) -> list:
    s = {"run_id": state["run_id"], "node": node, "text": text, "at": time.strftime("%H:%M:%S"), **data}
    cb = _emit.get(state["run_id"])
    if cb:
        try:
            cb(s)
        except Exception:
            pass
    return (state.get("steps") or []) + [s]


# ---------------------------------------------------------------- tools (plain code)
def tool_waiting_incidents(con) -> list:
    from agents import verifier
    checked = verifier.latest_map(con)
    urg = core._ai_urgency_map(con)
    out = []
    for i in core.rows(con.execute("SELECT * FROM incidents WHERE status IN ('new','suggested','held')")):
        i["ai_urgency"] = urg.get(i["id"])
        core.enrich(i)
        t = core._ai_triage(con, i["id"]) or {}
        out.append({"id": i["id"], "type": i["type"], "people": i["people"], "priority": i["priority"],
                    "lat": i["lat"], "lon": i["lon"], "ai_urgency": i["ai_urgency"],
                    "vulnerable": t.get("ai_vulnerable"), "needs": t.get("ai_needs"),
                    "verification": checked.get(i["id"]), "summary": t.get("ai_summary") or i["summary"]})
    out.sort(key=lambda x: -x["priority"])
    return out[:MAX_INCIDENTS]


def tool_free_units(con) -> list:
    import v1
    out = []
    for r in core.rows(con.execute("SELECT * FROM responders WHERE status='available'")):
        lat, lon = v1.unit_position(con, r["id"])
        out.append({"id": r["id"], "name": r["name"], "kind": r["kind"], "lat": lat, "lon": lon})
    return out


def tool_blocked_roads(con) -> list:
    return core.rows(con.execute("SELECT id, lat, lon, radius_m, note FROM hazards WHERE status='active'"))


def tool_route_eta(unit: dict, inc: dict, hazards) -> dict:
    import v1
    a, b = (unit["lat"], unit["lon"]), (inc["lat"], inc["lon"])
    r = routing.aerial(a, b) if unit["kind"] in v1.AERIAL_KINDS else routing.plan(a, b, hazards)
    return {"eta_min": r.get("eta_min"), "distance_km": round((r.get("distance_m") or 0) / 1000, 1),
            "route_source": r.get("source"), "no_road_route": bool(r.get("no_road_route"))}


# ---------------------------------------------------------------- graph nodes
def gather(state: State) -> State:
    import v1
    with core.db() as con:
        incidents = tool_waiting_incidents(con)
        steps = _step(state, "gather", f"Tool waiting_incidents() → {len(incidents)} incidents need a unit",
                      tool="waiting_incidents")
        state = {**state, "steps": steps}
        units = tool_free_units(con)
        steps = _step(state, "gather", f"Tool free_units() → {len(units)} free: " + ", ".join(u["name"] for u in units),
                      tool="free_units")
        state = {**state, "steps": steps}
        hz_rows = tool_blocked_roads(con)
        hazards = v1.hazard_objs(con)
    steps = _step(state, "gather", f"Tool blocked_roads() → {len(hz_rows)} active road blocks", tool="blocked_roads")
    state = {**state, "steps": steps}

    options: dict = {}
    calls = 0
    for inc in incidents:
        need = logic.CAPABLE.get(logic.family(inc["type"]), logic.CAPABLE["other"])
        capable = [u for u in units if u["kind"] in need] or units  # nobody capable: offer everyone, AI must explain
        capable.sort(key=lambda u: logic.distance_m(u["lat"], u["lon"], inc["lat"], inc["lon"]))
        opts = []
        for u in capable[:CANDIDATES_PER_INCIDENT]:
            r = tool_route_eta(u, inc, hazards)
            calls += 1
            opts.append({"unit_id": u["id"], "unit": u["name"], "kind": u["kind"], "capable": u["kind"] in need, **r})
        options[str(inc["id"])] = opts
    steps = _step(state, "gather", f"Tool route_eta() × {calls} → real road ETAs (blocked roads avoided)",
                  tool="route_eta", calls=calls)
    return {**state, "incidents": incidents, "units": units, "hazards": hz_rows, "options": options, "steps": steps}


def _greedy(incidents: list, options: dict) -> Plan:
    """Fallback without AI: highest priority first, fastest capable free unit, but do not take
    the ONLY unit another waiting incident could use if an alternative is at most 10 min slower."""
    used, assigns, waiting = set(), [], []

    def capable_free(inc_id):
        return [o for o in options.get(str(inc_id), []) if o["capable"] and o["unit_id"] not in used]

    for n, inc in enumerate(incidents):
        opts = sorted(capable_free(inc["id"]), key=lambda o: o["eta_min"] if o["eta_min"] is not None else 10_000)
        if not opts:
            waiting.append(Hold(incident_id=inc["id"], reason="No free capable unit left"))
            continue
        later = incidents[n + 1:]
        pick, note = opts[0], ""
        for o in opts:
            sole = any([x["unit_id"] for x in capable_free(l["id"])] == [o["unit_id"]] for l in later)
            fast_enough = (o["eta_min"] or 10_000) <= (opts[0]["eta_min"] or 10_000) + 10
            if not sole and fast_enough:
                pick = o
                if o is not opts[0]:
                    note = f"; kept {opts[0]['unit']} free for another incident"
                break
        used.add(pick["unit_id"])
        assigns.append(Assign(incident_id=inc["id"], unit_id=pick["unit_id"],
                              reason=f"Priority {inc['priority']}; free {pick['kind']} in {pick['eta_min']} min{note}"))
    return Plan(assignments=assigns, waiting=waiting,
                summary="Rule plan: highest priority first; fastest capable unit, keeping scarce units for other incidents.")


def plan(state: State) -> State:
    inc_brief = [{k: v for k, v in i.items() if k not in ("lat", "lon")} for i in state["incidents"]]
    if not inc_brief:
        steps = _step(state, "plan", "Nothing waiting: no plan needed")
        return {**state, "proposal": {"assignments": [], "waiting": [], "summary": "No incident is waiting for a unit.",
                                      "source": "none"}, "steps": steps}
    user = json.dumps({"incidents": inc_brief, "candidates_by_incident": state["options"],
                       "active_road_blocks": len(state["hazards"])}, ensure_ascii=False)
    if llm.provider():
        steps = _step(state, "plan", f"Asking {llm.label()} to plan {len(inc_brief)} incidents together…")
        state = {**state, "steps": steps}
    p = llm.structured(Plan, SYSTEM, user)
    source = llm.label()
    if p is None:
        err = llm.status()["last_call"].get("error") if llm.provider() else "no AI key"
        p, source = _greedy(state["incidents"], state["options"]), "rule plan (AI unavailable)"
        steps = _step(state, "plan", f"AI unavailable ({(err or '')[:80]}): used the rule planner instead")
    else:
        steps = _step(state, "plan", f"AI proposed {len(p.assignments)} dispatches, {len(p.waiting)} waiting")
    return {**state, "proposal": {**p.model_dump(), "source": source}, "steps": steps}


def check(state: State) -> State:
    """Plain code: the AI's plan must be possible. Anything impossible is removed with the reason."""
    units = {u["id"]: u for u in state["units"]}
    incs = {i["id"]: i for i in state["incidents"]}
    used: set = set()
    ok, bad = [], []
    for a in state["proposal"]["assignments"]:
        inc, unit = incs.get(a["incident_id"]), units.get(a["unit_id"])
        opt = next((o for o in state["options"].get(str(a["incident_id"]), []) if o["unit_id"] == a["unit_id"]), None)
        problem = None
        if inc is None:
            problem = "incident is not waiting (or does not exist)"
        elif unit is None:
            problem = "unit is not free (or does not exist)"
        elif a["unit_id"] in used:
            problem = "unit already used in this plan"
        elif any(x["incident_id"] == a["incident_id"] for x in ok):
            problem = "incident already has a unit in this plan"
        elif opt is None:
            problem = "unit was not a checked candidate for this incident"
        if problem:
            bad.append({**a, "problem": problem})
            continue
        used.add(a["unit_id"])
        ok.append({**a, "unit": unit["name"], "kind": unit["kind"], "type": inc["type"], "people": inc["people"],
                   "priority": inc["priority"], "ai_urgency": inc.get("ai_urgency"), "verification": inc.get("verification"),
                   "eta_min": opt["eta_min"], "distance_km": opt["distance_km"], "route_source": opt["route_source"],
                   "capable": opt["capable"]})
    # Coverage: did the AI leave an incident waiting while a suitable unit is still free?
    added = []
    covered = {x["incident_id"] for x in ok}
    for inc in state["incidents"]:
        if inc["id"] in covered:
            continue
        free = [o for o in state["options"].get(str(inc["id"]), []) if o["capable"] and o["unit_id"] not in used]
        if not free:
            continue
        o = min(free, key=lambda x: x["eta_min"] if x["eta_min"] is not None else 10_000)
        used.add(o["unit_id"])
        unit = units[o["unit_id"]]
        added.append({"incident_id": inc["id"], "unit_id": o["unit_id"], "unit": unit["name"], "kind": unit["kind"],
                      "type": inc["type"], "people": inc["people"], "priority": inc["priority"],
                      "ai_urgency": inc.get("ai_urgency"), "verification": inc.get("verification"),
                      "eta_min": o["eta_min"], "distance_km": o["distance_km"], "route_source": o["route_source"],
                      "capable": True, "added_by_check": True,
                      "reason": f"Added by safety check: AI left it waiting, but {unit['name']} is free ({o['eta_min']} min)"})
    ok += added
    steps = _step(state, "check", f"Safety check: {len(ok) - len(added)} dispatches valid, {len(bad)} rejected"
                  + (": " + "; ".join(f"#{b['incident_id']} {b['problem']}" for b in bad) if bad else "")
                  + (f"; {len(added)} incident(s) the AI left waiting have a free unit: added for you to decide"
                     if added else ""))
    state = {**state, "steps": steps}
    if ok:  # recorded here because the pause itself happens inside human_approval
        steps = _step(state, "human_approval", "⏸ Paused: waiting for the officer to approve")
    return {**state, "checked": ok, "rejected": bad, "steps": steps}


def human_approval(state: State) -> State:
    from langgraph.types import interrupt
    decision = interrupt({"run_id": state["run_id"], "checked": state["checked"]})
    n = len(decision.get("approved_incident_ids") or [])
    steps = _step(state, "human_approval", f"▶ Officer {decision.get('officer') or ''} decided: {n} approved")
    return {**state, "decision": decision, "steps": steps}


def execute(state: State) -> State:
    import v1
    d = state.get("decision") or {}
    officer = d.get("officer") or state.get("officer") or "Duty Officer"
    approved = set(d.get("approved_incident_ids") or [])
    executed, notes = [], []
    with core.db() as con:
        for a in state["checked"]:
            if a["incident_id"] not in approved:
                continue
            inc = con.execute("SELECT status FROM incidents WHERE id=?", (a["incident_id"],)).fetchone()
            unit = con.execute("SELECT status, name FROM responders WHERE id=?", (a["unit_id"],)).fetchone()
            if not inc or inc["status"] not in ("new", "suggested", "held") or not unit or unit["status"] != "available":
                executed.append({**a, "done": False, "why": "changed since the plan was made"})
                continue
            con.execute("UPDATE incidents SET status='dispatched', responder_id=? WHERE id=?", (a["unit_id"], a["incident_id"]))
            con.execute("UPDATE responders SET status='busy' WHERE id=?", (a["unit_id"],))
            core.write_log(con, officer, "dispatch_approved", a["incident_id"], responder=unit["name"],
                           via="AI dispatch plan", plan_run=state["run_id"], plan_source=state["proposal"]["source"],
                           reason=a["reason"])
            notes += v1.on_dispatch(con, a["incident_id"], a["unit_id"])
            executed.append({**a, "done": True})
        core.write_log(con, officer, "ai_plan_decided", None, plan_run=state["run_id"],
                       approved=len([e for e in executed if e["done"]]), proposed=len(state["checked"]))
    n = len([e for e in executed if e["done"]])
    steps = _step(state, "execute", f"{officer} approved {n} of {len(state['checked'])}: units notified")
    return {**state, "executed": executed, "notes": notes, "steps": steps}


# ---------------------------------------------------------------- graph
_graph = None


def graph():
    global _graph
    if _graph is None:
        from langgraph.checkpoint.sqlite import SqliteSaver
        from langgraph.graph import END, START, StateGraph
        g = StateGraph(State)
        for name, fn in (("gather", gather), ("plan", plan), ("check", check),
                         ("human_approval", human_approval), ("execute", execute)):
            g.add_node(name, fn)
        g.add_edge(START, "gather")
        g.add_edge("gather", "plan")
        g.add_edge("plan", "check")
        g.add_edge("check", "human_approval")
        g.add_edge("human_approval", "execute")
        g.add_edge("execute", END)
        saver = SqliteSaver(sqlite3.connect(str(RUNS_DB), check_same_thread=False))
        _graph = g.compile(checkpointer=saver)
    return _graph


def _public(state: dict) -> dict:
    keys = ("run_id", "proposal", "checked", "rejected", "executed", "steps", "decision")
    return {k: state.get(k) for k in keys}


def start(officer: str, emit: Optional[Callable[[dict], None]] = None) -> dict:
    """Run until the officer approval pause. Returns the plan to show."""
    run_id = uuid.uuid4().hex[:8]
    if emit:
        _emit[run_id] = emit
    cfg = {"configurable": {"thread_id": run_id}}
    try:
        graph().invoke({"run_id": run_id, "officer": officer, "steps": []}, cfg)
        st = graph().get_state(cfg).values
    finally:
        _emit.pop(run_id, None)
    out = _public(st)
    out["status"] = "waiting_for_officer" if st.get("checked") else "nothing_to_approve"
    return out


def resume(run_id: str, approved_incident_ids: list[int], officer: str,
           emit: Optional[Callable[[dict], None]] = None) -> dict:
    """The officer's decision: continue the paused graph."""
    from langgraph.types import Command
    cfg = {"configurable": {"thread_id": run_id}}
    snap = graph().get_state(cfg)
    if not snap.values:
        raise KeyError(run_id)
    if not snap.next:
        out = _public(snap.values)
        out["status"] = "already_decided"
        return out
    if emit:
        _emit[run_id] = emit
    try:
        graph().invoke(Command(resume={"approved_incident_ids": approved_incident_ids, "officer": officer}), cfg)
    finally:
        _emit.pop(run_id, None)
    st = graph().get_state(cfg).values
    out = _public(st)
    out["notes"] = st.get("notes") or []
    out["status"] = "done"
    return out


def get(run_id: str) -> Optional[dict]:
    snap = graph().get_state({"configurable": {"thread_id": run_id}})
    if not snap.values:
        return None
    out = _public(snap.values)
    out["status"] = "waiting_for_officer" if snap.next else "done"
    return out
