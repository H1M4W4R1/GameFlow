"""
Flow control nodes — tick clocks, graph start, and conditional branching.
"""
from __future__ import annotations

import time
from typing import Any

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui  import QPainter, QColor, QFont

from core.node_base import NodeBase
from core.types     import PinDescriptor, PinDirection, PinType


# ─────────────────────────────────────────────────────────────────────────────
# TICK  (10 ms, driven by runtime loop)
# ─────────────────────────────────────────────────────────────────────────────

class TickNode(NodeBase):
    """Fires every 10 ms — the heartbeat of the graph."""
    NODE_NAME  = "Tick"
    NODE_GROUP = "Flow"
    PINS = [
        PinDescriptor("tick", PinDirection.OUTPUT, PinType.TICK),
    ]
    MIN_WIDTH  = 140.0
    MIN_HEIGHT = 60.0

    def execute(self, trigger_pin: str) -> None:
        self.fire_tick("tick")

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        painter.setPen(QColor("#f95979"))
        painter.setFont(QFont("Courier New", 8))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "10 ms")


# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURABLE TICK
# ─────────────────────────────────────────────────────────────────────────────

class ConfigurableTickNode(NodeBase):
    """
    Fires a tick at a configurable interval.
    Set the interval by double-clicking the field inside the node.
    The runtime calls execute() every 10 ms; this node gates to the interval.
    """
    NODE_NAME  = "Tick (Custom)"
    NODE_GROUP = "Flow"
    PINS = [
        PinDescriptor("tick", PinDirection.OUTPUT, PinType.TICK),
    ]
    EDITABLE_FIELDS = {
        "interval_ms": (float, 100.0),
    }
    MIN_WIDTH  = 160.0
    MIN_HEIGHT = 80.0

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._last_fire: float = 0.0

    def on_start(self) -> None:
        self._last_fire = time.monotonic()

    def execute(self, trigger_pin: str) -> None:
        interval_ms = float(self.get_field("interval_ms") or 100.0)
        interval_s  = max(0.01, interval_ms / 1000.0)
        now = time.monotonic()
        if now - self._last_fire >= interval_s:
            self._last_fire = now
            self.fire_tick("tick")

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        ms = float(self.get_field("interval_ms") or 100.0)
        painter.setPen(QColor("#f95979"))
        painter.setFont(QFont("Courier New", 9))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, f"{ms:.0f} ms")


# ─────────────────────────────────────────────────────────────────────────────
# START
# ─────────────────────────────────────────────────────────────────────────────

class StartNode(NodeBase):
    """Fires exec_out exactly once when the graph starts."""
    NODE_NAME  = "Start"
    NODE_GROUP = "Flow"
    PINS = [
        PinDescriptor("exec_out", PinDirection.OUTPUT, PinType.TICK),
    ]
    MIN_WIDTH  = 140.0
    MIN_HEIGHT = 60.0

    def on_start(self) -> None:
        self.fire_tick("exec_out")

    def execute(self, trigger_pin: str) -> None:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# CONDITION / IF
# ─────────────────────────────────────────────────────────────────────────────

class ConditionNode(NodeBase):
    """
    Evaluates  a OP b  and routes the incoming tick to on_true or on_false.
    Set the operator via the editable field (double-click).
    Supported operators: ==  !=  >  >=  <  <=
    """
    NODE_NAME  = "Condition / If"
    NODE_GROUP = "Flow"
    PINS = [
        PinDescriptor("exec_in",  PinDirection.INPUT,  PinType.TICK),
        PinDescriptor("a",        PinDirection.INPUT,  PinType.FLOAT, default=0.0),
        PinDescriptor("b",        PinDirection.INPUT,  PinType.FLOAT, default=0.0),
        PinDescriptor("on_true",  PinDirection.OUTPUT, PinType.TICK),
        PinDescriptor("on_false", PinDirection.OUTPUT, PinType.TICK),
        PinDescriptor("result",   PinDirection.OUTPUT, PinType.BOOL),
    ]
    EDITABLE_FIELDS = {
        "op": (str, "=="),
    }
    MIN_WIDTH = 180.0

    def execute(self, trigger_pin: str) -> None:
        a  = float(self.get_input("a") or 0.0)
        b  = float(self.get_input("b") or 0.0)
        op = str(self.get_field("op") or "==").strip()
        result = _compare(op, a, b)
        self.set_output("result", result)
        self.fire_tick("on_true" if result else "on_false")

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        op = str(self.get_field("op") or "==")
        a  = self.get_input("a")
        b  = self.get_input("b")
        painter.setPen(QColor("#90a4ae"))
        painter.setFont(QFont("Courier New", 9))
        painter.drawText(
            QRectF(rect.x(), rect.y(), rect.width(), 24),
            Qt.AlignmentFlag.AlignCenter,
            f"{a} {op} {b}",
        )


def _compare(op: str, a: float, b: float) -> bool:
    return {
        "==": a == b,
        "!=": a != b,
        ">":  a >  b,
        ">=": a >= b,
        "<":  a <  b,
        "<=": a <= b,
    }.get(op, False)
