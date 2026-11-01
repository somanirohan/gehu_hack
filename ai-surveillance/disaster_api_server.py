"""Disaster Management API Server powered by Groq AI with Strict Safety Guardrails.

Provides high-speed, reliable disaster assistance:
- POST /api/chat: Guardrail validation -> SQLite protocol retrieval -> Groq LLM inference.
- POST /api/guardrail/check: Standalone topic classification endpoint.
- GET /health: Health status and Groq readiness.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
import uvicorn
from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Reconfigure stdout/stderr for Unicode safety on Windows consoles
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

try:
    from dotenv import load_dotenv
    load_dotenv(CURRENT_DIR / ".env")
except ImportError:
    pass

from rag.sqlite_store import DisasterSQLiteStore

# Groq Configuration
DEFAULT_GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b")
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

app = FastAPI(
    title="ResQMesh Disaster AI API (Groq)",
    description="Groq-powered Emergency Disaster Response API with strict safety guardrails",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    query: Optional[str] = None
    message: Optional[str] = None
    messages: Optional[List[ChatMessage]] = None
    language: Optional[str] = "en"
    max_tokens: Optional[int] = 350
    temperature: Optional[float] = 0.2
    groq_api_key: Optional[str] = None


# --- Strict Disaster Safety Guardrails ---

DISASTER_ALLOWLIST_KEYWORDS = [
    # General Emergency
    "emergency", "disaster", "crisis", "survive", "survival", "rescue", "evacuate",
    "evacuation", "shelter", "sos", "hazard", "danger", "trapped", "help", "safe",
    "safety", "distress", "staging", "relief", "beacon", "first aid", "first-aid",
    
    # Structural & Geological
    "earthquake", "collapse", "rubble", "tremor", "aftershock", "building collapse",
    "landslide", "mudslide", "rockfall", "avalanche", "debris", "structure", "geophone",
    "falling debris", "under rubble",
    
    # Weather & Hydrological
    "flood", "flooding", "flash flood", "water surge", "water purification", "purify water",
    "cyclone", "hurricane", "storm", "typhoon", "tornado", "gale", "eye of storm",
    "tsunami", "high ground", "drown", "drowning", "drinking water",
    
    # Thermal & Fire
    "fire", "wildfire", "smoke", "smoke inhalation", "burn", "burns", "flames", "extinguisher",
    "gas leak", "electrical shock", "downed power lines",
    
    # Medical First Aid
    "bleed", "bleeding", "severe bleeding", "blood", "tourniquet", "fracture", "broken bone",
    "splint", "cpr", "choking", "unconscious", "shock", "hypothermia", "heatstroke",
    "wound", "bandage", "dressing", "resuscitation", "triage", "injury", "concussion",
    
    # Indian Languages Emergency Terms
    "बाढ़", "पूर", "வெள்ளம்", "వరద",
    "भूकंप", "धरणीकंप", "நிலநடுக்கம்", "భూకంపం",
    "मलबे", "ढिगारा", "இடிபாடு", "శిథిల",
    "आग", "आगी", "தீ", "అగ్ని",
    "तूफान", "वादळ", "புயல்", "తుఫాను",
    "भूस्खलन", "दरड", "நிலச்சரிவு", "కొండచరియలు",
    "रक्त", "खून", "रक्तस्त्राव", "இரத்தம்", "రక్తం",
    "घाव", "जखम", "காயம்", "గాయం",
    "पानी", "पाणी", "தண்ணீர்", "నీరు",
    "प्राथमिक उपचार", "प्रथमोपचार", "முதலுதவி", "ప్రథమ చికిత్స",
    "बचाव", "सुरक्षा", "ఆశ్రయం", "புகலிடம்", "निवारा", "आश्रय",
    "बचाओ", "मदद", "फंसे", "फंस", "घायल", "बेहोश", "चोट", "एम्बुलेंस", "अस्पताल", "डूब", "गिर", "भूस्खलन",

    # Hinglish: Hindi typed in English letters (how most people text)
    "bachao", "bachaao", "madad", "help karo", "aag", "baadh", "badh", "paani", "pani bhar", "fase", "phase hain",
    "phas", "fas gaye", "fans", "ghayal", "zakhmi", "chot", "khoon", "behosh", "saans", "bhukamp", "bhookamp",
    "toofan", "tufan", "malba", "pahad", "girna", "gir gaya", "gir gayi", "dab gaye", "dabe", "doob", "dub",
    "jal gaya", "jal raha", "dhuan", "bijli", "karant", "sadak band", "rasta band", "road band", "lapata",
    "kho gaya", "ambulance", "hospital", "aspatal", "rahat", "khatra", "sanp", "saanp",

    # More English emergency words
    "injured", "injury", "hurt", "accident", "crash", "ambulance", "hospital", "paramedic", "stuck", "lost",
    "missing", "faint", "fainted", "breathing", "not breathing", "heart attack", "stroke", "seizure", "poison",
    "snake", "bite", "electrocut", "power line", "explosion", "gas", "cloudburst", "heavy rain", "river",
    "bridge", "road blocked", "stranded", "evacuat", "aftershock", "medicine", "insulin", "pregnant", "labour",
]

DISASTER_BLOCKLIST_PATTERNS = [
    r"\b(write a python script|code for|write a poem|write code|debug this code|sql injection|hack)\b",
    r"\b(who is the president|who won the match|recipe for chocolate|joke|tell me a joke)\b",
    r"\b(stock price|crypto price|bitcoin|cryptocurrency|investing advice|buy stocks)\b",
    r"\b(solve this math problem|homework|essay about|movie review)\b",
]

GUARDRAIL_REJECTIONS = {
    "en": (
        "⚠️ **Guardrail Notice**: I am dedicated strictly to **Emergency Disaster Response and Survival Guidance**.\n\n"
        "I can only assist with active disaster protocols, emergency first aid, search and rescue, evacuation routes, and crisis safety.\n\n"
        "Please ask an emergency or disaster-related question."
    ),
    "hi": (
        "⚠️ **सुरक्षा सूचना**: मैं केवल **आपदा आपातकालीन उत्तरजीविता और सुरक्षा** के लिए समर्पित हूँ।\n\n"
        "मैं केवल आपदा प्रोटोकॉल, आपातकालीन प्राथमिक चिकित्सा, खोज व बचाव और निकासी संबंधी सहायता प्रदान कर सकता हूँ।\n\n"
        "कृपया आपदा या आपातकाल से संबंधित प्रश्न पूछें।"
    ),
    "mr": (
        "⚠️ **सुरक्षा सूचना**: मी केवळ **आपत्ती आपत्कालीन प्रतिसाद आणि जगण्याच्या मार्गदर्शनासाठी** समर्पित आहे.\n\n"
        "मी फक्त आपत्ती नियम, प्रथमोपचार, शोध व बचाव आणि सुरक्षित स्थलांतर याबद्दल मार्गदर्शन करू शकतो.\n\n"
        "कृपया आपत्कालीन किंवा आपत्तीशी संबंधित प्रश्न विचारा."
    ),
    "ta": (
        "⚠️ **பாதுகாப்பு அறிவிப்பு**: நான் **பேரிடர் அவசர உதவி மற்றும் உயிர்வாழும் வழிகாட்டலுக்கு** மட்டுமே அர்ப்பணிக்கப்பட்டுள்ளேன்.\n\n"
        "பேரிடர் நெறிமுறைகள், அவசர முதலுதவி, தேடுதல் மற்றும் மீட்பு தொடர்பான கேள்விகளுக்கு மட்டுமே நான் பதிலளிக்க முடியும்.\n\n"
        "தயவுசெய்து பேரிடர் அல்லது அவசரநிலை தொடர்பான கேள்வியைக் கேளுங்கள்."
    ),
    "te": (
        "⚠️ **భద్రతా నోటీసు**: నేను **విపత్తు అత్యవసర సహాయం మరియు మనుగడ మార్గదర్శకత్వం** కోసం మాత్రమే రూపొందించబడ్డాను.\n\n"
        "విపత్తు నిబంధనలు, ప్రథమ చికిత్స, సహాయక చర్యలు మరియు తరలింపు గురించి మాత్రమే నేను మార్గనిర్దేశం చేయగలను.\n\n"
        "దయచేసి విపత్తు లేదా అత్యవసర పరిస్థితికి సంబంధించిన ప్రశ్నను అడగండి."
    )
}


def _blocked(q: str) -> bool:
    return any(re.search(p, q, re.IGNORECASE) for p in DISASTER_BLOCKLIST_PATTERNS)


def _has_keyword(q: str) -> bool:
    return any(kw in q for kw in DISASTER_ALLOWLIST_KEYWORDS)


def is_disaster_query(query: str) -> bool:
    """Fast word check only (no AI). Kept for /api/guardrail/check and as the first step."""
    q = query.lower().strip()
    if len(q) < 3 or _blocked(q):
        return False
    return _has_keyword(q)


_TOPIC_CACHE: Dict[str, bool] = {}


def _ai_says_disaster(query: str, groq_key: Optional[str]) -> Optional[bool]:
    """Quick yes/no from the AI for questions the word list does not cover (any language,
    typos, Hinglish). None if the AI is unavailable."""
    if not groq_key:
        return None
    key = query.strip().lower()[:300]
    if key in _TOPIC_CACHE:
        return _TOPIC_CACHE[key]
    try:
        resp = requests.post(GROQ_API_URL, timeout=8, headers={"Authorization": f"Bearer {groq_key}"}, json={
            "model": DEFAULT_GROQ_MODEL, "temperature": 0, "max_tokens": 200, "reasoning_effort": "low",
            "messages": [
                {"role": "system", "content": "Decide if a message to a disaster-help chatbot is about an emergency, disaster, "
                 "safety, first aid, rescue, evacuation, shelter, or surviving a crisis (in any language, including "
                 "Hindi written in English letters). Answer with exactly one word: YES or NO."},
                {"role": "user", "content": query[:500]},
            ]})
        if resp.status_code != 200:
            return None
        text = (resp.json()["choices"][0]["message"].get("content") or "").strip().upper()
        if not text:
            return None
        verdict = text.startswith("YES") or " YES" in text
        _TOPIC_CACHE[key] = verdict
        return verdict
    except Exception:
        return None


def guardrail_allows(query: str, history: Optional[List[Dict[str, str]]] = None,
                     groq_key: Optional[str] = None) -> bool:
    """Refuse only what is clearly off-topic. A person in danger must never be turned away
    because they typed in Hinglish or used a word the list does not have."""
    q = query.lower().strip()
    if len(q) < 2 or _blocked(q):
        return False
    if _has_keyword(q):
        return True
    # a follow-up in an emergency conversation ("aur kya karu?", "what next?")
    if history and any(_has_keyword((m.get("content") or "").lower()) for m in history if m.get("role") == "user"):
        return True
    ai = _ai_says_disaster(query, groq_key)
    # AI unavailable: answer anyway. The answer itself is still limited to disaster topics by the
    # system prompt, and refusing a real emergency is worse than answering an off-topic question.
    return True if ai is None else ai


class GroqDisasterEngine:
    """Disaster Assistant powered by Groq AI and SQLite Survival Protocols."""

    def __init__(self):
        self.sqlite_store = DisasterSQLiteStore()
        if self.sqlite_store.count() == 0:
            self.sqlite_store.ingest_from_json(force_refresh=True)

    def resolve_groq_key(self, request_key: Optional[str] = None) -> Optional[str]:
        """Resolves Groq API key from request, environment, or file."""
        if request_key and request_key.strip():
            return request_key.strip()
        env_key = os.environ.get("GROQ_API_KEY", "").strip()
        if env_key:
            return env_key
        # Check ~/.groq_key or local .env
        home_key_file = Path.home() / ".groq_key"
        if home_key_file.exists():
            return home_key_file.read_text("utf-8").strip()
        return None

    def answer_query(
        self,
        query: str,
        messages_history: Optional[List[Dict[str, str]]] = None,
        language: str = "en",
        max_tokens: int = 350,
        temperature: float = 0.2,
        groq_key: Optional[str] = None
    ) -> Dict[str, Any]:
        """Runs Guardrail Verification -> SQLite Retrieval -> Groq Inference."""
        lang_code = (language or "en")[:2].lower()
        active_groq_key = self.resolve_groq_key(groq_key)

        # 1. Safety Guardrail Verification
        if not guardrail_allows(query, messages_history, active_groq_key):
            rejection_text = GUARDRAIL_REJECTIONS.get(lang_code, GUARDRAIL_REJECTIONS["en"])
            return {
                "answer": rejection_text,
                "is_disaster_related": False,
                "guardrail_triggered": True,
                "matched_protocol": None,
                "category": "Guardrail Notice",
                "critical_warning": "Non-disaster query rejected by safety guardrail.",
                "actions": "",
                "sources": []
            }

        # 2. SQLite RAG Protocol Retrieval
        # A follow-up like "aur kya karu?" names no disaster: search the guide with the earlier
        # user messages too, or it matches a random protocol (seen: flood chat got earthquake advice).
        search_text = query
        if not _has_keyword(query.lower()) and messages_history:
            earlier = [m.get("content", "") for m in messages_history if m.get("role") == "user"]
            search_text = " ".join(earlier[-2:] + [query])
        matched = self.sqlite_store.search(search_text, limit=2)
        top_protocol = matched[0] if matched else None

        title = top_protocol.get("title", "Disaster Emergency") if top_protocol else "Emergency Protocol"
        category = top_protocol.get("category", "Safety") if top_protocol else "Safety"
        warning = top_protocol.get("critical_warning", "") if top_protocol else None
        actions = top_protocol.get("actions", "") if top_protocol else ""

        context_blocks = []
        if warning:
            context_blocks.append(f"CRITICAL LIFE-SAFETY WARNING: {warning}")
        if actions:
            context_blocks.append(f"VERIFIED PROTOCOL ACTIONS:\n{actions}")

        context_text = "\n\n".join(context_blocks)

        # Language-specific system directive
        lang_directives = {
            "hi": "Respond entirely and fluently in pure Hindi (हिंदी). Use clear Devanagari script.",
            "mr": "Respond entirely and fluently in pure Marathi (मराठी). Use clear Devanagari script.",
            "ta": "Respond entirely and fluently in pure Tamil (தமிழ்). Use clear Tamil script.",
            "te": "Respond entirely and fluently in pure Telugu (తెలుగు). Use clear Telugu script.",
            "en": "Respond directly and clearly in English. If the user writes in Hindi or Hinglish (Hindi in English "
                  "letters), reply in the same style they used."
        }
        lang_directive = lang_directives.get(lang_code, "Respond directly and clearly in English.")

        # 3. If no Groq key is configured, provide structured synthesis from SQLite knowledge base
        if not active_groq_key:
            return self._synthesize_local_rag(query, top_protocol, lang_code)

        # 4. Formulate Groq Prompt with Safety Guardrails
        system_prompt = (
            f"You are the ResQMesh Emergency Disaster Response Specialist AI powered by Groq. {lang_directive}\n\n"
            "STRICT SAFETY GUARDRAIL:\n"
            "You are strictly programmed to ONLY assist with active disaster emergencies, survival protocols, "
            "emergency first aid, search and rescue, evacuation, emergency shelters, and disaster preparedness.\n"
            "Under NO circumstances should you assist with non-emergency topics. If the query deviates from disaster "
            "safety, politely decline and redirect the user back to disaster survival.\n\n"
            "EMERGENCY INSTRUCTION RULES:\n"
            "1. Put the single most critical, life-saving action in the FIRST sentence in bold.\n"
            "2. Highlight any lethal danger clearly with '⚠️ DANGER / WARNING'.\n"
            "3. Keep instructions concise, direct, and numbered or bulleted.\n"
            "4. Ground your guidance in verified emergency protocols.\n"
            "5. Remind the user to activate their offline mesh SOS beacon if trapped or in peril.\n"
            "6. The user is in India (Uttarakhand). Use Indian emergency numbers only: 112 (all emergencies), "
            "108 (ambulance), 101 (fire), 100 (police), 1070 (state disaster helpline). Never mention 911."
        )

        groq_messages = [{"role": "system", "content": system_prompt}]

        # Include recent multi-turn history if present
        if messages_history:
            for m in messages_history[-4:]:
                groq_messages.append({"role": m["role"], "content": m["content"]})

        user_content = f"VERIFIED EMERGENCY KNOWLEDGE BASE:\n{context_text}\n\nUSER EMERGENCY QUESTION: {query}"
        groq_messages.append({"role": "user", "content": user_content})

        try:
            payload = {
                "model": DEFAULT_GROQ_MODEL,
                "messages": groq_messages,
                "temperature": temperature,
                "max_tokens": max_tokens
            }
            if "gpt-oss" in DEFAULT_GROQ_MODEL or "qwen" in DEFAULT_GROQ_MODEL:
                # Thinking models spend tokens on hidden reasoning first; with the app's 350-token limit the
                # visible answer came back EMPTY (348 of 350 tokens were reasoning). Low reasoning + room to answer.
                payload["reasoning_effort"] = "low"
                payload["max_tokens"] = max(max_tokens, 1000)
            headers = {
                "Authorization": f"Bearer {active_groq_key}",
                "Content-Type": "application/json"
            }
            resp = requests.post(GROQ_API_URL, json=payload, headers=headers, timeout=12)

            if resp.status_code == 200:
                data = resp.json()
                generated_answer = data["choices"][0]["message"]["content"].strip()
                return {
                    "answer": generated_answer,
                    "is_disaster_related": True,
                    "guardrail_triggered": False,
                    "matched_protocol": title,
                    "category": category,
                    "critical_warning": warning,
                    "actions": actions,
                    "sources": [m.get("title", "") for m in matched],
                    "model": DEFAULT_GROQ_MODEL,
                    "provider": "Groq"
                }
            else:
                print(f"[Groq API Error] HTTP {resp.status_code}: {resp.text}")
        except Exception as e:
            print(f"[Groq API Call Failed]: {e}")

        # Fallback to local RAG synthesis if Groq call encounters network/key error
        return self._synthesize_local_rag(query, top_protocol, lang_code)

    def _synthesize_local_rag(self, query: str, top_protocol: Optional[Dict[str, Any]], lang_code: str) -> Dict[str, Any]:
        """Instant structured fallback synthesis using verified SQLite protocol records."""
        if not top_protocol:
            fallback_answers = {
                "hi": "कोई विशिष्ट आपातकालीन प्रोटोकॉल नहीं मिला। ऊंचे स्थानों पर जाएं, गिरे हुए बिजली के तारों से बचें और Bitchat में SOS प्रसारित करें।",
                "mr": "विशिष्ट आपत्कालीन नियम आढळला नाही. उंचावर जा, विजेच्या तारांपासून लांब राहा आणि Bitchat मध्ये SOS पाठवा.",
                "ta": "குறிப்பிட்ட நெறிமுறை கிடைக்கவில்லை. உயரமான இடத்திற்குச் செல்லுங்கள் மற்றும் Bitchat-ல் SOS சமிக்ஞை அனுப்பவும்.",
                "te": "నిర్దిష్ట అత్యవసర నిబంధన కనుగొనబడలేదు. ఎత్తైన ప్రాంతాలకు వెళ్లండి మరియు Bitchat లో SOS ను పంపండి.",
                "en": "Seek secure high ground immediately, stay away from downed power lines, and broadcast your SOS beacon in Bitchat."
            }
            return {
                "answer": fallback_answers.get(lang_code, fallback_answers["en"]),
                "is_disaster_related": True,
                "guardrail_triggered": False,
                "matched_protocol": "General Emergency",
                "category": "Safety",
                "critical_warning": None,
                "actions": "",
                "sources": [],
                "provider": "Offline Knowledge Base"
            }

        title = top_protocol.get("title", "Disaster Protocol")
        warning = top_protocol.get("critical_warning", "")
        actions = top_protocol.get("actions", "")

        lines = [f"📋 **{title} Instructions**:"]
        if warning:
            lines.insert(0, f"⚠️ **CRITICAL WARNING**: {warning}\n")
        lines.append(actions)
        lines.append("\n📡 *Tip: Tap the red SOS button in Bitchat to broadcast your coordinates to nearby rescue nodes.*")

        return {
            "answer": "\n".join(lines),
            "is_disaster_related": True,
            "guardrail_triggered": False,
            "matched_protocol": title,
            "category": top_protocol.get("category", "Disaster"),
            "critical_warning": warning,
            "actions": actions,
            "sources": [title],
            "provider": "Offline Knowledge Base"
        }


engine = GroqDisasterEngine()


@app.get("/health")
def health_check() -> Dict[str, Any]:
    key_configured = bool(engine.resolve_groq_key())
    return {
        "status": "healthy",
        "provider": "Groq",
        "model": DEFAULT_GROQ_MODEL,
        "groq_key_configured": key_configured,
        "guardrails": "active",
        "sqlite_entries": engine.sqlite_store.count(),
        "timestamp": time.time()
    }


@app.post("/api/guardrail/check")
def check_guardrail(req: Dict[str, str]) -> Dict[str, Any]:
    query = req.get("query") or req.get("message") or ""
    allowed = guardrail_allows(query, None, engine.resolve_groq_key())
    return {
        "query": query,
        "allowed": allowed,
        "reason": "Disaster emergency topic" if allowed else "Query rejected: Not disaster or emergency related."
    }


@app.post("/api/chat")
def api_chat(
    req: ChatRequest,
    x_groq_api_key: Optional[str] = Header(None, alias="X-Groq-Api-Key")
) -> Dict[str, Any]:
    query_text = (req.query or req.message or "").strip()
    if not query_text and req.messages:
        query_text = req.messages[-1].content.strip()

    if not query_text:
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    history_dicts = None
    if req.messages:
        history_dicts = [{"role": m.role, "content": m.content} for m in req.messages[:-1]]

    groq_key = req.groq_api_key or x_groq_api_key

    return engine.answer_query(
        query=query_text,
        messages_history=history_dicts,
        language=req.language or "en",
        max_tokens=req.max_tokens or 350,
        temperature=req.temperature or 0.2,
        groq_key=groq_key
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ResQMesh Groq Disaster AI API Server")
    parser.add_argument("--port", type=int, default=8800, help="HTTP port (default: 8800)")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host address (default: 0.0.0.0)")
    args = parser.parse_args()

    print(f"\n=======================================================")
    print(f" ResQMesh Disaster AI Server (Groq)")
    print(f" Model:       {DEFAULT_GROQ_MODEL}")
    print(f" Guardrails:  ACTIVE (Disaster & Emergency Only)")
    print(f" Address:     http://{args.host}:{args.port}")
    print(f"=======================================================\n")

    uvicorn.run(app, host=args.host, port=args.port)
