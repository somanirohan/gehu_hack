"""Triage Agent: reads every incoming SOS like an experienced control-room operator.

Input:  free text from the mesh app (Hindi, English, Hinglish, typos, emojis).
Output: a fixed schema (Triage) -> type, people, injured, vulnerable people, urgency,
        landmarks, what is needed, a one-line English summary, confidence and reasons.

Rules that never change:
  * The result is a SUGGESTION, labelled with the model that produced it.
  * If the AI is unavailable/slow/fails, the old word rules (classify.py) are used.
  * The AI never dispatches anything; the officer still approves.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

import classify
from agents import llm

IncidentType = Literal["trapped", "collapse", "landslide", "fire", "injured", "accident", "medical",
                       "missing", "flood", "crowd", "fall", "other"]


class Triage(BaseModel):
    kind: Literal["sos", "road_block", "message"] = Field(
        description="sos = someone needs help; road_block = a road/bridge is blocked or unsafe and nobody "
                    "is asking for rescue; message = information/chat, no help needed")
    incident_type: IncidentType = Field(description="main emergency type (for sos); 'other' if unclear")
    people: Optional[int] = Field(None, description="number of people needing help, if stated or clearly implied")
    injured: Optional[int] = Field(None, description="number injured, if mentioned")
    vulnerable: list[Literal["children", "elderly", "pregnant", "disabled", "sick"]] = Field(
        default_factory=list, description="vulnerable people mentioned")
    urgency: Literal["critical", "high", "medium", "low"] = Field(
        description="critical = life in danger now (trapped in rising water, not breathing, fire with people inside); "
                    "high = serious injury or danger soon; medium = needs help but stable; low = no immediate danger")
    landmarks: list[str] = Field(default_factory=list, description="places mentioned, e.g. 'Tapkeshwar mandir', 'Rispana pul'")
    needs: list[Literal["rescue", "boat", "ambulance", "fire", "police", "drone", "food", "water", "shelter", "medicine"]] = Field(
        default_factory=list, description="what help is needed")
    summary_en: str = Field(description="one short English sentence for the officer, max 20 words")
    language: str = Field(description="language of the message, e.g. Hinglish, Hindi, English, Garhwali")
    confidence: float = Field(description="0 to 1: how sure you are about type and urgency")
    reasons: str = Field(description="max 25 words: which words or facts led to this reading")


SYSTEM = """You are the triage officer of the Dehradun (Uttarakhand, India) disaster control room.
You read SOS messages that arrive from an offline mesh-messaging app. They are written in Hindi,
English, Hinglish (Hindi in Latin letters) or Garhwali, often with typos, and may contain emojis
(🆘 means SOS, ⛔ means road blocked).

Rules:
- Read ONLY what the message says. Never invent people, injuries or places. If a number is not
  given, leave it empty.
- "fase/phase/phas gaye/trapped/nikal nahi pa rahe" = trapped (people cannot get out).
  Water rising + trapped => incident_type "trapped", urgency "critical", needs include "boat" or "rescue".
- "behosh/saans nahi" = unconscious/not breathing => critical, medical/injured, needs ambulance.
- A message ONLY about a blocked/broken/flooded road or bridge, with nobody asking for help,
  is kind "road_block".
- Test or drill messages are still read normally, but mention "test" in the reasons.
- Greetings, status updates ("we are safe", "reached shelter") are kind "message", urgency "low".
- summary_en must be plain English an officer can read in 2 seconds.
"""


def ai_triage(text: str, role: Optional[str] = None) -> Optional[Triage]:
    """The AI reading, or None if AI is unavailable or failed."""
    clean = classify.clean(text or "").strip()
    if not clean:
        return None
    user = f"Sender role in the app: {role or 'unknown'}\nMessage: {clean}"
    return llm.structured(Triage, SYSTEM, user)


def to_rule_shape(t: Triage) -> dict:
    """Convert the AI reading into the same shape classify.classify() returns, plus AI extras."""
    matched = []
    return {
        "kind": t.kind,
        "type": t.incident_type if t.kind == "sos" else ("landslide" if t.incident_type == "landslide" else None),
        "people": t.people,
        "matched": matched,
        "confidence": round(max(0.0, min(1.0, t.confidence)), 2),
        "label": llm.label(),
        "ai": {
            "summary": t.summary_en,
            "urgency": t.urgency,
            "injured": t.injured,
            "vulnerable": t.vulnerable,
            "landmarks": t.landmarks,
            "needs": t.needs,
            "language": t.language,
            "reasons": t.reasons,
        },
    }


def read(text: str, role: Optional[str] = None) -> dict:
    """Best available reading: AI first, word rules as fallback. Never raises."""
    rules = classify.classify(text or "")
    t = ai_triage(text, role)
    if t is None:
        rules["ai_error"] = llm.status()["last_call"].get("error") if llm.provider() else None
        return rules
    out = to_rule_shape(t)
    out["rule_guess"] = f"{rules['kind']}/{rules['type']}"  # kept so the officer can compare
    return out
