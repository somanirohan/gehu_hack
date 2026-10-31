"""Agents with a FAKE model (no key, no internet needed)."""
import os
import tempfile
import json
import time

os.environ.setdefault("RESCUE_DB", os.path.join(tempfile.mkdtemp(), "agents.db"))
os.environ["USE_OSRM"] = "0"

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
import routing  # noqa: E402
from agents import llm, triage  # noqa: E402

client = TestClient(main.app)
DDN = (30.3165, 78.0322)
calls = []


_real_structured = llm.structured


def fake_structured(schema, system, user):
    if not llm.provider():  # same contract as the real one: no key -> None
        return None
    if schema is not triage.Triage:  # e.g. the Verifier Agent's verdict
        return schema(verdict="unverified", reasons="fake model")
    calls.append(user)
    if "boom" in user:
        return None
    return triage.Triage(kind="sos", incident_type="trapped", people=3, injured=None, vulnerable=["elderly"],
                         urgency="critical", landmarks=["Tapkeshwar mandir"], needs=["boat", "rescue"],
                         summary_en="3 people trapped on a roof near Tapkeshwar temple, water rising; one elderly.",
                         language="Hinglish", confidence=0.9, reasons="'fase', 'chhat par', 'paani badh raha'")


def setup_function():
    routing.set_network(routing.RoadNetwork.grid(*DDN, rows=16, cols=16, spacing_m=220))
    client.post("/api/demo/reset")
    calls.clear()
    llm.structured = fake_structured
    os.environ["GROQ_API_KEY"] = "test"


def teardown_function():
    os.environ.pop("GROQ_API_KEY", None)
    llm.structured = _real_structured


def bundle(*msgs):
    return {"bundle_schema": "bitchat.civ.sync/v1", "produced_at": int(time.time() * 1000), "incidents": list(msgs), "shelters": []}


def msg(i, content):
    return {"id": f"a{i}", "timestamp": int(time.time() * 1000), "sender": "u", "role": "CIVILIAN",
            "lat": DDN[0], "lon": DDN[1], "content": f"{content} geo:{DDN[0]},{DDN[1]}"}


def test_ai_reading_is_used_and_labelled():
    client.post("/api/v1/bitchat/civ-sync", json=bundle(msg(1, "TEST bachao 3 log chhat par, ek buzurg")))
    inc = client.get("/api/incidents").json()[0]
    assert inc["type"] == "trapped" and inc["people"] == 3 and inc["ai_urgency"] == "critical"
    assert "AI read it as critical +15" in inc["priority_reason"]
    d = client.get(f"/api/incidents/{inc['id']}").json()["ai_triage"]
    assert d["ai_vulnerable"] == "elderly" and d["category_source"].startswith("AI suggestion")
    assert "geo:" not in calls[0]


def test_repeats_do_not_call_the_ai_again():
    b = bundle(msg(2, "bachao"))
    client.post("/api/v1/bitchat/civ-sync", json=b)
    client.post("/api/v1/bitchat/civ-sync", json=b)
    assert len(calls) == 1


def test_ai_failure_falls_back_to_rules():
    client.post("/api/v1/bitchat/civ-sync", json=bundle(msg(3, "boom aag lagi hai")))
    inc = client.get("/api/incidents").json()[0]
    assert inc["type"] == "fire" and inc["ai_urgency"] is None
    assert client.get("/api/v1/feed").json()[0]["payload"]["category_source"] == "rule suggestion"


def test_no_key_means_rules_only():
    os.environ.pop("GROQ_API_KEY")
    client.post("/api/v1/bitchat/civ-sync", json=bundle(msg(4, "aag lagi hai")))
    assert calls == [] and client.get("/api/incidents").json()[0]["type"] == "fire"


def test_try_endpoint():
    r = client.post("/api/v1/agents/triage", json={"text": "bachao"}).json()
    assert r["kind"] == "sos" and r["ai"]["urgency"] == "critical"


