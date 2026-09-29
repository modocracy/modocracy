"""PySide6 Qt Widgets 화면. 브라우저·HTML·GPU 합성 없이 일반 위젯을 그린다."""
from __future__ import annotations

import logging
import platform
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from PySide6.QtCore import QObject, QSize, Qt, QTimer, Signal, Slot, qInstallMessageHandler, qVersion
from PySide6.QtGui import QColor, QIcon, QImageReader, QPalette, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog,
    QFileDialog, QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QProgressBar, QPushButton,
    QRadioButton, QScrollArea, QSplitter, QTableWidget, QTableWidgetItem,
    QTextEdit, QVBoxLayout, QWidget,
)

from . import APP_NAME, __version__, i18n, updater
from .core import ModError, NeedsConfirm, safe_join
from .native_backend import Backend
from .server import RASTER_TYPES, AppServer, update_info
from .ui_text import tr

log = logging.getLogger(__name__)
USER_ROLE = Qt.ItemDataRole.UserRole
STYLE = """
QWidget { color: #e3e8f0; font-family: 'Segoe UI', 'Malgun Gothic'; font-size: 10pt; }
QMainWindow, QDialog, QWidget#root { background: #0e1219; }
QFrame#card, QWidget#sidebar, QWidget#detail { background: #171e29; border-radius: 10px; }
QLabel { background: transparent; }
QLabel#title { font-size: 19pt; font-weight: 700; }
QLabel#heading { font-size: 13pt; font-weight: 600; }
QLabel#muted { color: #9dacc1; }
QLabel#warning { color: #ffd181; }
QLabel#error { color: #ffb0b6; }
QPushButton { background: #253145; border: 1px solid #3a4a63; border-radius: 6px; padding: 7px 12px; }
QPushButton:hover { background: #33455f; border-color: #738fad; }
QPushButton:pressed { background: #405778; }
QPushButton:focus { border: 1px solid #80c5ff; }
QPushButton:disabled { color: #778396; background: #1c2430; border-color: #2b3545; }
QPushButton#primary { background: #207bbc; border-color: #4bacef; font-weight: 600; }
QPushButton#primary:hover { background: #2795df; }
QPushButton#danger { color: #ffc0c6; }
QListWidget, QTableWidget, QLineEdit, QComboBox, QTextEdit {
    background: #111722; border: 1px solid #354258; border-radius: 5px;
    selection-background-color: #275982; selection-color: #ffffff;
}
QListWidget { padding: 4px; }
QListWidget::item { padding: 10px 5px; margin: 2px 0; border-radius: 5px; }
QListWidget::item:selected { background: #244764; }
QListWidget::item:hover { background: #223047; }
QLineEdit, QComboBox { padding: 6px; }
QComboBox QAbstractItemView { background: #202c3d; selection-background-color: #275982; }
QCheckBox, QRadioButton { spacing: 8px; padding: 4px 0; }
QCheckBox::indicator, QRadioButton::indicator { width: 16px; height: 16px; }
QHeaderView::section { background: #233045; border: 0; padding: 6px; }
QTableWidget { gridline-color: #2b394b; }
QScrollArea { border: 0; background: transparent; }
QScrollBar:vertical { background: #131a24; width: 12px; }
QScrollBar::handle:vertical { background: #46556c; min-height: 24px; border-radius: 5px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QSplitter::handle { background: #0e1219; width: 9px; }
QProgressBar { border: 0; background: #1a2739; max-height: 4px; }
QProgressBar::chunk { background: #51b9f4; }
QStatusBar { background: #0e1219; color: #acbbce; }
"""


def label(text: str = "", role: str = "", *, wrap: bool = True) -> QLabel:
    widget = QLabel(str(text))
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setWordWrap(wrap)
    widget.setObjectName(role)
    widget.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return widget


def button(text: str, action, role: str = "") -> QPushButton:
    widget = QPushButton(text)
    widget.setObjectName(role)
    widget.clicked.connect(lambda _checked=False: action())
    return widget


def row(*widgets) -> QHBoxLayout:
    layout = QHBoxLayout()
    for widget in widgets:
        if widget is None:
            layout.addStretch()
        else:
            layout.addWidget(widget)
    return layout


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


class Bridge(QObject):
    completed = Signal(object)
    focus = Signal()
    exit = Signal()


