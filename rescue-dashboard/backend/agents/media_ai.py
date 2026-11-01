"""Speech-to-text and photo reading for voice notes and photos from the field.

Uses the same keys as agents/llm.py (backend/.env), called over plain HTTPS so no
extra SDK is needed:
    GROQ_API_KEY    -> Whisper large-v3 (speech) + a Llama 4 vision model (photos)
    GEMINI_API_KEY  -> Gemini (speech and photos), used when Groq is missing or fails
Optional overrides:
    GROQ_STT_MODEL=whisper-large-v3
    GROQ_VISION_MODEL=<force one model; otherwise the first available from VISION_PREFERENCE>
    GROQ_TEXT_MODEL=<model for translation; defaults to GROQ_MODEL / llm default>
    GEMINI_MEDIA_MODEL=gemini-2.5-flash
    AI_DISABLED=1   (everything below returns None; callers keep the raw audio/photo)

Local languages: Whisper and Gemini handle Hindi, Bengali, Marathi, Tamil, Telugu,
Gujarati, Kannada, Malayalam, Punjabi, Urdu, Nepali and English. Garhwali/Kumaoni
have no dedicated model; they usually come out as Hindi/Nepali text, which the
translation step still turns into English.

Every function returns None instead of raising, so a failed AI call never loses a report.
"""
from __future__ import annotations

import base64
import json
import os
import re
import time
from typing import Any, Optional

from agents import llm

GROQ_BASE = "https://api.groq.com/openai/v1"
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
TIMEOUT_S = float(os.environ.get("MEDIA_AI_TIMEOUT", "45"))

last_error: dict[str, Any] = {"error": None, "at": None}


def _key(name: str) -> str:
    return os.environ.get(name, "").strip()


def enabled() -> bool:
    return os.environ.get("AI_DISABLED") != "1" and bool(_key("GROQ_API_KEY") or _key("GEMINI_API_KEY"))


def _fail(where: str, exc: Exception) -> None:
    last_error.update(error=f"{where}: {type(exc).__name__}: {str(exc)[:240]}", at=time.strftime("%Y-%m-%dT%H:%M:%S"))


def _client():
    import httpx
    return httpx.Client(timeout=TIMEOUT_S)


def _json_from(text: str) -> Optional[dict]:
    """Models sometimes wrap JSON in ``` fences or add a sentence; take the first {...} block."""
    if not text:
        return None
    try:
        return json.loads(text)
    except ValueError:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except ValueError:
                return None
    return None


# Groq retires and adds models often; use the first of these the account can see.
VISION_PREFERENCE = ["qwen/qwen3.8-27b", "meta-llama/llama-4-scout-17b-16e-instruct",
                     "meta-llama/llama-4-maverick-17b-128e-instruct"]
_groq_models: dict[str, Any] = {"ids": None, "at": 0.0}


def _groq_vision_model() -> str:
    forced = os.environ.get("GROQ_VISION_MODEL", "").strip()
    if forced:
        return forced
    if _groq_models["ids"] is None or time.time() - _groq_models["at"] > 3600:
        try:
            with _client() as c:
                r = c.get(f"{GROQ_BASE}/models", headers={"Authorization": f"Bearer {_key('GROQ_API_KEY')}"})
            r.raise_for_status()
            _groq_models.update(ids={m["id"] for m in r.json().get("data", [])}, at=time.time())
        except Exception as exc:
            _fail("groq-models", exc)
            _groq_models.update(ids=set(), at=time.time())
    return next((m for m in VISION_PREFERENCE if m in _groq_models["ids"]), VISION_PREFERENCE[0])


# ---------- low-level calls ----------
class RateLimited(Exception):
    """The AI provider said "too many requests"; `wait` is how many seconds it asked for."""

    def __init__(self, wait: float, where: str = ""):
        super().__init__(f"rate limited{(' (' + where + ')') if where else ''}: try again in {wait:.0f}s")
        self.wait = wait


def _wait_hint(r) -> float:
    """Seconds to wait from a 429: Retry-After header, else Groq's 'try again in 12.3s' text."""
    try:
        return float(r.headers.get("retry-after"))
    except (TypeError, ValueError):
        pass
    m = re.search(r"try again in (?:(\d+)m)?([\d.]+)s", r.text or "")
    if m:
        return int(m.group(1) or 0) * 60 + float(m.group(2))
    return 20.0


