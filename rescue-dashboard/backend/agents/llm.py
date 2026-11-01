"""One place that decides which AI model to use.

Put ONE of these in backend/.env (never commit that file):
    GROQ_API_KEY=...        (free: console.groq.com)
    GEMINI_API_KEY=...      (free: aistudio.google.com)
Optional:
    GROQ_MODEL=openai/gpt-oss-120b     GEMINI_MODEL=gemini-2.5-flash
    AI_DISABLED=1          (force the rule-based fallback, e.g. to show offline mode)

If no key, no internet, a timeout or any error: callers get None and use the rules.
"""
from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Any, Optional, Type

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:  # python-dotenv not installed: plain environment variables still work
    pass

TIMEOUT_S = float(os.environ.get("AI_TIMEOUT", "12"))
MAX_PATIENT_WAIT_S = float(os.environ.get("AI_MAX_WAIT", "60"))
DEFAULT_MODELS = {"groq": "openai/gpt-oss-120b", "gemini": "gemini-2.5-flash"}

_model_cache: dict = {}
_last: dict[str, Any] = {"ok": None, "error": None, "latency_ms": None, "at": None}


def provider() -> Optional[str]:
    if os.environ.get("AI_DISABLED") == "1":
        return None
    if os.environ.get("GROQ_API_KEY", "").strip():
        return "groq"
    if os.environ.get("GEMINI_API_KEY", "").strip():
        return "gemini"
    return None


def model_name() -> Optional[str]:
    p = provider()
    if p == "groq":
        return os.environ.get("GROQ_MODEL") or DEFAULT_MODELS["groq"]
    if p == "gemini":
        return os.environ.get("GEMINI_MODEL") or DEFAULT_MODELS["gemini"]
    return None


def label() -> str:
    """What the dashboard shows as the source of an AI result."""
    p = provider()
    return f"AI suggestion ({'Groq' if p == 'groq' else 'Gemini'} · {model_name()})" if p else "rule suggestion"


def chat_model():
    """LangChain chat model, or None when AI is unavailable."""
    p, name = provider(), model_name()
    if not p:
        return None
    key = (p, name)
    if key not in _model_cache:
        if p == "groq":
            from langchain_groq import ChatGroq
            _model_cache[key] = ChatGroq(model=name, temperature=0, timeout=TIMEOUT_S, max_retries=1,
                                         api_key=os.environ["GROQ_API_KEY"].strip())
        else:
            from langchain_google_genai import ChatGoogleGenerativeAI
            _model_cache[key] = ChatGoogleGenerativeAI(model=name, temperature=0, timeout=TIMEOUT_S, max_retries=1,
                                                       google_api_key=os.environ["GEMINI_API_KEY"].strip())
    return _model_cache[key]


def _record(ok: bool, started: float, error: Optional[str] = None) -> None:
    _last.update(ok=ok, error=error, latency_ms=round((time.time() - started) * 1000),
                 at=time.strftime("%Y-%m-%dT%H:%M:%S"))


def _rate_limit_wait(err: str) -> Optional[float]:
    """Seconds Groq/Gemini asks us to wait, if this error is a rate limit (429); else None."""
    low = err.lower()
    if "ratelimit" not in low.replace(" ", "") and "429" not in low and "rate limit" not in low:
        return None
    m = re.search(r"try again in (?:(\d+)m)?([\d.]+)s", err)
    return (int(m.group(1) or 0) * 60 + float(m.group(2))) if m else 10.0


def structured(schema: Type, system: str, user: str, patient: bool = False):
    """Ask the model for an answer in a fixed Pydantic schema. Returns an instance or None.

    patient=True (for work nobody is waiting on, e.g. the Verifier after the SOS is shown):
    on a rate limit, wait what the provider asks (up to MAX_PATIENT_WAIT_S in total) and retry,
    instead of falling back to the rules at once."""
    m = chat_model()
    if m is None:
        return None
    started = time.time()
    messages = [("system", system), ("human", user)]
    fixed_once, waited = False, 0.0
    while True:
        try:
            out = m.with_structured_output(schema).invoke(messages)
            _record(True, started)
            return out
        except Exception as exc:  # network, quota, bad output: caller falls back to rules
            err = f"{type(exc).__name__}: {str(exc)[:300]}"
            # The model sometimes fills a field with a value outside the allowed list; Groq then
            # rejects the answer ("tool call validation failed"). One retry, with a reminder, fixes
            # most of these (seen live: ~1 in 8 messages in a burst).
            low = err.lower()
            bad_output = "validation failed" in low or "did not match schema" in low or "failed to call a function" in low
            if bad_output and not fixed_once:
                fixed_once = True
                messages = [("system", system + "\nUse ONLY the allowed values for every field; leave a field empty if unsure."),
                            ("human", user)]
                continue
            wait = _rate_limit_wait(err) if patient else None
            if wait is not None and waited + wait <= MAX_PATIENT_WAIT_S:
                time.sleep(wait + 0.5)
                waited += wait + 0.5
                continue
            _record(False, started, err)
            return None


def text(system: str, user: str) -> Optional[str]:
    m = chat_model()
    if m is None:
        return None
    started = time.time()
    try:
        out = m.invoke([("system", system), ("human", user)])
        _record(True, started)
        return out.content if isinstance(out.content, str) else str(out.content)
    except Exception as exc:
        _record(False, started, f"{type(exc).__name__}: {str(exc)[:300]}")
        return None


def status() -> dict:
    return {"provider": provider(), "model": model_name(), "label": label(), "last_call": dict(_last)}
