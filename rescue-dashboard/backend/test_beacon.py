"""Unit tests for SOS Beacon endpoints: live capacity updates, creator authorization, and map feeds."""
import os
import tempfile
import pytest

os.environ.setdefault("RESCUE_DB", os.path.join(tempfile.mkdtemp(), "beacon_test.db"))
os.environ["USE_OSRM"] = "0"

from fastapi.testclient import TestClient
import main
import bridge

client = TestClient(main.app)
DDN = (30.3165, 78.0322)


def setup_function():
    client.post("/api/demo/reset")


def test_create_beacon_and_get_beacons():
    res = client.post("/api/v1/beacons", json={
        "name": "Clock Tower Evacuation Beacon",
        "lat": DDN[0],
        "lon": DDN[1],
        "capacity": 75,
        "status": "OPEN",
        "note": "Water and blankets available",
        "origin": "test-device-1"
    }).json()

    assert res["ok"] is True
    assert "creator_token" in res
    beacon = res["beacon"]
    assert beacon["name"] == "Clock Tower Evacuation Beacon"
    assert beacon["capacity"] == 75
    assert beacon["status"] == "OPEN"
    token = res["creator_token"]

    # Check list of beacons
    beacons = client.get("/api/v1/beacons").json()
    assert len(beacons) == 1
    assert beacons[0]["id"] == beacon["id"]
    assert beacons[0]["capacity"] == 75

    # Check shelter list includes beacon with is_beacon=True
    shelters = client.get("/api/v1/shelters").json()
    b = next(s for s in shelters if s["id"] == beacon["id"])
    assert b["is_beacon"] is True


def test_update_beacon_capacity_with_valid_token():
    res = client.post("/api/v1/beacons", json={
        "name": "Parade Ground Camp",
        "lat": DDN[0],
        "lon": DDN[1],
        "capacity": 50,
        "status": "OPEN"
    }).json()
    beacon_id = res["beacon"]["id"]
    token = res["creator_token"]

    # Update capacity to 80
    patch_res = client.patch(f"/api/v1/beacons/{beacon_id}", json={
        "creator_token": token,
        "capacity": 80,
        "status": "OPEN",
        "note": "Capacity expanded with 30 more cots"
    }).json()

    assert patch_res["ok"] is True
    assert patch_res["beacon"]["capacity"] == 80
    assert patch_res["beacon"]["note"] == "Capacity expanded with 30 more cots"

    # Verify updated beacon in database
    b = client.get(f"/api/v1/beacons/{beacon_id}").json()
    assert b["capacity"] == 80


def test_update_beacon_capacity_rejects_unauthorized():
    res = client.post("/api/v1/beacons", json={
        "name": "Secured Beacon",
        "lat": DDN[0],
        "lon": DDN[1],
        "capacity": 30,
        "status": "OPEN"
    }).json()
    beacon_id = res["beacon"]["id"]

    # Wrong token
    r = client.patch(f"/api/v1/beacons/{beacon_id}", json={
        "creator_token": "wrong-token-1234",
        "capacity": 999
    })
    assert r.status_code == 403


def test_civ_sync_creates_beacon_and_allows_origin_update():
    # Simulate bitchat mesh syncing a civilian shelter (SOS beacon)
    bundle = {
        "bundle_schema": "bitchat.civ.sync/v1",
        "produced_at": 1730000000000,
        "incidents": [],
        "shelters": [{
            "id": "mesh-beacon-1",
            "name": "Mesh SOS Node",
            "lat": DDN[0],
            "lon": DDN[1],
            "capacity": 40,
            "status": "OPEN",
            "role": "CIVILIAN",
            "version": 1730000000000,
            "originPeerID": "peer-abc-999"
        }]
    }
    sync_res = client.post("/api/v1/bitchat/civ-sync", json=bundle).json()
    assert sync_res["shelters_changed"] == 1

    # Check it appears as a beacon
    beacons = client.get("/api/v1/beacons").json()
    b = next(x for x in beacons if x["id"] == "mesh-beacon-1")
    assert b["capacity"] == 40
    assert b["role"] == "CIVILIAN"

    # Update capacity using the origin peer ID
    patch_res = client.patch(f"/api/v1/shelters/mesh-beacon-1", json={
        "origin": "peer-abc-999",
        "capacity": 55,
        "status": "FULL"
    }).json()
    assert patch_res["ok"] is True
    assert patch_res["beacon"]["capacity"] == 55
    assert patch_res["beacon"]["status"] == "FULL"