def _post(client, url: str, **kw):
    """POST with one short retry on a rate limit (429). If still limited, raises RateLimited so
    the caller can queue the work instead of losing it."""
    r = client.post(url, **kw)
    if r.status_code == 429:
        wait = _wait_hint(r)
        if wait <= 8:
            time.sleep(max(0.5, wait))
            r = client.post(url, **kw)
        if r.status_code == 429:
            raise RateLimited(_wait_hint(r), url.rsplit("/", 1)[-1])
    r.raise_for_status()
    return r


def _groq_chat(messages: list, model: str, want_json: bool, max_tokens: int = 800) -> Optional[str]:
    # max_tokens matters on the free tier: Groq counts the reserved reply length against the
    # per-minute token limit, so an unset (huge) default exhausts it after one photo.
    body: dict[str, Any] = {"model": model, "messages": messages, "temperature": 0, "max_tokens": max_tokens}
    if want_json:
        body["response_format"] = {"type": "json_object"}
    with _client() as c:
        r = _post(c, f"{GROQ_BASE}/chat/completions", json=body,
                  headers={"Authorization": f"Bearer {_key('GROQ_API_KEY')}"})
    return r.json()["choices"][0]["message"]["content"]


def _gemini(parts: list, want_json: bool) -> Optional[str]:
    model = os.environ.get("GEMINI_MEDIA_MODEL") or os.environ.get("GEMINI_MODEL") or "gemini-2.5-flash"
    body: dict[str, Any] = {"contents": [{"role": "user", "parts": parts}],
                            "generationConfig": {"temperature": 0}}
    if want_json:
        body["generationConfig"]["responseMimeType"] = "application/json"
    with _client() as c:
        r = _post(c, f"{GEMINI_BASE}/{model}:generateContent", json=body,
                  headers={"x-goog-api-key": _key("GEMINI_API_KEY")})
    cand = r.json().get("candidates") or [{}]
    return "".join(p.get("text", "") for p in cand[0].get("content", {}).get("parts", []))


# ---------- speech to text ----------
def transcribe(raw: bytes, filename: str, mime: str, language: Optional[str] = None) -> Optional[dict]:
    """Audio -> {"text", "language", "model"} in the speaker's own language and script."""
    if not enabled() or not raw:
        return None
    if _key("GROQ_API_KEY"):
        model = os.environ.get("GROQ_STT_MODEL", "whisper-large-v3")
        try:
            data = {"model": model, "response_format": "verbose_json", "temperature": "0"}
            if language:
                data["language"] = language
            with _client() as c:
                r = _post(c, f"{GROQ_BASE}/audio/transcriptions", data=data,
                          files={"file": (filename or "voice.m4a", raw, mime or "application/octet-stream")},
                          headers={"Authorization": f"Bearer {_key('GROQ_API_KEY')}"})
            j = r.json()
            text = (j.get("text") or "").strip()
            if text:
                return {"text": text, "language": (j.get("language") or language or "unknown"), "model": f"Groq · {model}"}
        except Exception as exc:  # fall through to Gemini
            _fail("groq-stt", exc)
    if _key("GEMINI_API_KEY"):
        try:
            hint = f" The speaker is probably using language code '{language}'." if language else ""
            out = _gemini([
                {"inline_data": {"mime_type": mime or "audio/mpeg", "data": base64.b64encode(raw).decode()}},
                {"text": "Transcribe this emergency voice message exactly as spoken, in the speaker's own language "
                         "and script (Devanagari for Hindi/Garhwali/Kumaoni etc.). Do not translate or summarise."
                         + hint + ' Reply as JSON: {"text": "...", "language": "<language name in English>"}'},
            ], want_json=True)
            j = _json_from(out or "")
            if j and (j.get("text") or "").strip():
                return {"text": j["text"].strip(), "language": j.get("language") or "unknown", "model": "Gemini"}
        except Exception as exc:
            _fail("gemini-stt", exc)
    return None


def is_english(language: Optional[str]) -> bool:
    return (language or "").strip().lower() in ("en", "english")


def translate_en(text: str, language: Optional[str]) -> Optional[str]:
    """Any language -> one plain English version for the officer and the triage rules."""
    if not text or is_english(language):
        return text or None
    if not enabled():
        return None
    system = ("Translate this emergency message from an Indian disaster area into plain English. "
              "Keep place names, numbers and people counts exactly. Output only the translation.")
    if _key("GROQ_API_KEY"):
        try:
            model = os.environ.get("GROQ_TEXT_MODEL") or (llm.model_name() if llm.provider() == "groq" else None) \
                or llm.DEFAULT_MODELS["groq"]
            out = _groq_chat([{"role": "system", "content": system}, {"role": "user", "content": text}], model, False)
            if out and out.strip():
                return out.strip()
        except Exception as exc:
            _fail("groq-translate", exc)
    if _key("GEMINI_API_KEY"):
        try:
            out = _gemini([{"text": f"{system}\n\n{text}"}], want_json=False)
            if out and out.strip():
                return out.strip()
        except Exception as exc:
            _fail("gemini-translate", exc)
    return None