# ---------- Verifier Agent ----------
from agents import verifier  # noqa: E402


def _v(verdict, reasons):
    return verifier.Verdict(verdict=verdict, reasons=reasons)


def test_verifier_rules_two_senders_confirm():
    os.environ.pop("GROQ_API_KEY")  # rules only
    m1 = dict(msg(20, "aag lagi hai"), sender="a")
    m2 = dict(msg(21, "aag aag jaldi"), sender="b")
    client.post("/api/v1/bitchat/civ-sync", json=bundle(m1))
    inc = client.get("/api/incidents").json()[0]
    assert inc["verification"] == "unverified"
    client.post("/api/v1/bitchat/civ-sync", json=bundle(m2))
    d = client.get(f"/api/incidents/{inc['id']}").json()
    assert d["verification"]["verdict"] == "confirmed" and d["verification"]["source"] == "rule check"
    assert d["verification"]["evidence"]["different_senders"] == 2


def test_verifier_rules_test_word_and_outside_area():
    os.environ.pop("GROQ_API_KEY")
    client.post("/api/v1/bitchat/civ-sync", json=bundle(msg(22, "test test aag lagi")))
    assert client.get("/api/incidents").json()[0]["verification"] == "possible_fake"
    client.post("/api/demo/reset")
    far = dict(msg(23, "aag lagi"), lat=19.07, lon=72.87)
    client.post("/api/v1/bitchat/civ-sync", json=bundle(far))
    assert client.get("/api/incidents").json()[0]["verification"] == "possible_fake"


def test_verifier_uses_ai_verdict_with_label():
    def fake(schema, system, user):
        if schema is verifier.Verdict:
            assert "different_senders" in user  # the AI only sees gathered evidence
            assert "practice_drill" not in user  # drill status is shown by the badge, not judged
            return _v("likely", "Single detailed report inside Dehradun")
        return fake_structured(schema, system, user)
    llm.structured = fake
    client.post("/api/v1/bitchat/civ-sync", json=bundle(msg(24, "bachao")))
    inc = client.get("/api/incidents").json()[0]
    d = client.get(f"/api/incidents/{inc['id']}").json()["verification"]
    assert d["verdict"] == "likely" and d["source"].startswith("AI suggestion")


def test_verifier_never_changes_priority():
    os.environ.pop("GROQ_API_KEY")
    client.post("/api/v1/bitchat/civ-sync", json=bundle(msg(25, "test aag lagi")))
    inc = client.get("/api/incidents").json()[0]
    assert inc["verification"] == "possible_fake" and "fake" not in inc["priority_reason"]


# ---------- Dispatch Planner (LangGraph) ----------
from agents import planner  # noqa: E402


def _two_incidents():
    client.post("/api/v1/bitchat/civ-sync", json=bundle(dict(msg(30, "aag lagi hai"), sender="a")))
    far = dict(msg(31, "paani mein fase hain"), sender="b", lat=DDN[0] + 0.03, lon=DDN[1] + 0.03)
    client.post("/api/v1/bitchat/civ-sync", json=bundle(far))
    return client.get("/api/incidents").json()


def test_planner_rule_fallback_pauses_and_needs_officer():
    os.environ.pop("GROQ_API_KEY")
    incs = _two_incidents()
    r = client.post("/api/v1/agents/plan", json={"officer": "Rao"}).json()
    assert r["status"] == "waiting_for_officer" and r["proposal"]["source"].startswith("rule plan")
    assert len(r["checked"]) == 2
    nodes = [s["node"] for s in r["steps"]]
    assert nodes[:4] == ["gather", "gather", "gather", "gather"] and "human_approval" in nodes
    # nothing dispatched yet
    assert all(i["status"] in ("new", "suggested") for i in client.get("/api/incidents").json())
    # officer approves only one
    keep = r["checked"][0]["incident_id"]
    d = client.post(f"/api/v1/agents/plan/{r['run_id']}/decide", json={"approved_incident_ids": [keep], "officer": "Rao"}).json()
    assert d["status"] == "done" and sum(e["done"] for e in d["executed"]) == 1
    st = {i["id"]: i["status"] for i in client.get("/api/incidents").json()}
    assert st[keep] == "dispatched" and list(st.values()).count("dispatched") == 1
    log = client.get("/api/log?limit=60").json()
    assert any(e["action"] == "dispatch_approved" and e["detail"].get("via") == "AI dispatch plan" for e in log)
    # deciding twice does nothing more
    again = client.post(f"/api/v1/agents/plan/{r['run_id']}/decide", json={"approved_incident_ids": [], "officer": "Rao"}).json()
    assert again["status"] == "already_decided"
    assert len(incs) == 2


