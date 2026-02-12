"""Tests for the FastAPI API routes."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from koda2.api.routes import set_orchestrator


@pytest.fixture
def mock_orchestrator():
    """Create a mock orchestrator with all required services."""
    orch = MagicMock()

    # Mock process_message
    orch.process_message = AsyncMock(return_value={
        "response": "Hello! How can I help?",
        "intent": "general_chat",
        "entities": {},
        "actions": [],
        "tokens_used": 30,
        "model": "gpt-4o",
    })

    # Mock calendar
    orch.calendar.active_providers = []
    orch.calendar.list_events = AsyncMock(return_value=[])
    orch.calendar.list_all_calendars = AsyncMock(return_value={})
    orch.calendar.schedule_with_prep = AsyncMock(return_value=(
        MagicMock(id="ev1", title="Test", provider_id="p1"),
        None,
    ))

    # Mock email
    orch.email.imap_configured = False
    orch.email.smtp_configured = False
    orch.email.fetch_emails = AsyncMock(return_value=[])
    orch.email.send_email = AsyncMock(return_value=True)

    # Mock LLM
    orch.llm.available_providers = []

    # Mock telegram / whatsapp
    orch.telegram.is_configured = False
    orch.whatsapp.is_configured = False

    # Mock self-improve
    orch.self_improve.list_plugins.return_value = []
    orch.self_improve.list_capabilities.return_value = {"send_email": "email"}
    orch.self_improve.generate_plugin = AsyncMock(return_value="/plugins/test.py")

    # Mock scheduler
    orch.scheduler.list_tasks.return_value = []

    # Mock memory
    orch.memory.recall.return_value = []
    orch.memory.store_memory = AsyncMock(return_value=MagicMock(id="mem1"))

    # Mock documents
    orch.documents.generate_docx = MagicMock(return_value="data/generated/test.docx")
    orch.documents.generate_xlsx = MagicMock(return_value="data/generated/test.xlsx")
    orch.documents.generate_pdf = MagicMock(return_value="data/generated/test.pdf")

    # Mock images
    orch.images.generate = AsyncMock(return_value=["https://example.com/image.png"])
    orch.images.analyze = AsyncMock(return_value="A beautiful landscape")

    return orch


@pytest.fixture
def client(mock_orchestrator):
    """Create a test client with mock orchestrator."""
    set_orchestrator(mock_orchestrator)
    from koda2.main import app
    return TestClient(app)


class TestHealthEndpoint:
    """Tests for the health check endpoint."""

    def test_health_check(self, client) -> None:
        """Health check returns 200 with status info."""
        response = client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "calendar_providers" in data
        assert "llm_providers" in data


class TestChatEndpoint:
    """Tests for the chat endpoint."""

    def test_chat_basic(self, client) -> None:
        """Chat endpoint processes a message and returns response."""
        response = client.post("/api/chat", json={
            "message": "Hello!",
            "user_id": "test_user",
        })
        assert response.status_code == 200
        data = response.json()
        assert "response" in data
        assert data["intent"] == "general_chat"

    def test_chat_with_channel(self, client) -> None:
        """Chat endpoint accepts channel parameter."""
        response = client.post("/api/chat", json={
            "message": "Check my calendar",
            "user_id": "test_user",
            "channel": "telegram",
        })
        assert response.status_code == 200


class TestCalendarEndpoints:
    """Tests for calendar API endpoints."""

    def test_list_events(self, client) -> None:
        """GET /calendar/events returns events list."""
        response = client.get("/api/calendar/events?days=7")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_list_calendars(self, client) -> None:
        """GET /calendar/calendars returns calendar list."""
        response = client.get("/api/calendar/calendars")
        assert response.status_code == 200

    def test_create_event(self, client) -> None:
        """POST /calendar/events creates an event."""
        response = client.post("/api/calendar/events", json={
            "title": "Team Meeting",
            "start": "2026-02-15T10:00:00",
            "end": "2026-02-15T11:00:00",
            "prep_minutes": 15,
        })
        assert response.status_code == 200
        data = response.json()
        assert "event" in data


class TestEmailEndpoints:
    """Tests for email API endpoints."""

    def test_get_inbox(self, client) -> None:
        """GET /email/inbox returns email list."""
        response = client.get("/api/email/inbox?limit=10")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_send_email(self, client) -> None:
        """POST /email/send sends an email."""
        response = client.post("/api/email/send", json={
            "to": ["test@example.com"],
            "subject": "Test Email",
            "body_text": "Hello!",
        })
        assert response.status_code == 200
        assert response.json()["sent"] is True


class TestDocumentEndpoints:
    """Tests for document generation endpoints."""

    def test_generate_docx(self, client) -> None:
        """POST /documents/generate creates a DOCX."""
        response = client.post("/api/documents/generate", json={
            "title": "Test Doc",
            "doc_type": "docx",
            "content": [{"type": "paragraph", "data": "Hello"}],
            "filename": "test",
        })
        assert response.status_code == 200
        assert "path" in response.json()


class TestPluginEndpoints:
    """Tests for plugin/capability endpoints."""

    def test_list_plugins(self, client) -> None:
        """GET /plugins returns plugin list."""
        response = client.get("/api/plugins")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_list_capabilities(self, client) -> None:
        """GET /capabilities returns capability map."""
        response = client.get("/api/capabilities")
        assert response.status_code == 200
        assert "send_email" in response.json()


class TestMemoryEndpoints:
    """Tests for memory endpoints."""

    def test_store_memory(self, client) -> None:
        """POST /memory/store creates a memory entry."""
        response = client.post("/api/memory/store", json={
            "user_id": "test_user",
            "category": "preference",
            "content": "Prefers morning meetings",
            "importance": 0.8,
        })
        assert response.status_code == 200
        assert response.json()["status"] == "stored"

    def test_search_memory(self, client) -> None:
        """GET /memory/search returns search results."""
        response = client.get("/api/memory/search?query=meetings&user_id=test_user")
        assert response.status_code == 200
        assert isinstance(response.json(), list)


class TestSchedulerEndpoints:
    """Tests for scheduler endpoints."""

    def test_list_tasks(self, client) -> None:
        """GET /scheduler/tasks returns task list."""
        response = client.get("/api/scheduler/tasks")
        assert response.status_code == 200
        assert isinstance(response.json(), list)
