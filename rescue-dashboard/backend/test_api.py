import os
import sqlite3
import tempfile

os.environ["RESCUE_DB"] = os.path.join(tempfile.mkdtemp(), "test.db")

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402

client = TestClient(main.app)


def setup_function():
    client.post("/api/demo/reset")


def sos(ext, type_="trapped", lat=18.5204, lon=73.8567, **kw):
    body = {"external_id": ext, "source": "mesh", "type": type_, "lat": lat, "lon": lon,
            "message": "Water rising, 3 people on roof", "people": 3, **kw}
    return client.post("/api/reports", json=body).json()


def test_new_report_creates_incident_with_suggestion():
    r = sos("a1")
    assert r["incident_id"] and not r["merged"]
    inc = client.get(f"/api/incidents/{r['incident_id']}").json()
    assert inc["status"] == "suggested"
    assert "nearest available" in inc["suggestion_reason"]
    assert inc["priority"] > 0 and inc["priority_reason"]


def test_same_external_id_is_ignored():
    sos("dup")
    assert sos("dup")["duplicate"] is True
    assert len(client.get("/api/incidents").json()) == 1


def test_nearby_reports_merge_far_ones_do_not():
    a = sos("m1")
    b = sos("m2", lat=18.5210)               # ~70 m away -> merge
    c = sos("m3", lat=18.5400)               # ~2 km away -> new
    d = sos("m4", type_="fire")              # same place, other family -> new
    assert b["merged"] and b["incident_id"] == a["incident_id"]
    assert not c["merged"] and not d["merged"]
    inc = client.get(f"/api/incidents/{a['incident_id']}").json()
    assert inc["report_count"] == 2


def test_approve_then_status_flow_frees_responder():
    iid = sos("f1", type_="injured")["incident_id"]
    inc = client.post(f"/api/incidents/{iid}/approve", json={"officer": "Officer Rao"}).json()
    assert inc["status"] == "dispatched"
    rid = inc["responder_id"]
    busy = [x for x in client.get("/api/responders").json() if x["id"] == rid][0]
    assert busy["status"] == "busy"
    for s in ("en_route", "on_site", "resolved"):
        assert client.post(f"/api/incidents/{iid}/status", json={"status": s, "actor": "crew"}).status_code == 200
    free = [x for x in client.get("/api/responders").json() if x["id"] == rid][0]
    assert free["status"] == "available"


def test_status_change_needs_dispatch_first():
    iid = sos("s1")["incident_id"]
    assert client.post(f"/api/incidents/{iid}/status", json={"status": "on_site", "actor": "x"}).status_code == 409


def test_log_detects_tampering():
    sos("t1")
    assert client.get("/api/log/verify").json()["ok"] is True
    con = sqlite3.connect(main.DB_PATH)
    con.execute("UPDATE log SET actor='someone-else' WHERE seq=2")
    con.commit()
    v = client.get("/api/log/verify").json()
    assert v["ok"] is False and 2 in v["broken_at"]


def test_batch_upload_and_stats():
    items = [{"external_id": f"b{i}", "source": "mesh", "type": "flood", "lat": 18.52, "lon": 73.85 + i * 0.0003,
              "people": 2} for i in range(4)]
    out = client.post("/api/reports/batch", json=items).json()
    assert out["new"] == 4
    st = client.get("/api/stats").json()
    assert st["reports"] == 4 and st["incidents"] == 1 and st["merged_reports"] == 3
