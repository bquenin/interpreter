# uninstall.ps1 - Uninstaller for interpreter-v2
# Usage: powershell -c "irm https://raw.githubusercontent.com/bquenin/interpreter/main/uninstall.ps1 | iex"

$ErrorActionPreference = 'Stop'

Write-Host ""
Write-Host "=== interpreter-v2 Uninstaller ===" -ForegroundColor Cyan
Write-Host ""

# Check if uv is installed
$uvPath = Get-Command uv -ErrorAction SilentlyContinue
if (-not $uvPath) {
    Write-Host "uv is not installed. Nothing to uninstall." -ForegroundColor Yellow
    exit 0
}

# Check if interpreter-v2 is installed
$toolList = uv tool list 2>$null
if ($toolList -notmatch "interpreter-v2") {
    Write-Host "interpreter-v2 is not installed." -ForegroundColor Yellow
} else {
    Write-Host "[1/2] Uninstalling interpreter-v2..." -ForegroundColor Yellow
    uv tool uninstall interpreter-v2
    Write-Host "interpreter-v2 uninstalled" -ForegroundColor Green
}

# Remove user data
Write-Host "[2/2] Removing user data..." -ForegroundColor Yellow

$configDir = "$env:USERPROFILE\.interpreter"
$modelsDir = "$env:USERPROFILE\.cache\huggingface\hub"

# Remove config
if (Test-Path $configDir) {
    Remove-Item -Recurse -Force $configDir
    Write-Host "     Removed config directory" -ForegroundColor Green
} else {
    Write-Host "     Config directory not found" -ForegroundColor Gray
}

# Remove cached models
if (Test-Path $modelsDir) {
    $interpreterModels = Get-ChildItem -Path $modelsDir -Directory -Filter "models--bquenin--*" -ErrorAction SilentlyContinue
    if ($interpreterModels) {
        foreach ($model in $interpreterModels) {
            Remove-Item -Recurse -Force $model.FullName
            Write-Host "     Removed $($model.Name)" -ForegroundColor Green
        }
    } else {
        Write-Host "     Cached models not found" -ForegroundColor Gray
    }
} else {
    Write-Host "     Cached models not found" -ForegroundColor Gray
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  Uninstall complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
