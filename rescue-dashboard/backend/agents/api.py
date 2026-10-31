"""HTTP endpoints for the agents."""
from typing import Optional

from fastapi import APIRouter
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from agents import llm, triage, verifier

router = APIRouter(prefix="/api/v1/agents")


@router.get("/status")
def agent_status():
    """Which AI model is active, and whether the last call worked."""
    return llm.status()


class TriageIn(BaseModel):
    text: str
    role: Optional[str] = None


@router.post("/verify/{incident_id}")
async def run_verify(incident_id: int):
    """Run the Verifier Agent again for one incident (button on the dashboard)."""
    from v1 import _send
    out = await run_in_threadpool(verifier.verify, incident_id)
    await _send([("changed", {"verified": [incident_id]})])
    return out


@router.post("/triage")
async def try_triage(body: TriageIn):
    """Try the Triage Agent on any text (nothing is stored). Handy for testing and for judges."""
    return await run_in_threadpool(triage.read, body.text, body.role)


# ---------------------------------------------------------------- Dispatch Planner (LangGraph)
import asyncio  # noqa: E402

from fastapi import HTTPException  # noqa: E402

from agents import planner  # noqa: E402


class PlanIn(BaseModel):
    officer: str = "Duty Officer"


class DecideIn(BaseModel):
    approved_incident_ids: list[int] = []
    officer: str = "Duty Officer"


def _emitter(loop):
    import main as core

    def emit(step: dict) -> None:  # called from the worker thread; pushes each step live to dashboards
        asyncio.run_coroutine_threadsafe(core.hub.send("agent_step", step), loop)
    return emit


@router.post("/plan")
async def start_plan(body: PlanIn):
    """Run the Dispatch Planner until it pauses for the officer's approval."""
    return await run_in_threadpool(planner.start, body.officer, _emitter(asyncio.get_running_loop()))


@router.get("/plan/{run_id}")
def get_plan(run_id: str):
    out = planner.get(run_id)
    if out is None:
        raise HTTPException(404, "Unknown plan")
    return out


@router.post("/plan/{run_id}/decide")
async def decide_plan(run_id: str, body: DecideIn):
    """The officer approves some, all or none of the plan. Only then do units move."""
    from v1 import _send
    try:
        out = await run_in_threadpool(planner.resume, run_id, body.approved_incident_ids, body.officer,
                                      _emitter(asyncio.get_running_loop()))
    except KeyError:
        raise HTTPException(404, "Unknown plan")
    await _send([tuple(n) for n in out.pop("notes", [])] + [("changed", {"plan": run_id})])
    return out


# ---------------------------------------------------------------- Route Watch Agent
from agents import route_watch  # noqa: E402


class AlertDecision(BaseModel):
    approve: bool
    officer: str = "Duty Officer"


@router.get("/route-alerts")
def list_route_alerts(limit: int = 30):
    """Recent Route Watch alerts (pending ones need the officer)."""
    return route_watch.alerts(limit)


@router.post("/route-alerts/{alert_id}/decide")
async def decide_route_alert(alert_id: int, body: AlertDecision):
    from v1 import _send
    try:
        notes = await run_in_threadpool(route_watch.decide, alert_id, body.approve, body.officer)
    except KeyError:
        raise HTTPException(404, "Unknown alert")
    await _send([tuple(n) for n in notes] + [("changed", {"route_alert": alert_id})])
    return {"ok": True, "notes": len(notes)}


# ---------------------------------------------------------------- Commander Assistant (ReAct) + SITREP
from agents import commander  # noqa: E402


class AskIn(BaseModel):
    question: str
    history: list[dict] = []
    officer: str = "Duty Officer"


class SitrepIn(BaseModel):
    officer: str = "Duty Officer"


@router.post("/ask")
async def ask_commander(body: AskIn):
    """Ask the Commander Assistant about the live situation. Read-only: it never changes anything."""
    from v1 import _send
    out = await run_in_threadpool(commander.ask, body.question, body.history, body.officer)
    await _send([("changed", {"commander": True})])
    return out


@router.post("/sitrep")
async def make_sitrep(body: SitrepIn):
    """Situation report: numbers counted by code, words by AI (checked by code)."""
    from v1 import _send
    out = await run_in_threadpool(commander.sitrep, body.officer)
    await _send([("changed", {"sitrep": True})])
    return out
