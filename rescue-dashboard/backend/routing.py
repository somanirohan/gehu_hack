"""Road routing that avoids blocked roads.

Three levels, best first:
  1. Our own road graph (OpenStreetMap, built once with tools/build_graph.py).
     Works with NO internet and can avoid any reported hazard. This is the one
     that makes live re-routing possible.
  2. An OSRM server (public demo or self-hosted): real roads, but it cannot
     avoid our hazards, so it is used only when no graph is loaded.
  3. A straight line, clearly labelled, so the map never breaks.
"""
from __future__ import annotations

import json
import math
import os
import urllib.request
from dataclasses import dataclass

import networkx as nx
import numpy as np

# Default speeds (km/h) by OSM road type, reduced for disaster conditions.
SPEED_KMH = {
    "motorway": 50, "trunk": 45, "primary": 35, "secondary": 30, "tertiary": 25,
    "residential": 18, "unclassified": 18, "service": 12, "living_street": 10,
}
DEFAULT_SPEED = 20
HAZARD_BUFFER_M = 25  # treat roads this close to a hazard edge as blocked too


def haversine_m(lat1, lon1, lat2, lon2) -> float:
    r = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


@dataclass
class Hazard:
    id: int
    lat: float
    lon: float
    radius_m: float

    def covers(self, lat, lon, extra=HAZARD_BUFFER_M) -> bool:
        return haversine_m(self.lat, self.lon, lat, lon) <= self.radius_m + extra


def _speed(highway) -> float:
    if isinstance(highway, str) and highway.startswith("["):
        try:
            highway = json.loads(highway.replace("'", '"'))
        except ValueError:
            pass
    if isinstance(highway, list):
        highway = highway[0] if highway else ""
    return SPEED_KMH.get(str(highway).replace("_link", ""), DEFAULT_SPEED)


class RoadNetwork:
    def __init__(self, graph: nx.MultiDiGraph, name: str = "graph"):
        self.g = graph
        self.name = name
        self.node_ids = list(graph.nodes)
        self.lat = {n: float(graph.nodes[n]["y"]) for n in self.node_ids}
        self.lon = {n: float(graph.nodes[n]["x"]) for n in self.node_ids}
        # arrays for fast nearest / within-radius queries on city-sized graphs
        self._lat = np.array([self.lat[n] for n in self.node_ids])
        self._lon = np.array([self.lon[n] for n in self.node_ids])
        for u, v, k, d in graph.edges(keys=True, data=True):
            length = float(d.get("length") or haversine_m(self.lat[u], self.lon[u], self.lat[v], self.lon[v]))
            d["length"] = length
            d["seconds"] = length / (_speed(d.get("highway")) / 3.6)

    # ---------- loading ----------
    @classmethod
    def load(cls, path: str) -> "RoadNetwork":
        g = nx.read_graphml(path)
        if not g.is_multigraph():
            g = nx.MultiDiGraph(g)
        return cls(g, name=os.path.basename(path))

    @classmethod
    def grid(cls, lat0: float, lon0: float, rows: int = 12, cols: int = 12, spacing_m: float = 250) -> "RoadNetwork":
        """A synthetic street grid, for tests and for demos without a real map file."""
        g = nx.MultiDiGraph()
        dlat = spacing_m / 111_320
        dlon = spacing_m / (111_320 * math.cos(math.radians(lat0)))
        top_lat = lat0 + dlat * (rows - 1) / 2
        left_lon = lon0 - dlon * (cols - 1) / 2
        for r in range(rows):
            for c in range(cols):
                g.add_node(f"{r}-{c}", y=top_lat - r * dlat, x=left_lon + c * dlon)
        for r in range(rows):
            for c in range(cols):
                hw = "primary" if r % 4 == 0 or c % 4 == 0 else "residential"
                for rr, cc in ((r + 1, c), (r, c + 1)):
                    if rr < rows and cc < cols:
                        g.add_edge(f"{r}-{c}", f"{rr}-{cc}", highway=hw)
                        g.add_edge(f"{rr}-{cc}", f"{r}-{c}", highway=hw)
        return cls(g, name=f"grid {rows}x{cols}")

    # ---------- queries ----------
    def _dist_m(self, lat: float, lon: float) -> np.ndarray:
        """Approximate metres from (lat, lon) to every junction (equirectangular; fine at city scale)."""
        dy = (self._lat - lat) * 111_320
        dx = (self._lon - lon) * 111_320 * math.cos(math.radians(lat))
        return np.hypot(dx, dy)

    def nearest(self, lat: float, lon: float):
        return self.node_ids[int(np.argmin(self._dist_m(lat, lon)))]

    def within(self, lat: float, lon: float, radius_m: float) -> list:
        idx = np.nonzero(self._dist_m(lat, lon) <= radius_m)[0]
        return [self.node_ids[i] for i in idx]

    def blocked_nodes(self, hazards: list[Hazard]) -> set:
        out: set = set()
        for h in hazards:
            out.update(self.within(h.lat, h.lon, h.radius_m + HAZARD_BUFFER_M))
        return out

    def blocked_edges(self, hazards: list[Hazard]) -> set:
        """Edges whose middle lies in a hazard (catches long roads passing through it)."""
        out: set = set()
        for h in hazards:
            for u in self.within(h.lat, h.lon, h.radius_m + 800):   # roads rarely exceed 800 m between junctions
                for v in self.g.successors(u):
                    if h.covers((self.lat[u] + self.lat[v]) / 2, (self.lon[u] + self.lon[v]) / 2):
                        out.add((u, v))
                        out.add((v, u))
        return out

    def route(self, a: tuple[float, float], b: tuple[float, float], hazards: list[Hazard] | None = None) -> dict | None:
        hazards = hazards or []
        blocked = self.blocked_nodes(hazards)
        src, dst = self.nearest(*a), self.nearest(*b)
        # Start and end are kept even inside a hazard: the unit is there / the victim is there.
        blocked.discard(src)
        blocked.discard(dst)

        bad_edges = self.blocked_edges(hazards)

        def weight(u, v, edges):
            if u in blocked or v in blocked or (u, v) in bad_edges:
                return None
            return min(d["seconds"] for d in edges.values())

        try:
            path = nx.shortest_path(self.g, src, dst, weight=weight)
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return None
        coords = [[a[0], a[1]]] + [[self.lat[n], self.lon[n]] for n in path] + [[b[0], b[1]]]
        meters = seconds = 0.0
        for u, v in zip(path, path[1:]):
            best = min(self.g[u][v].values(), key=lambda d: d["seconds"])
            meters += best["length"]
            seconds += best["seconds"]
        return {"coords": coords, "distance_m": round(meters), "eta_min": max(1, round(seconds / 60)),
                "source": f"road graph ({self.name})", "avoided": [h.id for h in hazards]}