def test_planner_check_rejects_impossible_ai_plan():
    incs = _two_incidents()
    ids = [i["id"] for i in incs]

    def fake(schema, system, user):
        if schema is planner.Plan:
            data = json.loads(user)
            opts = data["candidates_by_incident"]
            u = opts[str(ids[0])][0]["unit_id"]
            return planner.Plan(assignments=[planner.Assign(incident_id=ids[0], unit_id=u, reason="fast"),
                                             planner.Assign(incident_id=ids[1], unit_id=u, reason="same unit twice"),
                                             planner.Assign(incident_id=999, unit_id=1, reason="made up")],
                                waiting=[], summary="test")
        return fake_structured(schema, system, user)
    llm.structured = fake
    r = client.post("/api/v1/agents/plan", json={}).json()
    assert r["proposal"]["source"].startswith("AI suggestion")
    assert len(r["rejected"]) == 2
    extra = [a for a in r["checked"] if a.get("added_by_check")]
    assert len(r["checked"]) == 2 and len(extra) == 1 and extra[0]["incident_id"] == ids[1]
    assert {b["problem"] for b in r["rejected"]} == {"unit already used in this plan", "incident is not waiting (or does not exist)"}


def test_planner_nothing_waiting():
    os.environ.pop("GROQ_API_KEY")
    r = client.post("/api/v1/agents/plan", json={}).json()
    assert r["status"] == "nothing_to_approve"


# ---------- Route Watch Agent ----------
from agents import route_watch  # noqa: E402
import routing as _r  # noqa: E402,F401


def _dispatch_far(unit_kind="ambulance"):
    """A unit driving to an incident ~3 km away; returns (incident, unit, route)."""
    routing.set_network(routing.RoadNetwork.grid(*DDN, rows=40, cols=40, spacing_m=220))
    far = dict(msg(40, "ghayal aadmi, 2 log"), sender="z", lat=DDN[0] + 0.025, lon=DDN[1] + 0.02)
    client.post("/api/v1/bitchat/civ-sync", json=bundle(far))
    inc = client.get("/api/incidents").json()[0]
    unit = [u for u in client.get("/api/v1/units").json() if u["kind"] == unit_kind][0]
    client.post(f"/api/incidents/{inc['id']}/approve", json={"officer": "Rao", "responder_id": unit["id"]})
    a = [u for u in client.get("/api/v1/units").json() if u["id"] == unit["id"]][0]["assignment"]
    return inc, unit, a


