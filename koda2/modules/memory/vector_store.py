"""ChromaDB vector store for semantic memory search."""

from __future__ import annotations

from typing import Optional

import chromadb
from chromadb.config import Settings as ChromaSettings

from koda2.config import get_settings
from koda2.logging_config import get_logger

logger = get_logger(__name__)

_client: Optional[chromadb.ClientAPI] = None


def get_chroma_client() -> chromadb.ClientAPI:
    """Return the singleton ChromaDB client."""
    global _client
    if _client is None:
        settings = get_settings()
        _client = chromadb.PersistentClient(
            path=settings.chroma_persist_dir,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        logger.info("chroma_initialized", path=settings.chroma_persist_dir)
    return _client


def get_collection(name: str = "executive_memory") -> chromadb.Collection:
    """Get or create a named ChromaDB collection."""
    client = get_chroma_client()
    return client.get_or_create_collection(
        name=name,
        metadata={"hnsw:space": "cosine"},
    )


class VectorMemory:
    """Semantic memory backed by ChromaDB."""

    def __init__(self, collection_name: str = "executive_memory") -> None:
        self.collection = get_collection(collection_name)

    def add(
        self,
        doc_id: str,
        text: str,
        metadata: Optional[dict] = None,
    ) -> None:
        """Add or update a document in the vector store."""
        meta = metadata or {}
        if not meta:
            meta = {"_source": "koda2"}
        self.collection.upsert(
            ids=[doc_id],
            documents=[text],
            metadatas=[meta],
        )
        logger.debug("vector_upserted", doc_id=doc_id)

    def search(
        self,
        query: str,
        n_results: int = 5,
        where: Optional[dict] = None,
    ) -> list[dict]:
        """Semantic search returning the most relevant documents."""
        kwargs: dict = {"query_texts": [query], "n_results": n_results}
        if where:
            kwargs["where"] = where

        results = self.collection.query(**kwargs)
        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]
        ids = results.get("ids", [[]])[0]

        return [
            {
                "id": ids[i],
                "content": documents[i],
                "metadata": metadatas[i],
                "distance": distances[i],
            }
            for i in range(len(documents))
        ]

    def delete(self, doc_id: str) -> None:
        """Remove a document from the vector store."""
        self.collection.delete(ids=[doc_id])
        logger.debug("vector_deleted", doc_id=doc_id)

    def count(self) -> int:
        """Return the total number of documents."""
        return self.collection.count()
