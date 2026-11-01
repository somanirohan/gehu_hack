"""Voice notes and photos from the field. The AI calls are replaced with fakes, so these
tests run offline and without keys; they check what the server does with the AI's answer."""
import io
import os
import tempfile
import uuid

os.environ["RESCUE_DB"] = os.path.join(tempfile.mkdtemp(), "field.db")
os.environ["USE_OSRM"] = "0"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
import routing  # noqa: E402
from agents import media_ai  # noqa: E402

client = TestClient(main.app)
LAT, LON = 30.3165, 78.0322


@pytest.fixture(autouse=True)
def _rules_only(monkeypatch):
    """Triage uses the word rules here; media_ai is faked per test. Scoped to this file only."""
    monkeypatch.setenv("AI_DISABLED", "1")
    monkeypatch.setenv("PHOTO_CHECK_INLINE", "1")  # photo check inside the request; the queue has its own test
    monkeypatch.setattr(media_ai, "enabled", lambda: True)


def setup_function():
    routing.set_network(routing.RoadNetwork.grid(LAT, LON, rows=12, cols=12, spacing_m=220))
    client.post("/api/demo/reset")


def jpeg(gps=None):
    from PIL import Image
    buf = io.BytesIO()
    im = Image.new("RGB", (64, 48), (60, 120, 40))
    if gps:
        exif = Image.Exif()
        exif.get_ifd(0x8825).update(gps)
        im.save(buf, "JPEG", exif=exif)
    else:
        im.save(buf, "JPEG")
    return buf.getvalue()


def fake_stt(text, language):
    return lambda raw, name, mime, hint=None: {"text": text, "language": language, "model": "fake-whisper"}


def tree(conf=0.9, blocks=True, hazard="fallen_tree", people=False):
    return lambda raw, mime, caption="", **kw: {"hazard": hazard, "blocks_road": blocks, "people_in_danger": people,
                                          "confidence": conf, "description": "A large tree lies across the road.",
                                          "radius_m": 50.0, "model": "fake-vision"}


def feed_item(event_id):
    return next(e for e in client.get("/api/v1/feed").json() if e["event_id"] == event_id)


# ---------- voice ----------
def test_hindi_voice_note_is_transcribed_translated_and_becomes_an_sos(monkeypatch):
    monkeypatch.setattr(media_ai, "transcribe", fake_stt("दो लोग फंसे हैं, पानी बढ़ रहा है", "hindi"))
    monkeypatch.setattr(media_ai, "translate_en", lambda text, lang: "Two people are trapped, the water is rising")
    r = client.post("/api/v1/field/voice", files={"file": ("sos.m4a", b"fake-audio", "audio/mp4")},
                    data={"lat": LAT, "lon": LON, "sender": "asha", "role": "CIVILIAN"}).json()
    assert r["transcript"].startswith("दो लोग")
    assert r["transcript_en"] == "Two people are trapped, the water is rising"
    assert r["incident_id"], r  # went through the normal pipeline
    e = feed_item(r["event_id"])
    assert e["kind"] == "sos"
    assert e["payload"]["spoken_language"] == "hindi"
    assert e["media"][0]["mime"].startswith("audio/")
    assert client.get(e["media"][0]["url"]).content == b"fake-audio"  # officer can play the recording
    inc = client.get(f"/api/incidents/{r['incident_id']}").json()
    assert not inc.get("photo")  # the audio file is never shown as the incident photo


def test_voice_without_location_is_kept_for_the_officer(monkeypatch):
    monkeypatch.setattr(media_ai, "transcribe", fake_stt("road is blocked near the bridge", "english"))
    r = client.post("/api/v1/field/voice", files={"file": ("v.ogg", b"x", "audio/ogg")}).json()
    assert r["transcript"] == "road is blocked near the bridge"
    assert r["transcript_en"] is None  # already English
    e = feed_item(r["event_id"])
    assert e["kind"] == "voice" and e["lat"] is None
    assert "no location" in e["payload"]["note"]


