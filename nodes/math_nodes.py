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
# Component-wise helpers for arithmetic on scalars, vectors, and colors
# ─────────────────────────────────────────────────────────────────────────────

def _apply_binary(op, a, b):
    """Apply a binary op to scalars, or component-wise to sequences (vectors/colors)."""
    a_seq = isinstance(a, (tuple, list))
    b_seq = isinstance(b, (tuple, list))
    if a_seq or b_seq:
        la = list(a) if a_seq else None
        lb = list(b) if b_seq else None
        if la is None:
            la = [float(a)] * len(lb)
        if lb is None:
            lb = [float(b)] * len(la)
        n = min(len(la), len(lb))
        return tuple(op(float(la[i]), float(lb[i])) for i in range(n))
    try:
        return op(float(a), float(b))
    except (TypeError, ValueError):
        return 0.0


def _apply_unary(op, a):
    """Apply a unary op to a scalar, or component-wise to a sequence."""
    if isinstance(a, (tuple, list)):
        return tuple(op(float(x)) for x in a)
    try:
        return op(float(a))
    except (TypeError, ValueError):
        return 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Shared base for binary ops (a OP b → result)
# ─────────────────────────────────────────────────────────────────────────────

class _BinaryMathNode(NodeBase):
    """
    Internal base for nodes with two ANY inputs and one ANY output.
    Operations are applied component-wise to vectors/colors, or as scalars.
    Subclasses implement _compute().
    """
    NODE_GROUP = "Math / Arithmetic"
    PINS = [
        PinDescriptor("a",      PinDirection.INPUT,  PinType.ANY, default=0.0),
        PinDescriptor("b",      PinDirection.INPUT,  PinType.ANY, default=0.0),
        PinDescriptor("result", PinDirection.OUTPUT, PinType.ANY),
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

    def _a(self) -> Any:
        v = self.get_input("a")
        return v if v is not None else 0.0

    def _b(self) -> Any:
        v = self.get_input("b")
        return v if v is not None else 0.0

    def _compute(self) -> None:
        raise NotImplementedError

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        painter.setPen(QColor("#90a4ae"))
        painter.setFont(QFont("Courier New", 13, QFont.Weight.Bold))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self.PAINT_SYMBOL)


