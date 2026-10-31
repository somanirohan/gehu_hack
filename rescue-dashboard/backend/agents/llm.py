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
import time
from pathlib import Path
from typing import Any, Optional, Type

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:  # python-dotenv not installed: plain environment variables still work
    pass

TIMEOUT_S = float(os.environ.get("AI_TIMEOUT", "12"))
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


def structured(schema: Type, system: str, user: str):
    """Ask the model for an answer in a fixed Pydantic schema. Returns an instance or None."""
    m = chat_model()
    if m is None:
        return None
    started = time.time()
    try:
        out = m.with_structured_output(schema).invoke([("system", system), ("human", user)])
        _record(True, started)
        return out
    except Exception as exc:  # network, quota, bad output: caller falls back to rules
        _record(False, started, f"{type(exc).__name__}: {str(exc)[:300]}")
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
