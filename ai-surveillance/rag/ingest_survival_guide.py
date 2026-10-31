"""CLI tool to ingest or re-index the Disaster Survival Guide into ChromaDB."""
import sys
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from rag.vector_store import DisasterVectorStore
except ImportError:
    from vector_store import DisasterVectorStore


def main():
    print("[RAG] Connecting to local persistent ChromaDB...")
    store = DisasterVectorStore()
    print(f"[RAG] Existing documents in store: {store.count()}")
    print("[RAG] Ingesting survival guide points...")
    count = store.ingest_from_json(force_refresh=True)
    print(f"[RAG] Successfully ingested {count} survival protocol chunks into local vector DB!")
    print(f"[RAG] Database location: {store.storage_dir}")


if __name__ == "__main__":
    main()
