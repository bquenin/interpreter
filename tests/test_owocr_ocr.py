"""Tests for the owocr websocket OCR backend (no network access)."""

import io
import json
from collections import deque

import numpy as np
import pytest
from PIL import Image
from websockets.exceptions import ConnectionClosedError, InvalidHandshake, InvalidURI

from interpreter.config import Config, OCRBackend, OwocrSettings
from interpreter.models import ModelLoadError
from interpreter.ocr import OCR, OCRResult, create_ocr
from interpreter.owocr_ocr import (
    DEFAULT_URL,
    PROBE_SIZE,
    SERVER_COMMAND,
    TAG_ROWS,
    OwocrOCR,
    OwocrOCRError,
    check_endpoint,
    describe_connection_error,
    encode_png,
    is_loopback_url,
    normalize_url,
    parse_response,
    remote_warning,
    tag_frame,
)


class _FakeConn:
    """Stand-in for websockets.sync.client.ClientConnection.

    ``replies`` holds what recv() returns in order: a message, an exception instance
    (raised instead), or a callable taking the connection (so a reply can echo the
    size of the image just sent, as owocr does). When it runs out, recv() raises
    TimeoutError like the real client does on its deadline.
    """

    def __init__(self, replies=()):
        self.replies = deque(replies)
        self.sent = []
        self.closed = False

    def send(self, message):
        self.sent.append(message)

    def recv(self, timeout=None):
        if not self.replies:
            raise TimeoutError()
        reply = self.replies.popleft()
        if isinstance(reply, Exception):
            raise reply
        if callable(reply):
            return reply(self)
        return reply

    def close(self):
        self.closed = True

    def sent_size(self, index=-1) -> tuple[int, int]:
        """(width, height) of a PNG this connection was given, as owocr would echo it."""
        return Image.open(io.BytesIO(self.sent[index])).size


def _bbox(cx, cy, w, h):
    return {"center_x": cx, "center_y": cy, "width": w, "height": h, "rotation_z": None}


def _line(text, cx=0.5, cy=0.5, w=0.5, h=0.2, words=None, bbox=True):
    return {
        "bounding_box": _bbox(cx, cy, w, h) if bbox else None,
        "words": words if words is not None else [{"text": text, "bounding_box": _bbox(cx, cy, w, h)}],
        "text": text,
        "writing_direction": None,
    }


def _reply(lines=(), width=PROBE_SIZE, height=PROBE_SIZE, paragraph_bbox=None) -> str:
    """One owocr JSON result frame holding a single paragraph."""
    paragraphs = [{"bounding_box": paragraph_bbox, "lines": list(lines), "writing_direction": None}] if lines else []
    return json.dumps({"image_properties": {"width": width, "height": height}, "paragraphs": paragraphs})


def _result(lines=(), index=-1):
    """A reply for the image most recently sent (or the one at ``index``), like owocr's."""
    return lambda conn: _reply(lines, *conn.sent_size(index))


def _frame(width=200, height=100) -> np.ndarray:
    return np.zeros((height, width, 4), dtype=np.uint8)


class _ConnectionQueue(deque):
    """Fake connections handed out by connect(), plus a record of every connect() call."""

    def __init__(self):
        super().__init__()
        self.calls = []


@pytest.fixture
def connections(monkeypatch):
    """Patch connect() to hand out queued fake connections; refuses when the queue is empty."""
    queue = _ConnectionQueue()

    def connect(url, **kwargs):
        queue.calls.append((url, kwargs))
        if not queue:
            raise ConnectionRefusedError("refused")
        conn = queue.popleft()
        if isinstance(conn, Exception):
            raise conn
        return conn

    monkeypatch.setattr("interpreter.owocr_ocr.connect", connect)
    return queue


def _loaded_ocr(connections, conn: _FakeConn) -> OwocrOCR:
    connections.append(conn)
    ocr = OwocrOCR(OwocrSettings(timeout=1.0))
    ocr.load()
    return ocr


class TestNormalizeUrl:
    def test_empty_falls_back_to_default(self):
        assert normalize_url("") == DEFAULT_URL
        assert normalize_url("   ") == DEFAULT_URL

    def test_http_schemes_become_websocket_schemes(self):
        assert normalize_url("http://127.0.0.1:7331/") == "ws://127.0.0.1:7331"
        assert normalize_url("HTTPS://host:1/") == "wss://host:1"

    def test_bare_host_port_gets_ws_scheme(self):
        assert normalize_url("192.168.1.5:7331") == "ws://192.168.1.5:7331"

    def test_ws_url_is_kept(self):
        assert normalize_url("wss://host:7331/") == "wss://host:7331"


