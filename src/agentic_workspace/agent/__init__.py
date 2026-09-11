"""Desktop agent package: tool-calling loop over Ollama."""

from .loop import MAX_STEPS, AgentRunner

__all__ = ["AgentRunner", "MAX_STEPS"]
