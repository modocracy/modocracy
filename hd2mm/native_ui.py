"""PySide6 Qt Widgets 화면. 브라우저·HTML·GPU 합성 없이 일반 위젯을 그린다.

모양은 예전 웹 화면(어두운 카드 + 노란 포인트)을 따른다. 색은 C, 위젯 모양은 STYLE,
체크 상자·라디오 버튼·끌어놓기 표시는 Style(QProxyStyle), 모드 목록 한 줄은 ModDelegate가 그린다.
"""
from __future__ import annotations

import logging
import platform
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from PySide6.QtCore import (
    QByteArray, QEvent, QObject, QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal, Slot,
    qInstallMessageHandler, qVersion,
)
from PySide6.QtGui import (
    QBrush, QColor, QFont, QFontMetrics, QIcon, QImageReader, QLinearGradient, QPainter,
    QPainterPath, QPalette, QPen, QPixmap,
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog, QFileDialog,
    QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLayout, QLineEdit, QListWidget, QListWidgetItem,
    QMainWindow, QMessageBox, QProgressBar, QProxyStyle, QPushButton, QRadioButton, QScrollArea,
    QSizePolicy, QSplitter, QStyle, QStyledItemDelegate, QTableWidget, QTableWidgetItem, QTextEdit,
    QVBoxLayout, QWidget,
)

from . import APP_NAME, __version__, i18n, updater
from .core import ModError, NeedsConfirm, safe_join
from .native_backend import Backend
from .server import RASTER_TYPES, AppServer, update_info
from .ui_text import tr

log = logging.getLogger(__name__)
USER_ROLE = Qt.ItemDataRole.UserRole
MOD_ROLE = Qt.ItemDataRole.UserRole + 1
WEB_DIR = Path(__file__).resolve().parent / "web"

# 예전 웹 화면(style.css :root)과 같은 색
C = {
    "bg": "#0b0d10", "bg2": "#101318", "panel": "#14171d", "panel2": "#1b1f27", "panel3": "#232833",
    "line": "#262c37", "line2": "#323a48", "text": "#e8ebf0", "muted": "#8d95a3", "faint": "#5f6775",
    "accent": "#ffe11a", "accent2": "#ffd000", "ink": "#14140f", "desc": "#cfd4dc",
    "ok": "#4fd08a", "warn": "#ffb224", "err": "#ff5d50", "info": "#6fb5ff",
}
TONE_RGB = {"ok": "79, 208, 138", "warn": "255, 178, 36", "err": "255, 93, 80", "error": "255, 93, 80",
            "info": "111, 181, 255", "accent": "255, 225, 26"}

STYLE = """
QMainWindow, QDialog, QWidget#root { background: $bg; }
QToolTip { background: $panel3; color: $text; border: 1px solid $line2; padding: 5px 8px; }
QLabel { background: transparent; color: $text; }
QLabel#muted { color: $muted; }
QLabel#faint, QLabel#kicker_faint { color: $faint; }
QLabel#kicker { color: $accent; }
QLabel#section { color: $muted; }
QLabel#desc { color: $desc; }
QLabel#warnText { color: $warn; }
QLabel#errText { color: $err; }
QLabel#okText { color: $ok; }
QLabel#heroTitle { color: #ffffff; }
QLabel#path { background: $bg2; border: 1px solid $line; border-radius: 7px; padding: 8px 10px; color: $desc; }
QLabel#dot { background: $faint; border-radius: 5px; }
QLabel#dot[tone="ok"] { background: $ok; }
QLabel#dot[tone="warn"] { background: $warn; }
QLabel#dot[tone="err"] { background: $err; }

QFrame#topbar { background: $bg; border: 0; border-bottom: 1px solid $line; }
QFrame#panel { background: $panel; border: 1px solid $line; border-radius: 10px; }
QFrame#divider { background: $line; border: 0; }
QFrame#status { background: $panel; border: 1px solid $line; border-radius: 10px; }
QFrame#status[tone="ok"] { border-color: rgba(79, 208, 138, 90);
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 rgba(79, 208, 138, 30), stop:0.45 $panel); }
QFrame#status[tone="warn"] { border-color: rgba(255, 178, 36, 100);
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 rgba(255, 178, 36, 30), stop:0.45 $panel); }
QFrame#status[tone="err"] { border-color: rgba(255, 93, 80, 115);
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 rgba(255, 93, 80, 30), stop:0.45 $panel); }
QFrame#update { border: 1px solid rgba(111, 181, 255, 90); border-radius: 10px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 rgba(111, 181, 255, 26), stop:0.55 $panel); }
QFrame#diagnostic { border: 1px solid rgba(255, 178, 36, 90); border-radius: 10px; background: rgba(255, 178, 36, 20); }
QFrame#callout { border: 1px solid $line; border-radius: 7px; background: $panel2; }
QFrame#callout[tone="error"] { border-color: rgba(255, 93, 80, 100); background: rgba(255, 93, 80, 30); }
QFrame#callout[tone="warn"] { border-color: rgba(255, 178, 36, 100); background: rgba(255, 178, 36, 30); }
QFrame#callout[tone="info"] { border-color: rgba(111, 181, 255, 77); background: rgba(111, 181, 255, 26); }
QFrame#option { background: $bg2; border: 1px solid $line; border-radius: 7px; }
QFrame#option[active="true"] { border-color: rgba(255, 225, 26, 115); }
QFrame#fold { background: $bg2; border: 1px solid $line; border-radius: 7px; }
QFrame#card { background: $panel; border: 1px solid $line; border-radius: 10px; }

QPushButton { background: $panel2; color: $text; border: 1px solid $line2; border-radius: 7px;
    padding: 0 14px; min-height: 34px; font-weight: 600; }
QPushButton:hover { background: $panel3; }
QPushButton:pressed { background: $line2; }
QPushButton:focus { border-color: rgba(255, 225, 26, 150); }
QPushButton:disabled { color: $faint; background: $panel; border-color: $line; }
QPushButton[size="small"] { min-height: 28px; padding: 0 10px; }
QPushButton[variant="primary"] { background: $accent; border-color: $accent; color: $ink; }
QPushButton[variant="primary"]:hover { background: $accent2; border-color: $accent2; }
QPushButton[variant="primary"]:focus { border-color: #ffffff; }
QPushButton[variant="primary"]:disabled { background: rgba(255, 225, 26, 60); border-color: transparent; color: rgba(20, 20, 15, 150); }
QPushButton[variant="outline"] { background: transparent; border-color: rgba(255, 225, 26, 140); color: $accent; }
QPushButton[variant="outline"]:hover { background: rgba(255, 225, 26, 26); }
QPushButton[variant="outline"]:disabled { border-color: $line; color: $faint; }
QPushButton[variant="ghost"] { background: transparent; border-color: transparent; color: $muted; }
QPushButton[variant="ghost"]:hover { background: $panel2; color: $text; }
QPushButton[variant="ghost"]:disabled { color: $faint; }
QPushButton[variant="danger"] { background: transparent; border-color: rgba(255, 93, 80, 100); color: $err; }
QPushButton[variant="danger"]:hover { background: rgba(255, 93, 80, 30); }
QPushButton[variant="dangerSolid"] { background: $err; border-color: $err; color: #ffffff; }
QPushButton[variant="dangerSolid"]:hover { background: #ff7468; border-color: #ff7468; }
QPushButton[variant="chip"] { background: $panel; border: 1px solid $line; border-radius: 17px; color: $muted;
    font-weight: 400; padding: 0 14px; }
QPushButton[variant="chip"]:hover { border-color: $line2; color: $text; }
QPushButton[variant="fold"] { background: transparent; border: 0; border-radius: 7px; text-align: left;
    padding: 0 10px; min-height: 40px; }
QPushButton[variant="fold"]:hover { background: $panel2; }
QPushButton#emptyDrop { background: transparent; border: 2px dashed $line2; border-radius: 10px; min-height: 200px; }
QPushButton#emptyDrop:hover { border-color: rgba(255, 225, 26, 150); }

QListWidget#modList { background: transparent; border: 0; outline: 0; }
QScrollArea { background: transparent; border: 0; }
QWidget#transparent { background: transparent; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 3px 2px; }
QScrollBar::handle:vertical { background: $line2; border-radius: 3px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: $faint; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px 3px; }
QScrollBar::handle:horizontal { background: $line2; border-radius: 3px; min-width: 30px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

QLineEdit, QComboBox { background: $bg2; color: $text; border: 1px solid $line2; border-radius: 7px;
    padding: 0 10px; min-height: 34px; selection-background-color: rgba(255, 225, 26, 90); selection-color: #ffffff; }
QLineEdit:focus, QComboBox:focus, QComboBox:on { border-color: rgba(255, 225, 26, 160); }
QComboBox:disabled { color: $faint; border-color: $line; }
QComboBox::drop-down { border: 0; width: 28px; }
QComboBox QAbstractItemView { background: $panel2; color: $text; border: 1px solid $line2; outline: 0;
    selection-background-color: $panel3; selection-color: $accent; padding: 4px; }
QCheckBox, QRadioButton { background: transparent; color: $text; spacing: 10px; }
QCheckBox:disabled, QRadioButton:disabled { color: $faint; }

QTableWidget { background: transparent; border: 0; gridline-color: transparent; color: $desc;
    selection-background-color: $panel3; selection-color: $text; }
QTableWidget::item { border-bottom: 1px solid $line; padding: 0 6px; }
QHeaderView { background: transparent; border: 0; }
QHeaderView::section { background: transparent; color: $muted; border: 0; border-bottom: 1px solid $line;
    padding: 6px; font-weight: 600; }
QTextEdit { background: $bg; color: $desc; border: 1px solid $line; border-radius: 7px; padding: 6px;
    selection-background-color: rgba(255, 225, 26, 90); }

QProgressBar { background: transparent; border: 0; }
QProgressBar::chunk { background: $accent; }
QSplitter::handle { background: transparent; }
QStatusBar { background: $bg; color: $muted; border-top: 1px solid $line; }
QStatusBar::item { border: 0; }
QMessageBox { background: $panel; }
QMessageBox QLabel { color: $text; }
"""


def stylesheet() -> str:
    text = STYLE
    for key in sorted(C, key=len, reverse=True):  # $panel2가 $panel보다 먼저 바뀌도록
        text = text.replace("$" + key, C[key])
    return text


# ------------------------------------------------------------ 아이콘 (예전 웹 화면과 같은 선 아이콘)
def _svg(inner: str, fill: str = "none") -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="{fill}" stroke="currentColor" '
            f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">{inner}</svg>')


