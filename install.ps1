#Requires -Version 5.1
<#
.SYNOPSIS
    Koda2 — Windows Installer (PowerShell)
.DESCRIPTION
    Installs Koda2 AI Executive Assistant on Windows.
    Requires: Python 3.12+, Node.js 18+ (for WhatsApp), Git.
    Run as: powershell -ExecutionPolicy Bypass -File install.ps1
#>

$ErrorActionPreference = "Stop"

function Write-Info  { Write-Host "[INFO]  $args" -ForegroundColor Cyan }
function Write-Ok    { Write-Host "[OK]    $args" -ForegroundColor Green }
function Write-Warn  { Write-Host "[WARN]  $args" -ForegroundColor Yellow }
function Write-Fail  { Write-Host "[FAIL]  $args" -ForegroundColor Red; exit 1 }

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

Write-Host ""
Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host "       Koda2 - Installation (Windows)                   " -ForegroundColor Cyan
Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host ""

# -- 1. Check Python 3.12+ ------------------------------------------------
Write-Info "Checking Python..."
$Python = $null
foreach ($candidate in @("python3.12", "python3.13", "python3", "python", "py")) {
    try {
        $ver = & $candidate -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
        if ($ver) {
            $parts = $ver.Split(".")
            if ([int]$parts[0] -ge 3 -and [int]$parts[1] -ge 12) {
                $Python = $candidate
                break
            }
        }
    } catch { }
}

if (-not $Python) {
    # Try py launcher
    try {
        $ver = & py -3.12 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
        if ($ver) { $Python = "py -3.12" }
    } catch { }
}

if (-not $Python) {
    Write-Warn "Python 3.12+ not found."
    Write-Info "Install from: https://www.python.org/downloads/"
    Write-Info "Or via winget: winget install Python.Python.3.12"
    Write-Info "Or via scoop:  scoop install python"
    Write-Fail "Python 3.12+ is required. Install it and re-run this script."
}
Write-Ok "Python: $(& $Python --version 2>&1)"

# -- 2. Check Node.js -----------------------------------------------------
Write-Info "Checking Node.js..."
$NodeOk = $false
try {
    $nodeVer = (node -v 2>$null) -replace 'v', ''
    $nodeMajor = [int]($nodeVer.Split(".")[0])
    if ($nodeMajor -ge 18) {
        Write-Ok "Node.js: v$nodeVer"
        $NodeOk = $true
    } else {
        Write-Warn "Node.js $nodeVer found, but 18+ recommended for WhatsApp"
    }
} catch {
    Write-Warn "Node.js not found - needed for WhatsApp integration"
    Write-Info "Install from: https://nodejs.org/"
    Write-Info "Or via winget: winget install OpenJS.NodeJS.LTS"
}

# -- 3. Create virtual environment ----------------------------------------
if (-not (Test-Path ".venv")) {
    Write-Info "Creating virtual environment..."
    & $Python -m venv .venv
    Write-Ok "Virtual environment created"
} else {
    Write-Ok "Virtual environment exists"
}

# Activate
$ActivateScript = Join-Path $ScriptDir ".venv\Scripts\Activate.ps1"
if (Test-Path $ActivateScript) {
    & $ActivateScript
} else {
    Write-Fail "Cannot activate virtual environment. Ensure Python venv is installed."
}

# -- 4. Install Koda2 -----------------------------------------------------
Write-Info "Upgrading pip..."
pip install --upgrade pip --quiet 2>$null

Write-Info "Installing Koda2 and dependencies..."
pip install -e ".[dev]" --quiet 2>$null
Write-Ok "Dependencies installed"

# -- 5. Install WhatsApp bridge deps --------------------------------------
$WaBridgeDir = Join-Path $ScriptDir "koda2\modules\messaging\whatsapp_bridge"
if ($NodeOk -and (Test-Path (Join-Path $WaBridgeDir "package.json"))) {
    Write-Info "Installing WhatsApp bridge dependencies..."
    Push-Location $WaBridgeDir
    try {
        npm install --production --silent 2>$null
        Write-Ok "WhatsApp bridge dependencies installed"
    } catch {
        Write-Warn "WhatsApp bridge npm install failed (can retry later)"
    }
    Pop-Location
}

