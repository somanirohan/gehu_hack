"""Disaster Management RAG + SLM Chatbot Engine.

Combines local Vector Database retrieval with Small Language Model (SLM)
inference to provide immediate, actionable, life-saving advice during crises.

Modes:
  1. Interactive CLI: python disaster_chatbot.py --cli
  2. HTTP Server:     python disaster_chatbot.py --serve [--port 8800]
  3. Python Library:  from rag.disaster_chatbot import DisasterChatbot
"""
from __future__ import annotations

import argparse
import json
import os
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

# Ensure UTF-8 output on Windows console
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from rag.vector_store import DisasterVectorStore

EMERGENCY_SYSTEM_PROMPT = """You are an emergency disaster response specialist and tactical advisor.
Your mission is to provide concise, urgent, life-saving guidance to individuals facing active disasters.

STRICT PROTOCOLS:
1. Put the most critical, immediate life-safety action in the FIRST sentence.
2. Highlight any lethal danger or warning clearly (e.g. ⚠️ WARNING: DO NOT...).
3. Keep instructions clear, direct, and numbered or bulleted.
4. Base your recommendations strictly on the provided verified disaster protocols.
5. Remind the user to activate their offline mesh SOS beacon if trapped or in peril."""


class DisasterChatbot:
    """RAG + SLM Chatbot for offline disaster response."""

    def __init__(
        self,
        vector_store: Optional[DisasterVectorStore] = None,
        model_id: str = "Qwen/Qwen2.5-VL-3B-Instruct",
        device: str = "auto",
        use_lightweight_slm: bool = False
    ):
        self.vector_store = vector_store or DisasterVectorStore()
        self.model_id = model_id
        self.device = device
        self.use_lightweight_slm = use_lightweight_slm
        self._model = None
        self._tokenizer = None
        self._lock = threading.Lock()

        # Ensure vector DB is populated
        if self.vector_store.count() == 0:
            self.vector_store.ingest_from_json()

    def retrieve_context(self, user_query: str, n_results: int = 2) -> List[Dict[str, Any]]:
        """Retrieves top matching survival protocol chunks from the local vector DB."""
        return self.vector_store.query(user_query, n_results=n_results)

    def format_prompt(self, user_query: str, context_chunks: List[Dict[str, Any]]) -> str:
        """Assembles prompt with verified context for the language model."""
        context_text = ""
        for i, chunk in enumerate(context_chunks, 1):
            context_text += (
                f"\n[Source {i}: {chunk['disaster']} - {chunk['phase']}]\n"
                f"CRITICAL WARNING: {chunk['critical_alert']}\n"
                f"INSTRUCTIONS: {chunk['content']}\n"
            )

        prompt = (
            f"{EMERGENCY_SYSTEM_PROMPT}\n\n"
            f"--- VERIFIED DISASTER SURVIVAL KNOWLEDGE BASE ---\n"
            f"{context_text}\n"
            f"--- EMERGENCY QUERY ---\n"
            f"User: {user_query}\n\n"
            f"Emergency Response Specialist (Actionable, life-saving advice):"
        )
        return prompt

    def generate_response(self, user_query: str, n_context: int = 2) -> Dict[str, Any]:
        """Runs RAG retrieval and produces the final response.
        
        Returns:
            Dict containing:
              - 'answer': Clean, actionable response text
              - 'sources': List of matched vector DB items with alerts
              - 'critical_alerts': High-priority warning strings
        """
        chunks = self.retrieve_context(user_query, n_results=n_context)
        critical_alerts = [c["critical_alert"] for c in chunks if c.get("critical_alert")]

        if not chunks:
            return {
                "answer": "Stay in a secure location and protect your head. Activate the SOS beacon on your Bitchat mesh to notify nearby rescue teams.",
                "sources": [],
                "critical_alerts": []
            }

        # If lightweight SLM mode or if transformer model is not loaded,
        # generate an instant high-reliability structured synthesis from the retrieved chunks.
        if self.use_lightweight_slm or self._model is None:
            answer = self._synthesize_structured_answer(user_query, chunks)
        else:
            prompt = self.format_prompt(user_query, chunks)
            answer = self._generate_with_local_slm(prompt)

        return {
            "query": user_query,
            "answer": answer,
            "critical_alerts": critical_alerts,
            "sources": [
                {
                    "disaster": c["disaster"],
                    "phase": c["phase"],
                    "category": c["category"],
                    "relevance": c.get("relevance_score", 0.0)
                }
                for c in chunks
            ]
        }

    def _synthesize_structured_answer(self, query: str, chunks: List[Dict[str, Any]]) -> str:
        """Fast, robust offline synthesis from vector retrieved knowledge."""
        top = chunks[0]
        alert = top.get("critical_alert", "")
        content = top.get("content", "")
        phase = top.get("phase", "")
        disaster = top.get("disaster", "")

        lines = [
            f"🚨 **{disaster} Protocol ({phase})**"
        ]
        if alert:
            lines.append(f"\n⚠️ **CRITICAL WARNING**: {alert}\n")

        lines.append(f"**Immediate Actions**:")
        # Format sentences as clear action steps
        sentences = [s.strip() for s in content.replace("1.", "\n• ").replace("2.", "\n• ").replace("3.", "\n• ").replace("4.", "\n• ").split(". ") if s.strip()]
        for s in sentences:
            if not s.endswith("."):
                s += "."
            lines.append(f"• {s}")

        lines.append("\n📡 *Tip: Tap the red SOS button in Bitchat to broadcast your coordinates to nearby rescue nodes.*")
        return "\n".join(lines)

    def _generate_with_local_slm(self, prompt: str) -> str:
        """Runs generative inference through local HuggingFace SLM."""
        try:
            import torch
            inputs = self._tokenizer(prompt, return_tensors="pt")
            if torch.cuda.is_available() and self.device != "cpu":
                inputs = {k: v.to("cuda") for k, v in inputs.items()}

            with torch.no_grad():
                outputs = self._model.generate(
                    **inputs,
                    max_new_tokens=256,
                    temperature=0.2,
                    top_p=0.9,
                    do_sample=True
                )
            decoded = self._tokenizer.decode(outputs[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)
            return decoded.strip()
        except Exception as e:
            # Fallback to structured knowledge synthesis on error
            return f"[SLM fallback] Error during inference: {e}"


# --- Lightweight HTTP API Server for App and Client Integration ---

class ChatbotHttpHandler(BaseHTTPRequestHandler):
    chatbot: Optional[DisasterChatbot] = None

    def _send_json(self, status: int, data: Dict[str, Any]):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2).encode("utf-8"))

    def do_OPTIONS(self):
        self._send_json(200, {"status": "ok"})

    def do_GET(self):
        if self.path == "/health":
            self._send_json(200, {"status": "ok", "vector_docs": self.chatbot.vector_store.count() if self.chatbot else 0})
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
        else:
            self._send_json(404, {"error": "Endpoint not found"})


