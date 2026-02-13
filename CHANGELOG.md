# Changelog

All notable changes to Koda2 will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.0] - 2026-02-13

### Added
- **Self-Healing Supervisor** (`koda2/supervisor/`):
  - `safety.py` — git stash/pop backup+rollback, max 3 repair attempts per crash, max 5 restarts/10min, audit log, safe patch workflow, auto-push after every commit
  - `monitor.py` — spawns koda2 as subprocess, captures stderr, periodic health checks, auto-restart with rate limiting
  - `repair.py` — extracts crash info from traceback, sends to Claude via OpenRouter, applies minimal fix with confidence filter
  - `evolution.py` — plans improvements from natural language, generates file create/modify ops, tests+commits+pushes or rollbacks, user feedback analysis loop
  - `cli.py` — `koda2-supervisor run|repair|improve|learn|status` commands
- **Continuous Learning Loop** (`koda2/supervisor/learner.py`):
  - Background task runs every hour alongside the supervisor
  - Gathers signals: conversation history (complaints/wishes), audit log (crashes/errors), app logs (warnings)
  - LLM analyzes signals, classifies by impact, proposes concrete improvements
  - Executes improvements via EvolutionEngine (plan→code→test→commit→push)
  - Auto-updates CHANGELOG after improvements
  - Auto-bumps version (patch for fixes, minor for features) in pyproject.toml
  - Notifies user via WhatsApp with changelog summary
  - Periodic code hygiene checks (every 6 cycles)
  - Tracks failed ideas to avoid retrying them
  - Persists state to `data/supervisor/learner_state.json`
  - CLI: `koda2-supervisor learn` for manual cycle, `--no-learning` flag to disable
  - API: `POST /api/supervisor/learn` to trigger a cycle
- **User Feedback Loop** — `/feedback` command analyzes feedback via LLM, classifies as bug/feature/behavior/general, auto-implements if actionable
- **`/improve` WhatsApp command** — request self-improvement from chat, AI plans+implements+tests+commits+pushes
- **`self_improve_code` LLM tool** — agent can autonomously trigger code improvements during conversation
- **Supervisor API** — `GET /api/supervisor/status` (repair state + learner state + audit log), `POST /api/supervisor/improve`, `POST /api/supervisor/learn`
- **Dashboard Supervisor section** — improve form, learning loop panel with stats + Run Cycle Now button, repair state panel, color-coded audit log
- **Service mode uses supervisor** — install.sh now wires launchd/systemd to `koda2-supervisor run`
- **Improvement Queue** (`koda2/supervisor/improvement_queue.py`):
  - Persistent chronological queue for self-improvement tasks (`data/supervisor/improvement_queue.json`)
  - Background asyncio worker processes items by priority then age
  - Sources: user (dashboard), learner (auto-observations), supervisor, system
  - API: `GET /api/supervisor/queue`, `POST /api/supervisor/queue/start|stop`, `POST /api/supervisor/queue/{id}/cancel`
  - Dashboard panel with live queue view, worker toggle, cancel buttons
  - ContinuousLearner now queues proposals instead of executing directly

### Fixed
- **Evolution Engine 400 error** — replaced invalid OpenRouter model `anthropic/claude-sonnet-4-20250514` with settings-configured model (fallback `anthropic/claude-3.5-sonnet`), added response body logging on API errors

## [0.3.0] - 2026-02-13

### Added
- **Autonomous Agent Loop** — LLM now uses native tool/function calling instead of fragile JSON parsing
  - `process_message` runs an iterative loop: LLM calls tools → executes → feeds results back → repeats
  - Supports up to 15 tool-calling iterations per request (configurable `MAX_TOOL_ITERATIONS`)
  - Large tool results auto-truncated to 4000 chars to prevent context overflow
- **Native tool calling for all LLM providers**
  - OpenAI: full tool_calls serialization and parsing (was partial)
  - Anthropic: converts OpenAI tool format to Anthropic `tool_use`/`tool_result` blocks
  - Google Gemini: converts to `FunctionDeclaration` protos, parses `function_call` responses
  - OpenRouter: full OpenAI-compatible tool calling support
- **Tool definition generator** — `CommandRegistry.to_openai_tools()` auto-generates OpenAI function-calling schemas from all registered commands
- **ChatMessage model** — added `tool_calls` and `tool_call_id` fields for multi-turn tool conversations
- **Background Agent with tool-calling loop** — `AgentService` rewritten to use native tool calling (50 iterations, 8000 char results) instead of fragile JSON plan parsing
- **Auto-detect complex tasks** — if first LLM response has ≥4 tool calls, task is auto-offloaded to background agent with user notification
- **Scheduler now active with real recurring tasks** registered at startup:
  - Contact Sync (every 6 hours)
  - Email Check for unread (every 15 minutes)
  - Calendar Sync (every 30 minutes)
  - Daily Morning Summary via WhatsApp (07:00 cron)
  - Proactive Alerts Check (every 10 minutes)
