"""Field-base sync: run the backend on a laptop at a relief camp or command post,
let phones and responder tablets connect to it over a local Wi-Fi hotspot, and
whenever ANY internet link appears (a dongle, a satellite terminal, a phone tether),
this script pushes everything to the cloud and pulls the cloud's replies back.

Every event has a unique id, so pushing twice is harmless: nothing is lost or doubled.

    python edge_sync.py --edge http://127.0.0.1:8001 --cloud https://your-cloud-address
"""
import argparse
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

STATE = Path(__file__).with_name("edge_sync_state.json")


def call(url, body=None, method="GET", key=None):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if key:
        headers["X-API-Key"] = key
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def once(edge, cloud, key, state):
    feed = call(f"{edge}/api/v1/feed?limit=500")
    new = [e for e in reversed(feed) if e["event_id"] not in state["pushed"]]
    for i in range(0, len(new), 50):
        chunk = new[i:i + 50]
        body = [{"event_id": e["event_id"], "kind": e["kind"], "created_at": e["created_at"], "device_id": e["device_id"],
                 "lat": e["lat"], "lon": e["lon"], "acc": e["acc"], "payload": e["payload"],
                 "via": {**(e["via"] or {}), "path": "edge-sync"},
                 "media": [{"media_id": m["media_id"]} for m in e["media"]]} for e in chunk]
        call(f"{cloud}/api/v1/events", body, "POST", key)
        state["pushed"] += [e["event_id"] for e in chunk]
    out = call(f"{cloud}/api/v1/outbox" + (f"?since={state['since']}" if state.get("since") else ""))
    if out["items"]:
        call(f"{edge}/api/v1/outbox/import", out["items"], "POST")
    state["since"] = out["server_time"]
    return len(new), len(out["items"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--edge", default="http://127.0.0.1:8001")
    ap.add_argument("--cloud", required=True)
    ap.add_argument("--key", default=None, help="device API key for the cloud")
    ap.add_argument("--every", type=int, default=10, help="seconds between attempts")
    a = ap.parse_args()
    state = json.loads(STATE.read_text()) if STATE.exists() else {"pushed": [], "since": None}
    while True:
        try:
            pushed, pulled = once(a.edge, a.cloud, a.key, state)
            STATE.write_text(json.dumps(state))
            print(f"synced: pushed {pushed}, pulled {pulled} replies")
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            print(f"no link to cloud yet ({e}); retrying in {a.every}s")
        time.sleep(a.every)


if __name__ == "__main__":
    main()
