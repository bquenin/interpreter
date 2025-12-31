"""Model management for Interpreter.

Downloads Sugoi V4 translation model from official HuggingFace source on first use.
MeikiOCR models are handled automatically by the meikiocr pip package.
Both use the standard HuggingFace cache at ~/.cache/huggingface/
"""

import os
from pathlib import Path

# Suppress HuggingFace Hub warning about unauthenticated requests
os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"

from huggingface_hub import snapshot_download
from huggingface_hub.utils import LocalEntryNotFoundError

# Official HuggingFace repository for Sugoi V4
SUGOI_REPO_ID = "entai2965/sugoi-v4-ja-en-ctranslate2"


def get_sugoi_model_path() -> Path:
    """Get path to Sugoi V4 translation model, downloading if needed.

    Downloads from official HuggingFace source on first use.
    Model is cached in standard HuggingFace cache (~/.cache/huggingface/).

    Returns:
        Path to the model directory
    """
    # First try to load from cache (no network request)
    try:
        model_path = snapshot_download(
            repo_id=SUGOI_REPO_ID,
            local_files_only=True,
        )
        return Path(model_path)
    except LocalEntryNotFoundError:
        pass

    # Not cached, download from HuggingFace
    print("Downloading Sugoi V4 model (~1.1GB)...")
    model_path = snapshot_download(repo_id=SUGOI_REPO_ID)
    return Path(model_path)
