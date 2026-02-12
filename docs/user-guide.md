# Koda2 User Guide

## Getting Started

### Prerequisites
- macOS or Linux
- Python 3.12+
- At least one LLM API key (OpenAI, Anthropic, Google, or OpenRouter)

### Installation

```bash
./install.sh
python setup_wizard.py    # Interactive API key configuration
koda2        # Start the server
```

## Using Koda2

### Via Telegram Bot

The most natural way to interact with Koda2. Set up your Telegram bot:

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
