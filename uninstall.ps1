# uninstall.ps1 - Uninstaller for interpreter-v2
# Usage: powershell -c "irm https://raw.githubusercontent.com/bquenin/interpreter/main/uninstall.ps1 | iex"

$ErrorActionPreference = 'Stop'

Write-Host ""
Write-Host "=== interpreter-v2 Uninstaller ===" -ForegroundColor Cyan
Write-Host ""

function Remove-InterpreterPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [string]$Description
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }

    try {
        Remove-Item -LiteralPath $Path -Recurse -Force
        Write-Host "     Removed $Description" -ForegroundColor Green
    } catch {
        Write-Host "     Could not remove $Description`: $($_.Exception.Message)" -ForegroundColor Red
    }
}

# uv's installer adds itself to ~/.local/bin. Look there as a fallback because
# the current shell may not have picked up the PATH change yet.
$uvCommand = Get-Command uv -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
$uvExecutable = if ($uvCommand) { $uvCommand.Source } else { $null }
$defaultUvExecutable = Join-Path $env:USERPROFILE ".local\bin\uv.exe"
if (-not $uvExecutable -and (Test-Path -LiteralPath $defaultUvExecutable -PathType Leaf)) {
    $uvExecutable = $defaultUvExecutable
}

# Resolve uv's configured directories when possible, while retaining defaults
# for interrupted uv installs or environments that are no longer registered.
$toolRoot = if ($env:UV_TOOL_DIR) { $env:UV_TOOL_DIR } else { Join-Path $env:APPDATA "uv\tools" }
$toolBin = if ($env:UV_TOOL_BIN_DIR) { $env:UV_TOOL_BIN_DIR } else { Join-Path $env:USERPROFILE ".local\bin" }
if ($uvExecutable) {
    $reportedToolRoot = & $uvExecutable tool dir 2>$null
    if ($LASTEXITCODE -eq 0 -and $reportedToolRoot) {
        $toolRoot = ($reportedToolRoot | Select-Object -Last 1).Trim()
    }

    $reportedToolBin = & $uvExecutable tool dir --bin 2>$null
    if ($LASTEXITCODE -eq 0 -and $reportedToolBin) {
        $toolBin = ($reportedToolBin | Select-Object -Last 1).Trim()
    }
}

$toolEnvironment = Join-Path $toolRoot "interpreter-v2"
$toolExecutable = Join-Path $toolBin "interpreter-v2.exe"

Write-Host "[1/4] Uninstalling interpreter-v2..." -ForegroundColor Yellow
if ($uvExecutable) {
    $toolList = & $uvExecutable tool list 2>$null
    if ($toolList -match "interpreter-v2" -or (Test-Path -LiteralPath $toolEnvironment)) {
        $ErrorActionPreference = 'Continue'
        & $uvExecutable tool uninstall interpreter-v2
        $uninstallExitCode = $LASTEXITCODE
        $ErrorActionPreference = 'Stop'

        if ($uninstallExitCode -eq 0) {
            Write-Host "     interpreter-v2 uninstalled" -ForegroundColor Green
        } else {
            Write-Host "     uv could not uninstall the tool; cleaning up its files directly" -ForegroundColor Yellow
        }
    } else {
        Write-Host "     interpreter-v2 is not registered with uv" -ForegroundColor Gray
    }
} else {
    Write-Host "     uv was not found; cleaning up its files directly" -ForegroundColor Yellow
}

# Remove orphan files left by an interrupted install or a stale uv registry.
Write-Host "[2/4] Cleaning up orphan files..." -ForegroundColor Yellow
if (Test-Path -LiteralPath $toolExecutable) {
    Remove-InterpreterPath -Path $toolExecutable -Description "orphan executable"
} else {
    Write-Host "     No orphan executable found" -ForegroundColor Gray
}
if (Test-Path -LiteralPath $toolEnvironment) {
    Remove-InterpreterPath -Path $toolEnvironment -Description "stale tool environment"
} else {
    Write-Host "     No stale tool environment found" -ForegroundColor Gray
}

# New installers use this dedicated cache so it can always be removed without
# disturbing other uv users. Older installers used uv's shared cache; prune only
# entries uv knows are unreachable and leave reusable downloads alone.
Write-Host "[3/4] Removing package downloads..." -ForegroundColor Yellow
$installCacheDir = Join-Path $env:LOCALAPPDATA "interpreter-v2\uv-cache"
if (Test-Path -LiteralPath $installCacheDir) {
    Remove-InterpreterPath -Path $installCacheDir -Description "interpreter package cache"
}

