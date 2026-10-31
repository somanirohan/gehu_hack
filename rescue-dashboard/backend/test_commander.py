"""Commander Assistant + SITREP with a FAKE model (no key, no internet needed)."""
import os
import tempfile

os.environ.setdefault("RESCUE_DB", os.path.join(tempfile.mkdtemp(), "commander.db"))
os.environ["USE_OSRM"] = "0"

from fastapi.testclient import TestClient  # noqa: E402
from langchain_core.language_models.chat_models import BaseChatModel  # noqa: E402
from langchain_core.messages import AIMessage  # noqa: E402
from langchain_core.outputs import ChatGeneration, ChatResult  # noqa: E402

import main  # noqa: E402
import routing  # noqa: E402
from agents import commander, llm  # noqa: E402

client = TestClient(main.app)
DDN = (30.3165, 78.0322)


def report(i, typ="trapped", people=3, msg="help"):
    return {"external_id": f"c{i}", "source": "manual", "type": typ, "message": msg,
            "lat": DDN[0] + i * 0.01, "lon": DDN[1], "people": people}


class FakeReAct(BaseChatModel):
    """First turn: call list_incidents(waiting). Second turn: answer, mentioning a real and a fake id."""
    answer: str = "Waiting: #1. Also #999."

    @property
    def _llm_type(self):
        return "fake"

    def bind_tools(self, tools, **kw):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kw):
        if any(getattr(m, "type", "") == "tool" for m in messages):
            msg = AIMessage(content=self.answer)
        else:
            msg = AIMessage(content="", tool_calls=[{"name": "list_incidents", "args": {"which": "waiting"}, "id": "t1"}])
        return ChatResult(generations=[ChatGeneration(message=msg)])


_real_chat, _real_structured = llm.chat_model, llm.structured


def setup_function():
    routing.set_network(routing.RoadNetwork.grid(*DDN, rows=16, cols=16, spacing_m=220))
    client.post("/api/demo/reset")
    client.post("/api/reports", json=report(1))
    client.post("/api/reports", json=report(2, "fire", 2))


def teardown_function():
    llm.chat_model, llm.structured = _real_chat, _real_structured
    os.environ.pop("GROQ_API_KEY", None)


def test_rule_answers_without_ai():
    r = client.post("/api/v1/agents/ask", json={"question": "which incidents have no unit?"}).json()
    assert r["source"].startswith("rule")
    assert "#1" in r["answer"] and "#2" in r["answer"]
    r = client.post("/api/v1/agents/ask", json={"question": "boat kahan hai?"}).json()
    assert "boat" in r["answer"].lower()
    r = client.post("/api/v1/agents/ask", json={"question": "#2"}).json()
    assert "fire" in r["answer"]
    r = client.post("/api/v1/agents/ask", json={"question": "any road blocked?"}).json()
    assert "No road" in r["answer"]


def test_react_agent_uses_tools_and_ids_are_checked():
    llm.chat_model = lambda: FakeReAct()
    r = client.post("/api/v1/agents/ask", json={"question": "what is waiting?"}).json()
    assert r["tools"] == ["list_incidents"]
    assert "#1" in r["answer"]
    assert r["bad_ids"] == [999] and "Safety check" in r["answer"]
    log = client.get("/api/log").json()
    assert any(e["action"] == "commander_asked" for e in log)


def test_sitrep_rules_and_numbers_from_code():
    r = client.post("/api/v1/agents/sitrep", json={"officer": "DM Office"}).json()
    f = r["facts"]["figures"]
    assert f["open_incidents"] == 2 and f["people_affected"] == 5
    assert r["source"] == "rule text"
    assert "SITUATION REPORT" in r["markdown"] and "Prepared by DM Office" in r["markdown"]


def test_sitrep_drops_invented_numbers():
    os.environ["GROQ_API_KEY"] = "test"
    llm.structured = lambda schema, system, user: commander.SitrepText(
        headline="2 open incidents.", situation="Two incidents are open.",
        concerns=["#1 trapped needs a unit.", "4000 people are missing."],
        actions=["Approve a unit for #1.", "Send 77 boats."])
    r = client.post("/api/v1/agents/sitrep", json={}).json()
    assert r["removed_lines"] == 2
    assert r["text"]["concerns"] == ["#1 trapped needs a unit."]
    assert r["text"]["actions"] == ["Approve a unit for #1."]
