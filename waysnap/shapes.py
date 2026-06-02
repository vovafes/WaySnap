"""
Shape data model for the annotation layer.
Each shape stores its own geometry and knows how to draw itself via QPainter.
"""
from __future__ import annotations

import math
from abc import ABC, abstractmethod

from PyQt6.QtCore import QPoint, QRect, Qt
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygon


class Shape(ABC):
    def __init__(self, color: QColor, width: int) -> None:
        self.color = QColor(color)
        self.width = width

    @abstractmethod
    def draw(self, p: QPainter) -> None: ...

    @abstractmethod
    def is_valid(self) -> bool: ...

    @staticmethod
    def _pen(color: QColor, width: int,
             cap=Qt.PenCapStyle.RoundCap,
             join=Qt.PenJoinStyle.RoundJoin) -> QPen:
        return QPen(color, width, Qt.PenStyle.SolidLine, cap, join)


class Stroke(Shape):
    """Freehand pencil stroke."""

    def __init__(self, color: QColor, width: int) -> None:
        super().__init__(color, width)
        self.points: list[QPoint] = []

    def draw(self, p: QPainter) -> None:
        if len(self.points) < 2:
            return
        p.setPen(self._pen(self.color, self.width))
        p.setBrush(Qt.BrushStyle.NoBrush)
        path = QPainterPath()
        path.moveTo(self.points[0])
        for pt in self.points[1:]:
            path.lineTo(pt)
        p.drawPath(path)

    def is_valid(self) -> bool:
        return len(self.points) >= 2


class Arrow(Shape):
    def __init__(self, color: QColor, width: int) -> None:
        super().__init__(color, width)
        self.start = QPoint()
        self.end   = QPoint()

    def draw(self, p: QPainter) -> None:
        if not self.is_valid():
            return
        p.setPen(self._pen(self.color, self.width))
        p.setBrush(self.color)
        p.drawLine(self.start, self.end)
        _arrowhead(p, self.start, self.end, self.width)

    def is_valid(self) -> bool:
        return (self.end - self.start).manhattanLength() > 4


class RectShape(Shape):
    def __init__(self, color: QColor, width: int) -> None:
        super().__init__(color, width)
        self.start = QPoint()
        self.end   = QPoint()

    def draw(self, p: QPainter) -> None:
        if not self.is_valid():
            return
        p.setPen(self._pen(self.color, self.width,
                           Qt.PenCapStyle.SquareCap, Qt.PenJoinStyle.MiterJoin))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(QRect(self.start, self.end).normalized())

    def is_valid(self) -> bool:
        r = QRect(self.start, self.end).normalized()
        return r.width() > 2 and r.height() > 2


class EllipseShape(Shape):
    def __init__(self, color: QColor, width: int) -> None:
        super().__init__(color, width)
        self.start = QPoint()
        self.end   = QPoint()

    def draw(self, p: QPainter) -> None:
        if not self.is_valid():
            return
        p.setPen(self._pen(self.color, self.width))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QRect(self.start, self.end).normalized())

    def is_valid(self) -> bool:
        r = QRect(self.start, self.end).normalized()
        return r.width() > 2 and r.height() > 2


# ── Helpers ───────────────────────────────────────────────────────────────────

def _arrowhead(p: QPainter, start: QPoint, end: QPoint, width: int) -> None:
    angle = math.atan2(end.y() - start.y(), end.x() - start.x())
    size  = max(14, width * 4)
    p1 = QPoint(int(end.x() + size * math.cos(angle + math.pi * 5 / 6)),
                int(end.y() + size * math.sin(angle + math.pi * 5 / 6)))
    p2 = QPoint(int(end.x() + size * math.cos(angle - math.pi * 5 / 6)),
                int(end.y() + size * math.sin(angle - math.pi * 5 / 6)))
    p.drawPolygon(QPolygon([end, p1, p2]))


def make_shape(tool: str, color: QColor, width: int) -> Shape:
    return {
        "pencil":  Stroke,
        "arrow":   Arrow,
        "rect":    RectShape,
        "ellipse": EllipseShape,
    }[tool](color, width)
