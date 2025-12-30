"""Configuration management for Interpreter."""

import os
from pathlib import Path

import yaml


class Config:
    """Application configuration."""

    def __init__(
        self,
        window_title: str = "RetroArch",
        refresh_rate: float = 0.5,
        ocr_confidence: float = 0.6,
        overlay_mode: str = "banner",
        font_size: int = 24,
        font_color: str = "#FFFFFF",
        background_color: str = "#404040",
        background_opacity: float = 0.8,
    ):
        self.window_title = window_title
        self.refresh_rate = refresh_rate
        self.ocr_confidence = ocr_confidence
        self.overlay_mode = overlay_mode  # "banner" or "inplace"
        self.font_size = font_size
        self.font_color = font_color
        self.background_color = background_color
        self.background_opacity = background_opacity

    @classmethod
    def load(cls, config_path: str | None = None) -> "Config":
        """Load configuration from YAML file.

        Args:
            config_path: Path to config file. If None, looks for config.yml
                        in common locations.

        Returns:
            Config instance with loaded values.
        """
        if config_path is None:
            # Look for config in common locations
            search_paths = [
                Path("config.yml"),
                Path(__file__).parent.parent / "config.yml",
                Path.home() / ".interpreter" / "config.yml",
            ]
            for path in search_paths:
                if path.exists():
                    config_path = str(path)
                    break

        if config_path and os.path.exists(config_path):
            with open(config_path, "r") as f:
                data = yaml.safe_load(f) or {}
            return cls(
                window_title=data.get("window_title", "RetroArch"),
                refresh_rate=float(data.get("refresh_rate", 0.5)),
                ocr_confidence=float(data.get("ocr_confidence", 0.6)),
                overlay_mode=data.get("overlay_mode", "banner"),
                font_size=int(data.get("font_size", 24)),
                font_color=data.get("font_color", "#FFFFFF"),
                background_color=data.get("background_color", "#404040"),
                background_opacity=float(data.get("background_opacity", 0.8)),
            )

        # Return defaults if no config file found
        return cls()

    def hex_to_rgb(self, hex_color: str) -> tuple[int, int, int]:
        """Convert hex color string to RGB tuple."""
        hex_color = hex_color.lstrip("#")
        return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
