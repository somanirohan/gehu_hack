"""Pure decision rules: distance, duplicate merging, priority, responder suggestion.

No AI model sets any number here. Every score comes with a plain-language reason,
so an officer can see why an incident is ranked where it is.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

# How bad each incident type is on its own (0-40).
TYPE_WEIGHT = {
    "trapped": 40,
    "injured": 35,
    "fire": 35,
    "fall": 30,
    "medical": 30,
    "flood": 25,
    "crowd": 20,
    "sensor": 25,
    "collapse": 40,
    "landslide": 35,
    "accident": 30,
    "missing": 25,
    "other": 10,
}

# Types that count as "the same emergency" when merging nearby reports.
MERGE_FAMILY = {
    "fall": "person-down",
    "injured": "person-down",
    "medical": "person-down",
    "trapped": "trapped",
    "sensor": "trapped",
    "fire": "fire",
    "flood": "flood",
    "crowd": "crowd",
    "collapse": "trapped",
    "landslide": "landslide",
    "accident": "person-down",
    "missing": "missing",
    "other": "other",
}

MERGE_RADIUS_M = 150
MERGE_WINDOW_MIN = 30

# Which responder kinds can handle which incident families.
CAPABLE = {
    "person-down": {"ambulance", "rescue"},
    "trapped": {"rescue", "fire"},
    "fire": {"fire"},
    "flood": {"rescue", "boat"},
    "crowd": {"police"},
    "landslide": {"rescue", "drone"},
    "missing": {"police", "drone", "rescue"},
    "other": {"rescue", "police", "ambulance", "fire", "drone", "boat"},
}

AVG_SPEED_KMH = 25  # flooded city roads; used only for a rough ETA


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def parse_time(value: str | None) -> datetime:
    if not value:
        return now_utc()
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres (haversine)."""
    r = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def family(incident_type: str) -> str:
    return MERGE_FAMILY.get(incident_type, "other")


def should_merge(report: dict, incident: dict) -> bool:
    """A new report joins an open incident of the same family, close by, recent."""
    if incident["status"] == "resolved":
        return False
    if family(report["type"]) != family(incident["type"]):
        return False
    if distance_m(report["lat"], report["lon"], incident["lat"], incident["lon"]) > MERGE_RADIUS_M:
        return False
    gap_min = abs((parse_time(report["reported_at"]) - parse_time(incident["last_report_at"])).total_seconds()) / 60
    return gap_min <= MERGE_WINDOW_MIN


def priority(incident: dict, at: datetime | None = None) -> tuple[int, str]:
    """Score 0-100 plus the reason, from type, people, reports and waiting time."""
    at = at or now_utc()
    t = TYPE_WEIGHT.get(incident["type"], 10)
    people = min(incident.get("people") or 1, 20)
    p_score = min(people * 2, 20)
    r_score = min((incident.get("report_count", 1) - 1) * 3, 15)
    waited_min = max(0, (at - parse_time(incident["first_report_at"])).total_seconds() / 60)
    w_score = min(int(waited_min // 5) * 2, 15)
    v_score = 10 if incident.get("source") == "camera" else 0  # seen on camera = confirmed
    score = min(100, t + p_score + r_score + w_score + v_score)
    parts = [f"{incident['type']} +{t}", f"{people} {'person' if people == 1 else 'people'} +{p_score}"]
    if r_score:
        parts.append(f"{incident['report_count']} reports +{r_score}")
    if w_score:
        parts.append(f"waiting {int(waited_min)} min +{w_score}")
    if v_score:
        parts.append(f"camera-confirmed +{v_score}")
    return score, " · ".join(parts)


def severity_label(score: int) -> str:
    if score >= 70:
        return "critical"
    if score >= 50:
        return "high"
    if score >= 30:
        return "medium"
    return "low"


def suggest_responder(incident: dict, responders: list[dict]) -> tuple[dict | None, str]:
    """Nearest available responder that can handle this incident, with the reason."""
    needed = CAPABLE.get(family(incident["type"]), CAPABLE["other"])
    options = []
    for r in responders:
        if r["status"] != "available" or r["kind"] not in needed:
            continue
        d = distance_m(incident["lat"], incident["lon"], r["lat"], r["lon"])
        options.append((d, r))
    if not options:
        return None, f"No available {' / '.join(sorted(needed))} unit; consider mutual aid"
    options.sort(key=lambda x: x[0])
    d, best = options[0]
    eta = max(1, round(d / 1000 / AVG_SPEED_KMH * 60))
    reason = f"{best['name']} ({best['kind']}) is nearest available: {d / 1000:.1f} km, about {eta} min"
    if len(options) > 1:
        d2, nxt = options[1]
        reason += f"; next best {nxt['name']} at {d2 / 1000:.1f} km"
    return best, reason


def summarize(incident: dict, reports: list[dict]) -> str:
    """One-line summary from the reports. Rule-based; swap in an LLM later if wanted."""
    sources = sorted({r["source"] for r in reports})
    msgs = [r["message"] for r in reports if r.get("message")]
    people = incident.get("people") or 1
    head = f"{incident['type'].capitalize()}, {people} {'person' if people == 1 else 'people'}"
    head += f", {len(reports)} report{'s' if len(reports) != 1 else ''} via {', '.join(sources)}"
    if msgs:
        head += f'. Latest: "{msgs[-1][:90]}"'
    return head
