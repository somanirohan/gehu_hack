"""The mesh app's chatbot goes through this backend (same https tunnel as Sync) to the chatbot server."""
import os
import tempfile

os.environ["RESCUE_DB"] = os.path.join(tempfile.mkdtemp(), "chat.db")
os.environ["USE_OSRM"] = "0"

import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import chat_proxy  # noqa: E402
import main  # noqa: E402

client = TestClient(main.app)
REAL_ASYNC_CLIENT = httpx.AsyncClient


def fake_chatbot(handler):
    """Replace the outgoing HTTP client with one that answers from `handler` (no network)."""
    def make(*a, **kw):
        kw["transport"] = httpx.MockTransport(handler)
        return REAL_ASYNC_CLIENT(*a, **kw)
    return make


def test_chat_is_forwarded_with_the_body_and_optional_key(monkeypatch):
    seen = {}

    def handler(req: httpx.Request):
        seen["url"], seen["body"], seen["key"] = str(req.url), req.content, req.headers.get("X-Groq-Api-Key")
        return httpx.Response(200, json={"answer": "Move to high ground", "provider": "Groq"})

    monkeypatch.setenv("CHATBOT_URL", "http://chatbot.test:8800")
    monkeypatch.setattr(chat_proxy.httpx, "AsyncClient", fake_chatbot(handler))
    r = client.post("/api/chat", json={"query": "baadh aa gayi", "language": "hi"}, headers={"X-Groq-Api-Key": "k1"})
    assert r.status_code == 200 and r.json()["answer"] == "Move to high ground"
    assert seen["url"] == "http://chatbot.test:8800/api/chat" and b"baadh" in seen["body"] and seen["key"] == "k1"


def test_chatbot_down_gives_a_clear_503(monkeypatch):
    def handler(req):
        raise httpx.ConnectError("refused", request=req)

    monkeypatch.setattr(chat_proxy.httpx, "AsyncClient", fake_chatbot(handler))
    r = client.post("/api/chat", json={"query": "help"})
    assert r.status_code == 503 and "not running" in r.json()["detail"]
    assert client.get("/health").status_code == 503


def test_health_passes_through(monkeypatch):
    monkeypatch.setattr(chat_proxy.httpx, "AsyncClient",
                        fake_chatbot(lambda req: httpx.Response(200, json={"status": "healthy"})))
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "healthy" and r.json()["via"] == "rescue-dashboard proxy"


def test_dashboard_and_api_still_served():
    assert client.get("/api/health").status_code == 200