# ---------- photos ----------
HAZARDS = ["fallen_tree", "landslide", "flooded_road", "collapsed_structure", "damaged_bridge",
           "power_line_down", "fire", "vehicle_accident", "debris", "none"]

PHOTO_PROMPT = (
    "You are helping a disaster control room in Uttarakhand, India. Look at this photo sent from the field "
    "and decide whether it shows something that blocks or endangers a road.\n"
    f"hazard must be one of: {', '.join(HAZARDS)}.\n"
    "blocks_road = true only if vehicles clearly cannot pass safely.\n"
    "people_in_danger = true only if people are visibly trapped, injured or in immediate danger.\n"
    "Reply as JSON only: {\"hazard\": \"...\", \"blocks_road\": true/false, \"people_in_danger\": true/false, "
    "\"confidence\": 0.0-1.0, \"description\": \"one short English sentence\", "
    "\"suggested_radius_m\": 30-300}"
)


def _shrink(raw: bytes, mime: str, max_side: int = 1024) -> tuple[bytes, str]:
    """Phone photos are 3–8 MB; a 1024 px JPEG is plenty to spot a fallen tree and keeps the
    request small (fewer image tokens, under free-tier rate limits, faster on slow links)."""
    try:
        import io
        from PIL import Image, ImageOps
        im = ImageOps.exif_transpose(Image.open(io.BytesIO(raw)))
        im.thumbnail((max_side, max_side))
        buf = io.BytesIO()
        im.convert("RGB").save(buf, "JPEG", quality=82)
        return buf.getvalue(), "image/jpeg"
    except Exception:
        return raw, (mime if (mime or "").startswith("image/") else "image/jpeg")


def analyze_photo(raw: bytes, mime: str, caption: str = "", raise_rate_limit: bool = False) -> Optional[dict]:
    """Photo -> {"hazard", "blocks_road", "people_in_danger", "confidence", "description", "radius_m", "model"}.

    raise_rate_limit=True: if every provider is rate-limited, raise RateLimited (the photo queue
    waits and retries) instead of returning None."""
    if not enabled() or not raw:
        return None
    prompt = PHOTO_PROMPT + (f"\nThe sender wrote: \"{caption[:300]}\"" if caption else "")
    raw, mime = _shrink(raw, mime)
    b64 = base64.b64encode(raw).decode()
    out, model = None, None
    limited: Optional[RateLimited] = None
    if _key("GROQ_API_KEY"):
        model = _groq_vision_model()
        try:
            out = _groq_chat([{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
            ]}], model, True, max_tokens=300)
            model = f"Groq · {model}"
        except RateLimited as exc:
            _fail("groq-vision", exc)
            limited, out = exc, None
        except Exception as exc:
            _fail("groq-vision", exc)
            out = None
    if out is None and _key("GEMINI_API_KEY"):
        try:
            out = _gemini([{"inline_data": {"mime_type": mime, "data": b64}}, {"text": prompt}], want_json=True)
            model = "Gemini"
            limited = None
        except RateLimited as exc:
            _fail("gemini-vision", exc)
            limited = exc if limited is None or exc.wait < limited.wait else limited
            out = None
        except Exception as exc:
            _fail("gemini-vision", exc)
            out = None
    if out is None and limited is not None and raise_rate_limit:
        raise limited
    j = _json_from(out or "")
    if not j:
        return None
    hazard = str(j.get("hazard") or "none").strip().lower().replace(" ", "_")
    if hazard not in HAZARDS:
        hazard = "debris" if j.get("blocks_road") else "none"
    try:
        conf = max(0.0, min(1.0, float(j.get("confidence") or 0)))
    except (TypeError, ValueError):
        conf = 0.0
    try:
        radius = max(30.0, min(300.0, float(j.get("suggested_radius_m") or 60)))
    except (TypeError, ValueError):
        radius = 60.0
    return {"hazard": hazard, "blocks_road": bool(j.get("blocks_road")), "people_in_danger": bool(j.get("people_in_danger")),
            "confidence": round(conf, 2), "description": str(j.get("description") or "")[:240], "radius_m": radius,
            "model": model}
