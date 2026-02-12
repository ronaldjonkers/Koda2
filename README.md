# Koda2

**Professional AI Executive Assistant — Fully Automated Director-Level Secretary**

Koda2 is a modular, scalable, and self-improving AI assistant that manages calendars, emails, tasks, documents, and communications across multiple platforms.

## Features

| Module | Description |
|--------|-------------|
| **Memory System** | Long-term user profile with vector-based semantic search (ChromaDB) |
| **Calendar Management** | Exchange (EWS), Google Calendar, Office 365 (Graph API), CalDAV |
| **Email Management** | IMAP/SMTP, Gmail API — read, send, reply, prioritize, templates |
| **Messaging** | Telegram Bot + WhatsApp Web (QR code pairing, personal account) |
| **LLM Router** | Multi-provider (OpenAI, Anthropic, Google, OpenRouter) with fallback |
| **Image Gen/Analysis** | DALL-E, Stability AI generation + GPT-4 Vision analysis |
| **Document Generation** | DOCX, XLSX, PDF with templates and code scaffolding |
| **Task Scheduler** | Cron jobs, reminders, event-driven triggers (APScheduler) |
| **macOS Integration** | AppleScript bridge, Contacts sync, secure shell execution |
| **Self-Improvement** | Capability detection, auto-code generation, plugin system |

## Architecture

```
koda2/
├── api/              # FastAPI routes
├── modules/
│   ├── memory/       # Module 1: User profile + vector memory
│   ├── calendar/     # Module 2: Multi-provider calendar
│   ├── email/        # Module 3: Email management
│   ├── messaging/    # Module 4: Telegram + WhatsApp
│   ├── llm/          # Module 5: LLM router + providers
│   ├── images/       # Module 6: Image generation/analysis
│   ├── documents/    # Module 7: Document generation
│   ├── scheduler/    # Module 8: Task scheduling
│   ├── macos/        # Module 9: macOS integration
│   └── self_improve/ # Module 10: Self-improvement engine
├── security/         # AES-256 encryption, RBAC, audit logging
├── config.py         # Centralized configuration
├── database.py       # Async SQLAlchemy + SQLite
├── orchestrator.py   # Central brain connecting all modules
└── main.py           # FastAPI application entry point
```

## Install — One Line

**macOS / Linux (single line, installs everything):**

```bash
curl -fsSL https://raw.githubusercontent.com/ronaldjonkers/Koda2/main/get-koda2.sh | bash
```

Or with `wget`:

```bash
wget -qO- https://raw.githubusercontent.com/ronaldjonkers/Koda2/main/get-koda2.sh | bash
```

**Windows (PowerShell, single line):**

```powershell
irm https://raw.githubusercontent.com/ronaldjonkers/Koda2/main/get-koda2.ps1 | iex
```

These one-liners automatically install **all** prerequisites (Homebrew, Python 3.12+, Node.js 18+, Git) and set up Koda2 completely. Supports macOS (Intel + Apple Silicon), Ubuntu/Debian, Fedora/RHEL/CentOS, Arch/Manjaro, openSUSE, Alpine, and Windows 10/11.

### Custom install location

```bash
KODA2_INSTALL_DIR=/opt/koda2 curl -fsSL https://raw.githubusercontent.com/ronaldjonkers/Koda2/main/get-koda2.sh | bash
```

### Manual install (if you prefer)

```bash
git clone https://github.com/ronaldjonkers/Koda2.git && cd Koda2
chmod +x install.sh && ./install.sh
python setup_wizard.py
```

### Start Koda2

```bash
cd ~/Koda2 && source .venv/bin/activate && koda2
```

### Run as a Service (auto-start on boot)

The installer offers to install Koda2 as a system service:
- **macOS:** LaunchAgent (launchd) — starts at login
- **Linux:** systemd user service — starts at boot
- **Windows:** Task Scheduler — starts at login

### Docker

```bash
docker compose up -d
```

API documentation is available at `http://localhost:8000/docs` after starting.

## Configuration

