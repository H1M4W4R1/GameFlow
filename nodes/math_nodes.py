"""
Math nodes — individual arithmetic / trig / comparison nodes.

Design rules:
  • All math nodes are PURE DATA — no exec_in / exec_out.
  • They react to incoming pin changes via on_data_received() and immediately
    push result downstream.
  • Constant operands can be set via EDITABLE_FIELDS (double-click).
  • Input pins override the editable field value when connected.
"""
from __future__ import annotations

import math
from typing import Any

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui  import QPainter, QColor, QFont

from core.node_base import NodeBase
from core.types     import PinDescriptor, PinDirection, PinType


# ─────────────────────────────────────────────────────────────────────────────
# Shared base for binary ops (a OP b → result)
# ─────────────────────────────────────────────────────────────────────────────

class _BinaryMathNode(NodeBase):
    """
    Internal base for nodes with two float inputs and one float output.
    Subclasses set _op() and paint_symbol.
    """
    NODE_GROUP = "Math"
    PINS = [
        PinDescriptor("a",      PinDirection.INPUT,  PinType.FLOAT, default=0.0),
        PinDescriptor("b",      PinDirection.INPUT,  PinType.FLOAT, default=0.0),
        PinDescriptor("result", PinDirection.OUTPUT, PinType.FLOAT),
    ]
    # Each subclass may provide EDITABLE_FIELDS for b if it's commonly constant
    PAINT_SYMBOL: str = "?"
    MIN_WIDTH  = 150.0
    MIN_HEIGHT = 70.0

    def on_start(self) -> None:
        self._compute()

    def on_data_received(self, pin_name: str, value: Any) -> None:
        self._compute()

    def execute(self, trigger_pin: str) -> None:
        self._compute()

    def _a(self) -> float:
        return float(self.get_input("a") or 0.0)

    def _b(self) -> float:
        return float(self.get_input("b") or 0.0)

    def _compute(self) -> None:
        raise NotImplementedError

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        painter.setPen(QColor("#90a4ae"))
        painter.setFont(QFont("Courier New", 13, QFont.Weight.Bold))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self.PAINT_SYMBOL)


class _UnaryMathNode(NodeBase):
    """Internal base for single-input math nodes."""
    NODE_GROUP = "Math"
    PINS = [
        PinDescriptor("a",      PinDirection.INPUT,  PinType.FLOAT, default=0.0),
        PinDescriptor("result", PinDirection.OUTPUT, PinType.FLOAT),
    ]
    PAINT_SYMBOL: str = "f(x)"
    MIN_WIDTH  = 140.0
    MIN_HEIGHT = 70.0

    def on_start(self) -> None:
        self._compute()

    def on_data_received(self, pin_name: str, value: Any) -> None:
        self._compute()

    def execute(self, trigger_pin: str) -> None:
        self._compute()

    def _a(self) -> float:
        return float(self.get_input("a") or 0.0)

    def _compute(self) -> None:
        raise NotImplementedError

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        painter.setPen(QColor("#90a4ae"))
        painter.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self.PAINT_SYMBOL)


# ─────────────────────────────────────────────────────────────────────────────
# Binary operations
# ─────────────────────────────────────────────────────────────────────────────

class AddNode(_BinaryMathNode):
    """a + b"""
    NODE_NAME    = "Add"
    PAINT_SYMBOL = "a + b"

    def _compute(self) -> None:
        self.set_output("result", self._a() + self._b())


class SubtractNode(_BinaryMathNode):
    """a − b"""
    NODE_NAME    = "Subtract"
    PAINT_SYMBOL = "a − b"

    def _compute(self) -> None:
        self.set_output("result", self._a() - self._b())


class MultiplyNode(_BinaryMathNode):
    """a × b"""
    NODE_NAME    = "Multiply"
    PAINT_SYMBOL = "a × b"

    def _compute(self) -> None:
        self.set_output("result", self._a() * self._b())


class DivideNode(_BinaryMathNode):
    """a ÷ b  (returns 0 if b == 0)"""
    NODE_NAME    = "Divide"
    PAINT_SYMBOL = "a ÷ b"

    def _compute(self) -> None:
        b = self._b()
        self.set_output("result", self._a() / b if b != 0.0 else 0.0)


class ModuloNode(_BinaryMathNode):
    """a mod b  (returns 0 if b == 0)"""
    NODE_NAME    = "Modulo"
    PAINT_SYMBOL = "a mod b"

    def _compute(self) -> None:
        b = self._b()
        self.set_output("result", self._a() % b if b != 0.0 else 0.0)


class PowerNode(_BinaryMathNode):
    """a ^ b"""
    NODE_NAME    = "Power"
    PAINT_SYMBOL = "a ^ b"

    def _compute(self) -> None:
        self.set_output("result", self._a() ** self._b())


