"""Forward the mesh app's AI chatbot to the disaster chatbot server (ai-surveillance/disaster_api_server.py).

Why: phones reach this backend through ONE https address (the Cloudflare tunnel). Android blocks
plain http:// by default, and the chatbot server runs on another port (8800), so the phone could not
reach it directly. With this proxy the app's chatbot uses the same https address as Sync:

    app  --https-->  tunnel  -->  this backend :8001 /api/chat  -->  chatbot server :8800 /api/chat

CHATBOT_URL (env) points at the chatbot server; default http://127.0.0.1:8800.
"""
from __future__ import annotations

import os
from typing import Optional

import httpx
from fastapi import APIRouter, Header, HTTPException, Request

router = APIRouter()
TIMEOUT_S = 45.0  # the chatbot may check the topic, then answer


def _target() -> str:
    return os.environ.get("CHATBOT_URL", "http://127.0.0.1:8800").rstrip("/")


@router.post("/api/chat")
async def chat(request: Request, x_groq_api_key: Optional[str] = Header(None, alias="X-Groq-Api-Key")):
    body = await request.body()
    headers = {"Content-Type": "application/json"}
    if x_groq_api_key:
        headers["X-Groq-Api-Key"] = x_groq_api_key
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S) as c:
            r = await c.post(f"{_target()}/api/chat", content=body, headers=headers)
    except httpx.HTTPError:
        raise HTTPException(503, "The AI chatbot server is not running. Start it with run.ps1 "
                                 "(or: python disaster_api_server.py in ai-surveillance).")
    try:
        data = r.json()
    except ValueError:
        raise HTTPException(502, f"Chatbot server answered HTTP {r.status_code} without JSON")
    if r.status_code >= 400:
        raise HTTPException(r.status_code, data.get("detail") if isinstance(data, dict) else str(data))
    return data


@router.get("/health")
async def chatbot_health():
    """The app's 'Test connection' calls <server>/health."""
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get(f"{_target()}/health")
        return {**r.json(), "via": "rescue-dashboard proxy"}
    except Exception:
        raise HTTPException(503, "The AI chatbot server is not running")
