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
