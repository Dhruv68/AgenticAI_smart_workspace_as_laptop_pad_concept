"""Freehand ink canvas: pen/eraser/select, pressure-aware, undo/redo.

Custom QWidget + QPainter (not QGraphicsView) to keep stroke rendering
simple and pixel-faithful. Strokes are stored as timestamped point lists
(see :mod:`agentic_workspace.models`), so the canvas can be serialized,
cropped to PNG for the vision model, and re-rendered at any size.
"""

from __future__ import annotations

from PySide6.QtCore import (
    QBuffer,
    QEvent,
    QIODevice,
    QPointF,
    QRect,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QImage,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QTabletEvent,
)
from PySide6.QtWidgets import QWidget

from ..models import AISessionNote, Stroke, StrokePoint

# Palette (ported from reference_canvas.html)
PAPER_BG = "#F5F6F1"      # canvas surface
APP_BG = "#ECEEE9"
PAPER_EDGE = "#DFE2DA"
INK = "#23262B"
INK_SOFT = "#5B5F58"
GRID_DOT = "#C9CDC2"
AI_ACCENT = "#5B4FE0"
AI_SOFT = "#EDEBFC"
ACCEPTED = "#2B7A5B"
EMPTY_HINT = "#B7BBAF"

GRID_STEP = 22
MIN_SELECT = 12  # px; smaller drags are ignored, like the HTML prototype
MAX_CROP_WIDTH = 1568  # downscale wider crops: vision prefill is expensive
NOTE_WRAP_WIDTH = 210

EMPTY_HINT_TEXT = (
    "sketch a problem, diagram, or equation —\n"
    "then press S and drag a box to ask about it"
)


