"""Dehradun practice drill for the demo.

Sends reports in EXACTLY the format the Android app sends (bitchat.civ.sync/v1) to the
same endpoint, so the dashboard path is the real one. Every bundle carries "drill": true,
and the dashboard shows these with a DRILL badge, so they are never mistaken for real calls.

    python simulator/drill_dehradun.py                       # local server
    python simulator/drill_dehradun.py --url https://xyz.trycloudflare.com
    python simulator/drill_dehradun.py --fast                # 3 s between steps

Script:
  1. Five Hinglish SOS messages at real Dehradun flood / accident spots, some "held offline"
     for a few minutes (as if they hopped over the mesh first).
  2. The same message sent again (the app re-sends on every flush): the dashboard must not
     duplicate it.
  3. Waits for an officer to approve a dispatch on the dashboard.
  4. A GOV (official) "road blocked" message on that unit's route: the dashboard should
     re-route the unit and the responder site should show the new route.
Only the Python standard library is used.
"""
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PLACES = json.load(open(os.path.join(HERE, "..", "backend", "dehradun_places.json"), encoding="utf-8"))
P = {p["id"]: p for p in PLACES["places"]}

# (place id, sender, role, text, minutes the message waited offline before reaching internet)
SCRIPT = [
    ("tapkeshwar", "rahul_m", "CIVILIAN", "Bachao! Tamsa nadi ka paani mandir tak aa gaya, 6 log fase hain", 7),
    ("rispana-bridge", "priya_k", "CIVILIAN", "Rispana pul ke paas accident, bike aur truck, 2 log ghayal", 2),
    ("sahastradhara", "local_guide", "CIVILIAN", "Sahastradhara mein badal fata, ghar ke andar 4 log trapped", 12),
    ("isbt", "conductor_22", "CIVILIAN", "ISBT ke paas ek aadmi behosh pada hai, saans nahi le raha", 0),
    ("it-park", "it_worker", "CIVILIAN", "IT Park road par paani bhar gaya, gaadi mein 3 log phase", 4),
]


def post(url: str, body: dict) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read() or b"{}")


def get(url: str):
    with urllib.request.urlopen(url, timeout=20) as r:
        return json.loads(r.read())


def message(i: int, place: str, sender: str, role: str, text: str, waited_min: float, jitter: float = 0.0) -> dict:
    p = P[place]
    lat, lon = round(p["lat"] + jitter, 6), round(p["lon"] - jitter, 6)
    return {"id": f"drill-{int(time.time())}-{i}", "timestamp": int((time.time() - waited_min * 60) * 1000),
            "sender": sender, "role": role, "lat": lat, "lon": lon, "content": f"{text} geo:{lat},{lon}"}