def test_voice_is_stored_even_when_speech_to_text_fails(monkeypatch):
    monkeypatch.setattr(media_ai, "transcribe", lambda *a, **k: None)
    r = client.post("/api/v1/field/voice", files={"file": ("v.m4a", b"x", "audio/mp4")},
                    data={"lat": LAT, "lon": LON}).json()
    e = feed_item(r["event_id"])
    assert e["kind"] == "voice"
    assert e["payload"]["stt_error"]
    assert "listen" in e["payload"]["note"]


def test_voice_upload_is_idempotent(monkeypatch):
    monkeypatch.setattr(media_ai, "transcribe", fake_stt("help", "english"))
    first = client.post("/api/v1/field/voice", files={"file": ("v.m4a", b"x", "audio/mp4")},
                        data={"lat": LAT, "lon": LON, "event_id": "voice-abc"}).json()
    again = client.post("/api/v1/field/voice", files={"file": ("v.m4a", b"x", "audio/mp4")},
                        data={"lat": LAT, "lon": LON, "event_id": "voice-abc"}).json()
    assert first["event_id"] == "voice-abc" and again["duplicate"] is True


# ---------- photos ----------
def test_fallen_tree_photo_asks_officer_then_blocks_road_with_photo_as_proof(monkeypatch):
    monkeypatch.setattr(media_ai, "analyze_photo", tree())
    r = client.post("/api/v1/field/photo", files={"file": ("t.jpg", jpeg(), "image/jpeg")},
                    data={"lat": LAT, "lon": LON, "caption": "ped gir gaya"}).json()
    s = r["suggestion"]
    assert s and s["status"] == "pending" and s["label"] == "Fallen tree"
    assert (s["lat"], s["lon"]) == (LAT, LON) and s["loc_source"] == "phone GPS"
    assert [x["id"] for x in client.get("/api/v1/field/suggestions").json()] == [s["id"]]
    assert client.get("/api/v1/hazards").json() == []  # nothing blocked until the officer says so

    ok = client.post(f"/api/v1/field/suggestions/{s['id']}/accept", json={"officer": "Insp. Rawat"}).json()
    hz = client.get("/api/v1/hazards").json()
    assert hz[0]["id"] == ok["hazard_id"] and hz[0]["status"] == "active"
    assert hz[0]["photo"] == s["photo"]  # proof attached to the blockage
    assert client.get("/api/v1/field/suggestions").json() == []
    log = client.get("/api/log").json()
    entry = next(x for x in (log if isinstance(log, list) else log["entries"]) if x["action"] == "photo_hazard_accepted")
    assert s["photo_sha256"] in str(entry)  # tamper-evident log records exactly which photo
    assert client.post(f"/api/v1/field/suggestions/{s['id']}/accept", json={}).status_code == 409


def test_photo_location_falls_back_to_exif_gps(monkeypatch):
    monkeypatch.setattr(media_ai, "analyze_photo", tree())
    gps = {1: "N", 2: (30.0, 18.0, 59.4), 3: "E", 4: (78.0, 1.0, 55.92)}
    r = client.post("/api/v1/field/photo", files={"file": ("t.jpg", jpeg(gps), "image/jpeg")}).json()
    assert r["location_source"] == "photo GPS (EXIF)"
    assert abs(r["suggestion"]["lat"] - 30.3165) < 1e-3 and abs(r["suggestion"]["lon"] - 78.0322) < 1e-3


def test_photo_without_location_needs_a_spot_picked_on_the_map(monkeypatch):
    monkeypatch.setattr(media_ai, "analyze_photo", tree())
    s = client.post("/api/v1/field/photo", files={"file": ("t.jpg", jpeg(), "image/jpeg")}).json()["suggestion"]
    assert s["lat"] is None
    assert client.post(f"/api/v1/field/suggestions/{s['id']}/accept", json={}).status_code == 422
    ok = client.post(f"/api/v1/field/suggestions/{s['id']}/accept", json={"lat": LAT, "lon": LON})
    assert ok.status_code == 200
    assert client.get("/api/v1/hazards").json()[0]["lat"] == LAT


