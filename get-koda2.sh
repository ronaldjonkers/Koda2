#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# Koda2 — Single-line installer / uninstaller / updater
#
# Install:
#   curl -fsSL https://raw.githubusercontent.com/ronaldjonkers/Koda2/main/get-koda2.sh | bash
#   wget -qO- https://raw.githubusercontent.com/ronaldjonkers/Koda2/main/get-koda2.sh | bash
#
# Uninstall:
#   curl -fsSL https://raw.githubusercontent.com/ronaldjonkers/Koda2/main/get-koda2.sh | bash -s -- --uninstall
#
# Update:
#   curl -fsSL https://raw.githubusercontent.com/ronaldjonkers/Koda2/main/get-koda2.sh | bash -s -- --update
#
# Supports: macOS (Intel + Apple Silicon), Ubuntu/Debian, Fedora/RHEL/CentOS,
#           Arch/Manjaro, openSUSE, Alpine Linux
# Idempotent: safe to run multiple times.
# ─────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── Colors & Emoji ───────────────────────────────────────────────────
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

INSTALL_DIR="${KODA2_INSTALL_DIR:-$HOME/Koda2}"
REPO_URL="${KODA2_REPO:-https://github.com/ronaldjonkers/Koda2.git}"
BRANCH="${KODA2_BRANCH:-main}"
ACTION="install"

# ── Parse arguments ──────────────────────────────────────────────────
for arg in "$@"; do
    case "$arg" in
        --uninstall|uninstall) ACTION="uninstall" ;;
        --update|update)       ACTION="update" ;;
        --help|-h)
            echo "Usage: get-koda2.sh [--uninstall|--update]"
            echo "  (no args)    Install Koda2"
            echo "  --update     Update to latest version"
            echo "  --uninstall  Remove Koda2 completely"
            exit 0
            ;;
    esac
done

# ── Banner ───────────────────────────────────────────────────────────
print_banner() {
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
    echo ""
}

# ── Detect platform ──────────────────────────────────────────────────
detect_platform() {
    OS="$(uname -s)"
    DISTRO="unknown"
    PKG_MGR=""

    case "$OS" in
        Darwin)
            PLATFORM="macos"
            ;;
        Linux)
            PLATFORM="linux"
            if [ -f /etc/os-release ]; then
                . /etc/os-release
                DISTRO="$ID"
            elif [ -f /etc/redhat-release ]; then
                DISTRO="rhel"
            fi
            if command -v apt-get &>/dev/null; then PKG_MGR="apt"
            elif command -v dnf &>/dev/null; then PKG_MGR="dnf"
            elif command -v yum &>/dev/null; then PKG_MGR="yum"
            elif command -v pacman &>/dev/null; then PKG_MGR="pacman"
            elif command -v zypper &>/dev/null; then PKG_MGR="zypper"
            elif command -v apk &>/dev/null; then PKG_MGR="apk"
            fi
            ;;
        *)
            fail "Unsupported OS: $OS — For Windows: irm .../get-koda2.ps1 | iex"
            ;;
    esac
    info "Platform: ${BOLD}$PLATFORM${NC} ($DISTRO)"
}

# ── Helpers ──────────────────────────────────────────────────────────
needs_python() {
    for candidate in python3.13 python3.12 python3; do
        if command -v "$candidate" &>/dev/null; then
            local ver
            ver=$("$candidate" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "0.0")
            local major minor
            major=$(echo "$ver" | cut -d. -f1)
            minor=$(echo "$ver" | cut -d. -f2)
            if [ "$major" -ge 3 ] && [ "$minor" -ge 12 ]; then
                return 1
            fi
        fi
    done
    return 0
}

needs_node() {
    if command -v node &>/dev/null; then
        local ver major
        ver=$(node -v 2>/dev/null | sed 's/v//')
        major=$(echo "$ver" | cut -d. -f1)
        if [ "$major" -ge 18 ]; then return 1; fi
    fi
    return 0
}

install_brew() {
    if [ "$PLATFORM" = "macos" ] && ! command -v brew &>/dev/null; then
        info "Installing Homebrew 🍺..."
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
        if [ -f /opt/homebrew/bin/brew ]; then
            eval "$(/opt/homebrew/bin/brew shellenv)"
            echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> "$HOME/.zprofile" 2>/dev/null || true
        fi
        ok "Homebrew installed"
    fi
}

