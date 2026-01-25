"""Configuration management for Interpreter."""

import os
from enum import Enum
from pathlib import Path

import yaml

from . import log


class OverlayMode(str, Enum):
    """Overlay display mode."""

    BANNER = "banner"
    INPLACE = "inplace"


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

    # Default OCR confidence threshold
    DEFAULT_OCR_CONFIDENCE = 0.6

    def __init__(
        self,
        window_title: str = "Snes9x",
        ocr_confidence: float = 0.6,
        overlay_mode: OverlayMode = OverlayMode.BANNER,
        font_family: str | None = None,
        font_size: int = 26,
        font_color: str = "#FFFFFF",
        background_color: str = "#404040",
        background_opacity: float = 0.8,
        hotkeys: dict | None = None,
        config_path: str | None = None,
        banner_x: int | None = None,
        banner_y: int | None = None,
        exclusion_zones: dict | None = None,
        ocr_confidence_per_window: dict | None = None,
    ):
        self.window_title = window_title
        self.ocr_confidence = ocr_confidence  # Global default
        self.overlay_mode = overlay_mode
        self.font_family = font_family  # None = system default
        self.font_size = font_size
        self.font_color = font_color
        self.background_color = background_color
        self.background_opacity = background_opacity
        self.hotkeys = hotkeys if hotkeys is not None else self.DEFAULT_HOTKEYS.copy()
        self.config_path = config_path
        self.banner_x = banner_x
        self.banner_y = banner_y
        # Exclusion zones per window title: {"window_title": [{"x": 0.0, "y": 0.0, "width": 0.1, "height": 0.1}, ...]}
        self.exclusion_zones = exclusion_zones if exclusion_zones is not None else {}
        # Per-window OCR confidence: {"window_title": 0.55, ...}
        self.ocr_confidence_per_window = ocr_confidence_per_window if ocr_confidence_per_window is not None else {}

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

            # Parse overlay_mode from string to enum
            mode_str = data.get("overlay_mode", "banner")
            try:
                overlay_mode = OverlayMode(mode_str)
            except ValueError:
                logger.warning("invalid overlay_mode, using banner", mode=mode_str)
                overlay_mode = OverlayMode.BANNER

            return cls(
                window_title=data.get("window_title", cls.DEFAULT_WINDOW_TITLE),
                ocr_confidence=float(data.get("ocr_confidence", cls.DEFAULT_OCR_CONFIDENCE)),
                overlay_mode=overlay_mode,
                font_family=data.get("font_family"),  # None = system default
                font_size=int(data.get("font_size", 26)),
                font_color=data.get("font_color", "#FFFFFF"),
                background_color=data.get("background_color", "#404040"),
                background_opacity=float(data.get("background_opacity", 0.8)),
                hotkeys=hotkeys,
                config_path=config_path,
                banner_x=data.get("banner_x"),
                banner_y=data.get("banner_y"),
                exclusion_zones=data.get("exclusion_zones", {}),
                ocr_confidence_per_window=data.get("ocr_confidence_per_window", {}),
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

# OCR confidence threshold (0.0-1.0)
# Filters out low-confidence text detection
ocr_confidence: 0.6

# Overlay mode: "banner" (subtitle bar) or "inplace" (over game text)
overlay_mode: banner

# Subtitle appearance
font_size: 26
font_color: "#FFFFFF"
background_color: "#404040"
background_opacity: 0.8  # 0.0 (transparent) to 1.0 (opaque)

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

    def get_exclusion_zones(self, window_title: str) -> list[dict]:
        """Get exclusion zones for a specific window title.

        Args:
            window_title: The window title to get zones for.

        Returns:
            List of zone dicts with x, y, width, height as floats (0.0-1.0).
        """
        return self.exclusion_zones.get(window_title, [])

    def set_exclusion_zones(self, window_title: str, zones: list[dict]) -> None:
        """Set exclusion zones for a specific window title.

        Args:
            window_title: The window title to set zones for.
            zones: List of zone dicts with x, y, width, height as floats (0.0-1.0).
        """
        if zones:
            self.exclusion_zones[window_title] = zones
        elif window_title in self.exclusion_zones:
            del self.exclusion_zones[window_title]

    def get_ocr_confidence(self, window_title: str | None = None) -> float:
        """Get OCR confidence for a specific window, or global default.

        Args:
            window_title: The window title to get confidence for. If None, returns global default.

        Returns:
            OCR confidence threshold (0.0-1.0).
        """
        if window_title and window_title in self.ocr_confidence_per_window:
            return self.ocr_confidence_per_window[window_title]
        return self.ocr_confidence

    def set_ocr_confidence(self, window_title: str, confidence: float) -> None:
        """Set OCR confidence for a specific window.

        Args:
            window_title: The window title to set confidence for.
            confidence: OCR confidence threshold (0.0-1.0).
        """
        # Only store if different from global default
        if abs(confidence - self.ocr_confidence) < 0.001:
            # Same as global, remove per-window override
            if window_title in self.ocr_confidence_per_window:
                del self.ocr_confidence_per_window[window_title]
        else:
            self.ocr_confidence_per_window[window_title] = confidence

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
            "ocr_confidence": float(self.ocr_confidence),
            "overlay_mode": self.overlay_mode.value,
            "font_size": int(self.font_size),
            "font_color": str(self.font_color),
            "background_color": str(self.background_color),
            "background_opacity": float(self.background_opacity),
            "hotkeys": {str(k): str(v) for k, v in self.hotkeys.items()},
        }
        # Only save font_family if user has chosen one (None = system default)
        if self.font_family is not None:
            data["font_family"] = str(self.font_family)
        # Only save banner position if it was set (user has moved the banner)
        if self.banner_x is not None:
            data["banner_x"] = int(self.banner_x)
        if self.banner_y is not None:
            data["banner_y"] = int(self.banner_y)
        # Save exclusion zones if any are defined
        # Convert keys to plain strings to avoid Python-specific YAML tags
        if self.exclusion_zones:
            data["exclusion_zones"] = {
                str(k): [
                    {str(zk): float(zv) for zk, zv in zone.items()}
                    for zone in zones
                ]
                for k, zones in self.exclusion_zones.items()
            }
        # Save per-window OCR confidence if any are defined
        if self.ocr_confidence_per_window:
            data["ocr_confidence_per_window"] = {
                str(k): float(v) for k, v in self.ocr_confidence_per_window.items()
            }

        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True)

        self.config_path = config_path
        logger.info("config saved", path=config_path)
