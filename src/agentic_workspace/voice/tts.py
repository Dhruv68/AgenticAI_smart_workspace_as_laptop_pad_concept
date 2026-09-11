"""Local/offline text-to-speech via pyttsx3.

Speech always runs in a daemon thread so the UI never blocks. If pyttsx3
(or a system voice backend) is unavailable, speaking becomes a silent
no-op — the app must never crash because of TTS.
"""

from __future__ import annotations

import threading


class Speaker:
    """Fire-and-forget local speech."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._engine = None  # created lazily inside the worker thread
        self._speaking = False

    def speak(self, text: str) -> None:
        """Speak *text* aloud, interrupting anything currently spoken."""
        text = (text or "").strip()
        if not text:
            return
        self.stop()
        thread = threading.Thread(
            target=self._run, args=(text,), daemon=True, name="tts-speaker"
        )
        thread.start()

    def _run(self, text: str) -> None:
        try:
            import pyttsx3

            engine = pyttsx3.init()
        except Exception:
            return  # no voice backend — stay silent, never crash
        with self._lock:
            self._engine = engine
            self._speaking = True
        try:
            engine.say(text)
            engine.runAndWait()
        except Exception:
            pass
        finally:
            with self._lock:
                self._engine = None
                self._speaking = False
            try:
                engine.stop()
            except Exception:
                pass

    def stop(self) -> None:
        with self._lock:
            engine, self._engine = self._engine, None
        if engine is not None:
            try:
                engine.stop()
            except Exception:
                pass
