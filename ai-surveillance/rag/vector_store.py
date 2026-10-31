"""Local Vector Database for Disaster Management Survival Guide.

Uses persistent ChromaDB for high-performance offline semantic search
over disaster management protocols and survival tips.
"""
from __future__ import annotations

import json
import os
import sys

# Silence ONNX Runtime TensorRT fallback notices
os.environ.setdefault("ORT_LOGGING_LEVEL", "3")

from pathlib import Path
from typing import Any, Dict, List, Optional

import chromadb
from chromadb.config import Settings
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

DEFAULT_STORAGE_DIR = Path(__file__).resolve().parent.parent / "storage" / "survival_vectordb"
DATA_JSON_PATH = Path(__file__).resolve().parent / "survival_data.json"
COLLECTION_NAME = "disaster_survival_guide"


class DisasterVectorStore:
    """Manages the persistent vector database for disaster survival points."""

    def __init__(self, storage_dir: Optional[Path | str] = None):
        self.storage_dir = Path(storage_dir) if storage_dir else DEFAULT_STORAGE_DIR
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        try:
            self.embedding_fn = SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")
        except Exception:
            from chromadb.utils.embedding_functions import DefaultEmbeddingFunction
            self.embedding_fn = DefaultEmbeddingFunction()

        # Persistent ChromaDB client
        self.client = chromadb.PersistentClient(
            path=str(self.storage_dir),
            settings=Settings(anonymized_telemetry=False)
        )

        try:
            self.collection = self.client.get_or_create_collection(
                name=COLLECTION_NAME,
                embedding_function=self.embedding_fn,
                metadata={"description": "Disaster Survival Guide Knowledge Base for RAG"}
            )
        except ValueError:
            # Stored collection had different embedding function; recreate
            self.client.delete_collection(COLLECTION_NAME)
            self.collection = self.client.create_collection(
                name=COLLECTION_NAME,
                embedding_function=self.embedding_fn,
                metadata={"description": "Disaster Survival Guide Knowledge Base for RAG"}
            )

    def count(self) -> int:
        """Returns the number of indexed survival documents."""
        return self.collection.count()

    def ingest_from_json(self, json_path: Optional[Path | str] = None, force_refresh: bool = False) -> int:
        """Loads and indexes the survival points into the vector database.
        
        Args:
            json_path: Path to survival_data.json
            force_refresh: If True, clears existing records and re-indexes.
            
        Returns:
            Number of documents indexed.
        """
        path = Path(json_path) if json_path else DATA_JSON_PATH
        if not path.exists():
            raise FileNotFoundError(f"Survival data not found at: {path}")

        with open(path, "r", encoding="utf-8") as f:
            items: List[Dict[str, Any]] = json.load(f)

        if force_refresh and self.count() > 0:
            # Delete and recreate collection
            self.client.delete_collection(COLLECTION_NAME)
            self.collection = self.client.create_collection(
                name=COLLECTION_NAME,
                embedding_function=self.embedding_fn,
                metadata={"description": "Disaster Survival Guide Knowledge Base for RAG"}
            )

        ids: List[str] = []
        documents: List[str] = []
        metadatas: List[Dict[str, Any]] = []

        for item in items:
            doc_id = item["id"]
            title = item.get("disaster", "")
            phase = item.get("phase", "")
            category = item.get("category", "")
            alert = item.get("critical_alert", "")
            content = item.get("content", "")
            keywords = ", ".join(item.get("keywords", []))

            # Rich text for embedding representation
            embed_text = f"Disaster: {title}\nPhase: {phase}\nCategory: {category}\nWarning: {alert}\nInstructions: {content}\nKeywords: {keywords}"

            ids.append(doc_id)
            documents.append(embed_text)
            metadatas.append({
                "id": doc_id,
                "disaster": title,
                "category": category,
                "phase": phase,
                "critical_alert": alert,
                "content": content
            })

        # Upsert documents into vector DB
        self.collection.upsert(
            ids=ids,
            documents=documents,
            metadatas=metadatas
        )

        return self.count()

    def query(
        self,
        query_text: str,
        n_results: int = 3,
        disaster_filter: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Queries the vector database for survival protocols relevant to the query.
        
        Args:
            query_text: The user's question or situation description.
            n_results: Number of top chunks to return.
            disaster_filter: Optional filter by disaster name.
            
        Returns:
            List of matching records with metadata and relevance distance.
        """
        if self.count() == 0:
            self.ingest_from_json()

        where_clause = None
        if disaster_filter:
            where_clause = {"disaster": disaster_filter}

        results = self.collection.query(
            query_texts=[query_text],
            n_results=min(n_results, max(1, self.count())),
            where=where_clause
        )

        matched_records: List[Dict[str, Any]] = []
        if results and results["documents"]:
            docs = results["documents"][0]
            metas = results["metadatas"][0] if results.get("metadatas") else []
            distances = results["distances"][0] if results.get("distances") else []

            for idx, doc in enumerate(docs):
                meta = metas[idx] if idx < len(metas) else {}
                dist = distances[idx] if idx < len(distances) else 0.0
                matched_records.append({
                    "id": meta.get("id"),
                    "disaster": meta.get("disaster"),
                    "category": meta.get("category"),
                    "phase": meta.get("phase"),
                    "critical_alert": meta.get("critical_alert"),
                    "content": meta.get("content"),
                    "document_text": doc,
                    "distance": dist,
                    "relevance_score": round(max(0.0, 1.0 - (dist / 2.0)), 4)
                })

        return matched_records


if __name__ == "__main__":
    db = DisasterVectorStore()
    count = db.ingest_from_json(force_refresh=True)
    print(f"Successfully indexed {count} disaster survival documents in ChromaDB!")

    test_queries = [
        "I am trapped under concrete rubble in a collapsed building, how can I alert rescue teams?",
        "The wind suddenly stopped in the middle of a cyclone, is it safe to leave?",
        "Someone has a deep wound and is bleeding heavily from their leg, how to stop it?",
        "How can I signal search helicopters if there is no cell signal or electricity?"
    ]

    print("\n--- Running Verification Queries ---")
    for q in test_queries:
        print(f"\nQuery: '{q}'")
        matches = db.query(q, n_results=1)
        for m in matches:
            print(f"-> Matched: [{m['disaster']}] Phase: {m['phase']} (Score: {m['relevance_score']})")
            print(f"   Alert: {m['critical_alert']}")
