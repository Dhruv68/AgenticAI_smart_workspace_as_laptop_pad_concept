"""Local workspace store: notes with full-text search (sqlite + fts5).

Accepted AI notes auto-save here, the agent can save/search them, and the
Library tab browses them. One short-lived connection per call — thread-safe
by construction. The DB lives at ``data/workspace.db`` (git-ignored).
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    text TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
    title, text, content='notes', content_rowid='id'
);
CREATE TRIGGER IF NOT EXISTS notes_ai AFTER INSERT ON notes BEGIN
    INSERT INTO notes_fts(rowid, title, text)
    VALUES (new.id, new.title, new.text);
END;
CREATE TRIGGER IF NOT EXISTS notes_ad AFTER DELETE ON notes BEGIN
    INSERT INTO notes_fts(notes_fts, rowid, title, text)
    VALUES ('delete', old.id, old.title, old.text);
END;
"""


def db_path() -> Path:
    here = Path(__file__).resolve()
    repo_root = here.parents[3] if len(here.parents) > 3 else Path.cwd()
    d = repo_root / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d / "workspace.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path()))
    conn.executescript(SCHEMA)
    return conn


def save_note(title: str, text: str) -> str:
    """Save a note; returns a confirmation with its id."""
    title = (title or "Untitled note").strip()[:120]
    text = (text or "").strip()
    if not text:
        return "Not saved: note text was empty."
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO notes (title, text, created_at) VALUES (?, ?, ?)",
            (title, text, time.time()),
        )
        note_id = cur.lastrowid
    return f"Saved note #{note_id}: '{title}'"


def search_notes(query: str, limit: int = 8) -> str:
    """Full-text search over saved notes."""
    query = (query or "").strip()
    if not query:
        return "Empty search query."
    # Quote as a phrase so FTS5 operators in user text (e.g. dashes,
    # quotes, colons) can't break the query or change its meaning.
    phrase = '"' + query.replace('"', '""') + '"'
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT n.id, n.title,
                   snippet(notes_fts, 1, '…', '…', '…', 40) AS snip
            FROM notes_fts
            JOIN notes n ON n.id = notes_fts.rowid
            WHERE notes_fts MATCH ?
            ORDER BY rank LIMIT ?
            """,
            (phrase, max(1, limit)),
        ).fetchall()
    if not rows:
        return f"No saved notes match '{query}'."
    return "\n".join(f"#{r[0]} {r[1]}\n   {r[2]}" for r in rows)


def list_notes(limit: int = 20) -> str:
    """List recent notes, newest first."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, title, substr(text, 1, 80) FROM notes "
            "ORDER BY created_at DESC LIMIT ?",
            (max(1, limit),),
        ).fetchall()
    if not rows:
        return "No saved notes yet."
    return "\n".join(f"#{r[0]} {r[1]}\n   {r[2]}…" for r in rows)


def get_note(note_id: int) -> dict | None:
    """Fetch one note by id (used by the Library tab)."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, title, text, created_at FROM notes WHERE id = ?",
            (note_id,),
        ).fetchone()
    if not row:
        return None
    return {"id": row[0], "title": row[1], "text": row[2], "created_at": row[3]}


def all_notes(limit: int = 200) -> list[dict]:
    """All notes for the Library tab, newest first."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, title, substr(text, 1, 120), created_at FROM notes "
            "ORDER BY created_at DESC LIMIT ?",
            (max(1, limit),),
        ).fetchall()
    return [
        {"id": r[0], "title": r[1], "snippet": r[2], "created_at": r[3]} for r in rows
    ]
