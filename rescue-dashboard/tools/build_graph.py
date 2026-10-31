"""Download the real road network for your area once, so routing works offline
and can avoid blocked roads.

    pip install osmnx==2.0.1
    python build_graph.py --lat 18.5204 --lon 73.8567 --km 6 --out ../backend/roads.graphml

Then start the backend with:  ROAD_GRAPH=roads.graphml  (PowerShell: $env:ROAD_GRAPH="roads.graphml")
Needs internet only while downloading. A 6 km radius of a city is usually a few MB.
"""
import argparse

import osmnx as ox

ap = argparse.ArgumentParser()
ap.add_argument("--lat", type=float, required=True)
ap.add_argument("--lon", type=float, required=True)
ap.add_argument("--km", type=float, default=6, help="radius around the point")
ap.add_argument("--out", default="roads.graphml")
a = ap.parse_args()

print(f"Downloading drivable roads within {a.km} km of {a.lat}, {a.lon} ...")
g = ox.graph_from_point((a.lat, a.lon), dist=a.km * 1000, network_type="drive", simplify=True)
ox.save_graphml(g, a.out)
print(f"Saved {a.out}: {len(g.nodes)} junctions, {len(g.edges)} road segments")