install_git() {
    if command -v git &>/dev/null; then ok "Git $(git --version | awk '{print $3}')"; return; fi
    info "Installing Git..."
    case "$PLATFORM" in
        macos) brew install git ;;
        linux)
            case "$PKG_MGR" in
                apt)    sudo apt-get update -qq && sudo apt-get install -y -qq git ;;
                dnf)    sudo dnf install -y git ;;
                yum)    sudo yum install -y git ;;
                pacman) sudo pacman -Sy --noconfirm git ;;
                zypper) sudo zypper install -y git ;;
                apk)    sudo apk add git ;;
                *)      fail "Install git manually and re-run." ;;
            esac ;;
    esac
    ok "Git installed"
}

install_python() {
    if ! needs_python; then
        for c in python3.13 python3.12 python3; do
            if command -v "$c" &>/dev/null; then ok "Python $($c --version 2>&1 | awk '{print $2}') 🐍"; return; fi
        done
    fi
    info "Installing Python 3.12+ 🐍..."
    case "$PLATFORM" in
        macos) brew install python@3.12 ;;
        linux)
            case "$PKG_MGR" in
                apt)
                    sudo apt-get update -qq
                    sudo apt-get install -y -qq python3 python3-venv python3-pip python3-dev build-essential libffi-dev libssl-dev
                    if needs_python && [ "$DISTRO" = "ubuntu" ]; then
                        sudo apt-get install -y software-properties-common
                        sudo add-apt-repository -y ppa:deadsnakes/ppa
                        sudo apt-get update -qq
                        sudo apt-get install -y python3.12 python3.12-venv python3.12-dev
                    fi ;;
                dnf)    sudo dnf install -y python3 python3-pip python3-devel gcc libffi-devel openssl-devel ;;
                yum)    sudo yum install -y python3 python3-pip python3-devel gcc libffi-devel openssl-devel ;;
                pacman) sudo pacman -Sy --noconfirm python python-pip base-devel ;;
                zypper) sudo zypper install -y python3 python3-pip python3-devel gcc libffi-devel libopenssl-devel ;;
                apk)    sudo apk add python3 py3-pip python3-dev build-base libffi-dev openssl-dev ;;
                *)      fail "Install Python 3.12+ manually and re-run." ;;
            esac ;;
    esac
    ok "Python installed"
}

install_node() {
    if ! needs_node; then ok "Node.js $(node -v) 📦"; return; fi
    info "Installing Node.js 18+ 📦..."
    case "$PLATFORM" in
        macos) brew install node ;;
        linux)
            case "$PKG_MGR" in
                apt)  curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash - 2>/dev/null || true
                      sudo apt-get install -y -qq nodejs 2>/dev/null || true ;;
                dnf)  sudo dnf install -y nodejs npm 2>/dev/null || true ;;
                yum)  sudo yum install -y nodejs npm 2>/dev/null || true ;;
                pacman) sudo pacman -Sy --noconfirm nodejs npm 2>/dev/null || true ;;
                zypper) sudo zypper install -y nodejs npm 2>/dev/null || true ;;
                apk)  sudo apk add nodejs npm 2>/dev/null || true ;;
                *)    warn "Install Node.js 18+ manually for WhatsApp support." ;;
            esac ;;
    esac
    if ! needs_node; then ok "Node.js installed"
    else warn "Node.js 18+ not available — WhatsApp won't work until installed"; fi
}

