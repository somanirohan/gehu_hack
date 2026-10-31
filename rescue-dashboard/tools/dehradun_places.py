"""Refine Dehradun place coordinates from OpenStreetMap (Nominatim).

Some entries in backend/dehradun_places.json are marked coord_source "approximate"
(they could not be checked when the file was written). Run this on a laptop with
internet; it looks each one up by its "query" and writes the result back.

    python tools/dehradun_places.py            # only the approximate ones
    python tools/dehradun_places.py --all      # re-check everything
    python tools/dehradun_places.py --dry-run  # show, don't write

Nominatim's rules: max 1 request per second and a real User-Agent; this script obeys both.
Results outside the Dehradun district box are rejected, so a wrong match is never saved.
Only the Python standard library is used.
"""
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.parse
import urllib.request

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend", "dehradun_places.json")
BOX = (29.95, 77.55, 30.65, 78.35)  # lat_min, lon_min, lat_max, lon_max (Dehradun district, generous)
UA = "rescue-dashboard-hackathon/1.0 (Dehradun disaster demo)"


def lookup(query: str):
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
        {"q": query + ", Uttarakhand, India", "format": "json", "limit": 3})
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        for hit in json.loads(r.read()):
            lat, lon = float(hit["lat"]), float(hit["lon"])
            if BOX[0] <= lat <= BOX[2] and BOX[1] <= lon <= BOX[3]:
                return lat, lon, hit.get("display_name", "")
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    data = json.load(open(PATH, encoding="utf-8"))
    changed = 0
    for p in data["places"]:
        if not a.all and p.get("coord_source") != "approximate":
            continue
        try:
            hit = lookup(p.get("query") or p["name"])
        except Exception as exc:
            print(f"  {p['id']}: lookup failed ({exc})")
            hit = None
        time.sleep(1.1)
        if not hit:
            print(f"  {p['id']}: no match inside Dehradun, kept {p['lat']},{p['lon']}")
            continue
        lat, lon, name = hit
        moved = ((lat - p["lat"]) ** 2 + (lon - p["lon"]) ** 2) ** 0.5 * 111
        print(f"  {p['id']}: {p['lat']},{p['lon']} -> {lat:.6f},{lon:.6f} (moved {moved:.2f} km) [{name[:60]}]")
        p["lat"], p["lon"] = round(lat, 6), round(lon, 6)
        p["coord_source"] = "OpenStreetMap Nominatim"
        changed += 1
    if changed and not a.dry_run:
        json.dump(data, open(PATH, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
        print(f"Updated {changed} places in {PATH}. Restart the backend; press Reset to re-stage units.")
    else:
        print(f"{changed} places would change." if a.dry_run else "Nothing changed.")


if __name__ == "__main__":
    main()
