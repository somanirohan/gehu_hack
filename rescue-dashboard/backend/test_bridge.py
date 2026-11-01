"""The app's existing sync bundle (bitchat.civ.sync/v1) reaches the dashboard."""
import os
import tempfile
import time

os.environ.setdefault("RESCUE_DB", os.path.join(tempfile.mkdtemp(), "bridge.db"))
os.environ["USE_OSRM"] = "0"

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
import routing  # noqa: E402

client = TestClient(main.app)
DDN = (30.3165, 78.0322)  # Dehradun


def setup_function():
    routing.set_network(routing.RoadNetwork.grid(*DDN, rows=16, cols=16, spacing_m=220))
    client.post("/api/demo/reset")


def bundle(incidents=(), shelters=()):
    now = int(time.time() * 1000)
    return {"bundle_schema": "bitchat.civ.sync/v1", "produced_at": now,
            "incidents": list(incidents), "shelters": list(shelters)}


def msg(i, content, role="CIVILIAN", lat=DDN[0], lon=DDN[1], minutes_ago=5):
    return {"id": f"m{i}", "timestamp": int((time.time() - minutes_ago * 60) * 1000), "sender": f"user{i}",
            "role": role, "lat": lat, "lon": lon, "content": f"{content} geo:{lat},{lon}"}


def test_sos_message_becomes_incident_and_repeats_are_ignored():
    b = bundle([msg(1, "Bachao! 4 log chhat par fase hain, paani badh raha")])
    r = client.post("/api/v1/bitchat/civ-sync", json=b).json()
    assert r["new"] == 1
    inc = client.get("/api/incidents").json()[0]
    assert inc["type"] == "trapped" and inc["people"] == 4
    assert "geo:" not in inc["summary"]
    # the app re-sends the same messages on every flush
    r2 = client.post("/api/v1/bitchat/civ-sync", json=b).json()
    assert r2["new"] == 0 and r2["duplicates"] == 1
    assert len(client.get("/api/incidents").json()) == 1


def test_feed_shows_rule_label_and_offline_wait():
    client.post("/api/v1/bitchat/civ-sync", json=bundle([msg(2, "aag lagi hai market me", minutes_ago=12)]))
    e = client.get("/api/v1/feed").json()[0]
    assert e["payload"]["category_source"] == "rule suggestion"
    assert e["via"]["path"] == "mesh-sync" and e["via"]["held_seconds"] >= 700


def test_plain_message_is_on_the_incident_list_at_lowest_priority():
    """Every located report must be visible on the incident list (and to the AI planner).
    A message that is not an emergency becomes a low-priority 'other' incident the officer can close."""
    client.post("/api/v1/bitchat/civ-sync", json=bundle([msg(3, "Reached the shelter, all safe")]))
    inc = client.get("/api/incidents").json()
    assert len(inc) == 1 and inc[0]["type"] == "other"
    e = client.get("/api/v1/feed").json()[0]
    assert e["kind"] == "message" and e["incident_id"] == inc[0]["id"]


def test_official_road_block_activates_citizen_one_waits():
    citizen = client.post("/api/v1/bitchat/civ-sync", json=bundle([msg(4, "Sahastradhara road band, landslide", lat=30.3870, lon=78.1310)])).json()
    hz = client.get("/api/v1/hazards").json()
    assert hz[0]["status"] == "unverified" and citizen["new"] == 1
    client.post("/api/v1/bitchat/civ-sync", json=bundle([msg(5, "Bridge broken, cannot pass", role="GOV", lat=30.30, lon=78.05)]))
    statuses = sorted(h["status"] for h in client.get("/api/v1/hazards").json())
    assert statuses == ["active", "unverified"]


def test_shelters_are_stored_and_newer_version_wins():
    s = {"id": "sh1", "name": "Govt School Raipur", "lat": 30.31, "lon": 78.09, "capacity": 120, "status": "OPEN",
         "role": "GOV", "version": 2, "originPeerID": "abc", "verified": True}
    client.post("/api/v1/bitchat/civ-sync", json=bundle(shelters=[s]))
    client.post("/api/v1/bitchat/civ-sync", json=bundle(shelters=[dict(s, version=1, status="FULL")]))
    assert client.get("/api/v1/shelters").json()[0]["status"] == "OPEN"
    client.post("/api/v1/bitchat/civ-sync", json=bundle(shelters=[dict(s, version=3, status="FULL")]))
    assert client.get("/api/v1/shelters").json()[0]["status"] == "FULL"


