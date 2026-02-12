# Koda2 Documentation

Complete documentation for the Koda2 AI Executive Assistant.

## Quick Navigation

| Document | Description |
|----------|-------------|
| [User Guide](user-guide.md) | Complete guide for using Koda2 |
| [Developer Guide](developer-guide.md) | Development and contribution guide |
| [Exchange Setup](../EXCHANGE_SETUP.md) | Microsoft Exchange configuration |
| [Google Setup](../GOOGLE_SETUP.md) | Google Calendar/Gmail configuration |

## Setup & Installation

### Quick Start
```bash
# Install
./install.sh          # macOS/Linux
./install.ps1         # Windows

# First run (auto-launches setup wizard)
koda2

# Reconfigure anytime
koda2 --setup
# or
koda2-config
```

### Configuration Files

| File | Purpose |
|------|---------|
| `.env` | Main configuration (API keys, settings) |
| `config/google_credentials.json` | Google OAuth credentials |
| `config/google_token.json` | Google access token (auto-generated) |
| `data/` | Database and generated files |
| `logs/` | Application logs |

## Feature Documentation

### Core Modules

- **Memory** — Vector-based semantic search and user profiles
- **Calendar** — Multi-provider calendar (Exchange, Google, Office 365, CalDAV)
- **Email** — Unified inbox (IMAP, Exchange, Gmail)
- **Messaging** — Telegram Bot and WhatsApp Web integration
- **LLM Router** — Multi-provider with fallback (OpenAI, Anthropic, Google, OpenRouter)

### Director-Level Secretary Features

- **Travel** — Flight/hotel search with Amadeus and Booking.com APIs
- **Meetings** — Transcription (Whisper), minutes generation, action tracking
- **Expenses** — Receipt OCR (GPT-4 Vision), expense reports
- **Facilities** — Room booking, catering orders
- **Documents** — DOCX, XLSX, PDF, PPTX generation

### Infrastructure

- **Dashboard** — Real-time monitoring with WebSocket
- **Task Queue** — Parallel processing with progress tracking
- **Metrics** — System resource monitoring
- **Git Auto-Commit** — Automatic commits after code generation

## API Reference

Interactive API documentation available at:
```
http://localhost:8000/docs
```

### Common API Patterns

```bash
# Chat with assistant
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Schedule a meeting", "user_id": "john"}'

# Search flights
curl "http://localhost:8000/api/travel/search-flights?\
  origin=AMS&destination=JFK&departure_date=2024-03-15"

# Process receipt
curl -X POST http://localhost:8000/api/expenses/process-receipt \
  -d "image_path=/path/to/receipt.jpg"
```

## Architecture

```
Koda2/
├── koda2/
│   ├── api/              # FastAPI routes
│   ├── dashboard/        # Web dashboard (HTML/CSS/JS)
│   ├── modules/
│   │   ├── calendar/     # Calendar providers
│   │   ├── email/        # Email providers
│   │   ├── messaging/    # Telegram & WhatsApp
│   │   ├── llm/          # LLM router & providers
│   │   ├── travel/       # Flight/hotel booking
│   │   ├── meetings/     # Transcription & minutes
│   │   ├── expenses/     # Receipt processing
│   │   ├── facilities/   # Room booking & catering
│   │   ├── documents/    # Document generation
│   │   ├── git_manager/  # Auto-commit
│   │   ├── task_queue/   # Parallel processing
│   │   └── metrics/      # System monitoring
│   ├── security/         # Encryption, RBAC, audit
│   └── main.py           # Application entry
├── docs/                 # Documentation
├── config/               # Configuration files
├── data/                 # Database & files
└── tests/                # Test suite
```

## Troubleshooting

### Common Issues

**Setup wizard won't start:**
```bash
# Run manually
python setup_wizard.py
```

**WhatsApp QR code not loading:**
- Ensure Node.js 18+ is installed: `node --version`
- Check port 3001 is available
- Refresh the QR page

**Exchange connection fails:**
- Verify EWS_SERVER URL with IT department
- Try different username formats (DOMAIN\user, user@domain)
- Check [EXCHANGE_SETUP.md](../EXCHANGE_SETUP.md)

**Google authentication fails:**
- Ensure `config/google_credentials.json` exists
- Delete `config/google_token.json` to re-authenticate
- Check [GOOGLE_SETUP.md](../GOOGLE_SETUP.md)

### Getting Help

1. Check logs: `logs/koda2.log`
2. Review dashboard: `http://localhost:8000/dashboard`
3. Consult feature-specific guides above
