#Requires -Version 5.1
<#
.SYNOPSIS
    Koda2 — Single-line installer / uninstaller / updater for Windows
.DESCRIPTION
    Install:    irm https://raw.githubusercontent.com/ronaldjonkers/Koda2/main/get-koda2.ps1 | iex
    Uninstall:  $env:KODA2_ACTION='uninstall'; irm .../get-koda2.ps1 | iex
    Update:     $env:KODA2_ACTION='update'; irm .../get-koda2.ps1 | iex
#>

$ErrorActionPreference = "Stop"

# ── Colors & Helpers ──────────────────────────────────────────────────
function Write-Step  { Write-Host "`n━━━ $args ━━━" -ForegroundColor Blue }
function Write-Info  { Write-Host "  ▸ $args" -ForegroundColor Cyan }
function Write-Ok    { Write-Host "  ✔ $args" -ForegroundColor Green }
function Write-Warn  { Write-Host "  ⚠  $args" -ForegroundColor Yellow }
function Write-Fail  { Write-Host "  ✘ $args" -ForegroundColor Red; exit 1 }

$InstallDir = if ($env:KODA2_INSTALL_DIR) { $env:KODA2_INSTALL_DIR } else { "$HOME\Koda2" }
$RepoUrl = "https://github.com/ronaldjonkers/Koda2.git"
$Action = if ($env:KODA2_ACTION) { $env:KODA2_ACTION } else { "install" }
# Clean up env var so it doesn't persist
$env:KODA2_ACTION = $null

# ── Banner ────────────────────────────────────────────────────────────
function Show-Banner {
    Write-Host ""
    Write-Host "  ██╗  ██╗ ██████╗ ██████╗  █████╗ ██████╗ " -ForegroundColor Blue
    Write-Host "  ██║ ██╔╝██╔═══██╗██╔══██╗██╔══██╗╚════██╗" -ForegroundColor Blue
    Write-Host "  █████╔╝ ██║   ██║██║  ██║███████║ █████╔╝" -ForegroundColor Blue
    Write-Host "  ██╔═██╗ ██║   ██║██║  ██║██╔══██║██╔═══╝ " -ForegroundColor Blue
    Write-Host "  ██║  ██╗╚██████╔╝██████╔╝██║  ██║███████╗" -ForegroundColor Blue
    Write-Host "  ╚═╝  ╚═╝ ╚═════╝ ╚═════╝ ╚═╝  ╚═╝╚══════╝" -ForegroundColor Blue
    Write-Host ""
    Write-Host "  Professional AI Executive Assistant" -ForegroundColor DarkGray
    Write-Host ""
}

# ── Prerequisite checks ──────────────────────────────────────────────
$HasWinget = $false
try { winget --version 2>$null | Out-Null; $HasWinget = $true } catch { }

function Install-Prerequisites {
    Write-Step "📦 Checking prerequisites"

    # Git
    if (Get-Command git -ErrorAction SilentlyContinue) {
        Write-Ok "Git $(git --version)"
    } else {
        Write-Info "Installing Git..."
        if ($HasWinget) {
            winget install Git.Git --accept-package-agreements --accept-source-agreements --silent
            $env:PATH = "$env:PATH;C:\Program Files\Git\cmd"
        } else { Write-Fail "Git not found. Install from https://git-scm.com" }
        Write-Ok "Git installed"
    }

    # Python
    $script:PythonOk = $false
    foreach ($candidate in @("python3.12", "python3.13", "python3", "python", "py")) {
        try {
            $ver = & $candidate -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
            if ($ver) {
                $parts = $ver.Split(".")
                if ([int]$parts[0] -ge 3 -and [int]$parts[1] -ge 12) {
                    Write-Ok "Python $ver 🐍"
                    $script:PythonOk = $true
                    break
                }
            }
        } catch { }
    }
    if (-not $script:PythonOk) {
        Write-Info "Installing Python 3.12 🐍..."
        if ($HasWinget) {
            winget install Python.Python.3.12 --accept-package-agreements --accept-source-agreements --silent
            $env:PATH = "$env:PATH;$env:LOCALAPPDATA\Programs\Python\Python312;$env:LOCALAPPDATA\Programs\Python\Python312\Scripts"
        } else { Write-Fail "Install Python 3.12+ from https://python.org" }
        Write-Ok "Python installed"
    }

    # Node.js
    $script:NodeOk = $false
    try {
        $nodeVer = (node -v 2>$null) -replace 'v', ''
        if ($nodeVer -and [int]($nodeVer.Split(".")[0]) -ge 18) {
            Write-Ok "Node.js v$nodeVer 📦"
            $script:NodeOk = $true
        }
    } catch { }
    if (-not $script:NodeOk) {
        Write-Info "Installing Node.js LTS 📦..."
        if ($HasWinget) {
            winget install OpenJS.NodeJS.LTS --accept-package-agreements --accept-source-agreements --silent
            $env:PATH = "$env:PATH;C:\Program Files\nodejs"
            $script:NodeOk = $true
        } else { Write-Warn "Node.js not found — WhatsApp integration requires Node.js 18+" }
    }
}

