"""Commander Assistant Agent (LangGraph ReAct) + Situation Report.

Ask:     The officer asks a question in English, Hindi or Hinglish. A LangGraph ReAct
         agent THINKS -> picks a TOOL -> reads live data -> answers. Tools are READ-ONLY:
         this agent can never dispatch, re-route or change anything. It only answers and
         suggests; the officer still clicks approve.
         After the answer, code checks every incident number (#id) it mentions really
         exists. No AI / no internet: rule answers for the common questions.

SITREP:  Code counts every number from the live database (the "facts"). The AI only
         writes the words (situation, concerns, recommended actions). Code then removes
         any AI line that mentions a number or incident that is not in the facts, so the
         report cannot contain invented figures. No AI: rules write the words.
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

import logic
import main as core
from agents import llm

try:
    from zoneinfo import ZoneInfo
    IST = ZoneInfo("Asia/Kolkata")
except Exception:  # tzdata missing on some Windows Pythons: fall back to local time
    IST = None

WAITING = ("new", "suggested", "held")
MOVING = ("dispatched", "en_route")
STATUS_WORD = {"new": "new", "suggested": "awaiting approval", "held": "held", "dispatched": "dispatched",
               "en_route": "on the way", "on_site": "on site", "resolved": "resolved"}


def _now_ist() -> str:
    d = datetime.now(IST) if IST else datetime.now()
    return d.strftime("%d %b %Y, %H:%M") + (" IST" if IST else "")


# ---------------------------------------------------------------- data access (read-only)
def _safe_rows(con, sql: str, args: tuple = ()) -> list:
    try:
        return core.rows(con.execute(sql, args))
    except Exception:  # table not created yet (e.g. no shelters synced)
        return []


def _incidents(con, open_only: bool = True) -> list:
    from agents import verifier
    checked = verifier.latest_map(con)
    urg = core._ai_urgency_map(con)
    drill = {r[0] for r in con.execute("SELECT DISTINCT incident_id FROM reports WHERE via LIKE 'drill%'")}
    units = {r["id"]: r["name"] for r in core.rows(con.execute("SELECT id, name FROM responders"))}
    q = "SELECT * FROM incidents" + (" WHERE status != 'resolved'" if open_only else "")
    out = []
    for i in core.rows(con.execute(q)):
        i["ai_urgency"] = urg.get(i["id"])
        core.enrich(i)
        t = core._ai_triage(con, i["id"]) or {}
        waited = (logic.now_utc() - logic.parse_time(i["first_report_at"])).total_seconds() / 60
        out.append({
            "id": i["id"], "type": i["type"], "status": STATUS_WORD.get(i["status"], i["status"]), "_status": i["status"],
            "priority": i["priority"], "severity": i["severity"], "people": i["people"],
            "reports": i["report_count"], "waiting_min": int(max(0, waited)),
            "ai_urgency": i["ai_urgency"], "vulnerable": t.get("ai_vulnerable") or [],
            "needs": t.get("ai_needs") or [], "verification": checked.get(i["id"]) or "not checked",
            "drill": i["id"] in drill,
            "unit": units.get(i["responder_id"]) if i["responder_id"] else None,
            "suggested_unit": units.get(i["suggested_responder_id"]) if i["suggested_responder_id"] else None,
            "summary": (t.get("ai_summary") or i["summary"] or "")[:160],
            "lat": i["lat"], "lon": i["lon"],
        })
    out.sort(key=lambda x: -x["priority"])
    return out


def _units(con) -> list:
    tasks = {r["responder_id"]: r for r in _safe_rows(
        con, "SELECT responder_id, incident_id, status, eta_min FROM assignments WHERE status IN ('dispatched','en_route','on_site')")}
    out = []
    for r in core.rows(con.execute("SELECT * FROM responders ORDER BY kind, name")):
        t = tasks.get(r["id"])
        out.append({"id": r["id"], "name": r["name"], "kind": r["kind"],
                    "status": "free" if r["status"] == "available" else "on task",
                    "task": f"#{t['incident_id']} ({STATUS_WORD.get(t['status'], t['status'])}, ETA {t['eta_min']} min)" if t else None,
                    "lat": r["lat"], "lon": r["lon"]})
    return out


def _blocked_roads(con) -> list:
    return [{"id": h["id"], "note": h["note"], "reported_by": h["by"] or h["source"], "since": (h["created_at"] or "")[11:16]}
            for h in _safe_rows(con, "SELECT * FROM hazards WHERE status='active' ORDER BY id DESC")]


def _route_alerts(con) -> list:
    from agents import route_watch
    route_watch.init(con)
    return [{"id": a["id"], "unit": a["unit"], "kind": a["kind"], "status": a["status"], "text": a["text"]}
            for a in _safe_rows(con, "SELECT * FROM route_alerts ORDER BY id DESC LIMIT 10")]


def _shelters(con) -> list:
    return [{"name": s["name"], "status": s["status"], "capacity": s["capacity"]}
            for s in _safe_rows(con, "SELECT name, status, capacity FROM shelters ORDER BY name")]


def _public(inc: dict) -> dict:
    return {k: v for k, v in inc.items() if not k.startswith("_") and k not in ("lat", "lon")}


def _nearest_free(con, inc: dict, n: int = 3) -> list:
    needed = logic.CAPABLE.get(logic.family(inc["type"]), logic.CAPABLE["other"])
    opts = []
    for u in _units(con):
        if u["status"] != "free":
            continue
        d = logic.distance_m(inc["lat"], inc["lon"], u["lat"], u["lon"])
        opts.append({"unit": u["name"], "kind": u["kind"], "km": round(d / 1000, 1),
                     "suitable": u["kind"] in needed})
    opts.sort(key=lambda o: (not o["suitable"], o["km"]))
    return opts[:n]


# ---------------------------------------------------------------- tools for the agent
def _tools():
    from langchain_core.tools import tool

    @tool
    def situation_overview() -> str:
        """Headline numbers right now: open incidents by status and severity, people affected, units free/busy, blocked roads."""
        return json.dumps(facts()["figures"])

    @tool
    def list_incidents(which: str = "open") -> str:
        """List incidents, highest priority first. which = 'open' | 'waiting' (no unit yet) | 'moving' (unit on the way) | 'critical' | 'all'."""
        with core.db() as con:
            items = _incidents(con, open_only=which != "all")
        if which == "waiting":
            items = [i for i in items if i["_status"] in WAITING]
        elif which == "moving":
            items = [i for i in items if i["_status"] in MOVING]
        elif which == "critical":
            items = [i for i in items if i["severity"] == "critical"]
        return json.dumps([_public(i) for i in items[:15]])

    @tool
    def incident_details(incident_id: int) -> str:
        """Everything about one incident: status, people, AI triage, verifier verdict, unit, and nearest free suitable units."""
        with core.db() as con:
            inc = next((i for i in _incidents(con, open_only=False) if i["id"] == incident_id), None)
            if not inc:
                return json.dumps({"error": f"incident #{incident_id} does not exist"})
            msgs = [r["message"] for r in core.rows(con.execute(
                "SELECT message FROM reports WHERE incident_id=? ORDER BY reported_at DESC LIMIT 3", (incident_id,)))]
            near = _nearest_free(con, inc)
        return json.dumps(_public(inc) | {"latest_messages": msgs, "nearest_free_units": near})

    @tool
    def list_units(kind: str = "all") -> str:
        """All response units with free/on-task status and their current task. kind = 'all' or ambulance|rescue|fire|boat|drone|police."""
        with core.db() as con:
            us = _units(con)
        if kind != "all":
            us = [u for u in us if u["kind"] == kind]
        return json.dumps([{k: v for k, v in u.items() if k not in ("lat", "lon", "id")} for u in us])

    @tool
    def blocked_roads() -> str:
        """Roads currently blocked (active hazards) and recent Route Watch alerts (re-routes, stop-to-help)."""
        with core.db() as con:
            return json.dumps({"blocked_roads": _blocked_roads(con), "route_watch_alerts": _route_alerts(con)})

    @tool
    def shelters() -> str:
        """Relief shelters synced from the mesh app, with status and capacity."""
        with core.db() as con:
            return json.dumps(_shelters(con))

    return [situation_overview, list_incidents, incident_details, list_units, blocked_roads, shelters]


SYSTEM = """You are the Commander Assistant in the Dehradun disaster control room (RESQ).
You help the duty officer understand the LIVE situation. Always use the tools to read live data
before answering; never guess or invent incidents, units, numbers or places.
You are READ-ONLY: you cannot dispatch, re-route or change anything. If action is needed, SUGGEST it
and say the officer must approve it on the dashboard.
Answer in the same language style as the question (English, Hindi or Hinglish).
Be short and concrete: max 6 lines, use incident numbers like #14 and unit names exactly as given.
Life first: critical priority, more people, children/elderly, confirmed reports come first.
Mention when something is a DRILL (practice data) or 'possible_fake'.
Do not use markdown tables."""


# ---------------------------------------------------------------- Ask
def _check_ids(answer: str) -> tuple[str, list]:
    """Code check: every #id the AI mentions must exist."""
    with core.db() as con:
        ids = {r[0] for r in con.execute("SELECT id FROM incidents")}
    bad = sorted({int(x) for x in re.findall(r"#(\d+)", answer)} - ids)
    if bad:
        answer += "\n\n⚠ Safety check: " + ", ".join(f"#{b}" for b in bad) + " does not exist; ignore that part."
    return answer, bad