def test_harmless_or_unsure_photo_does_not_prompt(monkeypatch):
    monkeypatch.setattr(media_ai, "analyze_photo", tree(hazard="none", blocks=False))
    assert client.post("/api/v1/field/photo", files={"file": ("a.jpg", jpeg(), "image/jpeg")},
                       data={"lat": LAT, "lon": LON}).json()["suggestion"] is None
    monkeypatch.setattr(media_ai, "analyze_photo", tree(conf=0.2))
    assert client.post("/api/v1/field/photo", files={"file": ("b.jpg", jpeg(), "image/jpeg")},
                       data={"lat": LAT, "lon": LON}).json()["suggestion"] is None


def test_dismissed_suggestion_blocks_nothing(monkeypatch):
    monkeypatch.setattr(media_ai, "analyze_photo", tree())
    s = client.post("/api/v1/field/photo", files={"file": ("t.jpg", jpeg(), "image/jpeg")},
                    data={"lat": LAT, "lon": LON}).json()["suggestion"]
    assert client.post(f"/api/v1/field/suggestions/{s['id']}/dismiss", json={"officer": "x"}).json()["ok"]
    assert client.get("/api/v1/hazards").json() == []
    assert client.get("/api/v1/field/suggestions?status=dismissed").json()[0]["id"] == s["id"]


def test_photo_still_stored_when_ai_is_off(monkeypatch):
    monkeypatch.setattr(media_ai, "enabled", lambda: False)
    monkeypatch.setattr(media_ai, "analyze_photo", lambda *a, **k: None)
    r = client.post("/api/v1/field/photo", files={"file": ("t.jpg", jpeg(), "image/jpeg")},
                    data={"lat": LAT, "lon": LON}).json()
    assert r["suggestion"] is None
    e = feed_item(r["event_id"])
    assert e["kind"] == "photo" and e["media"][0]["mime"].startswith("image/") and e["payload"]["ai_error"]


def test_photo_with_people_in_danger_creates_incident(monkeypatch):
    monkeypatch.setattr(media_ai, "analyze_photo", tree(hazard="collapsed_structure", people=True))
    r = client.post("/api/v1/field/photo", files={"file": ("c.jpg", jpeg(), "image/jpeg")},
                    data={"lat": LAT, "lon": LON}).json()
    assert r["incident_id"]
    assert client.get(f"/api/incidents/{r['incident_id']}").json()["photo"]


def test_unique_event_ids(monkeypatch):
    monkeypatch.setattr(media_ai, "analyze_photo", lambda *a, **k: None)
    ids = {client.post("/api/v1/field/photo", files={"file": (f"{uuid.uuid4()}.jpg", jpeg(), "image/jpeg")}).json()["event_id"]
           for _ in range(3)}
    assert len(ids) == 3


# ---------- the AI client itself (network replaced) ----------
def test_photo_reader_normalises_model_output(monkeypatch):
    monkeypatch.delenv("AI_DISABLED", raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "test")
    monkeypatch.setattr(media_ai, "_groq_chat", lambda *a, **k: 'Sure! ```json\n{"hazard": "Fallen Tree", "blocks_road": true, '
                        '"people_in_danger": false, "confidence": 1.7, "description": "Tree on road", "suggested_radius_m": 5}\n```')
    out = media_ai.analyze_photo(b"img", "image/jpeg")
    assert out["hazard"] == "fallen_tree" and out["confidence"] == 1.0 and out["radius_m"] == 30.0


def test_speech_falls_back_to_gemini_when_groq_fails(monkeypatch):
    monkeypatch.delenv("AI_DISABLED", raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "test")
    monkeypatch.setenv("GEMINI_API_KEY", "test")

    class Boom:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, *a, **k):
            raise ConnectionError("groq down")

    monkeypatch.setattr(media_ai, "_client", lambda: Boom())
    monkeypatch.setattr(media_ai, "_gemini", lambda parts, want_json: '{"text": "மரம் விழுந்துவிட்டது", "language": "Tamil"}')
    out = media_ai.transcribe(b"a", "v.m4a", "audio/mp4")
    assert out == {"text": "மரம் விழுந்துவிட்டது", "language": "Tamil", "model": "Gemini"}
    assert "groq down" in media_ai.last_error["error"]


