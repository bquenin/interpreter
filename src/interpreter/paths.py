"""Resolution of the optional custom install location.

By default everything lives under the user's home directory: the uv tool
environment, the uv-managed Python, and the HuggingFace model cache. Users with
a small system drive can instead point the installer at another location via the
INTERPRETER_HOME environment variable. The installer records that location in
~/.interpreter/install-dir so later runs (and the app itself) find it without
the variable being set again.

Layout under the install location::

    <root>/uv/tools     uv tool environments (UV_TOOL_DIR)
    <root>/uv/python    uv-managed Python (UV_PYTHON_INSTALL_DIR)
    <root>/uv-cache     package downloads, removed after install
    <root>/models       HuggingFace hub cache (HF_HUB_CACHE)

The installers and uninstallers mirror this layout; keep them in sync.
"""

import os
from pathlib import Path

INSTALL_ROOT_ENV = "INTERPRETER_HOME"
INSTALL_ROOT_FILE_NAME = "install-dir"
MODELS_DIR_NAME = "models"


def get_config_dir() -> Path:
    """Directory holding config.yml and the install location pointer."""
    return Path.home() / ".interpreter"


def get_install_root() -> Path | None:
    """Return the custom install location, or None for the default layout.

    INTERPRETER_HOME takes precedence over the pointer file written by the
    installer. Blank values are treated as unset.
    """
    value = os.environ.get(INSTALL_ROOT_ENV, "").strip()
    if not value:
        pointer = get_config_dir() / INSTALL_ROOT_FILE_NAME
        try:
            value = pointer.read_text(encoding="utf-8-sig").strip()
        except OSError:
            return None
    if not value:
        return None
    return Path(os.path.expanduser(value))


def get_models_dir() -> Path | None:
    """Return the model cache directory under the install location, if any."""
    root = get_install_root()
    if root is None:
        return None
    return root / MODELS_DIR_NAME


def apply_environment() -> None:
    """Point huggingface_hub at the custom model directory.

    Must run before huggingface_hub is imported anywhere, because it reads
    HF_HUB_CACHE once at import time. An install location always wins over a
    generic HF_HOME/HF_HUB_CACHE so that models land where the user asked the
    installer to put them.
    """
    models_dir = get_models_dir()
    if models_dir is not None:
        os.environ["HF_HUB_CACHE"] = str(models_dir)