class MinNode(_BinaryMathNode):
    """min(a, b)"""
    NODE_NAME    = "Min"
    PAINT_SYMBOL = "min(a,b)"

    def _compute(self) -> None:
        self.set_output("result", min(self._a(), self._b()))


class MaxNode(_BinaryMathNode):
    """max(a, b)"""
    NODE_NAME    = "Max"
    PAINT_SYMBOL = "max(a,b)"

    def _compute(self) -> None:
        self.set_output("result", max(self._a(), self._b()))


# ─────────────────────────────────────────────────────────────────────────────
# Unary operations
# ─────────────────────────────────────────────────────────────────────────────

class AbsNode(_UnaryMathNode):
    """| a |"""
    NODE_NAME    = "Abs"
    PAINT_SYMBOL = "| a |"

    def _compute(self) -> None:
        self.set_output("result", abs(self._a()))


class NegateNode(_UnaryMathNode):
    """-a"""
    NODE_NAME    = "Negate"
    PAINT_SYMBOL = "−a"

    def _compute(self) -> None:
        self.set_output("result", -self._a())


class SinNode(_UnaryMathNode):
    """sin(a)  [radians]"""
    NODE_NAME    = "Sin"
    PAINT_SYMBOL = "sin(a)"

    def _compute(self) -> None:
        self.set_output("result", math.sin(self._a()))


class CosNode(_UnaryMathNode):
    """cos(a)  [radians]"""
    NODE_NAME    = "Cos"
    PAINT_SYMBOL = "cos(a)"

    def _compute(self) -> None:
        self.set_output("result", math.cos(self._a()))


class TanNode(_UnaryMathNode):
    """tan(a)  [radians]"""
    NODE_NAME    = "Tan"
    PAINT_SYMBOL = "tan(a)"

    def _compute(self) -> None:
        self.set_output("result", math.tan(self._a()))


class SqrtNode(_UnaryMathNode):
    """√ a  (uses abs(a) to avoid domain errors)"""
    NODE_NAME    = "Sqrt"
    PAINT_SYMBOL = "√ a"

    def _compute(self) -> None:
        self.set_output("result", math.sqrt(abs(self._a())))


class FloorNode(_UnaryMathNode):
    """⌊ a ⌋"""
    NODE_NAME    = "Floor"
    PAINT_SYMBOL = "⌊ a ⌋"

    def _compute(self) -> None:
        self.set_output("result", float(math.floor(self._a())))


class CeilNode(_UnaryMathNode):
    """⌈ a ⌉"""
    NODE_NAME    = "Ceil"
    PAINT_SYMBOL = "⌈ a ⌉"

    def _compute(self) -> None:
        self.set_output("result", float(math.ceil(self._a())))


class RoundNode(_UnaryMathNode):
    """round(a)"""
    NODE_NAME    = "Round"
    PAINT_SYMBOL = "round(a)"

    def _compute(self) -> None:
        self.set_output("result", float(round(self._a())))


# ─────────────────────────────────────────────────────────────────────────────
# Clamp  (three inputs — value, min, max — all pure data)
# ─────────────────────────────────────────────────────────────────────────────

class ClampNode(NodeBase):
    """
    Clamps value to [min_val, max_val].
    All three inputs are connectable pins; min/max also have editable defaults.
    Pure data — reacts instantly on any input change.
    """
    NODE_NAME  = "Clamp"
    NODE_GROUP = "Math"
    PINS = [
        PinDescriptor("value",   PinDirection.INPUT,  PinType.FLOAT, default=0.0),
        PinDescriptor("min_val", PinDirection.INPUT,  PinType.FLOAT, default=0.0),
        PinDescriptor("max_val", PinDirection.INPUT,  PinType.FLOAT, default=1.0),
        PinDescriptor("result",  PinDirection.OUTPUT, PinType.FLOAT),
    ]
    EDITABLE_FIELDS = {
        "min": (float, 0.0),
        "max": (float, 1.0),
    }
    MIN_WIDTH  = 160.0
    MIN_HEIGHT = 80.0

    def on_start(self) -> None:
        self._compute()

    def execute(self, trigger_pin: str) -> None:
        self._compute()

    def on_data_received(self, pin_name: str, value: Any) -> None:
        self._compute()

    def on_field_changed(self, name: str, value: Any) -> None:
        self._compute()

    def _compute(self) -> None:
        v  = float(self.get_input("value")   or 0.0)
        # Pin values take priority; fall back to editable field defaults
        lo_pin = self.get_input("min_val")
        hi_pin = self.get_input("max_val")
        lo = float(lo_pin if lo_pin is not None else self.get_field("min") or 0.0)
        hi = float(hi_pin if hi_pin is not None else self.get_field("max") or 1.0)
        self.set_output("result", max(lo, min(v, hi)))

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        lo = self.get_field("min") or 0.0
        hi = self.get_field("max") or 1.0
        painter.setPen(QColor("#90a4ae"))
        painter.setFont(QFont("Courier New", 8))
        painter.drawText(
            QRectF(rect.x(), rect.y(), rect.width(), 20),
            Qt.AlignmentFlag.AlignCenter,
            f"[{float(lo):.3g} … {float(hi):.3g}]",
        )


