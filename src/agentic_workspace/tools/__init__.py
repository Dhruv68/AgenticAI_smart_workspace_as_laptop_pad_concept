"""Tool registry for the desktop agent.

A :class:`Tool` is a named callable with a JSON-schema description the model
can read. :class:`ToolRegistry` exposes them to Ollama's ``/api/chat``
``tools`` parameter and executes calls from the model.

Tools run in a worker thread (never the UI thread). ``gmail_send`` is the
one gated tool: calling it raises :class:`NeedsConfirmation` carrying the
draft; the UI confirms with the user, then re-calls with ``_confirmed=True``.
Nothing is ever sent silently.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


class NeedsConfirmation(Exception):
    """Raised by a gated tool when it needs explicit user approval.

    Carries the draft so the UI can show exactly what would happen.
    """

    def __init__(self, tool_name: str, draft: dict) -> None:
        super().__init__(f"{tool_name} needs user confirmation")
        self.tool_name = tool_name
        self.draft = draft


@dataclass
class Tool:
    """One callable tool the agent can invoke."""

    name: str
    description: str
    parameters: dict  # JSON schema for the arguments object
    func: Callable[..., Any]
    gated: bool = False  # True -> first call raises NeedsConfirmation

    def to_ollama(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    """Name -> Tool mapping with Ollama-schema export and safe dispatch."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def names(self) -> list[str]:
        return list(self._tools)

    def ollama_tools(self) -> list[dict]:
        return [t.to_ollama() for t in self._tools.values()]

    def call(self, name: str, arguments: dict) -> Any:
        """Execute *name* with *arguments*.

        Raises NeedsConfirmation for gated tools on first call, KeyError for
        unknown tools. Tool exceptions are caught by the agent loop and fed
        back to the model as text — they never propagate raw.
        """
        tool = self._tools[name]  # KeyError -> unknown tool
        args = dict(arguments or {})
        confirmed = bool(args.pop("_confirmed", False))
        if tool.gated and not confirmed:
            raise NeedsConfirmation(name, args)
        if tool.gated:
            args["_confirmed"] = True  # propagate approval to the callable
        return tool.func(**args)
