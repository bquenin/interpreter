"""Application theme: Fusion style, a dark palette and a stylesheet that turns the settings
groups into cards, gives primary actions an accent colour and modernises the controls.

Everything is plain Qt: no extra dependency, same widgets, same platform behaviour.
"""

from pathlib import Path

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

# Design tokens
BG = "#0f1115"  # window background
CARD = "#171a21"  # group box background
CARD_BORDER = "#262b36"
FIELD = "#0f1115"  # inputs
FIELD_BORDER = "#2c3240"
HOVER = "#1f2430"
TEXT = "#e7e9ee"
MUTED = "#8a93a6"
ACCENT = "#4f8cff"
ACCENT_HOVER = "#6b9dff"
ACCENT_PRESSED = "#3b76e6"
OK = "#3ddc97"
ERROR = "#ff6b6b"
WARNING = "#ffb454"
RADIUS = 8

STYLESHEET = f"""
QMainWindow, QDialog {{
    background: {BG};
}}
QWidget {{
    color: {TEXT};
    font-size: 13px;
}}
QToolTip {{
    background: {CARD};
    color: {TEXT};
    border: 1px solid {CARD_BORDER};
    padding: 6px 8px;
    border-radius: 6px;
}}

/* Cards */
QGroupBox {{
    background: {CARD};
    border: 1px solid {CARD_BORDER};
    border-radius: {RADIUS + 4}px;
    margin-top: 14px;
    padding: 18px 14px 12px 14px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 14px;
    top: 4px;
    padding: 0 6px;
    color: {MUTED};
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 1px;
    text-transform: uppercase;
    background: {CARD};
}}

/* Buttons */
QPushButton {{
    background: {HOVER};
    border: 1px solid {FIELD_BORDER};
    border-radius: {RADIUS}px;
    padding: 6px 14px;
    min-height: 18px;
}}
QPushButton:hover {{
    background: #262c3a;
    border-color: #3a4152;
}}
QPushButton:pressed {{
    background: #161a22;
}}
QPushButton:disabled {{
    color: #5c6475;
    background: #161a22;
    border-color: #20252f;
}}
QPushButton[primary="true"] {{
    background: {ACCENT};
    border-color: {ACCENT};
    color: white;
    font-weight: 600;
}}
QPushButton[primary="true"]:hover {{
    background: {ACCENT_HOVER};
    border-color: {ACCENT_HOVER};
}}
QPushButton[primary="true"]:pressed {{
    background: {ACCENT_PRESSED};
}}
QPushButton[primary="true"]:disabled {{
    background: #26314a;
    border-color: #26314a;
    color: #7f8aa3;
}}
QPushButton[segment="true"] {{
    border-radius: 0;
    padding: 6px 18px;
}}
QPushButton[segment="true"]:checked {{
    background: {ACCENT};
    border-color: {ACCENT};
    color: white;
    font-weight: 600;
}}
QPushButton[segment="left"] {{
    border-top-left-radius: {RADIUS}px;
    border-bottom-left-radius: {RADIUS}px;
}}
QPushButton[segment="right"] {{
    border-top-right-radius: {RADIUS}px;
    border-bottom-right-radius: {RADIUS}px;
}}

/* Inputs */
QComboBox, QLineEdit, QPlainTextEdit, QKeySequenceEdit, QSpinBox {{
    background: {FIELD};
    border: 1px solid {FIELD_BORDER};
    border-radius: {RADIUS}px;
    padding: 5px 10px;
    selection-background-color: {ACCENT};
}}
QComboBox:hover, QLineEdit:hover, QPlainTextEdit:hover {{
    border-color: #3a4152;
}}
QComboBox:focus, QLineEdit:focus, QPlainTextEdit:focus, QKeySequenceEdit:focus {{
    border-color: {ACCENT};
}}
QComboBox:disabled, QLineEdit:disabled {{
    color: #5c6475;
    border-color: #20252f;
}}
QComboBox::drop-down {{
    border: none;
    width: 26px;
}}
QComboBox::down-arrow {{
    image: url("{{CHEVRON}}");
    width: 12px;
    height: 12px;
    margin-right: 8px;
}}
QComboBox QAbstractItemView {{
    background: {CARD};
    border: 1px solid {CARD_BORDER};
    border-radius: {RADIUS}px;
    padding: 4px;
    selection-background-color: {ACCENT};
    outline: none;
}}
QKeySequenceEdit {{
    padding: 0;
}}
QKeySequenceEdit QLineEdit {{
    border: 1px solid {FIELD_BORDER};
    border-radius: {RADIUS}px;
    padding: 5px 8px;
    background: {FIELD};
    color: {MUTED};
    font-weight: 600;
}}

/* Sliders */
QSlider::groove:horizontal {{
    height: 4px;
    background: {FIELD_BORDER};
    border-radius: 2px;
}}
QSlider::sub-page:horizontal {{
    background: {ACCENT};
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    width: 16px;
    height: 16px;
    margin: -6px 0;
    border-radius: 8px;
    background: white;
    border: 2px solid {ACCENT};
}}
QSlider::handle:horizontal:hover {{
    background: {ACCENT_HOVER};
}}

/* Labels */
QLabel[role="muted"] {{
    color: {MUTED};
}}
QLabel[role="status-ok"] {{
    color: {OK};
    font-weight: 600;
}}
QLabel[role="status-error"] {{
    color: {ERROR};
    font-weight: 600;
}}
QLabel[role="status-busy"] {{
    color: {WARNING};
}}
QLabel[role="preview"] {{
    background: #05060a;
    color: {MUTED};
    border: 1px solid {CARD_BORDER};
    border-radius: {RADIUS}px;
}}

/* Status bar */
QStatusBar {{
    background: {BG};
    color: {MUTED};
    border-top: 1px solid {CARD_BORDER};
}}
QStatusBar::item {{
    border: none;
}}

/* Scrollbars */
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {FIELD_BORDER};
    border-radius: 5px;
    min-height: 24px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
"""


def stylesheet() -> str:
    """The stylesheet with icon paths resolved (QSS needs absolute file URLs)."""
    chevron = (Path(__file__).parent.parent / "resources" / "icons" / "chevron-down.svg").as_posix()
    return STYLESHEET.replace("{CHEVRON}", chevron)


def apply_theme(app: QApplication) -> None:
    """Install the theme on the application: Fusion style, dark palette, stylesheet."""
    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(BG))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Base, QColor(FIELD))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(CARD))
    palette.setColor(QPalette.ColorRole.Text, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Button, QColor(HOVER))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(ACCENT))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("white"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(CARD))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(MUTED))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor("#5c6475"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor("#5c6475"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor("#5c6475"))
    app.setPalette(palette)
    app.setStyleSheet(stylesheet())


def set_role(widget, role: str) -> None:
    """Set a stylesheet role on a widget and re-polish it so the new rule applies."""
    widget.setProperty("role", role)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
