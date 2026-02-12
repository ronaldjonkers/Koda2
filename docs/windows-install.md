# Koda2 — Windows Installation Guide

## Prerequisites

| Software | Version | Install Command |
|----------|---------|-----------------|
| **Python** | 3.12+ | `winget install Python.Python.3.12` |
| **Node.js** | 18+ (for WhatsApp) | `winget install OpenJS.NodeJS.LTS` |
| **Git** | Latest | `winget install Git.Git` |

> **Tip:** You can also install via [Scoop](https://scoop.sh): `scoop install python nodejs git`

## Installation

### Option 1: PowerShell Script (Recommended)

```powershell
# Clone the repository
git clone https://github.com/ronaldjonkers/Koda2.git
cd Koda2

# Run the installer
powershell -ExecutionPolicy Bypass -File install.ps1
```

The script will:
1. Verify Python 3.12+ and Node.js 18+
2. Create a virtual environment
3. Install all Python dependencies
4. Install WhatsApp bridge Node.js dependencies
5. Create required directories
6. Generate encryption and secret keys
7. Initialize the database
8. Optionally create a Task Scheduler entry for auto-start

### Option 2: Manual Installation

```powershell
# 1. Clone
git clone https://github.com/ronaldjonkers/Koda2.git
cd Koda2

# 2. Create virtual environment
python -m venv .venv
.venv\Scripts\activate

# 3. Install dependencies
pip install -e ".[dev]"

# 4. Install WhatsApp bridge (optional)
cd koda2\modules\messaging\whatsapp_bridge
npm install --production
cd ..\..\..\..

# 5. Create directories
mkdir data, data\chroma, data\generated, data\whatsapp_session, logs, config, plugins, templates

# 6. Configure
copy .env.example .env
# Edit .env with your API keys

# 7. Run setup wizard
python setup_wizard.py

# 8. Initialize database
python -c "import asyncio; from koda2.database import init_db; asyncio.run(init_db())"
```

## Running Koda2

### Start manually

```powershell
cd Koda2
.venv\Scripts\activate
koda2
```

### Run as a Windows Service (auto-start)

#### Option A: Task Scheduler (created by installer)

The installer can create a Task Scheduler entry. To manage it:

```powershell
# Check status
schtasks /query /tn Koda2

# Run now
schtasks /run /tn Koda2

# Delete
schtasks /delete /tn Koda2 /f
```

#### Option B: NSSM (Non-Sucking Service Manager)

For a proper Windows service:

```powershell
# Install NSSM
winget install NSSM

# Create service
nssm install Koda2 "C:\path\to\Koda2\.venv\Scripts\koda2.exe"
nssm set Koda2 AppDirectory "C:\path\to\Koda2"
nssm set Koda2 AppStdout "C:\path\to\Koda2\logs\koda2.log"
nssm set Koda2 AppStderr "C:\path\to\Koda2\logs\koda2.error.log"

# Start
nssm start Koda2

# Stop
nssm stop Koda2
```

## WhatsApp Setup

1. Set `WHATSAPP_ENABLED=true` in `.env`
2. Start Koda2: `koda2`
3. Open `http://localhost:8000/api/whatsapp/qr` in your browser
4. Scan the QR code with your WhatsApp phone app
5. Send a message to yourself — Koda2 will process it and reply

## Troubleshooting

### Python not found
```powershell
# Check if Python is in PATH
python --version

# If not, use the py launcher
py -3.12 --version

# Or install via winget
winget install Python.Python.3.12
```

### Node.js not found
```powershell
winget install OpenJS.NodeJS.LTS
# Restart your terminal after installation
```

### Permission errors
Run PowerShell as Administrator, or use:
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### Port already in use
Edit `.env` and change `API_PORT` to a different port (e.g., 8001).
