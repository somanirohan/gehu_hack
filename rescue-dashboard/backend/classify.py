"""Rule-based reading of free-text mesh messages (English, Hindi, Hinglish).

The app's existing sync sends plain messages, not typed SOS events. These rules
suggest what a message is about so the dashboard can place and rank it. Every
result is labelled as a RULE SUGGESTION with the words that matched, never as
verified fact; an officer confirms or corrects it.
"""
from __future__ import annotations

import re

# (incident type, words). Checked in order: the first group that matches wins.
RULES: list[tuple[str, list[str]]] = [
    ("trapped",   ["trapped", "stuck", "fas gaye", "fase", "phase hue", "phas", "nikal nahi", "roof par", "chhat par", "chat par", "rooftop"]),
    ("collapse",  ["collapse", "building gir", "makaan gir", "ghar gir", "deewar gir", "wall fell", "debris", "malba"]),
    ("landslide", ["landslide", "bhuskhalan", "bhooskhalan", "pahad gir", "rockfall", "mudslide"]),
    ("fire",      ["fire", "aag", "smoke", "dhuan", "burning", "jal raha", "jal rahi"]),
    ("injured",   ["injured", "ghayal", "bleeding", "khoon", "hurt", "chot", "unconscious", "behosh", "fracture"]),
    ("accident",  ["accident", "durghatna", "collision", "takkar", "crash", "overturned", "palat"]),
    ("medical",   ["medical", "doctor", "medicine", "dawai", "insulin", "pregnant", "delivery", "heart attack", "oxygen"]),
    ("missing",   ["missing", "lapata", "laapata", "kho gaya", "kho gayi", "not found", "nahi mil"]),
    ("flood",     ["flood", "baadh", "badh", "paani", "pani", "water level", "water rising", "submerged", "doob", "dub gaya", "cloudburst", "badal phat", "badal fat"]),
    ("crowd",     ["crowd", "bheed", "stampede", "bhagdad"]),
]
ROAD_BLOCK = ["\u26d4", "road block", "road blocked", "road band", "rasta band", "raasta band", "sadak band", "road closed",
              "road washed", "road damaged", "bridge broken", "pul toot", "pul tut", "bridge collapsed", "road cut",
              "blocked road", "no way", "cannot pass", "can't pass", "nahi ja sakte", "nahi ja sakti", "nahi ja sakta"]
SOS = ["\U0001F198", "sos", "help", "bachao", "madad", "emergency", "urgent", "jaldi", "save us", "please help"]

_people = re.compile(r"(\d{1,3})\s*(?:log|people|persons|person|ppl|logo|aadmi|members|bacche|children|kids)", re.I)
_geo = re.compile(r"geo:-?\d+(?:\.\d+)?,-?\d+(?:\.\d+)?")


def clean(text: str) -> str:
    """Remove the app's geo:lat,lon tag so officers read only the message."""
    return re.sub(r"\s{2,}", " ", _geo.sub("", text or "")).strip()


def _has(text: str, words: list[str]) -> list[str]:
    return [w for w in words if re.search(rf"(?<![a-z]){re.escape(w)}(?![a-z])", text)]


def classify(text: str) -> dict:
    t = clean(text).lower()
    road = _has(t, ROAD_BLOCK)
    sos = _has(t, SOS)
    itype, matched = None, []
    for kind, words in RULES:
        m = _has(t, words)
        if m:
            itype, matched = kind, m
            break
    pm = _people.search(t)
    people = int(pm.group(1)) if pm else None
    if road and not itype:
        kind = "road_block"
    elif road and itype in ("flood", "landslide", "collapse") and not people and not sos:
        kind = "road_block"            # "road flooded / landslide debris blocked the road"
    elif itype or sos:
        kind = "sos"
    else:
        kind = "message"
    if kind == "sos" and not itype:
        itype = "other"
    confidence = 0.5 + 0.15 * min(len(matched) + len(sos) + len(road), 3)
    return {
        "kind": kind,
        "type": itype,
        "people": people,
        "matched": matched + sos + road,
        "confidence": round(min(confidence, 0.95), 2),
        "label": "rule suggestion",
    }