class _UnaryMathNode(NodeBase):
    """Internal base for single-input math nodes. Operates component-wise on vectors/colors."""
    NODE_GROUP = "Math / Arithmetic"
    PINS = [
        PinDescriptor("a",      PinDirection.INPUT,  PinType.ANY, default=0.0),
        PinDescriptor("result", PinDirection.OUTPUT, PinType.ANY),
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

    def _a(self) -> Any:
        v = self.get_input("a")
        return v if v is not None else 0.0

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
    """a + b  (component-wise for vectors/colors)"""
    NODE_NAME    = "Add"
    PAINT_SYMBOL = "a + b"

    def _compute(self) -> None:
        self.set_output("result", _apply_binary(lambda a, b: a + b, self._a(), self._b()))


class SubtractNode(_BinaryMathNode):
    """a − b  (component-wise for vectors/colors)"""
    NODE_NAME    = "Subtract"
    PAINT_SYMBOL = "a − b"

    def _compute(self) -> None:
        self.set_output("result", _apply_binary(lambda a, b: a - b, self._a(), self._b()))


class MultiplyNode(_BinaryMathNode):
    """a × b  (component-wise for vectors/colors)"""
    NODE_NAME    = "Multiply"
    PAINT_SYMBOL = "a × b"

    def _compute(self) -> None:
        self.set_output("result", _apply_binary(lambda a, b: a * b, self._a(), self._b()))


class DivideNode(_BinaryMathNode):
    """a ÷ b  (returns 0 per component where b == 0)"""
    NODE_NAME    = "Divide"
    PAINT_SYMBOL = "a ÷ b"

    def _compute(self) -> None:
        self.set_output("result", _apply_binary(
            lambda a, b: a / b if b != 0.0 else 0.0, self._a(), self._b()
        ))


class ModuloNode(_BinaryMathNode):
    """a mod b  (returns 0 per component where b == 0)"""
    NODE_NAME    = "Modulo"
    PAINT_SYMBOL = "a mod b"

    def _compute(self) -> None:
        self.set_output("result", _apply_binary(
            lambda a, b: a % b if b != 0.0 else 0.0, self._a(), self._b()
        ))


class PowerNode(_BinaryMathNode):
    """a ^ b  (component-wise for vectors/colors)"""
    NODE_NAME    = "Power"
    PAINT_SYMBOL = "a ^ b"

    def _compute(self) -> None:
        self.set_output("result", _apply_binary(lambda a, b: a ** b, self._a(), self._b()))


class MinNode(_BinaryMathNode):
    """min(a, b)  (component-wise for vectors/colors)"""
    NODE_NAME    = "Min"
    NODE_GROUP   = "Math / Min-Max"
    PAINT_SYMBOL = "min(a,b)"

    def _compute(self) -> None:
        self.set_output("result", _apply_binary(min, self._a(), self._b()))


class MaxNode(_BinaryMathNode):
    """max(a, b)  (component-wise for vectors/colors)"""
    NODE_NAME    = "Max"
    NODE_GROUP   = "Math / Min-Max"
    PAINT_SYMBOL = "max(a,b)"

    def _compute(self) -> None:
        self.set_output("result", _apply_binary(max, self._a(), self._b()))


# ─────────────────────────────────────────────────────────────────────────────
# Unary operations
# ─────────────────────────────────────────────────────────────────────────────

class AbsNode(_UnaryMathNode):
    """| a |  (component-wise for vectors/colors)"""
    NODE_NAME    = "Abs"
    PAINT_SYMBOL = "| a |"

    def _compute(self) -> None:
        self.set_output("result", _apply_unary(abs, self._a()))


class NegateNode(_UnaryMathNode):
    """-a  (component-wise for vectors/colors)"""
    NODE_NAME    = "Negate"
    PAINT_SYMBOL = "−a"

    def _compute(self) -> None:
        self.set_output("result", _apply_unary(lambda x: -x, self._a()))


class ReciprocalNode(_UnaryMathNode):
    """1 ÷ a  (component-wise for vectors/colors; returns 0 where a == 0)"""
    NODE_NAME    = "Reciprocal"
    PAINT_SYMBOL = "1 ÷ a"

    def _compute(self) -> None:
        self.set_output("result", _apply_unary(lambda x: 1.0 / x if x != 0.0 else 0.0, self._a()))


class OneMinusNode(_UnaryMathNode):
    """1 − a  (component-wise for vectors/colors)"""
    NODE_NAME    = "One Minus"
    PAINT_SYMBOL = "1 − a"

    def _compute(self) -> None:
        self.set_output("result", _apply_unary(lambda x: 1.0 - x, self._a()))


class SinNode(_UnaryMathNode):
    """sin(a)  [radians, component-wise for vectors]"""
    NODE_NAME    = "Sin"
    NODE_GROUP   = "Math / Trigonometric"
    PAINT_SYMBOL = "sin(a)"

    def _compute(self) -> None:
        self.set_output("result", _apply_unary(math.sin, self._a()))


class CosNode(_UnaryMathNode):
    """cos(a)  [radians, component-wise for vectors]"""
    NODE_NAME    = "Cos"
    NODE_GROUP   = "Math / Trigonometric"
    PAINT_SYMBOL = "cos(a)"

    def _compute(self) -> None:
        self.set_output("result", _apply_unary(math.cos, self._a()))


class TanNode(_UnaryMathNode):
    """tan(a)  [radians, component-wise for vectors]"""
    NODE_NAME    = "Tan"
    NODE_GROUP   = "Math / Trigonometric"
    PAINT_SYMBOL = "tan(a)"

    def _compute(self) -> None:
        self.set_output("result", _apply_unary(math.tan, self._a()))


class SqrtNode(_UnaryMathNode):
    """√ a  (uses abs per component to avoid domain errors)"""
    NODE_NAME    = "Sqrt"
    PAINT_SYMBOL = "√ a"

    def _compute(self) -> None:
        self.set_output("result", _apply_unary(lambda x: math.sqrt(abs(x)), self._a()))


class ExpNode(_UnaryMathNode):
    """e^a  (component-wise for vectors; clamps at overflow)"""
    NODE_NAME    = "Exp"
    NODE_GROUP   = "Math / Logarithm"
    PAINT_SYMBOL = "e^a"

    def _compute(self) -> None:
        def _safe_exp(x):
            try:
                return math.exp(x)
            except OverflowError:
                return float("inf")
        self.set_output("result", _apply_unary(_safe_exp, self._a()))


class LogNode(_UnaryMathNode):
    """ln(a)  — natural logarithm; returns 0 for a ≤ 0 (component-wise for vectors)"""
    NODE_NAME    = "Log"
    NODE_GROUP   = "Math / Logarithm"
    PAINT_SYMBOL = "ln(a)"

    def _compute(self) -> None:
        def _ln(x):
            return math.log(x) if x > 0 else 0.0
        self.set_output("result", _apply_unary(_ln, self._a()))


class Log10Node(_UnaryMathNode):
    """log₁₀(a)  — common logarithm; returns 0 for a ≤ 0 (component-wise for vectors)"""
    NODE_NAME    = "Log10"
    NODE_GROUP   = "Math / Logarithm"
    PAINT_SYMBOL = "log₁₀(a)"

    def _compute(self) -> None:
        def _log10(x):
            return math.log10(x) if x > 0 else 0.0
        self.set_output("result", _apply_unary(_log10, self._a()))


class LogNNode(_BinaryMathNode):
    """log_b(a)  — logarithm of a in base b; returns 0 for invalid domain (component-wise)"""
    NODE_NAME    = "LogN"
    NODE_GROUP   = "Math / Logarithm"
    PAINT_SYMBOL = "log_b(a)"

    def _compute(self) -> None:
        def _logn(a, b):
            if a <= 0 or b <= 0 or b == 1.0:
                return 0.0
            return math.log(a) / math.log(b)
        self.set_output("result", _apply_binary(_logn, self._a(), self._b()))


class SignNode(_UnaryMathNode):
    """sgn(a)  — returns −1, 0, or +1 based on sign (component-wise for vectors)"""
    NODE_NAME    = "Sign"
    PAINT_SYMBOL = "sgn(a)"

    def _compute(self) -> None:
        def _sign(x):
            if x > 0:
                return 1.0
            if x < 0:
                return -1.0
            return 0.0
        self.set_output("result", _apply_unary(_sign, self._a()))


class FloorNode(_UnaryMathNode):
    """⌊ a ⌋  (component-wise for vectors/colors)"""
    NODE_NAME    = "Floor"
    NODE_GROUP   = "Math / Rounding"
    PAINT_SYMBOL = "⌊ a ⌋"

    def _compute(self) -> None:
        self.set_output("result", _apply_unary(lambda x: float(math.floor(x)), self._a()))


class CeilNode(_UnaryMathNode):
    """⌈ a ⌉  (component-wise for vectors/colors)"""
    NODE_NAME    = "Ceil"
    NODE_GROUP   = "Math / Rounding"
    PAINT_SYMBOL = "⌈ a ⌉"

    def _compute(self) -> None:
        self.set_output("result", _apply_unary(lambda x: float(math.ceil(x)), self._a()))


class RoundNode(_UnaryMathNode):
    """round(a)  (component-wise for vectors/colors)"""
    NODE_NAME    = "Round"
    NODE_GROUP   = "Math / Rounding"
    PAINT_SYMBOL = "round(a)"

    def _compute(self) -> None:
        self.set_output("result", _apply_unary(lambda x: float(round(x)), self._a()))


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
    NODE_GROUP = "Math / Min-Max"
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
    NODE_GROUP = "Math / Interpolation"
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
    NODE_GROUP = "Math / Interpolation"
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
# Vector nodes (Math / Vector)
# ─────────────────────────────────────────────────────────────────────────────

def _vec2(x=0.0, y=0.0): return (float(x), float(y))
def _vec3(x=0.0, y=0.0, z=0.0): return (float(x), float(y), float(z))
def _vec4(x=0.0, y=0.0, z=0.0, w=0.0): return (float(x), float(y), float(z), float(w))


def _f(v, i):
    return float(v[i]) if isinstance(v, (tuple, list)) and len(v) > i else 0.0


class Vector2DConstructorNode(NodeBase):
    """Build a Vector2D from x, y components."""
    NODE_NAME  = "Vector2D"
    NODE_GROUP = "Math / Vector"
    PINS = [
        PinDescriptor("x",      PinDirection.INPUT,  PinType.FLOAT, default=0.0),
        PinDescriptor("y",      PinDirection.INPUT,  PinType.FLOAT, default=0.0),
        PinDescriptor("result", PinDirection.OUTPUT, PinType.VECTOR2D),
    ]
    MIN_WIDTH  = 140.0
    MIN_HEIGHT = 60.0

    def on_start(self) -> None:
        self._compute()

    def on_data_received(self, pin_name: str, value: Any) -> None:
        self._compute()

    def _compute(self) -> None:
        x = float(self.get_input("x") or 0.0)
        y = float(self.get_input("y") or 0.0)
        self.set_output("result", _vec2(x, y))

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        painter.setPen(QColor("#81c784"))
        painter.setFont(QFont("Courier New", 9))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "Vec2")


