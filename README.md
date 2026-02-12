<div align="center">

# 🤖 Koda2

**Professional AI Executive Assistant — Fully Automated Director-Level Secretary**

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)
[![Tests](https://img.shields.io/badge/tests-pytest-green.svg)](https://docs.pytest.org/)

<p align="center">
  <img src="https://img.shields.io/badge/🧠_LLM-Multi--Provider-purple" alt="Multi-Provider LLM">
  <img src="https://img.shields.io/badge/📅_Calendar-Multi--Platform-blue" alt="Multi-Platform Calendar">
  <img src="https://img.shields.io/badge/💬_Messaging-Telegram%20%26%20WhatsApp-green" alt="Messaging">
  <img src="https://img.shields.io/badge/✈️_Travel-Flights%20%26%20Hotels-orange" alt="Travel">
  <img src="https://img.shields.io/badge/📝_Meetings-Minutes%20%26%20Actions-yellow" alt="Meetings">
  <img src="https://img.shields.io/badge/💰_Expenses-Receipt%20Processing-red" alt="Expenses">
</p>

[🚀 Quick Start](#quick-start) • [📖 Documentation](#documentation) • [🖥️ Dashboard](#web-dashboard) • [🔌 API](#api-endpoints)

</div>

---

## ✨ What is Koda2?

Koda2 is a **production-ready AI executive assistant** that functions as a fully automated director-level secretary. It handles everything a real secretary would: calendars, emails, travel booking, meeting minutes, expense reports, and more.

### Key Capabilities

| Category | Features |
|----------|----------|
| **📅 Productivity** | Multi-calendar sync, email management, task scheduling, reminders |
| **💬 Communication** | WhatsApp, Telegram, email (Exchange, Gmail, IMAP) |
| **✈️ Travel** | Flight search (Amadeus), hotel booking (Booking.com), itinerary generation |
| **📝 Meetings** | Audio transcription, automatic minutes, action item tracking |
| **💰 Expenses** | Receipt OCR (GPT-4 Vision), expense reports, Excel export |
| **🏢 Facilities** | Room booking, catering orders, equipment management |
| **📊 Documents** | DOCX, XLSX, PDF, PPTX generation |
| **🧠 Intelligence** | Long-term memory, self-improvement, multi-provider LLM |

---

## 🚀 Quick Start

### Prerequisites
- Python 3.12+
- Node.js 18+ (for WhatsApp)
- macOS, Linux, or Windows

### Installation

```bash
# Clone repository
git clone <repository-url> && cd Koda2

# Run installer
chmod +x install.sh && ./install.sh    # macOS/Linux
# OR
powershell -ExecutionPolicy Bypass -File install.ps1  # Windows

# Start Koda2 (setup wizard runs automatically on first start)
koda2
```

**🎉 Koda2 automatically opens the dashboard in your browser!**

On startup, you'll see:
```
🚀 Koda2 is running!

▸ Dashboard:    http://localhost:8000/dashboard  ✔ Opened in browser
▸ API Docs:     http://localhost:8000/docs
```

**To start without opening browser:**
```bash
koda2 --no-browser
```

### First-Time Setup

On first run, Koda2 automatically launches the setup wizard to configure:

```
🤖 LLM Providers (OpenAI, Anthropic, Google, OpenRouter)
💬 Messaging (Telegram, WhatsApp)
📧 Email (Exchange, Office 365, Gmail, IMAP)
📅 Calendar (Exchange, Google, Office 365, CalDAV)
✈️ Travel APIs (optional)
💰 Expense Processing (optional)
```

**Re-run setup anytime:**
```bash
koda2 --setup
# or
koda2-config
```

---

## 🖥️ Web Dashboard

**URL:** `http://localhost:8000/dashboard`

The dashboard provides real-time monitoring and control:

| Feature | Description |
|---------|-------------|
| **📊 System Metrics** | Live CPU, memory, disk usage via WebSocket |
| **⚡ Active Tasks** | Monitor parallel task execution with progress bars |
| **💬 Messages** | Cross-channel conversation history |
| **🔌 Service Status** | Health indicators for all integrations |
| **🧠 Memory Browser** | Explore stored context and preferences |
| **👤 Account Management** | Add/remove/configure accounts |

**Dashboard is automatically shown at startup** — look for the URL in the terminal output!

---

## 💻 Terminal Chat

Chat with Koda2 directly from your terminal:

```bash
# Interactive chat mode
koda2 chat

# Single message
koda2 chat "Schedule a meeting with John tomorrow at 2pm"

# With context
koda2 chat "What's on my calendar today?"
```

**CLI Commands:**
```bash
koda2 status              # Show system status
koda2 dashboard           # Open web dashboard in browser
koda2 account list        # List configured accounts
koda2 account add         # Add new account
koda2 logs --follow       # Follow logs in real-time
```

## 📦 Features

### Messaging

**WhatsApp** — Personal account via QR code:

1. Enable WhatsApp in setup: `koda2 --setup`
2. Start Koda2 and scan QR code at `http://localhost:8000/api/whatsapp/qr`
3. Send a message to yourself to test

```
"Schedule a meeting with John next Tuesday at 2pm"
"Send WhatsApp to +31612345678: Running late"
```

**WhatsApp Troubleshooting:**
- **QR code not loading?** Refresh the page after 10 seconds
- **Messages not arriving?** Check terminal output for connection status
- **Session expired?** Use `/api/whatsapp/logout` and re-scan
- **Debug mode:** All incoming messages are logged to terminal with `[WhatsApp]` prefix

**Note:** Koda2 monitors ALL incoming WhatsApp messages (for processing) but only responds to messages you send to yourself.

**Telegram** — Bot integration with commands:
- `/status` — System health
- `/schedule` — Schedule meetings
- `/email` — Email operations
- `/remind` — Set reminders
- `/calendar` — Check agenda

### Calendar & Email

| Provider | Calendar | Email | Type |
|----------|----------|-------|------|
| **Exchange (EWS)** | ✅ | ✅ | On-premises |
| **Office 365** | ✅ | ✅ | Cloud (Graph API) |
| **Google** | ✅ | ✅ | Cloud |
| **CalDAV** | ✅ | ❌ | Standard protocol |
| **IMAP/SMTP** | ❌ | ✅ | Generic |

**Exchange On-Premises Support:**
```env
EWS_SERVER=https://mail.company.com/EWS/Exchange.asmx
EWS_USERNAME=DOMAIN\username     # Can differ from email!
EWS_PASSWORD=...
EWS_EMAIL=username@company.com   # Actual email
```

See [EXCHANGE_SETUP.md](EXCHANGE_SETUP.md) for detailed Exchange configuration.

### Travel Management

Book flights and hotels:

```bash
# Search flights
curl "http://localhost:8000/api/travel/search-flights?\
  origin=AMS&destination=JFK&departure_date=2024-03-15"

# Search hotels
curl "http://localhost:8000/api/travel/search-hotels?\
  destination=London&check_in=2024-03-15&check_out=2024-03-18"
```

- **Amadeus API** — Flight search
- **Booking.com** — Hotel search
- **Itinerary PDF** — Complete trip summaries

### Meeting Management

Automatic transcription and minutes:

```bash
# Upload meeting audio
curl -X POST /api/meetings/transcribe \
  -d "meeting_id=abc" \
  -d "audio_path=/path/to/recording.wav"

# Get action items
curl /api/meetings/action-items
```

Features:
- OpenAI Whisper transcription
- Automatic summary generation
- Action item extraction with assignees
- PDF minutes export
- Overdue tracking

### Expense Processing

Receipt OCR and reporting:

```bash
# Process receipt image
curl -X POST /api/expenses/process-receipt \
  -d "image_path=/path/to/receipt.jpg"
```

- GPT-4 Vision for OCR
- Automatic categorization
- VAT/BTW extraction
- Excel report export

### Facility Management

Room booking and catering:

```bash
# Book meeting room
curl -X POST /api/facilities/book-room \
  -d "venue_id=boardroom-a" \
  -d "start_time=2024-03-15T14:00:00"

# Order catering
curl -X POST /api/facilities/catering \
  -d "catering_type=lunch" \
  -d "number_of_people=12"
```

### Presentations

Generate PowerPoint from outline:

```bash
curl -X POST /api/documents/presentation \
  -d "title=Q1 Results" \
  -d "outline=# Summary
## Financials
- Revenue up 25%
- Profit improved
## Initiatives
- Product launch"
```

---

## 🔄 Self-Improvement

Koda2 detects missing capabilities and auto-generates code:

1. **Detect** — User asks for something new
2. **Generate** — LLM creates plugin code
3. **Test** — Automatic test generation
4. **Commit** — Git commit with descriptive message
5. **Activate** — Load and use immediately

---

## 🔌 API Endpoints

### Core

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/health` | System health |
| `POST` | `/api/chat` | Natural language processing |

### Calendar & Email

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/calendar/events` | List events |
| `POST` | `/api/calendar/events` | Create event |
| `GET` | `/api/email/inbox` | Fetch emails |
| `POST` | `/api/email/send` | Send email |

### Travel

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/travel/search-flights` | Search flights |
| `GET` | `/api/travel/search-hotels` | Search hotels |

### Meetings

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/meetings/create` | Create meeting |
| `POST` | `/api/meetings/transcribe` | Transcribe audio |
| `GET` | `/api/meetings/action-items` | List action items |

### Expenses

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/expenses/process-receipt` | Process receipt |
| `POST` | `/api/expenses/create-report` | Create report |

### Facilities

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/facilities/venues` | List venues |
| `POST` | `/api/facilities/book-room` | Book room |
| `POST` | `/api/facilities/catering` | Order catering |

Full API docs at `http://localhost:8000/docs` (Swagger UI).

---

## 📁 Configuration

### Google Credentials

For Google Calendar and Gmail, place OAuth credentials:

```
Koda2/
├── config/
│   ├── google_credentials.json    # Download from Google Cloud
│   └── google_token.json          # Auto-generated
```

See [GOOGLE_SETUP.md](GOOGLE_SETUP.md) for detailed setup.

### Environment Variables

All settings in `.env`:

```env
# Required
OPENAI_API_KEY=sk-...

# Exchange (on-premises)
EWS_SERVER=https://mail.company.com/EWS/Exchange.asmx
EWS_USERNAME=DOMAIN\username
EWS_PASSWORD=...
EWS_EMAIL=username@company.com

# Office 365
MSGRAPH_CLIENT_ID=...
MSGRAPH_CLIENT_SECRET=...

# WhatsApp
WHATSAPP_ENABLED=true

# Travel APIs (optional)
AMADEUS_API_KEY=...
RAPIDAPI_KEY=...
```

---

## 📖 Documentation

- [User Guide](docs/user-guide.md) — Complete usage guide
- [Developer Guide](docs/developer-guide.md) — Development & contribution
- [EXCHANGE_SETUP.md](EXCHANGE_SETUP.md) — Exchange configuration
- [GOOGLE_SETUP.md](GOOGLE_SETUP.md) — Google API setup

---

## 🛠️ Development

```bash
# Run tests
pytest

# With coverage
pytest --cov=koda2 --cov-report=html

# Format code
ruff format .
ruff check . --fix
```

---

## 🐳 Docker

```bash
docker compose up -d
```

---

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.

---

<div align="center">

Made with ❤️ for busy executives everywhere

**[⬆ Back to Top](#-koda2)**

</div>