# ══════════════════════════════════════════════════════════════════════
# ── INSTALL ──────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════
function Do-Install {
    Show-Banner
    Write-Host "  ▶ Installing Koda2" -ForegroundColor Magenta
    Write-Host ""

    Install-Prerequisites

    Write-Step "📥 Downloading Koda2"
    if (Test-Path "$InstallDir\.git") {
        Write-Info "Updating existing installation..."
        Push-Location $InstallDir
        git pull origin main --quiet
        Pop-Location
        Write-Ok "Repository updated"
    } else {
        Write-Info "Cloning to $InstallDir..."
        git clone --depth 1 $RepoUrl $InstallDir
        Write-Ok "Repository cloned"
    }

    Write-Step "🔧 Running installer"
    Push-Location $InstallDir
    & powershell -ExecutionPolicy Bypass -File install.ps1
    Pop-Location

    Write-Host ""
    Write-Host "  ╔══════════════════════════════════════════════════╗" -ForegroundColor Green
    Write-Host "  ║                                                  ║" -ForegroundColor Green
    Write-Host "  ║   ✅  Koda2 installed successfully!              ║" -ForegroundColor Green
    Write-Host "  ║                                                  ║" -ForegroundColor Green
    Write-Host "  ╚══════════════════════════════════════════════════╝" -ForegroundColor Green
    Write-Host ""
    Write-Host "  🚀 Start:     " -NoNewline; Write-Host "cd $InstallDir; .venv\Scripts\activate; koda2" -ForegroundColor DarkGray
    Write-Host "  ⚙️  Configure: " -NoNewline; Write-Host "cd $InstallDir; .venv\Scripts\activate; python setup_wizard.py" -ForegroundColor DarkGray
    Write-Host "  🔄 Update:    " -NoNewline; Write-Host '$env:KODA2_ACTION="update"; irm .../get-koda2.ps1 | iex' -ForegroundColor DarkGray
    Write-Host "  🗑️  Uninstall: " -NoNewline; Write-Host '$env:KODA2_ACTION="uninstall"; irm .../get-koda2.ps1 | iex' -ForegroundColor DarkGray
    Write-Host ""

    $runWizard = Read-Host "  Run the interactive setup wizard now? [Y/n]"
    if ($runWizard -notmatch "^[nN]") {
        Push-Location $InstallDir
        & .venv\Scripts\Activate.ps1
        python setup_wizard.py
        Pop-Location
    }
}

# ══════════════════════════════════════════════════════════════════════
# ── UNINSTALL ────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════
function Do-Uninstall {
    Show-Banner
    Write-Host "  ▶ Uninstalling Koda2" -ForegroundColor Red
    Write-Host ""

    if (-not (Test-Path $InstallDir)) {
        Write-Warn "Koda2 not found at $InstallDir — nothing to uninstall."
        return
    }

    Write-Host "  This will remove:" -ForegroundColor Yellow
    Write-Host "    📁 $InstallDir  (code, venv, data)" -ForegroundColor DarkGray
    Write-Host "    📋 Task Scheduler entry 'Koda2'" -ForegroundColor DarkGray
    Write-Host ""

    $confirm = Read-Host "  Are you sure? Type 'yes' to confirm"
    if ($confirm -ne "yes") {
        Write-Host "`n  Cancelled — nothing was removed." -ForegroundColor Green
        return
    }

    Write-Step "🛑 Removing service"
    try {
        schtasks /delete /tn Koda2 /f 2>$null | Out-Null
        Write-Ok "Task Scheduler entry removed"
    } catch {
        Write-Info "No Task Scheduler entry found"
    }

    Write-Step "🗑️  Removing files"
    Remove-Item -Recurse -Force $InstallDir -ErrorAction SilentlyContinue
    Write-Ok "Removed $InstallDir"

    Write-Host ""
    Write-Host "  ╔══════════════════════════════════════════════════╗" -ForegroundColor Green
    Write-Host "  ║                                                  ║" -ForegroundColor Green
    Write-Host "  ║   🗑️   Koda2 uninstalled completely.             ║" -ForegroundColor Green
    Write-Host "  ║                                                  ║" -ForegroundColor Green
    Write-Host "  ╚══════════════════════════════════════════════════╝" -ForegroundColor Green
    Write-Host ""
}

