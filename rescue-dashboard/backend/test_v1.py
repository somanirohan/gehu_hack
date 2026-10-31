import base64
import io
import os
import tempfile
import uuid

os.environ["RESCUE_DB"] = os.path.join(tempfile.mkdtemp(), "v1.db")
os.environ["USE_OSRM"] = "0"

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
import routing  # noqa: E402

client = TestClient(main.app)
LAT, LON = 18.5204, 73.8567


def setup_function():
    routing.set_network(routing.RoadNetwork.grid(LAT, LON, rows=16, cols=16, spacing_m=220))
    client.post("/api/demo/reset")


def ev(kind, lat=LAT, lon=LON, **payload):
    return {"event_id": uuid.uuid4().hex, "kind": kind, "lat": lat, "lon": lon, "device_id": "phoneA",
            "via": {"path": "mesh", "hops": 2, "held_seconds": 300}, "payload": payload}


def tiny_jpeg():
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), (200, 80, 60)).save(buf, "JPEG")
    return base64.b64encode(buf.getvalue()).decode()


def login(code):
    return {"Authorization": "Bearer " + client.post("/api/v1/units/login", json={"code": code, "pin": "1234"}).json()["token"]}


def test_sos_event_creates_incident_and_is_idempotent():
    e = ev("sos", type="trapped", people=4, message="Roof, water rising")
    r = client.post("/api/v1/events", json=e).json()
    assert r["handled_as"] == "new incident" and r["incident_id"]
    assert client.post("/api/v1/events", json=e).json()["duplicate"] is True
    out = client.get("/api/v1/outbox").json()["items"]
    assert any(i["kind"] == "received" and i["ref"] == e["event_id"] for i in out)


def test_photo_and_message_attach_to_nearby_incident():
    sos = ev("sos", type="injured", people=2)
    iid = client.post("/api/v1/events", json=sos).json()["incident_id"]
    photo = ev("photo", lat=LAT + 0.0005, caption="Leg injury")
    photo["media"] = [{"media_id": "m1", "b64": tiny_jpeg()}]
    r = client.post("/api/v1/events", json=photo).json()
    assert r["incident_id"] == iid
    msg = ev("message", text="Second person unconscious", ref_event_id=sos["event_id"])
    msg["lat"] = None
    assert client.post("/api/v1/events", json=msg).json()["incident_id"] == iid
    inc = client.get(f"/api/incidents/{iid}").json()
    assert inc["report_count"] == 3 and inc["photo"]


def test_full_photo_can_arrive_after_event():
    e = ev("photo", caption="far away")
    e["media"] = [{"media_id": "late1"}]
    client.post("/api/v1/events", json=e)
    feed = client.get("/api/v1/feed").json()
    assert feed[0]["media"][0]["pending"] is True
    raw = base64.b64decode(tiny_jpeg())
    client.post("/api/v1/media", data={"media_id": "late1"}, files={"file": ("p.jpg", raw, "image/jpeg")})
    assert client.get("/api/v1/feed").json()[0]["media"][0]["pending"] is False


def test_unknown_kind_is_stored_and_registry_kind_creates_incident():
    r = client.post("/api/v1/events", json=ev("battery_low", level=12)).json()
    assert r["handled_as"] == "stored"
    assert client.get("/api/v1/feed").json()[0]["kind"] == "battery_low"
    r2 = client.post("/api/v1/events", json=ev("medical_need", need="insulin", people=1)).json()
    assert r2["incident_id"]


def test_citizen_road_block_needs_two_reports_then_activates():
    a = client.post("/api/v1/events", json=ev("road_block", lat=18.53, lon=73.85, note="Bridge flooded")).json()
    assert "unverified" in a["handled_as"]
    b = client.post("/api/v1/events", json=ev("road_block", lat=18.5302, lon=73.8501)).json()
    assert b["handled_as"] == "hazard active"


def test_dispatch_creates_route_and_blocked_road_triggers_reroute():
    iid = client.post("/api/v1/events", json=ev("sos", lat=18.5110, lon=73.8690, type="trapped", people=3)).json()["incident_id"]
    inc = client.post(f"/api/incidents/{iid}/approve", json={"officer": "Rao"}).json()
    rid = inc["responder_id"]
    unit = [u for u in client.get("/api/v1/units").json() if u["id"] == rid][0]
    route1 = unit["assignment"]["route"]
    assert len(route1) > 2 and unit["assignment"]["route_version"] == 1
    mid = route1[len(route1) // 2]
    client.post("/api/v1/hazards", json={"lat": mid[0], "lon": mid[1], "radius_m": 80, "note": "Road washed away"})
    unit = [u for u in client.get("/api/v1/units").json() if u["id"] == rid][0]
    a = unit["assignment"]
    assert a["route_version"] == 2 and "Road blocked" in a["reroute_reason"]
    h = routing.Hazard(0, mid[0], mid[1], 80)
    assert not routing.route_hits(a["route"], h)


def test_responder_site_flow():
    iid = client.post("/api/v1/events", json=ev("sos", type="injured")).json()["incident_id"]
    inc = client.post(f"/api/incidents/{iid}/approve", json={"officer": "Rao"}).json()
    code = [u for u in client.get("/api/v1/units").json() if u["id"] == inc["responder_id"]][0]["code"]
    h = login(code)
    task = client.get("/api/v1/units/me/task", headers=h).json()["task"]
    assert task["incident_id"] == iid and task["route"]
    assert client.post("/api/v1/units/me/location", json={"lat": LAT + 0.01, "lon": LON}, headers=h).status_code == 200
    assert client.post("/api/v1/units/me/status", json={"status": "en_route"}, headers=h).json()["status"] == "en_route"
    hz = client.post("/api/v1/units/me/hazard", json={"lat": LAT + 0.005, "lon": LON, "note": "Tree down"}, headers=h).json()
    assert hz["status"] == "active"
    for s in ("on_site", "resolved"):
        client.post("/api/v1/units/me/status", json={"status": s}, headers=h)
    assert client.get("/api/v1/units/me/task", headers=h).json()["task"] is None
    assert client.get("/api/v1/units/me/task").status_code == 401


def test_area_alert_goes_to_outbox_and_log_stays_valid():
    client.post("/api/v1/alerts", json={"officer": "Rao", "lat": LAT, "lon": LON, "radius_m": 800, "text": "Move to Shelter B"})
    assert any(i["kind"] == "alert" for i in client.get("/api/v1/outbox").json()["items"])
    assert client.get("/api/log/verify").json()["ok"] is True