ICONS = {
    "settings": _svg('<path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/>'),
    "trash": _svg('<path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6M10 11v6M14 11v6"/>'),
    "folder": _svg('<path d="M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13c0 1.1.9 2 2 2Z"/>'),
    "play": _svg('<path d="M6 3l14 9-14 9z"/>'),
    "up": _svg('<path d="m18 15-6-6-6 6"/>'),
    "down": _svg('<path d="m6 9 6 6 6-6"/>'),
    "right": _svg('<path d="m9 18 6-6-6-6"/>'),
    "bottom": _svg('<path d="M12 3v12M6 9l6 6 6-6M5 21h14"/>'),
    "grip": _svg('<circle cx="9" cy="6" r="1.4"/><circle cx="15" cy="6" r="1.4"/><circle cx="9" cy="12" r="1.4"/><circle cx="15" cy="12" r="1.4"/><circle cx="9" cy="18" r="1.4"/><circle cx="15" cy="18" r="1.4"/>', "currentColor"),
    "warn": _svg('<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><path d="M12 9v4M12 17h.01"/>'),
    "error": _svg('<circle cx="12" cy="12" r="10"/><path d="M12 8v4M12 16h.01"/>'),
    "info": _svg('<circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/>'),
    "ok": _svg('<circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/>'),
    "package": _svg('<path d="m7.5 4.27 9 5.15"/><path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z"/><path d="m3.3 7 8.7 5 8.7-5M12 22V12"/>'),
    "upload": _svg('<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m17 8-5-5-5 5M12 3v12"/>'),
    "refresh": _svg('<path d="M21 12a9 9 0 1 1-2.64-6.36L21 8"/><path d="M21 3v5h-5"/>'),
}
_pixmap_cache: dict = {}


def svg_pixmap(svg: str, size: int, ratio: float = 1.0) -> QPixmap:
    key = (svg, size, ratio)
    if key not in _pixmap_cache:
        pixmap = QPixmap(int(size * ratio), int(size * ratio))
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        QSvgRenderer(QByteArray(svg.encode("utf-8"))).render(painter)
        painter.end()
        pixmap.setDevicePixelRatio(ratio)
        _pixmap_cache[key] = pixmap
    return _pixmap_cache[key]


def icon_pixmap(name: str, color: str, size: int = 16, ratio: float = 2.0) -> QPixmap:
    return svg_pixmap(ICONS[name].replace("currentColor", color), size, ratio)


def icon(name: str, color: str = C["text"], size: int = 16) -> QIcon:
    return QIcon(icon_pixmap(name, color, size))


def brand_pixmap(size: int) -> QPixmap:
    try:
        return svg_pixmap((WEB_DIR / "icon.svg").read_text(encoding="utf-8"), size, 2.0)
    except OSError:
        return QPixmap()


def dot_icon(color: str) -> QIcon:
    pixmap = QPixmap(32, 32)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    soft = QColor(color)
    soft.setAlpha(50)
    painter.setBrush(soft)
    painter.drawEllipse(QRectF(4, 4, 24, 24))
    painter.setBrush(QColor(color))
    painter.drawEllipse(QRectF(10, 10, 12, 12))
    painter.end()
    pixmap.setDevicePixelRatio(2.0)
    return QIcon(pixmap)


# ------------------------------------------------------------ 글꼴·작은 위젯 도우미
FONT_UI = ["Segoe UI", "Malgun Gothic"]
FONT_DISPLAY = ["Bahnschrift", "Segoe UI", "Malgun Gothic"]
FONT_MONO = ["Cascadia Mono", "Consolas", "D2Coding", "Malgun Gothic"]


def make_font(size: float = 10, weight=QFont.Weight.Normal, families=None, spacing: float = 0) -> QFont:
    font = QFont()
    font.setFamilies(families or FONT_UI)
    font.setPointSizeF(size)
    font.setWeight(weight)
    if spacing:
        font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 100 + spacing)
    return font


def label(text: str = "", role: str = "", *, wrap: bool = True, font: QFont | None = None,
          selectable: bool = True) -> QLabel:
    widget = QLabel(str(text))
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setWordWrap(wrap)
    widget.setObjectName(role)
    if font is not None:
        widget.setFont(font)
    if selectable:
        widget.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return widget


def section_label(text: str) -> QLabel:
    return label(text.upper(), "section", wrap=False, selectable=False,
                 font=make_font(8.5, QFont.Weight.Bold, FONT_DISPLAY, spacing=14))


BADGE_COLORS = {
    "plain": (QColor(C["panel3"]), C["muted"]), "accent": (QColor(255, 225, 26, 28), C["accent"]),
    "ok": (QColor(79, 208, 138, 32), C["ok"]), "err": (QColor(255, 93, 80, 32), C["err"]),
    "dark": (QColor(0, 0, 0, 125), C["text"]), "darkAccent": (QColor(40, 36, 8, 190), C["accent"]),
    "darkOk": (QColor(12, 40, 26, 190), "#b9f5d3"),
}


class Badge(QLabel):
    """둥근 알약 모양 표시 (웹 화면의 .badge)."""

    def __init__(self, text: str, tone: str = "plain"):
        super().__init__(text)
        self.tone = tone
        self.setFont(make_font(8.5, QFont.Weight.DemiBold))

    def sizeHint(self):
        metrics = QFontMetrics(self.font())
        return QSize(metrics.horizontalAdvance(self.text()) + 16, 20)

    def minimumSizeHint(self):
        return self.sizeHint()

    def paintEvent(self, event):
        back, fore = BADGE_COLORS.get(self.tone, BADGE_COLORS["plain"])
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(back)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        painter.setPen(QColor(fore))
        painter.setFont(self.font())
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self.text())
        painter.end()


def badge(text: str, tone: str = "plain") -> QLabel:
    widget = Badge(text, tone)
    widget.setFixedSize(widget.sizeHint())
    return widget


def button(text: str, action, variant: str = "", *, icon_name: str = "", small: bool = False,
           tip: str = "") -> QPushButton:
    widget = QPushButton(text)
    if variant:
        widget.setProperty("variant", variant)
    if small:
        widget.setProperty("size", "small")
    if icon_name:
        color = {"primary": C["ink"], "danger": C["err"], "outline": C["accent"], "ghost": C["muted"],
                 "dangerSolid": "#ffffff"}.get(variant, C["text"])
        widget.setIcon(icon(icon_name, color))
        widget.setIconSize(QSize(15, 15) if small else QSize(16, 16))
    if tip:
        widget.setToolTip(tip)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    widget.clicked.connect(lambda _checked=False: action())
    return widget


def row(*widgets, spacing: int = 8) -> QHBoxLayout:
    layout = QHBoxLayout()
    layout.setSpacing(spacing)
    layout.setContentsMargins(0, 0, 0, 0)
    for widget in widgets:
        if widget is None:
            layout.addStretch()
        elif isinstance(widget, int):
            layout.addSpacing(widget)
        elif isinstance(widget, QWidget):
            layout.addWidget(widget)
        else:
            layout.addLayout(widget)
    return layout


