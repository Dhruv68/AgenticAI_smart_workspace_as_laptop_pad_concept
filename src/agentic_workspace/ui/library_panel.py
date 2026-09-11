"""Library tab (right dock): searchable notes + reloadable sessions.

Notes come from the sqlite workspace store (:mod:`tools.notes`); sessions
are the JSON files under ``data/sessions/``. Clicking a note shows it;
double-clicking a session asks the main window to load it.
"""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QSplitter,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ..storage.session import sessions_dir
from ..tools import notes as notes_store

INK_SOFT = "#5B5F58"
EMPTY = "#B7BBAF"


class LibraryPanel(QWidget):
    """Browse saved notes and session files."""

    sessionRequested = Signal(str)  # path to a session JSON file

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        title = QLabel("LIBRARY")
        title.setStyleSheet(
            "font-family: 'IBM Plex Mono', monospace; font-size: 10px;"
            f"color: {INK_SOFT}; letter-spacing: 1px;"
        )
        layout.addWidget(title)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Search notes…")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self.refresh)
        layout.addWidget(self._search)

        splitter = QSplitter(Qt.Orientation.Vertical)

        # -- notes list ----------------------------------------------------
        notes_box = QWidget()
        notes_layout = QVBoxLayout(notes_box)
        notes_layout.setContentsMargins(0, 0, 0, 0)
        notes_label = QLabel("Notes")
        notes_label.setStyleSheet(f"font-size: 11px; color: {INK_SOFT};")
        notes_layout.addWidget(notes_label)
        self._notes_list = QListWidget()
        self._notes_list.itemClicked.connect(self._show_note)
        notes_layout.addWidget(self._notes_list)
        splitter.addWidget(notes_box)

        # -- note detail ---------------------------------------------------
        self._detail = QTextBrowser()
        self._detail.setPlaceholderText("Select a note to read it.")
        self._detail.setOpenExternalLinks(False)
        splitter.addWidget(self._detail)

        # -- sessions ------------------------------------------------------
        sessions_box = QWidget()
        sessions_layout = QVBoxLayout(sessions_box)
        sessions_layout.setContentsMargins(0, 0, 0, 0)
        sessions_label = QLabel("Sessions (double-click to open)")
        sessions_label.setStyleSheet(f"font-size: 11px; color: {INK_SOFT};")
        sessions_layout.addWidget(sessions_label)
        self._sessions_list = QListWidget()
        self._sessions_list.itemDoubleClicked.connect(self._open_session)
        sessions_layout.addWidget(self._sessions_list)
        splitter.addWidget(sessions_box)

        splitter.setSizes([180, 180, 140])
        layout.addWidget(splitter, 1)

        self._note_ids: list[int] = []

    # -- API -----------------------------------------------------------------
    def refresh(self) -> None:
        """Reload notes (filtered) and sessions."""
        query = self._search.text().strip()
        self._notes_list.clear()
        self._note_ids.clear()
        if query:
            # fts search; fall back to substring on bad queries
            try:
                found = self._search_ids(query)
            except Exception:
                found = [n for n in notes_store.all_notes() if query.lower() in (n["title"] + n["snippet"]).lower()]
        else:
            found = notes_store.all_notes()
        for n in found:
            when = time.strftime("%b %d", time.localtime(n["created_at"]))
            item = QListWidgetItem(f"{n['title']}  ·  {when}")
            item.setData(Qt.ItemDataRole.UserRole, n["id"])
            item.setToolTip(n["snippet"])
            self._notes_list.addItem(item)
            self._note_ids.append(n["id"])
        if not found:
            item = QListWidgetItem("(no notes yet — accepted AI notes save here)")
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            item.setForeground(Qt.GlobalColor.gray)
            self._notes_list.addItem(item)

        self._sessions_list.clear()
        try:
            files = sorted(
                sessions_dir().glob("*.json"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
        except Exception:
            files = []
        for f in files[:50]:
            when = time.strftime("%b %d %H:%M", time.localtime(f.stat().st_mtime))
            item = QListWidgetItem(f"{f.stem}  ·  {when}")
            item.setData(Qt.ItemDataRole.UserRole, str(f))
            self._sessions_list.addItem(item)
        if not files:
            item = QListWidgetItem("(no saved sessions)")
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            item.setForeground(Qt.GlobalColor.gray)
            self._sessions_list.addItem(item)

    # -- internals -------------------------------------------------------------
    def _search_ids(self, query: str) -> list[dict]:
        text = notes_store.search_notes(query, limit=200)
        if text.startswith("No saved notes") or text.startswith("Empty"):
            return []
        ids: list[int] = []
        for line in text.splitlines():
            if line.startswith("#"):
                try:
                    ids.append(int(line[1:].split()[0]))
                except (ValueError, IndexError):
                    pass
        by_id = {n["id"]: n for n in notes_store.all_notes(limit=1000)}
        return [by_id[i] for i in ids if i in by_id]

    def _show_note(self, item: QListWidgetItem) -> None:
        note_id = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(note_id, int):
            return
        note = notes_store.get_note(note_id)
        if not note:
            return
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(note["created_at"]))
        self._detail.setHtml(
            f"<h3 style='margin-bottom:2px;'>{_esc(note['title'])}</h3>"
            f"<div style='color:{INK_SOFT}; font-size:11px; margin-bottom:8px;'>{when}</div>"
            f"<div style='white-space: pre-wrap;'>{_esc(note['text'])}</div>"
        )

    def _open_session(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(path, str):
            self.sessionRequested.emit(path)


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
