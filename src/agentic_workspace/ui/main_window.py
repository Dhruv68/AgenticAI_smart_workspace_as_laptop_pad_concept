"""Main window: topbar, toolbar, canvas, dock tabs, status bar.

Paper aesthetic ported from ``reference_canvas.html``. Owns the provider,
tool registry, agent runner, history list, sessions, screen analysis, and
the Gmail connection — the ask dialogs do the floating UI, this window
does everything else.
"""

from __future__ import annotations

import functools
import threading
import time
import webbrowser

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QDockWidget,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSlider,
    QStatusBar,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from ..agent import AgentRunner
from ..ai.ollama_client import OllamaClient
from ..canvas.canvas_widget import (
    ACCEPTED,
    AI_ACCENT,
    APP_BG,
    INK,
    INK_SOFT,
    PAPER_EDGE,
    InkCanvas,
)
from ..config import AppConfig
from ..models import HistoryEntry
from ..screen.capture import capture_primary_monitor_png
from ..storage.session import export_canvas_png, load_session, save_session, sessions_dir
from ..tools import Tool, ToolRegistry
from ..tools import gmail as gmail_tools
from ..tools import notes as notes_store
from ..tools.web import WEB_SEARCH_TOOL_PARAMS, make_browser_open_tool, web_search
from ..voice.tts import Speaker
from .ask_dialog import AgentDialog, CanvasAskController, ScreenAskDialog
from .history_panel import HistoryPanel
from .library_panel import LibraryPanel

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView

    WEBENGINE_AVAILABLE = True
except ImportError:
    QWebEngineView = None  # type: ignore
    WEBENGINE_AVAILABLE = False

COLORS = ["#23262B", "#5B4FE0", "#2B7A5B", "#B5443A"]

_GMAIL_SETUP_HELP = """To connect Gmail you need your own Google OAuth client (one-time setup):

1. console.cloud.google.com → create a project
2. APIs & Services → enable the Gmail API
3. OAuth consent screen → External → add yourself as a test user
4. Credentials → Create Credentials → OAuth client ID → Desktop app
5. Download the JSON and set GMAIL_CLIENT_SECRETS=/path/to/it.json in your .env
   (or save it as data/gmail_client_secrets.json)

Then click Connect Gmail again."""


class _PingWorker(QThread):
    """Check Ollama reachability off the UI thread."""

    done = Signal(bool)

    def __init__(self, provider, parent=None) -> None:
        super().__init__(parent)
        self._provider = provider

    def run(self) -> None:  # noqa: N802 (Qt naming)
        self.done.emit(bool(self._provider.ping()))


