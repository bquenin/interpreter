"""OCR backend that talks to an external owocr process over a websocket.

owocr (https://github.com/AuroraWright/owocr) wraps many OCR engines (Google Lens,
Bing, OneOCR, Apple Live Text, MeikiOCR, Manga OCR, ...) behind one JSON result
format. Users install and run it themselves; the application only sends frames
and reads back text lines with bounding boxes.

Protocol (owocr 1.26, "read_from=websocket, write_to=websocket, output_format=json"):
- The client sends one BINARY frame holding an encoded image. A text frame crashes
  owocr, so this module only ever sends ``bytes``.
- owocr immediately answers with the text ``"True"`` (queued) or ``"False"`` (paused).
- The result follows as one JSON text frame, broadcast to every connected client,
  in submission order. There is no request id. When the engine fails owocr sends
  nothing at all, so every request has its own deadline.
- Bounding boxes are normalized (0..1) center/size floats relative to the sent image.
"""

import io
import json
import time

import numpy as np
from numpy.typing import NDArray
from websockets.exceptions import ConnectionClosed, InvalidHandshake, InvalidURI
from websockets.sync.client import connect

from . import log
from .capture.convert import bgra_to_rgb_pil
from .config import OwocrSettings
from .models import ModelLoadError
from .ocr import DEFAULT_CONFIDENCE_THRESHOLD, OCRResult

logger = log.get_logger()

# owocr's default websocket port. Prefer 127.0.0.1 over localhost (see llm_translate).
DEFAULT_URL = "ws://127.0.0.1:7331"

# How owocr must be started to act as a pure OCR server for Interpreter:
# websocket in and out, JSON with coordinates, one engine, no tray icon, no text
# reordering (-rt), no furigana filter (-f, it silently drops lines), never auto-pause (-a).
SERVER_COMMAND = "owocr -r websocket -w websocket -of json -e <engine> -el <engine> -t False -rt False -f False -a 0"

# Blank image used by load() and the Test button: proves the round trip without needing fonts.
PROBE_SIZE = 64

# Lossless but fast: pixel fonts must survive, and a 1080p frame encodes in tens of ms.
PNG_COMPRESS_LEVEL = 1

ACK_QUEUED = "True"
ACK_DROPPED = "False"


class OwocrOCRError(Exception):
    """Raised when a frame cannot be processed after the backend was loaded."""


def normalize_url(url: str) -> str:
    """Normalize a user-entered server address to a ws:// or wss:// URL."""
    url = (url or "").strip().rstrip("/")
    if not url:
        return DEFAULT_URL
    for http_scheme, ws_scheme in (("https://", "wss://"), ("http://", "ws://")):
        if url.lower().startswith(http_scheme):
            return ws_scheme + url[len(http_scheme) :]
    if "://" not in url:
        return "ws://" + url
    return url


def encode_png(frame: NDArray[np.uint8]) -> bytes:
    """Encode a BGRA frame as PNG bytes for the websocket."""
    buffer = io.BytesIO()
    bgra_to_rgb_pil(frame).save(buffer, format="PNG", compress_level=PNG_COMPRESS_LEVEL)
    return buffer.getvalue()


def probe_image() -> NDArray[np.uint8]:
    """A white square: cloud engines answer it with an empty result instead of an error."""
    return np.full((PROBE_SIZE, PROBE_SIZE, 4), 255, dtype=np.uint8)


def _bbox_to_pixels(bbox: object, width: int, height: int) -> dict | None:
    """Convert an owocr normalized center/size box into the app's pixel {x, y, width, height}."""
    if not isinstance(bbox, dict):
        return None
    try:
        cx = float(bbox["center_x"]) * width
        cy = float(bbox["center_y"]) * height
        w = float(bbox["width"]) * width
        h = float(bbox["height"]) * height
    except (KeyError, TypeError, ValueError):
        return None
    x1 = min(max(round(cx - w / 2), 0), width)
    y1 = min(max(round(cy - h / 2), 0), height)
    x2 = min(max(round(cx + w / 2), 0), width)
    y2 = min(max(round(cy + h / 2), 0), height)
    if x2 <= x1 or y2 <= y1:
        return None
    return {"x": int(x1), "y": int(y1), "width": int(x2 - x1), "height": int(y2 - y1)}


def _line_text(line: dict) -> str:
    """The line's text, or the words joined with their separators when the engine gave none."""
    text = line.get("text")
    if not text:
        words = line.get("words")
        if isinstance(words, list):
            text = "".join(
                str(word.get("text") or "") + str(word.get("separator") or "")
                for word in words
                if isinstance(word, dict)
            )
    return " ".join(str(text or "").split())


def parse_response(data: object, width: int, height: int) -> list[OCRResult]:
    """Turn an owocr JSON result into text regions, one per line, in owocr's order.

    owocr already orders lines for reading (for vertical text: one line per column,
    right to left), so the order is kept. A malformed payload yields no regions
    rather than an exception.
    """
    if not isinstance(data, dict) or not isinstance(data.get("paragraphs"), list):
        return []
    regions = []
    for paragraph in data["paragraphs"]:
        if not isinstance(paragraph, dict):
            continue
        paragraph_bbox = paragraph.get("bounding_box")
        lines = paragraph.get("lines")
        if not isinstance(lines, list):
            continue
        for line in lines:
            if not isinstance(line, dict):
                continue
            text = _line_text(line)
            if not text:
                continue
            bbox = _bbox_to_pixels(line.get("bounding_box"), width, height)
            if bbox is None:
                bbox = _bbox_to_pixels(paragraph_bbox, width, height)
            regions.append(OCRResult(text=text, bbox=bbox))
    return regions


