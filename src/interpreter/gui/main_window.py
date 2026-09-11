"""Main application window with settings and controls."""

import threading

from PIL import ImageDraw
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont, QImage, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QColorDialog,
    QComboBox,
    QFontDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QKeySequenceEdit,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from .. import log
from ..capture import Capture, WindowCapture, _is_wayland_session
from ..capture.convert import bgra_to_rgb_pil
from ..config import Config, LLMSettings, OCRBackend, OverlayMode, OwocrSettings, TranslationBackend
from ..languages import DEFAULT_SOURCE_LANGUAGE, SOURCE_LANGUAGES
from ..llm_translate import (
    DEFAULT_BASE_URLS,
    DEFAULT_SYSTEM_PROMPT,
    PROVIDER_LABELS,
    PROVIDERS,
    check_endpoint,
    describe_request_error,
    list_models,
    normalize_base_url,
    provider_label,
)
from ..overlay import BannerOverlay, InplaceOverlay
from ..owocr_ocr import DEFAULT_URL as OWOCR_DEFAULT_URL
from ..owocr_ocr import SERVER_COMMAND as OWOCR_SERVER_COMMAND
from ..owocr_ocr import check_endpoint as check_owocr_endpoint
from ..owocr_ocr import normalize_url as normalize_owocr_url
from ..owocr_ocr import remote_warning as owocr_remote_warning
from ..permissions import (
    check_accessibility,
    check_screen_recording,
    is_macos,
    open_accessibility_settings,
    open_screen_recording_settings,
    request_accessibility,
    request_screen_recording,
)
from ..translate import SUGOI_ONLY_JAPANESE, SUGOI_SOURCE_LANGUAGE
from . import keyboard
from .ocr_config import OCRConfigDialog
from .theme import ERROR, OK, set_role
from .workers import ProcessWorker

logger = log.get_logger()

# Font settings
MIN_FONT_SIZE = 8
MAX_FONT_SIZE = 72

# Fixed processing interval (2 FPS)
PROCESS_INTERVAL_MS = 500


