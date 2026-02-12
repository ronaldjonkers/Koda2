#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# Koda2 — One-command installer (macOS / Linux)
# Supports: macOS (Intel + Apple Silicon), Ubuntu/Debian, Fedora/RHEL,
#           Arch, openSUSE, Alpine, and other Linux distros.
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
echo -e "${BLUE}       Koda2 — Installation                       ${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════${NC}"
echo ""

# ── 1. Detect OS & distro ───────────────────────────────────────────
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
        # Detect package manager
        if command -v apt-get &>/dev/null; then
            PKG_MGR="apt"
        elif command -v dnf &>/dev/null; then
            PKG_MGR="dnf"
        elif command -v yum &>/dev/null; then
            PKG_MGR="yum"
        elif command -v pacman &>/dev/null; then
            PKG_MGR="pacman"
        elif command -v zypper &>/dev/null; then
            PKG_MGR="zypper"
        elif command -v apk &>/dev/null; then
            PKG_MGR="apk"
        fi
        ;;
    *)
        fail "Unsupported OS: $OS. Use install.ps1 for Windows."
        ;;
esac
info "Platform: $PLATFORM ($DISTRO), package manager: ${PKG_MGR:-none}"

# ── 2. Install Homebrew on macOS if missing ──────────────────────────
if [ "$PLATFORM" = "macos" ]; then
    if ! command -v brew &>/dev/null; then
        info "Installing Homebrew..."
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
        # Add brew to PATH for Apple Silicon
        if [ -f /opt/homebrew/bin/brew ]; then
            eval "$(/opt/homebrew/bin/brew shellenv)"
        fi
        ok "Homebrew installed"
    else
        ok "Homebrew available"
    fi
fi

# ── 3. Install system dependencies ──────────────────────────────────
install_system_deps() {
    case "$PLATFORM" in
        macos)
            info "Installing system dependencies via Homebrew..."
            brew install python@3.12 node git || true
            ok "System dependencies installed (macOS)"
            ;;
        linux)
            case "$PKG_MGR" in
                apt)
                    info "Installing system dependencies via apt..."
                    sudo apt-get update -qq
                    sudo apt-get install -y -qq python3 python3-venv python3-pip \
                        python3-dev build-essential git curl nodejs npm \
                        libffi-dev libssl-dev 2>/dev/null || true
                    # If python3 < 3.12, try deadsnakes PPA (Ubuntu/Debian)
                    if ! python3 -c "import sys; assert sys.version_info >= (3,12)" 2>/dev/null; then
                        if [ "$DISTRO" = "ubuntu" ]; then
                            info "Adding deadsnakes PPA for Python 3.12..."
                            sudo apt-get install -y software-properties-common
                            sudo add-apt-repository -y ppa:deadsnakes/ppa
                            sudo apt-get update -qq
                            sudo apt-get install -y python3.12 python3.12-venv python3.12-dev
                        fi
                    fi
                    ;;
                dnf)
                    info "Installing system dependencies via dnf..."
                    sudo dnf install -y python3 python3-pip python3-devel \
                        gcc git nodejs npm libffi-devel openssl-devel 2>/dev/null || true
                    ;;
                yum)
                    info "Installing system dependencies via yum..."
                    sudo yum install -y python3 python3-pip python3-devel \
                        gcc git nodejs npm libffi-devel openssl-devel 2>/dev/null || true
                    ;;
                pacman)
                    info "Installing system dependencies via pacman..."
                    sudo pacman -Sy --noconfirm python python-pip nodejs npm \
                        git base-devel 2>/dev/null || true
                    ;;
                zypper)
                    info "Installing system dependencies via zypper..."
                    sudo zypper install -y python3 python3-pip python3-devel \
                        gcc git nodejs npm libffi-devel libopenssl-devel 2>/dev/null || true
                    ;;
                apk)
                    info "Installing system dependencies via apk..."
                    sudo apk add python3 py3-pip python3-dev build-base \
                        git nodejs npm libffi-dev openssl-dev 2>/dev/null || true
                    ;;
                *)
                    warn "Unknown package manager. Please install manually: python3.12+, node 18+, git"
                    ;;
            esac
            ok "System dependencies installed ($PKG_MGR)"
            ;;
    esac
}

install_system_deps

# ── 4. Find Python 3.12+ ────────────────────────────────────────────
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

[ -z "$PYTHON" ] && fail "Python 3.12+ not found after installation. Please install manually."
ok "Python: $($PYTHON --version)"

