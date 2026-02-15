"""Memory service orchestrating structured DB + vector search."""

from __future__ import annotations

import datetime as dt
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from koda2.database import get_session
from koda2.logging_config import get_logger
from koda2.modules.memory.models import Contact, Conversation, MemoryEntry, UserProfile
from koda2.modules.memory.vector_store import VectorMemory

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
            profile.updated_at = dt.datetime.now(dt.UTC)
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
            profile.updated_at = dt.datetime.now(dt.UTC)
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
        self, user_id: str, limit: int = 20, max_age_hours: float = 0,
    ) -> list[Conversation]:
        """Get the most recent conversation turns for a user.

        Args:
            max_age_hours: If >0, only return conversations from the last N hours.
                           This prevents stale context from old sessions bleeding in.
        """
        async with get_session() as session:
            result = await session.execute(
                select(UserProfile).where(UserProfile.user_id == user_id)
            )
            profile = result.scalar_one_or_none()
            if profile is None:
                return []

            stmt = (
                select(Conversation)
                .where(Conversation.profile_id == profile.id)
                .order_by(Conversation.created_at.desc())
                .limit(limit)
            )
            if max_age_hours > 0:
                cutoff = dt.datetime.now(dt.UTC) - dt.timedelta(hours=max_age_hours)
                stmt = stmt.where(Conversation.created_at >= cutoff)

            result = await session.execute(stmt)
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

    def recall(
        self, query: str, user_id: Optional[str] = None, n: int = 5,
        max_distance: float = 0,
    ) -> list[dict]:
        """Recall relevant memories using semantic search.

        Args:
            max_distance: If >0, discard results with cosine distance above this
                          threshold.  Lower distance = more relevant.  Good default
                          for cosine space: 0.35–0.45.
        """
        where = {"user_id": user_id} if user_id else None
        results = self.vector.search(query, n_results=n, where=where)
        if max_distance > 0:
            results = [r for r in results if r.get("distance", 1.0) <= max_distance]
        return results

    async def list_memories(
        self,
        user_id: str,
        category: Optional[str] = None,
        limit: int = 50,
    ) -> list[MemoryEntry]:
        """List all stored memory entries for a user, optionally filtered by category."""
        async with get_session() as session:
            stmt = (
                select(MemoryEntry)
                .where(MemoryEntry.user_id == user_id)
                .where(MemoryEntry.active == True)  # noqa: E712
                .order_by(MemoryEntry.created_at.desc())
                .limit(limit)
            )
            if category:
                stmt = stmt.where(MemoryEntry.category == category)
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def update_memory(
        self,
        memory_id: str,
        content: str | None = None,
        category: str | None = None,
        importance: float | None = None,
    ) -> MemoryEntry | None:
        """Update a memory entry's content, category, or importance."""
        async with get_session() as session:
            result = await session.execute(
                select(MemoryEntry).where(MemoryEntry.id == memory_id)
            )
            entry = result.scalar_one_or_none()
            if not entry:
                return None
            if content is not None:
                entry.content = content
            if category is not None:
                entry.category = category
            if importance is not None:
                entry.importance = importance
            entry.updated_at = dt.datetime.now(dt.UTC)
            await session.flush()

            # Re-index in vector store with updated content
            if content is not None:
                try:
                    self.vector.add(
                        doc_id=memory_id,
                        text=entry.content,
                        metadata={
                            "user_id": entry.user_id,
                            "category": entry.category,
                            "importance": entry.importance,
                        },
                    )
                except Exception:
                    pass
            logger.info("memory_updated", memory_id=memory_id)
            return entry

    async def list_all_memories(
        self,
        category: str | None = None,
        limit: int = 100,
    ) -> list[MemoryEntry]:
        """List all active memory entries across all users (for dashboard)."""
        async with get_session() as session:
            stmt = (
                select(MemoryEntry)
                .where(MemoryEntry.active == True)  # noqa: E712
                .order_by(MemoryEntry.updated_at.desc())
                .limit(limit)
            )
            if category:
                stmt = stmt.where(MemoryEntry.category == category)
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def delete_memory(self, memory_id: str) -> bool:
        """Delete a memory entry by ID (soft-delete: sets active=False)."""
        async with get_session() as session:
            result = await session.execute(
                select(MemoryEntry).where(MemoryEntry.id == memory_id)
            )
            entry = result.scalar_one_or_none()
            if not entry:
                return False
            entry.active = False
            await session.flush()
            # Also remove from vector store
            try:
                self.vector.delete(memory_id)
            except Exception:
                pass
            logger.info("memory_deleted", memory_id=memory_id)
            return True

    async def get_memory_stats(self, user_id: str) -> dict[str, Any]:
        """Get memory statistics for a user."""
        async with get_session() as session:
            result = await session.execute(
                select(MemoryEntry)
                .where(MemoryEntry.user_id == user_id)
                .where(MemoryEntry.active == True)  # noqa: E712
            )
            entries = list(result.scalars().all())
            categories: dict[str, int] = {}
            for e in entries:
                categories[e.category] = categories.get(e.category, 0) + 1
            return {
                "total": len(entries),
                "categories": categories,
                "vector_count": self.vector.count(),
            }

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
            return result.scalars().first()
