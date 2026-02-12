"""Tests for the memory and user profile module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from executiveai.modules.memory.vector_store import VectorMemory


class TestVectorMemory:
    """Tests for the ChromaDB vector memory store."""

    @pytest.fixture
    def vector_memory(self, tmp_path) -> VectorMemory:
        """Create a VectorMemory instance with a temp directory."""
        with patch("executiveai.modules.memory.vector_store.get_settings") as mock:
            mock.return_value = MagicMock(chroma_persist_dir=str(tmp_path / "chroma"))
            # Reset the client singleton
            import executiveai.modules.memory.vector_store as vs
            vs._client = None
            return VectorMemory(collection_name="test_memory")

    def test_add_and_search(self, vector_memory: VectorMemory) -> None:
        """Adding a document makes it searchable."""
        vector_memory.add("doc1", "Meeting with John about project Alpha", {"user_id": "u1"})
        vector_memory.add("doc2", "Lunch reservation at Italian restaurant", {"user_id": "u1"})
        vector_memory.add("doc3", "Review quarterly financial report", {"user_id": "u1"})

        results = vector_memory.search("project meeting", n_results=2)
        assert len(results) > 0
        assert results[0]["id"] == "doc1"

    def test_add_and_count(self, vector_memory: VectorMemory) -> None:
        """Count reflects the number of added documents."""
        assert vector_memory.count() == 0
        vector_memory.add("d1", "First document")
        vector_memory.add("d2", "Second document")
        assert vector_memory.count() == 2

    def test_upsert(self, vector_memory: VectorMemory) -> None:
        """Upserting the same ID replaces the document."""
        vector_memory.add("d1", "Original content")
        vector_memory.add("d1", "Updated content")
        assert vector_memory.count() == 1
        results = vector_memory.search("Updated", n_results=1)
        assert "Updated" in results[0]["content"]

    def test_delete(self, vector_memory: VectorMemory) -> None:
        """Deleting removes the document."""
        vector_memory.add("d1", "To be deleted")
        assert vector_memory.count() == 1
        vector_memory.delete("d1")
        assert vector_memory.count() == 0

    def test_search_with_filter(self, vector_memory: VectorMemory) -> None:
        """Search can be filtered by metadata."""
        vector_memory.add("d1", "User A data", {"user_id": "a"})
        vector_memory.add("d2", "User B data", {"user_id": "b"})
        results = vector_memory.search("data", n_results=5, where={"user_id": "a"})
        assert all(r["metadata"]["user_id"] == "a" for r in results)

    def test_search_empty_collection(self, vector_memory: VectorMemory) -> None:
        """Searching an empty collection returns empty list."""
        results = vector_memory.search("anything")
        assert results == []
