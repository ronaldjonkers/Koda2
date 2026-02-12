#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# Koda2 — Single-line installer
#
# Usage (pick one):
#   curl -fsSL https://raw.githubusercontent.com/ronaldjonkers/Koda2/main/get-koda2.sh | bash
#   wget -qO- https://raw.githubusercontent.com/ronaldjonkers/Koda2/main/get-koda2.sh | bash
#
# What it does:
#   1. Installs Homebrew (macOS) if missing
#   2. Installs Python 3.12+, Node.js 18+, Git via system package manager
#   3. Clones the Koda2 repository
#   4. Runs the full installer (install.sh)
#   5. Launches the interactive setup wizard
#
# Supports: macOS (Intel + Apple Silicon), Ubuntu/Debian, Fedora/RHEL/CentOS,
#           Arch/Manjaro, openSUSE, Alpine Linux
# Idempotent: safe to run multiple times.
# ─────────────────────────────────────────────────────────────────────
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

info()  { echo -e "${BLUE}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
fail()  { echo -e "${RED}[FAIL]${NC}  $*"; exit 1; }

INSTALL_DIR="${KODA2_INSTALL_DIR:-$HOME/Koda2}"
REPO_URL="${KODA2_REPO:-https://github.com/ronaldjonkers/Koda2.git}"
BRANCH="${KODA2_BRANCH:-main}"

echo ""
echo -e "${BOLD}${BLUE}"
echo "  ██╗  ██╗ ██████╗ ██████╗  █████╗ ██████╗ "
echo "  ██║ ██╔╝██╔═══██╗██╔══██╗██╔══██╗╚════██╗"
echo "  █████╔╝ ██║   ██║██║  ██║███████║ █████╔╝"
echo "  ██╔═██╗ ██║   ██║██║  ██║██╔══██║██╔═══╝ "
echo "  ██║  ██╗╚██████╔╝██████╔╝██║  ██║███████╗"
echo "  ╚═╝  ╚═╝ ╚═════╝ ╚═════╝ ╚═╝  ╚═╝╚══════╝"
echo -e "${NC}"
echo -e "${BOLD}  Professional AI Executive Assistant${NC}"
echo ""

# ── Detect platform ──────────────────────────────────────────────────
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
        fail "Unsupported OS: $OS. For Windows, use: powershell -ExecutionPolicy Bypass -File install.ps1"
        ;;
esac
info "Platform: $PLATFORM ($DISTRO)"

# ── Install Homebrew on macOS ────────────────────────────────────────
if [ "$PLATFORM" = "macos" ]; then
    if ! command -v brew &>/dev/null; then
        info "Installing Homebrew (required for macOS)..."
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
        # Apple Silicon path
        if [ -f /opt/homebrew/bin/brew ]; then
            eval "$(/opt/homebrew/bin/brew shellenv)"
            echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> "$HOME/.zprofile" 2>/dev/null || true
        fi
        ok "Homebrew installed"
    else
        ok "Homebrew found"
    fi
fi

# ── Install Git ──────────────────────────────────────────────────────
if ! command -v git &>/dev/null; then
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
                *)      fail "Cannot install git automatically. Install git manually and re-run." ;;
            esac
            ;;
    esac
    ok "Git installed"
else
    ok "Git found"
fi

# ── Install Python 3.12+ ────────────────────────────────────────────
needs_python() {
    for candidate in python3.13 python3.12 python3; do
        if command -v "$candidate" &>/dev/null; then
            local ver
            ver=$("$candidate" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "0.0")
            local major minor
            major=$(echo "$ver" | cut -d. -f1)
            minor=$(echo "$ver" | cut -d. -f2)
            if [ "$major" -ge 3 ] && [ "$minor" -ge 12 ]; then
                return 1  # found
            fi
        fi
    done
    return 0  # not found
}

