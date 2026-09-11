"""Ollama implementation of :class:`VisionProvider`.

Talks to a local Ollama server's ``/api/chat`` endpoint. All failures are
translated into :class:`AIFriendlyError` with the exact command the user
needs to run.
"""

from __future__ import annotations

import base64

import requests

from . import AIFriendlyError, build_system_prompt


class OllamaClient:
    """Vision provider backed by a local Ollama server."""

    name = "ollama"

    def __init__(self, base_url: str, model: str, timeout: int = 180) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    # -- health -----------------------------------------------------------
    def ping(self, timeout: float = 2.0) -> bool:
        try:
            resp = requests.get(f"{self.base_url}/api/version", timeout=timeout)
            return resp.ok
        except requests.RequestException:
            return False

    # -- inference --------------------------------------------------------
    def chat(
        self, messages: list[dict], tools: list[dict] | None = None
    ) -> dict:
        """Raw ``/api/chat`` call. Returns the assistant ``message`` dict.

        *tools* uses Ollama's function-calling format. Raises AIFriendlyError.
        """
        payload: dict = {
            "model": self.model,
            "stream": False,
            "messages": messages,
        }
        if tools:
            payload["tools"] = tools
        try:
            resp = requests.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=(10, self.timeout),
            )
        except requests.exceptions.ConnectionError:
            raise AIFriendlyError(
                f"Couldn't reach Ollama at {self.base_url}.\n"
                "Start it with `ollama serve`, then make sure the model "
                f"is downloaded: `ollama pull {self.model}`"
            ) from None
        except requests.exceptions.Timeout:
            raise AIFriendlyError(
                "The model took too long to answer (over "
                f"{self.timeout}s). Try a smaller model like `qwen3-vl:2b`, "
                "or raise OLLAMA_TIMEOUT in your .env."
            ) from None
        except requests.RequestException as exc:
            raise AIFriendlyError(f"Network error talking to Ollama: {exc}") from None

        if resp.status_code == 404:
            raise AIFriendlyError(
                f"Model '{self.model}' isn't downloaded.\n"
                f"Run: `ollama pull {self.model}`"
            )
        if not resp.ok:
            detail = ""
            try:
                detail = str(resp.json().get("error", ""))
            except Exception:
                detail = resp.text[:200]
            raise AIFriendlyError(
                f"Ollama returned an error (HTTP {resp.status_code}). {detail}"
            )

        try:
            message = resp.json()["message"]
        except (KeyError, ValueError):
            raise AIFriendlyError(
                "Ollama answered, but the response was unreadable."
            ) from None
        if not isinstance(message, dict):
            raise AIFriendlyError("Ollama answered, but the response was unreadable.")
        return message

    def ask(
        self, image_png: bytes, question: str, history_context: str = ""
    ) -> str:
        question = question.strip() or "What am I missing or getting wrong here?"
        image_b64 = base64.b64encode(image_png).decode("ascii")
        message = self.chat(
            [
                {
                    "role": "system",
                    "content": build_system_prompt(history_context, mode="canvas"),
                },
                {
                    "role": "user",
                    "content": question,
                    "images": [image_b64],
                },
            ]
        )
        content = (message.get("content") or "").strip()
        if not content:
            raise AIFriendlyError("The model returned an empty response.")
        return content
