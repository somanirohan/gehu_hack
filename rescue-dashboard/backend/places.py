"""Dehradun places: map centre, landmarks, risk layer and demo unit staging."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter

FILE = Path(__file__).with_name("dehradun_places.json")
router = APIRouter(prefix="/api/v1")


def load() -> dict:
    return json.loads(FILE.read_text(encoding="utf-8"))


def demo_units() -> list[tuple[str, str, float, float]]:
    data = load()
    at = {p["id"]: p for p in data["places"]}
    return [(u["name"], u["kind"], at[u["at"]]["lat"], at[u["at"]]["lon"]) for u in data["units"]]


@router.get("/places")
def places():
    """Map centre, landmarks and risk areas (flood, accident, landslide) with their sources."""
    d = load()
    return {"center": d["center"], "places": d["places"]}
