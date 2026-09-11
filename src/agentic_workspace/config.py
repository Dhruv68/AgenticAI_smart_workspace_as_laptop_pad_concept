"""App configuration: .env -> AppConfig.

All tunables live here with sane defaults so the app never crashes on a
missing .env. Secrets are only ever *read* from the environment, never
written anywhere.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class AppConfig:
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3-vl:4b"
    ollama_timeout: int = 180
    gmail_client_secrets: str | None = None
    repo_root: Path = REPO_ROOT


def load_config(env: dict | None = None) -> AppConfig:
    """Build an AppConfig from a mapping (defaults to os.environ)."""
    import os

    env = env if env is not None else os.environ

    def _int(key: str, default: int) -> int:
        try:
            return int(env.get(key, default))
        except (TypeError, ValueError):
            return default

    secrets = (env.get("GMAIL_CLIENT_SECRETS") or "").strip() or None
    return AppConfig(
        ollama_base_url=(env.get("OLLAMA_BASE_URL") or "http://localhost:11434").strip(),
        ollama_model=(env.get("OLLAMA_MODEL") or "qwen3-vl:4b").strip(),
        ollama_timeout=_int("OLLAMA_TIMEOUT", 180),
        gmail_client_secrets=secrets,
        repo_root=REPO_ROOT,
    )