# -- 6. Create directories ------------------------------------------------
foreach ($dir in @("data", "data\chroma", "data\generated", "data\whatsapp_session",
                   "logs", "config", "plugins", "templates")) {
    $path = Join-Path $ScriptDir $dir
    if (-not (Test-Path $path)) { New-Item -ItemType Directory -Path $path -Force | Out-Null }
}
Write-Ok "Directories created"

# -- 7. Create .env -------------------------------------------------------
$envFile = Join-Path $ScriptDir ".env"
$envExample = Join-Path $ScriptDir ".env.example"
if (-not (Test-Path $envFile)) {
    Copy-Item $envExample $envFile
    Write-Info "Created .env from .env.example - please edit with your API keys"
} else {
    Write-Ok ".env file exists"
}

# -- 8. Generate keys -----------------------------------------------------
$envContent = Get-Content $envFile -Raw

if ($envContent -notmatch "KODA2_ENCRYPTION_KEY=.") {
    $encKey = python -c "import base64,os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"
    $envContent = $envContent -replace "KODA2_ENCRYPTION_KEY=.*", "KODA2_ENCRYPTION_KEY=$encKey"
    Set-Content $envFile $envContent
    Write-Ok "Encryption key generated"
}

if ($envContent -match "KODA2_SECRET_KEY=change-me") {
    $secret = python -c "import secrets; print(secrets.token_urlsafe(32))"
    $envContent = $envContent -replace "KODA2_SECRET_KEY=change-me[^\r\n]*", "KODA2_SECRET_KEY=$secret"
    Set-Content $envFile $envContent
    Write-Ok "Secret key generated"
}

# -- 9. Initialize database -----------------------------------------------
Write-Info "Initializing database..."
try {
    python -c "import asyncio; from koda2.database import init_db; asyncio.run(init_db())" 2>$null
    Write-Ok "Database initialized"
} catch {
    Write-Warn "Database init skipped"
}

# -- 10. Smoke test -------------------------------------------------------
Write-Info "Running smoke test..."
try {
    python -c "from koda2.config import get_settings; s = get_settings(); print(f'  Environment: {s.koda2_env}')"
    Write-Ok "Config loads successfully"
} catch {
    Write-Warn "Smoke test failed"
}

# -- 11. Offer Windows service / Task Scheduler ----------------------------
Write-Host ""
Write-Host "-- Service Installation (optional) --" -ForegroundColor Cyan
Write-Host ""

$installSvc = Read-Host "  Create a Windows Task Scheduler entry to start Koda2 at login? [y/N]"
if ($installSvc -match "^[yY]") {
    $koda2Exe = Join-Path $ScriptDir ".venv\Scripts\koda2.exe"
    if (Test-Path $koda2Exe) {
        $action = New-ScheduledTaskAction -Execute $koda2Exe -WorkingDirectory $ScriptDir
        $trigger = New-ScheduledTaskTrigger -AtLogOn
        $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
        Register-ScheduledTask -TaskName "Koda2" -Action $action -Trigger $trigger -Settings $settings -Description "Koda2 AI Executive Assistant" -Force
        Write-Ok "Task Scheduler entry created (starts at login)"
        Write-Host "  Manage in: Task Scheduler > Koda2"
        Write-Host "  Or run:    schtasks /query /tn Koda2"
    } else {
        Write-Warn "koda2.exe not found. Start manually: .venv\Scripts\koda2.exe"
    }
}

# -- Done ------------------------------------------------------------------
Write-Host ""
Write-Host "=======================================================" -ForegroundColor Green
Write-Host "       Koda2 installed successfully!                    " -ForegroundColor Green
Write-Host "=======================================================" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. Run the interactive setup:  python setup_wizard.py"
Write-Host "  2. Start the server:           .venv\Scripts\activate && koda2"
Write-Host "  3. WhatsApp: scan QR at        http://localhost:8000/api/whatsapp/qr"
Write-Host ""
Write-Host "API docs: http://localhost:8000/docs"
Write-Host ""
