"""Field simulator for API v1: what the mesh app will really send.

Replays a flood: SOS that waited offline and hopped through phones, photos
(thumbnail first, full photo later), follow-up messages, citizen road-block
reports, and a brand-new event kind the app team might add tomorrow.

    python simulate_field.py --base http://127.0.0.1:8001 --reset
    python simulate_field.py --fast            # no pauses
Standard library only, plus Pillow if available (for demo photos).
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import time
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone

SPOT = {  # Dehradun (backend/dehradun_places.json)
    "riverside": (30.3573, 78.0167), "underpass": (30.2985, 78.0565), "school": (30.3139, 78.0336),
    "colony": (30.3636, 78.0706), "bridge": (30.3244, 78.0417),
}


def ts(min_ago=0):
    return (datetime.now(timezone.utc) - timedelta(minutes=min_ago)).isoformat(timespec="seconds")


def photo(label, color):
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None, None
    big = Image.new("RGB", (960, 640), color)
    d = ImageDraw.Draw(big)
    d.rectangle((0, 420, 960, 640), fill=(60, 90, 120))
    d.text((24, 24), f"{label} (demo photo)", fill=(255, 255, 255))
    small = big.copy()
    small.thumbnail((240, 160))
    out = []
    for im, q in ((small, 60), (big, 80)):
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=q)
        out.append(buf.getvalue())
    return out[0], out[1]


def event(kind, spot, payload, min_ago=0, hops=0, held=0, device="phone-A", media=None, d=(0, 0)):
    lat, lon = SPOT[spot]
    return {"event_id": uuid.uuid4().hex, "kind": kind, "created_at": ts(min_ago), "device_id": device,
            "lat": lat + d[0], "lon": lon + d[1], "acc": 12, "payload": payload, "media": media or [],
            "via": {"path": "mesh", "hops": hops, "uploader": "phone-C", "held_seconds": held}}


def post_json(base, path, body):
    req = urllib.request.Request(base + path, json.dumps(body).encode(), {"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def post_file(base, media_id, raw):
    boundary = uuid.uuid4().hex
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"media_id\"\r\n\r\n{media_id}\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"p.jpg\"\r\nContent-Type: image/jpeg\r\n\r\n").encode() + raw + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(base + "/api/v1/media", body, {"Content-Type": f"multipart/form-data; boundary={boundary}"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8001")
    ap.add_argument("--reset", action="store_true")
    ap.add_argument("--fast", action="store_true")
    a = ap.parse_args()
    wait = (lambda s: None) if a.fast else time.sleep
    if a.reset:
        post_json(a.base, "/api/demo/reset", {})
        print("reset demo data")

    thumb, full = photo("Roof, riverside colony", (40, 70, 90))
    sos = event("sos", "riverside", {"type": "trapped", "people": 4, "message": "Paani badh raha hai, chhat par 4 log", "lang": "hi"},
                min_ago=9, hops=3, held=420, media=[{"media_id": "m-roof", "b64": base64.b64encode(thumb).decode()}] if thumb else [])
    steps = [
        ("SOS with thumbnail photo, 3 hops, waited 7 min offline", [sos]),
        ("Follow-up message about the same SOS", [event("message", "riverside", {"text": "Old man cannot walk, needs stretcher", "ref_event_id": sos["event_id"]}, min_ago=6, hops=2, held=200, device="phone-A")]),
        ("Phone reaches signal: uploads 3 SOS it was carrying", [
            event("sos", "school", {"type": "injured", "people": 21, "message": "Teacher injured, 20 children inside", "lang": "mr"}, min_ago=16, hops=4, held=900, device="phone-K"),
            event("sos", "underpass", {"type": "trapped", "people": 2, "message": "Car stuck in water under bridge"}, min_ago=12, hops=1, held=600, device="phone-M"),
            event("sos", "underpass", {"type": "trapped", "people": 2, "message": "Same car, water at window level"}, min_ago=10, hops=2, held=500, device="phone-N", d=(0.0003, 0.0002)),
        ]),
        ("Citizen reports bridge flooded (1st report: unverified)", [event("road_block", "bridge", {"note": "Bridge flooded, cars cannot pass", "radius_m": 90}, min_ago=3, hops=2, held=60, device="phone-P")]),
        ("Second citizen confirms the bridge (now active, routes avoid it)", [event("road_block", "bridge", {"note": "Bridge under water"}, min_ago=2, hops=1, device="phone-Q", d=(0.0002, -0.0001))]),
        ("New feature from the app team: medical need (creates incident by config)", [event("medical_need", "colony", {"need": "Insulin for diabetic patient", "people": 1}, min_ago=1, hops=2, device="phone-R")]),
        ("New feature nobody configured yet: safe check-in + battery level", [
            event("safe_checkin", "colony", {"name": "Patil family", "people": 5}, hops=1, device="phone-S"),
            event("battery_low", "school", {"level": 9, "device": "phone-K"}, device="phone-K"),
        ]),
    ]
    for i, (title, evs) in enumerate(steps, 1):
        r = post_json(a.base, "/api/v1/events", evs if len(evs) > 1 else evs[0])
        res = r.get("results", [r])
        print(f"[{i}/{len(steps)}] {title}: " + "; ".join(x.get("handled_as", "duplicate") for x in res))
        wait(6)
    if full:
        post_file(a.base, "m-roof", full)
        print("[+] Full-size roof photo arrived later over a better connection")
    print("Done. On the dashboard: approve a dispatch, open /responder on a phone, then block a road on its route.")


if __name__ == "__main__":
    main()