class TestEncodePng:
    def test_produces_png_of_the_frame_size_in_rgb(self):
        frame = _frame(30, 20)
        frame[:, :, 0] = 255  # blue channel in BGRA
        data = encode_png(frame)
        assert data[:8] == b"\x89PNG\r\n\x1a\n"
        image = Image.open(io.BytesIO(data))
        assert image.size == (30, 20)
        assert image.mode == "RGB"
        assert image.getpixel((0, 0)) == (0, 0, 255)


class TestTagFrame:
    def test_appends_black_rows_and_keeps_the_frame(self):
        frame = np.full((20, 30, 4), 200, dtype=np.uint8)
        tagged = tag_frame(frame, 5)
        assert tagged.shape == (25, 30, 4)
        assert (tagged[:20] == 200).all()
        assert (tagged[20:] == 0).all()


class TestRemoteWarning:
    @pytest.mark.parametrize("url", ["ws://127.0.0.1:7331", "localhost:7331", "ws://[::1]:7331", "wss://lan-box:7331"])
    def test_local_or_encrypted_gives_no_warning(self, url):
        assert remote_warning(url) is None
        assert is_loopback_url(url) or url.startswith("wss://")

    def test_plain_remote_host_is_flagged(self):
        warning = remote_warning("192.168.1.20:7331")
        assert "unencrypted to 192.168.1.20" in warning
        assert "wss://" in warning


class TestParseResponse:
    def test_normalized_boxes_become_frame_pixels(self):
        data = json.loads(_reply([_line("こんにちは", 0.5, 0.5, 0.5, 0.2)], 200, 100))
        assert parse_response(data, 200, 100) == [
            OCRResult("こんにちは", {"x": 50, "y": 40, "width": 100, "height": 20}),
        ]

    def test_boxes_are_clamped_to_the_image(self):
        data = json.loads(_reply([_line("a", 0.0, 0.0, 0.5, 0.5)], 100, 100))
        assert parse_response(data, 100, 100)[0].bbox == {"x": 0, "y": 0, "width": 25, "height": 25}

    def test_missing_text_is_rebuilt_from_words_and_separators(self):
        words = [{"text": "Hello", "separator": " "}, {"text": "world", "separator": None}]
        data = json.loads(_reply([_line(None, words=words)]))
        assert parse_response(data, 64, 64)[0].text == "Hello world"

    def test_whitespace_is_collapsed_and_blank_lines_dropped(self):
        data = json.loads(_reply([_line("  a \n b "), _line("   "), _line(None, words=[])]))
        assert [r.text for r in parse_response(data, 64, 64)] == ["a b"]

    def test_empty_paragraphs_give_no_regions(self):
        assert parse_response(json.loads(_reply()), 64, 64) == []

    def test_zero_area_box_becomes_none(self):
        data = json.loads(_reply([_line("x", 0.5, 0.5, 0.0, 0.2)]))
        assert parse_response(data, 64, 64) == [OCRResult("x", None)]

    def test_line_without_box_falls_back_to_paragraph_box(self):
        data = json.loads(_reply([_line("x", bbox=False)], 100, 100, paragraph_bbox=_bbox(0.5, 0.5, 1.0, 1.0)))
        assert parse_response(data, 100, 100)[0].bbox == {"x": 0, "y": 0, "width": 100, "height": 100}

    def test_server_order_is_kept_for_vertical_columns(self):
        # owocr emits vertical columns right to left, already in reading order
        data = json.loads(_reply([_line("右", 0.8, 0.5, 0.1, 0.8), _line("左", 0.2, 0.5, 0.1, 0.8)]))
        assert [r.text for r in parse_response(data, 64, 64)] == ["右", "左"]

    @pytest.mark.parametrize("payload", [None, "text", [], {}, {"paragraphs": None}, {"paragraphs": [None, 1]}])
    def test_malformed_payloads_give_no_regions(self, payload):
        assert parse_response(payload, 64, 64) == []