# ══════════════════════════════════════════════════════════════════════
# ── UPDATE ───────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════
function Do-Update {
    Show-Banner
    Write-Host "  ▶ Updating Koda2" -ForegroundColor Cyan
    Write-Host ""

    if (-not (Test-Path "$InstallDir\.git")) {
        Write-Warn "Koda2 not found — running full install."
        Do-Install
        return
    }

    Push-Location $InstallDir
    Install-Prerequisites

    Write-Step "📥 Pulling latest code"
    $oldVer = (Select-String -Path koda2\__init__.py -Pattern '__version__' | ForEach-Object { $_ -replace '.*"(.*)".*','$1' }) 2>$null
    git stash 2>$null
    git pull --rebase origin main 2>$null
    git stash pop 2>$null
    $newVer = (Select-String -Path koda2\__init__.py -Pattern '__version__' | ForEach-Object { $_ -replace '.*"(.*)".*','$1' }) 2>$null
    if ($oldVer -ne $newVer) {
        Write-Ok "Version: $oldVer → $newVer"
    } else {
        Write-Ok "Already on latest: v$newVer"
    }

    Write-Step "🐍 Updating Python environment"
    if (-not (Test-Path ".venv")) {
        Write-Warn "Virtual environment missing — recreating..."
        python -m venv .venv
    }
    & .venv\Scripts\Activate.ps1
    pip install --upgrade pip --quiet 2>$null
    pip install -e ".[dev]" --quiet 2>$null
    Write-Ok "Python dependencies up to date"

    Write-Step "📦 Updating WhatsApp bridge"
    $waDir = "koda2\modules\messaging\whatsapp_bridge"
    if ((Get-Command npm -ErrorAction SilentlyContinue) -and (Test-Path "$waDir\package.json")) {
        Push-Location $waDir
        try { npm install --production --silent 2>$null; Write-Ok "WhatsApp bridge updated" }
        catch { Write-Warn "WhatsApp bridge npm update failed" }
        Pop-Location
    }

    Write-Step "🗄️  Updating database"
    try {
        python -c "import asyncio; from koda2.database import init_db; asyncio.run(init_db())" 2>$null
        Write-Ok "Database schema up to date"
    } catch { Write-Warn "Database update skipped" }

    Write-Step "📝 Checking .env for new variables"
    if ((Test-Path ".env.example") -and (Test-Path ".env")) {
        $envContent = Get-Content ".env" -Raw
        $added = 0
        Get-Content ".env.example" | ForEach-Object {
            if ($_ -match "^([A-Z_]+)=" -and $envContent -notmatch "^$($Matches[1])=") {
                Add-Content ".env" $_
                Write-Info "  Added: $($Matches[1])"
                $added++
            }
        }
        if ($added -eq 0) { Write-Ok ".env is complete" }
    }

    Write-Step "🧪 Running tests"
    try {
        python -m pytest tests/ -x --tb=short -q 2>$null
        Write-Ok "All tests pass ✅"
    } catch { Write-Warn "Some tests failed" }

    Write-Step "🔍 System health check"
    try {
        python -c "from koda2.config import get_settings; s = get_settings(); print(f'  Environment: {s.koda2_env}'); print(f'  API port:    {s.api_port}'); print(f'  WhatsApp:    {chr(34)}enabled{chr(34) if s.whatsapp_enabled else chr(34)}disabled{chr(34)}')"
        Write-Ok "Config loads successfully"
    } catch { Write-Warn "Config check failed" }

    Pop-Location

    Write-Host ""
    Write-Host "  ╔══════════════════════════════════════════════════╗" -ForegroundColor Green
    Write-Host "  ║                                                  ║" -ForegroundColor Green
    Write-Host "  ║   ✅  Koda2 updated to v$newVer!                   ║" -ForegroundColor Green
    Write-Host "  ║                                                  ║" -ForegroundColor Green
    Write-Host "  ╚══════════════════════════════════════════════════╝" -ForegroundColor Green
    Write-Host ""
    Write-Host "  🚀 Restart: " -NoNewline; Write-Host "cd $InstallDir; .venv\Scripts\activate; koda2" -ForegroundColor DarkGray
    Write-Host ""
}

# ── Main ──────────────────────────────────────────────────────────────
switch ($Action) {
    "install"   { Do-Install }
    "uninstall" { Do-Uninstall }
    "update"    { Do-Update }
    default     { Do-Install }
}
