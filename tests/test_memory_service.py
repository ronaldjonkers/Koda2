"""Tests for the memory service (CRUD, conversations, contacts)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from koda2.database import Base
from koda2.modules.memory.models import Contact, Conversation, MemoryEntry, UserProfile


@pytest.fixture
def mock_vector():
    """Create a mock VectorMemory."""
    v = MagicMock()
    v.add = MagicMock()
    v.search = MagicMock(return_value=[])
    v.delete = MagicMock()
    v.count = MagicMock(return_value=0)
    return v


@pytest.fixture
async def memory_service(mock_vector):
    """Create a MemoryService with real in-memory DB and mocked vector store."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    @asynccontextmanager
    async def mock_get_session():
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    with patch("koda2.modules.memory.service.VectorMemory", return_value=mock_vector), \
         patch("koda2.modules.memory.service.get_session", side_effect=mock_get_session):
        from koda2.modules.memory.service import MemoryService
        service = MemoryService()
        yield service

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


class TestMemoryServiceProfile:
    """Tests for user profile management."""

    @pytest.mark.asyncio
    async def test_get_or_create_profile_new(self, memory_service) -> None:
        """Creating a new profile when none exists."""
        profile = await memory_service.get_or_create_profile("new_user", display_name="Test")
        assert isinstance(profile, UserProfile)
        assert profile.user_id == "new_user"
        assert profile.display_name == "Test"

    @pytest.mark.asyncio
    async def test_get_or_create_profile_existing(self, memory_service) -> None:
        """Getting an existing profile returns the same one."""
        p1 = await memory_service.get_or_create_profile("user1", display_name="First")
        p2 = await memory_service.get_or_create_profile("user1")
        assert p2.display_name == "First"

    @pytest.mark.asyncio
    async def test_update_profile(self, memory_service) -> None:
        """Updating profile fields."""
        await memory_service.get_or_create_profile("u1", display_name="Old", timezone="UTC")
        profile = await memory_service.update_profile("u1", {"display_name": "New", "timezone": "CET"})
        assert profile.display_name == "New"
        assert profile.timezone == "CET"

    @pytest.mark.asyncio
    async def test_update_profile_not_found(self, memory_service) -> None:
        """Updating a non-existent profile raises ValueError."""
        with pytest.raises(ValueError, match="Profile not found"):
            await memory_service.update_profile("nonexistent", {"display_name": "X"})

    @pytest.mark.asyncio
    async def test_learn_preference(self, memory_service) -> None:
        """Learning a preference updates the profile."""
        await memory_service.get_or_create_profile("u1")
        await memory_service.learn_preference("u1", "theme", "dark")
        await memory_service.learn_preference("u1", "language", "nl")
        profile = await memory_service.get_or_create_profile("u1")
        assert profile.preferences["theme"] == "dark"
        assert profile.preferences["language"] == "nl"

    @pytest.mark.asyncio
    async def test_learn_preference_no_profile(self, memory_service) -> None:
        """Learning preference for nonexistent user is a no-op."""
        await memory_service.learn_preference("ghost", "key", "value")


class TestMemoryServiceConversation:
    """Tests for conversation management."""

    @pytest.mark.asyncio
    async def test_add_conversation(self, memory_service, mock_vector) -> None:
        """Adding a conversation stores it in DB and vector store."""
        convo = await memory_service.add_conversation("u1", "user", "Hello!", channel="telegram")
        assert isinstance(convo, Conversation)
        assert convo.role == "user"
        assert convo.content == "Hello!"
        mock_vector.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_add_conversation_creates_profile(self, memory_service, mock_vector) -> None:
        """Adding a conversation for unknown user auto-creates profile."""
        convo = await memory_service.add_conversation("new_user", "user", "Hi")
        assert isinstance(convo, Conversation)

    @pytest.mark.asyncio
    async def test_get_recent_conversations_empty(self, memory_service) -> None:
        """Getting conversations for unknown user returns empty list."""
        result = await memory_service.get_recent_conversations("unknown")
        assert result == []

    @pytest.mark.asyncio
    async def test_get_recent_conversations(self, memory_service, mock_vector) -> None:
        """Getting recent conversations returns them in order."""
        await memory_service.add_conversation("u1", "user", "First")
        await memory_service.add_conversation("u1", "assistant", "Second")
        result = await memory_service.get_recent_conversations("u1")
        assert len(result) == 2
        assert result[0].content == "First"
        assert result[1].content == "Second"

    def test_search_conversations(self, memory_service, mock_vector) -> None:
        """Searching conversations delegates to vector store."""
        mock_vector.search.return_value = [
            {"id": "c1", "content": "meeting notes", "metadata": {}, "distance": 0.1}
        ]
        results = memory_service.search_conversations("meeting", user_id="u1")
        assert len(results) == 1
        mock_vector.search.assert_called_once()


class TestMemoryServiceMemoryEntries:
    """Tests for structured memory entries."""

    @pytest.mark.asyncio
    async def test_store_memory(self, memory_service, mock_vector) -> None:
        """Storing a memory entry persists to DB and vector store."""
        entry = await memory_service.store_memory(
            "u1", "preference", "Likes morning meetings", importance=0.8, source="chat",
        )
        assert isinstance(entry, MemoryEntry)
        assert entry.category == "preference"
        assert entry.importance == 0.8
        mock_vector.add.assert_called_once()

    def test_recall(self, memory_service, mock_vector) -> None:
        """Recalling memories uses semantic search."""
        mock_vector.search.return_value = [
            {"id": "m1", "content": "morning meetings", "metadata": {"user_id": "u1"}, "distance": 0.05}
        ]
        results = memory_service.recall("meetings", user_id="u1")
        assert len(results) == 1
        assert "morning" in results[0]["content"]


class TestMemoryServiceContacts:
    """Tests for contact management."""

    @pytest.mark.asyncio
    async def test_add_contact(self, memory_service, mock_vector) -> None:
        """Adding a contact stores it in DB and vector store."""
        await memory_service.get_or_create_profile("u1")
        contact = await memory_service.add_contact(
            "u1", name="John Doe", email="john@example.com", company="Acme",
        )
        assert isinstance(contact, Contact)
        assert contact.name == "John Doe"
        mock_vector.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_find_contact_not_found(self, memory_service) -> None:
        """Finding a contact for unknown user returns None."""
        contact = await memory_service.find_contact("unknown", "Nobody")
        assert contact is None
