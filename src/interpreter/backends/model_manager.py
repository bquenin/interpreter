"""Model management for downloading, caching, and status tracking."""

import os
import shutil
from enum import Enum
from pathlib import Path
from typing import Callable

from huggingface_hub import snapshot_download
from huggingface_hub.constants import HF_HUB_CACHE
from huggingface_hub.utils import LocalEntryNotFoundError

from .. import log
from .base import OCRBackendInfo, TranslationBackendInfo

logger = log.get_logger()

# Suppress HuggingFace Hub warnings
os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"
os.environ["HF_HUB_VERBOSITY"] = "error"


class ModelStatus(Enum):
    """Status of a model installation."""

    NOT_INSTALLED = "not_installed"
    DOWNLOADING = "downloading"
    READY = "ready"
    ERROR = "error"


# Type alias for progress callback
# callback(current_bytes, total_bytes, filename)
ProgressCallback = Callable[[int, int, str], None]


class ModelManager:
    """Manages model downloading, caching, and status tracking.

    This class provides a unified interface for managing models from
    HuggingFace Hub, including checking installation status, downloading,
    and repairing corrupted models.
    """

    def __init__(self):
        """Initialize the model manager."""
        self._download_status: dict[str, ModelStatus] = {}
        self._download_errors: dict[str, str] = {}

    def get_hf_cache_path(self, repo_id: str) -> Path:
        """Get HuggingFace cache directory for a repository.

        Args:
            repo_id: Repository ID (e.g., "org/model-name").

        Returns:
            Path to the cache directory for this repo.
        """
        # HuggingFace stores repos as: ~/.cache/huggingface/hub/models--org--repo/
        repo_folder = "models--" + repo_id.replace("/", "--")
        return Path(HF_HUB_CACHE) / repo_folder

    def is_installed(self, backend_info: OCRBackendInfo | TranslationBackendInfo) -> bool:
        """Check if a backend's model is installed.

        Args:
            backend_info: Backend info with huggingface_repo(s) field.

        Returns:
            True if the model is installed and ready, False otherwise.
        """
        repo_ids = self._get_repo_ids(backend_info)
        if not repo_ids:
            # Backend doesn't use HuggingFace (e.g., Tesseract)
            return True

        # All repos must be installed
        for repo_id in repo_ids:
            try:
                snapshot_download(repo_id=repo_id, local_files_only=True)
            except LocalEntryNotFoundError:
                return False

        return True

    def get_status(self, backend_info: OCRBackendInfo | TranslationBackendInfo) -> ModelStatus:
        """Get the current status of a backend's model.

        Args:
            backend_info: Backend info with huggingface_repo(s) field.

        Returns:
            Current ModelStatus.
        """
        repo_ids = self._get_repo_ids(backend_info)
        if not repo_ids:
            # Backend doesn't use HuggingFace
            return ModelStatus.READY

        # Check if any repo is currently downloading
        for repo_id in repo_ids:
            if repo_id in self._download_status:
                return self._download_status[repo_id]

        # Check if any repo had an error
        for repo_id in repo_ids:
            if repo_id in self._download_errors:
                return ModelStatus.ERROR

        # Check if installed
        if self.is_installed(backend_info):
            return ModelStatus.READY

        return ModelStatus.NOT_INSTALLED

    def get_error(self, backend_info: OCRBackendInfo | TranslationBackendInfo) -> str | None:
        """Get the error message for a failed model download.

        Args:
            backend_info: Backend info with huggingface_repo(s) field.

        Returns:
            Error message if there was an error, None otherwise.
        """
        repo_ids = self._get_repo_ids(backend_info)
        if not repo_ids:
            return None

        # Return first error found
        for repo_id in repo_ids:
            if repo_id in self._download_errors:
                return self._download_errors[repo_id]

        return None

    def install(
        self,
        backend_info: OCRBackendInfo | TranslationBackendInfo,
        progress_callback: ProgressCallback | None = None,
    ) -> list[Path]:
        """Download and install a backend's model(s).

        Args:
            backend_info: Backend info with huggingface_repo(s) field.
            progress_callback: Optional callback for download progress.

        Returns:
            List of paths to the installed model directories.

        Raises:
            ValueError: If backend doesn't have a HuggingFace repo.
            Exception: If download fails.
        """
        repo_ids = self._get_repo_ids(backend_info)
        if not repo_ids:
            raise ValueError(f"Backend {backend_info.name} does not have a HuggingFace repository")

        # Clear any previous errors
        for repo_id in repo_ids:
            self._download_errors.pop(repo_id, None)

        model_paths = []
        total_repos = len(repo_ids)

        for idx, repo_id in enumerate(repo_ids):
            # Update status
            self._download_status[repo_id] = ModelStatus.DOWNLOADING

            try:
                logger.info(
                    "downloading model",
                    repo=repo_id,
                    progress=f"{idx + 1}/{total_repos}",
                )

                # Download
                model_path = Path(snapshot_download(repo_id=repo_id))

                # Notify progress
                if progress_callback:
                    progress_callback(idx + 1, total_repos, repo_id)

                # Update status
                self._download_status[repo_id] = ModelStatus.READY
                model_paths.append(model_path)
                logger.info("model download complete", repo=repo_id)

            except Exception as e:
                # Record error
                self._download_status[repo_id] = ModelStatus.ERROR
                self._download_errors[repo_id] = str(e)
                logger.error("model download failed", repo=repo_id, error=str(e))
                raise

            finally:
                # Clean up downloading status (but keep error status)
                if self._download_status.get(repo_id) == ModelStatus.DOWNLOADING:
                    del self._download_status[repo_id]

        return model_paths

    def uninstall(self, backend_info: OCRBackendInfo | TranslationBackendInfo) -> bool:
        """Remove a backend's model(s) from cache.

        Args:
            backend_info: Backend info with huggingface_repo(s) field.

        Returns:
            True if any model was uninstalled, False if none were installed.
        """
        repo_ids = self._get_repo_ids(backend_info)
        if not repo_ids:
            return False

        any_uninstalled = False
        for repo_id in repo_ids:
            cache_path = self.get_hf_cache_path(repo_id)
            if cache_path.exists():
                logger.info("uninstalling model", repo=repo_id)
                shutil.rmtree(cache_path)
                any_uninstalled = True

            # Clear status
            self._download_status.pop(repo_id, None)
            self._download_errors.pop(repo_id, None)

        return any_uninstalled

    def repair(
        self,
        backend_info: OCRBackendInfo | TranslationBackendInfo,
        progress_callback: ProgressCallback | None = None,
    ) -> list[Path]:
        """Repair corrupted model(s) by re-downloading.

        Args:
            backend_info: Backend info with huggingface_repo(s) field.
            progress_callback: Optional callback for download progress.

        Returns:
            List of paths to the repaired model directories.
        """
        # First uninstall
        self.uninstall(backend_info)

        # Then reinstall
        return self.install(backend_info, progress_callback)

    def get_model_paths(self, backend_info: OCRBackendInfo | TranslationBackendInfo) -> list[Path]:
        """Get the paths to installed model(s).

        Args:
            backend_info: Backend info with huggingface_repo(s) field.

        Returns:
            List of paths to model directories, empty if not installed.
        """
        repo_ids = self._get_repo_ids(backend_info)
        if not repo_ids:
            return []

        paths = []
        for repo_id in repo_ids:
            try:
                path = Path(snapshot_download(repo_id=repo_id, local_files_only=True))
                paths.append(path)
            except LocalEntryNotFoundError:
                pass

        return paths

    def get_model_size_on_disk(self, backend_info: OCRBackendInfo | TranslationBackendInfo) -> int:
        """Get the total size of installed model(s) in bytes.

        Args:
            backend_info: Backend info with huggingface_repo(s) field.

        Returns:
            Total size in bytes, or 0 if not installed.
        """
        repo_ids = self._get_repo_ids(backend_info)
        if not repo_ids:
            return 0

        total_size = 0
        for repo_id in repo_ids:
            cache_path = self.get_hf_cache_path(repo_id)
            if cache_path.exists():
                for file_path in cache_path.rglob("*"):
                    if file_path.is_file():
                        total_size += file_path.stat().st_size

        return total_size

    def _get_repo_ids(self, backend_info: OCRBackendInfo | TranslationBackendInfo) -> list[str]:
        """Extract HuggingFace repo IDs from backend info.

        Args:
            backend_info: Backend info object.

        Returns:
            List of repository ID strings, empty if none available.
        """
        if isinstance(backend_info, TranslationBackendInfo):
            # Translation backends have a single repo
            if backend_info.huggingface_repo:
                return [backend_info.huggingface_repo]
            return []

        if isinstance(backend_info, OCRBackendInfo):
            # OCR backends may have multiple repos
            return backend_info.huggingface_repos or []

        return []


# Global model manager instance
_manager: ModelManager | None = None


def get_model_manager() -> ModelManager:
    """Get the global model manager instance.

    Returns:
        The global ModelManager instance.
    """
    global _manager
    if _manager is None:
        _manager = ModelManager()
    return _manager