def test_groq_requests_carry_the_api_key(monkeypatch):
    """Guards the exact header sent to Groq (an edit once broke it and every photo check failed)."""
    monkeypatch.delenv("AI_DISABLED", raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test_key")
    seen = []

    class Resp:
        status_code = 200
        headers: dict = {}

        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "{}"}}], "text": "hi", "language": "english", "data": []}

    class Capture:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, **kw):
            seen.append(kw["headers"]["Authorization"])
            return Resp()

        def get(self, url, **kw):
            seen.append(kw["headers"]["Authorization"])
            return Resp()

    monkeypatch.setattr(media_ai, "_client", lambda: Capture())
    media_ai._groq_models.update(ids=None, at=0.0)
    media_ai.analyze_photo(b"x", "image/jpeg")
    media_ai.transcribe(b"x", "v.m4a", "audio/mp4")
    media_ai.translate_en("नमस्ते", "hindi")
    assert len(seen) >= 4 and set(seen) == {"Bearer gsk_test_key"}, seen


def test_photo_check_failure_is_recorded(monkeypatch):
    monkeypatch.setattr(media_ai, "analyze_photo", lambda *a, **k: None)
    r = client.post("/api/v1/field/photo", files={"file": ("t.jpg", jpeg(), "image/jpeg")},
                    data={"lat": LAT, "lon": LON}).json()
    e = feed_item(r["event_id"])
    assert e["payload"]["ai_status"] == "failed" and e["media"][0]["url"]


def test_queue_waits_out_rate_limits_then_suggests(monkeypatch):
    """The real queue (not inline): first two tries are rate-limited, third succeeds."""
    import time
    import field_media
    monkeypatch.delenv("PHOTO_CHECK_INLINE", raising=False)
    waits = []

    async def no_sleep(s):
        waits.append(s)

    monkeypatch.setattr(field_media, "_sleep", no_sleep)
    calls = {"n": 0}

    def flaky(raw, mime, caption="", raise_rate_limit=False):
        calls["n"] += 1
        if calls["n"] < 3:
            raise media_ai.RateLimited(12.5)
        return tree()(raw, mime, caption)

    monkeypatch.setattr(media_ai, "analyze_photo", flaky)
    with TestClient(main.app) as c:  # keeps the server loop (and the queue worker) alive
        r = c.post("/api/v1/field/photo", files={"file": ("t.jpg", jpeg(), "image/jpeg")},
                   data={"lat": LAT, "lon": LON}).json()
        assert r["ai_status"] == "queued" and r["suggestion"] is None  # upload answered at once
        for _ in range(100):
            if c.get("/api/v1/field/suggestions").json():
                break
            time.sleep(0.05)
        sug = c.get("/api/v1/field/suggestions").json()
        assert sug and sug[0]["event_id"] == r["event_id"]
        assert calls["n"] == 3 and waits == [13.5, 13.5]
        e = next(x for x in c.get("/api/v1/feed").json() if x["event_id"] == r["event_id"])
        assert e["payload"]["ai_status"] == "done"
        assert c.get("/api/v1/field/queue").json()["photos_waiting"] == 0


def test_rate_limit_wait_is_read_from_groq_message():
    class R:
        headers: dict = {}
        text = '{"error":{"message":"Rate limit reached ... Please try again in 1m2.5s. Need more tokens?"}}'
    assert media_ai._wait_hint(R()) == 62.5


# ---------- every photo / voice / message must reach the incident list (and the planner) ----------
def _dispatched_incident():
    r = client.post("/api/v1/events", json={"event_id": uuid.uuid4().hex, "kind": "sos", "lat": LAT, "lon": LON,
                                            "payload": {"type": "injured", "people": 1, "message": "accident"}}).json()
    amb = next(u for u in client.get("/api/responders").json() if u["kind"] == "ambulance" and u["status"] == "available")
    client.post(f"/api/incidents/{r['incident_id']}/approve", json={"officer": "T", "responder_id": amb["id"]})
    return r["incident_id"]