class TestOwocrOCR:
    def test_name_and_inert_confidence(self):
        ocr = OwocrOCR(OwocrSettings())
        assert ocr.name == "owocr"
        ocr.confidence_threshold = 0.9
        assert ocr.confidence_threshold == 0.9
        assert not ocr.is_loaded()

    def test_non_positive_timeout_is_rejected(self):
        with pytest.raises(ModelLoadError, match="timeout"):
            OwocrOCR(OwocrSettings(timeout=0))

    def test_load_sends_one_probe_and_only_binary_frames(self, connections):
        conn = _FakeConn(["True", _result()])
        ocr = _loaded_ocr(connections, conn)
        assert ocr.is_loaded()
        assert len(conn.sent) == 1
        assert all(isinstance(item, bytes) for item in conn.sent)  # a text frame would crash owocr
        assert conn.sent[0][:8] == b"\x89PNG\r\n\x1a\n"
        assert connections.calls[0][0] == DEFAULT_URL
        assert connections.calls[0][1]["proxy"] is None

    def test_load_failure_is_a_model_load_error_with_the_server_command(self, connections):
        with pytest.raises(ModelLoadError, match=SERVER_COMMAND.split()[0]):
            OwocrOCR(OwocrSettings(timeout=1.0)).load()

    def test_load_without_reply_times_out(self, connections):
        conn = _FakeConn(["True"])
        connections.append(conn)
        with pytest.raises(ModelLoadError, match="did not answer within 1s"):
            OwocrOCR(OwocrSettings(timeout=1.0)).load()
        assert conn.closed

    def test_extract_returns_regions_in_frame_pixels(self, connections):
        conn = _FakeConn(["True", _result(), "True", _result([_line("やあ", 0.5, 0.25, 0.5, 0.1)])])
        ocr = _loaded_ocr(connections, conn)
        regions = ocr.extract_text_regions(_frame(200, 100))
        # The frame was sent with 1 + (2 % TAG_ROWS) = 3 tag rows, so the image is 200x103
        assert conn.sent_size() == (200, 100 + 1 + 2 % TAG_ROWS)
        assert regions == [OCRResult("やあ", {"x": 50, "y": 21, "width": 100, "height": 10})]
        assert len(conn.sent) == 2 and all(isinstance(item, bytes) for item in conn.sent)

    def test_consecutive_frames_carry_different_size_tags(self, connections):
        conn = _FakeConn(["True", _result()] + ["True", _result()] * TAG_ROWS)
        ocr = _loaded_ocr(connections, conn)
        for _ in range(TAG_ROWS):
            ocr.extract_text_regions(_frame(200, 100))
        heights = [conn.sent_size(i)[1] for i in range(1, TAG_ROWS + 1)]
        assert len(set(heights)) == TAG_ROWS  # no two frames in a cycle look alike
        assert all(100 < h <= 100 + TAG_ROWS for h in heights)

    def test_stale_result_for_the_previous_same_sized_frame_is_skipped(self, connections):
        """After a timeout, owocr still finishes the old frame and broadcasts it (Greptile P1)."""
        first = _FakeConn(["True", _result(), "True"])  # frame 1: no result within the deadline
        ocr = _loaded_ocr(connections, first)
        with pytest.raises(OwocrOCRError, match="did not answer"):
            ocr.extract_text_regions(_frame(200, 100))

        # The reconnected client first receives the late result for frame 1 (same window size),
        # then the real one for frame 2. Only the latter carries frame 2's tag height.
        late = lambda conn: _reply([_line("old")], *first.sent_size(1))  # noqa: E731
        second = _FakeConn(["True", late, _result([_line("new")])])
        connections.append(second)
        assert [r.text for r in ocr.extract_text_regions(_frame(200, 100))] == ["new"]
        assert first.sent_size(1)[0] == second.sent_size()[0]  # same width: only the tag differs

    def test_binary_frames_and_other_json_are_ignored(self, connections):
        conn = _FakeConn(["True", _result(), b"\x00", json.dumps({"status": "ok"}), _result([_line("x")])])
        ocr = _loaded_ocr(connections, conn)
        assert [r.text for r in ocr.extract_text_regions(_frame(200, 100))] == ["x"]

    def test_paused_server_is_reported(self, connections):
        conn = _FakeConn(["True", _result(), "False"])
        ocr = _loaded_ocr(connections, conn)
        with pytest.raises(OwocrOCRError, match="paused"):
            ocr.extract_text_regions(_frame())

    def test_plain_text_output_is_reported_as_misconfiguration(self, connections):
        conn = _FakeConn(["True", _result(), "True", "こんにちは"])
        ocr = _loaded_ocr(connections, conn)
        with pytest.raises(OwocrOCRError, match="-of json"):
            ocr.extract_text_regions(_frame())

    def test_timeout_drops_the_connection_and_the_next_frame_reconnects(self, connections):
        first = _FakeConn(["True", _result(), "True"])  # no result for the frame
        ocr = _loaded_ocr(connections, first)
        with pytest.raises(OwocrOCRError, match="did not answer"):
            ocr.extract_text_regions(_frame())
        assert first.closed and ocr._conn is None

        second = _FakeConn(["True", _result([_line("x")])])
        connections.append(second)
        assert [r.text for r in ocr.extract_text_regions(_frame(200, 100))] == ["x"]
        assert len(connections.calls) == 2
        assert ocr.is_loaded()

    def test_closed_connection_is_reported_and_dropped(self, connections):
        conn = _FakeConn(["True", _result(), ConnectionClosedError(None, None)])
        ocr = _loaded_ocr(connections, conn)
        with pytest.raises(OwocrOCRError, match="closed the connection"):
            ocr.extract_text_regions(_frame())
        assert ocr._conn is None

    def test_reconnect_failure_is_reported(self, connections):
        conn = _FakeConn(["True", _result()])
        ocr = _loaded_ocr(connections, conn)
        ocr.close()
        with pytest.raises(OwocrOCRError, match="Cannot reach owocr"):
            ocr.extract_text_regions(_frame())

    def test_close_is_idempotent(self, connections):
        conn = _FakeConn(["True", _result()])
        ocr = _loaded_ocr(connections, conn)
        ocr.close()
        ocr.close()
        assert conn.closed


