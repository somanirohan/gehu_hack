"""llm.structured retries once when the model's answer doesn't fit the schema (seen live with Groq)."""
from pydantic import BaseModel

from agents import llm


class Out(BaseModel):
    kind: str


class FakeModel:
    def __init__(self, errors):
        self.errors = list(errors)
        self.calls = 0

    def with_structured_output(self, schema):
        return self

    def invoke(self, messages):
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return Out(kind="sos")


def test_retries_once_on_schema_validation_failure(monkeypatch):
    m = FakeModel([RuntimeError("Error code: 400 - Tool call validation failed: parameters for tool Triage did not match schema")])
    monkeypatch.setattr(llm, "chat_model", lambda: m)
    assert llm.structured(Out, "sys", "user").kind == "sos"
    assert m.calls == 2


def test_gives_up_after_second_schema_failure(monkeypatch):
    err = RuntimeError("Tool call validation failed")
    m = FakeModel([err, err])
    monkeypatch.setattr(llm, "chat_model", lambda: m)
    assert llm.structured(Out, "sys", "user") is None
    assert m.calls == 2


def test_no_retry_for_other_errors(monkeypatch):
    m = FakeModel([ConnectionError("network down")])
    monkeypatch.setattr(llm, "chat_model", lambda: m)
    assert llm.structured(Out, "sys", "user") is None
    assert m.calls == 1  # network errors are retried inside the client already; don't double the wait


RATE = RuntimeError("RateLimitError: Error code: 429 - Rate limit reached for model `openai/gpt-oss-120b`. "
                    "Please try again in 7.5s. Need more tokens?")


def test_patient_call_waits_out_a_rate_limit(monkeypatch):
    slept = []
    monkeypatch.setattr(llm.time, "sleep", lambda s: slept.append(s))
    m = FakeModel([RATE])
    monkeypatch.setattr(llm, "chat_model", lambda: m)
    assert llm.structured(Out, "sys", "user", patient=True).kind == "sos"
    assert slept == [8.0] and m.calls == 2


def test_impatient_call_falls_back_at_once(monkeypatch):
    slept = []
    monkeypatch.setattr(llm.time, "sleep", lambda s: slept.append(s))
    m = FakeModel([RATE])
    monkeypatch.setattr(llm, "chat_model", lambda: m)
    assert llm.structured(Out, "sys", "user") is None  # e.g. Triage: the phone is waiting
    assert slept == [] and m.calls == 1


def test_patient_call_gives_up_after_the_wait_budget(monkeypatch):
    slept = []
    monkeypatch.setattr(llm.time, "sleep", lambda s: slept.append(s))
    monkeypatch.setattr(llm, "MAX_PATIENT_WAIT_S", 20.0)
    m = FakeModel([RATE, RATE, RATE, RATE])
    monkeypatch.setattr(llm, "chat_model", lambda: m)
    assert llm.structured(Out, "sys", "user", patient=True) is None
    assert sum(slept) <= 20.0 and m.calls == 3