class Vector3DConstructorNode(NodeBase):
    """Build a Vector3D from x, y, z components."""
    NODE_NAME  = "Vector3D"
    NODE_GROUP = "Math / Vector"
    PINS = [
        PinDescriptor("x",      PinDirection.INPUT,  PinType.FLOAT, default=0.0),
        PinDescriptor("y",      PinDirection.INPUT,  PinType.FLOAT, default=0.0),
        PinDescriptor("z",      PinDirection.INPUT,  PinType.FLOAT, default=0.0),
        PinDescriptor("result", PinDirection.OUTPUT, PinType.VECTOR3D),
    ]
    MIN_WIDTH  = 140.0
    MIN_HEIGHT = 70.0

    def on_start(self) -> None:
        self._compute()

    def on_data_received(self, pin_name: str, value: Any) -> None:
        self._compute()

    def _compute(self) -> None:
        x = float(self.get_input("x") or 0.0)
        y = float(self.get_input("y") or 0.0)
        z = float(self.get_input("z") or 0.0)
        self.set_output("result", _vec3(x, y, z))

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        painter.setPen(QColor("#66bb6a"))
        painter.setFont(QFont("Courier New", 9))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "Vec3")


class Vector4DConstructorNode(NodeBase):
    """Build a Vector4D from x, y, z, w components."""
    NODE_NAME  = "Vector4D"
    NODE_GROUP = "Math / Vector"
    PINS = [
        PinDescriptor("x",      PinDirection.INPUT,  PinType.FLOAT, default=0.0),
        PinDescriptor("y",      PinDirection.INPUT,  PinType.FLOAT, default=0.0),
        PinDescriptor("z",      PinDirection.INPUT,  PinType.FLOAT, default=0.0),
        PinDescriptor("w",      PinDirection.INPUT,  PinType.FLOAT, default=0.0),
        PinDescriptor("result", PinDirection.OUTPUT, PinType.VECTOR4D),
    ]
    MIN_WIDTH  = 140.0
    MIN_HEIGHT = 80.0

    def on_start(self) -> None:
        self._compute()

    def on_data_received(self, pin_name: str, value: Any) -> None:
        self._compute()

    def _compute(self) -> None:
        x = float(self.get_input("x") or 0.0)
        y = float(self.get_input("y") or 0.0)
        z = float(self.get_input("z") or 0.0)
        w = float(self.get_input("w") or 0.0)
        self.set_output("result", _vec4(x, y, z, w))

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        painter.setPen(QColor("#4caf50"))
        painter.setFont(QFont("Courier New", 9))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "Vec4")