class ModList(QListWidget):
    reordered = Signal(list)
    archives = Signal(list)

    def __init__(self):
        super().__init__()
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setWordWrap(True)
        self.setMinimumWidth(240)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
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
        self.closing = False
        self.restarting = False
        self.rendered = False
        self._load_failed = False
        self._painted = False
        self.current_lang = i18n.current()
        self.update_result = None
        self.settings_dialog = None
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="modocracy")
        self.bridge = Bridge(self)
        self.bridge.completed.connect(self._completed)
        self.bridge.focus.connect(self.focus_window)
        self.bridge.exit.connect(self.close)
        self.server.on_focus = self.bridge.focus.emit
        self.server.on_exit = self.bridge.exit.emit
        self.setMinimumSize(760, 500)
        fit_screen(self, 1260, 840)
        self.setAcceptDrops(True)
        self._build_ui()
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(15000)
        self.refresh_timer.timeout.connect(self.refresh_if_idle)
        self.refresh_timer.start()
        QTimer.singleShot(0, self.refresh)

    def _build_ui(self):
        self.setWindowTitle(tr("app.title") + (" · " + tr("native.diagnostic") if self.diagnostic else ""))
        root = QWidget()
        root.setObjectName("root")
        layout = QVBoxLayout(root)
        layout.setContentsMargins(20, 16, 20, 12)
        layout.setSpacing(12)
        self.settings_button = button(tr("settings.title"), self.open_settings)
        self.launch_button = button(tr("btn.launch"), self.launch_game)
        self.game_button = button(tr("chip.set_game"), self.open_settings)
        self.brand = label(APP_NAME, "title", wrap=False)
        layout.addLayout(row(self.brand, label(f"v{__version__}", "muted"), None,
                             self.game_button, self.launch_button, self.settings_button))
        if self.diagnostic:
            layout.addWidget(label(tr("native.diagnostic_note"), "warning"))
        self.update_bar = QFrame()
        self.update_bar.setObjectName("card")
        update_layout = QHBoxLayout(self.update_bar)
        self.update_label = label()
        self.update_button = button(tr("update.install"), self.install_update, "primary")
        update_layout.addWidget(self.update_label, 1)
        update_layout.addWidget(button(tr("update.changes"), self.show_release_notes))
        update_layout.addWidget(self.update_button)
        layout.addWidget(self.update_bar)
        self.update_bar.hide()
        status = QFrame()
        status.setObjectName("card")
        status_layout = QHBoxLayout(status)
        status_text = QVBoxLayout()
        self.status_title = label(tr("common.loading"), "heading")
        self.status_description = label("", "muted")
        status_text.addWidget(self.status_title)
        status_text.addWidget(self.status_description)
        status_layout.addLayout(status_text, 1)
        self.purge_button = button(tr("btn.remove_all"), lambda: self.game_action("purge"))
        self.deploy_button = button(tr("btn.apply"), lambda: self.game_action("deploy"), "primary")
        status_layout.addWidget(self.purge_button)
        status_layout.addWidget(self.deploy_button)
        layout.addWidget(status)
        self.splitter = QSplitter()
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(14, 14, 14, 14)
        self.count_label = label(tr("list.title"), "heading")
        self.add_button = button(tr("list.add"), self.pick_archives)
        side.addLayout(row(self.count_label, None, self.add_button))
        side.addWidget(label(tr("list.hint"), "muted"))
        side.addWidget(label(tr("list.first"), "muted"))
        self.mod_list = ModList()
        self.mod_list.currentItemChanged.connect(self.select_mod)
        self.mod_list.itemChanged.connect(self.toggle_item)
        self.mod_list.reordered.connect(self.reorder)
        self.mod_list.archives.connect(self.import_paths)
        side.addWidget(self.mod_list, 1)
        self.empty_button = button(tr("drop.empty_title") + "\n\n" + tr("drop.empty_text"), self.pick_archives)
        self.empty_button.setMinimumHeight(180)
        side.addWidget(self.empty_button, 1)
        side.addWidget(label(tr("list.last"), "muted"))
        self.splitter.addWidget(sidebar)
        self.detail_scroll = QScrollArea()
        self.detail_scroll.setWidgetResizable(True)
        self.detail_scroll.setMinimumWidth(360)
        self.splitter.addWidget(self.detail_scroll)
        self.splitter.setSizes([390, 810])
        self.splitter.setStretchFactor(1, 1)
        layout.addWidget(self.splitter, 1)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.hide()
        layout.addWidget(self.progress)
        self.retry_button = button(tr("native.retry"), self.refresh)
        self.retry_button.hide()
        layout.addWidget(self.retry_button)
        self.setCentralWidget(root)
        self.render_detail()
        self.set_busy(self.busy)

    def set_busy(self, value):
        self.busy = value
        self.progress.setVisible(value)
        for widget in (self.mod_list, self.detail_scroll, self.add_button, self.empty_button,
                       self.settings_button, self.game_button, self.launch_button, self.update_button):
            widget.setEnabled(not value and not self.closing)
        game = (self.state or {}).get("game", {})
        status = (self.state or {}).get("status", {})
        available = bool(self.state) and not game.get("problem") and not game.get("running")
        self.deploy_button.setEnabled(available and not value and not self.closing)
        self.purge_button.setEnabled(available and not value and not self.closing and
                                     bool(status.get("deployedFiles") or status.get("unmanaged")))

    def run_task(self, operation, success=None, *, refresh=False, failure=None, message=""):
        if self.busy or self.closing or self.restarting:
            return False
        self.set_busy(True)
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
            QTimer.singleShot(0, self.close)
        elif not self.busy:
            self.set_busy(False)

    def show_error(self, exc):
        QMessageBox.warning(self, APP_NAME, str(exc) if isinstance(exc, ModError) else i18n.t("err.unknown"))

    def refresh(self):
        def failed(exc):
            self._load_failed = True
            self.status_title.setText(tr("native.load_failed"))
            self.status_description.setText(str(exc))
            self.retry_button.show()
        self.run_task(self.backend.state, self.apply_state, failure=failed)

    def refresh_if_idle(self):
        if not self.busy and self.isVisible() and QApplication.activeModalWidget() is None:
            self.refresh()

    def apply_state(self, state):
        changed = state != self.state or self._load_failed
        self._load_failed = False
        self.state = state
        if state["lang"] != self.current_lang:
            self.current_lang = state["lang"]
            self._build_ui()
            self.render_update()
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

    def render_state(self):
        state, game, status = self.state, self.state["game"], self.state["status"]
        self.game_button.setText(tr("chip.set_game") if game["problem"] else "Helldivers 2" +
                                 (f" · {game['version']}" if game["version"] else "") +
                                 (tr("chip.running") if game["running"] else ""))
        self.game_button.setToolTip(game["path"] or tr("chip.title"))
        enabled = sum(bool(m["enabled"] and not m["error"]) for m in state["mods"])
        kind = status["state"]
        params = dict(problem=game["problem"] or "", count=enabled, mods=status.get("deployedMods", 0),
                      files=status.get("deployedFiles", 0), time=fmt_time(status.get("deployedAt")))
        suffix = "_some" if state["mods"] else "_none"
        self.status_title.setText(tr(f"status.{kind}.title" + (suffix if kind == "empty" else ""), **params))
        lines = [tr(f"status.{kind}.line" + (suffix if kind == "empty" else ""), **params)]
        if status.get("unmanaged"):
            lines.append(tr("status.unmanaged", count=len(status["unmanaged"])))
        for other in status.get("otherDeployments", []):
            lines.append(tr("status.other_deployment", path=other["gamePath"], count=other["files"]))
        if game["running"]:
            lines.append(tr("status.game_running"))
        self.status_description.setText("\n".join(lines))
        mods = state["mods"]
        ids = [m["id"] for m in mods]
        if self.selected_id not in ids:
            self.selected_id = ids[0] if ids else None
        self.count_label.setText(f"{tr('list.title')}  {sum(m['enabled'] for m in mods)}/{len(mods)}")
        scroll = self.mod_list.verticalScrollBar().value()
        self.mod_list.blockSignals(True)
        self.mod_list.clear()
        for m in mods:
            meta = [str(m.get("version") or ""), tr("mod.on" if m["enabled"] else "mod.off")]
            if m["error"] or m["issues"]:
                meta.append(tr("mod.has_issues"))
            item = QListWidgetItem(m["name"] + "\n" + " · ".join(filter(None, meta)))
            item.setData(USER_ROLE, m["id"])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if m["enabled"] else Qt.CheckState.Unchecked)
            item.setToolTip(m["name"] + "\n" + tr("mod.drag"))
            self.mod_list.addItem(item)
            if m["id"] == self.selected_id:
                self.mod_list.setCurrentItem(item)
        self.mod_list.blockSignals(False)
        self.mod_list.verticalScrollBar().setValue(scroll)
        self.mod_list.setVisible(bool(mods))
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

    def image_label(self, mod, url, size=128):
        widget = label("", wrap=False)
        widget.setFixedSize(size, size)
        widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if not url:
            widget.setText("MOD")
            widget.setObjectName("muted")
            return widget
        rel = parse_qs(urlsplit(url).query).get("path", [""])[0]
        path = safe_join(self.server.library.mods_dir / mod["id"], rel)
        try:
            if path and path.suffix.lower() in RASTER_TYPES and path.stat().st_size <= 32 * 1024 * 1024:
                reader = QImageReader(str(path))
                reader.setAutoTransform(True)
                source_size = reader.size()
                if source_size.isValid():
                    ratio = self.devicePixelRatioF()
                    reader.setScaledSize(source_size.scaled(QSize(int(size * ratio), int(size * ratio)),
                                                            Qt.AspectRatioMode.KeepAspectRatio))
                    image = reader.read()
                    pixmap = QPixmap.fromImage(image)
                    pixmap.setDevicePixelRatio(ratio)
                    widget.setPixmap(pixmap)
        except OSError:
            log.warning("미리보기 그림을 읽지 못함: %s", rel)
        return widget

    def render_detail(self, reset_scroll=False):
        scroll = 0 if reset_scroll else self.detail_scroll.verticalScrollBar().value()
        panel = QWidget()
        panel.setObjectName("detail")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(14)
        mod = self.selected_mod()
        if not mod:
            layout.addStretch()
            layout.addWidget(label(tr("detail.empty_title"), "title"))
            layout.addWidget(label(tr("detail.empty_text"), "muted"))
            layout.addStretch()
        else:
            hero = QHBoxLayout()
            hero.addWidget(self.image_label(mod, mod.get("icon")))
            title = QVBoxLayout()
            title.addWidget(label(mod["name"], "title"))
            badges = [str(mod.get("version") or ""), tr("mod.on" if mod["enabled"] else "mod.off")]
            if mod.get("gameVersion"):
                badges.append(tr("detail.game_version", version=mod["gameVersion"]))
            title.addWidget(label(" · ".join(filter(None, badges)), "muted"))
            hero.addLayout(title, 1)
            layout.addLayout(hero)
            toggle = QCheckBox(tr("detail.in_use" if mod["enabled"] else "detail.not_in_use"))
            toggle.setChecked(mod["enabled"])
            toggle.toggled.connect(lambda value: self.change_mod(mod["id"], {"enabled": value}))
            tools = row(toggle, None)
            index = self.state["mods"].index(mod)
            for key, offset, enabled in (("up", -1, index > 0), ("down", 1, index < len(self.state["mods"]) - 1),
                                         ("bottom", None, index < len(self.state["mods"]) - 1)):
                control = button(tr("detail." + key), lambda o=offset: self.move_mod(mod["id"], o))
                control.setToolTip(tr("detail." + key + "_title"))
                control.setEnabled(enabled)
                tools.addWidget(control)
            layout.addLayout(tools)
            layout.addLayout(row(button(tr("detail.folder"), lambda: self.open_target("mod", mod["id"])),
                                 button(tr("btn.delete"), lambda: self.delete_mod(mod), "danger"), None))
            issues = ([{"level": "error", "text": tr("detail.read_error", error=mod["error"])}] if mod["error"] else []) + mod["issues"]
            for issue in issues:
                layout.addWidget(label(issue["text"], "error" if issue["level"] == "error" else "warning"))
                if issue.get("fix") == "bottom":
                    layout.addWidget(button(tr("detail.move_bottom"), lambda: self.move_mod(mod["id"], None)))
            if mod.get("description"):
                layout.addWidget(label(tr("detail.description"), "heading"))
                layout.addWidget(label(mod["description"]))
            self.render_options(layout, mod)
            if not mod["error"]:
                layout.addWidget(label(tr("files.title") + " · " + tr("files.sets", count=len(mod["files"])), "heading"))
                files = QTableWidget(len(mod["files"]), 3)
                files.setHorizontalHeaderLabels([tr("files.source"), tr("files.target"), tr("files.size")])
                files.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
                files.verticalHeader().hide()
                files.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
                files.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
                files.setMinimumHeight(100)
                files.setMaximumHeight(240)
                for i, file in enumerate(mod["files"]):
                    for j, text in enumerate((file["source"], file["target"] or "—", fmt_size(file["size"]))):
                        item = QTableWidgetItem(text)
                        item.setToolTip(text)
                        files.setItem(i, j, item)
                layout.addWidget(files if mod["files"] else label(tr("files.none"), "muted"))
                layout.addWidget(label(tr("files.note_on" if mod["enabled"] else "files.note_off"), "muted"))
            if mod.get("hasReadme"):
                layout.addWidget(button(tr("readme.title"), lambda: self.show_readme(mod)))
            layout.addWidget(label(tr("meta.title"), "heading"))
            requires = []
            for req in mod.get("requires", []):
                text = tr("meta.at_least", name=req["name"], revision=req["revision"]) if req.get("revision") else req["name"]
                requires.append(tr("meta.optional", label=text) if req.get("optional") else text)
            for key, value in (("source", mod.get("sourceName")), ("added", fmt_time(mod.get("addedAt"))),
                               ("updated", fmt_time(mod.get("updatedAt"))), ("game_version", mod.get("gameVersion")),
                               ("requires", ", ".join(requires)), ("guid", mod.get("guid"))):
                if value:
                    layout.addWidget(label(f"{tr('meta.' + key)}: {value}", "muted"))
            layout.addStretch()
        old = self.detail_scroll.takeWidget()
        if old:
            old.deleteLater()
        self.detail_scroll.setWidget(panel)
        self.detail_scroll.verticalScrollBar().setValue(scroll)

    def render_options(self, layout, mod):
        if mod["error"] or not mod.get("options") or mod.get("mode") == "fixed":
            return
        layout.addWidget(label(tr("detail.choose_one" if mod["mode"] == "single" else "detail.options"), "heading"))
        group = QButtonGroup(layout.parentWidget())
        # 생성 중 선택 신호는 연결하지 않고, 사용자 입력만 백엔드로 보낸다.
        for index, option in enumerate(mod["options"]):
            box = QFrame()
            box_layout = QHBoxLayout(box)
            text_layout = QVBoxLayout()
            if mod["mode"] == "single":
                control = QRadioButton(option["name"])
                group.addButton(control)
                control.setChecked(mod["state"]["choice"] == index)
                control.clicked.connect(lambda _checked=False, i=index: self.change_mod(mod["id"], {"choice": i}))
            else:
                control = QCheckBox(option["name"])
                control.setChecked(mod["state"]["enabledOptions"][index])
                control.setEnabled(len(mod["options"]) > 1)
                control.toggled.connect(lambda value, i=index: self.change_array(mod, "enabledOptions", i, value))
            text_layout.addWidget(control)
            if option["description"]:
                text_layout.addWidget(label(option["description"], "muted"))
            image = option["image"]
            if option["subs"] and mod["mode"] == "multi":
                combo = QComboBox()
                combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
                combo.setMinimumContentsLength(14)
                combo.addItems([s["name"] for s in option["subs"]])
                chosen = mod["state"]["selectedSubs"][index]
                combo.setCurrentIndex(chosen)
                combo.setEnabled(mod["state"]["enabledOptions"][index])
                combo.setAccessibleName(tr("detail.suboption_aria", name=option["name"]))
                combo.currentIndexChanged.connect(lambda value, i=index: self.change_array(mod, "selectedSubs", i, value))
                text_layout.addWidget(combo)
                sub = option["subs"][chosen]
                if sub["description"]:
                    text_layout.addWidget(label(sub["description"], "muted"))
                image = sub["image"] or image
            box_layout.addLayout(text_layout, 1)
            if image:
                box_layout.addWidget(self.image_label(mod, image, 96))
            layout.addWidget(box)

    def change_array(self, mod, key, index, value):
        values = list(mod["state"][key])
        values[index] = value
        self.change_mod(mod["id"], {key: values})

    def choose(self, title, text, actions):
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setText(text)
        buttons = []
        for i, (caption, value) in enumerate(actions):
            btn = box.addButton(caption, QMessageBox.ButtonRole.RejectRole if i == 0 else QMessageBox.ButtonRole.ActionRole)
            buttons.append((btn, value))
        box.setDefaultButton(buttons[0][0])
        box.setEscapeButton(buttons[0][0])
        box.exec()
        return next((value for btn, value in buttons if btn == box.clickedButton()), None)

    def delete_mod(self, mod):
        if self.choose(tr("delete.title"), tr("delete.text", name=mod["name"]) + "\n\n" + tr("delete.note"),
                       [(tr("btn.cancel"), False), (tr("btn.delete"), True)]):
            self.command(f"/api/mods/{mod['id']}/delete", success=lambda _: self.statusBar().showMessage(tr("delete.done", name=mod["name"])))

    def pick_archives(self):
        paths, _ = QFileDialog.getOpenFileNames(self, tr("list.add"), "", "Mods (*.zip *.7z *.rar)")
        self.import_paths(paths)

    def import_paths(self, paths):
        if self.busy or self.closing:
            self.statusBar().showMessage(tr("import.busy"))
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
                self.statusBar().showMessage(tr("import.replaced" if result["updated"] else "import.added", name=result["name"]))
                next_file(index + 1)
            def failed(exc):
                self.show_error(exc)
                next_file(index + 1)
            self.run_task(lambda: self.backend.import_file(path), done, refresh=True, failure=failed,
                          message=tr("import.progress", name=path.name, counter=f" ({index + 1}/{len(accepted)})"))
        next_file(0)

    def game_action(self, kind, *, mode="ask", launch_after=False, confirmed=False):
        if self.busy or not self.state:
            return
        if not confirmed:
            if kind == "purge":
                if not self.choose(tr("purge.title"), tr("purge.text") + "\n\n" + tr("purge.note"),
                                   [(tr("btn.cancel"), False), (tr("btn.remove_all"), True)]):
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
            self.statusBar().showMessage(message)
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
        if self.busy or not self.state:
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
        self.command("/api/launch-game", success=lambda _: self.statusBar().showMessage(tr("launch.started")))

    def open_target(self, target, mod_id=None):
        self.command("/api/open", {"target": target, "id": mod_id})

    def text_dialog(self, title, text):
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        fit_screen(dialog, 760, 560)
        layout = QVBoxLayout(dialog)
        editor = QTextEdit()
        editor.setReadOnly(True)
        editor.setPlainText(text)
        layout.addWidget(editor)
        layout.addWidget(button(tr("btn.close"), dialog.accept))
        dialog.exec()
        dialog.deleteLater()

    def show_readme(self, mod):
        self.run_task(lambda: self.backend.readme(mod["id"]), lambda text: self.text_dialog(tr("readme.title"), text))

    def open_settings(self):
        if self.busy or not self.state:
            return
        dialog = SettingsDialog(self)
        self.settings_dialog = dialog
        dialog.exec()
        self.settings_dialog = None
        dialog.deleteLater()

    def check_update(self, manual=False):
        def done(result):
            self.update_result = result
            self.render_update()
            if manual and not result["newer"]:
                QMessageBox.information(self, APP_NAME, tr("update.latest", version=result["current"]))
        def failed(exc):
            if manual:
                self.show_error(exc)
        self.run_task(lambda: update_info(self.server, force=manual), done, failure=failed)

    def render_update(self):
        result = self.update_result
        self.update_bar.setVisible(bool(result and result["newer"]))
        if result:
            self.update_label.setText(tr("update.available", version=result["latest"]))
            self.update_button.setText(tr("update.install" if result["canInstall"] else "update.download"))
            self.update_button.setToolTip(result.get("problem") or "")

    def show_release_notes(self):
        if self.update_result:
            self.text_dialog(tr("update.changes"), self.update_result["notes"])

    def install_update(self):
        if self.busy or not self.update_result:
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

    @Slot()
    def focus_window(self):
        if self.isMinimized():
            self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and not self.busy:
            event.acceptProposedAction()

    def paintEvent(self, event):
        super().paintEvent(event)
        self._painted = True

    def dropEvent(self, event):
        self.import_paths([u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()])
        event.acceptProposedAction()

    def closeEvent(self, event):
        if self.busy:
            self.closing = True
            self.centralWidget().setEnabled(False)
            self.statusBar().showMessage(tr("native.wait_close"))
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