# ─────────────────────────────────────────────────────────────────────────────
# Lerp  (linear interpolation)
# ─────────────────────────────────────────────────────────────────────────────

class LerpNode(NodeBase):
    """
    Linear interpolation: result = a + (b − a) × t
    t = 0 → a,  t = 1 → b.  t is clamped to [0, 1].
    Pure data node.
    """
    NODE_NAME  = "Lerp"
    NODE_GROUP = "Math"
    PINS = [
        PinDescriptor("a",      PinDirection.INPUT,  PinType.FLOAT, default=0.0),
        PinDescriptor("b",      PinDirection.INPUT,  PinType.FLOAT, default=1.0),
        PinDescriptor("t",      PinDirection.INPUT,  PinType.FLOAT, default=0.5),
        PinDescriptor("result", PinDirection.OUTPUT, PinType.FLOAT),
    ]
    MIN_WIDTH  = 150.0
    MIN_HEIGHT = 70.0

    def on_start(self) -> None:
        self._compute()

    def on_data_received(self, pin_name: str, value: Any) -> None:
        self._compute()

    def execute(self, trigger_pin: str) -> None:
        self._compute()

    def _compute(self) -> None:
        a = float(self.get_input("a") or 0.0)
        b = float(self.get_input("b") or 1.0)
        t = max(0.0, min(1.0, float(self.get_input("t") or 0.0)))
        self.set_output("result", a + (b - a) * t)

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        t = float(self.get_input("t") or 0.0)
        painter.setPen(QColor("#90a4ae"))
        painter.setFont(QFont("Courier New", 9))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, f"lerp  t={t:.2f}")


# ─────────────────────────────────────────────────────────────────────────────
# Map Range
# ─────────────────────────────────────────────────────────────────────────────

class MapRangeNode(NodeBase):
    """
    Re-maps a value from [in_min, in_max] → [out_min, out_max].
    Equivalent to Arduino's map() but for floats.
    Pure data node; range limits settable via editable fields.
    """
    NODE_NAME  = "Map Range"
    NODE_GROUP = "Math"
    PINS = [
        PinDescriptor("value",   PinDirection.INPUT,  PinType.FLOAT, default=0.0),
        PinDescriptor("result",  PinDirection.OUTPUT, PinType.FLOAT),
    ]
    EDITABLE_FIELDS = {
        "in_min":  (float, 0.0),
        "in_max":  (float, 1.0),
        "out_min": (float, 0.0),
        "out_max": (float, 255.0),
    }
    MIN_WIDTH  = 170.0
    MIN_HEIGHT = 80.0

    def on_start(self) -> None:
        self._compute()

    def on_data_received(self, pin_name: str, value: Any) -> None:
        self._compute()

    def execute(self, trigger_pin: str) -> None:
        self._compute()

    def on_field_changed(self, name: str, value: Any) -> None:
        self._compute()

    def _compute(self) -> None:
        v       = float(self.get_input("value") or 0.0)
        in_min  = float(self.get_field("in_min")  or 0.0)
        in_max  = float(self.get_field("in_max")  or 1.0)
        out_min = float(self.get_field("out_min") or 0.0)
        out_max = float(self.get_field("out_max") or 255.0)
        if in_max == in_min:
            result = out_min
        else:
            t      = (v - in_min) / (in_max - in_min)
            result = out_min + t * (out_max - out_min)
        self.set_output("result", result)

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        i0 = self.get_field("in_min") or 0.0
        i1 = self.get_field("in_max") or 1.0
        o0 = self.get_field("out_min") or 0.0
        o1 = self.get_field("out_max") or 255.0
        painter.setPen(QColor("#90a4ae"))
        painter.setFont(QFont("Courier New", 7))
        painter.drawText(
            QRectF(rect.x(), rect.y(), rect.width(), 20),
            Qt.AlignmentFlag.AlignCenter,
            f"[{i0:.3g},{i1:.3g}] → [{o0:.3g},{o1:.3g}]",
        )


# ─────────────────────────────────────────────────────────────────────────────
# Type Conversion nodes
# ─────────────────────────────────────────────────────────────────────────────