class InkCanvas(QWidget):
    """The drawable surface."""

    regionSelected = Signal(QRect)   # user boxed a region >= 12x12 px
    strokesChanged = Signal()        # stroke/note count changed (status bar)

    TOOL_PEN = "pen"
    TOOL_ERASER = "eraser"
    TOOL_SELECT = "select"

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setStyleSheet(
            f"background: {PAPER_BG}; border: 1px solid {PAPER_EDGE};"
        )

        self._strokes: list[Stroke] = []
        self._redo: list[Stroke] = []
        self._notes: list[AISessionNote] = []

        self._tool = self.TOOL_PEN
        self._color = INK
        self._width = 3.0

        self._current: Stroke | None = None
        self._using_tablet = False

        self._sel_start: QPointF | None = None
        self._sel_rect: QRect | None = None

    # -- tool state -------------------------------------------------------
    def set_tool(self, tool: str) -> None:
        self._tool = tool
        self.setCursor(
            Qt.CursorShape.CrossCursor
            if tool != self.TOOL_ERASER
            else Qt.CursorShape.PointingHandCursor
        )

    def tool(self) -> str:
        return self._tool

    def set_color(self, color: str) -> None:
        self._color = color

    def set_width(self, width: float) -> None:
        self._width = max(1.0, float(width))

    def stroke_count(self) -> int:
        return len(self._strokes)

    # -- painting ---------------------------------------------------------
    def paintEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(PAPER_BG))
        self._paint_grid(p)
        self._paint_content(p)

        if not self._strokes and not self._notes:
            p.setPen(QColor(EMPTY_HINT))
            font = QFont("Fraunces", 13)
            font.setItalic(True)
            p.setFont(font)
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, EMPTY_HINT_TEXT)

        if self._sel_rect is not None:
            r = self._sel_rect
            p.fillRect(r, QColor(91, 79, 224, 16))
            pen = QPen(QColor(AI_ACCENT), 1.5)
            pen.setStyle(Qt.PenStyle.DashLine)
            pen.setDashPattern([5, 4])
            p.setPen(pen)
            p.drawRect(r)
        p.end()

    def _paint_grid(self, p: QPainter) -> None:
        p.setPen(QColor(GRID_DOT))
        step = GRID_STEP
        for x in range(0, self.width(), step):
            for y in range(0, self.height(), step):
                p.drawPoint(x, y)

    def _paint_content(self, p: QPainter) -> None:
        for stroke in self._strokes:
            self._paint_stroke(p, stroke)
        for note in self._notes:
            self._paint_note(p, note)

    def _paint_stroke(self, p: QPainter, stroke: Stroke) -> None:
        pts = stroke.points
        if not pts:
            return
        erasing = stroke.tool == self.TOOL_ERASER
        color = QColor(PAPER_BG) if erasing else QColor(stroke.color)
        base = stroke.width * (6.0 if erasing else 1.0)

        if len(pts) == 1:
            w = base * (0.35 + 0.65 * pts[0].pressure)
            p.setPen(QPen(color, w, Qt.PenStyle.SolidLine,
                           Qt.PenCapStyle.RoundCap))
            p.drawPoint(QPointF(pts[0].x, pts[0].y))
            return

        # Segment-by-segment so stylus pressure visibly changes line weight.
        for a, b in zip(pts, pts[1:]):
            w = base * (0.35 + 0.65 * ((a.pressure + b.pressure) / 2.0))
            p.setPen(QPen(color, w, Qt.PenStyle.SolidLine,
                           Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            p.drawLine(QPointF(a.x, a.y), QPointF(b.x, b.y))

    def _paint_note(self, p: QPainter, note: AISessionNote) -> None:
        font = QFont("Fraunces", 12)
        font.setItalic(True)
        p.setFont(font)
        p.setPen(QColor(AI_ACCENT))
        x, y = note.x, note.y
        p.drawText(QPointF(x, y), "✓ AI note:")
        y += 18
        fm = QFontMetrics(font)
        line = ""
        for word in note.text.split():
            trial = line + word + " "
            if fm.horizontalAdvance(trial) > NOTE_WRAP_WIDTH and line:
                p.drawText(QPointF(x, y), line.rstrip())
                y += 16
                line = word + " "
            else:
                line = trial
        if line.strip():
            p.drawText(QPointF(x, y), line.rstrip())

    # -- input ------------------------------------------------------------
    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._using_tablet or event.button() != Qt.MouseButton.LeftButton:
            return
        self._press(event.position(), 1.0)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._using_tablet:
            return
        self._move(event.position(), 1.0)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._using_tablet or event.button() != Qt.MouseButton.LeftButton:
            return
        self._release(event.position())

    def tabletEvent(self, event: QTabletEvent) -> None:  # noqa: N802
        etype = event.type()
        eraser_device = (
            getattr(QTabletEvent.DeviceType, "Eraser", None) is not None
            and event.deviceType() == QTabletEvent.DeviceType.Eraser
        )
        if etype == QEvent.Type.TabletPress:
            self._using_tablet = True
            self._tablet_was_eraser = eraser_device
            self._press(event.position(), event.pressure(), eraser_device)
        elif etype == QEvent.Type.TabletMove:
            self._move(event.position(), event.pressure())
        elif etype == QEvent.Type.TabletRelease:
            self._using_tablet = False
            self._release(event.position())
        else:
            return
        event.accept()

    # -- stroke / selection state machines --------------------------------
    def _press(self, pos: QPointF, pressure: float, force_eraser: bool = False) -> None:
        tool = self.TOOL_ERASER if force_eraser else self._tool
        if tool == self.TOOL_SELECT:
            self._sel_start = QPointF(pos)
            self._sel_rect = None
            return
        self._current = Stroke(
            color=self._color,
            width=self._width,
            tool=tool,
        )
        self._current.points.append(
            StrokePoint(x=pos.x(), y=pos.y(), pressure=max(0.05, pressure))
        )
        self._redo.clear()

    def _move(self, pos: QPointF, pressure: float) -> None:
        if self._tool == self.TOOL_SELECT and self._sel_start is not None:
            x = min(self._sel_start.x(), pos.x())
            y = min(self._sel_start.y(), pos.y())
            w = abs(pos.x() - self._sel_start.x())
            h = abs(pos.y() - self._sel_start.y())
            self._sel_rect = QRect(int(x), int(y), int(w), int(h))
            self.update()
            return
        if self._current is None:
            return
        last = self._current.points[-1]
        if abs(last.x - pos.x()) < 0.5 and abs(last.y - pos.y()) < 0.5:
            return
        self._current.points.append(
            StrokePoint(x=pos.x(), y=pos.y(), pressure=max(0.05, pressure))
        )
        self.update()

    def _release(self, pos: QPointF) -> None:
        if self._tool == self.TOOL_SELECT and self._sel_start is not None:
            self._move(pos, 1.0)  # finalize rect
            self._sel_start = None
            rect = self._sel_rect
            if rect is None or rect.width() < MIN_SELECT or rect.height() < MIN_SELECT:
                self.clear_selection()
            else:
                self.update()
                self.regionSelected.emit(QRect(rect))
            return
        if self._current is not None and len(self._current.points) >= 1:
            self._strokes.append(self._current)
            self.strokesChanged.emit()
        self._current = None
        self.update()

    # -- selection --------------------------------------------------------
    def clear_selection(self) -> None:
        self._sel_start = None
        self._sel_rect = None
        self.update()

    def cancel_selection(self) -> None:
        self.clear_selection()

    # -- undo / redo / clear ----------------------------------------------
    def undo(self) -> None:
        if self._strokes:
            self._redo.append(self._strokes.pop())
            self.strokesChanged.emit()
            self.update()

    def redo(self) -> None:
        if self._redo:
            self._strokes.append(self._redo.pop())
            self.strokesChanged.emit()
            self.update()

    def clear(self) -> None:
        self._strokes.clear()
        self._redo.clear()
        self._notes.clear()
        self.clear_selection()
        self.strokesChanged.emit()
        self.update()

    # -- AI notes ----------------------------------------------------------
    def add_ai_note(self, near: QRect, text: str) -> None:
        x = min(near.x() + near.width() + 14, max(10, self.width() - 240))
        y = min(near.y() + 14, max(30, self.height() - 60))
        self._notes.append(AISessionNote(x=float(x), y=float(y), text=text))
        self.strokesChanged.emit()
        self.update()

    # -- export ------------------------------------------------------------
    def render_full_image(self) -> QImage:
        img = QImage(self.size(), QImage.Format.Format_ARGB32)
        img.fill(QColor(PAPER_BG))
        p = QPainter(img)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            self._paint_content(p)
        finally:
            p.end()  # always release the paint device, even on error
        return img

    def crop_region_png(self, rect: QRect) -> bytes:
        """Render *rect* to PNG bytes, downscaled if wider than 1568px."""
        rect = rect.intersected(self.rect())
        img = QImage(rect.size(), QImage.Format.Format_ARGB32)
        img.fill(QColor(PAPER_BG))
        p = QPainter(img)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setClipRect(QRect(0, 0, rect.width(), rect.height()))
            p.translate(-rect.x(), -rect.y())
            self._paint_content(p)
        finally:
            p.end()  # always release the paint device, even on error
        if img.width() > MAX_CROP_WIDTH:
            img = img.scaledToWidth(
                MAX_CROP_WIDTH, Qt.TransformationMode.SmoothTransformation
            )
        buf = QBuffer()
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        img.save(buf, "PNG")
        return bytes(buf.data())

    # -- session state ------------------------------------------------------
    def get_strokes(self) -> list[Stroke]:
        return list(self._strokes)

    def get_notes(self) -> list[AISessionNote]:
        return list(self._notes)

    def set_strokes(self, strokes: list[Stroke]) -> None:
        self._strokes = list(strokes)
        self._redo.clear()
        self.strokesChanged.emit()
        self.update()

    def set_notes(self, notes: list[AISessionNote]) -> None:
        self._notes = list(notes)
        self.strokesChanged.emit()
        self.update()
