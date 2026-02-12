"""Memory service orchestrating structured DB + vector search."""

from __future__ import annotations

import datetime as dt
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from executiveai.database import get_session
from executiveai.logging_config import get_logger
from executiveai.modules.memory.models import Contact, Conversation, MemoryEntry, UserProfile
from executiveai.modules.memory.vector_store import VectorMemory

logger = get_logger(__name__)


class MemoryService:
    """Unified memory service combining relational and vector storage."""

    def __init__(self) -> None:
        self.vector = VectorMemory()

    # ── User Profile ─────────────────────────────────────────────────

    async def get_or_create_profile(self, user_id: str, **kwargs: Any) -> UserProfile:
        """Retrieve existing profile or create a new one."""
        async with get_session() as session:
            result = await session.execute(
                select(UserProfile).where(UserProfile.user_id == user_id)
            )
            profile = result.scalar_one_or_none()
            if profile is None:
                profile = UserProfile(user_id=user_id, **kwargs)
                session.add(profile)
                await session.flush()
                logger.info("profile_created", user_id=user_id)
            return profile

    async def update_profile(self, user_id: str, updates: dict[str, Any]) -> UserProfile:
        """Update user profile fields."""
        async with get_session() as session:
            result = await session.execute(
                select(UserProfile).where(UserProfile.user_id == user_id)
            )
            profile = result.scalar_one_or_none()
            if profile is None:
                raise ValueError(f"Profile not found for user_id={user_id}")
            for key, value in updates.items():
                if hasattr(profile, key):
                    setattr(profile, key, value)
            profile.updated_at = dt.datetime.utcnow()
            await session.flush()
            logger.info("profile_updated", user_id=user_id, fields=list(updates.keys()))
            return profile

    async def learn_preference(self, user_id: str, key: str, value: Any) -> None:
        """Automatically update a user preference from interactions."""
        async with get_session() as session:
            result = await session.execute(
                select(UserProfile).where(UserProfile.user_id == user_id)
            )
            profile = result.scalar_one_or_none()
            if profile is None:
                return
            prefs = dict(profile.preferences or {})
            prefs[key] = value
            profile.preferences = prefs
            profile.updated_at = dt.datetime.utcnow()
            await session.flush()
            logger.debug("preference_learned", user_id=user_id, key=key)

    # ── Conversations ────────────────────────────────────────────────

    async def add_conversation(
        self,
        user_id: str,
        role: str,
        content: str,
        channel: str = "api",
        model: str = "",
        tokens_used: int = 0,
    ) -> Conversation:
        """Store a conversation turn."""
        async with get_session() as session:
            result = await session.execute(
                select(UserProfile).where(UserProfile.user_id == user_id)
            )
            profile = result.scalar_one_or_none()
            if profile is None:
                profile = UserProfile(user_id=user_id)
                session.add(profile)
                await session.flush()

            convo = Conversation(
                profile_id=profile.id,
                role=role,
                content=content,
                channel=channel,
                model=model,
                tokens_used=tokens_used,
            )
            session.add(convo)
            await session.flush()

            self.vector.add(
                doc_id=convo.id,
                text=content,
                metadata={"user_id": user_id, "role": role, "channel": channel},
            )
            return convo

    async def get_recent_conversations(
        self, user_id: str, limit: int = 20
    ) -> list[Conversation]:
        """Get the most recent conversation turns for a user."""
        async with get_session() as session:
            result = await session.execute(
                select(UserProfile).where(UserProfile.user_id == user_id)
            )
            profile = result.scalar_one_or_none()
            if profile is None:
                return []

            result = await session.execute(
                select(Conversation)
                .where(Conversation.profile_id == profile.id)
                .order_by(Conversation.created_at.desc())
                .limit(limit)
            )
            return list(reversed(result.scalars().all()))

    def search_conversations(self, query: str, user_id: Optional[str] = None, n: int = 5) -> list[dict]:
        """Semantic search across conversation history."""
        where = {"user_id": user_id} if user_id else None
        return self.vector.search(query, n_results=n, where=where)

    # ── Memory Entries ───────────────────────────────────────────────

    async def store_memory(
        self,
        user_id: str,
        category: str,
        content: str,
        importance: float = 0.5,
        source: str = "",
    ) -> MemoryEntry:
        """Store a structured memory entry with vector indexing."""
        entry = MemoryEntry(
            user_id=user_id,
            category=category,
            content=content,
            importance=importance,
            source=source,
        )
        async with get_session() as session:
            session.add(entry)
            await session.flush()

            self.vector.add(
                doc_id=entry.id,
                text=content,
                metadata={"user_id": user_id, "category": category, "importance": importance},
            )
            logger.debug("memory_stored", user_id=user_id, category=category)
            return entry

    def recall(self, query: str, user_id: Optional[str] = None, n: int = 5) -> list[dict]:
        """Recall relevant memories using semantic search."""
        where = {"user_id": user_id} if user_id else None
        return self.vector.search(query, n_results=n, where=where)

    # ── Contacts ─────────────────────────────────────────────────────

    async def add_contact(self, user_id: str, **kwargs: Any) -> Contact:
        """Add a contact to the user's profile."""
        async with get_session() as session:
            result = await session.execute(
                select(UserProfile).where(UserProfile.user_id == user_id)
            )
            profile = result.scalar_one_or_none()
            if profile is None:
                profile = UserProfile(user_id=user_id)
                session.add(profile)
                await session.flush()

            contact = Contact(profile_id=profile.id, **kwargs)
            session.add(contact)
            await session.flush()

            self.vector.add(
                doc_id=f"contact_{contact.id}",
                text=f"{contact.name} {contact.email} {contact.company} {contact.notes}",
                metadata={"user_id": user_id, "type": "contact"},
            )
            return contact

    async def find_contact(self, user_id: str, name: str) -> Optional[Contact]:
        """Find a contact by name (exact or partial match)."""
        async with get_session() as session:
            result = await session.execute(
                select(UserProfile).where(UserProfile.user_id == user_id)
            )
            profile = result.scalar_one_or_none()
            if profile is None:
                return None

            result = await session.execute(
                select(Contact)
                .where(Contact.profile_id == profile.id)
                .where(Contact.name.ilike(f"%{name}%"))
            )
            return result.scalar_one_or_none()
