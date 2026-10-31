"""Replays a scripted flood scenario into the control room, for demos and testing.

Usage:
  python simulate.py                      # normal speed (~1 min)
  python simulate.py --fast               # no pauses
  python simulate.py --reset              # wipe the demo data first
  python simulate.py --photo fall.jpg     # attach a snapshot to the camera alert
  python simulate.py --base http://192.168.1.20:8000

Only the Python standard library is used, so it runs anywhere.
"""
from __future__ import annotations

import argparse
import base64
import json
import time
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone

# Dehradun spots (from backend/dehradun_places.json). Labels kept so the script reads the same.
SPOTS = {
    "underpass": (30.2985, 78.0565),   # Rispana bridge
    "riverside": (30.3573, 78.0167),   # Tapkeshwar, Tamsa river
    "school": (30.3139, 78.0336),      # near the railway station
    "market": (30.3244, 78.0417),      # Clock Tower area
    "colony": (30.3636, 78.0706),      # IT Park, Sahastradhara Road
}


def ts(minutes_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat(timespec="seconds")


def report(source, type_, spot, msg="", people=1, minutes_ago=0.0, jitter=(0, 0), **extra):
    lat, lon = SPOTS[spot]
    return {"external_id": uuid.uuid4().hex, "source": source, "type": type_,
            "lat": lat + jitter[0], "lon": lon + jitter[1], "message": msg, "people": people,
            "reported_at": ts(minutes_ago), **extra}


def post(base: str, path: str, body) -> dict:
    req = urllib.request.Request(base + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as res:
        return json.loads(res.read())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--fast", action="store_true")
    ap.add_argument("--reset", action="store_true")
    ap.add_argument("--photo", help="JPEG/PNG to attach to the camera alert")
    a = ap.parse_args()
    pause = (lambda s: None) if a.fast else time.sleep

    if a.reset:
        post(a.base, "/api/demo/reset", {})
        print("Demo data reset.")

    photo = None
    if a.photo:
        with open(a.photo, "rb") as f:
            photo = base64.b64encode(f.read()).decode()

    steps = [
        ("Camera AI spots a person down at the flooded underpass", "/api/reports",
         report("camera", "fall", "underpass", "Person lying still in water, not moving for 6 s", 1, photo_b64=photo,
                via="camera: CCTV-14 underpass")),
        ("Citizen SOS arrives over the mesh (3 hops)", "/api/reports",
         report("mesh", "trapped", "riverside", "Paani badh raha hai, chhat par 4 log hain", 4, minutes_ago=6, lang="hi",
                via="mesh: 3 hops, uploaded by responder phone")),
        ("Two more SOS about the same roof (will merge)", "/api/reports/batch", [
            report("mesh", "trapped", "riverside", "Family of 4 stuck on roof, water at first floor", 4, minutes_ago=5,
                   jitter=(0.0004, 0.0002), via="mesh: 2 hops"),
            report("mesh", "trapped", "riverside", "Please help, old man cannot walk", 5, minutes_ago=4,
                   jitter=(-0.0003, 0.0003), lang="en", via="mesh: 4 hops"),
        ]),
        ("Fire reported near the market", "/api/reports",
         report("mesh", "fire", "market", "Short circuit fire in shop, smoke everywhere", 2, minutes_ago=2, lang="en",
                via="mesh: 1 hop")),
        ("Network returns: a phone uploads the SOS it was holding", "/api/reports/batch", [
            report("mesh", "injured", "school", "Teacher injured, leg bleeding, 20 kids in school", 21, minutes_ago=18,
                   lang="mr", via="mesh: held 18 min, uploaded when phone got signal"),
            report("mesh", "flood", "colony", "Ground floor flooded, need boat", 6, minutes_ago=12,
                   via="mesh: held 12 min"),
            report("mesh", "flood", "colony", "Same colony, water rising fast", 3, minutes_ago=10,
                   jitter=(0.0002, -0.0002), via="mesh: held 10 min"),
        ]),
        ("Sensor node detects tapping under debris (simulated LoRa)", "/api/reports",
         report("sensor", "sensor", "colony", "Rhythmic tapping + CO2 rise under collapsed wall", 1,
                jitter=(0.0006, 0.0004), via="sensor: node-07 (simulated)")),
        ("Crowd building at the school gate (camera)", "/api/reports",
         report("camera", "crowd", "school", "Crowd density 4.2 people per m2 at gate", 60,
                jitter=(0.0003, 0.0002), via="camera: CCTV-03 school gate")),
    ]

    for i, (title, path, body) in enumerate(steps, 1):
        out = post(a.base, path, body)
        print(f"[{i}/{len(steps)}] {title} -> {out if path.endswith('reports') else {k: out[k] for k in ('received', 'new')}}")
        pause(7)

    print("Done. Open the dashboard and approve dispatches.")


if __name__ == "__main__":
    main()
