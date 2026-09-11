"""Workspace history panel (right dock, "History" tab).

Logs every Q/A interaction — accepted or dismissed, from canvas or screen —
newest first, with the accepted/dismissed styling from the HTML prototype.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..models import HistoryEntry

ACCEPTED = "#2B7A5B"
DISMISSED = "#C9877A"
INK = "#23262B"
INK_SOFT = "#5B5F58"
EMPTY = "#B7BBAF"


class HistoryPanel(QWidget):
    """Scrollable log of Q/A history entries."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(8)

        title = QLabel("WORKSPACE HISTORY")
        title.setStyleSheet(
            "font-family: 'IBM Plex Mono', monospace; font-size: 10px;"
            f"color: {INK_SOFT}; letter-spacing: 1px;"
        )
        outer.addWidget(title)

        self._empty = QLabel(
            "Accepted and dismissed hints will log here as workspace context."
        )
        self._empty.setWordWrap(True)
        self._empty.setStyleSheet(f"color: {EMPTY}; font-style: italic; font-size: 12px;")
        outer.addWidget(self._empty)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self._scroll.setVisible(False)

        self._inner = QWidget()
        self._items = QVBoxLayout(self._inner)
        self._items.setContentsMargins(0, 0, 4, 0)
        self._items.setSpacing(8)
        self._items.addStretch(1)
        self._scroll.setWidget(self._inner)
        outer.addWidget(self._scroll, 1)

        self._entries: list[HistoryEntry] = []

    # -- API ---------------------------------------------------------------
    def add_entry(self, entry: HistoryEntry) -> None:
        self._entries.append(entry)
        self._insert_widget(entry, at_top=True)

    def set_history(self, entries: list[HistoryEntry]) -> None:
        self._entries = list(entries)
        self._rebuild()

    def history_context(self, n: int = 3) -> str:
        """Last *n* entries formatted for the model's system prompt."""
        lines = []
        for e in self._entries[-n:]:
            q = e.question or "(no question, just asked for a hint)"
            lines.append(f"Q: {q} → A: {e.answer} [{e.status}]")
        return "\n".join(lines)

    def clear(self) -> None:
        self._entries.clear()
        self._rebuild()

    # -- internals -----------------------------------------------------------
    def _rebuild(self) -> None:
        while self._items.count() > 1:  # keep the trailing stretch
            child = self._items.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        for entry in reversed(self._entries):
            self._insert_widget(entry, at_top=False)
        self._refresh_empty()

    def _insert_widget(self, entry: HistoryEntry, at_top: bool) -> None:
        color = ACCEPTED if entry.status == "accepted" else DISMISSED
        source = f" · {entry.source}" if entry.source != "canvas" else ""
        label = QLabel(
            f"<div style='border-left: 2px solid {color}; padding: 2px 0 6px 10px;'>"
            f"<div style='font-weight: 500; color: {INK}; font-size: 12px;'>"
            f"{_esc(entry.question or 'General hint request')}</div>"
            f"<div style='color: {INK_SOFT}; font-size: 12px;'>{_esc(entry.answer)}</div>"
            f"<div style='font-family: monospace; font-size: 9px; color: {color};'>"
            f"{entry.status.upper()}{source}</div></div>"
        )
        label.setWordWrap(True)
        label.setTextFormat(Qt.TextFormat.RichText)
        self._items.insertWidget(0 if at_top else self._items.count() - 1, label)
        self._refresh_empty()

    def _refresh_empty(self) -> None:
        has = bool(self._entries)
        self._scroll.setVisible(has)
        self._empty.setVisible(not has)


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