# ---------- the router used by the app ----------
_network: RoadNetwork | None = None


def network() -> RoadNetwork | None:
    global _network
    if _network is None:
        path = os.environ.get("ROAD_GRAPH")
        if path and os.path.exists(path):
            _network = RoadNetwork.load(path)
        elif os.environ.get("DEMO_GRID"):  # "lat,lon[,km]" -> synthetic grid (testing only, not real roads)
            parts = [float(x) for x in os.environ["DEMO_GRID"].split(",")]
            lat, lon, km = parts[0], parts[1], (parts[2] if len(parts) > 2 else 3.5)
            n = max(4, int(km * 1000 / 220))
            _network = RoadNetwork.grid(lat, lon, rows=n, cols=n, spacing_m=220)
    return _network


def set_network(net: RoadNetwork | None) -> None:
    global _network
    _network = net


def _osrm(a, b) -> dict | None:
    base = os.environ.get("OSRM_URL", "https://router.project-osrm.org")
    url = f"{base}/route/v1/driving/{a[1]},{a[0]};{b[1]},{b[0]}?overview=full&geometries=geojson"
    try:
        with urllib.request.urlopen(url, timeout=4) as res:
            data = json.loads(res.read())
        r = data["routes"][0]
        coords = [[lat, lon] for lon, lat in r["geometry"]["coordinates"]]
        return {"coords": coords, "distance_m": round(r["distance"]), "eta_min": max(1, round(r["duration"] / 60)),
                "source": "OSRM (cannot avoid reported hazards)", "avoided": []}
    except Exception:
        return None


def plan(a: tuple[float, float], b: tuple[float, float], hazards: list[Hazard] | None = None) -> dict:
    """Best available route from a to b avoiding hazards. Never raises."""
    net = network()
    if net is not None:
        r = net.route(a, b, hazards)
        if r:
            return r
        return {"coords": [list(a), list(b)], "distance_m": round(haversine_m(*a, *b)), "eta_min": None,
                "source": "NO ROAD ROUTE: every road is blocked; send a boat or drone", "avoided": [h.id for h in hazards or []],
                "no_road_route": True}
    if os.environ.get("USE_OSRM", "1") == "1":
        r = _osrm(a, b)
        if r:
            return r
    d = haversine_m(*a, *b)
    return {"coords": [list(a), list(b)], "distance_m": round(d), "eta_min": max(1, round(d / 1000 / DEFAULT_SPEED * 60)),
            "source": "straight line (no routing available)", "avoided": []}


DRONE_SPEED_KMH = 50


def aerial(a: tuple[float, float], b: tuple[float, float]) -> dict:
    """Straight flight line for drones (no buildings, terrain or airspace modelled)."""
    d = haversine_m(*a, *b)
    return {"coords": [list(a), list(b)], "distance_m": round(d), "eta_min": max(1, round(d / 1000 / DRONE_SPEED_KMH * 60)),
            "source": "aerial straight line (drone)", "avoided": []}


def route_hits(coords: list[list[float]], hazard: Hazard) -> bool:
    """True if a route passes through a hazard (checks points every ~20 m)."""
    for (la1, lo1), (la2, lo2) in zip(coords, coords[1:]):
        steps = max(1, int(haversine_m(la1, lo1, la2, lo2) // 20))
        for i in range(steps + 1):
            t = i / steps
            if hazard.covers(la1 + (la2 - la1) * t, lo1 + (lo2 - lo1) * t, extra=10):
                return True
    return False