def ask(question: str, history: Optional[list] = None, officer: str = "Duty Officer") -> dict:
    question = (question or "").strip()[:500]
    started = time.time()
    out = None
    model = llm.chat_model()
    if model is not None:
        try:
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                from langgraph.prebuilt import create_react_agent
                agent = create_react_agent(model, _tools(), prompt=SYSTEM)
            msgs = []
            for h in (history or [])[-6:]:
                role = "human" if h.get("role") == "user" else "ai"
                if h.get("text"):
                    msgs.append((role, str(h["text"])[:800]))
            msgs.append(("human", question))
            res = agent.invoke({"messages": msgs}, {"recursion_limit": 12})
            used = []
            for m in res["messages"]:
                if getattr(m, "type", "") == "tool" and m.name not in used:
                    used.append(m.name)
            answer = res["messages"][-1].content
            if isinstance(answer, list):
                answer = " ".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in answer)
            if answer and answer.strip():
                llm._record(True, started)
                out = {"answer": answer.strip(), "tools": used, "source": llm.label()}
        except Exception as exc:  # network, quota, tool-call error: rules answer instead
            llm._record(False, started, f"{type(exc).__name__}: {str(exc)[:300]}")
    if out is None:
        out = rule_answer(question)
        out["source"] = "rule answer" + (" (AI unavailable)" if model is not None else "")
    out["answer"], out["bad_ids"] = _check_ids(out["answer"])
    out["ms"] = round((time.time() - started) * 1000)
    out["at"] = time.strftime("%H:%M:%S")
    with core.db() as con:
        core.write_log(con, officer, "commander_asked", None, question=question[:200],
                       tools=out["tools"], source=out["source"])
    return out


