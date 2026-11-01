"""Verifier Agent: is this SOS real?

Real disasters bring false alarms, test messages, pranks and the same person sending
the same thing ten times. The Verifier gathers EVIDENCE with plain code (who else
reported nearby, did an official / camera / responder confirm, is the sender spamming,
is the location inside Dehradun, does the text say test/drill), then asks the AI for
a verdict with reasons. If the AI is unavailable, a fixed rule gives the verdict.

Verdicts: confirmed | likely | unverified | possible_fake
It NEVER deletes or hides an SOS and never lowers its priority. It only warns the officer.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field

import logic
import main as core
from agents import llm

NEARBY_M = 500
NEARBY_MIN = 60
SPAM_WINDOW_MIN = 30
DEHRADUN_BOX = (29.95, 77.55, 30.65, 78.35)  # lat_min, lon_min, lat_max, lon_max
OFFICIAL_ROLES = {"AMBULANCE", "FIRE", "GOV"}
TEST_WORDS = re.compile(r"\b(test|testing|drill|demo|practice|mazaak|mazak|joke|prank|fake|jhooth)\b", re.I)

SCHEMA = """
CREATE TABLE IF NOT EXISTS verifications (
  id INTEGER PRIMARY KEY AUTOINCREMENT, incident_id INTEGER, verdict TEXT, reasons TEXT,
  evidence TEXT, source TEXT, at TEXT);
"""


class Verdict(BaseModel):
    verdict: Literal["confirmed", "likely", "unverified", "possible_fake"] = Field(
        description="confirmed = independent sources agree (2+ different people, or an official/camera/responder); "
                    "likely = one detailed, plausible report; unverified = too little to say; "
                    "possible_fake = clear signs of test/prank/spam/impossible location")
    reasons: str = Field(description="max 30 words, cite the evidence (e.g. '3 different senders within 200 m')")


SYSTEM = """You are the verification officer in the Dehradun disaster control room.
You get EVIDENCE gathered by software about one incident and decide how trustworthy it is.
Rules:
- Base the verdict ONLY on the evidence given. Do not invent facts.
- Never call a report fake just because it is short, emotional or badly spelled: people in danger write that way.
- Use possible_fake only for clear signs: the text says test/prank/joke, spam_signals is not empty
  (one sender, many far-apart places), or the location is outside the area.
