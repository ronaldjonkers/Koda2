#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# Koda2 — Comprehensive Update Script
# Checks all prerequisites, updates code, deps, bridge, DB, .env, tests.
# ─────────────────────────────────────────────────────────────────────
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

info()  { echo -e "  ${CYAN}▸${NC} $*"; }
ok()    { echo -e "  ${GREEN}✔${NC} $*"; }
warn()  { echo -e "  ${YELLOW}⚠${NC}  $*"; }
fail()  { echo -e "  ${RED}✘${NC} $*"; exit 1; }
step()  { echo -e "\n${BOLD}${BLUE}━━━ $* ━━━${NC}"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo ""
echo -e "${BOLD}${BLUE}"
echo "  ██╗  ██╗ ██████╗ ██████╗  █████╗ ██████╗ "
echo "  ██║ ██╔╝██╔═══██╗██╔══██╗██╔══██╗╚════██╗"
echo "  █████╔╝ ██║   ██║██║  ██║███████║ █████╔╝"
echo "  ██╔═██╗ ██║   ██║██║  ██║██╔══██║██╔═══╝ "
echo "  ██║  ██╗╚██████╔╝██████╔╝██║  ██║███████╗"
echo "  ╚═╝  ╚═╝ ╚═════╝ ╚═════╝ ╚═╝  ╚═╝╚══════╝"
echo -e "${NC}"
echo -e "  ${DIM}Professional AI Executive Assistant${NC}"
echo -e "  ${CYAN}▶ Updating...${NC}"
echo ""

# ── 1. Check prerequisites ───────────────────────────────────────────
step "🔍 Checking prerequisites"

# Python
PYTHON=""
for candidate in python3.13 python3.12 python3; do
    if command -v "$candidate" &>/dev/null; then
        ver=$("$candidate" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "0.0")
        major=$(echo "$ver" | cut -d. -f1)
        minor=$(echo "$ver" | cut -d. -f2)
        if [ "$major" -ge 3 ] && [ "$minor" -ge 12 ]; then
            PYTHON="$candidate"
            break
        fi
    fi
done
if [ -z "$PYTHON" ]; then
    fail "Python 3.12+ not found. Run install.sh first."
fi
ok "Python $($PYTHON --version 2>&1 | awk '{print $2}') 🐍"

# Node.js
if command -v node &>/dev/null; then
    NODE_VER=$(node -v | sed 's/v//')
    NODE_MAJOR=$(echo "$NODE_VER" | cut -d. -f1)
    if [ "$NODE_MAJOR" -ge 18 ]; then
        ok "Node.js v$NODE_VER 📦"
    else
        warn "Node.js $NODE_VER found, but 18+ recommended"
    fi
else
    warn "Node.js not found — WhatsApp bridge won't work"
fi

# Git
if command -v git &>/dev/null; then
    ok "Git $(git --version | awk '{print $3}')"
else
    fail "Git not found. Install git first."
fi

# ── 2. Pull latest code ─────────────────────────────────────────────
step "📥 Pulling latest code"

if [ -d ".git" ]; then
    OLD_VERSION=$(grep __version__ koda2/__init__.py 2>/dev/null | cut -d'"' -f2 || echo "unknown")
    git stash 2>/dev/null || true
    git pull --rebase origin main 2>/dev/null || git pull origin main
    git stash pop 2>/dev/null || true
    NEW_VERSION=$(grep __version__ koda2/__init__.py 2>/dev/null | cut -d'"' -f2 || echo "unknown")
    if [ "$OLD_VERSION" != "$NEW_VERSION" ]; then
        ok "Version: ${OLD_VERSION} → ${GREEN}${BOLD}${NEW_VERSION}${NC} 🎉"
    else
        ok "Already on latest: ${BOLD}v${NEW_VERSION}${NC}"
    fi
else
    warn "Not a git repo — skipping code pull"
    NEW_VERSION=$(grep __version__ koda2/__init__.py 2>/dev/null | cut -d'"' -f2 || echo "unknown")
fi

# ── 3. Virtual environment ──────────────────────────────────────────
step "🐍 Python environment"

if [ ! -d ".venv" ]; then
    warn "Virtual environment missing — recreating..."
    $PYTHON -m venv .venv
    ok "Virtual environment created"
fi

source .venv/bin/activate

info "Upgrading pip..."
pip install --upgrade pip --quiet
info "Installing/updating dependencies..."
pip install -e ".[dev]" --quiet
ok "Python dependencies up to date"

# ── 4. WhatsApp bridge ──────────────────────────────────────────────
step "📱 WhatsApp bridge"

WA_DIR="koda2/modules/messaging/whatsapp_bridge"
if command -v npm &>/dev/null && [ -f "$WA_DIR/package.json" ]; then
    info "Updating WhatsApp bridge dependencies..."
    (cd "$WA_DIR" && npm install --production --silent 2>/dev/null) && \
        ok "WhatsApp bridge dependencies updated" || \
        warn "WhatsApp bridge npm update failed"
else
    if [ -f "$WA_DIR/package.json" ]; then
        warn "npm not found — WhatsApp bridge dependencies not updated"
    else
        ok "WhatsApp bridge not present (skipped)"
    fi
fi

# ── 5. Database ─────────────────────────────────────────────────────
step "🗄️  Database"

info "Updating database schema..."
python -c "
import asyncio
from koda2.database import init_db
asyncio.run(init_db())
" 2>/dev/null && ok "Database schema up to date" || warn "Database update skipped"

# ── 6. Configuration ────────────────────────────────────────────────
step "📝 Configuration"

if [ -f ".env.example" ] && [ -f ".env" ]; then
    ADDED=0
    while IFS= read -r line; do
        key=$(echo "$line" | cut -d'=' -f1 | tr -d ' ')
        if [ -n "$key" ] && [[ ! "$key" =~ ^# ]] && ! grep -q "^$key=" .env 2>/dev/null; then
            echo "$line" >> .env
            info "Added new variable: ${BOLD}$key${NC}"
            ADDED=$((ADDED + 1))
        fi
    done < .env.example
    if [ "$ADDED" -eq 0 ]; then
        ok ".env is complete — no new variables"
    else
        ok "Added $ADDED new variable(s) to .env"
    fi
elif [ ! -f ".env" ]; then
    warn ".env not found — run setup_wizard.py to configure"
fi

# ── 7. Directories ──────────────────────────────────────────────────
step "📁 Directories"

for dir in data data/chroma data/generated data/whatsapp_session logs config plugins templates; do
    mkdir -p "$dir"
done
ok "All directories present"

# ── 8. Tests ────────────────────────────────────────────────────────
step "🧪 Running tests"

if python -m pytest tests/ -x --tb=short -q 2>/dev/null; then
    ok "All tests pass ✅"
else
    warn "Some tests failed — review before deploying"
fi

# ── 9. Health check ─────────────────────────────────────────────────
step "🔍 System health check"

python -c "
from koda2.config import get_settings
s = get_settings()
print(f'  Environment:  {s.koda2_env}')
print(f'  API port:     {s.api_port}')
wa = 'enabled' if s.whatsapp_enabled else 'disabled'
print(f'  WhatsApp:     {wa}')
" 2>/dev/null && ok "Config loads successfully" || warn "Config check failed"

# ── 10. Docker (optional) ───────────────────────────────────────────
if [ -f "docker-compose.yml" ] && command -v docker &>/dev/null; then
    step "🐳 Docker"
    read -rp "  Rebuild Docker containers? [y/N] " REPLY
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        info "Rebuilding Docker containers..."
        docker compose build --no-cache
        docker compose up -d
        ok "Docker containers rebuilt and started 🐳"
    else
        info "Skipped Docker rebuild"
    fi
fi

# ── Done ─────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}"
echo "  ╔══════════════════════════════════════════════════╗"
echo "  ║                                                  ║"
echo "  ║   ✅  Koda2 updated to v${NEW_VERSION}!                   ║"
echo "  ║                                                  ║"
echo "  ╚══════════════════════════════════════════════════╝"
echo -e "${NC}"
echo -e "  ${BOLD}🚀 Restart Koda2:${NC}"
echo -e "     ${DIM}source .venv/bin/activate && koda2${NC}"
echo ""