# ---------------------------------------------------------------- rule answers (no AI)
def _ppl(n) -> str:
    return f"{n} {'person' if n == 1 else 'people'}"


def _line(i: dict) -> str:
    bits = [f"#{i['id']} {i['type']}", f"priority {i['priority']}", _ppl(i['people']), i["status"]]
    if i["unit"]:
        bits.append(f"unit {i['unit']}")
    if i["drill"]:
        bits.append("DRILL")
    if i["verification"] == "possible_fake":
        bits.append("possible fake")
    return " · ".join(bits)


def rule_answer(q: str) -> dict:
    s = q.lower()
    with core.db() as con:
        incs = _incidents(con)
        units = _units(con)
        m = re.search(r"#\s*(\d+)|\b(?:incident|case|number|no\.?)\s*(\d+)|^\s*(\d+)\s*\??$", s)
        num = int(next(g for g in m.groups() if g)) if m else None
        ids = {i["id"] for i in incs}
        if num in ids:
            i = next(x for x in incs if x["id"] == num)
            near = _nearest_free(con, i)
            txt = _line(i) + f"\nVerifier: {i['verification']}. {i['summary']}"
            if i["_status"] in WAITING and near:
                txt += "\nNearest free: " + ", ".join(f"{n['unit']} ({n['kind']}, {n['km']} km)" for n in near)
            return {"answer": txt, "tools": ["incident_details"]}
        if re.search(r"road|block|rasta|raasta|sadak|route|reroute", s):
            roads = _blocked_roads(con)
            if not roads:
                return {"answer": "No road is blocked right now.", "tools": ["blocked_roads"]}
            return {"answer": "Blocked roads:\n" + "\n".join(f"• {r['note'] or 'road block'} (by {r['reported_by']}, since {r['since']})" for r in roads),
                    "tools": ["blocked_roads"]}
        if re.search(r"shelter|camp|rahat|aashray", s):
            sh = _shelters(con)
            return {"answer": "\n".join(f"• {x['name']}: {x['status']}" + (f", capacity {x['capacity']}" if x["capacity"] else "") for x in sh)
                    or "No shelters synced yet.", "tools": ["shelters"]}
    if re.search(r"fake|real|verify|sach|jhooth", s):
        sus = [i for i in incs if i["verification"] == "possible_fake"]
        return {"answer": ("Possible fake (still shown, check before sending):\n" + "\n".join("• " + _line(i) for i in sus))
                if sus else "No open incident is marked possible fake.", "tools": ["list_incidents"]}
    waiting = [i for i in incs if i["_status"] in WAITING]
    if re.search(r"first|pehle|priority|urgent|next|kya karu|what should", s):
        if not waiting:
            return {"answer": "Nothing is waiting for a unit. All open incidents have a unit.", "tools": ["list_incidents"]}
        top = waiting[0]
        return {"answer": f"Handle #{top['id']} first: " + _line(top) + ".\nThe officer approves the dispatch on the dashboard.",
                "tools": ["list_incidents"]}
    if re.search(r"no unit|without|waiting|unassigned|bina|pending|approve", s):
        return {"answer": (f"{len(waiting)} waiting for a unit:\n" + "\n".join("• " + _line(i) for i in waiting[:8]))
                if waiting else "Every open incident has a unit.", "tools": ["list_incidents"]}
    kinds = [k for k in ("ambulance", "rescue", "fire", "boat", "drone", "police") if k in s]
    if kinds or re.search(r"unit|free|khali|available|kahan|where", s):
        sel = [u for u in units if not kinds or u["kind"] in kinds]
        return {"answer": "\n".join(f"• {u['name']} ({u['kind']}): {u['status']}" + (f", {u['task']}" if u["task"] else "") for u in sel)
                or "No such unit.", "tools": ["list_units"]}
    f = facts()["figures"]
    return {"answer": f"{f['open_incidents']} open incidents ({f['critical_open']} critical), {f['people_affected']} people affected. "
                      f"{f['waiting_for_unit']} waiting for a unit, {f['units_free']} of {f['units_total']} units free, "
                      f"{f['roads_blocked']} roads blocked.\nTry: 'which incidents have no unit?', 'where is the boat?', '#14'.",
            "tools": ["situation_overview"]}