class Vector2DSplitNode(NodeBase):
    """Split Vector2D into x, y components."""
    NODE_NAME  = "Split Vector2D"
    NODE_GROUP = "Math / Vector"
    PINS = [
        PinDescriptor("vector", PinDirection.INPUT,  PinType.VECTOR2D),
        PinDescriptor("x",      PinDirection.OUTPUT, PinType.FLOAT),
        PinDescriptor("y",      PinDirection.OUTPUT, PinType.FLOAT),
    ]
    MIN_WIDTH  = 140.0
    MIN_HEIGHT = 60.0

    def on_start(self) -> None:
        self._compute()

    def on_data_received(self, pin_name: str, value: Any) -> None:
        self._compute()

    def _compute(self) -> None:
        v = self.get_input("vector")
        if v is not None and isinstance(v, (tuple, list)) and len(v) >= 2:
            self.set_output("x", float(v[0]))
            self.set_output("y", float(v[1]))
        else:
            self.set_output("x", 0.0)
            self.set_output("y", 0.0)

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        painter.setPen(QColor("#81c784"))
        painter.setFont(QFont("Courier New", 8))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "split Vec2")


class Vector3DSplitNode(NodeBase):
    """Split Vector3D into x, y, z components."""
    NODE_NAME  = "Split Vector3D"
    NODE_GROUP = "Math / Vector"
    PINS = [
        PinDescriptor("vector", PinDirection.INPUT,  PinType.VECTOR3D),
        PinDescriptor("x",      PinDirection.OUTPUT, PinType.FLOAT),
        PinDescriptor("y",      PinDirection.OUTPUT, PinType.FLOAT),
        PinDescriptor("z",      PinDirection.OUTPUT, PinType.FLOAT),
    ]
    MIN_WIDTH  = 140.0
    MIN_HEIGHT = 70.0

    def on_start(self) -> None:
        self._compute()

    def on_data_received(self, pin_name: str, value: Any) -> None:
        self._compute()

    def _compute(self) -> None:
        v = self.get_input("vector")
        if v is not None and isinstance(v, (tuple, list)) and len(v) >= 3:
            self.set_output("x", float(v[0]))
            self.set_output("y", float(v[1]))
            self.set_output("z", float(v[2]))
        else:
            self.set_output("x", 0.0)
            self.set_output("y", 0.0)
            self.set_output("z", 0.0)

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        painter.setPen(QColor("#66bb6a"))
        painter.setFont(QFont("Courier New", 8))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "split Vec3")


