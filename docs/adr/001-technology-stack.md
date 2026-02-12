# ADR-001: Technology Stack Selection

## Status
Accepted

## Date
2026-02-12

## Context
ExecutiveAI requires integration with AI/LLM providers, calendar systems (EWS, Google, Graph API, CalDAV), email (IMAP/SMTP, Gmail API), messaging platforms (Telegram, WhatsApp), document generation, image generation, macOS system integration, and a self-improvement engine. The stack must support all modules efficiently.

## Decision
**Primary Language: Python 3.12+**

### Core Framework
- **FastAPI** — Async HTTP framework, excellent performance, auto-generated OpenAPI docs
- **Uvicorn** — ASGI server

### Data Layer
- **SQLAlchemy 2.0** — ORM with async support for structured data
- **SQLite** — Primary structured database (portable, zero-config)
- **ChromaDB** — Vector database for semantic search / memory
- **Redis** — Caching, session management, pub/sub

### AI/LLM
- **openai** — OpenAI GPT models
- **anthropic** — Claude models
- **google-generativeai** — Gemini models
- **httpx** — OpenRouter and generic API calls

### Calendar & Email
- **exchangelib** — Exchange 2013/2016/2019 EWS
- **google-api-python-client** — Google Calendar & Gmail
- **msgraph-sdk** — Microsoft Graph API (Office 365)
- **caldav** — CalDAV protocol
- **aiosmtplib / aioimaplib** — Async IMAP/SMTP

### Messaging
- **python-telegram-bot** — Telegram Bot API
- **whatsapp-api-client-python** — WhatsApp Business API

### Document Generation
- **python-docx** — Word documents
- **openpyxl** — Excel spreadsheets
- **reportlab** — PDF generation
- **jinja2** — Template engine

### Security
- **cryptography** — AES-256 encryption
- **python-jose** — JWT tokens for RBAC
- **passlib** — Password hashing

### Testing
- **pytest** — Test framework
- **pytest-asyncio** — Async test support
- **pytest-cov** — Coverage reporting
- **httpx** — Async test client

### DevOps
- **Docker + Docker Compose** — Containerization
- **APScheduler** — Task scheduling

## Rationale
Python provides the richest ecosystem for AI/LLM integrations, document generation, and calendar/email libraries. FastAPI delivers near-Go performance for I/O-bound workloads via async. Type hints + Pydantic provide strong type safety. The ecosystem maturity minimizes custom code.

## Consequences
- Slightly lower raw CPU performance than Go/Rust (mitigated by async I/O)
- GIL limitation mitigated by async architecture and process pools for CPU-bound tasks
