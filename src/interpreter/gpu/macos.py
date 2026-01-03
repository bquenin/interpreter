"""macOS GPU setup (no-op).

macOS uses Metal/MPS for GPU acceleration, which is handled automatically
by the ML frameworks (CoreML, MLX). No explicit setup is required.

CUDA is not available on macOS.
"""


def setup() -> bool:
    """Setup GPU on macOS.

    No-op on macOS as Metal/MPS is handled automatically by ML frameworks.

    Returns:
        False (CUDA not available on macOS).
    """
    return False