class Vector4DSplitNode(NodeBase):
    """Split Vector4D into x, y, z, w components."""
    NODE_NAME  = "Split Vector4D"
    NODE_GROUP = "Math / Vector"
    PINS = [
        PinDescriptor("vector", PinDirection.INPUT,  PinType.VECTOR4D),
        PinDescriptor("x",      PinDirection.OUTPUT, PinType.FLOAT),
        PinDescriptor("y",      PinDirection.OUTPUT, PinType.FLOAT),
        PinDescriptor("z",      PinDirection.OUTPUT, PinType.FLOAT),
        PinDescriptor("w",      PinDirection.OUTPUT, PinType.FLOAT),
    ]
    MIN_WIDTH  = 140.0
    MIN_HEIGHT = 80.0

    def on_start(self) -> None:
        self._compute()

    def on_data_received(self, pin_name: str, value: Any) -> None:
        self._compute()

    def _compute(self) -> None:
        v = self.get_input("vector")
        if v is not None and isinstance(v, (tuple, list)) and len(v) >= 4:
            self.set_output("x", float(v[0]))
            self.set_output("y", float(v[1]))
            self.set_output("z", float(v[2]))
            self.set_output("w", float(v[3]))
        else:
            self.set_output("x", 0.0)
            self.set_output("y", 0.0)
            self.set_output("z", 0.0)
            self.set_output("w", 0.0)

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        painter.setPen(QColor("#4caf50"))
        painter.setFont(QFont("Courier New", 8))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "split Vec4")


