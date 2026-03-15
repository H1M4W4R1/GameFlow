"""
Constant nodes — emit a fixed value with no connectable input pins.

The value is set by double-clicking the field inside the node body.
All constants push their value once at graph start and re-push whenever
the field is changed at runtime.
"""
from __future__ import annotations

from typing import Any

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui  import QPainter, QColor, QFont

from core.node_base import NodeBase
from core.types     import PinDescriptor, PinDirection, PinType


# ─────────────────────────────────────────────────────────────────────────────
# Float Constant
# ─────────────────────────────────────────────────────────────────────────────

class FloatConstantNode(NodeBase):
    """
    Emits a constant float.
    Double-click the value field in the node body to change it.
    """
    NODE_NAME  = "Float"
    NODE_GROUP = "Constants"
    PINS = [
        PinDescriptor("output", PinDirection.OUTPUT, PinType.FLOAT),
    ]
    EDITABLE_FIELDS = {
        "value": (float, 0.0),
    }
    MIN_WIDTH  = 150.0
    MIN_HEIGHT = 80.0

    def on_start(self) -> None:
        self._push()

    def execute(self, trigger_pin: str) -> None:
        self._push()

    def on_field_changed(self, name: str, value: Any) -> None:
        self._push()

    def _push(self) -> None:
        self.set_output("output", float(self.get_field("value") or 0.0))

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        # Large value preview above the field editor area
        v = float(self.get_field("value") or 0.0)
        painter.setPen(QColor("#4fc3f7"))
        painter.setFont(QFont("Courier New", 18, QFont.Weight.Bold))
        preview = QRectF(rect.x(), rect.y(), rect.width(), 32)
        painter.drawText(preview, Qt.AlignmentFlag.AlignCenter, f"{v:.4g}")


# ─────────────────────────────────────────────────────────────────────────────
# Int Constant
# ─────────────────────────────────────────────────────────────────────────────

class IntConstantNode(NodeBase):
    """
    Emits a constant integer.
    Double-click the value field to change it.
    """
    NODE_NAME  = "Integer"
    NODE_GROUP = "Constants"
    PINS = [
        PinDescriptor("output", PinDirection.OUTPUT, PinType.INT),
    ]
    EDITABLE_FIELDS = {
        "value": (int, 0),
    }
    MIN_WIDTH  = 150.0
    MIN_HEIGHT = 80.0

    def on_start(self) -> None:
        self._push()

    def execute(self, trigger_pin: str) -> None:
        self._push()

    def on_field_changed(self, name: str, value: Any) -> None:
        self._push()

    def _push(self) -> None:
        self.set_output("output", int(self.get_field("value") or 0))

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        v = int(self.get_field("value") or 0)
        painter.setPen(QColor("#aed581"))
        painter.setFont(QFont("Courier New", 18, QFont.Weight.Bold))
        preview = QRectF(rect.x(), rect.y(), rect.width(), 32)
        painter.drawText(preview, Qt.AlignmentFlag.AlignCenter, str(v))


# ─────────────────────────────────────────────────────────────────────────────
# String Constant
# ─────────────────────────────────────────────────────────────────────────────

class StringConstantNode(NodeBase):
    """
    Emits a constant string.
    Double-click the value field to change it.
    """
    NODE_NAME  = "String"
    NODE_GROUP = "Constants"
    PINS = [
        PinDescriptor("output", PinDirection.OUTPUT, PinType.STRING),
    ]
    EDITABLE_FIELDS = {
        "value": (str, ""),
    }
    MIN_WIDTH  = 160.0
    MIN_HEIGHT = 80.0

    def on_start(self) -> None:
        self._push()

    def execute(self, trigger_pin: str) -> None:
        self._push()

    def on_field_changed(self, name: str, value: Any) -> None:
        self._push()

    def _push(self) -> None:
        self.set_output("output", str(self.get_field("value") or ""))

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        v   = str(self.get_field("value") or "")
        txt = f'"{v}"' if len(v) <= 16 else f'"{v[:13]}…"'
        painter.setPen(QColor("#ce93d8"))
        painter.setFont(QFont("Courier New", 10))
        preview = QRectF(rect.x(), rect.y(), rect.width(), 32)
        painter.drawText(preview, Qt.AlignmentFlag.AlignCenter, txt)


# ─────────────────────────────────────────────────────────────────────────────
# Bool Constant
# ─────────────────────────────────────────────────────────────────────────────

class BoolConstantNode(NodeBase):
    """
    Emits a constant boolean.
    Double-click the value field and type  true / false  (or 1 / 0).
    """
    NODE_NAME  = "Boolean"
    NODE_GROUP = "Constants"
    PINS = [
        PinDescriptor("output", PinDirection.OUTPUT, PinType.BOOL),
    ]
    EDITABLE_FIELDS = {
        "value": (bool, False),
    }
    MIN_WIDTH  = 150.0
    MIN_HEIGHT = 80.0

    def on_start(self) -> None:
        self._push()

    def execute(self, trigger_pin: str) -> None:
        self._push()

    def on_field_changed(self, name: str, value: Any) -> None:
        self._push()

    def _push(self) -> None:
        self.set_output("output", bool(self.get_field("value")))

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        v     = bool(self.get_field("value"))
        color = QColor("#4caf50") if v else QColor("#ef5350")
        painter.setPen(color)
        painter.setFont(QFont("Courier New", 14, QFont.Weight.Bold))
        preview = QRectF(rect.x(), rect.y(), rect.width(), 32)
        painter.drawText(preview, Qt.AlignmentFlag.AlignCenter, "TRUE" if v else "FALSE")
