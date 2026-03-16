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


class _ConstantBase(NodeBase):
    """Shared base for all constant nodes — pushes fresh output on wire connect."""
    def on_output_wire_connected(self, pin_name: str) -> None:
        self._push()


def _parse_color(s) -> tuple[float, float, float, float]:
    """Parse color from hex #RRGGBB or #RRGGBBAA or (r,g,b,a). Returns (r,g,b,a) 0-1."""
    if s is None:
        return (1.0, 1.0, 1.0, 1.0)
    if isinstance(s, (tuple, list)) and len(s) >= 3:
        r = max(0, min(1, float(s[0])))
        g = max(0, min(1, float(s[1])))
        b = max(0, min(1, float(s[2])))
        a = max(0, min(1, float(s[3]))) if len(s) > 3 else 1.0
        return (r, g, b, a)
    s = str(s).strip()
    if s.startswith("#"):
        s = s[1:]
        if len(s) == 6:
            return (int(s[0:2], 16) / 255, int(s[2:4], 16) / 255,
                    int(s[4:6], 16) / 255, 1.0)
        if len(s) == 8:
            return (int(s[0:2], 16) / 255, int(s[2:4], 16) / 255,
                    int(s[4:6], 16) / 255, int(s[6:8], 16) / 255)
    return (1.0, 1.0, 1.0, 1.0)


# ─────────────────────────────────────────────────────────────────────────────
# Float Constant
# ─────────────────────────────────────────────────────────────────────────────

class FloatConstantNode(_ConstantBase):
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

class IntConstantNode(_ConstantBase):
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

class StringConstantNode(_ConstantBase):
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

class BoolConstantNode(_ConstantBase):
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


# ─────────────────────────────────────────────────────────────────────────────
# Color Constant (outputs Color type; edit as #RRGGBB — ColorPicker in UI optional)
# ─────────────────────────────────────────────────────────────────────────────

class ColorConstantNode(_ConstantBase):
    """
    Emits a constant Color (r,g,b,a) 0-1.
    Double-click the color field to edit as #RRGGBB or #RRGGBBAA.
    """
    NODE_NAME  = "Color"
    NODE_GROUP = "Constants"
    PINS = [
        PinDescriptor("output", PinDirection.OUTPUT, PinType.COLOR),
    ]
    EDITABLE_FIELDS = {
        "color": (str, "#ffffff"),
    }
    MIN_WIDTH  = 160.0
    MIN_HEIGHT = 100.0

    def on_start(self) -> None:
        self._push()

    def execute(self, trigger_pin: str) -> None:
        self._push()

    def on_field_changed(self, name: str, value: Any) -> None:
        self._push()

    def _push(self) -> None:
        raw = self.get_field("color") or "#ffffff"
        self.set_output("output", _parse_color(raw))

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        c = _parse_color(self.get_field("color") or "#ffffff")
        r, g, b, a = int(c[0] * 255), int(c[1] * 255), int(c[2] * 255), int(c[3] * 255)
        swatch = QRectF(rect.x() + (rect.width() - 40) / 2, rect.y() + 2, 40, 20)
        painter.setPen(QColor("#444"))
        painter.setBrush(QColor(r, g, b, a))
        painter.drawRoundedRect(swatch, 3, 3)
        painter.setPen(QColor("#e57373"))
        painter.setFont(QFont("Courier New", 8))
        painter.drawText(
            QRectF(rect.x(), rect.y() + 24, rect.width(), 18),
            Qt.AlignmentFlag.AlignCenter,
            f"#{r:02x}{g:02x}{b:02x}",
        )
