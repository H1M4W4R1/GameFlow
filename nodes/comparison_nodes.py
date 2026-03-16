# ─────────────────────────────────────────────────────────────────────────────
# Comparison nodes — pure data nodes, output a bool result pin only.
# Wire their "result" into a Router node to branch execution.
# ─────────────────────────────────────────────────────────────────────────────
from typing import Any

from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QFont, QColor, QPainter

from core.node_base import NodeBase
from core.types import PinType, PinDirection, PinDescriptor


class _CompareNodeBase(NodeBase):
    """
    Pure data node: compares a OP b and pushes a bool on the *result* pin.
    No exec_in / exec_out — connect *result* to a RouterNode to branch.
    """
    NODE_GROUP = "Logic/Comparison"
    PINS = [
        PinDescriptor("a",      PinDirection.INPUT,  PinType.ANY),
        PinDescriptor("b",      PinDirection.INPUT,  PinType.ANY),
        PinDescriptor("result", PinDirection.OUTPUT, PinType.BOOL),
    ]
    MIN_WIDTH = 160.0

    def on_start(self) -> None:
        self._compute()

    def on_data_received(self, pin_name: str, value: Any) -> None:
        self._compute()

    def _compute(self) -> None:
        a = self.get_input("a")
        b = self.get_input("b")
        self.set_output("result", self._compare(a, b))

    def execute(self, trigger_pin: str) -> None:
        pass  # pure data node — never ticked

    def _compare(self, a: Any, b: Any) -> bool:
        raise NotImplementedError

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        painter.setPen(QColor("#90a4ae"))
        painter.setFont(QFont("Courier New", 10))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self.NODE_NAME)


class EqualNode(_CompareNodeBase):
    """a == b (Any types)."""
    NODE_NAME = "Equal"

    def _compare(self, a: Any, b: Any) -> bool:
        return a == b


class NotEqualNode(_CompareNodeBase):
    """a != b (Any types)."""
    NODE_NAME = "Not Equal"

    def _compare(self, a: Any, b: Any) -> bool:
        return a != b


class GreaterNode(_CompareNodeBase):
    """a > b (Any comparable types)."""
    NODE_NAME = "Greater"

    def _compare(self, a: Any, b: Any) -> bool:
        try:
            return a > b
        except TypeError:
            return False


class GreaterEqualNode(_CompareNodeBase):
    """a >= b (Any comparable types)."""
    NODE_NAME = "Greater or Equal"

    def _compare(self, a: Any, b: Any) -> bool:
        try:
            return a >= b
        except TypeError:
            return False


class LessNode(_CompareNodeBase):
    """a < b (Any comparable types)."""
    NODE_NAME = "Less"

    def _compare(self, a: Any, b: Any) -> bool:
        try:
            return a < b
        except TypeError:
            return False


class LessEqualNode(_CompareNodeBase):
    """a <= b (Any comparable types)."""
    NODE_NAME = "Less or Equal"

    def _compare(self, a: Any, b: Any) -> bool:
        try:
            return a <= b
        except TypeError:
            return False


# ─────────────────────────────────────────────────────────────────────────────
# Select  (ternary: condition ? a : b)
# ─────────────────────────────────────────────────────────────────────────────

class SelectNode(NodeBase):
    """
    Ternary select — outputs a when condition is True, b when False.
    Equivalent to C#  condition ? a : b
    Pure data node — reacts instantly on any input change.
    """
    NODE_NAME  = "Select"
    NODE_GROUP = "Logic/Comparison"
    PINS = [
        PinDescriptor("condition", PinDirection.INPUT,  PinType.BOOL, default=False),
        PinDescriptor("a",         PinDirection.INPUT,  PinType.ANY),
        PinDescriptor("b",         PinDirection.INPUT,  PinType.ANY),
        PinDescriptor("result",    PinDirection.OUTPUT, PinType.ANY),
    ]
    MIN_WIDTH  = 160.0
    MIN_HEIGHT = 80.0

    def on_start(self) -> None:
        self._compute()

    def on_data_received(self, pin_name: str, value: Any) -> None:
        self._compute()

    def _compute(self) -> None:
        cond = bool(self.get_input("condition"))
        self.set_output("result", self.get_input("a") if cond else self.get_input("b"))

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        painter.setPen(QColor("#ffb74d"))
        painter.setFont(QFont("Courier New", 9))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "? a : b")