# ---------------------------------------------------------------- SITREP
def facts() -> dict:
    """Every number in the situation report, counted by code."""
    with core.db() as con:
        allinc = _incidents(con, open_only=False)
        units = _units(con)
        roads = _blocked_roads(con)
        alerts = _route_alerts(con)
        shel = _shelters(con)
        n_reports = con.execute("SELECT COUNT(*) FROM reports").fetchone()[0]
        mesh = con.execute("SELECT COUNT(*) FROM reports WHERE source='mesh'").fetchone()[0]
        reroutes = con.execute("SELECT COUNT(*) FROM log WHERE action IN ('rerouted','rerouted_precaution')").fetchone()[0]
        dispatches = con.execute("SELECT COUNT(*) FROM log WHERE action='dispatch_approved'").fetchone()[0]
    stats = core.stats()
    open_ = [i for i in allinc if i["_status"] != "resolved"]
    waiting = [i for i in open_ if i["_status"] in WAITING]
    by = lambda key, items: {k: sum(1 for i in items if i[key] == k) for k in sorted({i[key] for i in items})}
    kinds = sorted({u["kind"] for u in units})
    figures = {
        "open_incidents": len(open_), "resolved_incidents": len(allinc) - len(open_),
        "critical_open": sum(i["severity"] == "critical" for i in open_),
        "people_affected": sum(i["people"] or 0 for i in open_),
        "incidents_with_children_or_elderly": sum(bool(i["vulnerable"]) for i in open_),
        "waiting_for_unit": len(waiting), "unit_on_the_way": sum(i["_status"] in MOVING for i in open_),
        "unit_on_site": sum(i["_status"] == "on_site" for i in open_),
        "possible_fake": sum(i["verification"] == "possible_fake" for i in open_),
        "drill_incidents": sum(i["drill"] for i in open_),
        "units_total": len(units), "units_free": sum(u["status"] == "free" for u in units),
        "roads_blocked": len(roads), "units_rerouted": reroutes, "dispatches_approved": dispatches,
        "route_alerts_pending": sum(a["status"] == "pending" for a in alerts),
        "reports_received": n_reports, "reports_via_mesh": mesh,
        "median_minutes_to_dispatch": stats.get("median_minutes_to_dispatch"),
    }
    return {
        "generated_at": _now_ist(),
        "figures": figures,
        "open_by_severity": by("severity", open_),
        "open_by_type": by("type", open_),
        "units_by_kind": {k: {"free": sum(u["kind"] == k and u["status"] == "free" for u in units),
                              "total": sum(u["kind"] == k for u in units)} for k in kinds},
        "top_waiting": [_public(i) for i in waiting[:6]],
        "units_on_task": [{"unit": u["name"], "task": u["task"]} for u in units if u["task"]],
        "blocked_roads": roads,
        "shelters": shel,
    }


