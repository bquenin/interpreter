"""Integration tests for install.sh and uninstall.sh.

They run under bash with a stub ``uv`` on PATH, so they work on Linux, macOS,
and Windows with Git Bash. ``uname`` is stubbed to report macOS so the
Linux-only dependency checks (which need system libraries) are skipped.
"""

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SCRIPT = REPO_ROOT / "install.sh"
UNINSTALL_SCRIPT = REPO_ROOT / "uninstall.sh"
MODEL_CACHE_NAMES = (
    "models--rtr46--meiki.text.detect.v0",
    "models--rtr46--meiki.txt.recognition.v0",
    "models--entai2965--sugoi-v4-ja-en-ctranslate2",
)


def _find_bash() -> str | None:
    if sys.platform == "win32":
        # Prefer Git Bash; the WindowsApps stub launches WSL instead.
        for candidate in (
            Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Git" / "bin" / "bash.exe",
            Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Git" / "usr" / "bin" / "bash.exe",
        ):
            if candidate.is_file():
                return str(candidate)
        found = shutil.which("bash")
        if found and "WindowsApps" not in found:
            return found
        return None
    return shutil.which("bash")


BASH = _find_bash()

pytestmark = pytest.mark.skipif(BASH is None, reason="requires bash")


def _minimal_path(fake_bin: Path) -> str:
    """PATH with the stubs first and only core utilities after, never a real uv."""
    if sys.platform == "win32":
        git_usr_bin = Path(BASH).resolve().parents[1] / "usr" / "bin"
        return os.pathsep.join([str(fake_bin), str(git_usr_bin)])
    return os.pathsep.join([str(fake_bin), "/usr/bin", "/bin"])


def _posix(path: Path) -> str:
    """Path as the bash scripts see it (MSYS form on Windows)."""
    if sys.platform == "win32":
        result = subprocess.run([BASH, "-c", 'cygpath -u "$0"', str(path)], check=True, capture_output=True, text=True)
        return result.stdout.strip()
    return str(path)


def _create_file(path: Path, content: str = "test") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _create_executable(path: Path, content: str) -> None:
    _create_file(path, content)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


UV_STUB = """#!/bin/bash
printf '%s\\n' "$*" >>"$UV_TEST_LOG"
printf 'UV_TOOL_DIR=%s\\n' "${UV_TOOL_DIR:-}" >>"$UV_TEST_LOG"
printf 'UV_PYTHON_INSTALL_DIR=%s\\n' "${UV_PYTHON_INSTALL_DIR:-}" >>"$UV_TEST_LOG"
case "$1 $2" in
"tool dir") echo "${UV_TOOL_DIR:-$HOME/.local/share/uv/tools}" ;;
"tool list") echo "interpreter-v2 v2.17.6" ;;
"tool install") exit "${UV_TEST_INSTALL_EXIT:-0}" ;;
esac
exit 0
"""


def _environment(tmp_path: Path, *, with_uv: bool = True) -> tuple[dict[str, str], Path, Path, Path]:
    home = tmp_path / "home"
    home.mkdir()
    fake_bin = tmp_path / "fake-bin"
    command_log = tmp_path / "uv-commands.log"
    _create_executable(fake_bin / "uname", "#!/bin/bash\necho Darwin\n")
    if with_uv:
        _create_executable(fake_bin / "uv", UV_STUB)

    model_hub = tmp_path / "huggingface" / "hub"
    environment = os.environ.copy()
    for name in (
        "INTERPRETER_HOME",
        "UV_TOOL_DIR",
        "UV_PYTHON_INSTALL_DIR",
        "UV_CACHE_DIR",
        "HF_HOME",
        "XDG_DATA_HOME",
        "XDG_CACHE_HOME",
    ):
        environment.pop(name, None)
    environment.update(
        {
            "HOME": _posix(home),
            "USERPROFILE": str(home),
            "HF_HUB_CACHE": _posix(model_hub),
            "PATH": _minimal_path(fake_bin),
            "UV_TEST_LOG": _posix(command_log),
        }
    )
    return environment, home, model_hub, command_log


