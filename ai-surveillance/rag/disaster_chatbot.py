"""Disaster Management RAG + Groq AI Chatbot Engine.

Combines local Vector Database / SQLite FTS5 retrieval with Groq AI LLM
inference to provide immediate, actionable, life-saving advice during crises.
Equipped with strict safety guardrails that restrict conversation to
disaster preparedness, survival protocols, and emergency guidance.

Modes:
  1. Interactive CLI: python disaster_chatbot.py --cli
  2. HTTP Server:     python disaster_chatbot.py --serve [--port 8800]
  3. Python Library:  from rag.disaster_chatbot import DisasterChatbot
  4. Test Suite:      python disaster_chatbot.py --test
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure package root is in path
CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = CURRENT_DIR.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_DIR / ".env")
except ImportError:
    pass

# Ensure UTF-8 output on Windows console
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

try:
    from rag.vector_store import DisasterVectorStore
except ImportError:
    try:
        from vector_store import DisasterVectorStore
    except ImportError:
        DisasterVectorStore = None

try:
    from rag.sqlite_store import DisasterSQLiteStore
except ImportError:
    try:
        from sqlite_store import DisasterSQLiteStore
    except ImportError:
        DisasterSQLiteStore = None


EMERGENCY_SYSTEM_PROMPT = """You are an emergency disaster response specialist and tactical advisor.
Your mission is to provide concise, urgent, life-saving guidance to individuals facing active disasters.