class DotProductNode(NodeBase):
    """
    Dot product of two vectors (or scalars).
    Vec2: ax·bx + ay·by  |  Vec3: + az·bz  |  Vec4: + aw·bw  |  scalar: a*b
    Always outputs Float.
    """
    NODE_NAME  = "Dot Product"
    NODE_GROUP = "Math / Vector"
    PINS = [
        PinDescriptor("a",      PinDirection.INPUT,  PinType.ANY),
        PinDescriptor("b",      PinDirection.INPUT,  PinType.ANY),
        PinDescriptor("result", PinDirection.OUTPUT, PinType.FLOAT),
    ]
    MIN_WIDTH  = 150.0
    MIN_HEIGHT = 60.0

    def on_start(self) -> None:
        self._compute()

    def on_data_received(self, pin_name: str, value: Any) -> None:
        self._compute()

    def _compute(self) -> None:
        a = self.get_input("a") or 0.0
        b = self.get_input("b") or 0.0
        if isinstance(a, (tuple, list)) or isinstance(b, (tuple, list)):
            la = list(a) if isinstance(a, (tuple, list)) else [float(a)]
            lb = list(b) if isinstance(b, (tuple, list)) else [float(b)]
            n = min(len(la), len(lb))
            self.set_output("result", sum(float(la[i]) * float(lb[i]) for i in range(n)))
        else:
            self.set_output("result", float(a) * float(b))

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        painter.setPen(QColor("#66bb6a"))
        painter.setFont(QFont("Courier New", 11))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "a · b")


class CrossProductNode(NodeBase):
    """
    Cross product of two vectors.
    Vec2 inputs → Float (ax·by − ay·bx, the 2D pseudo-cross).
    Vec3+ inputs → Vec3 (standard 3D cross, using first 3 components).
    """
    NODE_NAME  = "Cross Product"
    NODE_GROUP = "Math / Vector"
    PINS = [
        PinDescriptor("a",      PinDirection.INPUT,  PinType.ANY),
        PinDescriptor("b",      PinDirection.INPUT,  PinType.ANY),
        PinDescriptor("result", PinDirection.OUTPUT, PinType.ANY),
    ]
    MIN_WIDTH  = 150.0
    MIN_HEIGHT = 60.0

    def on_start(self) -> None:
        self._compute()

    def on_data_received(self, pin_name: str, value: Any) -> None:
        self._compute()

    def _compute(self) -> None:
        a = self.get_input("a") or (0.0, 0.0, 0.0)
        b = self.get_input("b") or (0.0, 0.0, 0.0)
        la = list(a) if isinstance(a, (tuple, list)) else [float(a)]
        lb = list(b) if isinstance(b, (tuple, list)) else [float(b)]
        n = max(len(la), len(lb))
        if n <= 2:
            # 2D pseudo-cross → scalar
            ax, ay = _f(la, 0), _f(la, 1)
            bx, by = _f(lb, 0), _f(lb, 1)
            self.set_output("result", ax * by - ay * bx)
        else:
            # 3D cross (uses first 3 components)
            ax, ay, az = _f(la, 0), _f(la, 1), _f(la, 2)
            bx, by, bz = _f(lb, 0), _f(lb, 1), _f(lb, 2)
            self.set_output("result", (
                ay * bz - az * by,
                az * bx - ax * bz,
                ax * by - ay * bx,
            ))

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        painter.setPen(QColor("#66bb6a"))
        painter.setFont(QFont("Courier New", 11))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "a × b")


# ─────────────────────────────────────────────────────────────────────────────
# Color nodes (Math / Color)
# ─────────────────────────────────────────────────────────────────────────────

def _parse_color(s: Any) -> tuple[float, float, float, float]:
    """Parse color from hex string #RRGGBB or #RRGGBBAA or (r,g,b,a). Returns (r,g,b,a) 0-1."""
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


class ColorAddNode(NodeBase):
    """Component-wise color add (clamped 0-1)."""
    NODE_NAME  = "Color Add"
    NODE_GROUP = "Math / Color"
    PINS = [
        PinDescriptor("a",      PinDirection.INPUT,  PinType.COLOR),
        PinDescriptor("b",      PinDirection.INPUT,  PinType.COLOR),
        PinDescriptor("result", PinDirection.OUTPUT, PinType.COLOR),
    ]
    MIN_WIDTH  = 150.0
    MIN_HEIGHT = 60.0

    def on_start(self) -> None:
        self._compute()

    def on_data_received(self, pin_name: str, value: Any) -> None:
        self._compute()

    def _compute(self) -> None:
        a = _parse_color(self.get_input("a"))
        b = _parse_color(self.get_input("b"))
        r = max(0, min(1, a[0] + b[0]))
        g = max(0, min(1, a[1] + b[1]))
        bl = max(0, min(1, a[2] + b[2]))
        al = max(0, min(1, a[3] + b[3]))
        self.set_output("result", (r, g, bl, al))

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        painter.setPen(QColor("#e57373"))
        painter.setFont(QFont("Courier New", 9))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "Color +")