class MainWindow(QMainWindow):
    openUrlRequested = Signal(str)
    gmailConnectDone = Signal(str)  # "" on success, error text otherwise

    def __init__(self, config: AppConfig, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self.setWindowTitle("Smart Workspace · v0")

        # -- services ------------------------------------------------------
        self._provider = OllamaClient(
            config.ollama_base_url, config.ollama_model, config.ollama_timeout
        )
        self._registry = self._build_registry()
        self._agent_runner = AgentRunner(self._provider, self._registry)
        self._speaker = Speaker()
        self._history: list[HistoryEntry] = []
        self._current_session: str | None = None
        self._dirty = False

        # -- central: topbar + canvas --------------------------------------
        central = QWidget()
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)
        central_layout.addWidget(self._build_topbar())
        central_layout.addWidget(self._build_warning_bar())
        self._canvas = InkCanvas()
        self._canvas.set_tool(InkCanvas.TOOL_PEN)
        central_layout.addWidget(self._canvas, 1)
        self.setCentralWidget(central)

        self.addToolBar(Qt.ToolBarArea.LeftToolBarArea, self._build_toolbar())
        self._build_dock()
        self.setStatusBar(self._build_statusbar())
        self._build_menus()
        self._build_shortcuts()

        # -- ask controller -------------------------------------------------
        self._asker = CanvasAskController(
            self._canvas,
            self._provider,
            self._agent_runner,
            self._speaker,
            lambda: self._history_panel.history_context(),
            self,
        )
        self._canvas.regionSelected.connect(self._asker.ask_region)
        self._asker.historyLogged.connect(self._add_history)
        self._asker.noteAccepted.connect(
            lambda rect, text: self._canvas.add_ai_note(rect, text)
        )
        self._asker.noteSaved.connect(self._library.refresh)
        self._canvas.strokesChanged.connect(self._on_canvas_changed)

        self.openUrlRequested.connect(self._open_url_in_browser)
        self.gmailConnectDone.connect(self._on_gmail_connect_done)

        # -- startup Ollama check (non-blocking) -----------------------------
        self._ping = _PingWorker(self._provider, self)
        self._ping.done.connect(self._on_ollama_checked)
        self._ping.start()

    # -- construction ---------------------------------------------------------
    def _build_topbar(self) -> QWidget:
        bar = QFrame()
        bar.setStyleSheet(f"background: {APP_BG}; border: none;")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(18, 10, 18, 8)

        brand = QVBoxLayout()
        brand.setSpacing(0)
        name = QLabel("smart workspace <span style='color:#5B4FE0;'>·</span> v0")
        name.setStyleSheet("font-size: 17px; font-weight: 600;")
        sub = QLabel("STROKE-CAPTURE &amp; CIRCLE-TO-ASK PROTOTYPE")
        sub.setStyleSheet(
            "font-family: monospace; font-size: 10px; color: #5B5F58;"
        )
        brand.addWidget(name)
        brand.addWidget(sub)
        layout.addLayout(brand)
        layout.addStretch(1)

        hint = QLabel("draw freely &nbsp;·&nbsp; S to select &nbsp;·&nbsp; Ctrl+Shift+A for screen")
        hint.setStyleSheet("font-family: monospace; font-size: 10px; color: #5B5F58;")
        layout.addWidget(hint)

        self._agent_input = QLineEdit()
        self._agent_input.setPlaceholderText("Ask the agent — web, Gmail, notes…")
        self._agent_input.setFixedWidth(280)
        self._agent_input.returnPressed.connect(self._run_topbar_agent)
        layout.addWidget(self._agent_input)
        go = QPushButton("Go")
        go.setStyleSheet(
            f"background: {AI_ACCENT}; color: #fff; border-radius: 8px; padding: 6px 14px;"
        )
        go.clicked.connect(self._run_topbar_agent)
        layout.addWidget(go)

        self._gmail_btn = QPushButton("Connect Gmail")
        self._gmail_btn.setToolTip("Sign in with Google to let the agent read/send Gmail")
        self._gmail_btn.clicked.connect(self._connect_gmail)
        layout.addWidget(self._gmail_btn)
        return bar

    def _build_warning_bar(self) -> QFrame:
        self._warning = QFrame()
        self._warning.setStyleSheet(
            "background: #FFF7E6; border-bottom: 1px solid #E8D9A8;"
        )
        layout = QHBoxLayout(self._warning)
        layout.setContentsMargins(18, 6, 18, 6)
        self._warning_label = QLabel()
        self._warning_label.setStyleSheet("font-size: 12px; color: #7A5B00;")
        self._warning_label.setWordWrap(True)
        layout.addWidget(self._warning_label, 1)
        dismiss = QPushButton("Dismiss")
        dismiss.setStyleSheet("border: none; color: #7A5B00;")
        dismiss.clicked.connect(self._warning.hide)
        layout.addWidget(dismiss)
        self._warning.hide()
        return self._warning

    def _build_toolbar(self) -> QToolBar:
        bar = QToolBar("Tools")
        bar.setOrientation(Qt.Orientation.Vertical)
        bar.setMovable(False)
        bar.setStyleSheet(
            "QToolBar { background: #fff; border: 1px solid " + PAPER_EDGE + ";"
            " border-radius: 14px; spacing: 4px; padding: 8px; }"
            "QToolButton { border-radius: 9px; font-size: 16px; padding: 6px; }"
            "QToolButton:checked { background: #5B4FE0; color: #fff; }"
        )
        self._tool_actions: dict[str, QAction] = {}
        for tool, icon, tip, key in [
            ("pen", "✎", "Pen (P)", "P"),
            ("eraser", "▱", "Eraser (E)", "E"),
            ("select", "⬚", "Select region (S)", "S"),
        ]:
            action = QAction(icon, self)
            action.setToolTip(f"{tip}")
            action.setCheckable(True)
            action.triggered.connect(functools.partial(self._set_tool, tool))
            bar.addAction(action)
            self._tool_actions[tool] = action
        self._tool_actions["pen"].setChecked(True)
        bar.addSeparator()

        # color swatches
        for color in COLORS:
            btn = QPushButton()
            btn.setFixedSize(22, 22)
            btn.setCheckable(True)
            btn.setStyleSheet(
                f"QPushButton {{ background: {color}; border-radius: 11px;"
                " border: 2px solid #fff; }"
                "QPushButton:checked { border: 2px solid #5B4FE0; }"
            )
            btn.setToolTip(f"Ink color {color}")
            btn.clicked.connect(functools.partial(self._set_color, color, btn))
            bar.addWidget(btn)
            if not hasattr(self, "_swatches"):
                self._swatches = []
            self._swatches.append(btn)
        self._swatches[0].setChecked(True)

        self._size_slider = QSlider(Qt.Orientation.Vertical)
        self._size_slider.setRange(1, 14)
        self._size_slider.setValue(3)
        self._size_slider.setToolTip("Brush size")
        self._size_slider.valueChanged.connect(
            lambda v: self._canvas.set_width(float(v))
        )
        bar.addWidget(self._size_slider)
        bar.addSeparator()

        undo = QAction("↩", self)
        undo.setToolTip("Undo (Ctrl+Z)")
        undo.triggered.connect(self._canvas.undo)
        bar.addAction(undo)
        redo = QAction("↪", self)
        redo.setToolTip("Redo (Ctrl+Shift+Z)")
        redo.triggered.connect(self._canvas.redo)
        bar.addAction(redo)
        clear = QAction("🗑", self)
        clear.setToolTip("Clear canvas")
        clear.triggered.connect(self._clear_canvas)
        bar.addAction(clear)
        return bar

    def _build_dock(self) -> None:
        dock = QDockWidget("Workspace", self)
        dock.setAllowedAreas(
            Qt.DockWidgetArea.RightDockWidgetArea | Qt.DockWidgetArea.LeftDockWidgetArea
        )
        self._tabs = QTabWidget()
        self._history_panel = HistoryPanel()
        self._library = LibraryPanel()
        self._tabs.addTab(self._history_panel, "History")
        self._tabs.addTab(self._library, "Library")
        if WEBENGINE_AVAILABLE:
            self._browser = QWebEngineView()
        else:
            self._browser = QLabel(
                "Embedded browser unavailable.\n\n"
                "Install it with:\n`pip install PySide6-WebEngine`\n\n"
                "Pages will open in your system browser instead."
            )
            self._browser.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._browser.setWordWrap(True)
        browser_tab = QWidget()
        browser_layout = QVBoxLayout(browser_tab)
        browser_layout.setContentsMargins(0, 0, 0, 0)
        browser_layout.addWidget(self._browser)
        self._tabs.addTab(browser_tab, "Browser")
        dock.setWidget(self._tabs)
        dock.setMinimumWidth(250)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
        self._library.refresh()

    def _build_statusbar(self) -> QStatusBar:
        bar = QStatusBar()
        self._ollama_label = QLabel("● checking Ollama…")
        self._ollama_label.setStyleSheet("color: #5B5F58;")
        self._stroke_label = QLabel("0 strokes")
        bar.addWidget(self._ollama_label)
        bar.addPermanentWidget(self._stroke_label)
        return bar

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        for text, shortcut, slot in [
            ("&New session", "Ctrl+N", self._new_session),
            ("&Open session…", "Ctrl+O", self._open_session),
            ("&Save session", "Ctrl+S", self._save_session),
            ("&Export PNG…", "", self._export_png),
        ]:
            action = QAction(text, self)
            if shortcut:
                action.setShortcut(QKeySequence(shortcut))
            action.triggered.connect(slot)
            file_menu.addAction(action)
        file_menu.addSeparator()
        quit_action = QAction("&Quit", self)
        quit_action.setShortcut(QKeySequence("Ctrl+Q"))
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

    def _build_shortcuts(self) -> None:
        self._shortcuts: list[QShortcut] = []

        def add(key: str, slot):
            sc = QShortcut(QKeySequence(key), self)
            sc.setContext(Qt.ShortcutContext.WindowShortcut)
            sc.activated.connect(slot)
            self._shortcuts.append(sc)

        add("P", lambda: self._set_tool("pen"))
        add("E", lambda: self._set_tool("eraser"))
        add("S", lambda: self._set_tool("select"))
        add("Ctrl+Z", self._canvas.undo)
        add("Ctrl+Shift+Z", self._canvas.redo)
        add("Ctrl+Y", self._canvas.redo)
        add("Ctrl+Shift+A", self._screen_ask)
        esc = QShortcut(QKeySequence("Escape"), self)
        esc.setContext(Qt.ShortcutContext.WindowShortcut)
        esc.activated.connect(self._on_escape)

    # -- tool registry --------------------------------------------------------
    def _build_registry(self) -> ToolRegistry:
        registry = ToolRegistry()
        registry.register(
            Tool(
                name="web_search",
                description=(
                    "Search the web (no API key needed). Returns top results "
                    "with title, snippet, and URL."
                ),
                parameters=WEB_SEARCH_TOOL_PARAMS,
                func=web_search,
            )
        )
        registry.register(
            make_browser_open_tool(lambda url: self.openUrlRequested.emit(url))
        )
        secrets = self._config.gmail_client_secrets
        registry.register(
            Tool(
                name="gmail_search",
                description="Search the user's Gmail. Returns id, subject, from, date, snippet.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Gmail search query"},
                        "max_results": {"type": "integer", "default": 8},
                    },
                    "required": ["query"],
                },
                func=functools.partial(gmail_tools.gmail_search, _client_secrets=secrets),
            )
        )
        registry.register(
            Tool(
                name="gmail_read",
                description="Read one Gmail message by id (from gmail_search).",
                parameters={
                    "type": "object",
                    "properties": {"message_id": {"type": "string"}},
                    "required": ["message_id"],
                },
                func=functools.partial(gmail_tools.gmail_read, _client_secrets=secrets),
            )
        )
        registry.register(
            Tool(
                name="gmail_send",
                description=(
                    "Send an email. The app ALWAYS asks the user to confirm "
                    "the full draft first — just call it."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "to": {"type": "string"},
                        "subject": {"type": "string"},
                        "body": {"type": "string"},
                    },
                    "required": ["to", "body"],
                },
                func=functools.partial(gmail_tools.gmail_send, _client_secrets=secrets),
                gated=True,
            )
        )
        registry.register(
            Tool(
                name="save_note",
                description="Save a note to the local workspace store.",
                parameters={
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "text": {"type": "string"},
                    },
                    "required": ["title", "text"],
                },
                func=notes_store.save_note,
            )
        )
        registry.register(
            Tool(
                name="search_notes",
                description="Full-text search over the user's saved notes.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "limit": {"type": "integer", "default": 8},
                    },
                    "required": ["query"],
                },
                func=notes_store.search_notes,
            )
        )
        registry.register(
            Tool(
                name="list_notes",
                description="List recent saved notes, newest first.",
                parameters={
                    "type": "object",
                    "properties": {"limit": {"type": "integer", "default": 20}},
                },
                func=notes_store.list_notes,
            )
        )
        return registry

    # -- slots -----------------------------------------------------------------
    def _set_tool(self, tool: str) -> None:
        if self._typing():
            return
        self._canvas.set_tool(tool)
        for name, action in self._tool_actions.items():
            action.setChecked(name == tool)

    def _set_color(self, color: str, btn: QPushButton) -> None:
        self._canvas.set_color(color)
        for b in self._swatches:
            b.setChecked(b is btn)

    def _typing(self) -> bool:
        """True when focus is in a text field (don't hijack P/E/S)."""
        w = QApplication.focusWidget()
        return isinstance(w, (QLineEdit,)) or (
            w is not None and "TextEdit" in type(w).__name__
        )

    def _on_escape(self) -> None:
        self._asker.close()

    def _on_canvas_changed(self) -> None:
        self._dirty = True
        self._stroke_label.setText(f"{self._canvas.stroke_count()} strokes")

    def _clear_canvas(self) -> None:
        answer = QMessageBox.question(
            self, "Clear canvas", "Erase all strokes and AI notes?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._canvas.clear()

    # -- history ---------------------------------------------------------------
    def _add_history(self, entry: HistoryEntry) -> None:
        self._history.append(entry)
        self._history_panel.add_entry(entry)
        self._library.refresh()
        self._dirty = True

    # -- Ollama status -----------------------------------------------------------
    def _on_ollama_checked(self, ok: bool) -> None:
        model = self._config.ollama_model
        if ok:
            self._ollama_label.setText(f"● ollama · {model}")
            self._ollama_label.setStyleSheet(f"color: {ACCEPTED};")
            self._warning.hide()
        else:
            self._ollama_label.setText("● ollama unreachable")
            self._ollama_label.setStyleSheet("color: #B5443A;")
            self._warning_label.setText(
                "Couldn't reach Ollama — AI answers won't work until it's running. "
                f"Fix: <b>ollama serve</b>, then <b>ollama pull {model}</b>."
            )
            self._warning.show()

    # -- topbar agent --------------------------------------------------------------
    def _run_topbar_agent(self) -> None:
        task = self._agent_input.text().strip()
        if not task:
            return
        dlg = AgentDialog(task, self._agent_runner, self)
        dlg.noteSaved.connect(self._library.refresh)
        dlg.exec()
        self._agent_input.clear()

    # -- Gmail -----------------------------------------------------------------------
    def _connect_gmail(self) -> None:
        secrets = gmail_tools.client_secrets_path(self._config.gmail_client_secrets)
        if secrets is None:
            QMessageBox.information(self, "Connect Gmail", _GMAIL_SETUP_HELP)
            return
        if gmail_tools.is_connected():
            QMessageBox.information(self, "Gmail", "Gmail is already connected.")
            return
        self._gmail_btn.setEnabled(False)
        self._gmail_btn.setText("Connecting…")

        def work() -> None:
            result = gmail_tools.connect_interactive(secrets)
            self.gmailConnectDone.emit("" if result == "Gmail connected." else result)

        threading.Thread(target=work, daemon=True, name="gmail-connect").start()

    def _on_gmail_connect_done(self, error: str) -> None:
        self._gmail_btn.setEnabled(True)
        if error:
            self._gmail_btn.setText("Connect Gmail")
            QMessageBox.warning(self, "Gmail", error)
        else:
            self._gmail_btn.setText("Gmail ✓")

    # -- browser -----------------------------------------------------------------------
    def _open_url_in_browser(self, url: str) -> None:
        from PySide6.QtCore import QUrl

        self._tabs.setCurrentIndex(2)
        if WEBENGINE_AVAILABLE:
            self._browser.setUrl(QUrl(url))
        else:
            webbrowser.open(url)
            self.statusBar().showMessage(
                "Opened in system browser (install PySide6-WebEngine for the embedded tab).",
                6000,
            )

    # -- screen analysis -----------------------------------------------------------------
    def _screen_ask(self) -> None:
        self.hide()
        QTimer.singleShot(300, self._do_screen_capture)

    def _do_screen_capture(self) -> None:
        try:
            png = capture_primary_monitor_png()
        except RuntimeError as exc:
            self.show()
            self.raise_()
            QMessageBox.warning(self, "Screen capture", str(exc))
            return
        self.show()
        self.raise_()
        self.activateWindow()
        dlg = ScreenAskDialog(
            png, self._provider, self._agent_runner, self._speaker,
            lambda: self._history_panel.history_context(), self,
        )
        dlg.askCompleted.connect(
            lambda q, a: self._add_history(HistoryEntry(q, a, "accepted", "screen"))
        )
        dlg.exec()

    # -- sessions ---------------------------------------------------------------------------
    def _confirm_discard(self) -> bool:
        if not self._dirty:
            return True
        answer = QMessageBox.question(
            self, "Unsaved changes", "Discard unsaved changes?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _new_session(self) -> None:
        if not self._confirm_discard():
            return
        self._canvas.clear()
        self._history = []
        self._history_panel.clear()
        self._current_session = None
        self._dirty = False
        self._stroke_label.setText("0 strokes")

    def _open_session(self) -> None:
        if not self._confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Open session", str(sessions_dir()), "Session JSON (*.json)"
        )
        if path:
            self._load_session_path(path)

    def _load_session_path(self, path: str) -> None:
        try:
            data = load_session(path)
        except (ValueError, FileNotFoundError, OSError) as exc:
            QMessageBox.warning(self, "Open session", f"Couldn't open session:\n{exc}")
            return
        self._canvas.set_strokes(data["strokes"])
        self._canvas.set_notes(data["ai_notes"])
        self._history = data["history"]
        self._history_panel.set_history(self._history)
        self._current_session = path
        self._dirty = False
        self._stroke_label.setText(f"{self._canvas.stroke_count()} strokes")
        self.statusBar().showMessage(f"Opened {path}", 4000)

    def _save_session(self) -> None:
        path = self._current_session
        if path is None:
            default = time.strftime("session-%Y%m%d-%H%M%S.json")
            path, _ = QFileDialog.getSaveFileName(
                self, "Save session", str(sessions_dir() / default),
                "Session JSON (*.json)",
            )
            if not path:
                return
            self._current_session = path
        try:
            save_session(
                path, self._canvas.get_strokes(), self._canvas.get_notes(), self._history
            )
        except OSError as exc:
            QMessageBox.warning(self, "Save session", f"Couldn't save:\n{exc}")
            return
        self._dirty = False
        self._library.refresh()
        self.statusBar().showMessage(f"Saved {path}", 4000)

    def _export_png(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export PNG", str(sessions_dir() / "canvas.png"), "PNG image (*.png)"
        )
        if not path:
            return
        try:
            export_canvas_png(self._canvas, path)
        except OSError as exc:
            QMessageBox.warning(self, "Export PNG", f"Couldn't export:\n{exc}")
            return
        self.statusBar().showMessage(f"Exported {path}", 4000)

    # -- close ------------------------------------------------------------------------------
    def closeEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        if not self._confirm_discard():
            event.ignore()
            return
        self._speaker.stop()
        super().closeEvent(event)