def _run(script: Path, environment: dict[str, str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [BASH, _posix(script)],
        check=False,
        capture_output=True,
        env=environment,
        cwd=cwd,
        text=True,
        timeout=60,
    )


def _log_lines(command_log: Path) -> list[str]:
    return command_log.read_text(encoding="utf-8").splitlines()


def _pointer(home: Path) -> Path:
    return home / ".interpreter" / "install-dir"


# --- install.sh ---------------------------------------------------------------


def test_default_install_keeps_previous_behavior(tmp_path: Path) -> None:
    environment, home, _, command_log = _environment(tmp_path)

    result = _run(INSTALL_SCRIPT, environment)

    assert result.returncode == 0, result.stdout + result.stderr
    lines = _log_lines(command_log)
    assert "tool install --upgrade --python 3.12 interpreter-v2" in lines
    assert "UV_TOOL_DIR=" in lines
    assert not _pointer(home).exists()
    assert "home directory" in result.stdout


def test_install_to_custom_location(tmp_path: Path) -> None:
    environment, home, _, command_log = _environment(tmp_path)
    root = tmp_path / "other-drive" / "interpreter"
    root_posix = _posix(root)
    environment["INTERPRETER_HOME"] = root_posix

    result = _run(INSTALL_SCRIPT, environment)

    assert result.returncode == 0, result.stdout + result.stderr
    lines = _log_lines(command_log)
    install_index = lines.index(
        f"tool install --upgrade --python 3.12 --cache-dir {root_posix}/uv-cache interpreter-v2"
    )
    assert lines[install_index + 1] == f"UV_TOOL_DIR={root_posix}/uv/tools"
    assert lines[install_index + 2] == f"UV_PYTHON_INSTALL_DIR={root_posix}/uv/python"
    assert f"cache clean --cache-dir {root_posix}/uv-cache" in lines
    assert not any(line.startswith("tool uninstall") for line in lines)
    assert root.is_dir()
    assert (root / ".interpreter-v2").is_file()
    assert not (root / "uv-cache").exists()
    assert _pointer(home).read_text(encoding="utf-8") == root_posix
    assert f"Installed to {root_posix}" in result.stdout
    assert f"{root_posix}/models" in result.stdout


def test_relative_and_tilde_locations_are_normalized(tmp_path: Path) -> None:
    environment, home, _, _ = _environment(tmp_path)
    environment["INTERPRETER_HOME"] = "~/apps/interpreter"

    result = _run(INSTALL_SCRIPT, environment)

    assert result.returncode == 0, result.stdout + result.stderr
    assert _pointer(home).read_text(encoding="utf-8") == f"{_posix(home)}/apps/interpreter"

    environment["INTERPRETER_HOME"] = "relative/interpreter/"
    result = _run(INSTALL_SCRIPT, environment, cwd=tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert _pointer(home).read_text(encoding="utf-8") == f"{_posix(tmp_path)}/relative/interpreter"


def test_filesystem_root_is_rejected(tmp_path: Path) -> None:
    environment, home, _, command_log = _environment(tmp_path)
    environment["INTERPRETER_HOME"] = "/"

    result = _run(INSTALL_SCRIPT, environment)

    assert result.returncode == 1
    assert "filesystem root" in result.stdout
    assert not command_log.exists()
    assert not _pointer(home).exists()


def test_upgrade_reuses_recorded_location(tmp_path: Path) -> None:
    environment, home, _, command_log = _environment(tmp_path)
    root = tmp_path / "other-drive" / "interpreter"
    root_posix = _posix(root)
    _create_file(_pointer(home), root_posix)
    _create_file(root / "uv" / "tools" / "interpreter-v2" / "pyvenv.cfg")

    result = _run(INSTALL_SCRIPT, environment)

    assert result.returncode == 0, result.stdout + result.stderr
    lines = _log_lines(command_log)
    assert f"tool install --upgrade --python 3.12 --cache-dir {root_posix}/uv-cache interpreter-v2" in lines
    assert not any(line.startswith("tool uninstall") for line in lines)
    assert (root / "uv" / "tools" / "interpreter-v2" / "pyvenv.cfg").exists()
    assert _pointer(home).read_text(encoding="utf-8") == root_posix


def test_moving_from_home_removes_previous_environment(tmp_path: Path) -> None:
    environment, home, _, command_log = _environment(tmp_path)
    default_environment = home / ".local" / "share" / "uv" / "tools" / "interpreter-v2"
    _create_file(default_environment / "pyvenv.cfg")
    root = tmp_path / "other-drive" / "interpreter"
    environment["INTERPRETER_HOME"] = _posix(root)

    result = _run(INSTALL_SCRIPT, environment)

    assert result.returncode == 0, result.stdout + result.stderr
    lines = _log_lines(command_log)
    # --force lets uv replace the launcher left in the shared bin directory.
    install_index = lines.index(
        f"tool install --force --upgrade --python 3.12 --cache-dir {_posix(root)}/uv-cache interpreter-v2"
    )
    assert lines[install_index + 1] == f"UV_TOOL_DIR={_posix(root)}/uv/tools"
    # The old environment is deleted directly: `uv tool uninstall` there would
    # also remove the launcher the new install just created in the shared bin.
    assert not any(line.startswith("tool uninstall") for line in lines)
    assert not default_environment.exists()
    assert "remain in the HuggingFace cache" in result.stdout


def test_moving_between_custom_locations_removes_previous_environment(tmp_path: Path) -> None:
    environment, home, _, command_log = _environment(tmp_path)
    old_root = tmp_path / "old-drive" / "interpreter"
    new_root = tmp_path / "new-drive" / "interpreter"
    _create_file(_pointer(home), _posix(old_root))
    _create_file(old_root / "uv" / "tools" / "interpreter-v2" / "pyvenv.cfg")
    _create_file(old_root / "models" / MODEL_CACHE_NAMES[0] / "blobs" / "model.bin")
    environment["INTERPRETER_HOME"] = _posix(new_root)

    result = _run(INSTALL_SCRIPT, environment)

    assert result.returncode == 0, result.stdout + result.stderr
    lines = _log_lines(command_log)
    assert (
        f"tool install --force --upgrade --python 3.12 --cache-dir {_posix(new_root)}/uv-cache interpreter-v2" in lines
    )
    assert not any(line.startswith("tool uninstall") for line in lines)
    assert not (old_root / "uv" / "tools" / "interpreter-v2").exists()
    # Models are never deleted by the installer; the user is told where they are.
    assert (old_root / "models" / MODEL_CACHE_NAMES[0]).exists()
    assert f"remain in {_posix(old_root)}/models" in result.stdout
    assert _pointer(home).read_text(encoding="utf-8") == _posix(new_root)


def test_failed_install_keeps_previous_install(tmp_path: Path) -> None:
    environment, home, _, command_log = _environment(tmp_path)
    default_environment = home / ".local" / "share" / "uv" / "tools" / "interpreter-v2"
    _create_file(default_environment / "pyvenv.cfg")
    root = tmp_path / "other-drive" / "interpreter"
    environment["INTERPRETER_HOME"] = _posix(root)
    environment["UV_TEST_INSTALL_EXIT"] = "42"
    _create_file(root / "uv-cache" / "partial-download.whl")

    result = _run(INSTALL_SCRIPT, environment)

    assert result.returncode == 1
    assert "Installation failed" in result.stdout
    assert f"cache clean --cache-dir {_posix(root)}/uv-cache" in _log_lines(command_log)
    assert not (root / "uv-cache").exists()
    # Nothing is recorded and the working installation is left untouched.
    assert not _pointer(home).exists()
    assert (default_environment / "pyvenv.cfg").exists()


# --- uninstall.sh -------------------------------------------------------------


def _populate_install(root: Path, home: Path, model_hub: Path, *, marker: bool = True) -> Path:
    if marker:
        _create_file(root / ".interpreter-v2", "Created by the interpreter-v2 installer.")
    _create_file(root / "uv" / "tools" / "interpreter-v2" / "pyvenv.cfg")
    _create_file(root / "uv" / "python" / "cpython-3.12" / "bin" / "python")
    _create_file(root / "uv-cache" / "partial-download.whl")
    for model_cache_name in MODEL_CACHE_NAMES:
        _create_file(root / "models" / model_cache_name / "blobs" / "model.bin")
    _create_file(home / ".interpreter" / "config.yml")
    # A model left in the default cache by an install that was later moved.
    _create_file(model_hub / MODEL_CACHE_NAMES[2] / "blobs" / "model.bin")
    unrelated_model = model_hub / "models--someone-else--unrelated"
    _create_file(unrelated_model / "blobs" / "model.bin")
    return unrelated_model


def test_uninstall_removes_recorded_location(tmp_path: Path) -> None:
    environment, home, model_hub, command_log = _environment(tmp_path)
    root = tmp_path / "other-drive" / "interpreter"
    unrelated_model = _populate_install(root, home, model_hub)
    _create_file(_pointer(home), _posix(root))

    result = _run(UNINSTALL_SCRIPT, environment)

    assert result.returncode == 0, result.stdout + result.stderr
    lines = _log_lines(command_log)
    uninstall_index = lines.index("tool uninstall interpreter-v2")
    assert lines[uninstall_index + 1] == f"UV_TOOL_DIR={_posix(root)}/uv/tools"
    assert not root.exists()
    assert not (home / ".interpreter").exists()
    assert not (model_hub / MODEL_CACHE_NAMES[2]).exists()
    assert unrelated_model.exists()
    assert f"Removed install location {_posix(root)}" in result.stdout


def test_uninstall_keeps_location_with_other_files_and_works_without_uv(tmp_path: Path) -> None:
    environment, home, model_hub, command_log = _environment(tmp_path, with_uv=False)
    root = tmp_path / "other-drive" / "interpreter"
    _populate_install(root, home, model_hub)
    _create_file(root / "my-notes.txt", "keep me")
    environment["INTERPRETER_HOME"] = _posix(root)

    result = _run(UNINSTALL_SCRIPT, environment)

    assert result.returncode == 0, result.stdout + result.stderr
    assert not command_log.exists()
    assert "uv was not found" in result.stdout
    assert not (root / "uv").exists()
    assert not (root / "uv-cache").exists()
    assert not (root / "models").exists()
    assert (root / "my-notes.txt").read_text(encoding="utf-8") == "keep me"
    assert "Kept" in result.stdout
    assert not (home / ".interpreter").exists()


def test_uninstall_leaves_location_without_installer_marker_alone(tmp_path: Path) -> None:
    """A mistyped or shared INTERPRETER_HOME must not have its contents deleted."""
    environment, home, model_hub, _ = _environment(tmp_path)
    root = tmp_path / "shared-tools"
    _populate_install(root, home, model_hub, marker=False)
    _create_file(root / "uv" / "tools" / "other-tool" / "pyvenv.cfg")
    environment["INTERPRETER_HOME"] = _posix(root)

    result = _run(UNINSTALL_SCRIPT, environment)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "was not created by the interpreter-v2 installer" in result.stdout
    # Only interpreter-v2's own tool environment goes; everything else stays.
    assert not (root / "uv" / "tools" / "interpreter-v2").exists()
    assert (root / "uv" / "tools" / "other-tool" / "pyvenv.cfg").exists()
    assert (root / "uv" / "python").exists()
    assert (root / "uv-cache").exists()
    for model_cache_name in MODEL_CACHE_NAMES:
        assert (root / "models" / model_cache_name).exists()


def test_uninstall_without_custom_location_removes_default_models(tmp_path: Path) -> None:
    environment, home, model_hub, command_log = _environment(tmp_path)
    _create_file(home / ".interpreter" / "config.yml")
    for model_cache_name in MODEL_CACHE_NAMES:
        _create_file(model_hub / model_cache_name / "blobs" / "model.bin")
        _create_file(model_hub / ".locks" / model_cache_name / "download.lock")
    legacy_model = model_hub / "models--bquenin--legacy-model"
    _create_file(legacy_model / "blobs" / "model.bin")
    unrelated_model = model_hub / "models--someone-else--unrelated"
    _create_file(unrelated_model / "blobs" / "model.bin")

    result = _run(UNINSTALL_SCRIPT, environment)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "tool uninstall interpreter-v2" in _log_lines(command_log)
    for model_cache_name in MODEL_CACHE_NAMES:
        assert not (model_hub / model_cache_name).exists()
        assert not (model_hub / ".locks" / model_cache_name).exists()
    assert not legacy_model.exists()
    assert unrelated_model.exists()
    assert not (home / ".interpreter").exists()
    assert "No custom install location" in result.stdout