def bundle(items: list[dict]) -> dict:
    return {"bundle_schema": "bitchat.civ.sync/v1", "produced_at": int(time.time() * 1000),
            "incidents": items, "shelters": [], "drill": True}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8001")
    ap.add_argument("--fast", action="store_true")
    ap.add_argument("--wait", type=int, default=3600, help="seconds to wait for a dispatch (default 1 hour)")
    ap.add_argument("--citizen-only", action="store_true",
                    help="skip the 5 SOS; only send the citizen reports onto a unit that is ALREADY driving")
    ap.add_argument("--citizen", action="store_true",
                    help="Route Watch demo: a CITIZEN reports a fallen tree and an injured person on the unit's route")
    a = ap.parse_args()
    base = a.url.rstrip("/")
    sync = base + "/api/v1/bitchat/civ-sync"
    gap = 3 if a.fast else 8

    print(f"DRILL against {base}. Everything sent is labelled drill.\n")
    if a.citizen_only:
        a.citizen = True
    sent = []
    for i, (place, sender, role, text, waited) in enumerate([] if a.citizen_only else SCRIPT, 1):
        m = message(i, place, sender, role, text, waited)
        sent.append(m)
        r = post(sync, bundle([m]))
        print(f"[{i}] {P[place]['name']}: \"{text[:50]}...\" -> new={r['new']}")
        time.sleep(gap)

    if a.citizen_only:
        sent = []
    # The app re-sends its recent messages on every flush; nothing must duplicate.
    r = post(sync, bundle(sent[:2])) if sent else {"new": 0, "duplicates": 0}
    print(f"\nRe-sent 2 old messages (as the app does) -> new={r['new']}, duplicates={r['duplicates']}")

    if not a.citizen_only:
        # A second citizen near the first SOS: should merge into the same incident.
        m = message(99, "tapkeshwar", "neighbour_t", "CIVILIAN", "Tapkeshwar mandir mein log fase, jaldi aao", 1, jitter=0.0004)
        r = post(sync, bundle([m]))
        print(f"Second report near Tapkeshwar -> new={r['new']} (dashboard should merge it, report count 2)")

    print("\nNow approve a dispatch on the dashboard. Waiting...")
    deadline = time.time() + a.wait
    target = None
    while time.time() < deadline and not target:
        for u in get(base + "/api/v1/units"):
            asg = u.get("assignment")
            if asg and asg.get("route") and len(asg["route"]) > 2 and u["kind"] != "drone":
                target = (u, asg)
                break
        if not target:
            time.sleep(3)
    if not target:
        print("No road dispatch seen; drill ends here.")
        return
    u, asg = target
    route = asg["route"]
    lat, lon = route[len(route) // 2]
    print(f"{u['name']} is on its way ({asg.get('eta_min')} min, route v{asg.get('route_version')}).")
    time.sleep(gap)
    if a.citizen:
        # Route Watch Agent demo: ordinary people report things on the road the unit is driving.
        t1 = route[len(route) // 3]
        t2 = route[(2 * len(route)) // 3]
        tree = {"id": f"drill-{int(time.time())}-tree", "timestamp": int(time.time() * 1000), "sender": "local_shopkeeper",
                "role": "CIVILIAN", "lat": t1[0], "lon": t1[1],
                "content": f"Yahan road pe bada ped gir gaya, gaadi nahi ja sakti geo:{t1[0]},{t1[1]}"}
        post(sync, bundle([tree]))
        print(f"Citizen: fallen tree on the route at {t1[0]:.5f},{t1[1]:.5f} (Route Watch should re-route or ask).")
        time.sleep(gap)
        hurt = {"id": f"drill-{int(time.time())}-hurt", "timestamp": int(time.time() * 1000), "sender": "passerby_22",
                "role": "CIVILIAN", "lat": t2[0], "lon": t2[1],
                "content": f"Bachao, scooty accident, ek aadmi ghayal sadak ke kinare geo:{t2[0]},{t2[1]}"}
        post(sync, bundle([hurt]))
        print("Citizen: injured person beside the route (Route Watch should suggest stop-to-help if the unit can help).")
        print("Look at the Route Watch box on the dashboard map and at the responder phone.")
        return
    m = {"id": f"drill-{int(time.time())}-block", "timestamp": int(time.time() * 1000), "sender": "ddn_police_ctrl",
         "role": "GOV", "lat": lat, "lon": lon,
         "content": f"Road band hai, landslide se malba gira, gaadi nahi ja sakti geo:{lat},{lon}"}
    post(sync, bundle([m]))
    print(f"Official road block sent on the route at {lat:.5f},{lon:.5f}.")
    time.sleep(3)
    for x in get(base + "/api/v1/units"):
        if x["id"] == u["id"] and x.get("assignment"):
            b = x["assignment"]
            print(f"{u['name']} now on route v{b.get('route_version')} ({b.get('eta_min')} min). Reason: {b.get('reroute_reason')}")
    print("\nDrill done. Reset with the dashboard's 'Reset demo' button (or POST /api/demo/reset).")


if __name__ == "__main__":
    main()