Copy `.env.example` to `.env` and configure your API keys:

```bash
cp .env.example .env
```

**Minimum required:** At least one LLM provider API key (OpenAI, Anthropic, Google, or OpenRouter).

See `.env.example` for all available configuration options.

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/health` | System health check |
| `POST` | `/api/chat` | Natural language message processing |
| `GET` | `/api/calendar/events` | List calendar events |
| `POST` | `/api/calendar/events` | Create calendar event |
| `GET` | `/api/email/inbox` | Fetch inbox emails |
| `POST` | `/api/email/send` | Send an email |
| `POST` | `/api/documents/generate` | Generate DOCX/XLSX/PDF |
| `POST` | `/api/images/generate` | Generate images |
| `POST` | `/api/images/analyze` | Analyze images |
| `POST` | `/api/memory/store` | Store a memory |
| `GET` | `/api/memory/search` | Semantic memory search |
| `GET` | `/api/plugins` | List loaded plugins |
| `GET` | `/api/capabilities` | List all capabilities |
| `POST` | `/api/plugins/generate` | Auto-generate a plugin |
| `GET` | `/api/whatsapp/status` | WhatsApp connection status |
| `GET` | `/api/whatsapp/qr` | Get QR code for WhatsApp pairing |
| `POST` | `/api/whatsapp/send` | Send WhatsApp message to anyone |
| `POST` | `/api/whatsapp/webhook` | Receive WhatsApp messages |
| `GET` | `/api/scheduler/tasks` | List scheduled tasks |

## Usage Examples

### Via API

```bash
# Chat with Koda2
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Schedule a meeting with John next Tuesday at 10am", "user_id": "ronald"}'

# Generate a document
curl -X POST http://localhost:8000/api/documents/generate \
  -H "Content-Type: application/json" \
  -d '{"title": "Q1 Report", "doc_type": "pdf", "content": [{"type": "paragraph", "data": "..."}]}'
```

### Via Telegram

1. Set `TELEGRAM_BOT_TOKEN` in `.env`
2. Start the server
3. Message your bot:
   - `/schedule Meeting with John next Tuesday`
   - `/email Check my inbox`
   - `/remind Buy groceries at 5pm`
   - `/status` — System health

### Via WhatsApp

1. Set `WHATSAPP_ENABLED=true` in `.env`
2. Start the server
3. Scan the QR code at `http://localhost:8000/api/whatsapp/qr`
4. Send a message **to yourself** in WhatsApp — Koda2 processes it and replies
5. Koda2 can send messages to anyone on your behalf via the API or chat commands

## Testing

```bash
source .venv/bin/activate
pytest                              # Run all tests
pytest --cov=koda2            # With coverage report
pytest tests/test_calendar.py -v    # Single module
```

## Scripts

| Script | Description |
|--------|-------------|
| `install.sh` | One-command installation (macOS/Linux — all distros) |
| `install.ps1` | Windows installation (PowerShell) |
| `uninstall.sh` | Complete removal |
| `update.sh` | Pull latest + update dependencies |
| `setup_wizard.py` | Interactive configuration wizard |

## Technology Stack

- **Language:** Python 3.12+
- **Framework:** FastAPI + Uvicorn
- **Database:** SQLAlchemy 2.0 + SQLite (async)
- **Vector DB:** ChromaDB
- **Cache:** Redis (optional)
- **AI/LLM:** OpenAI, Anthropic, Google Gemini, OpenRouter
- **Scheduling:** APScheduler
- **Security:** AES-256-GCM encryption, RBAC, JWT
- **Testing:** pytest + pytest-asyncio + pytest-cov
- **Containerization:** Docker + Docker Compose

See `docs/adr/001-technology-stack.md` for the detailed rationale.

## Security

- All API keys stored in environment variables (`.env`)
- Sensitive data encrypted with AES-256-GCM
- Role-based access control (Admin, User, Viewer)
- Comprehensive audit logging
- Shell command sanitization (blocks dangerous commands)
- Telegram user ID allowlist

## License

MIT

## Version

0.2.0
