#Requires -Version 5.1
<#
.SYNOPSIS
    Koda2 — Single-line installer for Windows
.DESCRIPTION
    Usage:
        irm https://raw.githubusercontent.com/ronaldjonkers/Koda2/main/get-koda2.ps1 | iex

    Installs Python 3.12+, Node.js 18+, Git (via winget), clones Koda2,
    and runs the full installer.
#>

$ErrorActionPreference = "Stop"

function Write-Info  { Write-Host "[INFO]  $args" -ForegroundColor Cyan }
function Write-Ok    { Write-Host "[OK]    $args" -ForegroundColor Green }
function Write-Warn  { Write-Host "[WARN]  $args" -ForegroundColor Yellow }
function Write-Fail  { Write-Host "[FAIL]  $args" -ForegroundColor Red; exit 1 }

$InstallDir = if ($env:KODA2_INSTALL_DIR) { $env:KODA2_INSTALL_DIR } else { "$HOME\Koda2" }
$RepoUrl = "https://github.com/ronaldjonkers/Koda2.git"

Write-Host ""
Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host "       Koda2 - One-Line Installer (Windows)            " -ForegroundColor Cyan
Write-Host "       Professional AI Executive Assistant              " -ForegroundColor Cyan
Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host ""

# -- Check winget ----------------------------------------------------------
$HasWinget = $false
try { winget --version 2>$null | Out-Null; $HasWinget = $true } catch { }

# -- Install Git -----------------------------------------------------------
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Info "Installing Git..."
    if ($HasWinget) {
        winget install Git.Git --accept-package-agreements --accept-source-agreements --silent
        $env:PATH = "$env:PATH;C:\Program Files\Git\cmd"
    } else {
        Write-Fail "Git not found and winget not available. Install Git from https://git-scm.com and re-run."
    }
    Write-Ok "Git installed"
} else {
    Write-Ok "Git found"
}

# -- Install Python 3.12+ -------------------------------------------------
$PythonOk = $false
foreach ($candidate in @("python3.12", "python3.13", "python3", "python", "py")) {
    try {
        $ver = & $candidate -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
        if ($ver) {
            $parts = $ver.Split(".")
            if ([int]$parts[0] -ge 3 -and [int]$parts[1] -ge 12) {
                $PythonOk = $true
                break
            }
        }
    } catch { }
}

if (-not $PythonOk) {
    Write-Info "Installing Python 3.12..."
    if ($HasWinget) {
        winget install Python.Python.3.12 --accept-package-agreements --accept-source-agreements --silent
        # Refresh PATH
        $env:PATH = "$env:PATH;$env:LOCALAPPDATA\Programs\Python\Python312;$env:LOCALAPPDATA\Programs\Python\Python312\Scripts"
    } else {
        Write-Fail "Python 3.12+ not found and winget not available. Install from https://python.org and re-run."
    }
    Write-Ok "Python installed"
} else {
    Write-Ok "Python 3.12+ found"
}

# -- Install Node.js 18+ --------------------------------------------------
$NodeOk = $false
try {
    $nodeVer = (node -v 2>$null) -replace 'v', ''
    if ($nodeVer -and [int]($nodeVer.Split(".")[0]) -ge 18) { $NodeOk = $true }
} catch { }

if (-not $NodeOk) {
    Write-Info "Installing Node.js LTS..."
    if ($HasWinget) {
        winget install OpenJS.NodeJS.LTS --accept-package-agreements --accept-source-agreements --silent
        $env:PATH = "$env:PATH;C:\Program Files\nodejs"
    } else {
        Write-Warn "Node.js not found. Install from https://nodejs.org for WhatsApp support."
    }
} else {
    Write-Ok "Node.js 18+ found"
}

# -- Clone or update -------------------------------------------------------
if (Test-Path "$InstallDir\.git") {
    Write-Info "Updating existing Koda2 installation..."
    Push-Location $InstallDir
    git pull origin main --quiet
    Pop-Location
    Write-Ok "Repository updated"
} else {
    Write-Info "Cloning Koda2 to $InstallDir..."
    git clone --depth 1 $RepoUrl $InstallDir
    Write-Ok "Repository cloned"
}

# -- Run installer ---------------------------------------------------------
Write-Info "Running Koda2 installer..."
Push-Location $InstallDir
& powershell -ExecutionPolicy Bypass -File install.ps1
Pop-Location

# -- Done ------------------------------------------------------------------
Write-Host ""
Write-Host "=======================================================" -ForegroundColor Green
Write-Host "       Koda2 installed successfully!                    " -ForegroundColor Green
Write-Host "=======================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Start Koda2:"
Write-Host "    cd $InstallDir"
Write-Host "    .venv\Scripts\activate"
Write-Host "    koda2"
Write-Host ""
Write-Host "  Configure:"
Write-Host "    cd $InstallDir"
Write-Host "    .venv\Scripts\activate"
Write-Host "    python setup_wizard.py"
Write-Host ""

$runWizard = Read-Host "  Run the interactive setup wizard now? [Y/n]"
if ($runWizard -notmatch "^[nN]") {
    Push-Location $InstallDir
    & .venv\Scripts\activate
    python setup_wizard.py
    Pop-Location
}
