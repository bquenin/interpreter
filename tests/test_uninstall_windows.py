"""Integration tests for the Windows uninstaller."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

POWERSHELL = shutil.which("powershell") or shutil.which("pwsh")
REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SCRIPT = REPO_ROOT / "install.ps1"
UNINSTALL_SCRIPT = REPO_ROOT / "uninstall.ps1"
MODEL_CACHE_NAMES = (
    "models--rtr46--meiki.text.detect.v0",
    "models--rtr46--meiki.txt.recognition.v0",
    "models--entai2965--sugoi-v4-ja-en-ctranslate2",
)

pytestmark = pytest.mark.skipif(
    sys.platform != "win32" or POWERSHELL is None,
    reason="requires PowerShell on Windows",
)


def _create_file(path: Path, content: str = "test") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _run_powershell_script(script: Path, environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            POWERSHELL,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
        ],
        check=False,
        capture_output=True,
        env=environment,
        text=True,
        timeout=30,
    )


def _run_uninstaller(environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return _run_powershell_script(UNINSTALL_SCRIPT, environment)


def _base_environment(tmp_path: Path) -> tuple[dict[str, str], Path, Path, Path, Path]:
    user_profile = tmp_path / "user"
    app_data = tmp_path / "appdata"
    local_app_data = tmp_path / "localappdata"
    model_hub = tmp_path / "huggingface" / "hub"

    environment = os.environ.copy()
    environment.update(
        {
            "APPDATA": str(app_data),
            "HF_HUB_CACHE": str(model_hub),
            "LOCALAPPDATA": str(local_app_data),
            "USERPROFILE": str(user_profile),
        }
    )
    environment.pop("HF_HOME", None)
    environment.pop("UV_CACHE_DIR", None)
    environment.pop("UV_TOOL_BIN_DIR", None)
    environment.pop("UV_TOOL_DIR", None)
    environment.pop("XDG_CACHE_HOME", None)

    return environment, user_profile, app_data, local_app_data, model_hub


def _populate_user_data(user_profile: Path, model_hub: Path) -> Path:
    _create_file(user_profile / ".interpreter" / "config.yml")
    for model_cache_name in MODEL_CACHE_NAMES:
        _create_file(model_hub / model_cache_name / "blobs" / "model.bin")
        _create_file(model_hub / ".locks" / model_cache_name / "download.lock")

    legacy_model = model_hub / "models--bquenin--legacy-model"
    _create_file(legacy_model / "blobs" / "model.bin")
    _create_file(model_hub / ".locks" / legacy_model.name / "download.lock")

    unrelated_model = model_hub / "models--someone-else--unrelated"
    _create_file(unrelated_model / "blobs" / "model.bin")
    return unrelated_model


def test_removes_partial_install_models_and_prunes_uv_cache(tmp_path: Path) -> None:
    environment, user_profile, _, _, model_hub = _base_environment(tmp_path)
    fake_bin = tmp_path / "fake-bin"
    tool_root = tmp_path / "custom-tool-root"
    tool_bin = tmp_path / "custom-tool-bin"
    command_log = tmp_path / "uv-commands.log"

    uv_stub = fake_bin / "uv.cmd"
    _create_file(
        uv_stub,
        """@echo off
