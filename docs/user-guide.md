# Koda2 User Guide

Complete guide for using your AI Executive Assistant.

## Table of Contents

- [Quick Start](#quick-start)
- [Setup Wizard](#setup-wizard)
- [Dashboard](#web-dashboard)
- [Messaging](#messaging)
- [Calendar & Email](#calendar--email)
- [Travel Management](#travel-management)
- [Meeting Management](#meeting-management)
- [Expense Processing](#expense-processing)
- [Facility Management](#facility-management)
- [Presentations](#presentations)
- [Configuration](#configuration)

---

## Quick Start

### Prerequisites
- macOS, Linux, or Windows
- Python 3.12+
- Node.js 18+ (for WhatsApp integration)
- At least one LLM API key (OpenAI recommended)

### Installation

**Option 1: Automatic Installation (Recommended)**

```bash
# macOS / Linux
git clone <repository-url> && cd Koda2
chmod +x install.sh && ./install.sh
```

**Option 2: Manual Installation**

```bash
git clone <repository-url> && cd Koda2
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate    # Windows
pip install -e ".[dev]"
```

### First Run

```bash
# Start Koda2 - setup wizard runs automatically on first start
# Browser opens automatically to the dashboard!
koda2

# Start without opening browser
koda2 --no-browser

# Or run setup manually anytime
koda2 --setup
# or
koda2-config
```

The setup wizard will guide you through:
1. LLM provider configuration (OpenAI, etc.)
2. Messaging setup (Telegram, WhatsApp)
3. Email configuration (Exchange, Gmail, IMAP)
4. Calendar integration
5. Travel & expense APIs (optional)

---

## Setup Wizard

The setup wizard (`koda2 --setup`) helps configure all integrations:

### Running Setup

```bash
# Interactive setup
koda2 --setup

# Or use the standalone script
python setup_wizard.py
```

### What Gets Configured

| Section | Options |
|---------|---------|
| **General** | Environment, log level, API port |
| **LLM Providers** | OpenAI, Anthropic, Google, OpenRouter |
| **Telegram** | Bot token, allowed users |
| **WhatsApp** | Enable/disable, QR code instructions |
| **Email** | IMAP/SMTP, Exchange (EWS), Office 365, Gmail |
| **Calendar** | Exchange, Google, Office 365, CalDAV |
| **Travel** | Amadeus (flights), Booking.com (hotels) |
| **Expenses** | Receipt processing |

### Google Credentials Location

For Google Calendar and Gmail, place your OAuth credentials:

```
Koda2/
├── config/
│   ├── google_credentials.json    # Download from Google Cloud Console
│   └── google_token.json          # Auto-generated after auth
```

See [GOOGLE_SETUP.md](../GOOGLE_SETUP.md) for detailed instructions.

### Exchange Configuration

Koda2 supports **both** on-premises Exchange and Office 365:

**On-Premises Exchange (EWS):**
```env
EWS_SERVER=https://mail.company.com/EWS/Exchange.asmx
EWS_USERNAME=DOMAIN\username      # Can be different from email!
EWS_PASSWORD=your_password
EWS_EMAIL=username@company.com     # Your actual email
```

**Office 365 (Microsoft Graph):**
```env
MSGRAPH_CLIENT_ID=your_client_id
MSGRAPH_CLIENT_SECRET=your_secret
MSGRAPH_TENANT_ID=your_tenant_id
```

See [EXCHANGE_SETUP.md](../EXCHANGE_SETUP.md) for detailed instructions.

---

## Terminal Chat

Chat with Koda2 directly from your terminal without starting the web interface:

```bash
# Interactive chat mode
koda2 chat

# Single message
koda2 chat "What's on my calendar today?"

# Get status
koda2 status

# Open dashboard in browser
koda2 dashboard

# View logs
koda2 logs --follow
```

### CLI Commands Reference

| Command | Description |
|---------|-------------|
| `koda2` | Start the Koda2 server (opens browser automatically) |
| `koda2 --no-browser` | Start without opening browser |
| `koda2 chat` | Interactive terminal chat |
| `koda2 chat "message"` | Send single message |
| `koda2 status` | Show system status |
| `koda2 dashboard` | Open web dashboard |
| `koda2 account list` | List configured accounts |
| `koda2 account add` | Add new account |
| `koda2 logs` | View logs |
| `koda2 commit "msg"` | Commit and push changes |
| `koda2 commit --no-push` | Commit without pushing |
| `koda2 --setup` | Run setup wizard |

---

## Web Dashboard

Koda2 includes a beautiful real-time web dashboard at **`http://localhost:8000/dashboard`**.

**The dashboard URL is displayed when Koda2 starts up!** Look for:
```
🚀 Koda2 is running!
▸ Dashboard: http://localhost:8000/dashboard
```

### Dashboard Features

| Feature | Description |
|---------|-------------|
| **System Metrics** | Real-time CPU, memory, disk usage |
| **Active Tasks** | Monitor parallel task execution with progress bars |
| **Messages** | View recent conversations across all channels |
| **Service Status** | Health indicators for all connected services |
| **Calendar** | Upcoming events overview |
| **Memory Browser** | Explore stored memories and context |

### Real-Time Updates

The dashboard uses WebSocket for live updates:
- Task progress updates as they execute
- System metrics refresh every 5 seconds
- Service status changes
- New messages appear instantly

---

## Messaging

### WhatsApp (Personal Account)

Connect your personal WhatsApp via QR code:

1. Enable in setup: `koda2 --setup` → WhatsApp section
2. Start Koda2: `koda2`
3. Open `http://localhost:8000/api/whatsapp/qr`
4. Scan QR code with WhatsApp app
5. Send a message **to yourself**

**How it works:**
- Koda2 monitors ALL your incoming WhatsApp messages (displayed in terminal)
- Only messages you send **to yourself** trigger AI responses
- You can send commands like `/status` or natural language like "Schedule a meeting"

**Available Commands:**
```
/status          - Show system status
/schedule ...    - Schedule meetings
/email ...       - Email operations
/remind ...      - Set reminders
/calendar        - Check calendar
/config          - View settings
/accounts        - Manage accounts
/help            - Show help
```

#### WhatsApp Troubleshooting

**Messages not arriving?**
1. Check terminal output - all messages are logged with `[WhatsApp]` prefix
2. Ensure you sent the message to yourself (your own number)
3. Check connection status: `http://localhost:8000/api/whatsapp/status`

**QR code not loading?**
1. Wait 10-15 seconds for generation
2. Refresh the page
3. Check terminal for QR code in ASCII format

**Session expired?**
```bash
# Logout and re-scan
curl -X POST http://localhost:8000/api/whatsapp/logout
```

**Debug mode:**
All WhatsApp activity is logged to the terminal. Look for:
- `[WhatsApp] Message from...` - All incoming messages
- `[WhatsApp] Forwarding self-message...` - Messages sent to yourself
- `[Koda2] Processing message...` - AI processing
- `[Koda2] Sending reply...` - Response being sent

**Natural Language Examples:**
- "Schedule a meeting with John next Tuesday at 2pm"
- "Send WhatsApp to +31612345678: Running 10 minutes late"
- "What's on my calendar today?"

### Telegram Bot

1. Create bot via [@BotFather](https://t.me/botfather)
2. Add token in setup wizard
3. Add your user ID to allowed list
4. Start chatting!

Same commands as WhatsApp work in Telegram.

---

## Calendar & Email

### Supported Providers

| Provider | Calendar | Email | Notes |
|----------|----------|-------|-------|
| **Exchange (EWS)** | ✅ | ✅ | On-premises Exchange 2013+ |
| **Office 365** | ✅ | ✅ | Via Microsoft Graph API |
| **Google** | ✅ | ✅ | Gmail + Google Calendar |
| **CalDAV** | ✅ | ❌ | Apple, Nextcloud, etc. |
| **IMAP/SMTP** | ❌ | ✅ | Generic email |

### Calendar Features

- View all calendars in one unified view
- Schedule with automatic conflict detection
- Preparation time blocks before meetings
- Recurring events support
- Multi-timezone handling

### Email Features

- Unified inbox across all providers
- Intelligent prioritization
- Template system
- Attachment handling
- Reply with threading

---

## Travel Management

Book flights, hotels, and manage business trips.

### Flight Search

```bash
# Via API
curl "http://localhost:8000/api/travel/search-flights?\
  origin=AMS&destination=JFK&\
  departure_date=2024-03-15&\
  return_date=2024-03-22"
```

**Or via messaging:**
- "Find flights from Amsterdam to New York next week"
- "Search for business class flights to London on March 15"

### Hotel Search

```bash
curl "http://localhost:8000/api/travel/search-hotels?\
  destination=London&\
  check_in=2024-03-15&\
  check_out=2024-03-18"
```

### Trip Management

Create complete itineraries:
1. Create trip with destinations and dates
2. Add flights, hotels, ground transport
3. Generate PDF itinerary
4. Store in memory for reference

**Required APIs:**
- Amadeus API for flights (free tier available)
- RapidAPI for Booking.com hotels

---

## Meeting Management

Automatic transcription, minutes generation, and action item tracking.

### Creating Meetings

```bash
# Create meeting
curl -X POST "http://localhost:8000/api/meetings/create" \
  -d "title=Weekly Team Standup" \
  -d "scheduled_start=2024-03-15T10:00:00" \
  -d "scheduled_end=2024-03-15T11:00:00" \
  -d "organizer=john.doe@company.com"
```

### Transcription

Upload meeting audio for automatic transcription:

```bash
curl -X POST "http://localhost:8000/api/meetings/transcribe" \
  -d "meeting_id=abc123" \
  -d "audio_path=/path/to/recording.wav"
```

**Features:**
- OpenAI Whisper API for accurate transcription
- Automatic speaker detection
- Timestamped segments

### Minutes Generation

Automatically generates meeting minutes with:
- Meeting summary
- Key decisions
- Action items with assignees
- Due dates

```bash
# Generate PDF minutes
curl "http://localhost:8000/api/meetings/abc123/minutes"
```

### Action Item Tracking

Track action items across meetings:

```bash
# Get all pending action items
curl "http://localhost:8000/api/meetings/action-items"
```

Features:
- Automatic overdue detection
- Reminder notifications
- Progress tracking
- Integration with calendar for due dates

---

## Expense Processing

Automated receipt processing and expense reporting.

### Receipt Processing

Upload receipt images for automatic data extraction:

```bash
curl -X POST "http://localhost:8000/api/expenses/process-receipt" \
  -d "image_path=/path/to/receipt.jpg" \
  -d "submitted_by=john.doe@company.com" \
  -d "project_code=PROJ-001"
```

**Automatic extraction:**
- Merchant name
- Date and amount
- VAT/BTW amount and percentage
- Currency
- Category (travel, meals, etc.)

Powered by GPT-4 Vision for accurate OCR.

### Expense Reports

Create and export expense reports:

```bash
# Create report
curl -X POST "http://localhost:8000/api/expenses/create-report" \
  -d "title=March 2024 Business Trip" \
  -d "employee_name=John Doe" \
  -d "period_start=2024-03-01" \
  -d "period_end=2024-03-31"

# Export to Excel
curl -X POST "http://localhost:8000/api/expenses/{report_id}/export"
```

Exports include:
- All expenses with categories
- VAT calculations
- Project codes
- Digital receipt attachments

---

## Facility Management

Book meeting rooms and order catering.

### Room Booking

```bash
# List available venues
curl "http://localhost:8000/api/facilities/venues?min_capacity=10"

# Book a room
curl -X POST "http://localhost:8000/api/facilities/book-room" \
  -d "venue_id=room-a" \
  -d "meeting_title=Board Meeting" \
  -d "organizer_name=John Doe" \
  -d "start_time=2024-03-15T14:00:00" \
  -d "end_time=2024-03-15T15:00:00" \
  -d "expected_attendees=12"
```

### Catering Orders

```bash
curl -X POST "http://localhost:8000/api/facilities/catering" \
  -d "catering_type=lunch" \
  -d "event_name=Board Meeting" \
  -d "event_date=2024-03-15" \
  -d "delivery_time=13:00" \
  -d "number_of_people=12"
```

**Catering Types:**
- Coffee break
- Working lunch
- Breakfast
- Dinner
- Reception

Automatic menu suggestions based on event type and dietary requirements.

---

## Presentations

Generate PowerPoint presentations from outlines.

### From Outline

```bash
curl -X POST "http://localhost:8000/api/documents/presentation" \
  -d "title=Q1 2024 Results" \
  -d "author=John Doe" \
  -d "outline=# Executive Summary
## Financial Highlights
- Revenue up 25%
- Profit margin improved
## Key Initiatives
- Product launch
- Market expansion
## Q2 Outlook
- Growth targets
- Investment plans"
```

### Features

- Multiple slide layouts
- Corporate themes
- Tables and charts
- Speaker notes
- Automatic closing slide

---

## Configuration

### Environment Variables

All configuration is in `.env`. Key settings:

```env
# Core
KODA2_ENV=production
KODA2_LOG_LEVEL=INFO
API_PORT=8000

# LLM
OPENAI_API_KEY=sk-...
LLM_DEFAULT_PROVIDER=openai
LLM_DEFAULT_MODEL=gpt-4o

# OpenRouter (alternative LLM provider)
OPENROUTER_API_KEY=sk-or-v1-...
OPENROUTER_MODEL=openai/gpt-4o  # Or anthropic/claude-3.5-sonnet, etc.

# Exchange (on-premises)
EWS_SERVER=https://mail.company.com/EWS/Exchange.asmx
EWS_USERNAME=DOMAIN\username
EWS_PASSWORD=...
EWS_EMAIL=username@company.com

# Office 365
MSGRAPH_CLIENT_ID=...
MSGRAPH_CLIENT_SECRET=...
MSGRAPH_TENANT_ID=...

# Google
GOOGLE_CREDENTIALS_FILE=config/google_credentials.json

# WhatsApp
WHATSAPP_ENABLED=true
WHATSAPP_BRIDGE_PORT=3001

# Travel
AMADEUS_API_KEY=...
AMADEUS_API_SECRET=...
RAPIDAPI_KEY=...
```

### Account Management

Koda2 supports multiple accounts per provider. Manage accounts via:

**CLI:**
```bash
# List all accounts
koda2 account list

# Add new account (interactive wizard)
koda2 account add

# Test account credentials
koda2 account test <account_id>

# Set default account
koda2 account set-default <account_id>

# Disable/enable accounts
koda2 account disable <account_id>
koda2 account enable <account_id>
```

**Web Dashboard:**
- Go to `http://localhost:8000/dashboard`
- Click "Accounts" section
- Add, edit, or test accounts

**Messaging (Telegram/WhatsApp):**
```
/accounts list       - Show all accounts
/accounts default    - Show/set default account
/accounts test <name> - Test account
/accounts add        - How to add accounts
```

### Reconfiguring

Run the setup wizard anytime:
```bash
koda2 --setup
# or
koda2-config
```

The setup wizard now includes:
- **Credential validation** - Tests connections before saving
- **Model selection** - Choose from top 10 OpenRouter models
- **Account naming** - Give accounts descriptive names
- **Multi-account setup** - Add multiple Exchange, Gmail, etc.

### Auto Git Commit

Koda2 automatically commits and pushes changes to git:

```bash
# Check git auto-commit status
koda2 status

# Manual commit
koda2 commit "Description of changes"

# Commit without push
koda2 commit --no-push
```

**Configuration in `.env`:**
```env
# Enable auto-commit (commits every 5 minutes if there are changes)
GIT_AUTO_COMMIT=true

# Enable auto-push (pushes after each commit)
GIT_AUTO_PUSH=true
```

**What gets committed automatically:**
- Every 5 minutes if there are uncommitted changes
- When you shut down Koda2 (final commit)
- Generated commit messages describe what changed

### LLM Model Check on Startup

If no LLM is configured, Koda2 will ask you on startup:

```
⚠ No LLM provider configured!
Koda2 needs an AI model to function.

Available providers:
  1. OpenAI (recommended)
  2. Anthropic (Claude)
  3. Google AI (Gemini)
  4. OpenRouter
  5. Exit and configure manually

Select provider (1-5): 
```

You can then enter your API key and model directly, without restarting.

---

## Troubleshooting

### Common Issues

**"No LLM provider configured"**
- Run `koda2 --setup` and add at least one API key

**"WhatsApp not connecting"**
- Ensure Node.js 18+ is installed: `node --version`
- Check QR code hasn't expired (refresh page)

**"Exchange connection failed"**
- Verify EWS_SERVER URL with your IT department
- Try different username formats (DOMAIN\user, user@domain, just user)
- Check if EWS is enabled for your account

**"Google authentication failed"**
- Ensure `config/google_credentials.json` exists
- Delete `config/google_token.json` and re-authenticate

### Getting Help

- Check logs: `logs/koda2.log`
- API documentation: `http://localhost:8000/docs`
- Dashboard: `http://localhost:8000/dashboard`

---

## Next Steps

- Explore the [Dashboard](http://localhost:8000/dashboard)
- Try the [API](http://localhost:8000/docs)
- Read the [Developer Guide](developer-guide.md)
- Check [EXCHANGE_SETUP.md](../EXCHANGE_SETUP.md) for Exchange help
- Check [GOOGLE_SETUP.md](../GOOGLE_SETUP.md) for Google setup
