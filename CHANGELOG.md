# Changelog

All notable changes to Koda2 will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.5.3] - 2026-02-15

### Fixed
- **Tool loop runaway** — lowered `MAX_TOOL_ITERATIONS` from 15 → 8; AI was burning
  14 iterations ($0.15+) for a simple "hoi joyce" greeting exploring the codebase
- **Empty response after tool loop** — when max iterations hit, a final summary LLM
  call is forced (no tools) so the user always gets a reply
- **`orchestrator_no_response_for_whatsapp_message`** — guaranteed non-empty response
  on every code path in `process_message`
- **CalendarService.list_events() `limit` kwarg** — removed invalid keyword argument
  in proactive service that caused `context_calendar_failed` every 10 minutes
- **Playwright auto-install** — `BrowserService._ensure_browser()` now auto-installs
  playwright + chromium when missing instead of crashing with RuntimeError

### Added
- **`install_package` action** — AI can now install Python packages via pip:
  - New `install_package` command in registry (LLM-accessible)
  - Blocks dangerous packages (os, sys, subprocess, shutil)
  - Auto-installs chromium browser binaries when playwright is installed
  - 120s timeout, captures output for user feedback
- **`SafetyGuard.pip_install()`** — supervisor can install packages in the project venv
  with full audit trail

### Tests
- 359 tests pass (3 new: pip_install no-packages, success, failure)

### Auto-improvement (2026-02-15)
- **Revised: Add health check endpoint and enhance logging/error reporting for crash diagnosis - fixed missing imports** (risk: low)
  - Modified koda2/api/routes.py
  - Modified koda2/api/routes.py


### Auto-improvement (2026-02-15)
- **Add channel-aware response formatting to handle WhatsApp/Telegram vs dashboard differently** (risk: low)
  - Skipped koda2/orchestrator.py: old_text not found


### Auto-improvement (2026-02-15)
- **Add WhatsApp file transfer functionality with error handling and logging** (risk: low)
  - Skipped koda2/modules/messaging/whatsapp_bot.py: old_text not found


### Auto-improvement (2026-02-15)
- **Add /weather command to get forecast for a city using existing weather module** (risk: low)
  - Skipped koda2/modules/weather/service.py: old_text not found
  - Skipped koda2/modules/commands/registry.py: old_text not found
  - Skipped koda2/modules/commands/registry.py: old_text not found
  - Skipped koda2/modules/commands/registry.py: old_text not found
  - Skipped koda2/modules/commands/registry.py: old_text not found


### Auto-improvement (2026-02-15)
- **Remove calendar conflict checking functionality from the codebase** (risk: low)
  - Skipped koda2/modules/calendar/models.py: old_text not found
  - Skipped koda2/modules/calendar/service.py: old_text not found
  - Skipped tests/test_calendar.py: old_text not found
  - Skipped tests/test_calendar_service.py: old_text not found


### Auto-improvement (2026-02-15)
- **Add file transfer functionality to WhatsApp bot with proper error handling and logging** (risk: low)
  - Skipped koda2/modules/messaging/whatsapp_bot.py: old_text not found
  - Skipped tests/test_messaging.py: old_text not found


### Auto-improvement (2026-02-15)
- **Fix timezone handling in calendar event creation by ensuring consistent Europe/Amsterdam timezone usage** (risk: low)
  - Skipped koda2/modules/calendar/service.py: old_text not found
  - Skipped koda2/modules/calendar/service.py: old_text not found


### Auto-improvement (2026-02-15)
- **Create a formatting layer to convert JSON responses to human-readable text, focusing on the main user-facing outputs** (risk: low)
  - Created koda2/formatting.py
  - Skipped koda2/api/routes.py: old_text not found


### Auto-improvement (2026-02-15)
- **Fix timezone handling in calendar module and remove conflict detection** (risk: low)
  - Skipped koda2/modules/calendar/service.py: old_text not found
  - Skipped koda2/modules/calendar/service.py: old_text not found


### Auto-improvement (2026-02-15)
- **Add error handling and verification to calendar API operations** (risk: low)
  - Skipped koda2/modules/calendar/providers.py: old_text not found


### Auto-improvement (2026-02-15)
- **Add calendar selection and logging to event creation flow** (risk: low)
  - Skipped koda2/modules/calendar/service.py: old_text not found
  - Skipped koda2/modules/calendar/providers.py: old_text not found


### Auto-improvement (2026-02-16)
- **Add logging and retry mechanism to WhatsApp message sending function in whatsapp_bot.py** (risk: low)
  - Skipped koda2/modules/messaging/whatsapp_bot.py: old_text not found


### Auto-improvement (2026-02-16)
- **Enhance WhatsApp messaging with logging, error handling, retries, and delivery confirmation** (risk: low)
  - Skipped koda2/modules/messaging/whatsapp_bot.py: old_text not found


### Auto-improvement (2026-02-16)
- **Enhance WhatsApp LID handling with better error handling, logging, and validation** (risk: low)
  - Skipped koda2/modules/messaging/whatsapp_bot.py: old_text not found
  - Skipped koda2/modules/messaging/whatsapp_bot.py: old_text not found


