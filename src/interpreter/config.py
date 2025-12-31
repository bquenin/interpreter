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
        font_size: int = 40,
        font_color: str = "#FFFFFF",
        background_color: str = "#404040",
    ):
        self.window_title = window_title
        self.refresh_rate = refresh_rate
        self.ocr_confidence = ocr_confidence
        self.overlay_mode = overlay_mode  # "banner" or "inplace"
        self.font_size = font_size
        self.font_color = font_color
        self.background_color = background_color

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
            with open(config_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            return cls(
                window_title=data.get("window_title", "RetroArch"),
                refresh_rate=float(data.get("refresh_rate", 0.5)),
                ocr_confidence=float(data.get("ocr_confidence", 0.6)),
                overlay_mode=data.get("overlay_mode", "banner"),
                font_size=int(data.get("font_size", 40)),
                font_color=data.get("font_color", "#FFFFFF"),
                background_color=data.get("background_color", "#404040"),
            )

        # No config file found - create default in home directory
        config = cls()
        config._create_default_config()
        return config

    def _create_default_config(self) -> None:
        """Create a default config file in the user's home directory."""
        config_dir = Path.home() / ".interpreter"
        config_path = config_dir / "config.yml"

        # Don't overwrite if it already exists
        if config_path.exists():
            return

        # Create directory if needed
        config_dir.mkdir(parents=True, exist_ok=True)

        # Write default config with comments
        default_config = """# Window to capture (partial title match)
window_title: "RetroArch"

# Refresh rate in seconds (how often to capture and process the screen)
# Lower = more responsive but higher CPU usage
# Recommended: 0.5s (fast CPU) to 1.0s (slower CPU)
refresh_rate: 0.5

# OCR confidence threshold (0.0-1.0)
# Filters out low-confidence text detection
ocr_confidence: 0.6

# Overlay mode: "banner" (subtitle bar) or "inplace" (over game text)
overlay_mode: banner

# Subtitle appearance
font_size: 40
font_color: "#FFFFFF"
background_color: "#404040"
"""
        with open(config_path, "w", encoding="utf-8") as f:
            f.write(default_config)

        print(f"Created default config at: {config_path}")

    def hex_to_rgb(self, hex_color: str) -> tuple[int, int, int]:
        """Convert hex color string to RGB tuple."""
        hex_color = hex_color.lstrip("#")
        return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