class TestDescribeConnectionError:
    settings = OwocrSettings(url="ws://127.0.0.1:7331", timeout=3.0)

    def test_backend_errors_pass_through(self):
        assert describe_connection_error(OwocrOCRError("paused"), self.settings) == "paused"

    def test_invalid_uri(self):
        assert "Invalid owocr URL" in describe_connection_error(InvalidURI("x", "bad"), self.settings)

    def test_handshake(self):
        assert "not an owocr websocket server" in describe_connection_error(InvalidHandshake(), self.settings)

    def test_closed(self):
        message = describe_connection_error(ConnectionClosedError(None, None), self.settings)
        assert "closed the connection" in message

    def test_timeout_mentions_the_configured_seconds(self):
        assert "within 3s" in describe_connection_error(TimeoutError(), self.settings)

    def test_refused_mentions_the_server_command(self):
        message = describe_connection_error(ConnectionRefusedError(), self.settings)
        assert message.startswith("Cannot reach owocr at ws://127.0.0.1:7331")
        assert SERVER_COMMAND in message

    def test_other(self):
        assert describe_connection_error(RuntimeError("boom"), self.settings) == "owocr request failed: boom"


class TestCheckEndpoint:
    def test_returns_round_trip_ms_and_closes(self, connections):
        conn = _FakeConn(["True", _result()])
        connections.append(conn)
        ms = check_endpoint(OwocrSettings(timeout=1.0))
        assert isinstance(ms, int) and ms >= 0
        assert conn.closed

    def test_failure_raises_model_load_error(self, connections):
        with pytest.raises(ModelLoadError, match="Cannot reach owocr"):
            check_endpoint(OwocrSettings(timeout=1.0))


class TestFactory:
    def test_default_is_meiki(self):
        ocr = create_ocr(Config())
        assert isinstance(ocr, OCR)
        assert ocr.name == "MeikiOCR"

    def test_owocr_backend_uses_its_settings(self):
        config = Config(ocr_backend=OCRBackend.OWOCR, owocr=OwocrSettings(url="host:1"))
        ocr = create_ocr(config)
        assert isinstance(ocr, OwocrOCR)
        assert ocr._url == "ws://host:1"


class TestConfigRoundTrip:
    def test_defaults_do_not_write_owocr_block(self, tmp_path):
        path = tmp_path / "config.yml"
        Config().save(str(path))
        text = path.read_text(encoding="utf-8")
        assert "ocr_backend: meiki" in text
        assert "owocr:" not in text

    def test_owocr_settings_round_trip(self, tmp_path):
        path = tmp_path / "config.yml"
        config = Config(ocr_backend=OCRBackend.OWOCR, owocr=OwocrSettings(url="ws://10.0.0.2:7331", timeout=4.5))
        config.save(str(path))
        loaded = Config.load(str(path))
        assert loaded.ocr_backend == OCRBackend.OWOCR
        assert loaded.owocr == config.owocr

    def test_invalid_backend_falls_back_to_meiki(self, tmp_path):
        path = tmp_path / "config.yml"
        path.write_text("ocr_backend: banana\nowocr:\n  url: ws://h:1\n  unknown: 1\n", encoding="utf-8")
        loaded = Config.load(str(path))
        assert loaded.ocr_backend == OCRBackend.MEIKI
        assert loaded.owocr.url == "ws://h:1"

    def test_missing_keys_use_defaults(self, tmp_path):
        path = tmp_path / "config.yml"
        path.write_text("window_title: x\n", encoding="utf-8")
        loaded = Config.load(str(path))
        assert loaded.ocr_backend == OCRBackend.MEIKI
        assert loaded.owocr == OwocrSettings()

    @pytest.mark.parametrize("yaml_value", ["0", "-5", ".inf", ".nan", "soon"])
    def test_bad_timeout_uses_default(self, tmp_path, yaml_value):
        path = tmp_path / "config.yml"
        path.write_text(f"owocr:\n  timeout: {yaml_value}\n", encoding="utf-8")
        assert Config.load(str(path)).owocr.timeout == 10.0

    def test_url_is_coerced_to_string(self):
        assert OwocrSettings.from_dict({"url": 7331}).url == "7331"
        assert OwocrSettings.from_dict("nonsense") == OwocrSettings()