# ── 5. Check Node.js (for WhatsApp bridge) ──────────────────────────
if command -v node &>/dev/null; then
    NODE_VER=$(node -v | sed 's/v//')
    NODE_MAJOR=$(echo "$NODE_VER" | cut -d. -f1)
    if [ "$NODE_MAJOR" -ge 18 ]; then
        ok "Node.js: v$NODE_VER"
    else
        warn "Node.js $NODE_VER found, but 18+ recommended for WhatsApp bridge"
    fi
else
    warn "Node.js not found — needed for WhatsApp integration"
    if [ "$PLATFORM" = "macos" ]; then
        info "Install with: brew install node"
    elif [ "$PKG_MGR" = "apt" ]; then
        info "Install with: curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash - && sudo apt install -y nodejs"
    fi
fi

# ── 6. Create virtual environment ───────────────────────────────────
if [ ! -d ".venv" ]; then
    info "Creating virtual environment..."
    $PYTHON -m venv .venv
    ok "Virtual environment created"
else
    ok "Virtual environment exists"
fi

source .venv/bin/activate

# ── 7. Upgrade pip & install Koda2 ──────────────────────────────────
info "Upgrading pip..."
pip install --upgrade pip --quiet

info "Installing Koda2 and dependencies..."
pip install -e ".[dev]" --quiet
ok "Dependencies installed"

# ── 8. Install WhatsApp bridge dependencies ─────────────────────────
WA_BRIDGE_DIR="koda2/modules/messaging/whatsapp_bridge"
if command -v npm &>/dev/null && [ -f "$WA_BRIDGE_DIR/package.json" ]; then
    info "Installing WhatsApp bridge dependencies..."
    (cd "$WA_BRIDGE_DIR" && npm install --production --silent 2>/dev/null) && \
        ok "WhatsApp bridge dependencies installed" || \
        warn "WhatsApp bridge npm install failed (can retry later)"
fi

# ── 9. Create directories ───────────────────────────────────────────
for dir in data data/chroma data/generated data/whatsapp_session logs config plugins templates; do
    mkdir -p "$dir"
done
ok "Directories created"

# ── 10. Create .env if missing ──────────────────────────────────────
if [ ! -f ".env" ]; then
    cp .env.example .env
    info "Created .env from .env.example — please edit with your API keys"
else
    ok ".env file exists"
fi

