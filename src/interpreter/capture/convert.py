"""Frame format conversion utilities.

All capture modules store frames as numpy arrays in native BGRA format.
These utilities convert BGRA to formats needed by consumers.
"""

import numpy as np
from numpy.typing import NDArray

# Type alias for BGRA frame (height, width, 4 channels)
BGRAFrame = NDArray[np.uint8]


def bgra_to_rgb(frame: BGRAFrame) -> NDArray[np.uint8]:
    """Convert BGRA numpy array to RGB numpy array.

    Used by:
    - OCR consumer (directly)
    - GUI preview (via bgra_to_rgb_pil wrapper)

    Args:
        frame: numpy array of shape (H, W, 4) in BGRA format.

    Returns:
        numpy array of shape (H, W, 3) in RGB format.
    """
    # Reorder channels: B=0, G=1, R=2, A=3 -> R=2, G=1, B=0
    rgb = frame[:, :, [2, 1, 0]]
    return np.ascontiguousarray(rgb)


def bgra_to_rgb_pil(frame: BGRAFrame):
    """Convert BGRA numpy array to PIL RGB Image.

    Wraps bgra_to_rgb() for consumers needing PIL Image.

    Args:
        frame: numpy array of shape (H, W, 4) in BGRA format.

    Returns:
        PIL Image in RGB mode.
    """
    from PIL import Image

    return Image.fromarray(bgra_to_rgb(frame), mode="RGB")
