"""Background worker so AI calls never block the UI thread."""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from . import AIFriendlyError, VisionProvider


class AskWorker(QThread):
    """Runs ``provider.ask(...)`` off the UI thread.

    Signals:
        finished(str): the model's answer text.
        failed(str): a user-friendly error message.
    """

    finished = Signal(str)
    failed = Signal(str)

    def __init__(
        self,
        provider: VisionProvider,
        image_png: bytes,
        question: str,
        history_context: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._provider = provider
        self._image_png = image_png
        self._question = question
        self._history_context = history_context

    def run(self) -> None:
        try:
            answer = self._provider.ask(
                self._image_png, self._question, self._history_context
            )
        except AIFriendlyError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # never let the thread die silently
            self.failed.emit(f"Unexpected error while asking the model: {exc}")
        else:
            self.finished.emit(answer)