echo %*>>"%UV_TEST_LOG%"
if "%1 %2 %3"=="tool dir --bin" echo %UV_TOOL_BIN_DIR%
if "%1 %2"=="tool dir" if not "%3"=="--bin" echo %UV_TOOL_DIR%
if "%1 %2"=="tool list" echo interpreter-v2 v2.17.4
exit /b 0
""",
    )

    partial_environment = tool_root / "interpreter-v2"
    orphan_executable = tool_bin / "interpreter-v2.exe"
    _create_file(partial_environment / "partial-download.whl")
    _create_file(orphan_executable)
    unrelated_model = _populate_user_data(user_profile, model_hub)

    environment.update(
        {
            "PATH": str(fake_bin),
            "UV_TEST_LOG": str(command_log),
            "UV_TOOL_BIN_DIR": str(tool_bin),
            "UV_TOOL_DIR": str(tool_root),
        }
    )

    result = _run_uninstaller(environment)

    assert result.returncode == 0, result.stdout + result.stderr
    assert not partial_environment.exists()
    assert not orphan_executable.exists()
    assert not (user_profile / ".interpreter").exists()
    for model_cache_name in MODEL_CACHE_NAMES:
        assert not (model_hub / model_cache_name).exists()
        assert not (model_hub / ".locks" / model_cache_name).exists()
    assert not (model_hub / "models--bquenin--legacy-model").exists()
    assert unrelated_model.exists()

    uv_commands = command_log.read_text(encoding="utf-8").splitlines()
    assert "tool uninstall interpreter-v2" in uv_commands
    assert not any(command.startswith("cache clean ") for command in uv_commands)
    assert "cache prune" in uv_commands


def test_installer_cleans_its_dedicated_cache_after_failure(tmp_path: Path) -> None:
    environment, user_profile, _, local_app_data, _ = _base_environment(tmp_path)
    fake_bin = tmp_path / "fake-bin"
    command_log = tmp_path / "uv-commands.log"

    uv_stub = fake_bin / "uv.cmd"
    _create_file(
        uv_stub,
        """@echo off
echo %*>>"%UV_TEST_LOG%"
if "%1 %2"=="tool install" exit /b 42
exit /b 0
""",
    )

    environment.update(
        {
            "PATH": str(fake_bin),
            "UV_TEST_LOG": str(command_log),
        }
    )
    install_cache = local_app_data / "interpreter-v2" / "uv-cache"
    _create_file(install_cache / "partial-download.whl")

    result = _run_powershell_script(INSTALL_SCRIPT, environment)

    assert result.returncode == 1
    uv_commands = command_log.read_text(encoding="utf-8").splitlines()
    install_command = next(command for command in uv_commands if command.startswith("tool install "))
    assert f"--cache-dir {install_cache}" in install_command
    assert f"cache clean --cache-dir {install_cache}" in uv_commands
    assert not install_cache.exists()
    assert not (user_profile / ".local" / "bin" / "interpreter-v2.exe").exists()


@pytest.mark.parametrize("use_custom_tool_dirs", [False, True], ids=["default-dirs", "custom-dirs"])
def test_cleans_files_and_models_when_uv_is_unavailable(tmp_path: Path, use_custom_tool_dirs: bool) -> None:
    environment, user_profile, app_data, local_app_data, model_hub = _base_environment(tmp_path)
    empty_path = tmp_path / "empty-path"
    empty_path.mkdir()
    environment["PATH"] = str(empty_path)

    if use_custom_tool_dirs:
        tool_root = tmp_path / "custom-tool-root"
        tool_bin = tmp_path / "custom-tool-bin"
        environment["UV_TOOL_DIR"] = str(tool_root)
        environment["UV_TOOL_BIN_DIR"] = str(tool_bin)
    else:
        tool_root = app_data / "uv" / "tools"
        tool_bin = user_profile / ".local" / "bin"

    partial_environment = tool_root / "interpreter-v2"
    orphan_executable = tool_bin / "interpreter-v2.exe"
    install_cache = local_app_data / "interpreter-v2" / "uv-cache"
    _create_file(partial_environment / "partial-download.whl")
    _create_file(orphan_executable)
    _create_file(install_cache / "partial-download.whl")
    unrelated_model = _populate_user_data(user_profile, model_hub)

    result = _run_uninstaller(environment)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "uv was not found" in result.stdout
    assert not partial_environment.exists()
    assert not orphan_executable.exists()
    assert not install_cache.exists()
    assert not (user_profile / ".interpreter").exists()
    for model_cache_name in MODEL_CACHE_NAMES:
        assert not (model_hub / model_cache_name).exists()
    assert unrelated_model.exists()