def _mid(route):
    return route[len(route) // 2]


def test_route_watch_short_detour_reroutes_now():
    os.environ.pop("GROQ_API_KEY")  # rules only
    inc, unit, a = _dispatch_far()
    lat, lon = _mid(a["route"])
    client.post("/api/v1/bitchat/civ-sync", json=bundle(dict(msg(41, "road band, ped gir gaya"), sender="c", lat=lat, lon=lon)))
    al = client.get("/api/v1/agents/route-alerts").json()
    assert al and al[0]["kind"] == "reroute" and al[0]["status"] == "auto" and al[0]["unit_id"] == unit["id"]
    a2 = [u for u in client.get("/api/v1/units").json() if u["id"] == unit["id"]][0]["assignment"]
    assert a2["route_version"] == 2 and "Precaution" in a2["reroute_reason"]


def test_route_watch_long_detour_waits_for_officer(monkeypatch):
    os.environ.pop("GROQ_API_KEY")
    monkeypatch.setattr(route_watch, "AUTO_MAX_MIN", -1)
    inc, unit, a = _dispatch_far()
    lat, lon = _mid(a["route"])
    client.post("/api/v1/bitchat/civ-sync", json=bundle(dict(msg(42, "bridge broken, cannot pass"), sender="c", lat=lat, lon=lon)))
    al = client.get("/api/v1/agents/route-alerts").json()[0]
    assert al["status"] == "pending"
    a1 = [u for u in client.get("/api/v1/units").json() if u["id"] == unit["id"]][0]["assignment"]
    assert a1["route_version"] == 1  # nothing moved yet
    client.post(f"/api/v1/agents/route-alerts/{al['id']}/decide", json={"approve": True, "officer": "Rao"})
    a2 = [u for u in client.get("/api/v1/units").json() if u["id"] == unit["id"]][0]["assignment"]
    assert a2["route_version"] == 2
    assert client.get("/api/v1/agents/route-alerts").json()[0]["status"] == "approved"


def test_route_watch_far_report_changes_nothing():
    os.environ.pop("GROQ_API_KEY")
    inc, unit, a = _dispatch_far()
    client.post("/api/v1/bitchat/civ-sync", json=bundle(dict(msg(43, "road band"), sender="c", lat=DDN[0] - 0.03, lon=DDN[1] - 0.03)))
    assert client.get("/api/v1/agents/route-alerts").json() == []


def test_route_watch_stop_to_help_divert():
    os.environ.pop("GROQ_API_KEY")
    inc, unit, a = _dispatch_far()
    lat, lon = _mid(a["route"])
    client.post("/api/v1/bitchat/civ-sync", json=bundle(dict(msg(44, "accident, ek aadmi ghayal behosh"), sender="d", lat=lat, lon=lon)))
    alerts = client.get("/api/v1/agents/route-alerts").json()
    div = [x for x in alerts if x["kind"] == "divert"]
    assert div and div[0]["status"] == "pending" and "Divert?" in div[0]["text"]
    client.post(f"/api/v1/agents/route-alerts/{div[0]['id']}/decide", json={"approve": True, "officer": "Rao"})
    st = {i["id"]: i for i in client.get("/api/incidents").json()}
    assert st[div[0]["new_incident_id"]]["status"] == "dispatched"
    assert st[inc["id"]]["status"] == "suggested"
    log = client.get("/api/log?limit=60").json()
    assert any(e["action"] == "diverted" for e in log)


def test_route_watch_ignore_keeps_route():
    os.environ.pop("GROQ_API_KEY")
    inc, unit, a = _dispatch_far()
    lat, lon = _mid(a["route"])
    client.post("/api/v1/bitchat/civ-sync", json=bundle(dict(msg(45, "accident, 1 ghayal"), sender="d", lat=lat, lon=lon)))
    div = [x for x in client.get("/api/v1/agents/route-alerts").json() if x["kind"] == "divert"][0]
    client.post(f"/api/v1/agents/route-alerts/{div['id']}/decide", json={"approve": False, "officer": "Rao"})
    st = {i["id"]: i for i in client.get("/api/incidents").json()}
    assert st[inc["id"]]["status"] == "dispatched"


def test_route_watch_never_touches_drones():
    os.environ.pop("GROQ_API_KEY")
    inc, unit, a = _dispatch_far("drone")
    lat, lon = _mid(a["route"])
    client.post("/api/v1/bitchat/civ-sync", json=bundle(dict(msg(46, "road band"), sender="c", lat=lat, lon=lon)))
    assert client.get("/api/v1/agents/route-alerts").json() == []