def test_photo_next_to_an_incident_already_handled_gets_its_own_incident(monkeypatch):
    monkeypatch.setattr(media_ai, "analyze_photo", tree(hazard="none", blocks=False))
    busy = _dispatched_incident()
    r = client.post("/api/v1/field/photo", files={"file": ("p.jpg", jpeg(), "image/jpeg")}, data={"lat": LAT, "lon": LON}).json()
    assert r["incident_id"] and r["incident_id"] != busy
    inc = client.get(f"/api/incidents/{r['incident_id']}").json()
    assert inc["status"] in ("new", "suggested")  # waiting: on the list and for the AI planner
    assert inc["reports"][0]["media"][0]["mime"].startswith("image/")  # the photo shows in the incident panel


def test_photo_next_to_a_waiting_incident_joins_it_and_shows_there(monkeypatch):
    monkeypatch.setattr(media_ai, "analyze_photo", tree(hazard="none", blocks=False))
    r0 = client.post("/api/v1/events", json={"event_id": uuid.uuid4().hex, "kind": "sos", "lat": LAT, "lon": LON,
                                             "payload": {"type": "trapped", "people": 3, "message": "fase hain"}}).json()
    r = client.post("/api/v1/field/photo", files={"file": ("p.jpg", jpeg(), "image/jpeg")},
                    data={"lat": LAT, "lon": LON + 0.0005}).json()
    assert r["incident_id"] == r0["incident_id"]
    reps = client.get(f"/api/incidents/{r0['incident_id']}").json()["reports"]
    assert any(m["mime"].startswith("image/") for rep in reps for m in rep["media"])


def test_voice_message_that_is_not_an_sos_still_becomes_an_incident_with_its_recording(monkeypatch):
    monkeypatch.setattr(media_ai, "transcribe", fake_stt("we have reached the school building", "english"))
    r = client.post("/api/v1/field/voice", files={"file": ("v.m4a", b"audio-bytes", "audio/mp4")},
                    data={"lat": LAT, "lon": LON}).json()
    assert r["incident_id"], r
    rep = client.get(f"/api/incidents/{r['incident_id']}").json()["reports"][0]
    assert rep["media"][0]["mime"].startswith("audio/") and rep["transcript"] == "we have reached the school building"


def test_photo_showing_people_in_danger_upgrades_its_own_incident(monkeypatch):
    monkeypatch.setattr(media_ai, "analyze_photo", tree(hazard="collapsed_structure", people=True, blocks=False))
    r = client.post("/api/v1/field/photo", files={"file": ("c.jpg", jpeg(), "image/jpeg")}, data={"lat": LAT, "lon": LON}).json()
    inc = client.get(f"/api/incidents/{r['incident_id']}").json()
    assert inc["type"] == "collapse" and inc["report_count"] == 1  # same incident, now typed (not a duplicate)


def test_photo_incidents_reach_the_ai_planner(monkeypatch):
    monkeypatch.setattr(media_ai, "analyze_photo", tree(hazard="none", blocks=False))
    _dispatched_incident()
    r = client.post("/api/v1/field/photo", files={"file": ("p.jpg", jpeg(), "image/jpeg")}, data={"lat": LAT, "lon": LON}).json()
    plan = client.post("/api/v1/agents/plan", json={"officer": "T"}).json()  # AI off here: rule planner, same inputs
    planned = {c["incident_id"] for c in plan.get("checked") or []} | {w["incident_id"] for w in plan["proposal"].get("waiting") or []}
    assert r["incident_id"] in planned


def test_message_without_location_stays_in_the_feed_only():
    client.post("/api/v1/events", json={"event_id": "noloc-1", "kind": "message", "payload": {"text": "hello"}})
    e = feed_item("noloc-1")
    assert e["incident_id"] is None and "no location" in e["handled_as"]