class SitrepText(BaseModel):
    headline: str = Field(description="one line, max 20 words: the overall situation")
    situation: str = Field(description="2-3 sentences for the District Magistrate / SDRF: what is happening now")
    concerns: list[str] = Field(default_factory=list, description="max 4 key concerns, each max 20 words")
    actions: list[str] = Field(default_factory=list, description="max 5 recommended actions for the officer to decide, each max 20 words")


SITREP_SYSTEM = """You write the situation report (SITREP) of the Dehradun disaster control room for the
District Magistrate and SDRF. You get FACTS as JSON, counted by code from the live database.
Use ONLY numbers, incident ids (#id), unit names and places that appear in the facts; never invent any.
Plain, formal English. Recommended actions are suggestions for the officer to approve, not orders.
Life first: critical incidents, children/elderly, people waiting longest. Mention drills and possible fakes if any."""


def _numbers(obj) -> set:
    found: set = set()
    for x in re.findall(r"\d+(?:\.\d+)?", json.dumps(obj, ensure_ascii=False)):
        found.add(x)
        found.add(x.split(".")[0])
    return found


def _ok_line(line: str, allowed: set) -> bool:
    return all(n in allowed for n in re.findall(r"\d+(?:\.\d+)?", line))


def _rule_text(f: dict) -> SitrepText:
    g = f["figures"]
    concerns, actions = [], []
    for i in f["top_waiting"][:3]:
        if i["severity"] in ("critical", "high"):
            concerns.append(f"#{i['id']} {i['type']} ({_ppl(i['people'])}) waiting {i['waiting_min']} min without a unit.")
            actions.append(f"Approve a unit for #{i['id']} {i['type']}" + (f" (suggested: {i['suggested_unit']})." if i["suggested_unit"] else "."))
    if g["roads_blocked"]:
        concerns.append(f"{g['roads_blocked']} road(s) blocked; units are being re-routed.")
        actions.append("Send police or a drone to confirm and clear blocked roads.")
    if g["possible_fake"]:
        concerns.append(f"{g['possible_fake']} report(s) marked possible fake; verify before committing scarce units.")
    if g["units_free"] == 0:
        concerns.append("No unit is free.")
        actions.append("Request mutual aid from SDRF / neighbouring districts.")
    if g["route_alerts_pending"]:
        actions.append(f"Decide {g['route_alerts_pending']} pending Route Watch alert(s).")
    return SitrepText(
        headline=f"{g['open_incidents']} open incidents, {g['critical_open']} critical, {g['people_affected']} people affected.",
        situation=(f"The control room is handling {g['open_incidents']} open incidents affecting {_ppl(g['people_affected'])}; "
                   f"{g['waiting_for_unit']} waiting for a unit, {g['unit_on_the_way']} with a unit on the way. "
                   f"{g['units_free']} of {g['units_total']} units are free and {g['roads_blocked']} road(s) are blocked."),
        concerns=concerns[:4], actions=actions[:5])


