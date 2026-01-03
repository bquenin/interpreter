"""Linux GPU setup using CUDA libraries from pip packages."""

import ctypes
import os
import sys
from pathlib import Path


def setup() -> bool:
    """Setup CUDA libraries on Linux.

    Finds CUDA libraries installed via nvidia-* pip packages and:
    1. Adds their directories to LD_LIBRARY_PATH
    2. Preloads the libraries using ctypes (required since LD_LIBRARY_PATH
       is only read at process startup)

    Returns:
        True if CUDA libraries were found and loaded, False otherwise.
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

    # Find all lib directories under nvidia packages
    lib_dirs = []
    for package_dir in nvidia_dir.iterdir():
        if package_dir.is_dir():
            lib_dir = package_dir / "lib"
            if lib_dir.exists():
                lib_dirs.append(str(lib_dir))

    if not lib_dirs:
        return False

    # Add to LD_LIBRARY_PATH environment variable
    current_path = os.environ.get("LD_LIBRARY_PATH", "")
    new_paths = [p for p in lib_dirs if p not in current_path]

    if new_paths:
        os.environ["LD_LIBRARY_PATH"] = os.pathsep.join(new_paths) + os.pathsep + current_path

    # Preload CUDA libraries using ctypes (works even after process start)
    # Order matters: load dependencies first
    cuda_libs = [
        "libcublas.so.12",
        "libcublasLt.so.12",
        "libcudnn.so.9",
    ]

    loaded_any = False
    for lib_dir in lib_dirs:
        for lib_name in cuda_libs:
            lib_path = Path(lib_dir) / lib_name
            if lib_path.exists():
                try:
                    ctypes.CDLL(str(lib_path), mode=ctypes.RTLD_GLOBAL)
                    loaded_any = True
                except OSError:
                    pass  # Library might have unmet dependencies, that's ok

    return loaded_any
