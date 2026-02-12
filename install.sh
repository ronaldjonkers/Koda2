#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# ExecutiveAI — One-command installer (macOS / Linux)
# Idempotent: safe to run multiple times.
# ─────────────────────────────────────────────────────────────────────
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info()  { echo -e "${BLUE}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
fail()  { echo -e "${RED}[FAIL]${NC}  $*"; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo ""
echo -e "${BLUE}═══════════════════════════════════════════════════${NC}"
echo -e "${BLUE}       ExecutiveAI — Installation                  ${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════${NC}"
echo ""

# ── 1. Detect OS ─────────────────────────────────────────────────────
OS="$(uname -s)"
case "$OS" in
    Darwin) PLATFORM="macos" ;;
    Linux)  PLATFORM="linux" ;;
    *)      fail "Unsupported OS: $OS" ;;
esac
info "Platform detected: $PLATFORM"

# ── 2. Check Python 3.12+ ───────────────────────────────────────────
PYTHON=""
for candidate in python3.12 python3.13 python3; do
    if command -v "$candidate" &>/dev/null; then
        ver=$("$candidate" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
        major=$(echo "$ver" | cut -d. -f1)
        minor=$(echo "$ver" | cut -d. -f2)
        if [ "$major" -ge 3 ] && [ "$minor" -ge 12 ]; then
            PYTHON="$candidate"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    warn "Python 3.12+ not found."
    if [ "$PLATFORM" = "macos" ]; then
        if command -v brew &>/dev/null; then
            info "Installing Python 3.12 via Homebrew..."
            brew install python@3.12
            PYTHON="python3.12"
        else
            fail "Please install Homebrew (https://brew.sh) or Python 3.12+ manually."
        fi
    else
        fail "Please install Python 3.12+ (e.g., sudo apt install python3.12 python3.12-venv)"
    fi
fi
ok "Python: $($PYTHON --version)"

# ── 3. Create virtual environment ───────────────────────────────────
if [ ! -d ".venv" ]; then
    info "Creating virtual environment..."
    $PYTHON -m venv .venv
    ok "Virtual environment created"
else
    ok "Virtual environment exists"
fi

source .venv/bin/activate

# ── 4. Upgrade pip ───────────────────────────────────────────────────
info "Upgrading pip..."
pip install --upgrade pip --quiet

# ── 5. Install dependencies ─────────────────────────────────────────
info "Installing ExecutiveAI and dependencies..."
pip install -e ".[dev]" --quiet
ok "Dependencies installed"

# ── 6. Create directories ───────────────────────────────────────────
for dir in data data/chroma data/generated logs config plugins templates; do
    mkdir -p "$dir"
done
ok "Directories created"

# ── 7. Create .env if missing ───────────────────────────────────────
if [ ! -f ".env" ]; then
    cp .env.example .env
    info "Created .env from .env.example — please edit with your API keys"
else
    ok ".env file exists"
fi

# ── 8. Generate encryption key if not set ────────────────────────────
if ! grep -q "EXECUTIVEAI_ENCRYPTION_KEY=." .env 2>/dev/null; then
    ENC_KEY=$(python -c "
import base64, os
print(base64.urlsafe_b64encode(os.urandom(32)).decode())
")
    if grep -q "EXECUTIVEAI_ENCRYPTION_KEY=" .env; then
        sed -i.bak "s|EXECUTIVEAI_ENCRYPTION_KEY=.*|EXECUTIVEAI_ENCRYPTION_KEY=$ENC_KEY|" .env
        rm -f .env.bak
    else
        echo "EXECUTIVEAI_ENCRYPTION_KEY=$ENC_KEY" >> .env
    fi
    ok "Encryption key generated"
fi

# ── 9. Generate secret key if not set ────────────────────────────────
if grep -q "EXECUTIVEAI_SECRET_KEY=change-me" .env 2>/dev/null; then
    SECRET=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
    sed -i.bak "s|EXECUTIVEAI_SECRET_KEY=change-me|EXECUTIVEAI_SECRET_KEY=$SECRET|" .env
    rm -f .env.bak
    ok "Secret key generated"
fi

# ── 10. Initialize database ─────────────────────────────────────────
info "Initializing database..."
python -c "
import asyncio
from executiveai.database import init_db
asyncio.run(init_db())
" 2>/dev/null && ok "Database initialized" || warn "Database init skipped (run manually if needed)"

# ── 11. Check Docker (optional) ─────────────────────────────────────
if command -v docker &>/dev/null; then
    ok "Docker available: $(docker --version | head -1)"
    if command -v docker-compose &>/dev/null || docker compose version &>/dev/null 2>&1; then
        ok "Docker Compose available"
    fi
else
    warn "Docker not found — optional, only needed for containerized deployment"
fi

# ── 12. Check Redis (optional) ──────────────────────────────────────
if command -v redis-cli &>/dev/null; then
    if redis-cli ping &>/dev/null 2>&1; then
        ok "Redis running"
    else
        warn "Redis installed but not running (optional — start with: redis-server)"
    fi
else
    warn "Redis not found (optional — install with: brew install redis)"
fi

# ── 13. Run quick tests ─────────────────────────────────────────────
info "Running smoke tests..."
python -c "
from executiveai.config import get_settings
s = get_settings()
print(f'  Environment: {s.executiveai_env}')
print(f'  Log level: {s.executiveai_log_level}')
" && ok "Config loads successfully"

echo ""
echo -e "${GREEN}═══════════════════════════════════════════════════${NC}"
echo -e "${GREEN}       ExecutiveAI installed successfully!         ${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════════${NC}"
echo ""
echo "Next steps:"
echo "  1. Edit .env with your API keys (at minimum one LLM provider)"
echo "  2. Run the interactive setup:  python setup_wizard.py"
echo "  3. Start the server:           source .venv/bin/activate && executiveai"
echo "  4. Or via Docker:              docker compose up -d"
echo ""
echo "API docs will be at: http://localhost:8000/docs"
echo ""