### Auto-improvement (2026-02-16)
- **Add error handling and monitoring to scheduler task execution** (risk: low)
  - Skipped koda2/modules/scheduler/service.py: old_text not found


## [0.5.2] - 2026-02-15

### Added
- **Git auto-pull & restart** — supervisor polls remote every 2 minutes:
  - `SafetyGuard.git_fetch()` / `check_remote_ahead()` / `git_pull()` — safe remote detection
  - `ProcessMonitor._check_remote_updates()` — fetch → compare → pull --ff-only → restart
  - Only pulls when remote is strictly ahead (no local commits that would conflict)
  - Audit log tracks all detected updates, pulls, and restarts

### Fixed
- **Scheduler `chat` action type** — users can now schedule AI-processed tasks:
  - Added `chat` parameter to `schedule_recurring_task`, `schedule_once_task`, `schedule_interval_task`
  - `chat` tasks process the prompt through the orchestrator and send the AI response via WhatsApp
  - Previously `chat` was only supported during restore, not creation (caused schedules to fail)
  - Updated command registry with `chat` parameter and examples for LLM awareness
- **Silent WhatsApp failures** — scheduled message tasks now log a warning when WhatsApp is not configured instead of silently doing nothing

### Tests
- 356 tests pass (8 new: git fetch, remote ahead, pull, monitor polling)

## [0.5.1] - 2026-02-14

### Added
- **Smart Model Router** (`koda2/supervisor/model_router.py`):
  - Picks the optimal LLM model per task complexity via OpenRouter
  - LIGHT (free/cheap): signal analysis, feedback classification, commit messages, docs
  - MEDIUM: error analysis, crash analysis, plan revision
  - HEAVY (Claude Sonnet 4): code generation, self-correction, repair, architecture
  - Falls back to OpenAI `gpt-4o-mini`/`gpt-4o` when not using OpenRouter
  - Logs model selection and token usage per call
- **Auto-restart after code changes**:
  - `SafetyGuard.request_restart()` / `check_restart_requested()` — file-based restart signal
  - `ProcessMonitor` checks for restart signal every health-check cycle
  - After successful evolution commit+push, the assistant process is gracefully restarted
- **Detailed commit messages**: LLM-generated multi-line commit messages with file-level descriptions
- **Auto CHANGELOG updates**: Every self-improvement appends to `CHANGELOG.md` before committing

### Changed
- `evolution.py` — replaced hardcoded LLM calls with smart model router
- `repair.py` — replaced hardcoded LLM calls with smart model router
- `learner.py` — signal analysis now uses cheap models, code generation uses top-tier

### Tests
- 348 tests pass (8 new: model router, restart signal, changelog updates)

## [0.5.0] - 2026-02-14

### Added
- **Self-Improving Supervisor** — supervisor evolves from self-healing to self-improving:
  - `notifier.py` — WhatsApp notifications for improvements, crashes, escalations, version bumps
  - `error_collector.py` — captures runtime tool execution errors from orchestrator for learning loop
  - **Self-correction loop** in `evolution.py` — when tests fail after applying a plan, LLM revises the plan (up to 3 attempts) before giving up
  - `revise_plan()` method feeds test output back to LLM to fix broken improvements
  - Runtime error signals integrated into `ContinuousLearner` signal gathering
  - Enhanced LLM analysis prompt: detects user frustration, wishes, complaints in Dutch/English
  - Improvement queue workers auto-start in both `koda2-supervisor run` and `orchestrator.startup()`
  - `koda2-supervisor queue` CLI command to inspect improvement queue status
  - Escalation to user via WhatsApp when all automatic retries exhausted

### Fixed
- `test_shutdown.py` — fixed hanging `test_bridge_uses_setsid` and failing graceful shutdown tests
- `test_orchestrator.py` — fixed `test_read_email` mock (fetch_all_emails vs fetch_emails)
- All 340 tests pass with no hangs

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
  - **Concurrent multi-agent workers** (default 3): LLM planning runs in parallel, git operations serialized via shared lock
  - New `planning` status — visible in dashboard when workers are computing plans
  - Configurable `max_workers` via API and constructor
  - Sources: user (dashboard), learner (auto-observations), supervisor, system
  - API: `GET /api/supervisor/queue`, `POST /api/supervisor/queue/start|stop`, `POST /api/supervisor/queue/{id}/cancel`
  - Dashboard panel with live queue view, active agent count, worker toggle, cancel buttons
  - ContinuousLearner now queues proposals instead of executing directly
- **EvolutionEngine split** — `plan_improvement` (parallel-safe LLM) and `apply_plan` (serialized git/test/commit) are now separate methods

### Fixed
- **Evolution Engine 400 error** — replaced invalid OpenRouter model `anthropic/claude-sonnet-4-20250514` with settings-configured model (fallback `anthropic/claude-3.5-sonnet`), added response body logging on API errors
- **Scheduler not executing tasks** — `orchestrator.startup()` was never called from `main.py` lifespan, so persisted tasks were never restored and system tasks never registered. Fixed by calling `startup()` properly.
- **Scheduler `chat` action type** — added `chat` action restore support so LLM-processed scheduled tasks survive reboots
- **Scheduler idempotent start** — `scheduler.start()` now safely handles double-start calls

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