def test_unknown_extra_fields_do_not_break_sync():
    b = bundle([dict(msg(6, "injured 2 people"), photo_count=1, future_field={"x": 1})])
    b["app_version"] = "1.9"
    assert client.post("/api/v1/bitchat/civ-sync", json=b).status_code == 200


def test_drone_gets_straight_route_and_is_not_rerouted():
    iid = client.post("/api/v1/bitchat/civ-sync", json=bundle([msg(7, "mera beta lapata hai", lat=30.33, lon=78.05)])).json()
    inc = client.get("/api/incidents").json()[0]
    drone = [u for u in client.get("/api/v1/units").json() if u["kind"] == "drone"][0]
    out = client.post(f"/api/incidents/{inc['id']}/approve", json={"officer": "Rao", "responder_id": drone["id"]}).json()
    a = [u for u in client.get("/api/v1/units").json() if u["id"] == drone["id"]][0]["assignment"]
    assert len(a["route"]) == 2 and "aerial" in a["route_source"]
    mid = [(a["route"][0][0] + a["route"][1][0]) / 2, (a["route"][0][1] + a["route"][1][1]) / 2]
    client.post("/api/v1/hazards", json={"lat": mid[0], "lon": mid[1], "radius_m": 200, "note": "test"})
    a2 = [u for u in client.get("/api/v1/units").json() if u["id"] == drone["id"]][0]["assignment"]
    assert a2["route_version"] == 1
    assert out["status"] == "dispatched" and iid["new"] == 1


def test_drill_bundles_are_labelled():
    b = bundle([msg(8, "Bachao, gaadi palat gayi, 2 log ghayal")])
    b["drill"] = True
    client.post("/api/v1/bitchat/civ-sync", json=b)
    e = client.get("/api/v1/feed").json()[0]
    assert e["via"]["path"] == "drill" and e["payload"]["drill"] is True
    assert client.get("/api/incidents").json()[0]["drill"] is True


def test_app_sos_button_format_is_always_sos():
    # ChatViewModel.sendSOS sends "🆘 <text> geo:lat,lon"
    client.post("/api/v1/bitchat/civ-sync", json=bundle([msg(9, "🆘 mera ghar")]))
    assert client.get("/api/v1/feed").json()[0]["kind"] == "sos"


def test_app_can_send_category_and_gets_accepted_ids():
    m = dict(msg(10, "help please"), category="medical", people=3)
    r = client.post("/api/v1/bitchat/civ-sync", json=bundle([m])).json()
    assert r["accepted_ids"] == ["m10"]
    inc = client.get("/api/incidents").json()[0]
    assert inc["type"] == "medical" and inc["people"] == 3
    assert client.get("/api/v1/feed").json()[0]["payload"]["category_source"] == "chosen in app"


def test_road_block_emoji():
    client.post("/api/v1/bitchat/civ-sync", json=bundle([msg(11, "\u26d4 Raipur road")]))
    assert client.get("/api/v1/feed").json()[0]["kind"] == "road_block"


def test_photo_named_in_sync_is_attached_when_it_arrives():
    import io
    from PIL import Image
    m = dict(msg(12, "🆘 ghar gir gaya, 2 log andar"), media_ids=["ph-12"])
    client.post("/api/v1/bitchat/civ-sync", json=bundle([m]))
    assert client.get("/api/v1/feed").json()[0]["media"][0]["pending"] is True
    buf = io.BytesIO(); Image.new("RGB", (40, 30), "red").save(buf, "JPEG")
    client.post("/api/v1/media", data={"media_id": "ph-12"}, files={"file": ("p.jpg", buf.getvalue(), "image/jpeg")})
    assert client.get("/api/incidents").json()[0]["photo"]
