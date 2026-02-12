# Changelog

All notable changes to Koda2 will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-02-12

### Added
- **WhatsApp Web integration** via QR code scan (whatsapp-web.js bridge)
  - Connect any personal WhatsApp account by scanning a QR code
  - Bot reads all messages, only responds to self-messages
  - Can send messages to anyone on the user's behalf
  - API endpoints: `/api/whatsapp/status`, `/qr`, `/send`, `/webhook`, `/logout`
- **Windows support** with PowerShell installer (`install.ps1`)
  - Task Scheduler integration for auto-start at login
  - Full Windows installation documentation (`docs/windows-install.md`)
- **Service mode** — run Koda2 as a background service
  - macOS: LaunchAgent (launchd) with auto-start at login
  - Linux: systemd user service with auto-start at boot
  - Windows: Task Scheduler entry
- **Enhanced installer** (`install.sh`) — supports all major platforms:
  - macOS (Intel + Apple Silicon) — auto-installs Homebrew if missing
  - Ubuntu/Debian, Fedora/RHEL, Arch, openSUSE, Alpine Linux
  - Auto-installs Python 3.12+, Node.js 18+, and all dependencies
- WhatsApp bridge Node.js dependencies installed automatically
- Interactive setup wizard now includes WhatsApp configuration

### Changed
- WhatsApp: replaced Business API with QR-code based whatsapp-web.js bridge
- Config: `WHATSAPP_API_URL`/`WHATSAPP_API_TOKEN` → `WHATSAPP_ENABLED`/`WHATSAPP_BRIDGE_PORT`
- Removed `whatsapp-api-client-python` dependency (replaced by Node.js bridge)

### Fixed
- `datetime.utcnow()` deprecation warnings → `datetime.now(UTC)` across all modules
- structlog `event=` kwarg conflicts in calendar and scheduler services
- tenacity retry on `ValueError` in image service (no longer retries programming errors)

## [0.1.0] - 2026-02-12

### Added
- **Module 1:** User Profile and Memory System with ChromaDB vector search
- **Module 2:** Calendar Management (EWS, Google, MS Graph, CalDAV)
- **Module 3:** Email Management (IMAP/SMTP, Gmail API, templates)
- **Module 4:** Messaging Integration (Telegram Bot, WhatsApp Business API)
- **Module 5:** LLM Router with multi-provider support and fallback
- **Module 6:** Image Generation (DALL-E, Stability AI) and Analysis (GPT-4 Vision)
- **Module 7:** Document Generation (DOCX, XLSX, PDF) and code scaffolding
- **Module 8:** Task Scheduler with cron, interval, and event-driven triggers
- **Module 9:** macOS System Integration (AppleScript, Contacts, shell)
- **Module 10:** Self-Improvement engine with plugin system and auto-code generation
- Security: AES-256-GCM encryption, RBAC, audit logging
- FastAPI REST API with full OpenAPI documentation
- Central orchestrator with natural language intent parsing
- Docker + Docker Compose configuration
- Install/Uninstall/Update scripts
- Interactive setup wizard
- Comprehensive test suite
