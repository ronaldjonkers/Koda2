<div align="center">

# 🤖 Koda2

**Personal AI Executive Assistant — Your Own Local-First AI Secretary**

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)
[![Tests](https://img.shields.io/badge/tests-pytest-green.svg)](https://docs.pytest.org/)

<p align="center">
  <img src="https://img.shields.io/badge/🧠_LLM-Multi--Provider-purple" alt="Multi-Provider LLM">
  <img src="https://img.shields.io/badge/📅_Calendar-Multi--Platform-blue" alt="Multi-Platform Calendar">
  <img src="https://img.shields.io/badge/💬_Messaging-Telegram%20%26%20WhatsApp-green" alt="Messaging">
  <img src="https://img.shields.io/badge/🌐_Browser-Chrome%20CDP-orange" alt="Browser Control">
  <img src="https://img.shields.io/badge/�_Email-Unified%20Inbox-red" alt="Unified Email">
  <img src="https://img.shields.io/badge/🧠_Memory-Long--Term-yellow" alt="Long-Term Memory">
</p>

[🚀 Quick Start](#-quick-start) • [� WhatsApp Setup](#-whatsapp-setup) • [🖥️ Dashboard](#-web-dashboard) • [🔌 API](#-api-endpoints) • [📖 All Features](#-features)

</div>

---

## ✨ What is Koda2?

Koda2 is a **personal AI assistant** you run on your own machine. It answers you on the channels you already use (WhatsApp, Telegram), manages your calendar, email, contacts, files, and can browse the web — all through natural language.

**v0.3.0** — Autonomous agent loop with native tool/function calling across all LLM providers (OpenAI, Anthropic, Google Gemini, OpenRouter). Ask it to do something complex and it will call tools, see results, and keep going until the task is done.

**NEW: Self-Healing Supervisor + Continuous Learning** — Koda2 monitors itself, auto-repairs crashes via LLM, and **proactively improves itself** by reading its own logs and conversations. Every hour it analyzes patterns, proposes improvements, implements them, updates docs, bumps the version, and notifies you via WhatsApp. Run with `koda2-supervisor run` or use `/improve` and `/feedback` from WhatsApp.

### Key Capabilities

| Category | Features |
|----------|----------|
| **� Channels** | WhatsApp (personal QR), Telegram bot, Web dashboard, CLI, API |
| **� Unified Email** | All accounts in one inbox — Gmail, Exchange/EWS, Office 365, IMAP — with account labels |
| **📅 Calendar** | Multi-provider sync — Exchange, Google, Office 365, CalDAV |
| **🧠 Memory** | Long-term memory with semantic search, manual entries, categories |
| **🌐 Browser** | Headless Chrome control — browse, click, type, screenshot, scrape |
| **⏰ Scheduler** | Cron jobs, interval tasks, one-time tasks — all manageable from WhatsApp |
| **📊 Documents** | Generate DOCX, XLSX, PDF, PPTX; analyze documents with AI |
| **🖼️ Images** | Generate with DALL-E/Stability, analyze with GPT-4 Vision |
| **🔧 Shell** | Run terminal commands, manage files, git operations |
| **🔗 Webhooks** | External triggers (GitHub, Stripe, etc.) that wake the agent |
| **🧩 Plugins** | Self-improvement: auto-generates code for missing capabilities |
| **🧬 Self-Healing** | Supervisor wrapper: auto-restart, LLM crash repair, `/improve` self-modification |

---

## 🚀 Quick Start

### Prerequisites
- Python 3.12+
- Node.js 18+ (for WhatsApp)
- macOS, Linux, or Windows

### Installation

```bash
git clone https://github.com/ronaldjonkers/Koda2.git && cd Koda2
chmod +x install.sh && ./install.sh    # macOS/Linux
koda2                                   # Start (setup wizard runs on first start)
```

On startup:
```
🚀 Koda2 is running!
▸ Dashboard:    http://localhost:8000/dashboard
▸ API Docs:     http://localhost:8000/docs
```

### Health Check

```bash
koda2 doctor    # Check environment, deps, database, LLM keys, messaging, security
```

### Re-run Setup

```bash
koda2 --setup
```

---

## 💬 WhatsApp Setup

WhatsApp is the primary way to interact with Koda2. It uses your **personal WhatsApp account** via QR code (not the Business API).

### Step 1: Enable WhatsApp

Add to your `.env` file:
```env
WHATSAPP_ENABLED=true
WHATSAPP_BRIDGE_PORT=3001
```

Or run `koda2 --setup` and enable WhatsApp in the messaging section.

### Step 2: Start Koda2 and Scan QR

```bash
koda2
```

Open `http://localhost:8000/api/whatsapp/qr` in your browser and scan the QR code with your phone (WhatsApp → Linked Devices → Link a Device).

### Step 3: Start Using It

Send a message **to yourself** on WhatsApp. Koda2 only responds to messages you send to yourself (security by default).

### How It Works

- Koda2 runs a Node.js bridge (`whatsapp-web.js`) that connects to WhatsApp Web
- Your phone stays connected as the primary device
- The bridge receives all messages but only processes self-messages
- Typing indicators show "typing..." while the agent works
- All slash commands work in WhatsApp

### WhatsApp Commands

| Command | Description |
|---------|-------------|
| `/help` | Show all available commands |
| `/status` | System health and uptime |
| `/calendar [today/week]` | View upcoming events |
| `/schedule <details>` | Create a calendar event |
| `/schedules` | List all scheduled background tasks |
| `/cancel <id>` | Cancel a scheduled task or agent task |
| `/email <request>` | Check inbox or send email |
| `/remind <what> at <when>` | Set a reminder |
| `/memory [text]` | List memories or store a new one |
| `/contacts [name]` | Search contacts |
| `/meet [title]` | Create a Google Meet link |
| `/accounts` | Manage email/calendar accounts (add/test/delete) |
| `/config` | View current settings |
| `/new` | Reset conversation (fresh session) |
| `/compact` | Compact session context (saves tokens) |
| `/usage` | Show token usage and estimated cost |

### Natural Language (No Commands Needed)

You can also just type naturally:

```
"Schedule a meeting with John tomorrow at 2pm"
"Send an email to ronald@company.com about the Q1 report"
"What's on my calendar this week?"
"Send WhatsApp to +31612345678: I'm running 10 minutes late"
"Search my emails for the invoice from last week"
"Remember that I prefer meetings before 11am"
"Browse https://news.ycombinator.com and summarize the top stories"
```

### Adding Accounts via WhatsApp

You can add email/calendar accounts directly from WhatsApp:

```
/accounts
```

Then follow the wizard:
1. Type `add` to start
2. Choose provider: `exchange`, `office365`, `imap`, `caldav`, `telegram`
3. Enter credentials step by step
4. Koda2 tests the connection automatically

Example Exchange setup:
```
/accounts
> add
> exchange
> exchange.company.com
> DOMAIN\username
> yourpassword
> user@company.com
> My Work Exchange
```

### WhatsApp Troubleshooting

| Problem | Solution |
|---------|----------|
| QR code not loading | Wait 10 seconds, refresh the page |
| Messages not arriving | Check terminal for `[WhatsApp]` connection status |
| Session expired | Visit `/api/whatsapp/logout`, restart, re-scan QR |
| "Not configured" errors | Check `WHATSAPP_ENABLED=true` in `.env` |
| Bridge crashes | Check Node.js is installed: `node --version` |

---

## 🖥️ Web Dashboard

**URL:** `http://localhost:8000/dashboard`

| Section | Features |
|---------|----------|
| **📊 Overview** | Live CPU, memory, disk, uptime, message rate |
| **💬 Chat** | Send messages to the assistant from the browser |
| **📅 Calendar** | View upcoming events from all connected calendars |
| **📧 Email** | Unified inbox with **account labels** (color-coded: Gmail=red, Exchange=amber, IMAP=blue, Office365=purple) |
| **👥 Contacts** | Synced from macOS, WhatsApp, Gmail, Exchange |
| **🧠 Memory** | Browse all stored memories, add new ones, delete, search with semantic matching |
| **⏰ Scheduler** | View/cancel scheduled tasks |
| **⚡ Tasks** | Monitor background agent tasks |
| **🔌 Integrations** | Health status of all connected services |
| **👤 Accounts** | Add/remove/test email and calendar accounts |

### Memory Management (Dashboard)

The Memory section shows all stored memories with:
- **Category tags** (note, fact, preference, project, contact, habit)
- **Source** (user, whatsapp, calendar, contacts, compact, webhook)
- **Timestamps** and **delete** buttons
- **"+ Add Memory"** button with category dropdown
- **Semantic search** across all memories
- **Stats bar**: total memories, vector count, category breakdown

---

## 🧠 Memory System

Koda2 has a long-term memory system that stores facts, preferences, and context:

### How Memory Works

- **Automatic**: Koda2 stores context from calendar events, contact lookups, document analysis, and webhooks
- **Manual**: You can store memories via WhatsApp (`/memory I prefer morning meetings`), the dashboard, or by telling the assistant ("Remember that my dentist is Dr. van der Berg")
- **Recall**: The agent automatically recalls relevant memories when processing your messages (semantic search via ChromaDB)
- **Session summaries**: When you `/compact`, old conversation history is summarized and stored as a memory

### Memory Categories

| Category | Examples |
|----------|---------|
| `preference` | "User prefers meetings before 11am" |
| `fact` | "Ronald works at GoSettle as CTO" |
| `note` | Free-form notes |
| `project` | "Project X deadline is March 15" |
| `contact` | "John's phone number is +31612345678" |
| `habit` | "User checks email at 8am and 5pm" |
| `session_summary` | Auto-generated from `/compact` |
| `webhook` | Events from external triggers |

### LLM Tools for Memory

The agent can use these tools autonomously:
- `store_memory` — Save a fact/preference/note
- `search_memory` — Semantic search across all memories
- `list_memories` — List all stored memories
- `delete_memory` — Remove a memory by ID

---

## 📧 Unified Email

All email accounts appear in **one unified inbox**, each labeled with the account name and color-coded by provider.

| Provider | Color | Setup |
|----------|-------|-------|
| **Gmail** | 🔴 Red | Google OAuth credentials |
| **Exchange (EWS)** | 🟠 Amber | Server + NTLM auth |
| **Office 365** | 🟣 Purple | MS Graph API |
| **IMAP/SMTP** | 🔵 Blue | Standard IMAP settings |

### Email Tools

| Tool | Description |
|------|-------------|
| `read_email` | Fetch from ALL accounts in one list |
| `get_email_detail` | Read full email body |
| `send_email` | Send from any account (specify with `account` param) |
| `reply_email` | Reply or reply-all |
| `search_email` | Search by keyword across all accounts |

---

## 🌐 Browser Control

Koda2 can control a headless Chrome browser via Playwright:

```
"Browse https://news.ycombinator.com and tell me the top 5 stories"
"Go to google.com, search for 'weather Amsterdam', and tell me the forecast"
"Take a screenshot of our company website"
```

### Browser Tools

| Tool | Description |
|------|-------------|
| `browse_url` | Navigate to URL, extract text content |
| `browser_action` | Click, type, scroll, screenshot, evaluate JS, navigate |

**Setup:** Install Playwright (optional):
```bash
pip install playwright
playwright install chromium
```

---

## ⏰ Scheduler

Create and manage recurring tasks:

```
"Run a daily email check at 8am"
"Every Monday at 9am, send me a weekly summary via WhatsApp"
"In 30 minutes, remind me to call the dentist"
```

### Built-in Scheduled Tasks

| Task | Schedule |
|------|----------|
| Contact Sync | Every 6 hours |
| Email Check | Every 15 minutes |
| Calendar Sync | Every 30 minutes |
| Morning Summary (WhatsApp) | Daily at 07:00 |
| Proactive Alerts | Every 10 minutes |

### Managing Tasks

- **WhatsApp**: `/schedules` to list, `/cancel <id>` to remove
- **Dashboard**: Scheduler section with remove buttons
- **LLM**: "Cancel the daily email check task"

---

## 🔗 Webhooks

External services can trigger Koda2 via webhooks:

```bash
# Simple event notification
curl -X POST http://localhost:8000/api/webhook/github \
  -H "Content-Type: application/json" \
  -d '{"event": "push", "source": "github", "message": "New push to main by ronald"}'

# Trigger agent + notify via WhatsApp
curl -X POST http://localhost:8000/api/webhook/stripe \
  -H "Content-Type: application/json" \
  -d '{
    "event": "payment_received",
    "source": "stripe",
    "message": "Payment of €500 received from Client X",
    "notify_channel": "whatsapp",
    "notify_to": "me"
  }'
```

Webhooks:
- Are stored as memories (searchable later)
- Can trigger the agent to process the event
- Can send notifications to WhatsApp or Telegram

---

## 🎭 Personality (SOUL.md)

Customize the assistant's personality by editing `workspace/SOUL.md`:

```markdown
# Koda2 — Personality & Behavior

## Core Identity
- You are helpful, proactive, and efficient
- You speak the user's language (Dutch or English)
- You are concise — no unnecessary filler words

## Behavior Rules
- Always use tools to fulfill requests
- If something fails, explain what went wrong
```

Tool-specific guidelines go in `workspace/TOOLS.md`. Both files are loaded automatically on each request. If they don't exist, built-in defaults are used.

---

## 💻 CLI

```bash
koda2                     # Start server (dashboard + API)
koda2 doctor              # Health check: deps, config, security
koda2 status              # Show system status
koda2 chat                # Interactive chat mode
koda2 chat "message"      # Single message
koda2 account list        # List configured accounts
koda2 account add         # Add new account
koda2 --setup             # Run setup wizard
koda2 --no-browser        # Start without opening browser
```

### `koda2 doctor`

Checks everything:
- **Environment**: `.env` file, config loading
- **Dependencies**: Required (fastapi, sqlalchemy, chromadb) and optional (playwright, google APIs)
- **Database**: SQLite and ChromaDB status
- **LLM Providers**: Which API keys are configured
- **Messaging**: Telegram token, WhatsApp enabled, Node.js installed
- **Workspace**: SOUL.md and TOOLS.md presence
- **Security**: Secret key, encryption key

---

## 🔌 API Endpoints

### Core

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/health` | System health |
| `POST` | `/api/chat` | Natural language processing |

### Email

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/email/inbox` | Unified inbox (all providers, with account labels) |
| `POST` | `/api/email/send` | Send email |

### Calendar

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/calendar/events` | List events |
| `POST` | `/api/calendar/events` | Create event |

### Memory

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/memory/list` | List all stored memories |
| `GET` | `/api/memory/search?query=...` | Semantic search |
| `GET` | `/api/memory/stats` | Memory statistics |
| `POST` | `/api/memory/store` | Store a new memory |
| `DELETE` | `/api/memory/{id}` | Delete a memory |

### Scheduler

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/scheduler/tasks` | List scheduled tasks |
| `DELETE` | `/api/scheduler/tasks/{id}` | Cancel a task |

### Webhooks

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/webhook/{hook_id}` | Receive external trigger |

### Contacts

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/contacts` | Search contacts |
| `POST` | `/api/contacts/sync` | Sync from all sources |

### WhatsApp

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/whatsapp/qr` | Get QR code for linking |
| `GET` | `/api/whatsapp/status` | Connection status |
| `POST` | `/api/whatsapp/send` | Send a message |

Full interactive API docs at `http://localhost:8000/docs` (Swagger UI).

---

## 🧬 Self-Healing Supervisor + Continuous Learning

Koda2 can **monitor itself, auto-repair crashes, improve its own code, and proactively learn from its own logs and conversations**. This is powered by a supervisor wrapper that runs _around_ the main application.

### Architecture

```
┌──────────────────────────────────────────────────────┐
│              koda2-supervisor                         │
│  ┌───────────┐ ┌──────────┐ ┌────────┐ ┌─────────┐ │
│  │ Process   │ │ Self-    │ │ Evolu- │ │ Contin- │ │
│  │ Monitor   │ │ Repair   │ │ tion   │ │ uous    │ │
│  │           │ │ Engine   │ │ Engine │ │ Learner │ │
│  │ • Start   │ │ • Crash  │ │ • User │ │ • Read  │ │
│  │ • Watch   │ │   analyze│ │   req  │ │   logs  │ │
│  │ • Restart │ │ • LLM fix│ │ • Code │ │ • Read  │ │
│  │ • Health  │ │ • Test   │ │   gen  │ │   chats │ │
│  │   check   │ │ • Commit │ │ • Test │ │ • Plan  │ │
│  │           │ │ • Push   │ │ • Push │ │ • Build │ │
│  └───────────┘ └──────────┘ └────────┘ │ • Docs  │ │
│                                         │ • Bump  │ │
│                                         │ • Notify│ │
│                                         └─────────┘ │
│  Safety: git backup, rollback, max 3 repair         │
│  attempts, test gate, audit log, confidence filter   │
└─────────────┬────────────────────────────────────────┘
              │ spawns + monitors
              ▼
┌──────────────────────────────────────────────────────┐
│            koda2 (FastAPI)                            │
└──────────────────────────────────────────────────────┘
```

### Start with Self-Healing

```bash
# Normal start (no self-healing)
koda2-server

# Start under supervisor (auto-restart + self-repair + learning)
koda2-supervisor run

# With WhatsApp notifications on improvements
koda2-supervisor run --notify "31612345678@c.us"

# Disable features selectively
koda2-supervisor run --no-repair      # just restart on crash
koda2-supervisor run --no-learning    # disable proactive learning
```

### Continuous Learning Loop

Every hour, the supervisor automatically:
1. **Reads conversation history** — detects complaints, wishes, confusion patterns
2. **Reads audit log** — finds recurring crashes and errors
3. **Reads application logs** — spots warnings and exceptions
4. **Analyzes via LLM** — classifies signals, prioritizes by impact
5. **Implements improvements** — code changes, tests, commit + push
6. **Updates documentation** — CHANGELOG auto-updated
7. **Bumps version** — patch for fixes, minor for features
8. **Notifies you** — WhatsApp message with what changed

```bash
# Run one learning cycle manually
koda2-supervisor learn

# With notification
koda2-supervisor learn --notify "31612345678@c.us"
```

### Self-Improvement from WhatsApp

Send `/improve` or `/feedback` from WhatsApp:

```
/improve add a /weather command that shows the forecast
/improve make the email summary include attachment names
/feedback the calendar events don't show the location
/feedback I love the WhatsApp integration!
```

The AI will:
1. Plan the minimal changes needed
2. Read the project structure for context
3. Generate code modifications
4. Run the test suite
5. Commit + push if tests pass, rollback if they fail
6. Update CHANGELOG, bump version
7. Notify you of the result

### Manual Repair

```bash
# Analyze a crash and attempt repair
koda2-supervisor repair crash_log.txt

# Request a code improvement from CLI
koda2-supervisor improve "add a /weather command"

# Check supervisor status, learner stats, and recent activity
koda2-supervisor status
```

### Safety Guardrails

| Guardrail | How |
|-----------|-----|
| **Git backup** | `git stash` before every code patch |
| **Rollback** | Automatic restore if tests fail |
| **Max retries** | Max 3 repair attempts per unique crash |
| **Restart limit** | Max 5 restarts per 10-minute window |
| **Test gate** | Changes only committed if tests pass |
| **Auto-push** | Every commit is immediately pushed to remote |
| **Audit log** | Every action logged to `data/supervisor/audit_log.jsonl` |
| **Confidence filter** | Low-confidence LLM fixes are skipped |
| **Failed idea tracking** | Previously failed improvements are not retried |

---

## 📁 Configuration

### Environment Variables (`.env`)

```env
# ── LLM (at least one required) ──
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
GOOGLE_AI_API_KEY=...
OPENROUTER_API_KEY=...
LLM_DEFAULT_PROVIDER=openai        # openai, anthropic, google, openrouter
LLM_DEFAULT_MODEL=gpt-4o

# ── Personalization ──
ASSISTANT_NAME=Koda2
USER_NAME=Ronald

# ── WhatsApp ──
WHATSAPP_ENABLED=true
WHATSAPP_BRIDGE_PORT=3001

# ── Telegram ──
TELEGRAM_BOT_TOKEN=123456:ABCDEF...

# ── Security ──
KODA2_SECRET_KEY=your-random-secret-key
KODA2_ENCRYPTION_KEY=your-32-byte-key

# ── Database ──
DATABASE_URL=sqlite+aiosqlite:///data/koda2.db
CHROMA_PERSIST_DIR=data/chroma
```

### Google Credentials

For Google Calendar and Gmail:
```
Koda2/
├── config/
│   ├── google_credentials.json    # Download from Google Cloud Console
│   └── google_token.json          # Auto-generated on first auth
```

See [GOOGLE_SETUP.md](GOOGLE_SETUP.md) for detailed setup.

### Workspace Files

```
Koda2/
├── workspace/
│   ├── SOUL.md     # Personality and behavior rules
│   └── TOOLS.md    # Tool usage guidelines
```

---

## 📖 Documentation

- [EXCHANGE_SETUP.md](EXCHANGE_SETUP.md) — Exchange/EWS configuration
- [GOOGLE_SETUP.md](GOOGLE_SETUP.md) — Google API setup
- [CHANGELOG.md](CHANGELOG.md) — Version history

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

# Health check
koda2 doctor
```

---

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.

---

<div align="center">

Made with ❤️ for busy executives everywhere

**[⬆ Back to Top](#-koda2)**

</div>