STRICT PROTOCOLS:
1. Put the most critical, immediate life-safety action in the FIRST sentence.
2. Highlight any lethal danger or warning clearly (e.g. ⚠️ WARNING: DO NOT...).
3. Keep instructions clear, direct, and numbered or bulleted.
4. Base your recommendations strictly on the provided verified disaster protocols.
5. Remind the user to activate their offline mesh SOS beacon if trapped or in peril."""

# --- Disaster Safety Guardrails ---

DISASTER_ALLOWLIST_KEYWORDS = [
    # General Emergency & Survival
    "emergency", "disaster", "crisis", "survive", "survival", "rescue", "evacuate",
    "evacuation", "shelter", "sos", "hazard", "danger", "trapped", "help", "safe",
    "safety", "distress", "staging", "relief", "beacon", "first aid", "first-aid",
    "drill", "alert", "warning", "guide", "protocol", "checklist", "pack", "go-bag",
    "rations", "battery", "flashlight", "radio",
    
    # Structural & Geological
    "earthquake", "collapse", "collapsed", "collapsing", "rubble", "tremor", "aftershock", "building collapse",
    "landslide", "mudslide", "rockfall", "avalanche", "debris", "structure", "geophone",
    "falling debris", "under rubble", "concrete", "slab", "slabs", "buried", "crush", "trapped inside",
    "hillside", "slope", "slide", "sliding", "sinkhole", "crater", "fault line", "road",
    
    # Weather & Hydrological
    "flood", "flooding", "flash flood", "water surge", "water purification", "purify water",
    "clean water", "purify", "purifying", "filter", "filtration", "boil water", "drinking water",
    "cyclone", "hurricane", "storm", "typhoon", "tornado", "gale", "eye of storm", "wind",
    "tsunami", "high ground", "drown", "drowning", "submerged", "river", "surge", "taps", "tap",
    "monsoon", "cloudburst", "heavy rain", "lightning", "thunderstorm",
    
    # Thermal, Fire & Hazardous
    "fire", "wildfire", "smoke", "smoke inhalation", "burn", "burns", "flames", "extinguisher",
    "gas leak", "electrical shock", "downed power lines", "power lines", "electric", "electrocution",
    "chemical leak", "toxic", "fumes", "explosion", "radiation",
    
    # Medical First Aid
    "bleed", "bleeding", "severe bleeding", "blood", "tourniquet", "fracture", "broken bone",
    "splint", "cpr", "choking", "unconscious", "shock", "hypothermia", "heatstroke",
    "wound", "bandage", "dressing", "resuscitation", "triage", "injury", "concussion",
    "pain", "chest compressions", "breath", "breathing", "airway", "snakebite", "bite", "poison",
    "frostbite", "dehydration"
]

DISASTER_BLOCKLIST_PATTERNS = [
    r"\b(write a python script|code for|write a poem|write code|debug this code|sql injection|hack)\b",
    r"\b(who is the president|who won the match|recipe for chocolate|joke|tell me a joke)\b",
    r"\b(stock price|crypto price|bitcoin|cryptocurrency|investing advice|buy stocks)\b",
    r"\b(solve this math problem|homework|essay about|movie review)\b",
]

GUARDRAIL_REJECTION_MESSAGE = (
    "⚠️ **Guardrail Notice**: I am dedicated strictly to **Emergency Disaster Response and Survival Guidance**.\n\n"
    "I can only assist with active disaster protocols, emergency first aid, search and rescue, evacuation routes, and crisis safety.\n\n"
    "Please ask an emergency or disaster-related question."
)


class DisasterChatbot:
    """RAG + Groq AI Chatbot for disaster survival response."""

    def __init__(
        self,
        vector_store: Optional[Any] = None,
        model_id: Optional[str] = None,
        groq_api_key: Optional[str] = None,
        *args,
        **kwargs
    ):
        """Initializes RAG Knowledge Base and Groq LLM integration.
        
        Args:
            vector_store: Optional vector or SQLite store instance.
            model_id: Groq model name (default from GROQ_MODEL env or llama-3.3-70b-versatile).
            groq_api_key: Optional Groq API key (defaults from GROQ_API_KEY env).
            *args, **kwargs: Accepted for backward compatibility (e.g. use_lightweight_slm).
        """
        self.model_id = model_id or os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
        raw_key = (groq_api_key or os.environ.get("GROQ_API_KEY", "")).strip()
        # Clean dummy placeholder keys
        if raw_key in ("your_groq_api_key_here", "your_groq_api_key"):
            raw_key = ""
        self.groq_api_key = raw_key

        # Always initialize secondary SQLite store for guaranteed zero-dependency fallback
        self.sqlite_store = None
        if DisasterSQLiteStore is not None:
            try:
                self.sqlite_store = DisasterSQLiteStore()
            except Exception as e:
                print(f"[RAG Init] SQLite store fallback init note: {e}")

        # Initialize primary knowledge base (ChromaDB or SQLite)
        if vector_store is not None:
            self.vector_store = vector_store
        else:
            self.vector_store = self._init_knowledge_store()

    def _init_knowledge_store(self) -> Any:
        """Attempts to initialize ChromaDB; falls back gracefully to SQLite FTS5."""
        if DisasterVectorStore is not None:
            try:
                store = DisasterVectorStore()
                if hasattr(store, "count") and store.count() == 0 and hasattr(store, "ingest_from_json"):
                    store.ingest_from_json()
                return store
            except Exception as e:
                print(f"[RAG Init] VectorStore initialization notice: {e}. Using SQLite FTS5.")

        return self.sqlite_store

    def check_guardrails(self, query: str) -> Optional[str]:
        """Checks if the query is emergency/disaster related. Returns rejection message if not."""
        q_lower = query.lower().strip()
        if not q_lower:
            return GUARDRAIL_REJECTION_MESSAGE

        # 1. Blocklist check
        for pattern in DISASTER_BLOCKLIST_PATTERNS:
            if re.search(pattern, q_lower, re.IGNORECASE):
                return GUARDRAIL_REJECTION_MESSAGE

        # 2. Allowlist keyword check
        has_allowed_keyword = any(kw.lower() in q_lower for kw in DISASTER_ALLOWLIST_KEYWORDS)
        
        # Generic multi-word queries without any emergency keywords are blocked
        if not has_allowed_keyword and len(q_lower.split()) > 3:
            return GUARDRAIL_REJECTION_MESSAGE

        return None

    def retrieve_context(self, user_query: str, n_results: int = 2) -> List[Dict[str, Any]]:
        """Retrieves top matching survival protocol chunks from vector DB or SQLite store."""
        results: List[Dict[str, Any]] = []

        # 1. Try Primary Vector Store (ChromaDB)
        if self.vector_store is not None and hasattr(self.vector_store, "query"):
            try:
                raw_chunks = self.vector_store.query(user_query, n_results=n_results)
                for c in raw_chunks:
                    results.append({
                        "id": c.get("id", ""),
                        "disaster": c.get("disaster") or c.get("title", "Emergency Protocol"),
                        "phase": c.get("phase", "General"),
                        "category": c.get("category", "General"),
                        "critical_alert": c.get("critical_alert") or c.get("critical_warning", ""),
                        "content": c.get("content") or c.get("actions", ""),
                        "relevance_score": c.get("relevance_score", 1.0)
                    })
                if results:
                    return results
            except Exception as e:
                print(f"[RAG Retrieval Notice] Vector query notice: {e}")

        # 2. Try Fallback SQLite Store
        fallback_store = self.sqlite_store or (self.vector_store if hasattr(self.vector_store, "search") else None)
        if fallback_store is not None and hasattr(fallback_store, "search"):
            try:
                raw_rows = fallback_store.search(user_query, limit=n_results)
                for r in raw_rows:
                    results.append({
                        "id": r.get("id", ""),
                        "disaster": r.get("title", "Emergency Protocol"),
                        "phase": "Immediate",
                        "category": r.get("category", "General"),
                        "critical_alert": r.get("critical_warning", ""),
                        "content": r.get("actions", ""),
                        "relevance_score": 1.0
                    })
            except Exception as e:
                print(f"[RAG Retrieval Notice] SQLite search notice: {e}")

        return results

    def generate_response(self, user_query: str, n_context: int = 2) -> Dict[str, Any]:
        """Runs safety guardrail check, knowledge retrieval, and generates response."""
        # 1. Guardrail validation
        guardrail_error = self.check_guardrails(user_query)
        if guardrail_error:
            return {
                "query": user_query,
                "answer": guardrail_error,
                "critical_alerts": [],
                "sources": [],
                "provider": "Safety Guardrail",
                "allowed": False
            }

        # 2. Knowledge Retrieval
        chunks = self.retrieve_context(user_query, n_results=n_context)
        critical_alerts = [c["critical_alert"] for c in chunks if c.get("critical_alert")]

        if not chunks:
            return {
                "query": user_query,
                "answer": (
                    "🚨 **General Emergency Protocol**:\n"
                    "1. Protect your head and move away from windows, unreinforced walls, and power lines.\n"
                    "2. Tap the red SOS beacon in Bitchat to broadcast your coordinates to nearby rescue teams.\n"
                    "3. Stay calm and preserve phone battery."
                ),
                "sources": [],
                "critical_alerts": [],
                "provider": "Offline Fallback",
                "allowed": True
            }

        # 3. Groq LLM Inference (if key available) or Offline Structured Synthesis
        answer = None
        if self.groq_api_key:
            answer = self._generate_with_groq(user_query, chunks)

        if not answer:
            answer = self._synthesize_structured_answer(user_query, chunks)

        return {
            "query": user_query,
            "answer": answer,
            "critical_alerts": critical_alerts,
            "sources": [
                {
                    "disaster": c.get("disaster", "Disaster Protocol"),
                    "phase": c.get("phase", "General"),
                    "category": c.get("category", "General"),
                    "relevance": c.get("relevance_score", 1.0)
                }
                for c in chunks
            ],
            "provider": "Groq" if self.groq_api_key and answer else "Offline Knowledge Base",
            "allowed": True
        }

    def _synthesize_structured_answer(self, query: str, chunks: List[Dict[str, Any]]) -> str:
        """Fast, robust offline synthesis from retrieved knowledge chunks."""
        top = chunks[0]
        alert = top.get("critical_alert", "").strip()
        content = top.get("content", "").strip()
        phase = top.get("phase", "Immediate")
        disaster = top.get("disaster", "Disaster Survival")

        lines = [
            f"🚨 **{disaster} Protocol ({phase})**"
        ]
        if alert:
            lines.append(f"\n⚠️ **CRITICAL WARNING**: {alert}\n")

        lines.append("**Immediate Actions**:")
        raw_items = [
            item.strip()
            for item in re.split(r"(?:\d+\.|\n•|\n-|\.\s+)", content)
            if item.strip() and len(item.strip()) > 3
        ]
        for item in raw_items[:5]:
            if not item.endswith("."):
                item += "."
            lines.append(f"• {item}")

        lines.append("\n📡 *Tip: Tap the SOS button in Bitchat to broadcast emergency alerts over the mesh network.*")
        return "\n".join(lines)

    def _generate_with_groq(self, query: str, chunks: List[Dict[str, Any]]) -> Optional[str]:
        """Calls Groq API for rapid inference with disaster ground truth."""
        try:
            import requests

            context_items = []
            for c in chunks:
                disaster = c.get("disaster", "Emergency")
                phase = c.get("phase", "Protocol")
                alert = c.get("critical_alert", "")
                content = c.get("content", "")
                context_items.append(f"[{disaster} - {phase}]: {alert} {content}".strip())

            context_text = "\n".join(context_items)
            system_prompt = (
                f"{EMERGENCY_SYSTEM_PROMPT}\n\n"
                f"STRICT SAFETY GUARDRAIL: Only answer disaster and emergency questions. Ground answers strictly on:\n{context_text}"
            )
            payload = {
                "model": self.model_id,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": query}
                ],
                "temperature": 0.2,
                "max_tokens": 350
            }
            headers = {
                "Authorization": f"Bearer {self.groq_api_key}",
                "Content-Type": "application/json"
            }
            r = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                json=payload,
                headers=headers,
                timeout=10
            )
            if r.status_code == 200:
                data = r.json()
                return data["choices"][0]["message"]["content"].strip()
            else:
                print(f"[RAG Groq WARN] Groq API returned status {r.status_code}: {r.text[:200]}")
        except Exception as e:
            print(f"[RAG Groq Notice] Request exception: {e}")
        return None


# --- Lightweight HTTP API Server for App and Client Integration ---

class ChatbotHttpHandler(BaseHTTPRequestHandler):
    chatbot: Optional[DisasterChatbot] = None

    def _send_json(self, status: int, data: Dict[str, Any]):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8"))

    def do_OPTIONS(self):
        self._send_json(200, {"status": "ok"})

    def do_GET(self):
        if self.path in ("/health", "/api/health"):
            doc_count = 0
            if self.chatbot and self.chatbot.vector_store:
                if hasattr(self.chatbot.vector_store, "count"):
                    try:
                        doc_count = self.chatbot.vector_store.count()
                    except Exception:
                        pass
            if doc_count == 0 and self.chatbot and self.chatbot.sqlite_store:
                try:
                    doc_count = self.chatbot.sqlite_store.count()
                except Exception:
                    pass

            self._send_json(200, {
                "status": "ok",
                "provider": "Groq" if (self.chatbot and self.chatbot.groq_api_key) else "Offline Knowledge Base",
                "model": self.chatbot.model_id if self.chatbot else "",
                "vector_docs": doc_count
            })
        else:
            self._send_json(404, {"error": "Endpoint not found"})

    def do_POST(self):
        if self.path in ("/api/chat", "/chat"):
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8")
            try:
                req = json.loads(body)
                query = req.get("query") or req.get("message") or ""
                if not query.strip():
                    self._send_json(400, {"error": "Missing 'query' field in JSON body"})
                    return
                resp = self.chatbot.generate_response(query)
                self._send_json(200, resp)
            except Exception as e:
                self._send_json(500, {"error": str(e)})

        elif self.path in ("/api/search", "/search"):
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8")
            try:
                req = json.loads(body)
                query = req.get("query", "")
                k = req.get("k", 3)
                results = self.chatbot.retrieve_context(query, n_results=k)
                self._send_json(200, {"query": query, "results": results})
            except Exception as e:
                self._send_json(500, {"error": str(e)})

        elif self.path in ("/api/guardrail/check", "/guardrail"):
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8")
            try:
                req = json.loads(body)
                query = req.get("query") or req.get("message") or ""
                guardrail_error = self.chatbot.check_guardrails(query) if self.chatbot else None
                self._send_json(200, {
                    "query": query,
                    "allowed": guardrail_error is None,
                    "rejection_message": guardrail_error
                })
            except Exception as e:
                self._send_json(500, {"error": str(e)})
        else:
            self._send_json(404, {"error": "Endpoint not found"})


def run_server(port: int = 8800):
    chatbot = DisasterChatbot()
    ChatbotHttpHandler.chatbot = chatbot

    server = HTTPServer(("0.0.0.0", port), ChatbotHttpHandler)
    print(f"\n[RAG Chatbot API] Disaster Chatbot HTTP Server running on http://0.0.0.0:{port}")
    print(f"[RAG Chatbot API] Endpoints:")
    print(f"  POST http://localhost:{port}/api/chat            (body: {{\"query\": \"...\"}})")
    print(f"  POST http://localhost:{port}/api/search          (body: {{\"query\": \"...\", \"k\": 3}})")
    print(f"  POST http://localhost:{port}/api/guardrail/check (body: {{\"query\": \"...\"}})")
    print(f"  GET  http://localhost:{port}/health\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[RAG Chatbot API] Server stopped.")
        server.server_close()


def run_cli():
    print("=" * 65)
    print("  🛡️  DISASTER MANAGEMENT RAG CHATBOT (EMERGENCY ADVISOR)  🛡️")
    print("=" * 65)
    print("Type your emergency query below (e.g. 'trapped in rubble', 'cyclone eye', 'severe bleeding').")
    print("Type 'exit' or 'quit' to stop.\n")

    chatbot = DisasterChatbot()

    while True:
        try:
            user_input = input("User Emergency Query > ").strip()
            if not user_input:
                continue
            if user_input.lower() in ("exit", "quit", "q"):
                print("Exiting. Stay safe.")
                break

            response = chatbot.generate_response(user_input)
            print("\n" + response["answer"] + "\n")
            print("-" * 65)
        except (KeyboardInterrupt, EOFError):
            print("\nExiting. Stay safe.")
            break


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Disaster Management RAG + Groq AI Chatbot")
    parser.add_argument("--cli", action="store_true", help="Launch interactive CLI chat")
    parser.add_argument("--serve", action="store_true", help="Run HTTP API server")
    parser.add_argument("--port", type=int, default=8800, help="Server port (default: 8800)")
    parser.add_argument("--test", action="store_true", help="Run automated test suite")
    args = parser.parse_args()

    if args.serve:
        run_server(port=args.port)
    elif args.cli:
        run_cli()
    else:
        # Default / --test: run automated verification
        chatbot = DisasterChatbot()
        sample_queries = [
            "Help, I'm buried under concrete slabs in a collapsed building!",
            "The storm went quiet suddenly, can we go out now?",
            "What to do if a hillside is sliding down toward our road?",
            "How do I clean and purify water when the taps are broken?",
            "Can you write a python script to scrape stock prices?"  # Guardrail test
        ]
        print("\n=== Running Disaster RAG Chatbot Verification Tests ===")
        for query in sample_queries:
            print(f"\n>>> Query: '{query}'")
            res = chatbot.generate_response(query)
            print(res["answer"])
            if res.get("sources"):
                print(f"[Matched Sources: {', '.join(s['disaster'] + ' - ' + s['phase'] for s in res['sources'])}]")
            print(f"[Provider: {res.get('provider')}] | [Allowed: {res.get('allowed')}]")