# ── 11. Generate encryption key if not set ───────────────────────────
if ! grep -q "KODA2_ENCRYPTION_KEY=." .env 2>/dev/null; then
    ENC_KEY=$(python -c "
import base64, os
print(base64.urlsafe_b64encode(os.urandom(32)).decode())
")
    if grep -q "KODA2_ENCRYPTION_KEY=" .env; then
        sed -i.bak "s|KODA2_ENCRYPTION_KEY=.*|KODA2_ENCRYPTION_KEY=$ENC_KEY|" .env
        rm -f .env.bak
    else
        echo "KODA2_ENCRYPTION_KEY=$ENC_KEY" >> .env
    fi
    ok "Encryption key generated"
fi

# ── 12. Generate secret key if not set ───────────────────────────────
if grep -q "KODA2_SECRET_KEY=change-me" .env 2>/dev/null; then
    SECRET=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
    sed -i.bak "s|KODA2_SECRET_KEY=change-me|KODA2_SECRET_KEY=$SECRET|" .env
    rm -f .env.bak
    ok "Secret key generated"
fi

# ── 13. Initialize database ─────────────────────────────────────────
info "Initializing database..."
python -c "
import asyncio
from koda2.database import init_db
asyncio.run(init_db())
" 2>/dev/null && ok "Database initialized" || warn "Database init skipped (run manually if needed)"

# ── 14. Check Docker (optional) ─────────────────────────────────────
if command -v docker &>/dev/null; then
    ok "Docker available: $(docker --version | head -1)"
else
    warn "Docker not found — optional, only needed for containerized deployment"
fi

# ── 15. Check Redis (optional) ──────────────────────────────────────
if command -v redis-cli &>/dev/null; then
    redis-cli ping &>/dev/null 2>&1 && ok "Redis running" || \
        warn "Redis installed but not running (optional)"
else
    warn "Redis not found (optional)"
fi

# ── 16. Run smoke test ──────────────────────────────────────────────
info "Running smoke test..."
python -c "
from koda2.config import get_settings
s = get_settings()
print(f'  Environment: {s.koda2_env}')
print(f'  Log level: {s.koda2_log_level}')
" && ok "Config loads successfully"

# ── 17. Offer to install as system service ──────────────────────────
echo ""
echo -e "${BLUE}── Service Installation (optional) ──${NC}"
echo ""

install_service() {
    if [ "$PLATFORM" = "macos" ]; then
        PLIST_PATH="$HOME/Library/LaunchAgents/com.koda2.agent.plist"
        cat > "$PLIST_PATH" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.koda2.agent</string>
    <key>ProgramArguments</key>
    <array>
        <string>${SCRIPT_DIR}/.venv/bin/koda2</string>
    </array>
    <key>WorkingDirectory</key>
    <string>${SCRIPT_DIR}</string>
    <key>RunAtLoad</key>
    <false/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>${SCRIPT_DIR}/logs/koda2.log</string>
    <key>StandardErrorPath</key>
    <string>${SCRIPT_DIR}/logs/koda2.error.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin</string>
    </dict>
</dict>
</plist>
PLIST
        ok "macOS LaunchAgent installed at $PLIST_PATH"
        echo "  Start service:           launchctl load $PLIST_PATH"
        echo "  Stop service:            launchctl unload $PLIST_PATH"
        echo "  Enable start at login:   Change RunAtLoad to <true/> in the plist"
    else
        # Linux systemd
        if command -v systemctl &>/dev/null; then
            SERVICE_PATH="$HOME/.config/systemd/user/koda2.service"
            mkdir -p "$(dirname "$SERVICE_PATH")"
            cat > "$SERVICE_PATH" << UNIT
[Unit]
Description=Koda2 AI Executive Assistant
After=network.target

[Service]
Type=simple
WorkingDirectory=${SCRIPT_DIR}
ExecStart=${SCRIPT_DIR}/.venv/bin/koda2
Restart=on-failure
RestartSec=5
Environment=PATH=/usr/local/bin:/usr/bin:/bin
StandardOutput=append:${SCRIPT_DIR}/logs/koda2.log
StandardError=append:${SCRIPT_DIR}/logs/koda2.error.log

[Install]
WantedBy=default.target
UNIT
            systemctl --user daemon-reload
            ok "systemd user service installed at $SERVICE_PATH"
            echo "  Start service:           systemctl --user start koda2"
            echo "  Stop service:            systemctl --user stop koda2"
            echo "  Enable start at boot:    systemctl --user enable koda2"
            echo "                           sudo loginctl enable-linger \$USER"
        else
            warn "systemd not found — create a service manually or use: nohup koda2 &"
        fi
    fi
}

read -rp "  Install Koda2 as a system service? [y/N] " INSTALL_SVC
case "$INSTALL_SVC" in
    [yY]|[yY][eE][sS])
        install_service
        ;;
    *)
        info "Skipped service installation. You can run this script again to install later."
        ;;
esac

# ── 18. Offer auto-start on boot ────────────────────────────────────
read -rp "  Enable Koda2 to start automatically at boot/login? [y/N] " AUTO_START
case "$AUTO_START" in
    [yY]|[yY][eE][sS])
        if [ "$PLATFORM" = "macos" ]; then
            PLIST_PATH="$HOME/Library/LaunchAgents/com.koda2.agent.plist"
            if [ -f "$PLIST_PATH" ]; then
                sed -i.bak 's|<false/>|<true/>|' "$PLIST_PATH"
                rm -f "${PLIST_PATH}.bak"
                launchctl load "$PLIST_PATH" 2>/dev/null || true
                ok "Koda2 will start at login"
            else
                warn "Service not installed. Run installer again and choose to install the service first."
            fi
        else
            if command -v systemctl &>/dev/null; then
                systemctl --user enable koda2 2>/dev/null || true
                sudo loginctl enable-linger "$USER" 2>/dev/null || true
                ok "Koda2 will start at boot"
            fi
        fi
        ;;
    *)
        info "Auto-start not enabled."
        ;;
esac

# ── Done ─────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}═══════════════════════════════════════════════════${NC}"
echo -e "${GREEN}       Koda2 installed successfully!               ${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════════${NC}"
echo ""
echo "Next steps:"
echo "  1. Run the interactive setup:  python setup_wizard.py"
echo "  2. Start the server:           source .venv/bin/activate && koda2"
echo "  3. Or via Docker:              docker compose up -d"
echo "  4. WhatsApp: scan QR at        http://localhost:8000/api/whatsapp/qr"
echo ""
echo "API docs: http://localhost:8000/docs"
echo ""