- **Scheduler tools for LLM** — `schedule_recurring_task`, `schedule_once_task`, `schedule_interval_task`, `list_scheduled_tasks`, `cancel_scheduled_task` — LLM can now create/manage scheduled tasks via native tool calling
- **`/schedules` WhatsApp/Telegram command** — lists all scheduled tasks with schedule, last run, next run, and run count
- **Scheduler persistence** — user-created scheduled tasks are saved to SQLite (`scheduled_tasks` table) and automatically restored after service restart. System tasks are re-registered at startup. Run counts and last_run synced to DB on shutdown.
- **Unified email across all providers** — `read_email` now fetches from ALL connected accounts (Google, Exchange/EWS, IMAP, Office365) in one merged list, sorted by date. Each email includes `account` label showing which account it belongs to.
- **New email tools for LLM** — `get_email_detail` (full body), `reply_email` (with reply_all), `search_email` (keyword search across all accounts)
- **Account-aware email sending** — `send_email` now supports `account` parameter to choose which account to send from, plus `cc` support
- **OFFICE365** added to `EmailProvider` enum (was missing, caused runtime errors for MSGraph accounts)
- **`/cancel <id>` command** — cancel scheduled tasks, queue tasks, or agent tasks from WhatsApp/Telegram (prefix match on IDs)
- **Full memory management** — dashboard shows all memories with add/delete, `/memory` WhatsApp command, `store_memory`/`list_memories`/`delete_memory` LLM tools, API endpoints
- **Session management** — `/new` (reset session), `/compact` (summarize + prune old messages to save tokens), `/usage` (token stats + cost estimate)
- **Typing indicators** — WhatsApp and Telegram show "typing..." while the agent processes requests and executes tools
- **SOUL.md / TOOLS.md workspace files** — customizable personality and tool guidelines loaded from `workspace/` directory. Falls back to built-in defaults.
- **Webhooks** — `POST /api/webhook/{hook_id}` receives external triggers (GitHub, Stripe, etc.), stores as memory, optionally processes through agent and notifies via WhatsApp/Telegram
- **Browser control** — `BrowserService` with Playwright/Chrome CDP: `browse_url` (navigate + extract text), `browser_action` (click, type, scroll, screenshot, evaluate JS). LLM can now browse the web.
- **`koda2 doctor`** — CLI health check command that validates environment, dependencies, database, LLM providers, messaging, workspace files, and security configuration
- **Context window guard** — token-aware history pruning: estimates token count per message, keeps history within 40% of context budget, loads up to 20 recent messages but only keeps what fits
- **Response chunking** — long responses are split at paragraph boundaries before sending to WhatsApp/Telegram (max 4000 chars per chunk), preserving readability
- **LLM provider cooldown** — failed providers get 60-second cooldown, deprioritized in fallback chain, auto-cleared on success
- **Inbound message debounce** — rapid-fire WhatsApp messages are batched (1.5s window) and processed as one combined message, commands bypass debounce
- **Email account labels in dashboard** — each email shows a color-coded account tag (Gmail=red, Exchange=amber, IMAP=blue, Office365=purple) with summary line
- **Self-Healing Supervisor** (`koda2/supervisor/`):
  - `safety.py` — git stash/pop backup+rollback, max 3 repair attempts per crash, max 5 restarts/10min, audit log (`data/supervisor/audit_log.jsonl`), safe patch workflow (backup→patch→test→commit or rollback)
  - `monitor.py` — spawns koda2 as subprocess, captures stderr, periodic health checks, auto-restart with rate limiting, crash callback triggers repair
  - `repair.py` — extracts crash info from traceback, reads source context, sends to Claude via OpenRouter, applies minimal fix, confidence filter (skips low-confidence)
  - `evolution.py` — plans improvements from natural language, reads project structure, generates file create/modify ops, tests+commits or rollbacks
  - `cli.py` — `koda2-supervisor run|repair|improve|status` commands
  - `/improve` WhatsApp command — request self-improvement from chat

### Changed
- **BREAKING:** `process_message` response format changed:
  - Removed: `intent`, `entities`, `actions` fields
  - Added: `tool_calls` (list of executed tools), `iterations` (loop count)
- **BREAKING:** `ChatResponse` API model updated to match new response format
- System prompt rewritten: clean, concise, tool-focused (no more JSON format instructions)
- LLM no longer asked to generate structured JSON — uses native function calling instead

### Removed
- JSON-based intent/action parsing from LLM responses (replaced by native tool calling)

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
