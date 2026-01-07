"""Shared utilities for model downloading and recovery."""

import shutil
from collections.abc import Callable
from pathlib import Path

from huggingface_hub.constants import HF_HUB_CACHE

from . import log

logger = log.get_logger()


def get_hf_cache_path(repo_id: str) -> Path:
    """Get HuggingFace cache directory for a repository.

    Args:
        repo_id: Repository ID (e.g., "org/model-name").

    Returns:
        Path to the cache directory for this repo.
    """
    # HuggingFace stores repos as: ~/.cache/huggingface/hub/models--org--repo/
    repo_folder = "models--" + repo_id.replace("/", "--")
    return Path(HF_HUB_CACHE) / repo_folder


def delete_model_cache(repo_id: str) -> bool:
    """Delete cached model to force re-download.

    Args:
        repo_id: Repository ID (e.g., "org/model-name").

    Returns:
        True if cache was deleted, False if it didn't exist.
    """
    cache_path = get_hf_cache_path(repo_id)
    if cache_path.exists():
        logger.info("deleting corrupted model cache", repo=repo_id)
        shutil.rmtree(cache_path)
        return True
    return False


class ModelLoadError(Exception):
    """Raised when a model fails to load after recovery attempts."""

    pass


def load_with_retry(
    load_fn: Callable[[], None],
    repo_ids: list[str],
    model_name: str,
) -> None:
    """Load a model with automatic cache cleanup and retry on failure.

    Args:
        load_fn: Function that loads the model (should raise on failure).
        repo_ids: List of HuggingFace repo IDs to clear on failure.
        model_name: Human-readable model name for error messages.

    Raises:
        ModelLoadError: If model fails to load after retry.
    """
    try:
        load_fn()
        return
    except Exception as e:
        error_str = str(e).lower()
        # Check if this looks like a file/corruption error
        is_file_error = any(
            term in error_str
            for term in ["file", "open", "read", "corrupt", "invalid", "onnx"]
        )

        if not is_file_error:
            # Not a file error, re-raise immediately
            raise ModelLoadError(
                f"Failed to load {model_name}: {e}\n"
                f"Please check your internet connection and try again."
            ) from e

        logger.warning(
            "model load failed, attempting recovery",
            model=model_name,
            error=str(e)[:100],
        )

    # Clear caches and retry
    for repo_id in repo_ids:
        delete_model_cache(repo_id)

    try:
        load_fn()
        logger.info("model recovery successful", model=model_name)
    except Exception as e:
        raise ModelLoadError(
            f"Failed to download {model_name}. "
            f"Please check your internet connection and try again."
        ) from e
