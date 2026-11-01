"""Officer actions on a route clicked on the map: cancel the dispatch, or mark it complete."""
import os
import tempfile
import uuid

os.environ["RESCUE_DB"] = os.path.join(tempfile.mkdtemp(), "routes.db")
os.environ["USE_OSRM"] = "0"

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
import routing  # noqa: E402

client = TestClient(main.app)
LAT, LON = 30.3165, 78.0322


def setup_function():
    routing.set_network(routing.RoadNetwork.grid(LAT, LON, rows=16, cols=16, spacing_m=220))
    client.post("/api/demo/reset")


def dispatched():
    """An SOS with an ambulance on the way; returns (incident_id, unit, assignment)."""
    r = client.post("/api/v1/events", json={"event_id": uuid.uuid4().hex, "kind": "sos", "lat": LAT + 0.01, "lon": LON,
                                            "payload": {"type": "injured", "people": 1, "message": "accident"}}).json()
    iid = r["incident_id"]
    amb = next(u for u in client.get("/api/responders").json() if u["kind"] == "ambulance" and u["status"] == "available")
    assert client.post(f"/api/incidents/{iid}/approve", json={"officer": "T", "responder_id": amb["id"]}).status_code == 200
    unit = next(u for u in client.get("/api/v1/units").json() if u["id"] == amb["id"])
    return iid, unit, unit["assignment"]


def test_units_list_has_what_the_route_panel_shows():
    _, _, a = dispatched()
    for key in ("id", "incident_id", "status", "route", "eta_min", "distance_m", "route_source", "created_at"):
        assert key in a, key
    assert len(a["route"]) > 1


def test_cancel_frees_unit_and_puts_incident_back_in_the_queue():
    iid, unit, a = dispatched()
    r = client.post(f"/api/v1/assignments/{a['id']}/cancel", json={"officer": "Insp. Rawat", "reason": "wrong address"})
    assert r.status_code == 200
    inc = client.get(f"/api/incidents/{iid}").json()
    assert inc["status"] == "suggested" and inc["responder_id"] is None
    assert inc["suggested_responder_id"]  # a fresh suggestion is ready for the officer
    u = next(x for x in client.get("/api/v1/units").json() if x["id"] == unit["id"])
    assert u["status"] == "available" and u["assignment"] is None
    log = client.get("/api/log").json()
    entries = log if isinstance(log, list) else log["entries"]
    assert any(e["action"] == "dispatch_cancelled" and "wrong address" in str(e["detail"]) for e in entries)
    # the responder's phone sees no task any more
    tok = client.post("/api/v1/units/login", json={"code": unit["code"], "pin": "1234"}).json()["token"]
    assert client.get("/api/v1/units/me/task", headers={"Authorization": f"Bearer {tok}"}).json()["task"] is None
    # and the incident can be dispatched again
    again = client.post(f"/api/incidents/{iid}/approve", json={"officer": "T"})
    assert again.status_code == 200


def test_complete_resolves_incident_from_any_stage():
    iid, unit, a = dispatched()  # still 'dispatched': the officer can close it directly
    r = client.post(f"/api/v1/assignments/{a['id']}/complete", json={"officer": "Insp. Rawat"})
    assert r.status_code == 200 and r.json()["status"] == "resolved"
    assert client.get(f"/api/incidents/{iid}").json()["status"] == "resolved"
    u = next(x for x in client.get("/api/v1/units").json() if x["id"] == unit["id"])
    assert u["status"] == "available" and u["assignment"] is None


def test_ground_team_flow_still_works():
    iid, unit, _ = dispatched()
    tok = client.post("/api/v1/units/login", json={"code": unit["code"], "pin": "1234"}).json()["token"]
    h = {"Authorization": f"Bearer {tok}"}
    for st in ("en_route", "on_site", "resolved"):
        assert client.post("/api/v1/units/me/status", json={"status": st}, headers=h).status_code == 200
    assert client.get(f"/api/incidents/{iid}").json()["status"] == "resolved"


def test_ended_route_cannot_be_cancelled_or_completed_twice():
    _, _, a = dispatched()
    assert client.post(f"/api/v1/assignments/{a['id']}/complete", json={}).status_code == 200
    assert client.post(f"/api/v1/assignments/{a['id']}/cancel", json={}).status_code == 409
    assert client.post(f"/api/v1/assignments/{a['id']}/complete", json={}).status_code == 409
    assert client.post("/api/v1/assignments/99999/cancel", json={}).status_code == 404


def test_responder_phone_is_told_who_cancelled_or_completed(monkeypatch):
    sent = []

    async def capture(event, data):
        sent.append((event, data))

    monkeypatch.setattr(main.hub, "send", capture)
    _, unit, a = dispatched()
    client.post(f"/api/v1/assignments/{a['id']}/cancel", json={"officer": "Insp. Rawat", "reason": "duplicate call"})
    st = [d for e, d in sent if e == "assignment_status"]
    assert st[-1]["status"] == "cancelled" and st[-1]["unit_id"] == unit["id"] and "duplicate call" in st[-1]["text"]

    _, unit2, a2 = dispatched()
    client.post(f"/api/v1/assignments/{a2['id']}/complete", json={"officer": "Insp. Rawat"})
    st = [d for e, d in sent if e == "assignment_status"]
    assert st[-1] == {"incident_id": a2["incident_id"], "status": "completed", "by": "Insp. Rawat",
                      "assignment_id": a2["id"], "unit_id": unit2["id"]}
