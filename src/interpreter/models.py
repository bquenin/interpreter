"""Model management for Interpreter.

Downloads Sugoi V4 translation model from official HuggingFace source on first use.
MeikiOCR models are handled automatically by the meikiocr pip package.
Both use the standard HuggingFace cache at ~/.cache/huggingface/
"""

from pathlib import Path

from huggingface_hub import snapshot_download

# Official HuggingFace repository for Sugoi V4
SUGOI_REPO_ID = "entai2965/sugoi-v4-ja-en-ctranslate2"


def get_sugoi_model_path() -> Path:
    """Get path to Sugoi V4 translation model, downloading if needed.

    Downloads from official HuggingFace source on first use.
    Model is cached in standard HuggingFace cache (~/.cache/huggingface/).

    Returns:
        Path to the model directory
    """
    # snapshot_download handles caching automatically
    # Returns cached path if already downloaded, downloads if not
    model_path = snapshot_download(repo_id=SUGOI_REPO_ID)
    return Path(model_path)
