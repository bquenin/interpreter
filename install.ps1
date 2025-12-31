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

# Install interpreter-v2
Write-Host "[2/2] Installing interpreter-v2 from PyPI..." -ForegroundColor Yellow
uv tool install interpreter-v2

# Update shell to add tools to PATH
uv tool update-shell 2>$null

Write-Host ""
Write-Host "Installation complete!" -ForegroundColor Green
Write-Host ""
Write-Host "To start, run:" -ForegroundColor Cyan
Write-Host "  interpreter-v2"
Write-Host ""
Write-Host "Note: You may need to restart your terminal for the command to be available."
Write-Host ""
