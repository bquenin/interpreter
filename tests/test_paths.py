"""Tests for the custom install location resolution."""

import importlib.util
import os
import sys
from pathlib import Path

import pytest

# Load the module from its file so these tests run without the package being
# installed (interpreter/__init__ reads the distribution version on import).
_PATHS_FILE = Path(__file__).resolve().parents[1] / "src" / "interpreter" / "paths.py"
_spec = importlib.util.spec_from_file_location("interpreter_paths_under_test", _PATHS_FILE)
paths = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = paths
_spec.loader.exec_module(paths)


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    # Path.home() reads USERPROFILE on Windows and HOME elsewhere.
    monkeypatch.setenv("USERPROFILE", str(home_dir))
    monkeypatch.setenv("HOME", str(home_dir))
    monkeypatch.delenv(paths.INSTALL_ROOT_ENV, raising=False)
    monkeypatch.delenv("HF_HUB_CACHE", raising=False)
    return home_dir


def _write_pointer(home_dir: Path, value: str) -> None:
    config_dir = home_dir / ".interpreter"
    config_dir.mkdir(exist_ok=True)
    (config_dir / paths.INSTALL_ROOT_FILE_NAME).write_text(value, encoding="utf-8")


def test_default_layout_when_nothing_is_configured(home: Path) -> None:
    assert paths.get_install_root() is None
    assert paths.get_models_dir() is None

    paths.apply_environment()

    assert "HF_HUB_CACHE" not in os.environ


def test_environment_variable_sets_install_root(home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "other-drive" / "interpreter"
    monkeypatch.setenv(paths.INSTALL_ROOT_ENV, str(root))

    assert paths.get_install_root() == root
    assert paths.get_models_dir() == root / "models"


def test_pointer_file_sets_install_root(home: Path, tmp_path: Path) -> None:
    root = tmp_path / "other-drive" / "interpreter"
    _write_pointer(home, f"{root}\n")

    assert paths.get_install_root() == root
    assert paths.get_models_dir() == root / "models"


def test_environment_variable_wins_over_pointer_file(
    home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_pointer(home, str(tmp_path / "recorded"))
    monkeypatch.setenv(paths.INSTALL_ROOT_ENV, str(tmp_path / "explicit"))

    assert paths.get_install_root() == tmp_path / "explicit"


def test_blank_values_mean_default_layout(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_pointer(home, "   \n")
    monkeypatch.setenv(paths.INSTALL_ROOT_ENV, "  ")

    assert paths.get_install_root() is None


def test_blank_environment_variable_falls_back_to_pointer(
    home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_pointer(home, str(tmp_path / "recorded"))
    monkeypatch.setenv(paths.INSTALL_ROOT_ENV, "")

    assert paths.get_install_root() == tmp_path / "recorded"


def test_tilde_is_expanded(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(paths.INSTALL_ROOT_ENV, "~/interpreter")

    assert paths.get_install_root() == home / "interpreter"


def test_relative_value_is_anchored_to_working_directory(
    home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(paths.INSTALL_ROOT_ENV, "relative/interpreter/")

    root = paths.get_install_root()

    assert root is not None
    assert root.is_absolute()
    assert root == tmp_path / "relative" / "interpreter"


def test_apply_environment_redirects_hf_cache(home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "other-drive" / "interpreter"
    monkeypatch.setenv(paths.INSTALL_ROOT_ENV, str(root))
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "generic-hf-cache"))

    paths.apply_environment()

    assert os.environ["HF_HUB_CACHE"] == str(root / "models")


def test_apply_environment_matches_huggingface_hub(home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """huggingface_hub reads HF_HUB_CACHE once at import; check it honors ours."""
    pytest.importorskip("huggingface_hub")
    root = tmp_path / "other-drive" / "interpreter"
    monkeypatch.setenv(paths.INSTALL_ROOT_ENV, str(root))
    monkeypatch.delitem(sys.modules, "huggingface_hub", raising=False)
    monkeypatch.delitem(sys.modules, "huggingface_hub.constants", raising=False)

    paths.apply_environment()
    import huggingface_hub.constants as hf_constants

    importlib_reloaded = importlib.reload(hf_constants)
    assert Path(importlib_reloaded.HF_HUB_CACHE) == root / "models"
