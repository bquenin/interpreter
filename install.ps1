# install.ps1 - One-liner installer for interpreter-v2
# Usage: powershell -c "irm https://raw.githubusercontent.com/bquenin/interpreter/main/install.ps1 | iex"

$ErrorActionPreference = 'Stop'

Write-Host ""
Write-Host "=== interpreter-v2 Installer ===" -ForegroundColor Cyan
Write-Host "Offline screen translator for Japanese retro games"
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
# Temporarily allow errors so uv's progress output (on stderr) doesn't stop the script
$ErrorActionPreference = 'Continue'
uv tool install --upgrade --python 3.12 interpreter-v2
$installExitCode = $LASTEXITCODE
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
$toolDir = "$env:LOCALAPPDATA\uv\tools\interpreter-v2"
if (Test-Path $toolDir) {
    & "$toolDir\Scripts\python.exe" -m compileall -q "$toolDir\Lib" 2>$null
    # Warm up caches (Windows Defender, etc.) by running once
    & interpreter-v2 --list-windows 2>$null | Out-Null
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
