"""Circle & Ask dialogs: floating ask panel, AI bubble, screen dialog.

Ports the interaction from ``reference_canvas.html``: select a region ->
ask panel pops up nearby -> "thinking…" bubble -> Accept / Dismiss / Speak.
Agent mode routes through the tool-calling loop instead of the direct
vision call. Everything AI runs in worker threads; the UI never blocks.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QImage, QPixmap, QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..agent.worker import AgentWorker
from ..ai.worker import AskWorker
from ..models import HistoryEntry
from ..tools import notes as notes_store

ACCENT = "#5B4FE0"
ACCENT_SOFT = "#EDEBFC"
INK = "#23262B"
INK_SOFT = "#5B5F58"
LINE = "#C9CDC2"
PAPER_EDGE = "#DFE2DA"

PANEL_WIDTH = 260


# -- floating ask panel ------------------------------------------------------
class AskPanel(QWidget):
    """Small "what about this region?" panel floating near the selection."""

    asked = Signal(str, bool)  # question, agent_mode
    cancelled = Signal()

    def __init__(self, question_hint: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setFixedWidth(PANEL_WIDTH)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            "AskPanel { background: #fff; border: 1px solid " + PAPER_EDGE + ";"
            " border-radius: 12px; }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        self._input = QLineEdit()
        self._input.setPlaceholderText(
            question_hint or "What am I missing? (optional)"
        )
        self._input.returnPressed.connect(self._submit)
        layout.addWidget(self._input)

        self._agent_mode = QCheckBox("Agent mode (web, Gmail, notes)")
        self._agent_mode.setToolTip(
            "Let the AI use tools — web search, Gmail, your notes — "
            "instead of just looking at the image."
        )
        self._agent_mode.setStyleSheet(f"font-size: 11px; color: {INK_SOFT};")
        layout.addWidget(self._agent_mode)

        row = QHBoxLayout()
        ask_btn = QPushButton("Ask AI")
        ask_btn.setDefault(True)
        ask_btn.setStyleSheet(
            f"background: {ACCENT}; color: #fff; border-radius: 8px; padding: 7px 12px;"
        )
        ask_btn.clicked.connect(self._submit)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet("border: none; color: #5B5F58;")
        cancel_btn.clicked.connect(self.cancelled.emit)
        row.addWidget(ask_btn, 1)
        row.addWidget(cancel_btn)
        layout.addLayout(row)

        self._input.setFocus()

    def _submit(self) -> None:
        self.asked.emit(self._input.text().strip(), self._agent_mode.isChecked())

    def keyPressEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        if event.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()
        else:
            super().keyPressEvent(event)


# -- floating AI bubble ------------------------------------------------------
class AIBubble(QWidget):
    """Shows "thinking…", then the answer with action buttons."""

    accepted = Signal()
    dismissed = Signal()
    speak_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedWidth(250)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            "AIBubble { background: " + ACCENT_SOFT + ";"
            " border: 1.5px dashed " + ACCENT + "; border-radius: 12px; }"
        )
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(10, 10, 10, 10)
        self._layout.setSpacing(8)

        self._tag = QLabel("AI · TEMPORARY")
        self._tag.setStyleSheet(
            "font-family: monospace; font-size: 9px; color: " + ACCENT + ";"
        )
        self._layout.addWidget(self._tag)

        self._spinner = QProgressBar()
        self._spinner.setRange(0, 0)  # busy indicator
        self._spinner.setFixedHeight(8)
        self._spinner.setTextVisible(False)
        self._layout.addWidget(self._spinner)

        self._status = QLabel("thinking…")
        self._status.setStyleSheet(f"font-size: 12px; color: {INK};")
        self._layout.addWidget(self._status)

        self._answer = QLabel()
        self._answer.setWordWrap(True)
        self._answer.setStyleSheet(f"font-size: 12.5px; color: {INK};")
        self._answer.setVisible(False)
        self._layout.addWidget(self._answer)

        self._actions = QWidget()
        actions_layout = QHBoxLayout(self._actions)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(6)
        self._accept_btn = QPushButton("Accept")
        self._accept_btn.setStyleSheet(
            f"background: {ACCENT}; color: #fff; border-radius: 8px; padding: 5px 10px;"
        )
        self._accept_btn.clicked.connect(self.accepted.emit)
        self._speak_btn = QPushButton("Speak")
        self._speak_btn.clicked.connect(self.speak_requested.emit)
        self._dismiss_btn = QPushButton("Dismiss")
        self._dismiss_btn.setStyleSheet("border: none; color: #5B5F58;")
        self._dismiss_btn.clicked.connect(self.dismissed.emit)
        actions_layout.addWidget(self._accept_btn)
        actions_layout.addWidget(self._speak_btn)
        actions_layout.addWidget(self._dismiss_btn)
        self._actions.setVisible(False)
        self._layout.addWidget(self._actions)

    def show_progress(self, text: str) -> None:
        self._status.setText(text)

    def show_answer(self, answer: str) -> None:
        self._spinner.setVisible(False)
        self._status.setVisible(False)
        self._answer.setText(_esc(answer).replace("\n", "<br>"))
        self._answer.setVisible(True)
        self._actions.setVisible(True)
        self.adjustSize()

    def show_error(self, message: str) -> None:
        self._spinner.setVisible(False)
        self._status.setText(f"Couldn't get an answer.\n{message}")
        self.adjustSize()


# -- canvas ask controller ---------------------------------------------------
class CanvasAskController(QObject):
    """Owns ask-panel -> worker -> bubble for canvas regions.

    Signals let the main window stay in charge of history, notes, and the
    workspace store; this controller only manages the floating UI + threads.
    """

    historyLogged = Signal(HistoryEntry)
    noteAccepted = Signal(object, str)  # QRect, answer text
    noteSaved = Signal()                # workspace store changed

    def __init__(self, canvas, provider, agent_runner, speaker,
                 history_context_fn, parent=None) -> None:
        super().__init__(parent)
        self._canvas = canvas
        self._provider = provider
        self._agent_runner = agent_runner
        self._speaker = speaker
        self._history_context_fn = history_context_fn
        self._panel: AskPanel | None = None
        self._bubble: AIBubble | None = None
        self._worker = None
        self._rect = None
        self._question = ""
        self._answer = ""

    def ask_region(self, rect) -> None:
        """Start the ask flow for a selected canvas rect."""
        self.close()
        self._rect = rect
        panel = AskPanel(parent=self._canvas)
        panel.asked.connect(self._on_asked)
        panel.cancelled.connect(self.close)
        _place_near(panel, self._canvas, rect)
        panel.show()
        self._panel = panel

    def close(self) -> None:
        if self._worker is not None:
            self._worker.terminate()
            self._worker.wait(500)
            self._worker = None
        if self._panel is not None:
            self._panel.deleteLater()
            self._panel = None
        if self._bubble is not None:
            self._bubble.deleteLater()
            self._bubble = None
        if self._rect is not None:
            self._canvas.clear_selection()
            self._rect = None

    # -- internals ---------------------------------------------------------
    def _on_asked(self, question: str, agent_mode: bool) -> None:
        rect = self._rect
        if rect is None:
            return
        self._question = question
        if self._panel is not None:
            self._panel.deleteLater()
            self._panel = None
        crop = self._canvas.crop_region_png(rect)

        bubble = AIBubble(parent=self._canvas)
        bubble.accepted.connect(self._on_accepted)
        bubble.dismissed.connect(self._on_dismissed)
        bubble.speak_requested.connect(self._on_speak)
        _place_near(bubble, self._canvas, rect)
        bubble.show()
        self._bubble = bubble

        if agent_mode:
            worker = AgentWorker(self._agent_runner, question or "What am I missing here?",
                                 image_png=crop)
            worker.progress.connect(bubble.show_progress)
            worker.confirm_requested.connect(self._on_confirm_requested)
            self._confirm_worker = worker
        else:
            worker = AskWorker(
                self._provider, crop, question,
                self._history_context_fn(),
            )
        worker.finished.connect(self._on_finished)
        worker.failed.connect(self._on_failed)
        worker.start()
        self._worker = worker

    def _on_confirm_requested(self, draft: dict) -> None:
        worker = getattr(self, "_confirm_worker", None)
        if worker is None:
            return
        text = (
            f"To: {draft.get('to', '')}\n"
            f"Subject: {draft.get('subject', '')}\n\n"
            f"{draft.get('body', '')}"
        )
        answer = QMessageBox.question(
            self._canvas.window(),
            "Confirm sending email",
            "The agent wants to send this email:\n\n" + text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        worker.answer_confirmation(answer == QMessageBox.StandardButton.Yes)

    def _on_finished(self, answer: str) -> None:
        self._answer = answer
        if self._bubble is not None:
            self._bubble.show_answer(answer)
        self._worker = None

    def _on_failed(self, message: str) -> None:
        if self._bubble is not None:
            self._bubble.show_error(message)
            QTimer.singleShot(5000, self.close)
        else:
            self.close()
        self._worker = None

    def _on_accepted(self) -> None:
        rect, answer, question = self._rect, self._answer, self._question
        self.noteAccepted.emit(rect, answer)
        self.historyLogged.emit(HistoryEntry(question, answer, "accepted", "canvas"))
        title = (question or "Canvas note").strip()[:60]
        notes_store.save_note(title, answer)
        self.noteSaved.emit()
        self.close()

    def _on_dismissed(self) -> None:
        self.historyLogged.emit(
            HistoryEntry(self._question, self._answer, "dismissed", "canvas")
        )
        self.close()

    def _on_speak(self) -> None:
        if self._answer:
            self._speaker.speak(self._answer)


def _place_near(widget: QWidget, canvas: QWidget, rect) -> None:
    """Position a floating widget near *rect*, clamped inside the canvas."""
    w = widget.width() or PANEL_WIDTH
    h = widget.sizeHint().height() or 120
    top = rect.y() + rect.height() + 8
    left = rect.x()
    if top + h > canvas.height():
        top = rect.y() - h - 8
    if left + w > canvas.width():
        left = canvas.width() - w - 10
    widget.move(QPoint(max(6, left), max(6, top)))


# -- screen analysis dialog --------------------------------------------------
class ScreenAskDialog(QDialog):
    """Ask about a screenshot: thumbnail, question, answer, copy/speak."""

    askCompleted = Signal(str, str)  # question, answer (for history)

    def __init__(self, image_png: bytes, provider, agent_runner, speaker,
                 history_context_fn, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Ask about this screen")
        self.setMinimumSize(560, 520)
        self._provider = provider
        self._agent_runner = agent_runner
        self._speaker = speaker
        self._history_context_fn = history_context_fn
        self._image_png = image_png
        self._worker = None
        self._answer = ""
        self._question = ""

        layout = QVBoxLayout(self)

        img = QImage.fromData(image_png, "PNG")
        thumb = QLabel()
        thumb.setPixmap(
            QPixmap.fromImage(img).scaledToWidth(
                520, Qt.TransformationMode.SmoothTransformation
            )
        )
        thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(thumb)

        qrow = QHBoxLayout()
        self._input = QLineEdit()
        self._input.setPlaceholderText("What do you want to know about this screen? (optional)")
        self._input.returnPressed.connect(self._ask)
        self._agent_mode = QCheckBox("Agent mode")
        self._agent_mode.setToolTip("Let the AI use tools (web, Gmail, notes).")
        self._ask_btn = QPushButton("Ask AI")
        self._ask_btn.setDefault(True)
        self._ask_btn.setStyleSheet(
            f"background: {ACCENT}; color: #fff; border-radius: 8px; padding: 7px 14px;"
        )
        self._ask_btn.clicked.connect(self._ask)
        qrow.addWidget(self._input, 1)
        qrow.addWidget(self._agent_mode)
        qrow.addWidget(self._ask_btn)
        layout.addLayout(qrow)

        self._status = QLabel("")
        self._status.setStyleSheet(f"color: {INK_SOFT}; font-size: 12px;")
        layout.addWidget(self._status)

        self._answer_view = QTextEdit()
        self._answer_view.setReadOnly(True)
        self._answer_view.setPlaceholderText("The answer will appear here.")
        layout.addWidget(self._answer_view, 1)

        brow = QHBoxLayout()
        self._copy_btn = QPushButton("Copy answer")
        self._copy_btn.setEnabled(False)
        self._copy_btn.clicked.connect(self._copy)
        self._speak_btn = QPushButton("Speak")
        self._speak_btn.setEnabled(False)
        self._speak_btn.clicked.connect(lambda: self._speaker.speak(self._answer))
        self._done_btn = QPushButton("Done")
        self._done_btn.clicked.connect(self.accept)
        brow.addWidget(self._copy_btn)
        brow.addWidget(self._speak_btn)
        brow.addStretch(1)
        brow.addWidget(self._done_btn)
        layout.addLayout(brow)

    def _ask(self) -> None:
        self._question = self._input.text().strip()
        self._ask_btn.setEnabled(False)
        self._status.setText("thinking…")
        if self._agent_mode.isChecked():
            worker = AgentWorker(
                self._agent_runner,
                self._question or "What am I looking at? Summarize it.",
                image_png=self._image_png,
            )
            worker.progress.connect(self._status.setText)
            worker.confirm_requested.connect(self._on_confirm_requested)
        else:
            worker = AskWorker(
                self._provider, self._image_png, self._question,
                self._history_context_fn(),
            )
        worker.finished.connect(self._on_finished)
        worker.failed.connect(self._on_failed)
        worker.start()
        self._worker = worker

    def _on_confirm_requested(self, draft: dict) -> None:
        text = (f"To: {draft.get('to', '')}\nSubject: {draft.get('subject', '')}\n\n"
                f"{draft.get('body', '')}")
        answer = QMessageBox.question(
            self, "Confirm sending email",
            "The agent wants to send this email:\n\n" + text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if self._worker is not None:
            self._worker.answer_confirmation(answer == QMessageBox.StandardButton.Yes)

    def _on_finished(self, answer: str) -> None:
        self._answer = answer
        self._answer_view.setPlainText(answer)
        self._status.setText("")
        self._copy_btn.setEnabled(True)
        self._speak_btn.setEnabled(True)
        self._ask_btn.setEnabled(True)
        self._worker = None
        self.askCompleted.emit(self._question, answer)

    def _on_failed(self, message: str) -> None:
        self._status.setText(f"Couldn't get an answer: {message}")
        self._ask_btn.setEnabled(True)
        self._worker = None

    def _copy(self) -> None:
        QGuiApplication.clipboard().setText(self._answer)

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        if self._worker is not None:
            self._worker.terminate()
            self._worker.wait(500)
        super().closeEvent(event)


# -- topbar agent dialog -------------------------------------------------------
class AgentDialog(QDialog):
    """Runs a free-form agent task from the topbar input."""

    noteSaved = Signal()

    def __init__(self, task: str, agent_runner, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Agent")
        self.setMinimumSize(560, 420)
        self._runner = agent_runner
        self._answer = ""
        self._task = task

        layout = QVBoxLayout(self)
        header = QLabel(f"<b>Task:</b> {_esc(task)}")
        header.setWordWrap(True)
        layout.addWidget(header)

        self._log = QTextEdit()
        self._log.setReadOnly(True)
        layout.addWidget(self._log, 1)

        brow = QHBoxLayout()
        self._save_btn = QPushButton("Save as note")
        self._save_btn.setEnabled(False)
        self._save_btn.clicked.connect(self._save_note)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        brow.addWidget(self._save_btn)
        brow.addStretch(1)
        brow.addWidget(close_btn)
        layout.addLayout(brow)

        self._worker = AgentWorker(agent_runner, task)
        self._worker.progress.connect(self._on_progress)
        self._worker.confirm_requested.connect(self._on_confirm_requested)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _append(self, html: str) -> None:
        self._log.append(html)

    def _on_progress(self, text: str) -> None:
        self._append(f"<i style='color:{INK_SOFT};'>… {text}</i>")

    def _on_confirm_requested(self, draft: dict) -> None:
        text = (f"To: {draft.get('to', '')}\nSubject: {draft.get('subject', '')}\n\n"
                f"{draft.get('body', '')}")
        answer = QMessageBox.question(
            self, "Confirm sending email",
            "The agent wants to send this email:\n\n" + text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        self._worker.answer_confirmation(answer == QMessageBox.StandardButton.Yes)

    def _on_finished(self, answer: str) -> None:
        self._answer = answer
        self._append(f"<div style='margin-top:8px;'>{_esc(answer).replace(chr(10), '<br>')}</div>")
        self._save_btn.setEnabled(True)

    def _on_failed(self, message: str) -> None:
        self._append(f"<b style='color:#B5443A;'>Failed:</b> {_esc(message)}")

    def _save_note(self) -> None:
        title = (self._task[:60] or "Agent result").strip()
        notes_store.save_note(title, self._answer)
        self.noteSaved.emit()
        self._save_btn.setEnabled(False)
        self._save_btn.setText("Saved ✓")

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        if self._worker is not None and self._worker.isRunning():
            self._worker.terminate()
            self._worker.wait(500)
        super().closeEvent(event)


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
