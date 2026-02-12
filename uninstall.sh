#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# Koda2 — Complete Uninstaller
# ─────────────────────────────────────────────────────────────────────
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo ""
echo -e "${RED}═══════════════════════════════════════════════════${NC}"
echo -e "${RED}       Koda2 — Uninstall                     ${NC}"
echo -e "${RED}═══════════════════════════════════════════════════${NC}"
echo ""

read -p "This will remove all Koda2 data, venv, and caches. Continue? [y/N] " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Cancelled."
    exit 0
fi

# Stop Docker containers
if command -v docker &>/dev/null; then
    echo -e "${YELLOW}Stopping Docker containers...${NC}"
    docker compose down --volumes 2>/dev/null || true
fi

# Remove virtual environment
if [ -d ".venv" ]; then
    echo -e "${YELLOW}Removing virtual environment...${NC}"
    rm -rf .venv
fi

# Remove data directories
for dir in data logs plugins/__pycache__ __pycache__ .pytest_cache htmlcov .mypy_cache .ruff_cache; do
    if [ -d "$dir" ]; then
        echo -e "${YELLOW}Removing $dir...${NC}"
        rm -rf "$dir"
    fi
done

# Remove generated files
rm -f .coverage
rm -rf koda2.egg-info
rm -rf build dist

# Remove config secrets (but keep templates)
rm -f config/google_token.json

echo ""
echo -e "${GREEN}Koda2 uninstalled.${NC}"
echo "Note: .env and source code were preserved. Remove manually if desired."
echo ""