if ($uvExecutable) {
    $ErrorActionPreference = 'Continue'
    & $uvExecutable cache prune
    $pruneExitCode = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'

    if ($pruneExitCode -eq 0) {
        Write-Host "     Unreachable uv cache entries removed" -ForegroundColor Green
    } else {
        Write-Host "     Some uv cache entries could not be removed; close other uv processes and retry" -ForegroundColor Red
    }

    $sharedCacheDir = & $uvExecutable cache dir 2>$null
    if ($LASTEXITCODE -eq 0 -and $sharedCacheDir) {
        $sharedCacheDir = ($sharedCacheDir | Select-Object -Last 1).Trim()
        Write-Host "     Older installers may have left reusable downloads in uv's shared cache:" -ForegroundColor Gray
        Write-Host "     $sharedCacheDir" -ForegroundColor Gray
        Write-Host "     Run 'uv cache clean' to clear it, including downloads cached by other uv projects." -ForegroundColor Gray
    }
} else {
    $defaultCacheDir = if ($env:UV_CACHE_DIR) { $env:UV_CACHE_DIR } else { Join-Path $env:LOCALAPPDATA "uv\cache" }
    Write-Host "     uv was not found, so its cache could not be pruned" -ForegroundColor Yellow
    Write-Host "     To clear every uv download later, reinstall uv and run 'uv cache clean': $defaultCacheDir" -ForegroundColor Gray
}

# Remove user data
Write-Host "[4/4] Removing user data..." -ForegroundColor Yellow

$configDir = Join-Path $env:USERPROFILE ".interpreter"
if ($env:HF_HUB_CACHE) {
    $modelsDir = $env:HF_HUB_CACHE
} elseif ($env:HF_HOME) {
    $modelsDir = Join-Path $env:HF_HOME "hub"
} elseif ($env:XDG_CACHE_HOME) {
    $modelsDir = Join-Path $env:XDG_CACHE_HOME "huggingface\hub"
} else {
    $modelsDir = Join-Path $env:USERPROFILE ".cache\huggingface\hub"
}

# Remove config
if (Test-Path -LiteralPath $configDir) {
    Remove-InterpreterPath -Path $configDir -Description "config directory"
} else {
    Write-Host "     Config directory not found" -ForegroundColor Gray
}

# Remove the repositories actually downloaded by interpreter-v2. Retain the
# legacy bquenin pattern for caches created by older releases.
$modelCacheNames = @(
    "models--rtr46--meiki.text.detect.v0",
    "models--rtr46--meiki.txt.recognition.v0",
    "models--entai2965--sugoi-v4-ja-en-ctranslate2"
)
$removedModel = $false
if (Test-Path -LiteralPath $modelsDir -PathType Container) {
    foreach ($modelCacheName in $modelCacheNames) {
        $modelPath = Join-Path $modelsDir $modelCacheName
        if (Test-Path -LiteralPath $modelPath) {
            Remove-InterpreterPath -Path $modelPath -Description $modelCacheName
            $removedModel = $true
        }

        $modelLockPath = Join-Path (Join-Path $modelsDir ".locks") $modelCacheName
        if (Test-Path -LiteralPath $modelLockPath) {
            Remove-InterpreterPath -Path $modelLockPath -Description "$modelCacheName lock files"
        }
    }

    $legacyModels = Get-ChildItem -LiteralPath $modelsDir -Directory -Filter "models--bquenin--*" -ErrorAction SilentlyContinue
    foreach ($legacyModel in $legacyModels) {
        Remove-InterpreterPath -Path $legacyModel.FullName -Description $legacyModel.Name
        $removedModel = $true
    }

    $legacyLocksDir = Join-Path $modelsDir ".locks"
    if (Test-Path -LiteralPath $legacyLocksDir -PathType Container) {
        $legacyModelLocks = Get-ChildItem -LiteralPath $legacyLocksDir -Directory -Filter "models--bquenin--*" -ErrorAction SilentlyContinue
        foreach ($legacyModelLock in $legacyModelLocks) {
            Remove-InterpreterPath -Path $legacyModelLock.FullName -Description "$($legacyModelLock.Name) lock files"
        }
    }
}
if (-not $removedModel) {
    Write-Host "     Cached models not found" -ForegroundColor Gray
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  Uninstall complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
