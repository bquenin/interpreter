"""Logging configuration using structlog.

Provides zerolog-style output with aligned 3-letter level names:
    12:30:45 INF window found title=RetroArch
    12:30:46 DBG ocr complete time_ms=45
    12:30:47 WRN cache miss key=foo
    12:30:48 ERR connection failed err=timeout
"""

import logging
import sys
from datetime import datetime

import structlog

# 3-letter level names for alignment (like zerolog)
LEVEL_NAMES = {
    "debug": "DBG",
    "info": "INF",
    "warning": "WRN",
    "error": "ERR",
    "critical": "CRT",
}

# Module-level debug flag (set by configure())
_debug_enabled = False


def _level_to_3letter(logger, method_name, event_dict):
    """Convert log level to 3-letter abbreviation."""
    level = event_dict.get("level", method_name)
    event_dict["level"] = LEVEL_NAMES.get(level, level.upper()[:3])
    return event_dict


def _format_timestamp(logger, method_name, event_dict):
    """Add timestamp in HH:MM:SS format."""
    event_dict["timestamp"] = datetime.now().strftime("%H:%M:%S")
    return event_dict


def _render_kv_pairs(logger, method_name, event_dict):
    """Render event dict as 'timestamp LEVEL message key=value ...' string."""
    timestamp = event_dict.pop("timestamp", "")
    level = event_dict.pop("level", "???")
    event = event_dict.pop("event", "")

    # Build key=value pairs for remaining fields
    kv_parts = []
    for key, value in event_dict.items():
        if key.startswith("_"):
            continue
        if isinstance(value, str) and " " in value:
            kv_parts.append(f'{key}="{value}"')
        else:
            kv_parts.append(f"{key}={value}")

    kv_str = " ".join(kv_parts)
    if kv_str:
        return f"{timestamp} {level} {event} {kv_str}"
    return f"{timestamp} {level} {event}"


def configure(level: str = "INFO", debug: bool = False) -> None:
    """Configure structlog for console output.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR).
        debug: If True, sets level to DEBUG.
    """
    global _debug_enabled
    if debug:
        level = "DEBUG"
    _debug_enabled = level.upper() == "DEBUG"

    # Configure structlog processors
    processors = [
        structlog.stdlib.add_log_level,
        _format_timestamp,
        _level_to_3letter,
        _render_kv_pairs,
    ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level.upper(), logging.INFO)),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.BoundLogger:
    """Get a logger instance.

    Args:
        name: Optional logger name (for context).

    Returns:
        A structlog BoundLogger instance.
    """
    logger = structlog.get_logger()
    if name:
        return logger.bind(logger=name)
    return logger


def is_debug_enabled() -> bool:
    """Check if debug logging is enabled."""
    return _debug_enabled