class ColorBlendNode(NodeBase):
    """Linear blend between two colors: result = a + (b - a) * t, t in [0,1]."""
    NODE_NAME  = "Color Blend"
    NODE_GROUP = "Math / Color"
    PINS = [
        PinDescriptor("a",      PinDirection.INPUT,  PinType.COLOR),
        PinDescriptor("b",      PinDirection.INPUT,  PinType.COLOR),
        PinDescriptor("t",      PinDirection.INPUT,  PinType.FLOAT, default=0.5),
        PinDescriptor("result", PinDirection.OUTPUT, PinType.COLOR),
    ]
    MIN_WIDTH  = 150.0
    MIN_HEIGHT = 70.0

    def on_start(self) -> None:
        self._compute()

    def on_data_received(self, pin_name: str, value: Any) -> None:
        self._compute()

    def _compute(self) -> None:
        a = _parse_color(self.get_input("a"))
        b = _parse_color(self.get_input("b"))
        t = max(0, min(1, float(self.get_input("t") or 0.5)))
        r = a[0] + (b[0] - a[0]) * t
        g = a[1] + (b[1] - a[1]) * t
        bl = a[2] + (b[2] - a[2]) * t
        al = a[3] + (b[3] - a[3]) * t
        self.set_output("result", (r, g, bl, al))

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        painter.setPen(QColor("#e57373"))
        painter.setFont(QFont("Courier New", 8))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "lerp")


# ─────────────────────────────────────────────────────────────────────────────
# DateTime math (Math / DateTime) — values are epoch seconds (float)
# ─────────────────────────────────────────────────────────────────────────────

class DateTimeDifferenceNode(NodeBase):
    """Outputs a - b in seconds (float)."""
    NODE_NAME  = "DateTime Difference"
    NODE_GROUP = "Math / DateTime"
    PINS = [
        PinDescriptor("a",      PinDirection.INPUT,  PinType.DATETIME),
        PinDescriptor("b",      PinDirection.INPUT,  PinType.DATETIME),
        PinDescriptor("seconds", PinDirection.OUTPUT, PinType.FLOAT),
    ]
    MIN_WIDTH  = 180.0
    MIN_HEIGHT = 60.0

    def on_start(self) -> None:
        self._compute()

    def on_data_received(self, pin_name: str, value: Any) -> None:
        self._compute()

    def _compute(self) -> None:
        a = float(self.get_input("a") or 0.0)
        b = float(self.get_input("b") or 0.0)
        self.set_output("seconds", a - b)

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        painter.setPen(QColor("#ba68c8"))
        painter.setFont(QFont("Courier New", 8))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "a − b (s)")


class DateTimeAddSecondsNode(NodeBase):
    """Add seconds to a DateTime; outputs new DateTime (epoch seconds)."""
    NODE_NAME  = "DateTime Add Seconds"
    NODE_GROUP = "Math / DateTime"
    PINS = [
        PinDescriptor("datetime", PinDirection.INPUT,  PinType.DATETIME),
        PinDescriptor("seconds",  PinDirection.INPUT,  PinType.FLOAT, default=0.0),
        PinDescriptor("result",   PinDirection.OUTPUT, PinType.DATETIME),
    ]
    MIN_WIDTH  = 180.0
    MIN_HEIGHT = 60.0

    def on_start(self) -> None:
        self._compute()

    def on_data_received(self, pin_name: str, value: Any) -> None:
        self._compute()

    def _compute(self) -> None:
        t = float(self.get_input("datetime") or 0.0)
        s = float(self.get_input("seconds") or 0.0)
        self.set_output("result", t + s)

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        painter.setPen(QColor("#ba68c8"))
        painter.setFont(QFont("Courier New", 8))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "dt + s")