def sitrep(officer: str = "Duty Officer") -> dict:
    f = facts()
    allowed = _numbers(f) | {"1", "2", "3"}
    removed = 0
    txt = llm.structured(SitrepText, SITREP_SYSTEM, json.dumps(f, ensure_ascii=False))
    source = llm.label() if txt else "rule text"
    if txt is None:
        txt = _rule_text(f)
    else:  # code check: drop any AI line with a number or #id that is not in the facts
        rule = _rule_text(f)
        if not _ok_line(txt.headline, allowed):
            txt.headline, removed = rule.headline, removed + 1
        if not _ok_line(txt.situation, allowed):
            txt.situation, removed = rule.situation, removed + 1
        keep_c = [c for c in txt.concerns[:4] if _ok_line(c, allowed)]
        keep_a = [a for a in txt.actions[:5] if _ok_line(a, allowed)]
        removed += len(txt.concerns[:4]) - len(keep_c) + len(txt.actions[:5]) - len(keep_a)
        txt.concerns, txt.actions = keep_c, keep_a
    md = _markdown(f, txt, officer, source, removed)
    with core.db() as con:
        core.write_log(con, officer, "sitrep_generated", None, source=source, removed_lines=removed,
                       open=f["figures"]["open_incidents"], critical=f["figures"]["critical_open"])
    return {"facts": f, "text": txt.model_dump(), "source": source, "removed_lines": removed,
            "markdown": md, "generated_at": f["generated_at"]}


def _markdown(f: dict, t: SitrepText, officer: str, source: str, removed: int) -> str:
    g = f["figures"]
    L = [f"SITUATION REPORT · RESQ Dehradun Disaster Control Room",
         f"As of {f['generated_at']} · Prepared by {officer}", "",
         t.headline, "", "1. SITUATION", t.situation, "",
         "2. KEY FIGURES",
         f"Open incidents: {g['open_incidents']} (critical {g['critical_open']}) · Resolved: {g['resolved_incidents']}",
         f"People affected: {g['people_affected']} · Incidents with children/elderly: {g['incidents_with_children_or_elderly']}",
         f"Waiting for a unit: {g['waiting_for_unit']} · Unit on the way: {g['unit_on_the_way']} · On site: {g['unit_on_site']}",
         f"Units free: {g['units_free']} of {g['units_total']} · Dispatches approved: {g['dispatches_approved']}"
         + (f" · Median time to dispatch: {g['median_minutes_to_dispatch']} min" if g["median_minutes_to_dispatch"] is not None else ""),
         f"Reports received: {g['reports_received']} ({g['reports_via_mesh']} via offline mesh)"
         + (f" · Possible fake: {g['possible_fake']}" if g["possible_fake"] else "")
         + (f" · Drill: {g['drill_incidents']}" if g["drill_incidents"] else ""), "",
         "3. INCIDENTS WAITING FOR A UNIT"]
    L += [f"• #{i['id']} {i['type']} · priority {i['priority']} ({i['severity']}) · {_ppl(i['people'])} · waiting {i['waiting_min']} min"
          + (" · DRILL" if i["drill"] else "") + (" · possible fake" if i["verification"] == "possible_fake" else "")
          for i in f["top_waiting"]] or ["• None"]
    L += ["", "4. RESOURCES"]
    L += [f"• {k}: {v['free']} free of {v['total']}" for k, v in f["units_by_kind"].items()]
    L += [f"• {u['unit']} → {u['task']}" for u in f["units_on_task"]]
    L += ["", "5. ROADS"]
    L += [f"• Blocked: {r['note'] or 'road block'} (by {r['reported_by']}, since {r['since']})" for r in f["blocked_roads"]] or ["• No road blocked"]
    if g["units_rerouted"]:
        L.append(f"• Units re-routed so far: {g['units_rerouted']}")
    if f["shelters"]:
        L += ["", "6. SHELTERS"] + [f"• {s['name']}: {s['status']}" + (f", capacity {s['capacity']}" if s["capacity"] else "") for s in f["shelters"]]
    L += ["", "KEY CONCERNS"] + ([f"• {c}" for c in t.concerns] or ["• None"])
    L += ["", "RECOMMENDED ACTIONS (for officer decision)"] + ([f"• {a}" for a in t.actions] or ["• None"])
    L += ["", f"Figures counted by code from the live database. Text: {source}."
          + (f" Safety check removed {removed} AI line(s) that used numbers not in the data." if removed else "")]
    return "\n".join(L)
