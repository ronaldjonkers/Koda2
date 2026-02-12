#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# Koda2 — Complete Uninstaller
# ─────────────────────────────────────────────────────────────────────
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

info()  { echo -e "  ${CYAN}▸${NC} $*"; }
ok()    { echo -e "  ${GREEN}✔${NC} $*"; }
warn()  { echo -e "  ${YELLOW}⚠${NC}  $*"; }
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
echo -e "  ${RED}▶ Uninstaller${NC}"
echo ""

echo -e "  ${YELLOW}This will remove:${NC}"
echo -e "    📁 Virtual environment (.venv)"
echo -e "    📁 Data, logs, caches"
echo -e "    📋 System service (if installed)"
echo -e "    ${DIM}Source code and .env are preserved${NC}"
echo ""

read -rp "  Continue? [y/N] " REPLY
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo -e "\n  ${GREEN}Cancelled — nothing was removed.${NC}\n"
    exit 0
fi

step "🛑 Stopping services"

# Stop Docker containers
if command -v docker &>/dev/null; then
    info "Stopping Docker containers..."
    docker compose down --volumes 2>/dev/null || true
    ok "Docker containers stopped"
fi

# Remove macOS LaunchAgent
if [ "$(uname -s)" = "Darwin" ]; then
    PLIST="$HOME/Library/LaunchAgents/com.koda2.agent.plist"
    if [ -f "$PLIST" ]; then
        launchctl unload "$PLIST" 2>/dev/null || true
        rm -f "$PLIST"
        ok "macOS LaunchAgent removed"
    fi
else
    # Remove systemd service
    if command -v systemctl &>/dev/null; then
        systemctl --user stop koda2 2>/dev/null || true
        systemctl --user disable koda2 2>/dev/null || true
        rm -f "$HOME/.config/systemd/user/koda2.service"
        systemctl --user daemon-reload 2>/dev/null || true
        ok "systemd service removed"
    fi
fi

step "🗑️  Removing files"

# Remove virtual environment
if [ -d ".venv" ]; then
    rm -rf .venv
    ok "Virtual environment removed"
fi

# Remove data directories
for dir in data logs plugins/__pycache__ __pycache__ .pytest_cache htmlcov .mypy_cache .ruff_cache; do
    if [ -d "$dir" ]; then
        rm -rf "$dir"
        ok "Removed $dir"
    fi
done

# Remove generated files
rm -f .coverage
rm -rf koda2.egg-info
rm -rf build dist

# Remove config secrets (but keep templates)
rm -f config/google_token.json

# Remove WhatsApp bridge node_modules
if [ -d "koda2/modules/messaging/whatsapp_bridge/node_modules" ]; then
    rm -rf "koda2/modules/messaging/whatsapp_bridge/node_modules"
    ok "WhatsApp bridge node_modules removed"
fi

echo ""
echo -e "${BOLD}${GREEN}"
echo "  ╔══════════════════════════════════════════════════╗"
echo "  ║                                                  ║"
echo "  ║   🗑️   Koda2 uninstalled.                        ║"
echo "  ║                                                  ║"
echo "  ╚══════════════════════════════════════════════════╝"
echo -e "${NC}"
echo -e "  ${DIM}Source code and .env were preserved.${NC}"
echo -e "  ${DIM}To remove everything: rm -rf $SCRIPT_DIR${NC}"
echo -e "  ${DIM}Reinstall: ./install.sh${NC}"
echo ""
