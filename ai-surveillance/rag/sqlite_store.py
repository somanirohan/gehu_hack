"""SQLite Local Storage and Full-Text Search for Disaster Survival Guide.

Stores structured disaster survival protocols in a fast local SQLite database with
FTS5 full-text indexing for offline keyword lookups.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "storage" / "survival_guide.db"
DEFAULT_JSON_PATH = Path(__file__).resolve().parent / "survival_data.json"


class DisasterSQLiteStore:
    """Fast, local SQLite database for disaster survival protocol lookups."""

    def __init__(self, db_path: Optional[Path | str] = None):
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_tables()

    def _init_tables(self) -> None:
        """Initializes tables and FTS5 full-text search index."""
        cursor = self.conn.cursor()

        # Primary protocols table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS survival_protocols (
                id TEXT PRIMARY KEY,
                category TEXT NOT NULL,
                title TEXT NOT NULL,
                severity TEXT DEFAULT 'HIGH',
                critical_warning TEXT,
                actions TEXT NOT NULL,
                tags TEXT NOT NULL
            )
        """)

        # FTS5 virtual table for lightning-fast keyword and phrase search
        try:
            cursor.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS survival_protocols_fts USING fts5(
                    id UNINDEXED,
                    category,
                    title,
                    critical_warning,
                    actions,
                    tags,
                    tokenize = 'porter unicode61'
                )
            """)
            self.has_fts = True
        except sqlite3.OperationalError:
            self.has_fts = False

        self.conn.commit()

    def count(self) -> int:
        """Returns the number of indexed protocols."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM survival_protocols")
        return cursor.fetchone()[0]

    def ingest_from_json(self, json_path: Optional[Path | str] = None, force_refresh: bool = False) -> int:
        """Ingests protocols from survival_data.json into SQLite."""
        path = Path(json_path) if json_path else DEFAULT_JSON_PATH
        if not path.exists():
            raise FileNotFoundError(f"Survival data not found at {path}")

        if not force_refresh and self.count() > 0:
            return self.count()

        with open(path, "r", encoding="utf-8") as f:
            items: List[Dict[str, Any]] = json.load(f)

        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM survival_protocols")
        if self.has_fts:
            cursor.execute("DELETE FROM survival_protocols_fts")

        for item in items:
            doc_id = item.get("id", "")
            disaster = item.get("disaster", "")
            phase = item.get("phase", "")
            title = f"{disaster} - {phase}" if phase else disaster
            category = item.get("category", "")
            severity = item.get("severity", "CRITICAL")
            critical_warning = item.get("critical_alert", "")
            actions_text = item.get("content", "")
            tags_list = item.get("keywords", [])
            tags_text = ", ".join(tags_list)

            cursor.execute("""
                INSERT OR REPLACE INTO survival_protocols
                (id, category, title, severity, critical_warning, actions, tags)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (doc_id, category, title, severity, critical_warning, actions_text, tags_text))

            if self.has_fts:
                cursor.execute("""
                    INSERT INTO survival_protocols_fts
                    (id, category, title, critical_warning, actions, tags)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (doc_id, category, title, critical_warning, actions_text, tags_text))

        self.conn.commit()
        return len(items)

    def search(self, query: str, limit: int = 3) -> List[Dict[str, Any]]:
        """Searches protocols using FTS5 or keyword matching."""
        cursor = self.conn.cursor()
        cleaned_query = query.strip()
        if not cleaned_query:
            cursor.execute("SELECT * FROM survival_protocols LIMIT ?", (limit,))
            return [dict(r) for r in cursor.fetchall()]

        results = []

        if self.has_fts:
            # Extract alphanumeric tokens for FTS query
            tokens = re.findall(r"\w+", cleaned_query.lower())
            # Remove common English stop words
            stopwords = {"the", "a", "an", "is", "in", "at", "to", "for", "of", "and", "or", "what", "how", "do", "i", "we", "can", "if"}
            meaningful_tokens = [t for t in tokens if t not in stopwords and len(t) > 2]

            if meaningful_tokens:
                fts_query = " OR ".join(f'"{t}"*' for t in meaningful_tokens)
                try:
                    cursor.execute("""
                        SELECT p.*, bm25(survival_protocols_fts) AS rank
                        FROM survival_protocols_fts fts
                        JOIN survival_protocols p ON p.id = fts.id
                        WHERE survival_protocols_fts MATCH ?
                        ORDER BY rank
                        LIMIT ?
                    """, (fts_query, limit))
                    results = [dict(r) for r in cursor.fetchall()]
                except sqlite3.OperationalError:
                    results = []

        if not results:
            # Fallback to LIKE keyword search
            like_terms = [f"%{t}%" for t in re.findall(r"\w+", cleaned_query) if len(t) > 2]
            if like_terms:
                clauses = " OR ".join(["title LIKE ? OR tags LIKE ? OR actions LIKE ?"] * len(like_terms))
                params = []
                for term in like_terms:
                    params.extend([term, term, term])
                params.append(limit)
                cursor.execute(f"SELECT * FROM survival_protocols WHERE {clauses} LIMIT ?", params)
                results = [dict(r) for r in cursor.fetchall()]

        if not results:
            # General fallback: return top high-priority protocols
            cursor.execute("SELECT * FROM survival_protocols ORDER BY severity DESC LIMIT ?", (limit,))
            results = [dict(r) for r in cursor.fetchall()]

        return results

    def close(self) -> None:
        """Closes the database connection."""
        self.conn.close()


if __name__ == "__main__":
    store = DisasterSQLiteStore()
    count = store.ingest_from_json(force_refresh=True)
    print(f"Ingested {count} disaster protocols into SQLite ({store.db_path})")

    # Quick test search
    test_queries = [
        "earthquake rubble collapse trapped",
        "cyclone calm eye",
        "purify water boil",
        "burn fire smoke"
    ]
    for q in test_queries:
        res = store.search(q, limit=1)
        if res:
            print(f"\n[Query: '{q}'] -> Matched: {res[0]['title']} ({res[0]['category']})")
            if res[0]['critical_warning']:
                print(f"  Warning: {res[0]['critical_warning']}")
