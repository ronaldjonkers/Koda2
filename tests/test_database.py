"""Tests for the database module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from koda2.database import Base, get_engine, get_session, get_session_factory, init_db, close_db


class TestDatabase:
    """Tests for database engine and session management."""

    @pytest.fixture(autouse=True)
    def reset_globals(self):
        """Reset module-level singletons."""
        import koda2.database as db
        db._engine = None
        db._session_factory = None
        yield
        db._engine = None
        db._session_factory = None

    def test_get_engine_creates_singleton(self) -> None:
        """get_engine returns the same engine instance."""
        with patch("koda2.database.get_settings") as mock:
            mock.return_value = MagicMock(
                database_url="sqlite+aiosqlite:///:memory:",
                koda2_env="test",
            )
            engine1 = get_engine()
            engine2 = get_engine()
            assert engine1 is engine2

    def test_get_session_factory_creates_singleton(self) -> None:
        """get_session_factory returns the same factory."""
        with patch("koda2.database.get_settings") as mock:
            mock.return_value = MagicMock(
                database_url="sqlite+aiosqlite:///:memory:",
                koda2_env="test",
            )
            f1 = get_session_factory()
            f2 = get_session_factory()
            assert f1 is f2

    @pytest.mark.asyncio
    async def test_init_db(self) -> None:
        """init_db creates all tables."""
        with patch("koda2.database.get_settings") as mock:
            mock.return_value = MagicMock(
                database_url="sqlite+aiosqlite:///:memory:",
                koda2_env="test",
            )
            await init_db()

    @pytest.mark.asyncio
    async def test_close_db(self) -> None:
        """close_db disposes engine."""
        with patch("koda2.database.get_settings") as mock:
            mock.return_value = MagicMock(
                database_url="sqlite+aiosqlite:///:memory:",
                koda2_env="test",
            )
            get_engine()
            await close_db()
            import koda2.database as db
            assert db._engine is None
            assert db._session_factory is None

    @pytest.mark.asyncio
    async def test_get_session_context_manager(self) -> None:
        """get_session provides a working session context."""
        with patch("koda2.database.get_settings") as mock:
            mock.return_value = MagicMock(
                database_url="sqlite+aiosqlite:///:memory:",
                koda2_env="test",
            )
            await init_db()
            async with get_session() as session:
                assert session is not None

    def test_base_has_naming_convention(self) -> None:
        """Base metadata uses proper naming conventions."""
        assert "pk" in Base.metadata.naming_convention
        assert "fk" in Base.metadata.naming_convention
        assert "uq" in Base.metadata.naming_convention