# ══════════════════════════════════════════════════════════════════════
# ── INSTALL ──────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════
do_install() {
    print_banner
    echo -e "  ${MAGENTA}▶ Installing Koda2${NC}"
    echo ""

    detect_platform

    step "📦 Installing prerequisites"
    install_brew
    install_git
    install_python
    install_node

    step "📥 Downloading Koda2"
    if [ -d "$INSTALL_DIR/.git" ]; then
        info "Updating existing installation..."
        cd "$INSTALL_DIR"
        git pull origin "$BRANCH" --quiet
        ok "Repository updated"
    else
        info "Cloning to $INSTALL_DIR..."
        git clone --branch "$BRANCH" --depth 1 "$REPO_URL" "$INSTALL_DIR"
        ok "Repository cloned"
    fi
    cd "$INSTALL_DIR"

    step "🔧 Running installer"
    chmod +x install.sh
    ./install.sh

    echo ""
    echo -e "${BOLD}${GREEN}"
    echo "  ╔══════════════════════════════════════════════════╗"
    echo "  ║                                                  ║"
    echo "  ║   ✅  Koda2 installed successfully!              ║"
    echo "  ║                                                  ║"
    echo "  ╚══════════════════════════════════════════════════╝"
    echo -e "${NC}"
    echo -e "  ${BOLD}🚀 Start Koda2:${NC}"
    echo -e "     ${DIM}cd $INSTALL_DIR && source .venv/bin/activate && koda2${NC}"
    echo ""
    echo -e "  ${BOLD}⚙️  Configure:${NC}"
    echo -e "     ${DIM}cd $INSTALL_DIR && source .venv/bin/activate && python setup_wizard.py${NC}"
    echo ""
    echo -e "  ${BOLD}🔄 Update later:${NC}"
    echo -e "     ${DIM}curl -fsSL .../get-koda2.sh | bash -s -- --update${NC}"
    echo ""
    echo -e "  ${BOLD}🗑️  Uninstall:${NC}"
    echo -e "     ${DIM}curl -fsSL .../get-koda2.sh | bash -s -- --uninstall${NC}"
    echo ""

    read -rp "  Run the interactive setup wizard now? [Y/n] " RUN_WIZARD
    case "$RUN_WIZARD" in
        [nN]|[nN][oO]) info "Skipped — run setup_wizard.py later." ;;
        *)
            source .venv/bin/activate
            python setup_wizard.py
            ;;
    esac
}

# ══════════════════════════════════════════════════════════════════════
# ── UNINSTALL ────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════
do_uninstall() {
    print_banner
    echo -e "  ${RED}▶ Uninstalling Koda2${NC}"
    echo ""

    if [ ! -d "$INSTALL_DIR" ]; then
        warn "Koda2 not found at $INSTALL_DIR — nothing to uninstall."
        exit 0
    fi

    echo -e "  ${YELLOW}This will remove:${NC}"
    echo -e "    📁 $INSTALL_DIR  ${DIM}(code, venv, data)${NC}"
    if [ "$(uname -s)" = "Darwin" ]; then
        echo -e "    📋 ~/Library/LaunchAgents/com.koda2.agent.plist  ${DIM}(service)${NC}"
    else
        echo -e "    📋 ~/.config/systemd/user/koda2.service  ${DIM}(service)${NC}"
    fi
    echo ""

    read -rp "  Are you sure? Type 'yes' to confirm: " CONFIRM
    if [ "$CONFIRM" != "yes" ]; then
        echo -e "\n  ${GREEN}Cancelled — nothing was removed.${NC}"
        exit 0
    fi

    step "🛑 Stopping services"
    if [ "$(uname -s)" = "Darwin" ]; then
        PLIST="$HOME/Library/LaunchAgents/com.koda2.agent.plist"
        if [ -f "$PLIST" ]; then
            launchctl unload "$PLIST" 2>/dev/null || true
            rm -f "$PLIST"
            ok "macOS LaunchAgent removed"
        fi
    else
        if command -v systemctl &>/dev/null; then
            systemctl --user stop koda2 2>/dev/null || true
            systemctl --user disable koda2 2>/dev/null || true
            rm -f "$HOME/.config/systemd/user/koda2.service"
            systemctl --user daemon-reload 2>/dev/null || true
            ok "systemd service removed"
        fi
    fi

    # Stop Docker
    if [ -f "$INSTALL_DIR/docker-compose.yml" ] && command -v docker &>/dev/null; then
        info "Stopping Docker containers..."
        (cd "$INSTALL_DIR" && docker compose down --volumes 2>/dev/null) || true
        ok "Docker containers stopped"
    fi

    step "🗑️  Removing files"
    rm -rf "$INSTALL_DIR"
    ok "Removed $INSTALL_DIR"

    echo ""
    echo -e "${BOLD}${GREEN}"
    echo "  ╔══════════════════════════════════════════════════╗"
    echo "  ║                                                  ║"
    echo "  ║   🗑️   Koda2 uninstalled completely.             ║"
    echo "  ║                                                  ║"
    echo "  ╚══════════════════════════════════════════════════╝"
    echo -e "${NC}"
    echo -e "  ${DIM}Reinstall anytime: curl -fsSL .../get-koda2.sh | bash${NC}"
    echo ""
}

