"""Tests for the translate module."""

import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestGetShortPath:
    """Tests for _get_short_path function."""

    def test_non_windows_returns_original_path(self):
        """On non-Windows platforms, should return the original path string."""
        from interpreter.translate import _get_short_path

        test_path = Path("/home/user/models/test.bin")

        with patch("interpreter.translate.sys.platform", "linux"):
            result = _get_short_path(test_path)

        assert result == str(test_path)

    def test_non_windows_darwin_returns_original_path(self):
        """On macOS, should return the original path string."""
        from interpreter.translate import _get_short_path

        test_path = Path("/Users/Álvaro/models/test.bin")

        with patch("interpreter.translate.sys.platform", "darwin"):
            result = _get_short_path(test_path)

        assert result == str(test_path)

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific test")
    def test_windows_successful_conversion(self):
        """On Windows, should return short path when conversion succeeds."""
        from interpreter.translate import _get_short_path

        test_path = Path(r"C:\Users\Álvaro\models\test.bin")
        short_path = r"C:\Users\LVARO~1\models\test.bin"

        # Create mock for the ctypes module
        mock_ctypes = MagicMock()
        mock_buffer = MagicMock()
        mock_buffer.value = short_path
        mock_ctypes.create_unicode_buffer.return_value = mock_buffer
        mock_ctypes.windll.kernel32.GetShortPathNameW.return_value = len(short_path)

        with (
            patch.dict("sys.modules", {"ctypes": mock_ctypes}),
            patch("interpreter.translate.sys.platform", "win32"),
        ):
            result = _get_short_path(test_path)

        assert result == short_path

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific test")
    def test_windows_fallback_on_failure(self):
        """On Windows, should return original path when conversion fails."""
        from interpreter.translate import _get_short_path

        test_path = Path(r"C:\Users\Álvaro\models\test.bin")

        # Create mock for the ctypes module
        mock_ctypes = MagicMock()
        mock_buffer = MagicMock()
        mock_ctypes.create_unicode_buffer.return_value = mock_buffer
        mock_ctypes.windll.kernel32.GetShortPathNameW.return_value = 0

        with (
            patch.dict("sys.modules", {"ctypes": mock_ctypes}),
            patch("interpreter.translate.sys.platform", "win32"),
        ):
            result = _get_short_path(test_path)

        assert result == str(test_path)

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific test")
    def test_windows_with_real_ascii_path(self):
        """On Windows with a real ASCII-only path, conversion should work."""
        from interpreter.translate import _get_short_path

        # Use a path that actually exists on Windows
        test_path = Path(r"C:\Windows\System32")

        result = _get_short_path(test_path)

        # Result should be a valid path string
        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific test")
    def test_windows_returns_valid_short_path_format(self):
        """On Windows, short path should be returned for paths with special chars."""
        from interpreter.translate import _get_short_path

        # Use temp directory which always exists
        test_path = Path(tempfile.gettempdir())

        result = _get_short_path(test_path)

        # Result should be a non-empty string
        assert isinstance(result, str)
        assert len(result) > 0
        # The path should exist (since we used an existing path)
        assert Path(result).exists()


def _fake_model_dir(tmp_path: Path) -> Path:
    """Create a directory with just the tokenizer file Translator reads directly."""
    spm_dir = tmp_path / "spm"
    spm_dir.mkdir()
    (spm_dir / "spm.ja.nopretok.model").write_bytes(b"fake")
    return tmp_path