def describe_connection_error(error: Exception, settings: OwocrSettings) -> str:
    """Turn a websocket failure into a message a user can act on."""
    url = normalize_url(settings.url)
    if isinstance(error, OwocrOCRError):
        return str(error)
    if isinstance(error, InvalidURI):
        return f"Invalid owocr URL '{url}'. Use the form ws://host:port."
    if isinstance(error, InvalidHandshake):
        return f"{url} is not an owocr websocket server."
    if isinstance(error, ConnectionClosed):
        return f"owocr at {url} closed the connection. Restart it and check its console."
    if isinstance(error, TimeoutError):
        return f"owocr at {url} did not answer within {settings.timeout:.0f}s. Check its console for an engine error."
    if isinstance(error, OSError):
        return f"Cannot reach owocr at {url}. Start it with: {SERVER_COMMAND}"
    return f"owocr request failed: {error}"


class OwocrOCR:
    """OCR engine backed by an owocr websocket server.

    Satisfies the same interface as ocr.OCR so the worker can use either. One request
    is in flight at a time (the worker thread is the only caller); after any failure
    the connection is dropped so the next frame starts from a clean state instead of
    reading a late reply meant for an earlier frame.
    """

    def __init__(self, settings: OwocrSettings):
        if not settings.timeout > 0:
            raise ModelLoadError(f"owocr timeout must be a positive number of seconds, got {settings.timeout!r}.")
        self._settings = settings
        self._url = normalize_url(settings.url)
        self._conn = None
        self._loaded = False
        # owocr returns no confidence scores; stored only to satisfy the engine interface
        self._confidence_threshold = DEFAULT_CONFIDENCE_THRESHOLD

    @property
    def name(self) -> str:
        """Short engine name for the Status panel."""
        return "owocr"

    @property
    def confidence_threshold(self) -> float:
        return self._confidence_threshold

    @confidence_threshold.setter
    def confidence_threshold(self, value: float) -> None:
        self._confidence_threshold = value

    def is_loaded(self) -> bool:
        return self._loaded

    def close(self) -> None:
        """Drop the connection (and its reader thread); the next frame reconnects."""
        conn, self._conn = self._conn, None
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    def load(self) -> None:
        """Connect and run one blank-image round trip.

        Raises:
            ModelLoadError: If the server is unreachable, paused, or not speaking JSON.
        """
        if self._loaded:
            return
        logger.info("connecting to owocr", url=self._url)
        start = time.perf_counter()
        try:
            self._connect()
            self._request(encode_png(probe_image()), PROBE_SIZE, PROBE_SIZE)
        except Exception as e:
            self.close()
            raise ModelLoadError(describe_connection_error(e, self._settings)) from e
        self._loaded = True
        logger.info("owocr ready", url=self._url, probe_ms=int((time.perf_counter() - start) * 1000))

    def extract_text_regions(self, image: NDArray[np.uint8]) -> list[OCRResult]:
        """Send the frame to owocr and return its lines as regions.

        Raises:
            OwocrOCRError: If the request fails; the connection is dropped for a clean retry.
        """
        if not self._loaded:
            self.load()
        height, width = image.shape[:2]
        try:
            if self._conn is None:
                self._connect()
            data = self._request(encode_png(image), width, height)
        except Exception as e:
            self.close()
            raise OwocrOCRError(describe_connection_error(e, self._settings)) from e
        return parse_response(data, width, height)

    def _connect(self) -> None:
        # No proxy: a system HTTP proxy must never sit between us and a local server.
        # No max_size: a busy screen can produce a large JSON result.
        self._conn = connect(self._url, open_timeout=self._settings.timeout, close_timeout=1, max_size=None, proxy=None)

    def _request(self, png: bytes, width: int, height: int) -> dict:
        """Send one image and wait for its JSON result.

        Acks are consumed on the way; a JSON result whose image size does not match
        the frame just sent is a late reply to an earlier request and is skipped.
        """
        assert isinstance(png, (bytes, bytearray))  # a str would be a text frame and crash owocr
        self._conn.send(png)
        deadline = time.perf_counter() + self._settings.timeout
        while True:
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                raise TimeoutError()
            message = self._conn.recv(timeout=remaining)
            if isinstance(message, (bytes, bytearray)):
                continue
            if message == ACK_QUEUED:
                continue
            if message == ACK_DROPPED:
                raise OwocrOCRError("owocr dropped the frame because it is paused. Unpause it, or start it with -a 0.")
            try:
                data = json.loads(message)
            except ValueError:
                raise OwocrOCRError("owocr replied with plain text instead of JSON. Start it with -of json.") from None
            if not isinstance(data, dict) or "paragraphs" not in data:
                continue
            properties = data.get("image_properties")
            if isinstance(properties, dict):
                size = (properties.get("width"), properties.get("height"))
                if None not in size and size != (width, height):
                    logger.debug("skipping stale owocr result", got=size, expected=(width, height))
                    continue
            return data


def check_endpoint(settings: OwocrSettings) -> int:
    """Connect and run the probe round trip, for the Settings "Test" button.

    Returns:
        Round-trip milliseconds for the probe image.

    Raises:
        ModelLoadError: If the server cannot be used.
    """
    ocr = OwocrOCR(settings)
    start = time.perf_counter()
    try:
        ocr.load()
    finally:
        ocr.close()
    return int((time.perf_counter() - start) * 1000)
