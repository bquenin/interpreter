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
Write-Host "[2/2] Installing interpreter-v2 from PyPI..." -ForegroundColor Yellow
$output = uv tool install --upgrade interpreter-v2 2>&1
# Show output only if it's not just "already installed" noise
$filtered = $output | Where-Object { $_ -notmatch "is already installed|already in PATH" }
if ($filtered) { $filtered | Write-Host }

# Update shell to add tools to PATH (suppress all output)
& { uv tool update-shell } *>$null

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
