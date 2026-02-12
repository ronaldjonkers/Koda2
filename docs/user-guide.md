# Koda2 User Guide

## Getting Started

### Prerequisites
- macOS, Linux, or Windows
- Python 3.12+
- Node.js 18+ (for WhatsApp integration)
- At least one LLM API key (OpenAI, Anthropic, Google, or OpenRouter)

### Installation — One Line

**macOS / Linux:**
```bash
curl -fsSL https://raw.githubusercontent.com/ronaldjonkers/Koda2/main/get-koda2.sh | bash
```

**Windows (PowerShell):**
```powershell
irm https://raw.githubusercontent.com/ronaldjonkers/Koda2/main/get-koda2.ps1 | iex
```

These install **everything** automatically (Homebrew, Python, Node.js, Git, all dependencies) and launch the setup wizard.

**Manual install (if you prefer):**
```bash
git clone https://github.com/ronaldjonkers/Koda2.git && cd Koda2
chmod +x install.sh && ./install.sh
python setup_wizard.py
koda2
```

### Running as a Service

The installer offers to set up Koda2 as a system service that starts automatically:
- **macOS:** LaunchAgent (launchd)
- **Linux:** systemd user service
- **Windows:** Task Scheduler

## Using Koda2

### Via WhatsApp (Personal Account)

Connect your personal WhatsApp account via QR code scan:

1. Set `WHATSAPP_ENABLED=true` in `.env`
2. Start Koda2
3. Open `http://localhost:8000/api/whatsapp/qr` in your browser
4. Scan the QR code with your WhatsApp phone app
5. Send a message **to yourself** in WhatsApp

**How it works:**
- Koda2 reads all your WhatsApp messages but **only responds to messages you send to yourself**
- This is your private command channel — like talking to your assistant
- Koda2 can send messages to **anyone** on your behalf when you ask
- Your session persists (no need to re-scan unless you log out)

**Examples (send to yourself):**
- "Schedule a meeting with John next Tuesday at 2pm"
- "Send a WhatsApp to +31612345678: I'll be 10 minutes late"
- "What's on my calendar today?"

### Via Telegram Bot

Set up your Telegram bot:

1. Create a bot via [@BotFather](https://t.me/botfather)
2. Add the token to your `.env` file
3. Add your Telegram user ID to `TELEGRAM_ALLOWED_USER_IDS`
4. Restart Koda2

**Commands:**
- `/start` — Initialize the bot
- `/help` — List available commands
- `/schedule <details>` — Schedule a meeting
- `/email <details>` — Email operations
- `/remind <details>` — Set a reminder
- `/status` — System health check

**Natural Language:** Just send a message like:
- "Schedule a meeting with John next Tuesday at 2pm"
- "Check my calendar for tomorrow"
- "Send an email to Sarah about the project update"
- "Remind me to call the dentist at 4pm"

### Via REST API

Full API documentation at `http://localhost:8000/docs` (Swagger UI).

```bash
# Ask Koda2 anything
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What meetings do I have today?", "user_id": "ronald"}'
```

## Calendar Integration

Koda2 supports multiple calendar backends simultaneously:

- **Exchange (EWS):** On-premises Exchange 2013/2016/2019
- **Google Calendar:** Google Workspace
- **Office 365:** Microsoft Graph API
- **CalDAV:** Standard protocol (Apple Calendar, Nextcloud, etc.)

Features:
- View all calendars in one place
- Schedule with automatic conflict detection
- Prep time blocks before meetings
- Automatic reminders

## Email Management

- Read and prioritize your inbox
- Send emails with templates
- Reply to messages
- Attachment handling
- Intelligent filtering (urgent items surfaced first)

## Document Generation

Generate professional documents from natural language:
- Word documents (.docx)
- Spreadsheets (.xlsx)
- PDF reports (.pdf)

## Self-Improvement

When you request something Koda2 can't do yet, it will:
1. Detect the missing capability
2. Auto-generate a plugin module
3. Write tests for the new code
4. Load and activate the new capability

## Configuration

All settings are in `.env`. Run `python setup_wizard.py` to reconfigure interactively.