# ══════════════════════════════════════════════════════════════════════
# ── UPDATE ───────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════
do_update() {
    print_banner
    echo -e "  ${CYAN}▶ Updating Koda2${NC}"
    echo ""

    if [ ! -d "$INSTALL_DIR/.git" ]; then
        warn "Koda2 not found at $INSTALL_DIR — running full install instead."
        do_install
        return
    fi

    cd "$INSTALL_DIR"
    detect_platform

    step "🔍 Checking prerequisites"
    install_brew
    install_git
    install_python
    install_node

    step "📥 Pulling latest code"
    OLD_VERSION=$(cat koda2/__init__.py 2>/dev/null | grep __version__ | cut -d'"' -f2 || echo "unknown")
    git stash 2>/dev/null || true
    git pull --rebase origin "$BRANCH" 2>/dev/null || git pull origin "$BRANCH"
    git stash pop 2>/dev/null || true
    NEW_VERSION=$(cat koda2/__init__.py 2>/dev/null | grep __version__ | cut -d'"' -f2 || echo "unknown")
    if [ "$OLD_VERSION" != "$NEW_VERSION" ]; then
        ok "Version: ${OLD_VERSION} → ${GREEN}${BOLD}${NEW_VERSION}${NC}"
    else
        ok "Already on latest: ${BOLD}v${NEW_VERSION}${NC}"
    fi

    step "🐍 Updating Python environment"
    if [ ! -d ".venv" ]; then
        warn "Virtual environment missing — recreating..."
        PYTHON=""
        for c in python3.13 python3.12 python3; do
            if command -v "$c" &>/dev/null; then PYTHON="$c"; break; fi
        done
        $PYTHON -m venv .venv
    fi
    source .venv/bin/activate
    pip install --upgrade pip --quiet
    pip install -e ".[dev]" --quiet
    ok "Python dependencies up to date"

    step "📦 Updating WhatsApp bridge"
    WA_DIR="koda2/modules/messaging/whatsapp_bridge"
    if command -v npm &>/dev/null && [ -f "$WA_DIR/package.json" ]; then
        (cd "$WA_DIR" && npm install --production --silent 2>/dev/null) && \
            ok "WhatsApp bridge dependencies updated" || \
            warn "WhatsApp bridge npm update failed"
    fi

    step "🗄️  Updating database"
    python -c "
import asyncio
from koda2.database import init_db
asyncio.run(init_db())
" 2>/dev/null && ok "Database schema up to date" || warn "Database update skipped"

    step "📝 Checking .env for new variables"
    if [ -f ".env.example" ] && [ -f ".env" ]; then
        ADDED=0
        while IFS= read -r line; do
            key=$(echo "$line" | cut -d'=' -f1 | tr -d ' ')
            if [ -n "$key" ] && [[ ! "$key" =~ ^# ]] && ! grep -q "^$key=" .env 2>/dev/null; then
                echo "$line" >> .env
                info "  Added new variable: ${BOLD}$key${NC}"
                ADDED=$((ADDED + 1))
            fi
        done < .env.example
        if [ "$ADDED" -eq 0 ]; then ok ".env is complete"; fi
    fi

    step "🧪 Running tests"
    if python -m pytest tests/ -x --tb=short -q 2>/dev/null; then
        ok "All tests pass ✅"
    else
        warn "Some tests failed — review before deploying"
    fi

    step "🔍 System health check"
    python -c "
from koda2.config import get_settings
s = get_settings()
print(f'  Environment:  {s.koda2_env}')
print(f'  Log level:    {s.koda2_log_level}')
print(f'  API port:     {s.api_port}')
print(f'  WhatsApp:     {\"enabled\" if s.whatsapp_enabled else \"disabled\"}')
" 2>/dev/null && ok "Config loads successfully" || warn "Config check failed"

    echo ""
    echo -e "${BOLD}${GREEN}"
    echo "  ╔══════════════════════════════════════════════════╗"
    echo "  ║                                                  ║"
    echo "  ║   ✅  Koda2 updated to v${NEW_VERSION}!                   ║"
    echo "  ║                                                  ║"
    echo "  ╚══════════════════════════════════════════════════╝"
    echo -e "${NC}"
    echo -e "  ${BOLD}🚀 Restart Koda2:${NC}"
    echo -e "     ${DIM}cd $INSTALL_DIR && source .venv/bin/activate && koda2${NC}"
    echo ""
}

# ── Main ─────────────────────────────────────────────────────────────
case "$ACTION" in
    install)   do_install ;;
    uninstall) do_uninstall ;;
    update)    do_update ;;
esac