class FlowLayout(QLayout):
    """자리가 모자라면 다음 줄로 넘기는 배치 (오른쪽 정렬). 좁은 창에서 버튼이 잘리지 않게 한다."""

    def __init__(self, parent=None, spacing: int = 6):
        super().__init__(parent)
        self.items = []
        self.gap = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self.items.append(item)

    def count(self):
        return len(self.items)

    def itemAt(self, index):
        return self.items[index] if 0 <= index < len(self.items) else None

    def takeAt(self, index):
        return self.items.pop(index) if 0 <= index < len(self.items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._place(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._place(rect, apply=True)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self.items:
            size = size.expandedTo(item.minimumSize())
        return size

    def _place(self, rect, apply):
        lines, line, width = [], [], 0
        for item in self.items:
            hint = item.sizeHint()
            if line and width + self.gap + hint.width() > rect.width():
                lines.append((line, width))
                line, width = [], 0
            width += (self.gap if line else 0) + hint.width()
            line.append((item, hint))
        if line:
            lines.append((line, width))
        y = rect.y()
        for line, width in lines:
            height = max(hint.height() for _, hint in line)
            x = rect.x() + max(0, rect.width() - width)
            for item, hint in line:
                if apply:
                    item.setGeometry(QRect(x, y + (height - hint.height()) // 2, hint.width(), hint.height()))
                x += hint.width() + self.gap
            y += height + self.gap
        return max(0, y - rect.y() - self.gap)


def frame(name: str, **props) -> QFrame:
    widget = QFrame()
    widget.setObjectName(name)
    for key, value in props.items():
        widget.setProperty(key, value)
    return widget


def divider() -> QFrame:
    line = frame("divider")
    line.setFixedHeight(1)
    return line


def repolish(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def rounded(pixmap: QPixmap, radius: float) -> QPixmap:
    result = QPixmap(pixmap.size())
    result.setDevicePixelRatio(pixmap.devicePixelRatio())
    result.fill(Qt.GlobalColor.transparent)
    painter = QPainter(result)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    ratio = pixmap.devicePixelRatio()
    path.addRoundedRect(QRectF(0, 0, pixmap.width() / ratio, pixmap.height() / ratio), radius, radius)
    painter.setClipPath(path)
    painter.drawPixmap(0, 0, pixmap)
    painter.end()
    return result


def fmt_size(value: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{value} B"
        value /= 1024


def fmt_time(value) -> str:
    if not value:
        return "—"
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone().strftime("%Y-%m-%d %H:%M")
    except (ValueError, AttributeError):
        return str(value)


def fit_screen(widget, width, height):
    area = widget.screen().availableGeometry()
    widget.resize(min(width, max(600, area.width() - 40)), min(height, max(400, area.height() - 70)))


def draw_switch(painter: QPainter, rect: QRectF, on: bool, enabled: bool = True) -> None:
    """켜기/끄기 스위치 (웹 화면의 .switch와 같은 36x20 모양)."""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    if not enabled:
        painter.setOpacity(0.45)
    track = QRectF(rect.x() + 0.5, rect.y() + 0.5, 35, 19)
    painter.setPen(QPen(QColor(C["accent"] if on else C["line2"]), 1))
    painter.setBrush(QColor(C["accent"] if on else C["panel3"]))
    painter.drawRoundedRect(track, 9.5, 9.5)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(C["ink"] if on else C["muted"]))
    painter.drawEllipse(QRectF(track.x() + (18.5 if on else 2.5), track.y() + 2.5, 14, 14))
    painter.restore()


# ------------------------------------------------------------ Qt 스타일
class Style(QProxyStyle):
    """Fusion을 바탕으로 체크 상자·라디오 버튼·끌어놓기 선만 웹 화면처럼 그린다."""

    def __init__(self):
        super().__init__("Fusion")

    def pixelMetric(self, metric, option=None, widget=None):
        if metric in (QStyle.PixelMetric.PM_IndicatorWidth, QStyle.PixelMetric.PM_IndicatorHeight,
                      QStyle.PixelMetric.PM_ExclusiveIndicatorWidth, QStyle.PixelMetric.PM_ExclusiveIndicatorHeight):
            return 18
        return super().pixelMetric(metric, option, widget)

    def drawPrimitive(self, element, option, painter, widget=None):
        pe = QStyle.PrimitiveElement
        if element in (pe.PE_IndicatorCheckBox, pe.PE_IndicatorRadioButton):
            state = option.state
            on = bool(state & QStyle.StateFlag.State_On)
            enabled = bool(state & QStyle.StateFlag.State_Enabled)
            hover = bool(state & QStyle.StateFlag.State_MouseOver)
            rect = QRectF(option.rect).adjusted(1, 1, -1, -1)
            size = min(rect.width(), rect.height())
            rect = QRectF(rect.center().x() - size / 2, rect.center().y() - size / 2, size, size)
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            if not enabled:
                painter.setOpacity(0.45)
            border = QColor(C["accent"]) if on or hover else QColor(C["line2"])
            painter.setPen(QPen(border, 1.2))
            painter.setBrush(QColor(C["accent"] if on and element == pe.PE_IndicatorCheckBox else C["bg2"]))
            if element == pe.PE_IndicatorCheckBox:
                painter.drawRoundedRect(rect, 4, 4)
                if on:
                    pen = QPen(QColor(C["ink"]), 2.2)
                    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                    painter.setPen(pen)
                    s = rect.width()
                    path = QPainterPath(QPointF(rect.x() + s * 0.26, rect.y() + s * 0.52))
                    path.lineTo(rect.x() + s * 0.43, rect.y() + s * 0.68)
                    path.lineTo(rect.x() + s * 0.75, rect.y() + s * 0.34)
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawPath(path)
            else:
                painter.drawEllipse(rect)
                if on:
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QColor(C["accent"]))
                    painter.drawEllipse(rect.center(), size * 0.27, size * 0.27)
            painter.restore()
            return
        if element == pe.PE_FrameFocusRect:
            return
        if element == pe.PE_IndicatorItemViewItemDrop:
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(C["accent"]))
            rect = option.rect
            painter.drawRoundedRect(QRectF(rect.left() + 6, rect.top() - 1.5, max(rect.width() - 12, 20), 3), 1.5, 1.5)
            painter.restore()
            return
        super().drawPrimitive(element, option, painter, widget)


class Switch(QCheckBox):
    """웹 화면과 같은 켜기/끄기 스위치. QCheckBox라서 신호·테스트는 그대로 쓴다."""

    def __init__(self, text: str = ""):
        super().__init__(text)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFont(make_font(10, QFont.Weight.DemiBold))

    def sizeHint(self):
        metrics = QFontMetrics(self.font())
        width = 36 + (12 + metrics.horizontalAdvance(self.text()) if self.text() else 0)
        return QSize(width + 2, max(22, metrics.height() + 4))

    def minimumSizeHint(self):
        return self.sizeHint()

    def hitButton(self, pos):
        return self.rect().contains(pos)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        top = (self.height() - 20) / 2
        draw_switch(painter, QRectF(0, top, 36, 20), self.isChecked(), self.isEnabled())
        if self.text():
            painter.setPen(QColor(C["text"] if self.isEnabled() else C["faint"]))
            painter.setFont(self.font())
            painter.drawText(QRect(48, 0, self.width() - 48, self.height()),
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.text())
        painter.end()


class Combo(QComboBox):
    """펼침 화살표를 직접 그리는 선택 상자 (스타일시트를 쓰면 기본 화살표가 사라진다)."""

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setOpacity(1.0 if self.isEnabled() else 0.45)
        painter.drawPixmap(QRect(self.width() - 26, (self.height() - 14) // 2, 14, 14),
                           icon_pixmap("down", C["muted"], 14))
        painter.end()


# ------------------------------------------------------------ 모드 목록
class Bridge(QObject):
    completed = Signal(object)
    focus = Signal()
    exit = Signal()


def worst_issue(mod) -> str | None:
    if mod.get("error") or any(i["level"] == "error" for i in mod.get("issues", [])):
        return "error"
    if any(i["level"] == "warn" for i in mod.get("issues", [])):
        return "warn"
    return None


class ModDelegate(QStyledItemDelegate):
    """모드 목록 한 줄: 손잡이 · 스위치 · 그림 · 이름과 배지 · 문제 표시."""

    HEIGHT = 62

    def __init__(self, window: "MainWindow"):
        super().__init__(window)
        self.window = window

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), self.HEIGHT)

    @staticmethod
    def parts(rect: QRect):
        r = QRect(rect).adjusted(2, 2, -2, -2)
        cy = r.center().y()
        grip = QRect(r.left() + 6, cy - 8, 12, 16)
        switch = QRect(grip.right() + 8, cy - 10, 36, 20)
        thumb = QRect(switch.right() + 12, cy - 22, 44, 44)
        flag = QRect(r.right() - 28, cy - 9, 18, 18)
        text = QRect(thumb.right() + 12, r.top(), flag.left() - thumb.right() - 18, r.height())
        return r, grip, switch, thumb, flag, text

    def paint(self, painter, option, index):
        mod = index.data(MOD_ROLE) or {}
        on = Qt.CheckState(index.data(Qt.ItemDataRole.CheckStateRole)) == Qt.CheckState.Checked
        state = option.state
        selected = bool(state & QStyle.StateFlag.State_Selected)
        hover = bool(state & QStyle.StateFlag.State_MouseOver)
        enabled = bool(state & QStyle.StateFlag.State_Enabled)
        r, grip, switch, thumb, flag, text = self.parts(option.rect)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        box = QRectF(r).adjusted(0.5, 0.5, -0.5, -0.5)
        if selected:
            gradient = QLinearGradient(box.topLeft(), box.topRight())
            gradient.setColorAt(0, QColor(255, 225, 26, 26))
            gradient.setColorAt(0.7, QColor(C["bg2"]))
            painter.setBrush(QBrush(gradient))
            painter.setPen(QPen(QColor(255, 225, 26, 150), 1))
        else:
            painter.setBrush(QColor(C["bg2"]))
            painter.setPen(QPen(QColor(C["line2"] if hover else C["bg2"]), 1))
        painter.drawRoundedRect(box, 7, 7)
        painter.drawPixmap(grip, icon_pixmap("grip", C["faint"], 16))
        draw_switch(painter, QRectF(switch), on, enabled)
        painter.setOpacity(1.0 if on else 0.5)
        pixmap = self.window.mod_pixmap(mod, mod.get("icon"), 44)
        if pixmap is not None:
            painter.drawPixmap(thumb, rounded(pixmap, 6))
        else:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(C["panel3"]))
            painter.drawRoundedRect(QRectF(thumb), 6, 6)
            painter.drawPixmap(thumb.adjusted(12, 12, -12, -12), icon_pixmap("package", C["faint"], 20))
        name_font = make_font(10, QFont.Weight.DemiBold)
        painter.setFont(name_font)
        painter.setPen(QColor(C["text"]))
        name_rect = QRect(text.left(), text.top() + 10, text.width(), 20)
        painter.drawText(name_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         QFontMetrics(name_font).elidedText(mod.get("name", ""), Qt.TextElideMode.ElideRight, text.width()))
        painter.setOpacity(1.0)
        # 배지와 켜짐/꺼짐
        badge_font = make_font(8, QFont.Weight.DemiBold)
        metrics = QFontMetrics(badge_font)
        x, y = text.left(), text.top() + 33
        badges = []
        if mod.get("version"):
            badges.append((str(mod["version"]), "accent"))
        if mod.get("error"):
            badges.append((tr("mod.load_error"), "err"))
        elif mod.get("mode") in ("multi", "single"):
            badges.append((tr("mod.options"), "plain"))
        for caption, tone in badges:
            width = metrics.horizontalAdvance(caption) + 14
            if x + width > text.right():
                break
            pill = QRectF(x, y, width, 18)
            back, fore = {"accent": (QColor(255, 225, 26, 28), C["accent"]), "err": (QColor(255, 93, 80, 32), C["err"]),
                          "plain": (QColor(C["panel3"]), C["muted"])}[tone]
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(back)
            painter.drawRoundedRect(pill, 9, 9)
            painter.setFont(badge_font)
            painter.setPen(QColor(fore))
            painter.drawText(pill, Qt.AlignmentFlag.AlignCenter, caption)
            x += width + 6
        painter.setFont(make_font(8.5))
        painter.setPen(QColor(C["muted"]))
        painter.drawText(QRect(x, y, max(0, text.right() - x), 18), Qt.AlignmentFlag.AlignVCenter,
                         tr("mod.on" if on else "mod.off"))
        worst = worst_issue(mod)
        if worst:
            painter.drawPixmap(flag, icon_pixmap("error" if worst == "error" else "warn",
                                                 C["err"] if worst == "error" else C["warn"], 18))
        painter.restore()

    def editorEvent(self, event, model, option, index):
        kind = event.type()
        if kind in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease, QEvent.Type.MouseButtonDblClick):
            switch = self.parts(option.rect)[2].adjusted(-6, -10, 6, 10)
            if event.button() == Qt.MouseButton.LeftButton and switch.contains(event.position().toPoint()):
                if kind == QEvent.Type.MouseButtonRelease and not self.window.blocked:
                    on = Qt.CheckState(index.data(Qt.ItemDataRole.CheckStateRole)) == Qt.CheckState.Checked
                    model.setData(index, Qt.CheckState.Unchecked if on else Qt.CheckState.Checked,
                                  Qt.ItemDataRole.CheckStateRole)
                return True  # 스위치를 누르면 선택·끌기를 시작하지 않는다
        return False

    def helpEvent(self, event, view, option, index):
        switch = self.parts(option.rect)[2]
        mod = index.data(MOD_ROLE) or {}
        on = Qt.CheckState(index.data(Qt.ItemDataRole.CheckStateRole)) == Qt.CheckState.Checked
        from PySide6.QtWidgets import QToolTip
        text = tr("switch.on_title" if on else "switch.off_title") if switch.contains(event.pos()) \
            else mod.get("name", "") + "\n" + tr("mod.drag")
        QToolTip.showText(event.globalPos(), text, view)
        return True


class ModList(QListWidget):
    reordered = Signal(list)
    archives = Signal(list)
    files_hover = Signal()

    def __init__(self, window: "MainWindow"):
        super().__init__()
        self.setObjectName("modList")
        self.setItemDelegate(ModDelegate(window))
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setMouseTracking(True)
        self.setSpacing(2)
        self.setMinimumWidth(300)
        self.viewport().setAutoFillBackground(False)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            self.files_hover.emit()
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            self.archives.emit([u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()])
            event.acceptProposedAction()
            return
        super().dropEvent(event)
        self.reordered.emit([self.item(i).data(USER_ROLE) for i in range(self.count())])


