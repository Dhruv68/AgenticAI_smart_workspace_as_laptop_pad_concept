"""QThread wrapper for the agent loop.

Mirrors :mod:`agentic_workspace.ai.worker`: the loop runs off the UI thread.
Gated tools (gmail_send) emit :attr:`confirm_requested` with the draft; the
UI answers through :meth:`answer_confirmation`, which unblocks the worker.
"""

from __future__ import annotations

import queue

from PySide6.QtCore import QThread, Signal

from ..ai import AIFriendlyError


class AgentWorker(QThread):
    """Runs :class:`AgentRunner.run` off the UI thread."""

    progress = Signal(str)   # human-readable step updates
    finished = Signal(str)   # final answer text
    failed = Signal(str)     # user-friendly error
    confirm_requested = Signal(dict)  # draft awaiting user approval

    def __init__(self, runner, user_text: str, image_png: bytes | None = None,
                 parent=None) -> None:
        super().__init__(parent)
        self._runner = runner
        self._user_text = user_text
        self._image_png = image_png
        self._confirm_box: queue.Queue = queue.Queue()

    # -- called in the worker thread -------------------------------------
    def _confirm(self, draft: dict) -> bool:
        self.confirm_requested.emit(draft)
        try:
            return bool(self._confirm_box.get(timeout=600))
        except queue.Empty:
            return False

    def run(self) -> None:  # noqa: N802 (Qt naming)
        try:
            answer = self._runner.run(
                self._user_text,
                image_png=self._image_png,
                progress_cb=self.progress.emit,
                confirm_fn=self._confirm,
            )
        except AIFriendlyError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # never die silently
            self.failed.emit(f"Agent error: {exc}")
        else:
            self.finished.emit(answer)

    # -- called in the UI thread ------------------------------------------
    def answer_confirmation(self, approved: bool) -> None:
        """Resolve a pending confirm_requested (UI thread)."""
        self._confirm_box.put(bool(approved))
