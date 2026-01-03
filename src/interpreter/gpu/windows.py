"""Windows GPU setup using CUDA DLLs from pip packages."""

import os
import sys
from pathlib import Path


def setup() -> bool:
    """Setup CUDA DLLs on Windows.

    Finds CUDA DLLs installed via nvidia-* pip packages and:
    1. Adds their directories to PATH
    2. Registers them with os.add_dll_directory (Python 3.8+)

    Returns:
        True if CUDA DLLs were found and registered, False otherwise.
    """

    # Find site-packages directory
    site_packages = None
    for path in sys.path:
        if "site-packages" in path and Path(path).exists():
            site_packages = Path(path)
            break

    if site_packages is None:
        return False

    # Look for nvidia package directories
    nvidia_dir = site_packages / "nvidia"
    if not nvidia_dir.exists():
        return False

    # Find all bin directories under nvidia packages
    dll_dirs = []
    for package_dir in nvidia_dir.iterdir():
        if package_dir.is_dir():
            bin_dir = package_dir / "bin"
            if bin_dir.exists():
                dll_dirs.append(str(bin_dir))

    if not dll_dirs:
        return False

    # Add to PATH environment variable
    current_path = os.environ.get("PATH", "")
    new_paths = [p for p in dll_dirs if p not in current_path]

    if new_paths:
        os.environ["PATH"] = os.pathsep.join(new_paths) + os.pathsep + current_path

    # Also use os.add_dll_directory for Python 3.8+ on Windows
    # This is the preferred method for finding DLLs
    for dll_dir in dll_dirs:
        try:
            os.add_dll_directory(dll_dir)
        except (OSError, AttributeError):
            pass  # add_dll_directory may not exist or may fail

    return True
