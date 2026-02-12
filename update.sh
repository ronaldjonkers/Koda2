#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# Koda2 — Update Script
# ─────────────────────────────────────────────────────────────────────
set -euo pipefail

BLUE='\033[0;34m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${BLUE}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo ""
echo -e "${BLUE}═══════════════════════════════════════════════════${NC}"
echo -e "${BLUE}       Koda2 — Update                        ${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════${NC}"
echo ""

# ── 1. Pull latest code ─────────────────────────────────────────────
if [ -d ".git" ]; then
    info "Pulling latest code..."
    git stash 2>/dev/null || true
    git pull --rebase origin main 2>/dev/null || git pull origin main
    git stash pop 2>/dev/null || true
    ok "Code updated"
else
    warn "Not a git repo — skipping code pull"
fi

# ── 2. Activate venv ────────────────────────────────────────────────
if [ ! -d ".venv" ]; then
    warn "Virtual environment not found — running install.sh first"
    bash install.sh
    exit 0
fi

source .venv/bin/activate

# ── 3. Update dependencies ──────────────────────────────────────────
info "Updating dependencies..."
pip install --upgrade pip --quiet
pip install -e ".[dev]" --quiet
ok "Dependencies updated"

# ── 4. Run database migrations ──────────────────────────────────────
info "Updating database..."
python -c "
import asyncio
from koda2.database import init_db
asyncio.run(init_db())
" 2>/dev/null && ok "Database updated" || warn "Database update skipped"

# ── 5. Update .env with new variables ────────────────────────────────
if [ -f ".env.example" ] && [ -f ".env" ]; then
    info "Checking for new environment variables..."
    while IFS= read -r line; do
        key=$(echo "$line" | cut -d'=' -f1 | tr -d ' ')
        if [ -n "$key" ] && [[ ! "$key" =~ ^# ]] && ! grep -q "^$key=" .env 2>/dev/null; then
            echo "$line" >> .env
            info "  Added new variable: $key"
        fi
    done < .env.example
fi

# ── 6. Run tests ────────────────────────────────────────────────────
info "Running tests..."
if pytest tests/ -x --tb=short -q 2>/dev/null; then
    ok "All tests pass"
else
    warn "Some tests failed — review before deploying"
fi

# ── 7. Docker rebuild (if using Docker) ──────────────────────────────
if [ -f "docker-compose.yml" ] && command -v docker &>/dev/null; then
    read -p "Rebuild Docker containers? [y/N] " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        info "Rebuilding Docker containers..."
        docker compose build --no-cache
        docker compose up -d
        ok "Docker containers rebuilt and started"
    fi
fi

echo ""
echo -e "${GREEN}═══════════════════════════════════════════════════${NC}"
echo -e "${GREEN}       Koda2 updated successfully!           ${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════════${NC}"
echo ""
