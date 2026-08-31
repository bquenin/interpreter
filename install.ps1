# install.ps1 - One-liner installer for interpreter-v2
# Usage: powershell -c "irm https://raw.githubusercontent.com/bquenin/interpreter/main/install.ps1 | iex"

$ErrorActionPreference = 'Stop'

# Force TLS 1.2+ for Windows PowerShell 5.1, which defaults to TLS 1.0/1.1
# and fails against modern hosts like astral.sh.
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

Write-Host ""
Write-Host "=== interpreter-v2 Installer ===" -ForegroundColor Cyan
Write-Host "Offline screen translator for Japanese retro games"
Write-Host "Plan for at least 6 GB of free disk space, including first-run model downloads." -ForegroundColor Gray
Write-Host ""

# Check if uv is installed
$uvPath = Get-Command uv -ErrorAction SilentlyContinue
if (-not $uvPath) {
    Write-Host "[1/2] Installing uv package manager..." -ForegroundColor Yellow
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression

    # Refresh PATH to find uv
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")

    # Verify uv is now available
    $uvPath = Get-Command uv -ErrorAction SilentlyContinue
    if (-not $uvPath) {
        Write-Host "Error: uv installation failed. Please restart your terminal and try again." -ForegroundColor Red
        exit 1
    }
    Write-Host "uv installed successfully!" -ForegroundColor Green
} else {
    Write-Host "[1/2] uv is already installed" -ForegroundColor Green
}

# Install or upgrade interpreter-v2
Write-Host "[2/3] Installing interpreter-v2 from PyPI..." -ForegroundColor Yellow
Write-Host "     (this may take a minute on first install)" -ForegroundColor Gray
# Use Python 3.12 explicitly - onnxruntime doesn't have wheels for 3.14 yet
# Keep the large package downloads in an interpreter-owned cache. This lets the
# installer clean them after success or failure instead of leaving gigabytes in
# uv's shared cache after an interrupted install.
$installCacheDir = Join-Path $env:LOCALAPPDATA "interpreter-v2\uv-cache"
# Temporarily allow errors so uv's progress output (on stderr) doesn't stop the script
$ErrorActionPreference = 'Continue'
try {
    uv tool install --force --upgrade --python 3.12 --cache-dir $installCacheDir interpreter-v2
    $installExitCode = $LASTEXITCODE
} finally {
    # uv can clean its cache safely even when package installation failed. Fall
    # back to direct removal because this directory belongs only to interpreter.
    uv cache clean --cache-dir $installCacheDir 2>$null | Out-Null
    if (Test-Path -LiteralPath $installCacheDir) {
        Remove-Item -LiteralPath $installCacheDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}
$ErrorActionPreference = 'Stop'
if ($installExitCode -ne 0) {
    Write-Host ""
    Write-Host "Installation failed!" -ForegroundColor Red
    Write-Host "This may be due to missing dependencies. Try:" -ForegroundColor Yellow
    Write-Host "  uv python install 3.12"
    Write-Host "  Then run this installer again."
    exit 1
}
$ErrorActionPreference = 'SilentlyContinue'
uv tool update-shell | Out-Null
$ErrorActionPreference = 'Stop'

# Pre-compile bytecode and warm up OS caches
Write-Host "[3/3] Optimizing for fast startup..." -ForegroundColor Yellow
$toolDir = "$env:APPDATA\uv\tools\interpreter-v2"
if (Test-Path $toolDir) {
    & "$toolDir\Scripts\python.exe" -m compileall -q "$toolDir\Lib" 2>$null
    # Warm up caches (Windows Defender, etc.) by triggering the full
    # module-level import chain via --help (no GUI, exits cleanly).
    & interpreter-v2 --help 2>$null | Out-Null
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  Installation complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "To start, run:" -ForegroundColor White
Write-Host ""
Write-Host "  interpreter-v2" -ForegroundColor Cyan
Write-Host ""
Write-Host "You may need to restart your terminal first."
Write-Host ""
