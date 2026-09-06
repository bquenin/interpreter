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


def _run_powershell_script(
    script: Path, environment: dict[str, str], cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
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
        cwd=cwd,
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
    environment.pop("INTERPRETER_HOME", None)
    environment.pop("UV_CACHE_DIR", None)
    environment.pop("UV_PYTHON_INSTALL_DIR", None)
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


# --- Custom install location (INTERPRETER_HOME) -------------------------------

# Records every call plus the uv directories it would use, and answers the
# queries the scripts make. UV_TEST_INSTALL_EXIT makes `tool install` fail.
UV_STUB_WITH_ENVIRONMENT = """@echo off
echo %*>>"%UV_TEST_LOG%"
echo UV_TOOL_DIR=%UV_TOOL_DIR%>>"%UV_TEST_LOG%"
echo UV_PYTHON_INSTALL_DIR=%UV_PYTHON_INSTALL_DIR%>>"%UV_TEST_LOG%"
if "%1 %2 %3"=="tool dir --bin" echo %UV_TOOL_BIN_DIR%
if "%1 %2"=="tool dir" if not "%3"=="--bin" echo %UV_TOOL_DIR%
if "%1 %2"=="tool list" echo interpreter-v2 v2.17.6
if "%1 %2"=="tool install" if not "%UV_TEST_INSTALL_EXIT%"=="" exit /b %UV_TEST_INSTALL_EXIT%
exit /b 0
"""


def _environment_with_uv_stub(tmp_path: Path) -> tuple[dict[str, str], Path, Path, Path, Path, Path]:
    environment, user_profile, app_data, local_app_data, model_hub = _base_environment(tmp_path)
    fake_bin = tmp_path / "fake-bin"
    command_log = tmp_path / "uv-commands.log"
    _create_file(fake_bin / "uv.cmd", UV_STUB_WITH_ENVIRONMENT)
    environment.update({"PATH": str(fake_bin), "UV_TEST_LOG": str(command_log)})
    return environment, user_profile, app_data, local_app_data, model_hub, command_log


def _log_lines(command_log: Path) -> list[str]:
    return command_log.read_text(encoding="utf-8").splitlines()


def _pointer(user_profile: Path) -> Path:
    return user_profile / ".interpreter" / "install-dir"


def _install_command(root: Path | None, local_app_data: Path) -> str:
    cache = root / "uv-cache" if root else local_app_data / "interpreter-v2" / "uv-cache"
    return f"tool install --force --upgrade --python 3.12 --cache-dir {cache} interpreter-v2"


def test_default_install_keeps_previous_behavior(tmp_path: Path) -> None:
    environment, user_profile, _, local_app_data, _, command_log = _environment_with_uv_stub(tmp_path)

    result = _run_powershell_script(INSTALL_SCRIPT, environment)

    assert result.returncode == 0, result.stdout + result.stderr
    lines = _log_lines(command_log)
    install_index = lines.index(_install_command(None, local_app_data))
    assert lines[install_index + 1] == "UV_TOOL_DIR="
    assert lines[install_index + 2] == "UV_PYTHON_INSTALL_DIR="
    assert not _pointer(user_profile).exists()
    assert "user profile" in result.stdout


def test_install_to_custom_location(tmp_path: Path) -> None:
    environment, user_profile, _, local_app_data, _, command_log = _environment_with_uv_stub(tmp_path)
    root = tmp_path / "other-drive" / "interpreter"
    environment["INTERPRETER_HOME"] = str(root)

    result = _run_powershell_script(INSTALL_SCRIPT, environment)

    assert result.returncode == 0, result.stdout + result.stderr
    lines = _log_lines(command_log)
    install_index = lines.index(_install_command(root, local_app_data))
    assert lines[install_index + 1] == f"UV_TOOL_DIR={root / 'uv' / 'tools'}"
    assert lines[install_index + 2] == f"UV_PYTHON_INSTALL_DIR={root / 'uv' / 'python'}"
    assert f"cache clean --cache-dir {root / 'uv-cache'}" in lines
    assert not any(line.startswith("tool uninstall") for line in lines)
    assert root.is_dir()
    assert not (root / "uv-cache").exists()
    assert not (local_app_data / "interpreter-v2").exists()
    assert _pointer(user_profile).read_text(encoding="utf-8") == str(root)
    assert f"Installed to {root}" in result.stdout
    assert str(root / "models") in result.stdout


def test_relative_location_and_trailing_separator_are_normalized(tmp_path: Path) -> None:
    environment, user_profile, _, _, _, _ = _environment_with_uv_stub(tmp_path)
    environment["INTERPRETER_HOME"] = "relative\\interpreter\\"

    result = _run_powershell_script(INSTALL_SCRIPT, environment, cwd=tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert _pointer(user_profile).read_text(encoding="utf-8") == str(tmp_path / "relative" / "interpreter")


def test_drive_root_is_rejected(tmp_path: Path) -> None:
    environment, user_profile, _, _, _, command_log = _environment_with_uv_stub(tmp_path)
    environment["INTERPRETER_HOME"] = tmp_path.anchor  # e.g. C:\\

    result = _run_powershell_script(INSTALL_SCRIPT, environment)

    assert result.returncode == 1
    assert "drive root" in result.stdout
    assert not command_log.exists()
    assert not _pointer(user_profile).exists()


def test_upgrade_reuses_recorded_location(tmp_path: Path) -> None:
    environment, user_profile, _, local_app_data, _, command_log = _environment_with_uv_stub(tmp_path)
    root = tmp_path / "other-drive" / "interpreter"
    _create_file(_pointer(user_profile), str(root))
    _create_file(root / "uv" / "tools" / "interpreter-v2" / "pyvenv.cfg")

    result = _run_powershell_script(INSTALL_SCRIPT, environment)

    assert result.returncode == 0, result.stdout + result.stderr
    lines = _log_lines(command_log)
    assert _install_command(root, local_app_data) in lines
    assert not any(line.startswith("tool uninstall") for line in lines)
    assert (root / "uv" / "tools" / "interpreter-v2" / "pyvenv.cfg").exists()
    assert _pointer(user_profile).read_text(encoding="utf-8") == str(root)


def test_moving_from_user_profile_removes_previous_environment(tmp_path: Path) -> None:
    environment, _, app_data, _, _, command_log = _environment_with_uv_stub(tmp_path)
    default_environment = app_data / "uv" / "tools" / "interpreter-v2"
    _create_file(default_environment / "pyvenv.cfg")
    root = tmp_path / "other-drive" / "interpreter"
    environment["INTERPRETER_HOME"] = str(root)

    result = _run_powershell_script(INSTALL_SCRIPT, environment)

    assert result.returncode == 0, result.stdout + result.stderr
    lines = _log_lines(command_log)
    uninstall_index = lines.index("tool uninstall interpreter-v2")
    assert lines[uninstall_index + 1] == f"UV_TOOL_DIR={app_data / 'uv' / 'tools'}"
    install_index = next(index for index, line in enumerate(lines) if line.startswith("tool install"))
    assert uninstall_index < install_index
    assert lines[install_index + 1] == f"UV_TOOL_DIR={root / 'uv' / 'tools'}"
    assert not default_environment.exists()
    assert "remain in the HuggingFace cache" in result.stdout


def test_moving_between_custom_locations_removes_previous_environment(tmp_path: Path) -> None:
    environment, user_profile, _, _, _, command_log = _environment_with_uv_stub(tmp_path)
    old_root = tmp_path / "old-drive" / "interpreter"
    new_root = tmp_path / "new-drive" / "interpreter"
    _create_file(_pointer(user_profile), str(old_root))
    _create_file(old_root / "uv" / "tools" / "interpreter-v2" / "pyvenv.cfg")
    _create_file(old_root / "models" / MODEL_CACHE_NAMES[0] / "blobs" / "model.bin")
    environment["INTERPRETER_HOME"] = str(new_root)

    result = _run_powershell_script(INSTALL_SCRIPT, environment)

    assert result.returncode == 0, result.stdout + result.stderr
    lines = _log_lines(command_log)
    uninstall_index = lines.index("tool uninstall interpreter-v2")
    assert lines[uninstall_index + 1] == f"UV_TOOL_DIR={old_root / 'uv' / 'tools'}"
    assert not (old_root / "uv" / "tools" / "interpreter-v2").exists()
    # Models are never deleted by the installer; the user is told where they are.
    assert (old_root / "models" / MODEL_CACHE_NAMES[0]).exists()
    assert f"remain in {old_root / 'models'}" in result.stdout
    assert _pointer(user_profile).read_text(encoding="utf-8") == str(new_root)


def test_failed_install_to_custom_location_cleans_cache_and_records_nothing(tmp_path: Path) -> None:
    environment, user_profile, _, _, _, command_log = _environment_with_uv_stub(tmp_path)
    root = tmp_path / "other-drive" / "interpreter"
    environment["INTERPRETER_HOME"] = str(root)
    environment["UV_TEST_INSTALL_EXIT"] = "42"
    _create_file(root / "uv-cache" / "partial-download.whl")

    result = _run_powershell_script(INSTALL_SCRIPT, environment)

    assert result.returncode == 1
    assert "Installation failed" in result.stdout
    assert f"cache clean --cache-dir {root / 'uv-cache'}" in _log_lines(command_log)
    assert not (root / "uv-cache").exists()
    assert not _pointer(user_profile).exists()


def _populate_custom_install(root: Path, user_profile: Path, model_hub: Path) -> Path:
    _create_file(root / "uv" / "tools" / "interpreter-v2" / "pyvenv.cfg")
    _create_file(root / "uv" / "python" / "cpython-3.12" / "python.exe")
    _create_file(root / "uv-cache" / "partial-download.whl")
    for model_cache_name in MODEL_CACHE_NAMES:
        _create_file(root / "models" / model_cache_name / "blobs" / "model.bin")
    _create_file(user_profile / ".interpreter" / "config.yml")
    # A model left in the default cache by an install that was later moved.
    _create_file(model_hub / MODEL_CACHE_NAMES[2] / "blobs" / "model.bin")
    unrelated_model = model_hub / "models--someone-else--unrelated"
    _create_file(unrelated_model / "blobs" / "model.bin")
    return unrelated_model


def test_uninstall_removes_recorded_location(tmp_path: Path) -> None:
    environment, user_profile, app_data, _, model_hub, command_log = _environment_with_uv_stub(tmp_path)
    root = tmp_path / "other-drive" / "interpreter"
    unrelated_model = _populate_custom_install(root, user_profile, model_hub)
    _create_file(_pointer(user_profile), str(root))
    leftover_default_environment = app_data / "uv" / "tools" / "interpreter-v2"
    _create_file(leftover_default_environment / "pyvenv.cfg")

    result = _run_uninstaller(environment)

    assert result.returncode == 0, result.stdout + result.stderr
    lines = _log_lines(command_log)
    uninstall_index = lines.index("tool uninstall interpreter-v2")
    assert lines[uninstall_index + 1] == f"UV_TOOL_DIR={root / 'uv' / 'tools'}"
    assert not root.exists()
    assert not leftover_default_environment.exists()
    assert not (user_profile / ".interpreter").exists()
    assert not (model_hub / MODEL_CACHE_NAMES[2]).exists()
    assert unrelated_model.exists()
    assert f"Removed install location {root}" in result.stdout


def test_uninstall_keeps_location_with_other_files_and_works_without_uv(tmp_path: Path) -> None:
    environment, user_profile, _, _, model_hub = _base_environment(tmp_path)
    empty_path = tmp_path / "empty-path"
    empty_path.mkdir()
    environment["PATH"] = str(empty_path)
    root = tmp_path / "other-drive" / "interpreter"
    _populate_custom_install(root, user_profile, model_hub)
    _create_file(root / "my-notes.txt", "keep me")
    environment["INTERPRETER_HOME"] = str(root)

    result = _run_uninstaller(environment)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "uv was not found" in result.stdout
    assert not (root / "uv").exists()
    assert not (root / "uv-cache").exists()
    assert not (root / "models").exists()
    assert (root / "my-notes.txt").read_text(encoding="utf-8") == "keep me"
    assert "Kept" in result.stdout
    assert not (user_profile / ".interpreter").exists()
