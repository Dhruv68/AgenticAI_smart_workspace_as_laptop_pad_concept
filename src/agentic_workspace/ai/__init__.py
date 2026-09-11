"""Vision-provider abstraction.

The UI only talks to :class:`VisionProvider`. Swapping Ollama for a hosted
model or a future on-device runtime means writing one new implementation —
nothing in the UI changes.
"""

from __future__ import annotations

from typing import Protocol


class AIFriendlyError(Exception):
    """An error whose message is safe to show to the user verbatim."""


class VisionProvider(Protocol):
    """Something that can answer a question about an image."""

    name: str

    def ask(
        self, image_png: bytes, question: str, history_context: str = ""
    ) -> str:
        """Answer *question* about the PNG image. Raises AIFriendlyError."""
        ...

    def ping(self, timeout: float = 2.0) -> bool:
        """True if the provider is reachable right now."""
        ...


_MARGIN_NOTE_PROMPT = (
    "You are an AI agent embedded directly in a shared visual workspace "
    "(a pen-and-paper style canvas). The user has circled or boxed a region of "
    "their own handwritten notes, diagram, or equation and is asking about "
    "just that region. Respond like a quick, concrete margin note — under 60 "
    "words, no preamble, no \"I can see that...\". If they didn't ask a specific "
    "question, give one useful observation or catch a likely error/missing "
    "piece. Ground everything only in what's actually visible in the image."
)

_SCREEN_PROMPT = (
    "You are an AI agent embedded in the user's desktop workspace. The user "
    "has captured a screenshot of their active application window and is "
    "asking about it. Respond like a quick, concrete margin note — under 60 "
    "words, no preamble, no \"I can see that...\". If they didn't ask a specific "
    "question, give one useful observation about their workflow or catch a "
    "likely error/missing piece. Ground everything only in what's actually "
    "visible in the image."
)


def build_system_prompt(history_context: str = "", mode: str = "canvas") -> str:
    """Shared system prompt, ported from the HTML prototype.

    *mode* is ``"canvas"`` (circled region of handwriting) or ``"screen"``
    (screenshot of the active window).
    """
    base = _MARGIN_NOTE_PROMPT if mode == "canvas" else _SCREEN_PROMPT
    if history_context.strip():
        base += "\n\nRecent workspace history:\n" + history_context.strip()
    return base
