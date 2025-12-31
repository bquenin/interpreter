"""GPU setup utilities for CUDA support on Windows and Linux."""

import os
import sys
from pathlib import Path


def setup_cuda_dlls() -> bool:
    """Add NVIDIA CUDA library directories to the system library path.

    On Windows, the nvidia-* pip packages install DLLs to site-packages/nvidia/*/bin/.
    On Linux, they install .so files to site-packages/nvidia/*/lib/.
    This function finds those directories and adds them to PATH (Windows) or
    LD_LIBRARY_PATH (Linux) so ctranslate2 and onnxruntime can find the CUDA libraries.

    Returns:
        True if CUDA libraries were found and added, False otherwise.
    """
    if sys.platform == "linux":
        return _setup_cuda_linux()
    elif sys.platform == "win32":
        return _setup_cuda_windows()
    return False


def _setup_cuda_linux() -> bool:
    """Setup CUDA libraries on Linux by updating LD_LIBRARY_PATH and preloading libs."""
    import ctypes

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

    for lib_dir in lib_dirs:
        for lib_name in cuda_libs:
            lib_path = Path(lib_dir) / lib_name
            if lib_path.exists():
                try:
                    ctypes.CDLL(str(lib_path), mode=ctypes.RTLD_GLOBAL)
                except OSError:
                    pass  # Library might have unmet dependencies, that's ok

    return True


def _setup_cuda_windows() -> bool:
    """Setup CUDA DLLs on Windows by updating PATH."""

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
