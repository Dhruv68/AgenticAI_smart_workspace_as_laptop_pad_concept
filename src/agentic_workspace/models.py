"""Core data models: strokes, AI notes, and history entries.

Everything here is JSON-serializable so sessions can be saved and restored
as plain files. Strokes keep timestamped points (not just pixels) so future
versions can reason about *how* the user writes.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class StrokePoint:
    """One sampled point of a stroke."""

    x: float
    y: float
    pressure: float = 1.0
    t: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {"x": self.x, "y": self.y, "p": self.pressure, "t": self.t}

    @classmethod
    def from_dict(cls, d: dict) -> "StrokePoint":
        return cls(
            x=float(d["x"]),
            y=float(d["y"]),
            pressure=float(d.get("p", 1.0)),
            t=float(d.get("t", 0.0)),
        )


@dataclass
class Stroke:
    """A single pen or eraser stroke: timestamped points plus style."""

    points: list[StrokePoint] = field(default_factory=list)
    color: str = "#23262B"
    width: float = 3.0
    tool: str = "pen"  # "pen" | "eraser"

    def to_dict(self) -> dict:
        return {
            "points": [p.to_dict() for p in self.points],
            "color": self.color,
            "width": self.width,
            "tool": self.tool,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Stroke":
        return cls(
            points=[StrokePoint.from_dict(p) for p in d.get("points", [])],
            color=str(d.get("color", "#23262B")),
            width=float(d.get("width", 3.0)),
            tool=str(d.get("tool", "pen")),
        )


@dataclass
class AISessionNote:
    """An AI answer accepted onto the canvas as a visible margin note."""

    x: float
    y: float
    text: str
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {"x": self.x, "y": self.y, "text": self.text, "t": self.created_at}

    @classmethod
    def from_dict(cls, d: dict) -> "AISessionNote":
        return cls(
            x=float(d["x"]),
            y=float(d["y"]),
            text=str(d.get("text", "")),
            created_at=float(d.get("t", 0.0)),
        )


@dataclass
class HistoryEntry:
    """One Q/A interaction, accepted or dismissed, from canvas or screen."""

    question: str
    answer: str
    status: str  # "accepted" | "dismissed"
    source: str = "canvas"  # "canvas" | "screen"
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "question": self.question,
            "answer": self.answer,
            "status": self.status,
            "source": self.source,
            "t": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "HistoryEntry":
        return cls(
            question=str(d.get("question", "")),
            answer=str(d.get("answer", "")),
            status=str(d.get("status", "dismissed")),
            source=str(d.get("source", "canvas")),
            created_at=float(d.get("t", 0.0)),
        )
