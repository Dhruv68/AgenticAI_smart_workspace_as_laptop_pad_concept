"""Save/load workspace sessions as JSON; export the canvas to PNG.

Sessions live under ``<repo>/data/sessions/`` (git-ignored). The JSON holds
structured strokes, accepted AI notes, and the interaction history — the
"workspace memory" the HTML prototype logged in its history panel.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from ..models import AISessionNote, HistoryEntry, Stroke

SESSION_VERSION = 1


def sessions_dir() -> Path:
    """Default directory for session files (created on demand)."""
    # <repo>/src/agentic_workspace/storage/session.py -> parents[2] == src/…
    here = Path(__file__).resolve()
    repo_root = here.parents[3] if len(here.parents) > 3 else Path.cwd()
    d = repo_root / "data" / "sessions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_session(
    path: str | Path,
    strokes: list[Stroke],
    notes: list[AISessionNote],
    history: list[HistoryEntry],
) -> None:
    payload = {
        "version": SESSION_VERSION,
        "saved_at": time.time(),
        "strokes": [s.to_dict() for s in strokes],
        "ai_notes": [n.to_dict() for n in notes],
        "history": [h.to_dict() for h in history],
    }
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_session(path: str | Path) -> dict:
    """Return ``{"strokes": [...], "ai_notes": [...], "history": [...]}``.

    Raises ValueError on corrupt files, FileNotFoundError when missing.
    """
    raw = Path(path).read_text(encoding="utf-8")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Session file is not valid JSON: {exc}") from None
    try:
        return {
            "strokes": [Stroke.from_dict(s) for s in payload.get("strokes", [])],
            "ai_notes": [AISessionNote.from_dict(n) for n in payload.get("ai_notes", [])],
            "history": [HistoryEntry.from_dict(h) for h in payload.get("history", [])],
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"Session file is corrupt: {exc}") from None


def export_canvas_png(canvas, path: str | Path) -> None:
    """Render the full canvas (strokes + AI notes) to a PNG file."""
    img = canvas.render_full_image()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not img.save(str(path), "PNG"):
        raise OSError(f"Couldn't write PNG to {path}")