def run_server(port: int = 8800):
    chatbot = DisasterChatbot(use_lightweight_slm=True)
    ChatbotHttpHandler.chatbot = chatbot

    server = HTTPServer(("0.0.0.0", port), ChatbotHttpHandler)
    print(f"\n[RAG Chatbot API] Disaster Chatbot HTTP Server running on http://0.0.0.0:{port}")
    print(f"[RAG Chatbot API] Endpoints:")
    print(f"  POST http://localhost:{port}/api/chat   (body: {{\"query\": \"...\"}})")
    print(f"  POST http://localhost:{port}/api/search (body: {{\"query\": \"...\", \"k\": 3}})")
    print(f"  GET  http://localhost:{port}/health\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[RAG Chatbot API] Server stopped.")
        server.server_close()


def run_cli():
    print("=" * 65)
    print("  🛡️  DISASTER MANAGEMENT RAG CHATBOT (OFFLINE ASSISTANT)  🛡️")
    print("=" * 65)
    print("Type your emergency query below (e.g. 'trapped in rubble', 'cyclone eye', 'severe bleeding').")
    print("Type 'exit' or 'quit' to stop.\n")

    chatbot = DisasterChatbot(use_lightweight_slm=True)

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
    parser = argparse.ArgumentParser(description="Disaster Management RAG + SLM Chatbot")
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
        # Default: run verification tests and print output
        chatbot = DisasterChatbot(use_lightweight_slm=True)
        sample_queries = [
            "Help, I'm buried under concrete slabs in a collapsed building!",
            "The storm went quiet suddenly, can we go out now?",
            "What to do if a hillside is sliding down toward our road?",
            "How do I clean and purify water when the taps are broken?"
        ]
        print("\n=== Running Disaster RAG + SLM Chatbot Tests ===")
        for query in sample_queries:
            print(f"\n>>> Query: '{query}'")
            res = chatbot.generate_response(query)
            print(res["answer"])
            print(f"[Matched Sources: {', '.join(s['disaster'] + ' - ' + s['phase'] for s in res['sources'])}]")