class TestModelLoading:
    """Tests for cache lookup, self-repair of partial caches, and download retries."""

    def _load(self, model_dir: Path, ctranslate2_side_effects: list):
        """Run Translator.load with mocked ctranslate2/sentencepiece/snapshot_download."""
        from interpreter import translate

        ct2 = MagicMock()
        ct2.get_supported_compute_types.return_value = []  # force CPU path
        ct2.Translator.side_effect = ctranslate2_side_effects
        spm = MagicMock()

        with (
            patch.dict(sys.modules, {"ctranslate2": ct2, "sentencepiece": spm}),
            patch.object(translate, "snapshot_download") as snapshot_download,
        ):
            snapshot_download.return_value = str(model_dir)
            translator = translate.Translator()
            translator.load()
        return translator, snapshot_download, ct2

    def test_cached_model_loads_without_network(self, tmp_path):
        model_dir = _fake_model_dir(tmp_path)
        translator, snapshot_download, _ = self._load(model_dir, [MagicMock()])

        assert translator._translator is not None
        assert snapshot_download.call_count == 1
        assert snapshot_download.call_args.kwargs["local_files_only"] is True

    def test_pinned_revision_is_used(self, tmp_path):
        from interpreter.translate import SUGOI_REVISION

        model_dir = _fake_model_dir(tmp_path)
        _, snapshot_download, _ = self._load(model_dir, [MagicMock()])

        assert snapshot_download.call_args.kwargs["revision"] == SUGOI_REVISION

    def test_partial_cache_is_repaired_online(self, tmp_path):
        """Issue #249: missing config.json makes CTranslate2 raise a JSON null error."""
        model_dir = _fake_model_dir(tmp_path)
        json_error = RuntimeError("[json.exception.type_error.302] type must be string, but is null")
        translator, snapshot_download, ct2 = self._load(model_dir, [json_error, MagicMock()])

        assert translator._translator is not None
        assert ct2.Translator.call_count == 2
        # First call is local-only, second is the online re-sync
        assert snapshot_download.call_count == 2
        assert snapshot_download.call_args_list[0].kwargs["local_files_only"] is True
        assert "local_files_only" not in snapshot_download.call_args_list[1].kwargs

    def test_unrepairable_cache_raises_model_load_error(self, tmp_path):
        from interpreter.models import ModelLoadError

        model_dir = _fake_model_dir(tmp_path)
        with pytest.raises(ModelLoadError, match="Fix Models"):
            self._load(model_dir, [RuntimeError("bad"), RuntimeError("still bad")])

    def test_missing_tokenizer_triggers_repair(self, tmp_path):
        """A missing spm file raises OSError, which must also trigger the re-sync."""
        from interpreter import translate

        ct2 = MagicMock()
        ct2.get_supported_compute_types.return_value = []
        spm = MagicMock()

        def repair(*args, **kwargs):
            if "local_files_only" not in kwargs:
                _fake_model_dir(tmp_path)
            return str(tmp_path)

        with (
            patch.dict(sys.modules, {"ctranslate2": ct2, "sentencepiece": spm}),
            patch.object(translate, "snapshot_download", side_effect=repair) as snapshot_download,
        ):
            translate.Translator().load()

        assert snapshot_download.call_count == 2


class TestDownloadRetry:
    """Tests for _download_sugoi_model retry behaviour."""

    def test_transient_failure_is_retried(self, tmp_path):
        from interpreter import translate

        with patch.object(
            translate,
            "snapshot_download",
            side_effect=[ConnectionError("Server disconnected"), str(tmp_path)],
        ) as snapshot_download:
            assert translate._download_sugoi_model() == tmp_path
        assert snapshot_download.call_count == 2

    def test_persistent_failure_raises_model_load_error(self):
        from interpreter import translate
        from interpreter.models import ModelLoadError

        with (
            patch.object(
                translate, "snapshot_download", side_effect=ConnectionError("Server disconnected")
            ) as snapshot_download,
            pytest.raises(ModelLoadError, match="Fix Models"),
        ):
            translate._download_sugoi_model()
        assert snapshot_download.call_count == translate.DOWNLOAD_ATTEMPTS

    def test_uncached_model_is_downloaded(self, tmp_path):
        from huggingface_hub.utils import LocalEntryNotFoundError

        from interpreter import translate

        with patch.object(
            translate, "snapshot_download", side_effect=[LocalEntryNotFoundError("nope"), str(tmp_path)]
        ) as snapshot_download:
            assert translate._get_sugoi_model_path() == tmp_path
        assert snapshot_download.call_count == 2
