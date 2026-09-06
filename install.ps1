# install.ps1 - One-liner installer for interpreter-v2
# Usage: powershell -c "irm https://raw.githubusercontent.com/bquenin/interpreter/main/install.ps1 | iex"
#
# To install somewhere other than your user profile (for example on a second
# drive), set INTERPRETER_HOME first. The choice is remembered for upgrades:
#   $env:INTERPRETER_HOME = "D:\interpreter"; powershell -c "irm https://raw.githubusercontent.com/bquenin/interpreter/main/install.ps1 | iex"

$ErrorActionPreference = 'Stop'

# Force TLS 1.2+ for Windows PowerShell 5.1, which defaults to TLS 1.0/1.1
# and fails against modern hosts like astral.sh.
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

Write-Host ""
Write-Host "=== interpreter-v2 Installer ===" -ForegroundColor Cyan
Write-Host "Offline screen translator for Japanese retro games"
Write-Host "Plan for at least 6 GB of free disk space, including first-run model downloads." -ForegroundColor Gray
Write-Host ""

# Resolve the install location. INTERPRETER_HOME wins; otherwise reuse the
# location recorded by a previous run so plain re-runs upgrade in place. The
# layout under the root mirrors src/interpreter/paths.py; keep them in sync:
#   <root>\uv\tools    tool environment      <root>\uv-cache  install downloads
#   <root>\uv\python   uv-managed Python     <root>\models    HuggingFace cache
$configDir = Join-Path $env:USERPROFILE ".interpreter"
$installRootFile = Join-Path $configDir "install-dir"
$previousRoot = $null
if (Test-Path -LiteralPath $installRootFile -PathType Leaf) {
    $previousRoot = (Get-Content -LiteralPath $installRootFile -Raw).Trim()
    if ($previousRoot) {
        $previousRoot = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($previousRoot).TrimEnd('\')
    } else {
        $previousRoot = $null
    }
}

$installRoot = $null
if ($env:INTERPRETER_HOME -and $env:INTERPRETER_HOME.Trim()) {
    $installRoot = $env:INTERPRETER_HOME.Trim()
} elseif ($previousRoot) {
    $installRoot = $previousRoot
}

if ($installRoot) {
    # Normalize relative paths against the shell's current directory (not the
    # process directory, which PowerShell does not keep in sync).
    $installRoot = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($installRoot).TrimEnd('\')
    $driveRoot = [System.IO.Path]::GetPathRoot($installRoot + '\').TrimEnd('\')
    if ($installRoot -eq $driveRoot) {
        Write-Host "Error: INTERPRETER_HOME must be a folder, not a drive root. Try $installRoot\interpreter" -ForegroundColor Red
        exit 1
    }
    New-Item -ItemType Directory -Force -Path $installRoot | Out-Null
    $env:UV_TOOL_DIR = Join-Path $installRoot "uv\tools"
    $env:UV_PYTHON_INSTALL_DIR = Join-Path $installRoot "uv\python"
    $installCacheDir = Join-Path $installRoot "uv-cache"
    $modelsDir = Join-Path $installRoot "models"
    Write-Host "Install location: $installRoot" -ForegroundColor Gray
} else {
    # Keep the large package downloads in an interpreter-owned cache. This lets
    # the installer clean them after success or failure instead of leaving
    # gigabytes in uv's shared cache after an interrupted install.
    $installCacheDir = Join-Path $env:LOCALAPPDATA "interpreter-v2\uv-cache"
    $modelsDir = $null
    Write-Host "Install location: user profile (set INTERPRETER_HOME to choose another drive)" -ForegroundColor Gray
}
Write-Host ""

# Check if uv is installed
$uvPath = Get-Command uv -ErrorAction SilentlyContinue
if (-not $uvPath) {
    Write-Host "[1/3] Installing uv package manager..." -ForegroundColor Yellow
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
    Write-Host "[1/3] uv is already installed" -ForegroundColor Green
}

# When the install location changes, remove the tool environment from the old
# location first. Otherwise --force would leave a multi-gigabyte orphan behind.
if ($previousRoot -ne $installRoot) {
    if ($previousRoot) {
        $previousToolDir = Join-Path $previousRoot "uv\tools"
    } else {
        $previousToolDir = Join-Path $env:APPDATA "uv\tools"
    }
    $previousToolEnvironment = Join-Path $previousToolDir "interpreter-v2"
    if (Test-Path -LiteralPath $previousToolEnvironment) {
        Write-Host "     Removing the previous installation from $previousToolDir" -ForegroundColor Yellow
        $savedToolDir = $env:UV_TOOL_DIR
        $env:UV_TOOL_DIR = $previousToolDir
        $ErrorActionPreference = 'Continue'
        uv tool uninstall interpreter-v2 2>$null | Out-Null
        $ErrorActionPreference = 'Stop'
        if ($savedToolDir) { $env:UV_TOOL_DIR = $savedToolDir } else { Remove-Item Env:UV_TOOL_DIR -ErrorAction SilentlyContinue }
        if (Test-Path -LiteralPath $previousToolEnvironment) {
            Remove-Item -LiteralPath $previousToolEnvironment -Recurse -Force -ErrorAction SilentlyContinue
        }
        if ($previousRoot) {
            Write-Host "     Models downloaded by the previous installation remain in $previousRoot\models" -ForegroundColor Gray
            Write-Host "     Delete that folder once the new installation works." -ForegroundColor Gray
        } else {
            Write-Host "     Models downloaded by the previous installation remain in the HuggingFace cache" -ForegroundColor Gray
            Write-Host "     ($env:USERPROFILE\.cache\huggingface\hub). Delete the models--rtr46--* and" -ForegroundColor Gray
            Write-Host "     models--entai2965--* folders there once the new installation works." -ForegroundColor Gray
        }
    }
}

# Install or upgrade interpreter-v2
Write-Host "[2/3] Installing interpreter-v2 from PyPI..." -ForegroundColor Yellow
Write-Host "     (this may take a minute on first install)" -ForegroundColor Gray
# Use Python 3.12 explicitly - onnxruntime doesn't have wheels for 3.14 yet
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

# Record the install location so upgrades, the app, and the uninstaller find it.
if ($installRoot) {
    New-Item -ItemType Directory -Force -Path $configDir | Out-Null
    # Windows PowerShell 5.1 adds a byte order mark with -Encoding UTF8; the app
    # and the bash scripts read this file, so write plain UTF-8.
    [System.IO.File]::WriteAllText($installRootFile, $installRoot, (New-Object System.Text.UTF8Encoding $false))
}

# Pre-compile bytecode and warm up OS caches
Write-Host "[3/3] Optimizing for fast startup..." -ForegroundColor Yellow
$toolRoot = if ($env:UV_TOOL_DIR) { $env:UV_TOOL_DIR } else { Join-Path $env:APPDATA "uv\tools" }
$toolDir = Join-Path $toolRoot "interpreter-v2"
if (Test-Path -LiteralPath "$toolDir\Scripts\python.exe") {
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
if ($installRoot) {
    Write-Host "Installed to $installRoot (models will download to $modelsDir)" -ForegroundColor Gray
    Write-Host ""
}
Write-Host "To start, run:" -ForegroundColor White
Write-Host ""
Write-Host "  interpreter-v2" -ForegroundColor Cyan
Write-Host ""
Write-Host "You may need to restart your terminal first."
Write-Host ""
