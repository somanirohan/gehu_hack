"""Check the AI connection:   python -m agents.check   (run inside backend/)"""
from pydantic import BaseModel, Field

from agents import llm


class Probe(BaseModel):
    emergency_type: str = Field(description="one word, e.g. trapped, flood, fire, medical")
    people: int = Field(description="number of people mentioned")


def main() -> None:
    p = llm.provider()
    if not p:
        print("NO AI KEY FOUND. Put GROQ_API_KEY=... or GEMINI_API_KEY=... in backend/.env")
        print("(The system still works with the word rules.)")
        return
    print(f"Provider: {p}   Model: {llm.model_name()}")
    print("Asking the AI to read: 'Bachao! 3 log chhat par fase hain, paani badh raha' ...")
    r = llm.structured(Probe, "You read disaster SOS messages written in Hindi, English or Hinglish.",
                       "Bachao! 3 log chhat par fase hain, paani badh raha")
    st = llm.status()["last_call"]
    if r is None:
        print("FAILED:", st["error"])
        print("Check: key copied fully? internet on? If it says the model is not found or decommissioned,")
        print("add GROQ_MODEL=<a model from console.groq.com/docs/models> (or GEMINI_MODEL=...) to backend/.env")
        return
    print(f"AI CONNECTED in {st['latency_ms']} ms -> type={r.emergency_type}, people={r.people}")


if __name__ == "__main__":
    main()