class IntToFloatNode(NodeBase):
    """Converts an INT pin to a FLOAT pin.  Useful when wiring integer
    sources (counters, constants) into float-expecting inputs."""
    NODE_NAME  = "Int → Float"
    NODE_GROUP = "Conversion"
    PINS = [
        PinDescriptor("input",  PinDirection.INPUT,  PinType.INT,   default=0),
        PinDescriptor("output", PinDirection.OUTPUT, PinType.FLOAT),
    ]
    MIN_WIDTH  = 150.0
    MIN_HEIGHT = 60.0

    def on_start(self) -> None:
        self._convert()

    def on_data_received(self, pin_name: str, value: Any) -> None:
        self._convert()

    def execute(self, trigger_pin: str) -> None:
        self._convert()

    def _convert(self) -> None:
        v = self.get_input("input")
        self.set_output("output", float(v) if v is not None else 0.0)

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        painter.setPen(QColor("#90a4ae"))
        painter.setFont(QFont("Courier New", 9))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "int → float")


class FloatToIntNode(NodeBase):
    """Converts a FLOAT pin to an INT pin (rounds to nearest integer)."""
    NODE_NAME  = "Float → Int"
    NODE_GROUP = "Conversion"
    PINS = [
        PinDescriptor("input",  PinDirection.INPUT,  PinType.FLOAT, default=0.0),
        PinDescriptor("output", PinDirection.OUTPUT, PinType.INT),
    ]
    MIN_WIDTH  = 150.0
    MIN_HEIGHT = 60.0

    def on_start(self) -> None:
        self._convert()

    def on_data_received(self, pin_name: str, value: Any) -> None:
        self._convert()

    def execute(self, trigger_pin: str) -> None:
        self._convert()

    def _convert(self) -> None:
        v = self.get_input("input")
        self.set_output("output", int(round(float(v))) if v is not None else 0)

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        painter.setPen(QColor("#90a4ae"))
        painter.setFont(QFont("Courier New", 9))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "float → int")


class BoolToFloatNode(NodeBase):
    """Converts BOOL → FLOAT  (False=0.0, True=1.0)."""
    NODE_NAME  = "Bool → Float"
    NODE_GROUP = "Conversion"
    PINS = [
        PinDescriptor("input",  PinDirection.INPUT,  PinType.BOOL,  default=False),
        PinDescriptor("output", PinDirection.OUTPUT, PinType.FLOAT),
    ]
    MIN_WIDTH  = 155.0
    MIN_HEIGHT = 60.0

    def on_start(self) -> None:
        self._convert()

    def on_data_received(self, pin_name: str, value: Any) -> None:
        self._convert()

    def execute(self, trigger_pin: str) -> None:
        self._convert()

    def _convert(self) -> None:
        v = self.get_input("input")
        self.set_output("output", 1.0 if v else 0.0)

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        painter.setPen(QColor("#90a4ae"))
        painter.setFont(QFont("Courier New", 9))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "bool → float")


class AnyToStringNode(NodeBase):
    """Converts any value to its string representation."""
    NODE_NAME  = "Any → String"
    NODE_GROUP = "Conversion"
    PINS = [
        PinDescriptor("input",  PinDirection.INPUT,  PinType.ANY,    default=0),
        PinDescriptor("output", PinDirection.OUTPUT, PinType.STRING),
    ]
    MIN_WIDTH  = 155.0
    MIN_HEIGHT = 60.0

    def on_start(self) -> None:
        self._convert()

    def on_data_received(self, pin_name: str, value: Any) -> None:
        self._convert()

    def execute(self, trigger_pin: str) -> None:
        self._convert()

    def _convert(self) -> None:
        v = self.get_input("input")
        self.set_output("output", str(v) if v is not None else "")

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        painter.setPen(QColor("#90a4ae"))
        painter.setFont(QFont("Courier New", 9))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "any → str")


class StringToFloatNode(NodeBase):
    """Parses a string to float (outputs 0.0 if parse fails)."""
    NODE_NAME  = "String → Float"
    NODE_GROUP = "Conversion"
    PINS = [
        PinDescriptor("input",  PinDirection.INPUT,  PinType.STRING, default="0"),
        PinDescriptor("output", PinDirection.OUTPUT, PinType.FLOAT),
        PinDescriptor("valid",  PinDirection.OUTPUT, PinType.BOOL),
    ]
    MIN_WIDTH  = 160.0
    MIN_HEIGHT = 60.0

    def on_start(self) -> None:
        self._convert()

    def on_data_received(self, pin_name: str, value: Any) -> None:
        self._convert()

    def execute(self, trigger_pin: str) -> None:
        self._convert()

    def _convert(self) -> None:
        s = str(self.get_input("input") or "")
        try:
            self.set_output("output", float(s))
            self.set_output("valid",  True)
        except ValueError:
            self.set_output("output", 0.0)
            self.set_output("valid",  False)

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        painter.setPen(QColor("#90a4ae"))
        painter.setFont(QFont("Courier New", 9))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "str → float")