- Repeat messages from the same person at the same place are NORMAL for someone in danger: never a reason for fake.
- If in doubt between two verdicts, choose the more cautious one for people's lives (e.g. 'likely' over 'unverified').
- A real emergency marked as fake costs lives; a fake marked as likely costs only a little time.
"""


def init(con) -> None:
    con.executescript(SCHEMA)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(ts: str | None) -> datetime:
    return logic.parse_time(ts)


def evidence(con, incident_id: int) -> Optional[dict]:
    """Facts only, gathered with code. This is what the AI sees."""
    inc = con.execute("SELECT * FROM incidents WHERE id=?", (incident_id,)).fetchone()
    if not inc:
        return None
    inc = dict(inc)
    reps = core.rows(con.execute("SELECT * FROM reports WHERE incident_id=?", (incident_id,)))
    evs = core.rows(con.execute("SELECT device_id, payload, created_at, lat, lon FROM events WHERE incident_id=?", (incident_id,)))
    payloads = [json.loads(e["payload"] or "{}") for e in evs]
    senders = {e["device_id"] for e in evs if e["device_id"]}
    roles = {(p.get("role") or "").upper() for p in payloads} - {""}
    sources = {r["source"] for r in reps}
    texts = [r["message"] or "" for r in reps]

    # other open incidents nearby (people reporting the same area, maybe a different type)
    nearby = 0
    t0 = _parse(inc["first_report_at"])
    for o in con.execute("SELECT id, lat, lon, first_report_at FROM incidents WHERE id != ? AND status != 'resolved'", (incident_id,)):
        if logic.distance_m(inc["lat"], inc["lon"], o["lat"], o["lon"]) <= NEARBY_M and \
                abs((_parse(o["first_report_at"]) - t0).total_seconds()) <= NEARBY_MIN * 60:
            nearby += 1

    # sender behaviour: how many SOS from the same device recently, and how spread out
    spam, repeats = [], []
    for dev in senders:
        rows = core.rows(con.execute("SELECT lat, lon, created_at, incident_id FROM events WHERE device_id=? AND kind='sos'", (dev,)))
        recent = [r for r in rows if (_now() - _parse(r["created_at"])).total_seconds() <= SPAM_WINDOW_MIN * 60]
        if len(recent) >= 2:
            spread = max((logic.distance_m(a["lat"], a["lon"], b["lat"], b["lon"])
                          for a in recent for b in recent if a["lat"] is not None and b["lat"] is not None), default=0)
            n_inc = len({r["incident_id"] for r in recent})
            # A person in danger often sends 2 or 3 SOS from the same place: that is NOT spam.
            # Spam = many SOS for 3+ different incidents spread over more than 2 km.
            if n_inc >= 3 and spread > 2000:
                spam.append({"sender": dev, "sos_last_30_min": len(recent),
                             "different_incidents": n_inc, "spread_m": round(spread)})
            else:
                repeats.append({"sender": dev, "sos_last_30_min": len(recent), "spread_m": round(spread),
                                "note": "same person sent several SOS from about the same place (normal when in danger)"})

    inside = DEHRADUN_BOX[0] <= inc["lat"] <= DEHRADUN_BOX[2] and DEHRADUN_BOX[1] <= inc["lon"] <= DEHRADUN_BOX[3]
    test_words = sorted({m.group(0).lower() for t in texts for m in TEST_WORDS.finditer(t)})
    drill = any("drill" in (r["via"] or "") for r in reps)
    return {
        "incident": {"id": incident_id, "type": inc["type"], "people": inc["people"]},
        "reports": len(reps),
        "different_senders": len(senders),
        "sender_roles": sorted(roles),
        "official_confirmation": bool(roles & OFFICIAL_ROLES) or bool(sources & {"camera", "responder", "manual"}),
        "camera_confirmation": "camera" in sources,
        "other_incidents_within_500m_1h": nearby,
        "spam_signals": spam,
        "repeat_messages_same_place": repeats,
        "inside_dehradun_area": inside,
        "test_words_in_text": test_words,
        "practice_drill": drill,
        "messages": [t[:200] for t in texts[-5:]],
    }


def rule_verdict(ev: dict) -> tuple[str, str]:
    """Fixed fallback when the AI is unavailable. Same evidence, simple rules."""
    if not ev["inside_dehradun_area"]:
        return "possible_fake", "Location is outside the Dehradun area"
    if any(s["different_incidents"] >= 3 and s["spread_m"] > 2000 for s in ev["spam_signals"]):
        return "possible_fake", "Same sender reported 3+ different places far apart within 30 min"
    if ev["test_words_in_text"] and not ev["practice_drill"]:
        return "possible_fake", f"Text contains: {', '.join(ev['test_words_in_text'])}"
    if ev["official_confirmation"]:
        return "confirmed", "Confirmed by an official, camera or responder"
    if ev["different_senders"] >= 2:
        return "confirmed", f"{ev['different_senders']} different people reported it"
    if ev["other_incidents_within_500m_1h"]:
        return "likely", f"{ev['other_incidents_within_500m_1h']} other report(s) nearby in the last hour"
    return "unverified", "Single report, no other source yet"


def verify(incident_id: int) -> Optional[dict]:
    """Gather evidence, get a verdict (AI or rules), store it. Never raises."""
    try:
        with core.db() as con:
            init(con)
            ev = evidence(con, incident_id)
        if ev is None:
            return None
        # The AI judges every report as if it were real: whether it is practice data is already
        # shown by the DRILL badge, so that flag is NOT given to the AI.
        for_ai = {k: v for k, v in ev.items() if k != "practice_drill"}
        # patient: the SOS is already saved and shown; better a real verdict a few seconds later than a rule one
        v = llm.structured(Verdict, SYSTEM, "EVIDENCE (JSON):\n" + json.dumps(for_ai, ensure_ascii=False), patient=True)
        if v is not None:
            verdict, reasons, source = v.verdict, v.reasons, llm.label()
        else:
            (verdict, reasons), source = rule_verdict(ev), "rule check"
        at = _now().isoformat(timespec="seconds")
        with core.db() as con:
            con.execute("INSERT INTO verifications (incident_id,verdict,reasons,evidence,source,at) VALUES (?,?,?,?,?,?)",
                        (incident_id, verdict, reasons, json.dumps(ev, ensure_ascii=False), source, at))
            core.write_log(con, "verifier-agent", "verified", incident_id, verdict=verdict, source=source)
        return {"incident_id": incident_id, "verdict": verdict, "reasons": reasons, "source": source, "at": at, "evidence": ev}
    except Exception as exc:  # the agent must never break incoming SOS handling
        return {"incident_id": incident_id, "error": str(exc)[:200]}


def verify_many(ids) -> list:
    return [verify(i) for i in dict.fromkeys(i for i in ids if i)]


def latest(con, incident_id: int) -> Optional[dict]:
    init(con)
    r = con.execute("SELECT verdict, reasons, evidence, source, at FROM verifications WHERE incident_id=? ORDER BY id DESC LIMIT 1",
                    (incident_id,)).fetchone()
    if not r:
        return None
    return {"verdict": r[0], "reasons": r[1], "evidence": json.loads(r[2]), "source": r[3], "at": r[4]}


def latest_map(con) -> dict:
    init(con)
    out = {}
    for iid, verdict in con.execute("SELECT incident_id, verdict FROM verifications ORDER BY id"):
        out[iid] = verdict
    return out