class MainWindow(QMainWindow):
    """Main application window."""

    # Signals for thread-safe hotkey handling
    hotkey_pressed = Signal()
    mode_switch_pressed = Signal()

    # Results of background endpoint queries (list of models, or (translation, ms)); str = error
    _llm_models_result = Signal(object)
    _llm_test_result = Signal(object)
    # Result of the owocr Test button (round-trip ms); str = error
    _owocr_test_result = Signal(object)

    def __init__(self, config: Config):
        super().__init__()
        self._config = config

        self.setWindowTitle("Interpreter")

        # State
        self._capturing = False
        self._mode = config.overlay_mode
        self._windows_list: list[dict] = []
        self._paused = False
        self._current_window_title: str = ""  # For exclusion zone lookup
        self._ocr_config_dialog = None  # Reference to open OCR config dialog
        # Wayland session detection (from capture module, uses D-Bus portal check)
        self._is_wayland_session = _is_wayland_session
        self._wayland_portal = None  # WaylandPortalCapture instance (for managing portal session lifecycle)
        self._wayland_selecting = False  # Guard against re-entry during portal flow
        self._fixing_ocr = False  # Track if we're re-downloading OCR model
        self._fixing_translation = False  # Track if we're re-downloading translation model

        # Components - unified capture interface (WindowCapture or WaylandCaptureStream)
        self._capture: Capture | None = None

        # Worker for OCR/translation (uses Python threading internally)
        self._process_worker = self._create_worker()
        self._llm_models_result.connect(self._on_llm_models_listed)
        self._llm_test_result.connect(self._on_llm_test_done)
        self._owocr_test_result.connect(self._on_owocr_test_done)
        # Settings snapshots of the in-flight Refresh / Test requests (stale results are dropped)
        self._llm_refresh_request: LLMSettings | None = None
        self._llm_test_request: LLMSettings | None = None
        self._llm_test_language: str = self._config.source_language
        self._owocr_test_request: OwocrSettings | None = None

        # Overlays
        self._banner_overlay = BannerOverlay(
            font_family=config.font_family,
            font_size=config.font_size,
            font_color=config.font_color,
            background_color=config.background_color,
            background_opacity=config.background_opacity,
        )
        self._inplace_overlay = InplaceOverlay(
            font_family=config.font_family,
            font_size=config.font_size,
            font_color=config.font_color,
            background_color=config.background_color,
            background_opacity=config.background_opacity,
        )

        # Apply saved banner position if available
        if config.banner_x is not None and config.banner_y is not None:
            logger.debug("restoring banner position", x=config.banner_x, y=config.banner_y)
            self._banner_overlay.set_position(config.banner_x, config.banner_y)
            # Ensure banner is visible (handles monitor changes, resolution changes, etc.)
            self._banner_overlay.clamp_to_visible_area()

        # Main processing timer (fixed 2 FPS)
        self._process_timer = QTimer()
        self._process_timer.timeout.connect(self._capture_and_process)
        self._last_frame = None
        self._last_bounds = {}

        self._setup_ui()
        # Auto-size window to fit all widgets, then lock minimum size
        self.adjustSize()
        self.setMinimumSize(self.size())
        self._refresh_windows()
        self._load_models()

    def _create_worker(self) -> ProcessWorker:
        """Create the OCR/translation worker and wire its signals."""
        worker = ProcessWorker(self._config)
        worker.text_ready.connect(self._on_text_ready)
        worker.regions_ready.connect(self._on_regions_ready)
        worker.ocr_results_ready.connect(self._on_ocr_results_ready)
        worker.models_ready.connect(self._on_models_ready)
        worker.models_failed.connect(self._on_models_failed)
        worker.ocr_status.connect(self._on_ocr_status)
        worker.translation_status.connect(self._on_translation_status)
        return worker

    def _setup_ui(self):
        """Set up the main UI."""
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(16, 12, 16, 8)
        layout.setSpacing(12)

        layout.addWidget(self._build_capture_group())
        layout.addWidget(self._build_appearance_group())
        layout.addWidget(self._build_ocr_group())
        layout.addWidget(self._build_translation_group())
        layout.addWidget(self._build_status_group())
        self._setup_hotkeys()

        # Stretch at bottom
        layout.addStretch()

        # Status bar
        self.statusBar().showMessage("Idle")

    def _build_capture_group(self) -> QGroupBox:
        """Window selection, capture controls and the preview."""
        # ==================== CAPTURE ====================
        # Window selection + Preview in one logical group
        capture_group = QGroupBox("Capture")
        capture_layout = QVBoxLayout(capture_group)

        # Window selection row
        window_row = QHBoxLayout()

        # Configure OCR button (shared by both Wayland and X11)
        self._ocr_config_btn = QPushButton("Configure OCR")
        self._ocr_config_btn.setEnabled(False)  # Disabled until capturing
        self._ocr_config_btn.clicked.connect(self._open_ocr_config)

        if self._is_wayland_session:
            # Wayland: single toggle button for capture
            self._select_window_btn = QPushButton("Start Capture")
            self._select_window_btn.setProperty("primary", True)
            self._select_window_btn.setEnabled(False)  # Disabled until models are loaded
            self._select_window_btn.clicked.connect(self._toggle_wayland_capture)
            window_row.addWidget(self._select_window_btn, 1)
            window_row.addWidget(self._ocr_config_btn)

            # Not used in Wayland mode
            self._window_combo = None
            self._start_btn = None
            self._stop_btn = None
        else:
            # X11/macOS/Windows: dropdown + start/refresh buttons
            self._window_combo = QComboBox()
            self._window_combo.setMinimumWidth(250)
            self._window_combo.activated.connect(self._on_window_selected)
            window_row.addWidget(self._window_combo, 1)

            self._start_btn = QPushButton("Start Capture")
            self._start_btn.setProperty("primary", True)
            self._start_btn.setEnabled(False)  # Disabled until models are loaded
            self._start_btn.clicked.connect(self._toggle_capture)
            window_row.addWidget(self._start_btn)

            refresh_btn = QPushButton("Refresh")
            refresh_btn.clicked.connect(self._refresh_windows)
            window_row.addWidget(refresh_btn)

            window_row.addWidget(self._ocr_config_btn)

            # Not used in X11 mode
            self._select_window_btn = None
            self._stop_btn = None

        capture_layout.addLayout(window_row)

        # Preview (centered, aspect ratio preserved)
        self._preview_label = QLabel()
        self._preview_label.setMinimumSize(320, 180)  # Minimum size, will grow to match aspect ratio
        self._preview_label.setFrameStyle(QFrame.Shape.NoFrame)
        self._preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_label.setText("No preview")
        self._preview_label.setProperty("role", "preview")
        capture_layout.addWidget(self._preview_label, 0, Qt.AlignmentFlag.AlignHCenter)

        return capture_group

    def _build_appearance_group(self) -> QGroupBox:
        """Overlay mode, hotkeys and the visual settings."""
        # ==================== APPEARANCE ====================
        # Overlay mode + all visual settings
        appearance_group = QGroupBox("Appearance")
        appearance_layout = QVBoxLayout(appearance_group)

        # Mode row (Banner/Inplace toggle + hotkeys)
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Mode:"))

        self._mode_group = QButtonGroup(self)
        self._mode_group.setExclusive(True)

        self._banner_btn = QPushButton("Banner")
        self._banner_btn.setCheckable(True)
        self._banner_btn.setChecked(self._mode == OverlayMode.BANNER)
        self._mode_group.addButton(self._banner_btn, 0)

        self._inplace_btn = QPushButton("Inplace")
        self._inplace_btn.setCheckable(True)
        self._inplace_btn.setChecked(self._mode == OverlayMode.INPLACE)
        self._mode_group.addButton(self._inplace_btn, 1)

        # Styled as a segmented control by the theme (see theme.py)
        self._banner_btn.setProperty("segment", "left")
        self._inplace_btn.setProperty("segment", "right")

        self._mode_group.idClicked.connect(self._on_mode_changed)

        # Container to keep buttons connected (no spacing)
        mode_container = QWidget()
        mode_btn_layout = QHBoxLayout(mode_container)
        mode_btn_layout.setContentsMargins(0, 0, 0, 0)
        mode_btn_layout.setSpacing(0)
        mode_btn_layout.addWidget(self._banner_btn)
        mode_btn_layout.addWidget(self._inplace_btn)
        mode_row.addWidget(mode_container)

        # Mode switch hotkey picker
        mode_switch_str = self._config.hotkeys.get("switch_mode", "m")
        self._mode_switch_str = mode_switch_str
        self._mode_hotkey = QKeySequenceEdit(self._hotkey_str_to_qkeysequence(mode_switch_str))
        self._mode_hotkey.setFixedWidth(80)
        self._mode_hotkey.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self._mode_hotkey.keySequenceChanged.connect(self._on_mode_hotkey_changed)
        mode_row.addWidget(self._mode_hotkey)

        # Wayland limitation warning (only shown on Wayland)
        if self._is_wayland_session:
            wayland_warning = QLabel("<a href='#' style='color: #ffa500;'>⚠️ Wayland limitations</a>")
            wayland_warning.setToolTip("Click for details about inplace mode on Wayland")
            wayland_warning.linkActivated.connect(self._show_wayland_warning)
            mode_row.addWidget(wayland_warning)

        mode_row.addStretch()

        # Hide/Show button with hotkey
        self._pause_btn = QPushButton("Hide")
        self._pause_btn.clicked.connect(self._toggle_pause)
        self._pause_btn.setEnabled(False)
        mode_row.addWidget(self._pause_btn)

        hotkey_str = self._config.hotkeys.get("toggle_overlay", "space")
        self._hotkey_str = hotkey_str
        self._pause_hotkey = QKeySequenceEdit(self._hotkey_str_to_qkeysequence(hotkey_str))
        self._pause_hotkey.setFixedWidth(80)
        self._pause_hotkey.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self._pause_hotkey.keySequenceChanged.connect(self._on_pause_hotkey_changed)
        mode_row.addWidget(self._pause_hotkey)

        appearance_layout.addLayout(mode_row)

        # Visual settings grid
        visual_grid = QGridLayout()

        # Font family
        visual_grid.addWidget(QLabel("Font:"), 0, 0)
        self._font_family_btn = QPushButton(self._config.font_family or "System Default")
        self._font_family_btn.clicked.connect(self._pick_font_family)
        visual_grid.addWidget(self._font_family_btn, 0, 1)

        # Font size
        visual_grid.addWidget(QLabel("Size:"), 0, 2)
        self._font_slider = QSlider(Qt.Orientation.Horizontal)
        self._font_slider.setRange(MIN_FONT_SIZE, MAX_FONT_SIZE)
        self._font_slider.setValue(self._config.font_size)
        self._font_slider.valueChanged.connect(self._on_font_size_changed)
        visual_grid.addWidget(self._font_slider, 0, 3)
        self._font_label = QLabel(f"{self._config.font_size}pt")
        visual_grid.addWidget(self._font_label, 0, 4)

        # Font color
        visual_grid.addWidget(QLabel("Text Color:"), 1, 0)
        self._font_color_btn = QPushButton()
        self._font_color_btn.setStyleSheet(f"background-color: {self._config.font_color};")
        self._font_color_btn.clicked.connect(self._pick_font_color)
        visual_grid.addWidget(self._font_color_btn, 1, 1)

        # Background color
        visual_grid.addWidget(QLabel("Background:"), 1, 2)
        self._bg_color_btn = QPushButton()
        self._bg_color_btn.setStyleSheet(f"background-color: {self._config.background_color};")
        self._bg_color_btn.clicked.connect(self._pick_bg_color)
        visual_grid.addWidget(self._bg_color_btn, 1, 3)

        # Opacity
        visual_grid.addWidget(QLabel("Opacity:"), 2, 0)
        self._opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self._opacity_slider.setRange(0, 100)
        self._opacity_slider.setValue(int(self._config.background_opacity * 100))
        self._opacity_slider.valueChanged.connect(self._on_opacity_changed)
        visual_grid.addWidget(self._opacity_slider, 2, 1, 1, 3)
        self._opacity_label = QLabel(f"{int(self._config.background_opacity * 100)}%")
        visual_grid.addWidget(self._opacity_label, 2, 4)

        appearance_layout.addLayout(visual_grid)

        return appearance_group

    def _build_status_group(self) -> QGroupBox:
        """Engine status rows and the Fix Models button."""
        # ==================== STATUS ====================
        # Models status (at bottom, less prominent)
        status_group = QGroupBox("Status")
        status_layout = QGridLayout(status_group)

        # OCR engine row (name follows the selected backend)
        status_layout.addWidget(QLabel("OCR:"), 0, 0)
        self._ocr_engine_label = QLabel(self._ocr_engine_name())
        status_layout.addWidget(self._ocr_engine_label, 0, 1)
        self._ocr_status_label = QLabel("Loading...")
        status_layout.addWidget(self._ocr_status_label, 0, 2)

        # Translation engine row (name follows the selected backend)
        status_layout.addWidget(QLabel("Translation:"), 1, 0)
        self._translation_engine_label = QLabel(self._translation_engine_name())
        status_layout.addWidget(self._translation_engine_label, 1, 1)
        self._translation_status_label = QLabel("Loading...")
        status_layout.addWidget(self._translation_status_label, 1, 2)

        # Fix Models button (hidden by default)
        self._fix_models_btn = QPushButton("Fix Models")
        self._fix_models_btn.clicked.connect(self._on_fix_models)
        self._fix_models_btn.setVisible(False)
        status_layout.addWidget(self._fix_models_btn, 2, 0, 1, 3, Qt.AlignRight)

        # macOS Permissions (inline, only shown on macOS when needed)
        if is_macos():
            self._setup_permissions_ui(status_layout)

        # Set column stretch so status is right-aligned
        status_layout.setColumnStretch(1, 1)

        return status_group

    def _setup_hotkeys(self):
        """Global hotkey listener, from the strings read by the appearance builder."""
        # Global hotkey listener - load from config
        self._current_hotkey = self._qt_key_to_key(self._hotkey_str)
        self._keyboard_listener = keyboard.Listener(on_press=self._on_key_press)
        self._keyboard_listener.start()
        self.hotkey_pressed.connect(self._toggle_pause)

        # Mode switch hotkey
        self._mode_switch_hotkey = self._qt_key_to_key(self._mode_switch_str)
        self.mode_switch_pressed.connect(self._toggle_mode)

    # ==================== OCR SETTINGS ====================

    def _build_ocr_group(self) -> QGroupBox:
        """Build the OCR group: engine selector plus the owocr server panel."""
        group = QGroupBox("OCR")
        group_layout = QVBoxLayout(group)

        # Engine row
        engine_row = QHBoxLayout()
        engine_row.addWidget(QLabel("Engine:"))
        self._ocr_engine_combo = QComboBox()
        self._ocr_engine_combo.addItem("MeikiOCR (built-in, offline)", OCRBackend.MEIKI.value)
        self._ocr_engine_combo.addItem("owocr (external process, websocket)", OCRBackend.OWOCR.value)
        self._ocr_engine_combo.setCurrentIndex(self._ocr_engine_combo.findData(self._config.ocr_backend.value))
        self._ocr_engine_combo.currentIndexChanged.connect(self._on_ocr_engine_changed)
        engine_row.addWidget(self._ocr_engine_combo, 1)
        self._apply_ocr_btn = QPushButton("Apply")
        self._apply_ocr_btn.setProperty("primary", True)
        self._apply_ocr_btn.setToolTip("Save these settings and reload the OCR engine")
        self._apply_ocr_btn.clicked.connect(self._apply_ocr_settings)
        engine_row.addWidget(self._apply_ocr_btn)
        group_layout.addLayout(engine_row)

        # Source language row: MeikiOCR reads Japanese only, so the choice is pinned for it
        language_row = QHBoxLayout()
        language_row.addWidget(QLabel("Source language:"))
        self._source_language_combo = QComboBox()
        for language in SOURCE_LANGUAGES:
            self._source_language_combo.addItem(language, language)
        self._source_language_combo.setCurrentIndex(
            max(0, self._source_language_combo.findData(self._config.source_language))
        )
        self._source_language_combo.setToolTip(
            "Language of the game's text. MeikiOCR and Sugoi V4 only handle Japanese; other languages "
            "need the owocr OCR engine and the LLM endpoint translation engine."
        )
        language_row.addWidget(self._source_language_combo, 1)
        group_layout.addLayout(language_row)
        self._sync_source_language_combo()

        # owocr panel (only visible for the owocr engine)
        self._owocr_panel = QWidget()
        owocr_grid = QGridLayout(self._owocr_panel)
        owocr_grid.setContentsMargins(0, 0, 0, 0)

        owocr_grid.addWidget(QLabel("Server URL:"), 0, 0)
        self._owocr_url_edit = QLineEdit(self._config.owocr.url)
        self._owocr_url_edit.setToolTip(
            f"Start owocr as: {OWOCR_SERVER_COMMAND}\n"
            f"Default address: {OWOCR_DEFAULT_URL}. "
            "Prefer 127.0.0.1 over localhost: on Windows, localhost adds ~2 s per request."
        )
        owocr_grid.addWidget(self._owocr_url_edit, 0, 1, 1, 2)

        self._owocr_test_btn = QPushButton("Test")
        self._owocr_test_btn.setToolTip("Send a blank image to the server and measure the round trip")
        self._owocr_test_btn.clicked.connect(self._test_owocr_endpoint)
        owocr_grid.addWidget(self._owocr_test_btn, 1, 0)
        self._owocr_result_label = QLabel("")
        self._owocr_result_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        # Reserve one text line even while empty so the row never collapses
        self._owocr_result_label.setMinimumHeight(self._owocr_test_btn.sizeHint().height())
        owocr_grid.addWidget(self._owocr_result_label, 1, 1, 1, 2)

        note = QLabel("owocr returns no confidence scores; the OCR confidence slider has no effect with this engine.")
        note.setProperty("role", "muted")
        note.setWordWrap(True)
        owocr_grid.addWidget(note, 2, 0, 1, 3)

        owocr_grid.setColumnStretch(1, 1)
        group_layout.addWidget(self._owocr_panel)
        self._owocr_panel.setVisible(self._config.ocr_backend == OCRBackend.OWOCR)

        return group

    def _ocr_engine_name(self) -> str:
        """Engine name shown in the Status group."""
        return "owocr" if self._config.ocr_backend == OCRBackend.OWOCR else "MeikiOCR"

    def _selected_ocr_backend(self) -> OCRBackend:
        return OCRBackend(self._ocr_engine_combo.currentData())

    def _owocr_settings_from_ui(self) -> OwocrSettings:
        """Read the owocr panel into an OwocrSettings value (without touching the config)."""
        return OwocrSettings(
            url=normalize_owocr_url(self._owocr_url_edit.text()),
            # Config-only field (no widget), carried over so Apply never drops it
            timeout=self._config.owocr.timeout,
        )

    def _on_ocr_engine_changed(self, _index: int):
        """Show the owocr panel only when the owocr engine is selected."""
        self._owocr_panel.setVisible(self._selected_ocr_backend() == OCRBackend.OWOCR)
        self._sync_source_language_combo()
        self._grow_to_fit()

    def _sync_source_language_combo(self):
        """Pin the source language to Japanese while MeikiOCR is selected; free it for owocr."""
        pluggable = self._selected_ocr_backend() == OCRBackend.OWOCR
        if not pluggable:
            self._source_language_combo.setCurrentIndex(self._source_language_combo.findData(DEFAULT_SOURCE_LANGUAGE))
        self._source_language_combo.setEnabled(pluggable)

    def _selected_source_language(self) -> str:
        """The source language the OCR group would apply (Japanese whenever MeikiOCR is selected)."""
        if self._selected_ocr_backend() != OCRBackend.OWOCR:
            return DEFAULT_SOURCE_LANGUAGE
        return self._source_language_combo.currentData() or DEFAULT_SOURCE_LANGUAGE

    def _set_owocr_result(self, text: str, error: bool = False):
        self._set_result_label(self._owocr_result_label, text, error)

    def _test_owocr_endpoint(self):
        """Run the probe round trip with the current panel settings on a background thread."""
        settings = self._owocr_settings_from_ui()
        self._owocr_test_request = settings
        self._owocr_test_btn.setEnabled(False)
        self._set_owocr_result("Testing...")

        def run():
            try:
                self._owocr_test_result.emit((settings, check_owocr_endpoint(settings)))
            except Exception as e:
                self._owocr_test_result.emit((settings, str(e)))

        threading.Thread(target=run, daemon=True).start()

    def _on_owocr_test_done(self, payload):
        settings, result = payload
        if settings is not self._owocr_test_request:
            return  # superseded by a newer Test
        self._owocr_test_request = None
        self._owocr_test_btn.setEnabled(True)
        if settings != self._owocr_settings_from_ui():
            self._set_owocr_result("Settings changed during the test; click Test again.", error=True)
            return
        if isinstance(result, str):
            self._set_owocr_result(result, error=True)
            return
        warning = owocr_remote_warning(settings.url)
        self._set_owocr_result(
            f"OK in {result} ms. {warning}" if warning else f"OK in {result} ms", error=bool(warning)
        )

    def _apply_ocr_settings(self):
        """Save the OCR group to config and reload the engine in the worker."""
        backend = self._selected_ocr_backend()
        source_language = self._selected_source_language()
        if source_language != SUGOI_SOURCE_LANGUAGE and self._config.translation_backend == TranslationBackend.SUGOI:
            # The owocr panel is visible whenever a non-Japanese source can be selected
            self._set_owocr_result(SUGOI_ONLY_JAPANESE, error=True)
            return
        if backend == OCRBackend.OWOCR:
            self._config.owocr = self._owocr_settings_from_ui()
            self._owocr_url_edit.setText(self._config.owocr.url)
            # Stale results from a previous Test or failure would contradict the new status
            warning = owocr_remote_warning(self._config.owocr.url)
            self._set_owocr_result(warning or "", error=bool(warning))
        language_changed = source_language != self._config.source_language
        self._config.ocr_backend = backend
        self._config.source_language = source_language
        self._config.save()

        self._ocr_engine_label.setText(self._ocr_engine_name())
        self._ocr_status_label.setToolTip("")
        self._fix_models_btn.setVisible(False)
        self.statusBar().showMessage("Reloading OCR engine...")
        self._process_worker.reload_ocr()
        if language_changed:
            # The LLM prompt names the source language, so the translation engine follows
            self._process_worker.reload_translation()

    # ==================== TRANSLATION SETTINGS ====================

    def _build_translation_group(self) -> QGroupBox:
        """Build the Translation group: engine selector plus the LLM endpoint panel."""
        group = QGroupBox("Translation")
        group_layout = QVBoxLayout(group)

        # Engine row
        engine_row = QHBoxLayout()
        engine_row.addWidget(QLabel("Engine:"))
        self._engine_combo = QComboBox()
        self._engine_combo.addItem("Sugoi V4 (built-in, offline)", TranslationBackend.SUGOI.value)
        self._engine_combo.addItem("LLM endpoint (Ollama / OpenAI-compatible)", TranslationBackend.LLM.value)
        self._engine_combo.setCurrentIndex(self._engine_combo.findData(self._config.translation_backend.value))
        self._engine_combo.currentIndexChanged.connect(self._on_engine_changed)
        engine_row.addWidget(self._engine_combo, 1)
        self._apply_translation_btn = QPushButton("Apply")
        self._apply_translation_btn.setProperty("primary", True)
        self._apply_translation_btn.setToolTip("Save these settings and reload the translation engine")
        self._apply_translation_btn.clicked.connect(self._apply_translation_settings)
        engine_row.addWidget(self._apply_translation_btn)
        group_layout.addLayout(engine_row)

        # LLM panel (only visible for the LLM engine)
        self._llm_panel = QWidget()
        llm_grid = QGridLayout(self._llm_panel)
        llm_grid.setContentsMargins(0, 0, 0, 0)
        settings = self._config.llm

        llm_grid.addWidget(QLabel("Provider:"), 0, 0)
        self._llm_provider_combo = QComboBox()
        for provider in PROVIDERS:
            self._llm_provider_combo.addItem(PROVIDER_LABELS[provider], provider)
        self._llm_provider_combo.setCurrentIndex(max(0, self._llm_provider_combo.findData(settings.provider)))
        self._llm_provider_combo.currentIndexChanged.connect(self._on_llm_provider_changed)
        llm_grid.addWidget(self._llm_provider_combo, 0, 1)

        llm_grid.addWidget(QLabel("Server URL:"), 0, 2)
        self._llm_url_edit = QLineEdit(settings.base_url)
        self._llm_url_edit.setToolTip(
            "Ollama: http://127.0.0.1:11434 - LM Studio: http://127.0.0.1:1234/v1 - OpenAI: https://api.openai.com/v1\n"
            "Prefer 127.0.0.1 over localhost: on Windows, localhost adds ~2 s per request."
        )
        llm_grid.addWidget(self._llm_url_edit, 0, 3, 1, 2)

        llm_grid.addWidget(QLabel("Model:"), 1, 0)
        self._llm_model_combo = QComboBox()
        self._llm_model_combo.setEditable(True)
        self._llm_model_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        if settings.model:
            self._llm_model_combo.addItem(settings.model)
        self._llm_model_combo.setCurrentText(settings.model)
        self._llm_model_combo.setToolTip("Type a model name or click Refresh to list the models on the server")
        llm_grid.addWidget(self._llm_model_combo, 1, 1)
        self._llm_refresh_btn = QPushButton("Refresh")
        self._llm_refresh_btn.setToolTip("Ask the server which models it has")
        self._llm_refresh_btn.clicked.connect(self._refresh_llm_models)
        llm_grid.addWidget(self._llm_refresh_btn, 1, 2)

        llm_grid.addWidget(QLabel("Target language:"), 1, 3)
        self._llm_language_edit = QLineEdit(settings.target_language)
        llm_grid.addWidget(self._llm_language_edit, 1, 4)

        llm_grid.addWidget(QLabel("API key:"), 2, 0)
        self._llm_api_key_edit = QLineEdit(settings.api_key)
        self._llm_api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._llm_api_key_edit.setPlaceholderText("Optional - only for hosted services (stored in config.yml)")
        llm_grid.addWidget(self._llm_api_key_edit, 2, 1, 1, 4)

        llm_grid.addWidget(QLabel("Prompt:"), 3, 0, Qt.AlignmentFlag.AlignTop)
        self._llm_prompt_edit = QPlainTextEdit(settings.system_prompt or DEFAULT_SYSTEM_PROMPT)
        self._llm_prompt_edit.setFixedHeight(64)
        self._llm_prompt_edit.setToolTip(
            "System prompt sent to the model. {source_language} and {target_language} are replaced."
        )
        llm_grid.addWidget(self._llm_prompt_edit, 3, 1, 1, 3)
        reset_prompt_btn = QPushButton("Reset")
        reset_prompt_btn.setToolTip("Restore the default prompt")
        reset_prompt_btn.clicked.connect(lambda: self._llm_prompt_edit.setPlainText(DEFAULT_SYSTEM_PROMPT))
        llm_grid.addWidget(reset_prompt_btn, 3, 4, Qt.AlignmentFlag.AlignTop)

        self._llm_test_btn = QPushButton("Test")
        self._llm_test_btn.setToolTip("Translate a sample line with these settings and measure the round trip")
        self._llm_test_btn.clicked.connect(self._test_llm_endpoint)
        llm_grid.addWidget(self._llm_test_btn, 4, 0)
        self._llm_result_label = QLabel("")
        self._llm_result_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        # Reserve one text line even while empty so the row never collapses
        self._llm_result_label.setMinimumHeight(self._llm_test_btn.sizeHint().height())
        llm_grid.addWidget(self._llm_result_label, 4, 1, 1, 4)

        llm_grid.setColumnStretch(1, 1)
        llm_grid.setColumnStretch(4, 1)
        group_layout.addWidget(self._llm_panel)
        self._llm_panel.setVisible(self._config.translation_backend == TranslationBackend.LLM)

        return group

    def _translation_engine_name(self) -> str:
        """Engine name shown in the Status group."""
        if self._config.translation_backend == TranslationBackend.LLM:
            llm = self._config.llm
            return f"{provider_label(llm.provider)} \u00b7 {llm.model or 'no model'}"
        return "Sugoi V4"

    def _selected_backend(self) -> TranslationBackend:
        return TranslationBackend(self._engine_combo.currentData())

    def _selected_provider(self) -> str:
        return self._llm_provider_combo.currentData()

    def _llm_settings_from_ui(self) -> LLMSettings:
        """Read the LLM panel into an LLMSettings value (without touching the config)."""
        prompt = self._llm_prompt_edit.toPlainText().strip()
        return LLMSettings(
            provider=self._selected_provider(),
            base_url=self._llm_url_edit.text().strip() or DEFAULT_BASE_URLS[self._selected_provider()],
            model=self._llm_model_combo.currentText().strip(),
            api_key=self._llm_api_key_edit.text().strip(),
            target_language=self._llm_language_edit.text().strip() or "English",
            system_prompt=None if not prompt or prompt == DEFAULT_SYSTEM_PROMPT else prompt,
            # Config-only fields (no widgets) are carried over so Apply never drops them
            context_lines=self._config.llm.context_lines,
            timeout=self._config.llm.timeout,
            request_options=dict(self._config.llm.request_options),
        )

    def _on_engine_changed(self, _index: int):
        """Show the LLM panel only when the LLM engine is selected."""
        self._llm_panel.setVisible(self._selected_backend() == TranslationBackend.LLM)
        self._grow_to_fit()

    def _grow_to_fit(self):
        """Grow the window height when a panel was revealed (adjustSize() caps at 2/3 of the screen)."""
        needed = self.sizeHint().height()
        if needed > self.height():
            self.resize(self.width(), needed)

    def _on_llm_provider_changed(self, _index: int):
        """Swap the default URL when the provider changes, unless the user typed their own."""
        provider = self._selected_provider()
        current = self._llm_url_edit.text().strip()
        if not current or current in DEFAULT_BASE_URLS.values():
            self._llm_url_edit.setText(DEFAULT_BASE_URLS[provider])
        self._llm_result_label.setText("")

    def _set_llm_result(self, text: str, error: bool = False):
        self._set_result_label(self._llm_result_label, text, error)

    @staticmethod
    def _set_result_label(label: QLabel, text: str, error: bool = False):
        """Show a one-line result under a settings panel; the full text is in the tooltip."""
        label.setStyleSheet(f"color: {ERROR};" if error else f"color: {OK};")
        label.setToolTip(text)
        # Elide instead of wrapping: the window's minimum size is locked, so a taller
        # label would overlap the prompt box instead of growing the panel.
        width = max(label.width() - 4, 200)
        label.setText(label.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, width))

    @staticmethod
    def _endpoint_identity(settings: LLMSettings) -> tuple[str, str, str]:
        """The parts of the settings that decide which server a model list came from."""
        return (settings.provider, normalize_base_url(settings.provider, settings.base_url), settings.api_key)

    def _refresh_llm_models(self):
        """List the server's models on a background thread.

        The request carries the settings it was made with; a result is dropped if a
        newer request superseded it or the endpoint fields changed meanwhile, so a slow
        old server can never overwrite the model list of the one now selected.
        """
        settings = self._llm_settings_from_ui()
        self._llm_refresh_request = settings
        self._llm_refresh_btn.setEnabled(False)
        self._set_llm_result("Listing models...")

        def run():
            try:
                self._llm_models_result.emit((settings, list_models(settings)))
            except Exception as e:
                self._llm_models_result.emit((settings, describe_request_error(e, settings)))

        threading.Thread(target=run, daemon=True).start()

    def _on_llm_models_listed(self, payload):
        settings, result = payload
        if settings is not self._llm_refresh_request:
            return  # superseded by a newer Refresh; that one re-enables the button
        self._llm_refresh_request = None
        self._llm_refresh_btn.setEnabled(True)
        if self._endpoint_identity(settings) != self._endpoint_identity(self._llm_settings_from_ui()):
            self._set_llm_result("Endpoint changed while listing models; click Refresh again.", error=True)
            return
        if isinstance(result, str):
            self._set_llm_result(result, error=True)
            return
        current = self._llm_model_combo.currentText().strip()
        self._llm_model_combo.clear()
        self._llm_model_combo.addItems(result)
        if current in result:
            self._llm_model_combo.setCurrentIndex(result.index(current))
        elif current:
            self._llm_model_combo.setCurrentText(current)
        if not result:
            hint = " Run 'ollama pull <model>' first." if self._selected_provider() == "ollama" else ""
            self._set_llm_result(f"The server has no models.{hint}", error=True)
        else:
            self._set_llm_result(f"{len(result)} model(s) found")

    def _test_llm_endpoint(self):
        """Translate a sample line with the current panel settings on a background thread."""
        settings = self._llm_settings_from_ui()
        if not settings.model:
            self._set_llm_result("Pick a model first.", error=True)
            return
        # The source language the OCR group would apply, not the saved one: the Test must
        # validate what the user is about to Apply, like every other pending field
        source_language = self._selected_source_language()
        self._llm_test_request = settings
        self._llm_test_language = source_language
        self._llm_test_btn.setEnabled(False)
        self._set_llm_result(f"Testing with a {source_language} sample (loading the model may take a moment)...")

        def run():
            try:
                self._llm_test_result.emit((settings, check_endpoint(settings, source_language)))
            except Exception as e:
                self._llm_test_result.emit((settings, str(e)))

        threading.Thread(target=run, daemon=True).start()

    def _on_llm_test_done(self, payload):
        settings, result = payload
        if settings is not self._llm_test_request:
            return  # superseded by a newer Test
        self._llm_test_request = None
        self._llm_test_btn.setEnabled(True)
        if settings != self._llm_settings_from_ui() or self._llm_test_language != self._selected_source_language():
            self._set_llm_result("Settings changed during the test; click Test again.", error=True)
            return
        if isinstance(result, str):
            self._set_llm_result(result, error=True)
            return
        translation, ms = result
        self._set_llm_result(f"OK in {ms} ms: {translation}")

    def _apply_translation_settings(self):
        """Save the Translation group to config and reload the engine in the worker."""
        backend = self._selected_backend()
        if backend == TranslationBackend.LLM:
            settings = self._llm_settings_from_ui()
            if not settings.model:
                self._set_llm_result("Pick a model before applying.", error=True)
                return
            self._config.llm = settings
        elif self._config.source_language != SUGOI_SOURCE_LANGUAGE:
            # The LLM panel is hidden for Sugoi, so the refusal goes to the status row and bar
            self._translation_status_label.setToolTip(SUGOI_ONLY_JAPANESE)
            self.statusBar().showMessage(SUGOI_ONLY_JAPANESE)
            return
        self._config.translation_backend = backend
        self._config.save()

        self._translation_engine_label.setText(self._translation_engine_name())
        self._translation_status_label.setToolTip("")
        self._fix_models_btn.setVisible(False)
        self.statusBar().showMessage("Reloading translation engine...")
        self._process_worker.reload_translation()

    def _setup_permissions_ui(self, status_layout: QGridLayout):
        """Set up macOS permissions in the status section."""
        # Get current row count to add after models
        row = status_layout.rowCount()

        # Screen Recording row
        status_layout.addWidget(QLabel("Screen Recording:"), row, 0)
        self._screen_recording_status = QLabel()
        status_layout.addWidget(self._screen_recording_status, row, 1)
        self._screen_recording_btn = QPushButton("Grant")
        self._screen_recording_btn.setFixedWidth(80)
        self._screen_recording_btn.clicked.connect(self._on_request_screen_recording)
        status_layout.addWidget(self._screen_recording_btn, row, 2)

        # Accessibility row (required for global hotkeys)
        row += 1
        status_layout.addWidget(QLabel("Accessibility:"), row, 0)
        self._accessibility_status = QLabel()
        status_layout.addWidget(self._accessibility_status, row, 1)
        self._accessibility_btn = QPushButton("Grant")
        self._accessibility_btn.setFixedWidth(80)
        self._accessibility_btn.clicked.connect(self._on_request_accessibility)
        status_layout.addWidget(self._accessibility_btn, row, 2)

        # Initial permission check
        self._update_permissions_status()

    def _update_permissions_status(self):
        """Update the permission status indicators."""
        if not is_macos():
            return

        # Screen Recording
        if check_screen_recording():
            self._screen_recording_status.setText("✓ Granted")
            set_role(self._screen_recording_status, "status-ok")
            self._screen_recording_btn.setVisible(False)
        else:
            self._screen_recording_status.setText("✗ Required")
            set_role(self._screen_recording_status, "status-error")
            self._screen_recording_btn.setVisible(True)

        # Accessibility
        if check_accessibility():
            self._accessibility_status.setText("✓ Granted")
            set_role(self._accessibility_status, "status-ok")
            self._accessibility_btn.setVisible(False)
        else:
            self._accessibility_status.setText("✗ Required")
            set_role(self._accessibility_status, "status-error")
            self._accessibility_btn.setVisible(True)

    def _on_request_screen_recording(self):
        """Handle Screen Recording grant button click."""
        # Try to request permission (triggers system dialog if first time)
        if not request_screen_recording():
            # Already denied, open System Settings
            open_screen_recording_settings()

        # Update status after a short delay (permission may take a moment to register)
        QTimer.singleShot(500, self._update_permissions_status)

    def _on_request_accessibility(self):
        """Handle Accessibility grant button click."""
        # Try to request permission (triggers system dialog)
        if not request_accessibility():
            # Already denied, open System Settings
            open_accessibility_settings()

        # Update status after a short delay
        QTimer.singleShot(500, self._update_permissions_status)

    def _load_models(self):
        """Start worker thread and load OCR/translation models."""
        self.statusBar().showMessage("Loading models...")
        self._process_worker.set_mode(self._mode)
        self._process_worker.start(self._config.ocr_confidence)

    def _on_models_ready(self):
        """Handle models loaded signal from worker thread."""
        # Enable the appropriate capture button
        if self._start_btn:
            self._start_btn.setEnabled(True)
        if self._select_window_btn:
            self._select_window_btn.setEnabled(True)
        self.statusBar().showMessage("Ready")
        logger.debug("models loaded")

    def _on_models_failed(self, error: str):
        """Handle model loading failure from worker thread."""
        # Disable the appropriate capture button
        if self._start_btn:
            self._start_btn.setEnabled(False)
        if self._select_window_btn:
            self._select_window_btn.setEnabled(False)
        self._show_fix_models_button()
        self.statusBar().showMessage(f"Model loading failed: {error[:120]}")
        # Full message on hover, since the status bar truncates
        failed = self._process_worker.get_failed_models()
        if "translation" in failed:
            self._translation_status_label.setToolTip(error)
            if self._config.translation_backend == TranslationBackend.LLM:
                self._set_llm_result(error, error=True)
        if "ocr" in failed:
            self._ocr_status_label.setToolTip(error)
            if self._config.ocr_backend == OCRBackend.OWOCR:
                self._set_owocr_result(error, error=True)
        logger.error("model loading failed", error=error)

    def _on_ocr_status(self, status: str):
        """Handle OCR model status change."""
        # Show "Downloading..." instead of "Loading..." when fixing
        if status == "loading" and self._fixing_ocr:
            status = "downloading"
        if status == "ready":
            self._fixing_ocr = False
            self._ocr_status_label.setToolTip("")
            # A recovered endpoint must not keep showing its old connection error
            if self._config.ocr_backend == OCRBackend.OWOCR and ERROR in self._owocr_result_label.styleSheet():
                warning = owocr_remote_warning(self._config.owocr.url)
                self._set_owocr_result(warning or "", error=bool(warning))
        self._update_status_label(self._ocr_status_label, status)
        self._update_fix_button_visibility()

    def _on_translation_status(self, status: str):
        """Handle translation model status change."""
        # Show "Downloading..." instead of "Loading..." when fixing
        if status == "loading" and self._fixing_translation:
            status = "downloading"
        if status == "ready":
            self._fixing_translation = False
            self._translation_status_label.setToolTip("")
        self._update_status_label(self._translation_status_label, status)
        self._update_fix_button_visibility()

    def _update_status_label(self, label: QLabel, status: str):
        """Update a model status label with appropriate text and style."""
        if status == "loading":
            label.setText("Loading...")
            set_role(label, "status-busy")
        elif status == "downloading":
            label.setText("Downloading...")
            set_role(label, "status-busy")
        elif status == "ready":
            label.setText("Ready")
            set_role(label, "status-ok")
        elif status == "error":
            label.setText("Error")
            set_role(label, "status-error")

    def _update_fix_button_visibility(self):
        """Show/hide the Fix Models button based on model status."""
        has_error = self._ocr_status_label.text() == "Error" or self._translation_status_label.text() == "Error"
        if has_error:
            self._show_fix_models_button()
        else:
            self._fix_models_btn.setVisible(False)

    def _show_fix_models_button(self):
        """Reveal the Fix Models button and grow the window so the extra row does not squeeze the layout."""
        if self._fix_models_btn.isVisible():
            return
        self._fix_models_btn.setVisible(True)
        self._grow_to_fit()

    def _on_fix_models(self):
        """Handle Fix Models button click."""
        from ..models import delete_model_cache

        # Track which models we're fixing (to show "Downloading..." instead of "Loading...")
        self._fixing_ocr = False
        self._fixing_translation = False

        # Delete caches for failed built-in models; endpoint-backed engines have nothing to download
        failed = self._process_worker.get_failed_models()
        if "ocr" in failed and self._config.ocr_backend == OCRBackend.MEIKI:
            delete_model_cache("rtr46/meiki.text.detect.v0")
            delete_model_cache("rtr46/meiki.txt.recognition.v0")
            self._fixing_ocr = True
        if (
            "translation" in failed
            and self._config.translation_backend == TranslationBackend.SUGOI
            # A source-language conflict is a settings problem, not a corrupt download
            and self._config.source_language == SUGOI_SOURCE_LANGUAGE
        ):
            delete_model_cache("entai2965/sugoi-v4-ja-en-ctranslate2")
            self._fixing_translation = True

        # Hide the button while fixing
        self._fix_models_btn.setVisible(False)

        if not (self._fixing_ocr or self._fixing_translation):
            # Nothing to download: retry the endpoints with the current settings
            self.statusBar().showMessage("Reconnecting...")
            if "ocr" in failed:
                self._process_worker.reload_ocr()
            if "translation" in failed:
                self._process_worker.reload_translation()
            return

        self.statusBar().showMessage("Downloading models...")

        # Stop and restart the worker to reload models
        self._process_worker.stop()
        self._process_worker = self._create_worker()
        self._process_worker.set_mode(self._mode)
        self._process_worker.start(self._config.ocr_confidence)

    def _refresh_windows(self):
        """Refresh the window list (X11 only)."""
        if self._is_wayland_session or self._window_combo is None:
            return

        self._window_combo.clear()
        self._windows_list = WindowCapture.list_windows()
        selected_idx = -1

        for i, win in enumerate(self._windows_list):
            title = win.get("title", "Unknown")
            bounds = win.get("bounds", {})
            width = bounds.get("width", 0)
            height = bounds.get("height", 0)
            if len(title) > 50:
                title = title[:50] + "..."
            display_text = f"{title} ({width}x{height})"
            self._window_combo.addItem(display_text)

            # Auto-select if matches config
            if self._config.window_title and self._config.window_title.lower() in win.get("title", "").lower():
                selected_idx = i

        if selected_idx >= 0:
            self._window_combo.setCurrentIndex(selected_idx)

    def _toggle_capture(self):
        """Start or stop capture."""
        if self._capturing:
            self._stop_capture()
        else:
            self._start_capture()

    def _start_capture(self):
        """Start capturing the selected window."""
        # Wayland session: always use portal capture
        if self._is_wayland_session:
            self._start_wayland_capture()
            return

        # X11 session: use selected window from list
        idx = self._window_combo.currentIndex()
        if idx < 0 or idx >= len(self._windows_list):
            self.statusBar().showMessage("No window selected")
            return

        window = self._windows_list[idx]
        title = window.get("title", "")
        window_id = window.get("id")
        bounds = window.get("bounds")

        self._capture = WindowCapture(title, window_id=window_id, bounds=bounds)
        if not self._capture.find_window():
            self.statusBar().showMessage("Window not found")
            return

        try:
            if not self._capture.start_stream():
                self.statusBar().showMessage("Failed to start stream")
                return
        except Exception as e:
            error_msg = str(e)
            log.get_logger().error("capture failed", error=error_msg)
            # Show truncated message in status bar (full message in logs)
            display_msg = error_msg.split("\n")[0][:100]  # First line, max 100 chars
            self.statusBar().showMessage(f"Capture failed: {display_msg}")
            self._capture = None
            return

        # Start single timer for capture + processing (fixed 2 FPS)
        self._process_timer.setInterval(PROCESS_INTERVAL_MS)
        self._process_timer.start()

        self._capturing = True
        self._paused = False
        if self._start_btn:
            self._start_btn.setText("Stop Capture")
        self._pause_btn.setEnabled(True)
        self._pause_btn.setText("Hide")
        self._ocr_config_btn.setEnabled(True)
        self.statusBar().showMessage(f"Capturing '{title[:40]}...'")

        # Update config with selected window
        self._config.window_title = title
        self._current_window_title = title  # Store for exclusion zone lookup

        # Set per-window OCR confidence
        confidence = self._config.get_ocr_confidence(title)
        self._process_worker.set_confidence_threshold(confidence)

        # Show overlay
        self._show_overlay()

    def _on_window_selected(self, index: int):
        """Handle window selection change (X11 only)."""
        # Not used in Wayland mode
        pass

    def _toggle_wayland_capture(self):
        """Toggle Wayland capture on/off."""
        if self._capturing:
            self._stop_capture()
        else:
            self._start_wayland_capture()

    def _start_wayland_capture(self):
        """Start Wayland capture using xdg-desktop-portal."""
        from ..capture.linux_wayland import WaylandCaptureStream, WaylandPortalCapture

        # Guard against re-entry (portal releases GIL, allowing Qt events to process)
        if self._wayland_selecting:
            return
        self._wayland_selecting = True

        self.statusBar().showMessage("Select a window...")
        if self._select_window_btn:
            self._select_window_btn.setEnabled(False)

        try:
            self._wayland_portal = WaylandPortalCapture()

            # Synchronous API (pipewire-capture 0.2.0) - returns stream info directly
            stream_info = self._wayland_portal.select_window()
            self._wayland_selecting = False

            if not stream_info:
                self.statusBar().showMessage("Window selection cancelled")
                if self._select_window_btn:
                    self._select_window_btn.setEnabled(True)
                self._wayland_portal.close()
                self._wayland_portal = None
                return

            fd, node_id, width, height = stream_info

            # Use unified capture interface
            self._capture = WaylandCaptureStream(fd, node_id, width, height)
            self._capture.start()

            # Start processing timer
            self._process_timer.setInterval(PROCESS_INTERVAL_MS)
            self._process_timer.start()

            self._capturing = True
            self._paused = False
            self._pause_btn.setEnabled(True)
            self._pause_btn.setText("Hide")
            self._ocr_config_btn.setEnabled(True)
            self.statusBar().showMessage("Capturing Wayland window...")

            # Update button to show stop action
            if self._select_window_btn:
                self._select_window_btn.setText("Stop Capture")
                self._select_window_btn.setEnabled(True)

            # Store window title for exclusion zone lookup (Wayland doesn't have window titles)
            self._current_window_title = "Wayland Capture"

            # Set per-window OCR confidence
            confidence = self._config.get_ocr_confidence(self._current_window_title)
            self._process_worker.set_confidence_threshold(confidence)

            # Show overlay
            self._show_overlay()

        except Exception as e:
            logger.error("failed to start wayland capture", error=str(e))
            self.statusBar().showMessage("Wayland capture failed")
            if self._select_window_btn:
                self._select_window_btn.setEnabled(True)
            self._wayland_selecting = False
            if self._wayland_portal:
                self._wayland_portal.close()
                self._wayland_portal = None

    def _stop_capture(self):
        """Stop capturing."""
        self._process_timer.stop()

        # Stop capture using unified interface
        if self._capture:
            self._capture.stop()
            self._capture = None

        # Close Wayland portal session if active
        if self._wayland_portal:
            self._wayland_portal.close()
            self._wayland_portal = None

        self._capturing = False
        self._paused = False
        self._pause_btn.setEnabled(False)
        self._ocr_config_btn.setEnabled(False)
        self.statusBar().showMessage("Ready")

        # Update UI based on session type
        if self._is_wayland_session:
            if self._select_window_btn:
                self._select_window_btn.setText("Start Capture")
                self._select_window_btn.setEnabled(True)
        else:
            if self._start_btn:
                self._start_btn.setText("Start Capture")

        # Clear preview
        self._preview_label.clear()
        self._preview_label.setText("No preview")

        # Hide overlays and clear inplace labels
        self._banner_overlay.hide()
        self._inplace_overlay.clear_regions()
        self._inplace_overlay.hide()

    def _toggle_pause(self):
        """Toggle pause state."""
        if not self._capturing:
            return
        self._paused = not self._paused
        if self._paused:
            self._pause_btn.setText("Show")
            self._banner_overlay.hide()
            self._inplace_overlay.clear_regions()
            self._inplace_overlay.hide()
        else:
            self._pause_btn.setText("Hide")
            self._show_overlay()

    def _toggle_mode(self):
        """Toggle between banner and inplace mode via hotkey."""
        new_mode_id = 0 if self._mode == OverlayMode.INPLACE else 1
        [self._banner_btn, self._inplace_btn][new_mode_id].setChecked(True)
        self._on_mode_changed(new_mode_id)

    def _on_key_press(self, key):
        """Handle global key press (called from keyboard listener thread)."""
        # Compare the pressed key with our hotkeys
        if key == self._current_hotkey:
            self.hotkey_pressed.emit()
        elif key == self._mode_switch_hotkey:
            self.mode_switch_pressed.emit()

    def _on_pause_hotkey_changed(self, key_sequence: QKeySequence):
        """Update pause hotkey when changed in UI."""
        if key_sequence.isEmpty():
            return
        # Convert Qt key sequence to keyboard key
        key_str = key_sequence.toString().lower()
        self._current_hotkey = self._qt_key_to_key(key_str)
        # Save to config
        self._config.hotkeys["toggle_overlay"] = key_str
        # Clear focus so it stops capturing keys
        self._pause_hotkey.clearFocus()

    def _on_mode_hotkey_changed(self, key_sequence: QKeySequence):
        """Update mode switch hotkey when changed in UI."""
        if key_sequence.isEmpty():
            return
        key_str = key_sequence.toString().lower()
        self._mode_switch_hotkey = self._qt_key_to_key(key_str)
        self._config.hotkeys["switch_mode"] = key_str
        self._mode_hotkey.clearFocus()

    def _qt_key_to_key(self, key_str: str):
        """Convert Qt key string to keyboard module key."""
        # Map common keys
        key_map = {
            "space": keyboard.Key.space,
            "esc": keyboard.Key.esc,
            "escape": keyboard.Key.esc,
            "tab": keyboard.Key.tab,
            "return": keyboard.Key.enter,
            "enter": keyboard.Key.enter,
            "backspace": keyboard.Key.backspace,
            "delete": keyboard.Key.delete,
            "home": keyboard.Key.home,
            "end": keyboard.Key.end,
            "pgup": keyboard.Key.page_up,
            "pgdown": keyboard.Key.page_down,
            "up": keyboard.Key.up,
            "down": keyboard.Key.down,
            "left": keyboard.Key.left,
            "right": keyboard.Key.right,
            "f1": keyboard.Key.f1,
            "f2": keyboard.Key.f2,
            "f3": keyboard.Key.f3,
            "f4": keyboard.Key.f4,
            "f5": keyboard.Key.f5,
            "f6": keyboard.Key.f6,
            "f7": keyboard.Key.f7,
            "f8": keyboard.Key.f8,
            "f9": keyboard.Key.f9,
            "f10": keyboard.Key.f10,
            "f11": keyboard.Key.f11,
            "f12": keyboard.Key.f12,
        }
        if key_str in key_map:
            return key_map[key_str]
        # For single characters, use KeyCode
        if len(key_str) == 1:
            return keyboard.KeyCode.from_char(key_str)
        return keyboard.Key.space  # fallback

    def _hotkey_str_to_qkeysequence(self, key_str: str) -> QKeySequence:
        """Convert config hotkey string to QKeySequence for the picker widget."""
        # Map config strings to Qt key names
        key_map = {
            "space": "Space",
            "esc": "Escape",
            "escape": "Escape",
            "tab": "Tab",
            "return": "Return",
            "enter": "Return",
            "backspace": "Backspace",
            "delete": "Delete",
            "home": "Home",
            "end": "End",
            "pgup": "PgUp",
            "pgdown": "PgDown",
            "up": "Up",
            "down": "Down",
            "left": "Left",
            "right": "Right",
        }
        # Check special keys first
        if key_str.lower() in key_map:
            return QKeySequence(key_map[key_str.lower()])
        # F-keys (f1-f12)
        if key_str.lower().startswith("f") and key_str[1:].isdigit():
            return QKeySequence(key_str.upper())
        # Single character
        if len(key_str) == 1:
            return QKeySequence(key_str.upper())
        # Fallback to space
        return QKeySequence(Qt.Key.Key_Space)

    def _on_mode_changed(self, button_id: int):
        """Handle mode selection change."""
        self._mode = OverlayMode.BANNER if button_id == 0 else OverlayMode.INPLACE

        self._process_worker.set_mode(self._mode)
        self._config.overlay_mode = self._mode

        if self._capturing and not self._paused:
            self._show_overlay()

    def _show_wayland_warning(self):
        """Show warning about inplace mode limitations on Wayland."""
        QMessageBox.information(
            self,
            "Inplace Mode on Wayland",
            "Inplace mode only works correctly with fullscreen games on Wayland.\n\n"
            "For windowed games, the text labels may appear in the wrong position "
            "because Wayland doesn't expose window coordinates.\n\n"
            "This is a Wayland security limitation, not a bug.",
        )

    def _show_overlay(self):
        """Show the appropriate overlay."""
        if self._mode == OverlayMode.BANNER:
            self._inplace_overlay.hide()
            self._banner_overlay.show()
        else:
            self._banner_overlay.hide()
            if self._last_bounds:
                self._inplace_overlay.position_over_window(self._last_bounds)
            self._inplace_overlay.show()

    def _capture_and_process(self):
        """Capture a frame and process it through OCR and translation."""
        if not self._capture:
            return

        # Get frame using unified capture interface
        frame = self._capture.get_frame()

        # Check if window was closed
        if self._capture.window_invalid:
            logger.info("window closed, stopping capture")
            self._stop_capture()
            return

        # Get bounds (None on Wayland, dict on X11/Windows/macOS)
        bounds = self._capture.bounds or {}

        # Keep the overlay above the game even after the game takes focus
        # (a focused topmost fullscreen window otherwise covers it)
        if not self._paused:
            overlay = self._inplace_overlay if self._mode == OverlayMode.INPLACE else self._banner_overlay
            overlay.ensure_above(getattr(self._capture, "window_id", None))

        if frame is None:
            return

        self._last_frame = frame
        self._last_bounds = bounds

        # Update preview (convert BGRA numpy to PIL RGB, scale to fit max 320 width)
        preview = bgra_to_rgb_pil(frame)
        frame_h, frame_w = frame.shape[:2]

        # Scale to max 320 width while preserving aspect ratio
        max_preview_width = 320
        scale = max_preview_width / frame_w
        preview_w = int(frame_w * scale)
        preview_h = int(frame_h * scale)
        preview = preview.resize((preview_w, preview_h))

        # Draw exclusion zones on preview
        zones = self._config.get_exclusion_zones(self._current_window_title)
        if zones:
            draw = ImageDraw.Draw(preview, "RGBA")
            for zone in zones:
                x = int(zone.get("x", 0) * preview_w)
                y = int(zone.get("y", 0) * preview_h)
                w = int(zone.get("width", 0) * preview_w)
                h = int(zone.get("height", 0) * preview_h)
                # Semi-transparent red fill with red outline
                draw.rectangle([x, y, x + w, y + h], fill=(255, 0, 0, 60), outline=(255, 0, 0, 180))

        data = preview.tobytes("raw", "RGB")
        qimg = QImage(data, preview_w, preview_h, preview_w * 3, QImage.Format.Format_RGB888)
        pixmap = QPixmap.fromImage(qimg)

        # Resize label to match preview aspect ratio
        self._preview_label.setFixedSize(preview_w, preview_h)
        self._preview_label.setPixmap(pixmap)

        # Update exclusion editor dialog if open
        if self._ocr_config_dialog:
            self._ocr_config_dialog.update_frame(frame)

        # Update inplace overlay position if window moved (X11 only - Wayland doesn't have bounds)
        if self._mode == OverlayMode.INPLACE and bounds and not self._paused:
            self._inplace_overlay.position_over_window(bounds)

        # Apply exclusion zones before OCR
        frame_for_ocr = self._apply_exclusion_zones(frame)

        # Process through OCR and translation (on worker thread)
        if not self._paused:
            self._process_worker.submit_frame(frame_for_ocr)

    def _on_text_ready(self, translated: str):
        """Handle translated text (banner mode)."""
        if not self._paused:
            self._banner_overlay.set_text(translated)

    def _on_regions_ready(self, regions: list):
        """Handle translated regions (inplace mode)."""
        if not self._paused:
            # Get content offset from capture (accounts for window decorations)
            content_offset = (0, 0)
            if self._capture:
                content_offset = self._capture.get_content_offset()
            self._inplace_overlay.set_regions(regions, content_offset)

    def _on_ocr_results_ready(self, results: list):
        """Handle raw OCR results (for OCR config dialog visualization)."""
        if self._ocr_config_dialog:
            self._ocr_config_dialog.update_ocr_results(results)

    # Settings handlers
    def _on_font_size_changed(self, value: int):
        self._config.font_size = value
        self._font_label.setText(f"{value}pt")
        self._banner_overlay.set_font_size(value)
        self._inplace_overlay.set_font_size(value)

    def _on_opacity_changed(self, value: int):
        opacity = value / 100.0
        self._config.background_opacity = opacity
        self._opacity_label.setText(f"{value}%")
        self._banner_overlay.set_opacity(opacity)
        self._inplace_overlay.set_opacity(opacity)

    def _pick_font_family(self):
        # Initialize dialog with current font
        if self._config.font_family:
            initial_font = QFont(self._config.font_family)
        else:
            initial_font = QFont()
        initial_font.setPointSize(self._config.font_size)

        ok, font = QFontDialog.getFont(initial_font, self)
        if ok:
            font_family = font.family()
            self._config.font_family = font_family
            self._font_family_btn.setText(font_family)
            self._banner_overlay.set_font_family(font_family)
            self._inplace_overlay.set_font_family(font_family)

    def _pick_font_color(self):
        color = QColorDialog.getColor()
        if color.isValid():
            hex_color = color.name()
            self._config.font_color = hex_color
            self._font_color_btn.setStyleSheet(f"background-color: {hex_color};")
            self._banner_overlay.set_colors(hex_color, self._config.background_color)
            self._inplace_overlay.set_colors(hex_color, self._config.background_color)

    def _pick_bg_color(self):
        color = QColorDialog.getColor()
        if color.isValid():
            hex_color = color.name()
            self._config.background_color = hex_color
            self._bg_color_btn.setStyleSheet(f"background-color: {hex_color};")
            self._banner_overlay.set_colors(self._config.font_color, hex_color)
            self._inplace_overlay.set_colors(self._config.font_color, hex_color)

    def _apply_exclusion_zones(self, frame):
        """Apply exclusion zones to frame by masking out excluded regions.

        Args:
            frame: BGRA numpy array (H, W, 4)

        Returns:
            Frame with exclusion zones blacked out.
        """
        if not self._current_window_title:
            return frame

        # Use dialog's zones if open (for live editing), otherwise use config
        if self._ocr_config_dialog:
            zones = self._ocr_config_dialog.get_zones()
        else:
            zones = self._config.get_exclusion_zones(self._current_window_title)

        if not zones:
            return frame

        # Make a copy to avoid modifying the original
        masked_frame = frame.copy()
        h, w = frame.shape[:2]

        for zone in zones:
            # Convert normalized coordinates to pixel coordinates
            x = int(zone.get("x", 0) * w)
            y = int(zone.get("y", 0) * h)
            zone_w = int(zone.get("width", 0) * w)
            zone_h = int(zone.get("height", 0) * h)

            # Clamp to frame bounds
            x = max(0, min(x, w))
            y = max(0, min(y, h))
            x2 = max(0, min(x + zone_w, w))
            y2 = max(0, min(y + zone_h, h))

            # Black out the region
            masked_frame[y:y2, x:x2] = 0

        return masked_frame

    def _open_ocr_config(self):
        """Open the OCR configuration dialog."""
        if not self._capturing or self._last_frame is None:
            return

        # Get current settings for this window
        current_zones = self._config.get_exclusion_zones(self._current_window_title)
        current_confidence = self._config.get_ocr_confidence(self._current_window_title)

        # Create and show dialog
        dialog = OCRConfigDialog(
            self,
            window_title=self._current_window_title,
            initial_confidence=current_confidence,
            initial_zones=current_zones,
        )

        # Connect confidence changes to worker (for live preview)
        dialog.confidence_changed.connect(self._process_worker.set_confidence_threshold)

        # Set up live frame updates
        self._ocr_config_dialog = dialog

        # Update with current frame
        dialog.update_frame(self._last_frame)
        dialog.apply_pending_zones()

        # Show dialog (modal)
        accepted = dialog.exec()

        if accepted:
            # Save zones and confidence to config
            new_zones = dialog.get_zones()
            new_confidence = dialog.get_confidence()

            self._config.set_exclusion_zones(self._current_window_title, new_zones)
            self._config.set_ocr_confidence(self._current_window_title, new_confidence)
            self._config.save()

            logger.debug(
                "OCR config updated",
                window=self._current_window_title,
                zones=len(new_zones),
                confidence=f"{new_confidence:.0%}",
            )
        else:
            # User cancelled - restore original confidence
            self._process_worker.set_confidence_threshold(current_confidence)

        self._ocr_config_dialog = None

    def get_banner_position(self) -> tuple[int, int]:
        """Get current banner overlay position."""
        return self._banner_overlay.get_position()

    def cleanup(self):
        """Clean up resources before closing."""
        self._stop_capture()
        self._keyboard_listener.stop()
        self._process_worker.stop()
        self._banner_overlay.close()
        self._inplace_overlay.close()