class DropOverlay(QWidget):
    """파일을 창 위로 끌고 오면 보이는 '놓으면 추가' 안내. 놓은 파일은 dropped로 보낸다."""

    dropped = Signal(list)

    def __init__(self, parent):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.hide()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(8, 9, 12, 205))
        box = QRectF(0, 0, 420, 190)
        box.moveCenter(QRectF(self.rect()).center())
        painter.setBrush(QColor(255, 225, 26, 13))
        pen = QPen(QColor(C["accent"]), 2, Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.drawRoundedRect(box, 16, 16)
        painter.drawPixmap(QRect(int(box.center().x()) - 17, int(box.top()) + 38, 34, 34),
                           icon_pixmap("upload", C["accent"], 34))
        painter.setPen(QColor(C["text"]))
        painter.setFont(make_font(13, QFont.Weight.DemiBold))
        painter.drawText(QRectF(box.left(), box.top() + 84, box.width(), 30), Qt.AlignmentFlag.AlignCenter,
                         tr("drop.overlay"))
        painter.setPen(QColor(C["muted"]))
        painter.setFont(make_font(9.5))
        painter.drawText(QRectF(box.left(), box.top() + 116, box.width(), 24), Qt.AlignmentFlag.AlignCenter,
                         ".zip · .7z · .rar")
        painter.end()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self.hide()

    def dropEvent(self, event):
        self.hide()
        self.dropped.emit([u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()])
        event.acceptProposedAction()


class Hero(QWidget):
    """상세 화면 위쪽: 흐리게 깔린 모드 그림 위에 그림·이름·배지."""

    def __init__(self, pixmap: QPixmap | None, title: str, badges: list[QLabel]):
        super().__init__()
        self.setFixedHeight(210)
        self.background = None
        if pixmap is not None:
            # 아주 작게 줄였다가 크게 늘리면 흐린 배경이 된다 (GPU 없이 가볍다).
            small = pixmap.toImage().scaled(24, 24, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                            Qt.TransformationMode.SmoothTransformation)
            self.background = QPixmap.fromImage(small)  # 화면 배율과 상관없이 픽셀 그대로 늘려 그린다
        layout = QHBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(20)
        image = QLabel()
        image.setFixedSize(150, 150)
        image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if pixmap is not None:
            image.setPixmap(rounded(pixmap, 10))
        else:
            image.setStyleSheet(f"background: {C['panel3']}; border-radius: 10px;")
            image.setPixmap(icon_pixmap("package", C["faint"], 48))
        layout.addWidget(image, 0, Qt.AlignmentFlag.AlignBottom)
        text = QVBoxLayout()
        text.setSpacing(8)
        text.addStretch()
        name = label(title, "heroTitle", font=make_font(18, QFont.Weight.DemiBold, FONT_DISPLAY))
        text.addWidget(name)
        chips = QHBoxLayout()
        chips.setSpacing(6)
        for chip in badges:
            chips.addWidget(chip)
        chips.addStretch()
        text.addLayout(chips)
        layout.addLayout(text, 1)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        rect = QRectF(self.rect())
        clip = QPainterPath()
        clip.addRoundedRect(rect.adjusted(0, 0, 0, 20), 9, 9)  # 아래 모서리는 잘려 나가 위쪽만 둥글다
        painter.setClipPath(clip)
        if self.background is not None:
            source = QRectF(0, 0, self.background.width(), self.background.height())
            scale = max(rect.width() * 1.15 / source.width(), rect.height() * 1.15 / source.height())
            target = QRectF(0, 0, source.width() * scale, source.height() * scale)
            target.moveCenter(rect.center())
            painter.drawPixmap(target, self.background, source)
            painter.fillRect(rect, QColor(0, 0, 0, 120))
        else:
            painter.fillRect(rect, QColor(C["panel2"]))
        fade = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        fade.setColorAt(0.45, QColor(20, 23, 29, 0))
        fade.setColorAt(1.0, QColor(20, 23, 29, 170))
        painter.fillRect(rect, QBrush(fade))
        painter.end()


class Fold(QFrame):
    """눌러서 펼치고 접는 칸 (웹 화면의 <details>)."""

    def __init__(self, title: str, extra: str, body: QWidget, opened: bool, on_toggle):
        super().__init__()
        self.setObjectName("fold")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.header = button(f"{title}   {extra}" if extra else title, self.toggle, "fold")
        self.header.setFont(make_font(10, QFont.Weight.DemiBold))
        self.header.setIconSize(QSize(14, 14))
        layout.addWidget(self.header)
        self.body = body
        layout.addWidget(body)
        self.on_toggle = on_toggle
        self.set_open(opened)

    def set_open(self, opened: bool):
        self.opened = opened
        self.body.setVisible(opened)
        self.header.setIcon(icon("down" if opened else "right", C["muted"], 14))

    def toggle(self):
        self.set_open(not self.opened)
        self.on_toggle(self.opened)


# ------------------------------------------------------------ 메인 창
class MainWindow(QMainWindow):
    ready = Signal()

    def __init__(self, server: AppServer, *, diagnostic: bool = False):
        super().__init__()
        self.server = server
        self.backend = Backend(server)
        self.diagnostic = diagnostic
        self.state = None
        self.selected_id = None
        self.busy = False
        self.quiet_task = False
        self._pending = []
        self.closing = False
        self.restarting = False
        self.rendered = False
        self._load_failed = False
        self._painted = False
        self.current_lang = i18n.current()
        self.update_result = None
        self.settings_dialog = None
        self.open_folds: set[str] = set()
        self._images: dict = {}
        self.overlay = None
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="modocracy")
        self.bridge = Bridge(self)
        self.bridge.completed.connect(self._completed)
        self.bridge.focus.connect(self.focus_window)
        self.bridge.exit.connect(self.close)
        self.server.on_focus = self.bridge.focus.emit
        self.server.on_exit = self.bridge.exit.emit
        self.setMinimumSize(900, 600)
        fit_screen(self, 1280, 860)
        self.setAcceptDrops(True)
        self.statusBar().setSizeGripEnabled(False)
        self._build_ui()
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(15000)
        self.refresh_timer.timeout.connect(self.refresh_if_idle)
        self.refresh_timer.start()
        QTimer.singleShot(0, self.refresh)

    # ---- 화면 구성
    def _build_ui(self):
        self.setWindowTitle(tr("app.title") + (" · " + tr("native.diagnostic") if self.diagnostic else ""))
        root = QWidget()
        root.setObjectName("root")
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._build_topbar())
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(2)
        policy = self.progress.sizePolicy()
        policy.setRetainSizeWhenHidden(True)  # 보였다 사라져도 화면이 들썩이지 않게
        self.progress.setSizePolicy(policy)
        self.progress.hide()
        outer.addWidget(self.progress)
        body = QVBoxLayout()
        body.setContentsMargins(22, 14, 22, 18)
        body.setSpacing(14)
        outer.addLayout(body, 1)
        if self.diagnostic:
            note = frame("diagnostic")
            note_layout = QHBoxLayout(note)
            note_layout.setContentsMargins(14, 8, 14, 8)
            ico = QLabel()
            ico.setPixmap(icon_pixmap("info", C["warn"], 16))
            note_layout.addWidget(ico)
            note_layout.addWidget(label(tr("native.diagnostic_note"), "warnText"), 1)
            body.addWidget(note)
        body.addWidget(self._build_update_bar())
        body.addWidget(self._build_status())
        self.retry_button = button(tr("native.retry"), self.refresh, "outline", icon_name="refresh")
        self.retry_button.hide()
        body.addLayout(row(self.retry_button, None))
        self.splitter = QSplitter()
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(16)
        self.splitter.addWidget(self._build_list_panel())
        self.splitter.addWidget(self._build_detail_panel())
        self.splitter.setSizes([400, 820])
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        body.addWidget(self.splitter, 1)
        self.setCentralWidget(root)
        self.overlay = DropOverlay(root)
        self.overlay.dropped.connect(self.import_paths)
        self.render_detail()
        self.render_update()
        self.set_busy(self.busy)

    def _build_topbar(self):
        bar = frame("topbar")
        bar.setFixedHeight(66)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(22, 0, 22, 0)
        layout.setSpacing(12)
        mark = QLabel()
        mark.setPixmap(brand_pixmap(34))
        mark.setFixedSize(34, 34)
        layout.addWidget(mark)
        brand = QVBoxLayout()
        brand.setSpacing(1)
        brand.addStretch()
        brand.addWidget(label("HELLDIVERS 2 MOD MANAGER", "kicker", wrap=False, selectable=False,
                              font=make_font(7.5, QFont.Weight.Bold, FONT_DISPLAY, spacing=22)))
        title = QHBoxLayout()
        title.setSpacing(8)
        title.addWidget(label(APP_NAME, wrap=False, selectable=False,
                              font=make_font(14.5, QFont.Weight.DemiBold, FONT_DISPLAY)))
        version = label(f"v{__version__}", "faint", wrap=False, font=make_font(8.5))
        title.addWidget(version, 0, Qt.AlignmentFlag.AlignBottom)
        brand.addLayout(title)
        brand.addStretch()
        layout.addLayout(brand)
        layout.addStretch()
        self.game_button = button(tr("chip.set_game"), self.open_settings, "chip")
        self.game_button.setFont(make_font(9.5))
        self.game_button.setIconSize(QSize(16, 16))
        self.game_button.setMaximumWidth(460)
        layout.addWidget(self.game_button)
        self.settings_button = button(tr("settings.title"), self.open_settings, "ghost", icon_name="settings")
        layout.addWidget(self.settings_button)
        return bar

    def _build_update_bar(self):
        self.update_bar = frame("update")
        layout = QHBoxLayout(self.update_bar)
        layout.setContentsMargins(16, 8, 10, 8)
        layout.setSpacing(10)
        ico = QLabel()
        ico.setPixmap(icon_pixmap("info", C["info"], 18))
        layout.addWidget(ico)
        self.update_label = label("", font=make_font(10, QFont.Weight.DemiBold))
        layout.addWidget(self.update_label, 1)
        layout.addWidget(button(tr("update.changes"), self.show_release_notes, "ghost", small=True))
        self.update_button = button(tr("update.install"), self.install_update, "primary", small=True)
        layout.addWidget(self.update_button)
        self.update_bar.hide()
        return self.update_bar

    def _build_status(self):
        self.status_frame = frame("status", tone="idle")
        layout = QHBoxLayout(self.status_frame)
        layout.setContentsMargins(16, 12, 14, 12)
        layout.setSpacing(12)
        self.status_dot = label("", "dot", selectable=False)
        self.status_dot.setFixedSize(10, 10)
        layout.addWidget(self.status_dot, 0, Qt.AlignmentFlag.AlignTop)
        text = QVBoxLayout()
        text.setSpacing(2)
        self.status_title = label(tr("common.loading"), font=make_font(11.5, QFont.Weight.DemiBold))
        text.addWidget(self.status_title)
        self.status_lines = QVBoxLayout()
        self.status_lines.setSpacing(1)
        text.addLayout(self.status_lines)
        layout.addLayout(text, 1)
        self.purge_button = button(tr("btn.remove_all"), lambda: self.game_action("purge"), "ghost")
        self.launch_button = button(tr("btn.launch"), self.launch_game, icon_name="play")
        self.deploy_button = button(tr("btn.apply"), lambda: self.game_action("deploy"), "primary")
        self.deploy_button.setMinimumWidth(110)
        for widget in (self.purge_button, self.launch_button, self.deploy_button):
            layout.addWidget(widget, 0, Qt.AlignmentFlag.AlignVCenter)
        self.status_dot.setContentsMargins(0, 0, 0, 0)
        return self.status_frame

    def _build_list_panel(self):
        panel = frame("panel")
        panel.setMinimumWidth(330)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        head = QVBoxLayout()
        head.setContentsMargins(16, 14, 16, 12)
        head.setSpacing(4)
        title = QHBoxLayout()
        title.setSpacing(6)
        title.addWidget(label(tr("list.title"), wrap=False, selectable=False,
                              font=make_font(12, QFont.Weight.DemiBold, FONT_DISPLAY)))
        self.count_label = label("", "muted", wrap=False, selectable=False, font=make_font(10.5))
        title.addWidget(self.count_label)
        title.addStretch()
        self.add_button = button(tr("list.add"), self.pick_archives, "outline", small=True)
        title.addWidget(self.add_button)
        head.addLayout(title)
        head.addWidget(label(tr("list.hint"), "muted", font=make_font(9)))
        layout.addLayout(head)
        layout.addWidget(divider())
        content = QVBoxLayout()
        content.setContentsMargins(10, 8, 10, 10)
        content.setSpacing(4)
        self.edge_top = self._edge(tr("list.first"))
        content.addLayout(self.edge_top)
        self.mod_list = ModList(self)
        self.mod_list.currentItemChanged.connect(self.select_mod)
        self.mod_list.itemChanged.connect(self.toggle_item)
        self.mod_list.reordered.connect(self.reorder)
        self.mod_list.archives.connect(self.import_paths)
        self.mod_list.files_hover.connect(self.show_overlay)
        content.addWidget(self.mod_list, 1)
        self.edge_bottom = self._edge(tr("list.last"))
        content.addLayout(self.edge_bottom)
        self.empty_button = QPushButton()
        self.empty_button.setObjectName("emptyDrop")
        self.empty_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.empty_button.setMinimumHeight(200)
        self.empty_button.clicked.connect(lambda _checked=False: self.pick_archives())
        empty = QVBoxLayout(self.empty_button)
        empty.setContentsMargins(18, 24, 18, 24)
        empty.setSpacing(6)
        empty.addStretch()
        for widget in (self._icon_label("upload", C["accent"], 34),
                       label(tr("drop.empty_title"), wrap=True, selectable=False, font=make_font(10.5, QFont.Weight.DemiBold)),
                       label(tr("drop.empty_text"), "muted", wrap=True, selectable=False, font=make_font(9))):
            widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
            widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            empty.addWidget(widget)
        empty.addStretch()
        content.addWidget(self.empty_button)
        content.addStretch(0)
        layout.addLayout(content, 1)
        return panel

    def _edge(self, text):
        layout = QHBoxLayout()
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(8)
        layout.addWidget(label(text, "faint", wrap=False, selectable=False, font=make_font(8.5)))
        line = divider()
        layout.addWidget(line, 1)
        return layout

    @staticmethod
    def _icon_label(name, color, size):
        widget = QLabel()
        widget.setPixmap(icon_pixmap(name, color, size))
        return widget

    def _build_detail_panel(self):
        panel = frame("panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(1, 1, 1, 1)
        self.detail_scroll = QScrollArea()
        self.detail_scroll.setWidgetResizable(True)
        self.detail_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.detail_scroll.viewport().setAutoFillBackground(False)
        self.detail_scroll.setMinimumWidth(420)
        layout.addWidget(self.detail_scroll)
        return panel

    def _set_edges_visible(self, visible):
        for layout in (self.edge_top, self.edge_bottom):
            for i in range(layout.count()):
                layout.itemAt(i).widget().setVisible(visible)

    # ---- 작업 실행
    @property
    def blocked(self):
        """사용자가 기다려야 하는 작업 중인지 (뒤에서 조용히 하는 새로고침은 제외)."""
        return self.busy and not self.quiet_task

    def set_busy(self, value):
        self.busy = value
        show = value and not self.quiet_task
        self.progress.setVisible(show)
        for widget in (self.mod_list, self.detail_scroll, self.add_button, self.empty_button,
                       self.settings_button, self.game_button, self.launch_button, self.update_button):
            widget.setEnabled(not show and not self.closing)
        game = (self.state or {}).get("game", {})
        status = (self.state or {}).get("status", {})
        available = bool(self.state) and not game.get("problem") and not game.get("running")
        self.deploy_button.setEnabled(available and not show and not self.closing)
        self.purge_button.setEnabled(available and not show and not self.closing and
                                     bool(status.get("deployedFiles") or status.get("unmanaged")))

    def run_task(self, operation, success=None, *, refresh=False, failure=None, message="", quiet=False):
        if self.closing or self.restarting:
            return False
        if self.busy:
            if self.quiet_task and not quiet:
                # 뒤에서 조용히 새로고침하는 중이면 끝난 뒤 바로 이어서 한다 (누른 것이 사라지지 않게)
                self._pending.append(lambda: self.run_task(operation, success, refresh=refresh,
                                                           failure=failure, message=message))
                return True
            return False
        self.quiet_task = quiet
        self.set_busy(True)
        if not quiet:
            self.retry_button.hide()
        if message:
            self.statusBar().showMessage(message)

        def work():
            result = operation()
            return result, self.backend.state() if refresh else None

        future = self._executor.submit(work)
        future.add_done_callback(lambda f: self.bridge.completed.emit((f, success, failure)))
        return True

    @Slot(object)
    def _completed(self, payload):
        future, success, failure = payload
        self.quiet_task = False
        self.set_busy(False)
        try:
            result, state = future.result()
            if state is not None:
                self.apply_state(state)
            if not self.closing and success:
                success(result)
        except Exception as exc:
            if not isinstance(exc, (ModError, NeedsConfirm)):
                log.exception("화면 작업 실패")
            else:
                log.warning("작업 실패: %s", exc)
            if not self.closing:
                if failure:
                    failure(exc)
                else:
                    self.show_error(exc)
        if self.closing:
            self._pending.clear()
            QTimer.singleShot(0, self.close)
        elif not self.busy:
            self.set_busy(False)
            if self._pending:
                QTimer.singleShot(0, self._pending.pop(0))

    def show_error(self, exc):
        QMessageBox.warning(self, APP_NAME, str(exc) if isinstance(exc, ModError) else i18n.t("err.unknown"))

    def refresh(self, quiet=False):
        def failed(exc):
            self._load_failed = True
            self.status_title.setText(tr("native.load_failed"))
            self._set_status_lines([(str(exc), "errText")])
            self._set_tone("err")
            self.retry_button.show()
        self.run_task(self.backend.state, self.apply_state, failure=failed, quiet=quiet)

    def refresh_if_idle(self):
        if not self.busy and self.isVisible() and QApplication.activeModalWidget() is None:
            self.refresh(quiet=True)

    def apply_state(self, state):
        changed = state != self.state or self._load_failed
        self._load_failed = False
        self.state = state
        if state["lang"] != self.current_lang:
            self.current_lang = state["lang"]
            self._build_ui()
            self.render_update()
            changed = True
        if changed:
            self.render_state()
        if not self.rendered:
            self.rendered = True
            # 처음 구성한 위젯이 그려질 이벤트 루프 차례까지 기다린다.
            QTimer.singleShot(0, self.mark_ready)
        self.set_busy(self.busy)

    def mark_ready(self):
        if self.closing:
            return
        if not self._painted:
            QTimer.singleShot(20, self.mark_ready)
            return
        log.info("Qt UI ready: mods=%s, language=%s, size=%sx%s", len(self.state["mods"]),
                 self.current_lang, self.width(), self.height())
        self.ready.emit()
        if self.state["checkUpdates"]:
            QTimer.singleShot(200, self.check_update)

    # ---- 상태 표시
    def _set_tone(self, tone):
        for widget in (self.status_frame, self.status_dot):
            widget.setProperty("tone", tone)
            repolish(widget)

    def _set_status_lines(self, lines):
        while self.status_lines.count():
            item = self.status_lines.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for text, role in lines:
            self.status_lines.addWidget(label(text, role, font=make_font(9.5)))

    def render_state(self):
        state, game, status = self.state, self.state["game"], self.state["status"]
        # 게임 칩
        if game["problem"]:
            self.game_button.setText(tr("chip.set_game"))
            self.game_button.setIcon(dot_icon(C["err"]))
        else:
            self.game_button.setText("Helldivers 2" + (f" · {game['version']}" if game["version"] else "") +
                                     (tr("chip.running") if game["running"] else ""))
            self.game_button.setIcon(dot_icon(C["warn"] if game["running"] else C["ok"]))
        self.game_button.setToolTip(tr("chip.title_path", path=game["path"]) if game["path"] else tr("chip.title"))
        # 상태 카드
        enabled = sum(bool(m["enabled"] and not m["error"]) for m in state["mods"])
        kind = status["state"]
        params = dict(problem=game["problem"] or "", count=enabled, mods=status.get("deployedMods", 0),
                      files=status.get("deployedFiles", 0), time=fmt_time(status.get("deployedAt")))
        suffix = ("_some" if state["mods"] else "_none") if kind == "empty" else ""
        self.status_title.setText(tr(f"status.{kind}.title{suffix}", **params))
        lines = [(tr(f"status.{kind}.line{suffix}", **params), "muted")]
        if status.get("unmanaged"):
            lines.append((tr("status.unmanaged", count=len(status["unmanaged"])), "warnText"))
        for other in status.get("otherDeployments", []):
            lines.append((tr("status.other_deployment", path=other["gamePath"], count=other["files"]), "warnText"))
        if game["running"]:
            lines.append((tr("status.game_running"), "errText"))
        self._set_status_lines(lines)
        self._set_tone({"nogame": "err", "broken": "err", "pending": "warn", "dirty": "warn", "ok": "ok"}.get(kind, "idle"))
        # 모드 목록
        mods = state["mods"]
        ids = [m["id"] for m in mods]
        if self.selected_id not in ids:
            self.selected_id = ids[0] if ids else None
        self.count_label.setText(f"{sum(m['enabled'] for m in mods)}/{len(mods)}" if mods else "")
        scroll = self.mod_list.verticalScrollBar().value()
        self.mod_list.blockSignals(True)
        self.mod_list.clear()
        for m in mods:
            item = QListWidgetItem(m["name"])
            item.setData(USER_ROLE, m["id"])
            item.setData(MOD_ROLE, m)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if m["enabled"] else Qt.CheckState.Unchecked)
            self.mod_list.addItem(item)
            if m["id"] == self.selected_id:
                self.mod_list.setCurrentItem(item)
        self.mod_list.blockSignals(False)
        self.mod_list.verticalScrollBar().setValue(scroll)
        self.mod_list.setVisible(bool(mods))
        self._set_edges_visible(bool(mods))
        self.empty_button.setVisible(not mods)
        self.render_detail()

    def selected_mod(self):
        return next((m for m in (self.state or {}).get("mods", []) if m["id"] == self.selected_id), None)

    def select_mod(self, current, previous=None):
        self.selected_id = current.data(USER_ROLE) if current else None
        self.render_detail(reset_scroll=True)

    def toggle_item(self, item):
        self.change_mod(item.data(USER_ROLE), {"enabled": item.checkState() == Qt.CheckState.Checked})

    def command(self, path, body=None, success=None, failure=None, message=""):
        def failed(exc):
            if self.state:
                self.render_state()
            (failure or self.show_error)(exc)
        return self.run_task(lambda: self.backend.command(path, body), success, refresh=True,
                             failure=failed, message=message)

    def change_mod(self, mod_id, changes):
        self.command(f"/api/mods/{mod_id}", changes)

    def reorder(self, ids):
        self.command("/api/order", {"ids": ids})

    def move_mod(self, mod_id, offset):
        ids = [m["id"] for m in self.state["mods"]]
        pos = ids.index(mod_id)
        ids.remove(mod_id)
        ids.insert(len(ids) if offset is None else max(0, min(len(ids), pos + offset)), mod_id)
        self.reorder(ids)

    # ---- 그림
    def mod_pixmap(self, mod, url, size):
        """모드 폴더의 그림을 size에 맞게 읽는다. 주소(수정 시각 포함)가 같으면 다시 읽지 않는다."""
        if not url or not mod:
            return None
        ratio = self.devicePixelRatioF() or 1.0
        key = (url, size, ratio)
        if key in self._images:
            return self._images[key]
        if len(self._images) > 300:
            self._images.clear()
        pixmap = None
        rel = parse_qs(urlsplit(url).query).get("path", [""])[0]
        path = safe_join(self.server.library.mods_dir / mod["id"], rel)
        try:
            if path and path.suffix.lower() in RASTER_TYPES and path.stat().st_size <= 32 * 1024 * 1024:
                reader = QImageReader(str(path))
                reader.setAutoTransform(True)
                source = reader.size()
                if source.isValid():
                    target = QSize(int(size * ratio), int(size * ratio))
                    reader.setScaledSize(source.scaled(target, Qt.AspectRatioMode.KeepAspectRatioByExpanding))
                    image = reader.read()
                    if not image.isNull():
                        pixmap = QPixmap.fromImage(image)
                        if pixmap.width() > target.width() or pixmap.height() > target.height():
                            pixmap = pixmap.copy((pixmap.width() - target.width()) // 2,
                                                 (pixmap.height() - target.height()) // 2, target.width(), target.height())
                        pixmap.setDevicePixelRatio(ratio)
        except OSError:
            log.warning("미리보기 그림을 읽지 못함: %s", rel)
        self._images[key] = pixmap
        return pixmap

    # ---- 상세 화면
    def render_detail(self, reset_scroll=False):
        scroll = 0 if reset_scroll else self.detail_scroll.verticalScrollBar().value()
        panel = QWidget()
        panel.setObjectName("transparent")
        outer = QVBoxLayout(panel)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        mod = self.selected_mod()
        if not mod:
            outer.addStretch()
            empty = QVBoxLayout()
            empty.setSpacing(6)
            for widget in (self._icon_label("package", C["faint"], 40),
                           label(tr("detail.empty_title"), font=make_font(12, QFont.Weight.DemiBold), selectable=False),
                           label(tr("detail.empty_text"), "muted", selectable=False)):
                widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
                empty.addWidget(widget)
            outer.addLayout(empty)
            outer.addStretch()
        else:
            outer.addWidget(self._hero(mod))
            body = QVBoxLayout()
            body.setContentsMargins(22, 18, 22, 26)
            body.setSpacing(18)
            body.addLayout(self._toolbar(mod))
            callouts = self._callouts(mod)
            if callouts:
                body.addLayout(callouts)
            if mod.get("description"):
                section = QVBoxLayout()
                section.setSpacing(8)
                section.addWidget(section_label(tr("detail.description")))
                section.addWidget(label(mod["description"], "desc", font=make_font(10)))
                body.addLayout(section)
            self.render_options(body, mod)
            if not mod["error"]:
                body.addWidget(self._files(mod))
            if mod.get("hasReadme"):
                readme = button(tr("readme.title"), lambda: self.show_readme(mod), "fold", icon_name="right")
                readme.setIconSize(QSize(14, 14))
                holder = frame("fold")
                holder_layout = QVBoxLayout(holder)
                holder_layout.setContentsMargins(0, 0, 0, 0)
                holder_layout.addWidget(readme)
                body.addWidget(holder)
            body.addLayout(self._meta(mod))
            body.addStretch()
            outer.addLayout(body, 1)
        old = self.detail_scroll.takeWidget()
        if old:
            old.deleteLater()
        self.detail_scroll.setWidget(panel)
        self.detail_scroll.verticalScrollBar().setValue(scroll)

    def _hero(self, mod):
        badges = []
        if mod.get("version"):
            badges.append(badge(str(mod["version"]), "darkAccent"))
        badges.append(badge(tr("mod.on" if mod["enabled"] else "mod.off"), "darkOk" if mod["enabled"] else "dark"))
        if mod.get("gameVersion"):
            badges.append(badge(tr("detail.game_version", version=mod["gameVersion"]), "dark"))
        return Hero(self.mod_pixmap(mod, mod.get("icon"), 150), mod["name"], badges)

    def _toolbar(self, mod):
        toggle = Switch(tr("detail.in_use" if mod["enabled"] else "detail.not_in_use"))
        toggle.setChecked(mod["enabled"])
        toggle.setToolTip(tr("switch.on_title" if mod["enabled"] else "switch.off_title"))
        toggle.toggled.connect(lambda value: self.change_mod(mod["id"], {"enabled": value}))
        buttons = QWidget()
        buttons.setObjectName("transparent")
        tools = FlowLayout(buttons)
        policy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        policy.setHeightForWidth(True)
        buttons.setSizePolicy(policy)
        index = self.state["mods"].index(mod)
        last = len(self.state["mods"]) - 1
        for key, offset, enabled, name in (("up", -1, index > 0, "up"), ("down", 1, index < last, "down"),
                                           ("bottom", None, index < last, "bottom")):
            control = button(tr("detail." + key), lambda o=offset: self.move_mod(mod["id"], o),
                             icon_name=name, small=True, tip=tr("detail." + key + "_title"))
            control.setEnabled(enabled)
            tools.addWidget(control)
        tools.addWidget(button(tr("detail.folder"), lambda: self.open_target("mod", mod["id"]),
                               icon_name="folder", small=True, tip=tr("detail.folder_title")))
        tools.addWidget(button(tr("btn.delete"), lambda: self.delete_mod(mod), "danger", icon_name="trash", small=True))
        return row(toggle, 12, buttons)

    def _callouts(self, mod):
        issues = ([{"level": "error", "text": tr("detail.read_error", error=mod["error"])}] if mod["error"] else []) + mod["issues"]
        if not issues:
            return None
        layout = QVBoxLayout()
        layout.setSpacing(8)
        colors = {"error": C["err"], "warn": C["warn"], "info": C["info"]}
        for issue in issues:
            level = issue["level"] if issue["level"] in colors else "info"
            box = frame("callout", tone=level)
            box_layout = QHBoxLayout(box)
            box_layout.setContentsMargins(12, 10, 12, 10)
            box_layout.setSpacing(10)
            box_layout.addWidget(self._icon_label({"error": "error", "warn": "warn"}.get(level, "info"), colors[level], 16),
                                 0, Qt.AlignmentFlag.AlignTop)
            box_layout.addWidget(label(issue["text"], font=make_font(9.5)), 1)
            if issue.get("fix") == "bottom":
                box_layout.addWidget(button(tr("detail.move_bottom"), lambda: self.move_mod(mod["id"], None), small=True),
                                     0, Qt.AlignmentFlag.AlignVCenter)
            layout.addWidget(box)
        return layout

    def render_options(self, layout, mod):
        if mod["error"] or not mod.get("options") or mod.get("mode") == "fixed":
            return
        section = QVBoxLayout()
        section.setSpacing(8)
        section.addWidget(section_label(tr("detail.choose_one" if mod["mode"] == "single" else "detail.options")))
        group = QButtonGroup(self.detail_scroll)
        # 생성 중 선택 신호는 연결하지 않고, 사용자 입력만 백엔드로 보낸다.
        for index, option in enumerate(mod["options"]):
            if mod["mode"] == "single":
                active = mod["state"]["choice"] == index
            else:
                active = bool(mod["state"]["enabledOptions"][index])
            box = frame("option", active="true" if active else "false")
            box_layout = QHBoxLayout(box)
            box_layout.setContentsMargins(12, 10, 12, 10)
            box_layout.setSpacing(12)
            text_layout = QVBoxLayout()
            text_layout.setSpacing(4)
            if mod["mode"] == "single":
                control = QRadioButton(option["name"])
                group.addButton(control)
                control.setChecked(active)
                control.clicked.connect(lambda _checked=False, i=index: self.change_mod(mod["id"], {"choice": i}))
            else:
                control = QCheckBox(option["name"])
                control.setChecked(active)
                control.setEnabled(len(mod["options"]) > 1)
                control.toggled.connect(lambda value, i=index: self.change_array(mod, "enabledOptions", i, value))
            control.setFont(make_font(10, QFont.Weight.DemiBold))
            control.setCursor(Qt.CursorShape.PointingHandCursor)
            text_layout.addWidget(control)
            if option["description"]:
                desc = label(option["description"], "muted", font=make_font(9))
                desc.setContentsMargins(28, 0, 0, 0)
                text_layout.addWidget(desc)
            image = option["image"]
            if option["subs"] and mod["mode"] == "multi":
                combo = Combo()
                combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
                combo.setMinimumContentsLength(18)
                combo.setMaximumWidth(380)
                combo.addItems([s["name"] for s in option["subs"]])
                chosen = mod["state"]["selectedSubs"][index]
                combo.setCurrentIndex(chosen)
                combo.setEnabled(bool(mod["state"]["enabledOptions"][index]))
                combo.setAccessibleName(tr("detail.suboption_aria", name=option["name"]))
                combo.currentIndexChanged.connect(lambda value, i=index: self.change_array(mod, "selectedSubs", i, value))
                sub_row = QHBoxLayout()
                sub_row.setContentsMargins(28, 4, 0, 0)
                sub_row.addWidget(combo)
                sub_row.addStretch()
                text_layout.addLayout(sub_row)
                sub = option["subs"][chosen]
                if sub["description"]:
                    desc = label(sub["description"], "muted", font=make_font(9))
                    desc.setContentsMargins(28, 0, 0, 0)
                    text_layout.addWidget(desc)
                image = sub["image"] or image
            box_layout.addLayout(text_layout, 1)
            pixmap = self.mod_pixmap(mod, image, 64) if image else None
            if pixmap is not None:
                picture = QLabel()
                picture.setPixmap(rounded(pixmap, 6))
                picture.setFixedSize(64, 64)
                box_layout.addWidget(picture, 0, Qt.AlignmentFlag.AlignTop)
            section.addWidget(box)
        layout.addLayout(section)

    def _files(self, mod):
        key = f"{mod['id']}:files"
        body = QWidget()
        body.setObjectName("transparent")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(12, 0, 12, 12)
        layout.setSpacing(8)
        if mod["files"]:
            table = QTableWidget(len(mod["files"]), 4)
            table.setHorizontalHeaderLabels([tr("files.source"), "", tr("files.target"), tr("files.size")])
            table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
            table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            table.setShowGrid(False)
            table.setWordWrap(False)
            table.setTextElideMode(Qt.TextElideMode.ElideMiddle)
            table.verticalHeader().hide()
            table.verticalHeader().setDefaultSectionSize(28)
            table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            header = table.horizontalHeader()
            header.setFont(make_font(9, QFont.Weight.DemiBold))
            header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
            header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
            header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
            table.setColumnWidth(1, 26)
            mono = make_font(9, families=FONT_MONO)
            for i, file in enumerate(mod["files"]):
                for j, text in enumerate((file["source"], "→", file["target"] or "—", fmt_size(file["size"]))):
                    item = QTableWidgetItem(text)
                    item.setToolTip(text if j != 1 else "")
                    item.setFont(mono if j in (0, 2) else make_font(9))
                    if j in (1, 3):
                        item.setForeground(QColor(C["muted"] if j == 3 else C["faint"]))
                    table.setItem(i, j, item)
            visible = min(len(mod["files"]), 10)
            table.setFixedHeight(32 + visible * 28 + 2)
            layout.addWidget(table)
        else:
            layout.addWidget(label(tr("files.none"), "muted", font=make_font(9.5)))
        layout.addWidget(label(tr("files.note_on" if mod["enabled"] else "files.note_off"), "muted", font=make_font(9)))

        def toggled(opened):
            (self.open_folds.add if opened else self.open_folds.discard)(key)
        return Fold(tr("files.title"), tr("files.sets", count=len(mod["files"])), body, key in self.open_folds, toggled)

    def _meta(self, mod):
        section = QVBoxLayout()
        section.setSpacing(8)
        section.addWidget(section_label(tr("meta.title")))
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(4)
        requires = []
        for req in mod.get("requires", []):
            text = tr("meta.at_least", name=req["name"], revision=req["revision"]) if req.get("revision") else req["name"]
            requires.append(tr("meta.optional", label=text) if req.get("optional") else text)
        row_index = 0
        for key, value in (("source", mod.get("sourceName")), ("added", fmt_time(mod.get("addedAt"))),
                           ("updated", fmt_time(mod.get("updatedAt"))), ("game_version", mod.get("gameVersion")),
                           ("requires", ", ".join(requires)), ("guid", mod.get("guid"))):
            if value:
                grid.addWidget(label(tr("meta." + key), "muted", wrap=False, font=make_font(9)), row_index, 0,
                               Qt.AlignmentFlag.AlignTop)
                grid.addWidget(label(str(value), font=make_font(9, families=FONT_MONO if key == "guid" else None)),
                               row_index, 1)
                row_index += 1
        grid.setColumnStretch(1, 1)
        section.addLayout(grid)
        return section

    def change_array(self, mod, key, index, value):
        values = list(mod["state"][key])
        values[index] = value
        self.change_mod(mod["id"], {key: values})

    # ---- 대화 상자
    def choose(self, title, text, actions, *, danger=False):
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setText(text)
        buttons = []
        for i, (caption, value) in enumerate(actions):
            btn = box.addButton(caption, QMessageBox.ButtonRole.RejectRole if i == 0 else QMessageBox.ButtonRole.ActionRole)
            if i == len(actions) - 1 and i > 0:
                btn.setProperty("variant", "dangerSolid" if danger else "primary")
            elif i == 0:
                btn.setProperty("variant", "ghost")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            buttons.append((btn, value))
        box.setDefaultButton(buttons[0][0])
        box.setEscapeButton(buttons[0][0])
        box.exec()
        return next((value for btn, value in buttons if btn == box.clickedButton()), None)

    def delete_mod(self, mod):
        if self.choose(tr("delete.title"), tr("delete.text", name=mod["name"]) + "\n\n" + tr("delete.note"),
                       [(tr("btn.cancel"), False), (tr("btn.delete"), True)], danger=True):
            self.command(f"/api/mods/{mod['id']}/delete", success=lambda _: self.statusBar().showMessage(tr("delete.done", name=mod["name"]), 6000))

    def pick_archives(self):
        paths, _ = QFileDialog.getOpenFileNames(self, tr("list.add"), "", "Mods (*.zip *.7z *.rar)")
        self.import_paths(paths)

    def import_paths(self, paths):
        self.overlay.hide()
        if self.blocked or self.closing:
            self.statusBar().showMessage(tr("import.busy"), 6000)
            return
        accepted = [Path(p) for p in paths if Path(p).suffix.lower() in (".zip", ".7z", ".rar")]
        rejected = [Path(p).name for p in paths if Path(p) not in accepted]
        if rejected:
            QMessageBox.warning(self, APP_NAME, tr("import.only_archives", names=", ".join(rejected)))
        if not accepted:
            return

        def next_file(index):
            if self.closing or index >= len(accepted):
                return
            path = accepted[index]
            def done(result):
                self.selected_id = result["id"]
                self.render_state()
                self.statusBar().showMessage(tr("import.replaced" if result["updated"] else "import.added", name=result["name"]), 6000)
                next_file(index + 1)
            def failed(exc):
                self.show_error(exc)
                next_file(index + 1)
            self.run_task(lambda: self.backend.import_file(path), done, refresh=True, failure=failed,
                          message=tr("import.progress", name=path.name, counter=f" ({index + 1}/{len(accepted)})"))
        next_file(0)

    def game_action(self, kind, *, mode="ask", launch_after=False, confirmed=False):
        if self.blocked or not self.state:
            return
        if not confirmed:
            if kind == "purge":
                if not self.choose(tr("purge.title"), tr("purge.text") + "\n\n" + tr("purge.note"),
                                   [(tr("btn.cancel"), False), (tr("btn.remove_all"), True)], danger=True):
                    return
            else:
                broken = [m for m in self.state["mods"] if m["enabled"] and
                          (m["error"] or any(i["level"] == "error" for i in m["issues"]))]
                if broken and not self.choose(tr("confirm_broken.title"), tr("confirm_broken.text") + "\n\n" +
                                              "\n".join(m["name"] for m in broken),
                                              [(tr("btn.cancel"), False), (tr("confirm_broken.apply"), True)]):
                    return
        def done(result):
            moved = tr("result.moved") if result.get("backup") else ""
            if kind == "purge":
                message = tr("result.purged", count=result["removed"], moved=moved)
            elif result.get("modCount"):
                message = tr("result.deployed", mods=result["modCount"], files=result["fileCount"], moved=moved)
            else:
                message = tr("result.cleared", moved=moved)
            self.statusBar().showMessage(message, 8000)
            if launch_after:
                self.launch_now()
        def failed(exc):
            if not isinstance(exc, NeedsConfirm):
                self.show_error(exc)
                return
            groups = []
            for group in exc.unmanaged:
                match = tr("unmanaged.same", name=group["match"]) if group.get("match") else tr("unmanaged.unknown")
                groups.append(f"{group['name']} · {match}")
            actions = [(tr("btn.cancel"), None)]
            if kind == "purge":
                actions.append((tr("unmanaged.keep"), "keep"))
            actions.append((tr("unmanaged.move_apply" if kind == "deploy" else "unmanaged.move"), "move"))
            choice = self.choose(tr("unmanaged.title"), tr("unmanaged.text") + "\n\n" + "\n".join(groups) +
                                 "\n\n" + tr("unmanaged.deploy_text" if kind == "deploy" else "unmanaged.purge_text"), actions)
            if choice:
                self.game_action(kind, mode=choice, launch_after=launch_after, confirmed=True)
        self.command(f"/api/{kind}", {"unmanaged": mode}, done, failed,
                     tr("btn.applying" if kind == "deploy" else "btn.removing"))

    def launch_game(self):
        if self.blocked or not self.state:
            return
        if self.state["status"]["state"] in ("pending", "dirty", "broken") and not self.state["game"]["running"]:
            choice = self.choose(tr("launch.title"), tr("launch.text"), [(tr("btn.cancel"), None),
                                 (tr("launch.anyway"), "launch"), (tr("launch.apply"), "deploy")])
            if choice is None:
                return
            if choice == "deploy":
                self.game_action("deploy", launch_after=True)
                return
        self.launch_now()

    def launch_now(self):
        self.command("/api/launch-game", success=lambda _: self.statusBar().showMessage(tr("launch.started"), 6000))

    def open_target(self, target, mod_id=None):
        self.command("/api/open", {"target": target, "id": mod_id})

    def text_dialog(self, title, text):
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        fit_screen(dialog, 760, 560)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        layout.addWidget(label(title, font=make_font(13, QFont.Weight.DemiBold, FONT_DISPLAY)))
        editor = QTextEdit()
        editor.setReadOnly(True)
        editor.setFont(make_font(9.5, families=FONT_MONO))
        editor.setPlainText(text)
        layout.addWidget(editor, 1)
        layout.addLayout(row(None, button(tr("btn.close"), dialog.accept)))
        dialog.exec()
        dialog.deleteLater()

    def show_readme(self, mod):
        self.run_task(lambda: self.backend.readme(mod["id"]), lambda text: self.text_dialog(tr("readme.title"), text))

    def open_settings(self):
        if self.blocked or not self.state:
            return
        dialog = SettingsDialog(self)
        self.settings_dialog = dialog
        dialog.exec()
        self.settings_dialog = None
        dialog.deleteLater()

    # ---- 업데이트
    def check_update(self, manual=False):
        def done(result):
            self.update_result = result
            self.render_update()
            if manual and not result["newer"]:
                QMessageBox.information(self, APP_NAME, tr("update.latest", version=result["current"]))
        def failed(exc):
            if manual:
                self.show_error(exc)
        # 켤 때 하는 확인은 뒤에서 조용히 한다 (인터넷이 느려도 화면을 막지 않게)
        self.run_task(lambda: update_info(self.server, force=manual), done, failure=failed, quiet=not manual)

    def render_update(self):
        result = self.update_result
        self.update_bar.setVisible(bool(result and result["newer"]))
        if result:
            self.update_label.setText(tr("update.available", version=result["latest"]) +
                                      tr("update.current", version=result["current"]))
            self.update_button.setText(tr("update.install" if result["canInstall"] else "update.download"))
            self.update_button.setToolTip(result.get("problem") or "")

    def show_release_notes(self):
        if self.update_result:
            self.text_dialog(tr("update.changes"), self.update_result["notes"])

    def install_update(self):
        if self.blocked or not self.update_result:
            return
        if not self.update_result["canInstall"]:
            self.open_target("release")
            return
        if not self.choose(tr("update.confirm_title", version=self.update_result["latest"]),
                           tr("update.confirm_text") + "\n\n" + tr("update.confirm_note"),
                           [(tr("btn.later"), False), (tr("update.install"), True)]):
            return
        def done(result):
            self.restarting = True
            self.centralWidget().setEnabled(False)
            self.statusBar().showMessage(tr("update.restarting", version=result["version"]))
        self.run_task(lambda: self.backend.command("/api/update/install"), done, message=tr("update.downloading"))

    # ---- 창 이벤트
    @Slot()
    def focus_window(self):
        if self.isMinimized():
            self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()

    @Slot()
    def show_overlay(self):
        if self.blocked:
            return
        self.overlay.setGeometry(self.centralWidget().rect())
        self.overlay.show()
        self.overlay.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.overlay is not None and self.overlay.isVisible():
            self.overlay.setGeometry(self.centralWidget().rect())

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and not self.blocked:
            event.acceptProposedAction()
            self.show_overlay()

    def paintEvent(self, event):
        super().paintEvent(event)
        self._painted = True

    def dropEvent(self, event):
        self.import_paths([u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()])
        event.acceptProposedAction()

    def closeEvent(self, event):
        if self.blocked:
            self.closing = True
            self.centralWidget().setEnabled(False)
            self.statusBar().showMessage(tr("native.wait_close"))
            event.ignore()
            return
        if self.busy:
            # 조용한 새로고침·업데이트 확인은 끝나길 기다렸다가 바로 닫는다
            self.closing = True
            event.ignore()
            return
        # 개발용 웹 API에서 시작한 작업도 중간에 끊지 않는다.
        with self.server.client_lock:
            self.server.stopping = True
            active = self.server.active_operations
        if active:
            self.closing = True
            QTimer.singleShot(100, self.close)
            event.ignore()
            return
        self.closing = True
        self.refresh_timer.stop()
        self._executor.shutdown(wait=False)
        self.server.on_focus = None
        self.server.on_exit = None
        log.info("Qt 창 종료")
        event.accept()


# ------------------------------------------------------------ 설정 창
class SettingsDialog(QDialog):
    def __init__(self, window: MainWindow):
        super().__init__(window)
        self.window = window
        self.pending = False
        self.setWindowTitle(tr("settings.title"))
        fit_screen(self, 640, 720)
        state = window.state
        self.initial = dict(gamePath=state["game"]["path"] or "", language=state["language"], checkUpdates=state["checkUpdates"])
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        head = QHBoxLayout()
        head.setSpacing(10)
        head.setContentsMargins(24, 20, 24, 8)
        head.addWidget(self._icon(icon_pixmap("settings", C["accent"], 20)))
        head.addWidget(label(tr("settings.title"), font=make_font(15, QFont.Weight.DemiBold, FONT_DISPLAY), selectable=False))
        head.addStretch()
        outer.addLayout(head)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.viewport().setAutoFillBackground(False)
        contents = QWidget()
        contents.setObjectName("transparent")
        layout = QVBoxLayout(contents)
        layout.setContentsMargins(24, 8, 24, 8)
        layout.setSpacing(14)
        scroll.setWidget(contents)
        outer.addWidget(scroll, 1)

        game = self._card(layout, tr("settings.game_folder"))
        self.path = QLineEdit(self.initial["gamePath"])
        self.path.setFont(make_font(9.5, families=FONT_MONO))
        game.addWidget(self.path)
        game.addLayout(row(button(tr("settings.browse"), self.browse, icon_name="folder", small=True),
                           button(tr("settings.detect"), self.detect, icon_name="refresh", small=True), None))
        self.help = label(tr("settings.game_help"), "muted", font=make_font(9))
        game.addWidget(self.help)

        library = self._card(layout, tr("settings.library"))
        path = label(state["paths"]["library"], "path", font=make_font(9, families=FONT_MONO))
        library.addWidget(path)
        library.addWidget(label(tr("settings.library_help"), "muted", font=make_font(9)))
        folders = row(button(tr("settings.open_library"), lambda: window.open_target("library"), small=True),
                      button(tr("settings.open_backups"), lambda: window.open_target("backups"), small=True), None)
        if window.diagnostic:
            folders.insertWidget(2, button(tr("settings.view_log"), lambda: window.open_target("log"), small=True))
        library.addLayout(folders)

        language = self._card(layout, tr("settings.language"))
        self.language = Combo()
        self.language.setMaximumWidth(300)
        for value, name in (("auto", tr("settings.language_auto")), ("ko", "한국어"), ("en", "English")):
            self.language.addItem(name, value)
        self.language.setCurrentIndex(self.language.findData(self.initial["language"]))
        language.addWidget(self.language)

        updates = self._card(layout, tr("settings.updates"))
        self.updates = QCheckBox(tr("settings.check_on_start"))
        self.updates.setCursor(Qt.CursorShape.PointingHandCursor)
        self.updates.setChecked(self.initial["checkUpdates"])
        updates.addWidget(self.updates)
        updates.addLayout(row(button(tr("settings.check_now"), self.check_update, small=True), 8,
                              label(tr("settings.version", version=__version__), "muted", wrap=False, font=make_font(9)), None))
        if not state["sevenZip"]:
            warn = frame("callout", tone="warn")
            warn_layout = QHBoxLayout(warn)
            warn_layout.setContentsMargins(12, 10, 12, 10)
            warn_layout.addWidget(self._icon(icon_pixmap("warn", C["warn"], 16)), 0, Qt.AlignmentFlag.AlignTop)
            warn_layout.addWidget(label(tr("settings.no_7zip"), font=make_font(9.5)), 1)
            layout.addWidget(warn)
        layout.addLayout(row(button(tr("native.licenses"), self.licenses, "ghost", small=True), None))
        layout.addStretch()

        outer.addWidget(divider())
        actions = row(None, button(tr("btn.close"), self.reject, "ghost"), button(tr("btn.save"), self.save, "primary"))
        actions.setContentsMargins(24, 14, 24, 16)
        outer.addLayout(actions)

    @staticmethod
    def _icon(pixmap):
        widget = QLabel()
        widget.setPixmap(pixmap)
        return widget

    @staticmethod
    def _card(parent_layout, title):
        card = frame("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(8)
        layout.addWidget(section_label(title))
        parent_layout.addWidget(card)
        return layout

    def set_help(self, text, role="muted"):
        self.help.setObjectName(role)
        repolish(self.help)
        self.help.setText(text)

    def browse(self):
        path = QFileDialog.getExistingDirectory(self, tr("settings.game_folder"), self.path.text())
        if path:
            self.path.setText(path)
            self.set_help(tr("settings.picked"), "okText")

    def task(self, operation, done, *, refresh=False):
        def finish(result):
            self.pending = False
            self.setEnabled(True)
            done(result)
        def failed(exc):
            self.pending = False
            self.setEnabled(True)
            self.set_help(str(exc), "errText")
        if self.window.run_task(operation, finish, refresh=refresh, failure=failed):
            self.pending = True
            self.setEnabled(False)

    def detect(self):
        def done(result):
            if result["path"]:
                self.path.setText(result["path"])
            self.set_help(tr("settings.found" if result["path"] else "settings.not_found"),
                          "okText" if result["path"] else "errText")
        self.task(lambda: self.window.backend.command("/api/detect-game"), done)

    def save(self):
        values = dict(gamePath=self.path.text(), language=self.language.currentData(), checkUpdates=self.updates.isChecked())
        changes = {k: v for k, v in values.items() if v != self.initial[k]}
        if not changes:
            if self.window.state["game"]["problem"]:
                self.set_help(self.window.state["game"]["problem"], "errText")
            else:
                self.accept()
            return
        def done(_):
            self.accept()
            self.window.statusBar().showMessage(tr("settings.saved"), 6000)
        self.task(lambda: self.window.backend.command("/api/settings", changes), done, refresh=True)

    def check_update(self):
        self.accept()
        self.window.check_update(manual=True)

    def licenses(self):
        path = Path(__file__).with_name("licenses.txt")
        self.window.text_dialog(tr("native.licenses"), path.read_text(encoding="utf-8"))

    def reject(self):
        if not self.pending:
            super().reject()


# ------------------------------------------------------------ 시작
def configure_qt(application):
    application.setStyle(Style())
    application.setApplicationName(APP_NAME)
    application.setApplicationVersion(__version__)
    application.setFont(make_font(10))
    palette = QPalette()
    for role, color in ((QPalette.ColorRole.Window, C["bg"]), (QPalette.ColorRole.WindowText, C["text"]),
                        (QPalette.ColorRole.Base, C["bg2"]), (QPalette.ColorRole.AlternateBase, C["panel2"]),
                        (QPalette.ColorRole.Text, C["text"]), (QPalette.ColorRole.Button, C["panel2"]),
                        (QPalette.ColorRole.ButtonText, C["text"]), (QPalette.ColorRole.Highlight, C["panel3"]),
                        (QPalette.ColorRole.HighlightedText, C["text"]), (QPalette.ColorRole.ToolTipBase, C["panel3"]),
                        (QPalette.ColorRole.ToolTipText, C["text"]), (QPalette.ColorRole.PlaceholderText, C["faint"]),
                        (QPalette.ColorRole.Link, C["accent"]), (QPalette.ColorRole.Mid, C["line2"]),
                        (QPalette.ColorRole.Dark, C["bg"]), (QPalette.ColorRole.Light, C["panel3"])):
        palette.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(C["faint"]))
    application.setPalette(palette)
    application.setStyleSheet(stylesheet())
    QImageReader.setAllocationLimit(64)


def run_window(server, icon_path, *, diagnostic=False):
    # QWidget의 기본 래스터 렌더링 사용. OpenGL/Quick/WebEngine 위젯을 만들지 않는다.
    previous_qt_handler = qInstallMessageHandler(lambda kind, context, message: log.warning("Qt %s: %s", kind, message))
    log.info("Qt 창 초기화: Python=%s Qt=%s OS=%s diagnostic=%s", platform.python_version(),
             qVersion(), platform.platform(), diagnostic)
    application = QApplication.instance() or QApplication([APP_NAME])
    configure_qt(application)
    if icon_path:
        application.setWindowIcon(QIcon(str(icon_path)))
    old_hook = sys.excepthook
    def exception_hook(kind, value, traceback):
        log.error("처리되지 않은 UI 오류", exc_info=(kind, value, traceback))
        QMessageBox.critical(None, APP_NAME, i18n.t("err.unknown"))
    sys.excepthook = exception_hook
    log.info("Runtime: Python=%s Qt=%s OS=%s platform=%s diagnostic=%s", platform.python_version(),
             qVersion(), platform.platform(), application.platformName(), diagnostic)
    # 모니터 모델명은 분석에 필요 없어서 남기지 않는다 (해상도·배율만)
    for number, screen in enumerate(application.screens(), 1):
        size = screen.geometry()
        log.info("Screen %s: %sx%s dpi=%s ratio=%s", number, size.width(), size.height(),
                 screen.logicalDotsPerInch(), screen.devicePixelRatio())
    window = MainWindow(server, diagnostic=diagnostic)
    window.ready.connect(updater.cleanup_leftovers)
    worker = threading.Thread(target=server.serve_forever, daemon=True, name="instance-server")
    worker.start()
    window.show()
    try:
        return application.exec()
    finally:
        window._executor.shutdown(wait=True)
        server.shutdown()
        worker.join(timeout=5)
        qInstallMessageHandler(previous_qt_handler)
        sys.excepthook = old_hook
