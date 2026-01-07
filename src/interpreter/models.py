"""Shared utilities for model downloading and recovery."""

import shutil
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
        logger.info("deleting model cache", repo=repo_id)
        shutil.rmtree(cache_path)
        return True
    return False


class ModelLoadError(Exception):
    """Raised when a model fails to load."""

    pass