if needs_python; then
    info "Installing Python 3.12+..."
    case "$PLATFORM" in
        macos) brew install python@3.12 ;;
        linux)
            case "$PKG_MGR" in
                apt)
                    sudo apt-get update -qq
                    sudo apt-get install -y -qq python3 python3-venv python3-pip python3-dev build-essential libffi-dev libssl-dev
                    # Ubuntu: try deadsnakes if still < 3.12
                    if needs_python && [ "$DISTRO" = "ubuntu" ]; then
                        info "Adding deadsnakes PPA for Python 3.12..."
                        sudo apt-get install -y software-properties-common
                        sudo add-apt-repository -y ppa:deadsnakes/ppa
                        sudo apt-get update -qq
                        sudo apt-get install -y python3.12 python3.12-venv python3.12-dev
                    fi
                    ;;
                dnf)    sudo dnf install -y python3 python3-pip python3-devel gcc libffi-devel openssl-devel ;;
                yum)    sudo yum install -y python3 python3-pip python3-devel gcc libffi-devel openssl-devel ;;
                pacman) sudo pacman -Sy --noconfirm python python-pip base-devel ;;
                zypper) sudo zypper install -y python3 python3-pip python3-devel gcc libffi-devel libopenssl-devel ;;
                apk)    sudo apk add python3 py3-pip python3-dev build-base libffi-dev openssl-dev ;;
                *)      fail "Cannot install Python automatically. Install Python 3.12+ manually and re-run." ;;
            esac
            ;;
    esac
    ok "Python installed"
else
    ok "Python 3.12+ found"
fi

# ── Install Node.js 18+ (for WhatsApp bridge) ───────────────────────
needs_node() {
    if command -v node &>/dev/null; then
        local ver
        ver=$(node -v 2>/dev/null | sed 's/v//')
        local major
        major=$(echo "$ver" | cut -d. -f1)
        if [ "$major" -ge 18 ]; then
            return 1
        fi
    fi
    return 0
}

if needs_node; then
    info "Installing Node.js 18+..."
    case "$PLATFORM" in
        macos) brew install node ;;
        linux)
            case "$PKG_MGR" in
                apt)
                    # Use NodeSource for a recent version
                    if ! command -v node &>/dev/null || needs_node; then
                        curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash - 2>/dev/null || true
                        sudo apt-get install -y -qq nodejs 2>/dev/null || true
                    fi
                    ;;
                dnf)    sudo dnf install -y nodejs npm 2>/dev/null || true ;;
                yum)    sudo yum install -y nodejs npm 2>/dev/null || true ;;
                pacman) sudo pacman -Sy --noconfirm nodejs npm 2>/dev/null || true ;;
                zypper) sudo zypper install -y nodejs npm 2>/dev/null || true ;;
                apk)    sudo apk add nodejs npm 2>/dev/null || true ;;
                *)      warn "Cannot install Node.js automatically. WhatsApp integration requires Node.js 18+." ;;
            esac
            ;;
    esac
    if ! needs_node; then
        ok "Node.js installed"
    else
        warn "Node.js 18+ not available — WhatsApp integration will not work until installed"
    fi
else
    ok "Node.js 18+ found"
fi

# ── Clone or update repository ───────────────────────────────────────
if [ -d "$INSTALL_DIR/.git" ]; then
    info "Updating existing Koda2 installation..."
    cd "$INSTALL_DIR"
    git pull origin "$BRANCH" --quiet
    ok "Repository updated"
else
    info "Cloning Koda2 to $INSTALL_DIR..."
    git clone --branch "$BRANCH" --depth 1 "$REPO_URL" "$INSTALL_DIR"
    ok "Repository cloned"
fi

cd "$INSTALL_DIR"

# ── Run the full installer ───────────────────────────────────────────
info "Running Koda2 installer..."
chmod +x install.sh
./install.sh

# ── Launch setup wizard ──────────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}Installation complete!${NC}"
echo ""
echo -e "  ${BOLD}Start Koda2:${NC}"
echo "    cd $INSTALL_DIR"
echo "    source .venv/bin/activate"
echo "    koda2"
echo ""
echo -e "  ${BOLD}Configure (interactive):${NC}"
echo "    cd $INSTALL_DIR"
echo "    source .venv/bin/activate"
echo "    python setup_wizard.py"
echo ""
echo -e "  ${BOLD}Quick one-liner to start:${NC}"
echo "    cd $INSTALL_DIR && source .venv/bin/activate && koda2"
echo ""

read -rp "  Run the interactive setup wizard now? [Y/n] " RUN_WIZARD
case "$RUN_WIZARD" in
    [nN]|[nN][oO])
        info "Skipped. Run later with: cd $INSTALL_DIR && source .venv/bin/activate && python setup_wizard.py"
        ;;
    *)
        source .venv/bin/activate
        python setup_wizard.py
        ;;
esac