class SettingsDialog(QDialog):
    def __init__(self, window: MainWindow):
        super().__init__(window)
        self.window = window
        self.pending = False
        self.setWindowTitle(tr("settings.title"))
        fit_screen(self, 680, 620)
        state = window.state
        self.initial = dict(gamePath=state["game"]["path"] or "", language=state["language"], checkUpdates=state["checkUpdates"])
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        contents = QWidget()
        layout = QVBoxLayout(contents)
        scroll.setWidget(contents)
        outer.addWidget(scroll, 1)
        layout.addWidget(label(tr("settings.game_folder"), "heading"))
        self.path = QLineEdit(self.initial["gamePath"])
        layout.addWidget(self.path)
        layout.addLayout(row(button(tr("settings.browse"), self.browse), button(tr("settings.detect"), self.detect), None))
        self.help = label(tr("settings.game_help"), "muted")
        layout.addWidget(self.help)
        layout.addWidget(label(tr("settings.library"), "heading"))
        layout.addWidget(label(state["paths"]["library"], "muted"))
        folders = row(button(tr("settings.open_library"), lambda: window.open_target("library")),
                      button(tr("settings.open_backups"), lambda: window.open_target("backups")), None)
        if window.diagnostic:
            folders.addWidget(button(tr("settings.view_log"), lambda: window.open_target("log")))
        layout.addLayout(folders)
        layout.addWidget(label(tr("settings.language"), "heading"))
        self.language = QComboBox()
        for value, name in (("auto", tr("settings.language_auto")), ("ko", "한국어"), ("en", "English")):
            self.language.addItem(name, value)
        self.language.setCurrentIndex(self.language.findData(self.initial["language"]))
        layout.addWidget(self.language)
        layout.addWidget(label(tr("settings.updates"), "heading"))
        self.updates = QCheckBox(tr("settings.check_on_start"))
        self.updates.setChecked(self.initial["checkUpdates"])
        layout.addWidget(self.updates)
        layout.addLayout(row(button(tr("settings.check_now"), self.check_update),
                             label(tr("settings.version", version=__version__), "muted"), None))
        if not state["sevenZip"]:
            layout.addWidget(label(tr("settings.no_7zip"), "warning"))
        layout.addWidget(button(tr("native.licenses"), self.licenses))
        layout.addStretch()
        outer.addLayout(row(None, button(tr("btn.close"), self.reject), button(tr("btn.save"), self.save, "primary")))

    def browse(self):
        path = QFileDialog.getExistingDirectory(self, tr("settings.game_folder"), self.path.text())
        if path:
            self.path.setText(path)
            self.help.setText(tr("settings.picked"))

    def task(self, operation, done, *, refresh=False):
        def finish(result):
            self.pending = False
            self.setEnabled(True)
            done(result)
        def failed(exc):
            self.pending = False
            self.setEnabled(True)
            self.help.setText(str(exc))
        if self.window.run_task(operation, finish, refresh=refresh, failure=failed):
            self.pending = True
            self.setEnabled(False)

    def detect(self):
        def done(result):
            if result["path"]:
                self.path.setText(result["path"])
            self.help.setText(tr("settings.found" if result["path"] else "settings.not_found"))
        self.task(lambda: self.window.backend.command("/api/detect-game"), done)

    def save(self):
        values = dict(gamePath=self.path.text(), language=self.language.currentData(), checkUpdates=self.updates.isChecked())
        changes = {k: v for k, v in values.items() if v != self.initial[k]}
        if not changes:
            if self.window.state["game"]["problem"]:
                self.help.setText(self.window.state["game"]["problem"])
            else:
                self.accept()
            return
        def done(_):
            self.accept()
            self.window.statusBar().showMessage(tr("settings.saved"))
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


def configure_qt(application):
    application.setStyle("Fusion")
    application.setApplicationName(APP_NAME)
    application.setApplicationVersion(__version__)
    palette = QPalette()
    for role, color in ((QPalette.ColorRole.Window, "#0e1219"), (QPalette.ColorRole.WindowText, "#e3e8f0"),
                        (QPalette.ColorRole.Base, "#111722"), (QPalette.ColorRole.AlternateBase, "#192536"),
                        (QPalette.ColorRole.Text, "#e3e8f0"), (QPalette.ColorRole.Button, "#253145"),
                        (QPalette.ColorRole.ButtonText, "#e3e8f0"), (QPalette.ColorRole.Highlight, "#275982"),
                        (QPalette.ColorRole.HighlightedText, "#ffffff"), (QPalette.ColorRole.ToolTipBase, "#253145"),
                        (QPalette.ColorRole.ToolTipText, "#e3e8f0")):
        palette.setColor(role, QColor(color))
    application.setPalette(palette)
    application.setStyleSheet(STYLE)
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
    for screen in application.screens():
        log.info("Screen: name=%s geometry=%s dpi=%s ratio=%s", screen.name(), screen.geometry(),
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
