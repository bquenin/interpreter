"""Configuration management for Interpreter."""

import os
from pathlib import Path

import yaml

from . import log

logger = log.get_logger()


class Config:
    """Application configuration."""

    DEFAULT_WINDOW_TITLE = "Snes9x"

    # Default hotkeys
    DEFAULT_HOTKEYS = {
        "toggle_overlay": "space",
        "switch_mode": "m",
        "increase_font": "=",
        "decrease_font": "-",
        "quit": "q",
    }

    def __init__(
        self,
        window_title: str = "Snes9x",
        refresh_rate: float = 0.5,
        ocr_confidence: float = 0.6,
        overlay_mode: str = "banner",
        font_size: int = 26,
        font_color: str = "#FFFFFF",
        background_color: str = "#404040",
        hotkeys: dict | None = None,
        config_path: str | None = None,
    ):
        self.window_title = window_title
        self.refresh_rate = refresh_rate
        self.ocr_confidence = ocr_confidence
        self.overlay_mode = overlay_mode  # "banner" or "inplace"
        self.font_size = font_size
        self.font_color = font_color
        self.background_color = background_color
        self.hotkeys = hotkeys if hotkeys is not None else self.DEFAULT_HOTKEYS.copy()
        self.config_path = config_path

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
            # Resolve to absolute path for clear display
            config_path = str(Path(config_path).resolve())
            with open(config_path, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}

            # Load hotkeys with defaults for any missing keys
            hotkeys_data = data.get("hotkeys", {})
            hotkeys = cls.DEFAULT_HOTKEYS.copy()
            hotkeys.update(hotkeys_data)

            return cls(
                window_title=data.get("window_title", cls.DEFAULT_WINDOW_TITLE),
                refresh_rate=float(data.get("refresh_rate", 0.5)),
                ocr_confidence=float(data.get("ocr_confidence", 0.6)),
                overlay_mode=data.get("overlay_mode", "banner"),
                font_size=int(data.get("font_size", 26)),
                font_color=data.get("font_color", "#FFFFFF"),
                background_color=data.get("background_color", "#404040"),
                hotkeys=hotkeys,
                config_path=config_path,
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
window_title: "Snes9x"

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
font_size: 26
font_color: "#FFFFFF"
background_color: "#404040"

# Hotkeys - single characters or special key names
# Special keys: f1-f12, escape, space, enter, tab, backspace, delete,
#               insert, home, end, page_up, page_down, up, down, left, right
hotkeys:
  toggle_overlay: "space"
  switch_mode: "m"
  increase_font: "="
  decrease_font: "-"
  quit: "q"
"""
        with open(config_path, "w", encoding="utf-8") as f:
            f.write(default_config)

        logger.info("created default config", path=str(config_path))

    def hex_to_rgb(self, hex_color: str) -> tuple[int, int, int]:
        """Convert hex color string to RGB tuple."""
        hex_color = hex_color.lstrip("#")
        if len(hex_color) != 6 or not all(c in "0123456789abcdefABCDEF" for c in hex_color):
            logger.warning("invalid hex color, using white", color=hex_color)
            return (255, 255, 255)
        return tuple(int(hex_color[i : i + 2], 16) for i in (0, 2, 4))

    def save(self, config_path: str | None = None) -> None:
        """Save configuration to YAML file.

        Args:
            config_path: Path to save to. If None, uses the path the config was loaded from,
                        or creates in ~/.interpreter/config.yml
        """
        if config_path is None:
            config_path = self.config_path

        if config_path is None:
            config_dir = Path.home() / ".interpreter"
            config_dir.mkdir(parents=True, exist_ok=True)
            config_path = str(config_dir / "config.yml")

        # Explicitly convert to basic types to avoid Python-specific YAML tags
        data = {
            "window_title": str(self.window_title) if self.window_title else "",
            "refresh_rate": float(self.refresh_rate),
            "ocr_confidence": float(self.ocr_confidence),
            "overlay_mode": str(self.overlay_mode),
            "font_size": int(self.font_size),
            "font_color": str(self.font_color),
            "background_color": str(self.background_color),
            "hotkeys": {str(k): str(v) for k, v in self.hotkeys.items()},
        }

        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True)

        self.config_path = config_path
        logger.info("config saved", path=config_path)
