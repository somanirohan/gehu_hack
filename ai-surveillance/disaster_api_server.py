"""Disaster Management API Server using SQLite Lookup + Qwen2.5-1.5B Local SLM.

Provides fast, offline-capable endpoints for disaster survival query resolution:
- POST /api/chat: Performs SQLite FTS lookup on survival protocols and generates tailored
                  instructions using Qwen2.5-1.5B-Instruct on local GPU.
- POST /api/lookup: Direct SQLite FTS lookup without LLM inference (sub-millisecond).
- GET /health: Health status and model readiness.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import torch
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from transformers import AutoModelForCausalLM, AutoTokenizer

# Reconfigure stdout/stderr for Unicode safety on Windows consoles
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from rag.sqlite_store import DisasterSQLiteStore

MODEL_ID = "Qwen/Qwen2.5-1.5B-Instruct"

app = FastAPI(
    title="Disaster Survival Management API",
    description="SQLite FTS Protocol Lookup + Qwen2.5-1.5B Local SLM Assistant",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    query: str
    language: Optional[str] = "en"
    max_tokens: Optional[int] = 200
    temperature: Optional[float] = 0.3


class LookupRequest(BaseModel):
    query: str
    limit: Optional[int] = 3


class DisasterEngine:
    """Manages SQLite storage and the Qwen2.5-1.5B neural model."""

    def __init__(self, load_model: bool = True):
        self.sqlite_store = DisasterSQLiteStore()
        # Ensure database is populated
        if self.sqlite_store.count() == 0:
            self.sqlite_store.ingest_from_json(force_refresh=True)

        self.device = "cuda:0" if torch.cuda.is_available() else "cpu"
        self.tokenizer = None
        self.model = None

        if load_model:
            self.load_model()

    def load_model(self) -> None:
        """Loads Qwen2.5-1.5B onto device."""
        if self.model is not None:
            return

        print(f"[Engine] Loading {MODEL_ID} on {self.device}...")
        t0 = time.time()
        self.tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
        self.model = AutoModelForCausalLM.from_pretrained(
            MODEL_ID,
            torch_dtype=torch.float16 if "cuda" in self.device else torch.float32,
            device_map=self.device
        )
        self.model.eval()
        print(f"[Engine] Model loaded in {time.time() - t0:.2f}s!")

    def answer_query(
        self,
        query: str,
        language: str = "en",
        max_tokens: int = 200,
        temperature: float = 0.3
    ) -> Dict[str, Any]:
        """Performs SQLite lookup and synthesizes response with Qwen2.5-1.5B in the requested language."""
        # Multi-language keyword mapping for SQLite lookup
        keyword_map = {
            "बाढ़": "flood", "पूर": "flood", "வெள்ளம்": "flood", "వరద": "flood",
            "भूकंप": "earthquake collapse", "धरणीकंप": "earthquake collapse", "நிலநடுக்கம்": "earthquake", "భూకంపం": "earthquake",
            "मलबे": "rubble collapse trapped", "ढिगारा": "rubble collapse", "இடிபாடு": "rubble collapse", "శిథిల": "rubble collapse",
            "आग": "fire smoke", "आगी": "fire smoke", "தீ": "fire smoke", "అగ్ని": "fire smoke",
            "तूफान": "cyclone storm", "वादळ": "cyclone storm", "புயல்": "cyclone storm", "తుఫాను": "cyclone storm",
            "भूस्खलन": "landslide mudflow", "दरड": "landslide mudflow", "நிலச்சரிவு": "landslide mudflow", "కొండచరియలు": "landslide mudflow",
            "रक्त": "severe bleeding tourniquet", "खून": "severe bleeding", "இரத்தம்": "bleeding first aid", "రక్తం": "bleeding first aid",
            "घाव": "wound first aid", "जखम": "wound first aid", "காயம்": "wound first aid", "గాయం": "wound first aid",
            "पानी": "water purification", "पाणी": "water purification", "தண்ணீர்": "water purification", "నీరు": "water purification"
        }

        search_query = query
        for k, v in keyword_map.items():
            if k in query:
                search_query = f"{search_query} {v}"

        # 1. SQLite Fast Lookup
        matched = self.sqlite_store.search(search_query, limit=2)
        top_protocol = matched[0] if matched else None

        if not top_protocol:
            fallback_answers = {
                "hi": "कोई विशिष्ट आपातकालीन प्रोटोकॉल नहीं मिला। सामान्य सुरक्षा नियमों का पालन करें: ऊंचे स्थानों पर जाएं, गिरे हुए बिजली के तारों से बचें और Bitchat में SOS प्रसारित करें।",
                "mr": "विशिष्ट आपत्कालीन नियम आढळला नाही. सामान्य सुरक्षा नियमांचे पालन करा: उंचावर जा, विजेच्या तारांपासून लांब राहा आणि Bitchat मध्ये SOS पाठवा.",
                "ta": "குறிப்பிட்ட நெறிமுறை எதுவும் கிடைக்கவில்லை. பொதுவான பாதுகாப்பு விதிகளைப் பின்பற்றவும்: உயரமான இடத்திற்குச் செல்லுங்கள், மின் கம்பிகளிலிருந்து விலகி இருங்கள் மற்றும் Bitchat-ல் SOS சமிக்ஞை அனுப்பவும்.",
                "te": "నిర్దిష్ట అత్యవసర నిబంధన కనుగొనబడలేదు. సాధారణ భద్రతా నియమాలను పాటించండి: ఎత్తైన ప్రాంతాలకు వెళ్లండి, విద్యుత్ తీగలకు దూరంగా ఉండండి మరియు Bitchat లో SOS ను పంపండి.",
                "en": "No specific survival protocol found. Follow general safety instructions: seek high ground, avoid downed wires, and broadcast SOS."
            }
            lang_code = (language or "en")[:2].lower()
            return {
                "answer": fallback_answers.get(lang_code, fallback_answers["en"]),
                "matched_protocol": "General Emergency",
                "category": "General",
                "critical_warning": None,
                "actions": "",
                "sources": []
            }

        title = top_protocol.get("title", "Disaster Protocol")
        category = top_protocol.get("category", "General")
        warning = top_protocol.get("critical_warning", "")
        actions = top_protocol.get("actions", "")

        context_lines = []
        if warning:
            context_lines.append(f"CRITICAL LIFE-SAFETY WARNING: {warning}")
        if actions:
            context_lines.append(f"VERIFIED EMERGENCY ACTIONS:\n{actions}")

        context_text = "\n\n".join(context_lines)

        # Language-specific system prompt instruction
        lang_code = (language or "en")[:2].lower()
        lang_directives = {
            "hi": "Respond entirely and fluently in pure Hindi (हिंदी). Use clear Devanagari script. Do NOT reply in English.",
            "mr": "Respond entirely and fluently in pure Marathi (मराठी). Use clear Devanagari script. Do NOT reply in English.",
            "ta": "Respond entirely and fluently in pure Tamil (தமிழ்). Use clear Tamil script. Do NOT reply in English.",
            "te": "Respond entirely and fluently in pure Telugu (తెలుగు). Use clear Telugu script. Do NOT reply in English.",
            "en": "Respond directly and clearly in English."
        }
        lang_directive = lang_directives.get(lang_code, "Respond directly and clearly in English.")

        # 2. Qwen2.5-1.5B prompt formulation
        system_prompt = (
            f"You are a disaster emergency survival assistant. {lang_directive} "
            "Answer the user's question directly, concisely, and with life-saving accuracy using the verified emergency data provided below. "
            "Always state any critical warning first in bold, followed by 2-4 immediate action bullet points in the requested language."
        )

        user_content = f"VERIFIED EMERGENCY DATA:\n{context_text}\n\nUSER QUESTION: {query}"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ]

        if self.model is None:
            self.load_model()

        prompt_text = self.tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = self.tokenizer([prompt_text], return_tensors="pt").to(self.model.device)

        with torch.no_grad():
            outputs = self.model.generate(
                **inputs,
                max_new_tokens=max_tokens,
                temperature=temperature,
                do_sample=(temperature > 0.0)
            )

        gen_tokens = outputs[0][len(inputs.input_ids[0]):]
        answer = self.tokenizer.decode(gen_tokens, skip_special_tokens=True).strip()

        return {
            "answer": answer,
            "matched_protocol": title,
            "category": category,
            "critical_warning": warning,
            "actions": actions,
            "sources": [m.get("title", "") for m in matched]
        }


# Global engine instance
engine: Optional[DisasterEngine] = None


def get_engine() -> DisasterEngine:
    global engine
    if engine is None:
        engine = DisasterEngine(load_model=True)
    return engine


@app.get("/health")
def health_check() -> Dict[str, Any]:
    eng = get_engine()
    return {
        "status": "healthy",
        "model": MODEL_ID,
        "device": eng.device,
        "sqlite_entries": eng.sqlite_store.count(),
        "timestamp": time.time()
    }


@app.post("/api/chat")
def api_chat(req: ChatRequest) -> Dict[str, Any]:
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")
    eng = get_engine()
    return eng.answer_query(
        query=req.query,
        language=req.language or "en",
        max_tokens=req.max_tokens or 200,
        temperature=req.temperature or 0.3
    )


@app.post("/api/lookup")
def api_lookup(req: LookupRequest) -> Dict[str, Any]:
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")
    eng = get_engine()
    results = eng.sqlite_store.search(req.query, limit=req.limit or 3)
    return {
        "query": req.query,
        "count": len(results),
        "results": results
    }


def run_tests() -> None:
    """Automated verification of SQLite lookup and Qwen2.5-1.5B inference."""
    eng = get_engine()
    test_queries = [
        "Help! I am trapped under rubble after a building collapse!",
        "The cyclone eye is passing and it's quiet. Can we go outside?",
        "How do I purify flood water for drinking?",
        "A severe landslide is sliding towards our mountain road, what to do?"
    ]

    print("\n=== Testing SQLite Lookup + Qwen2.5-1.5B Disaster Engine ===")
    for q in test_queries:
        print(f"\n>>> Query: '{q}'")
        t0 = time.time()
        res = eng.answer_query(q)
        dt = time.time() - t0
        print(f"Matched: {res['matched_protocol']} ({res['category']}) in {dt:.2f}s")
        if res['critical_warning']:
            print(f"⚠️ Warning: {res['critical_warning']}")
        print(f"AI Answer:\n{res['answer']}\n{'-'*50}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Disaster Management SQLite + Qwen2.5-1.5B API Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host address to bind")
    parser.add_argument("--port", type=int, default=8800, help="Port to listen on")
    parser.add_argument("--test", action="store_true", help="Run self-tests and exit")
    args = parser.parse_args()

    if args.test:
        run_tests()
    else:
        print(f"Starting Disaster Management API Server on {args.host}:{args.port}...")
        uvicorn.run(app, host=args.host, port=args.port)
