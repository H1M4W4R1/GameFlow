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
        self._last_fire:   float        = 0.0
        self._pause_start: float | None = None

    def on_start(self) -> None:
        self._last_fire   = time.monotonic()
        self._pause_start = None

    def on_pause(self) -> None:
        self._pause_start = time.monotonic()

    def on_resume(self) -> None:
        if self._pause_start is not None:
            self._last_fire += time.monotonic() - self._pause_start
        self._pause_start = None

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
# EVENT NODES  (fired by the runtime on lifecycle transitions)
# ─────────────────────────────────────────────────────────────────────────────

class StartNode(NodeBase):
    """Fires exec_out exactly once when the graph starts."""
    NODE_NAME  = "On Started"
    NODE_GROUP = "Flow"
    PINS = [
        PinDescriptor("exec_out", PinDirection.OUTPUT, PinType.TICK),
    ]
    MIN_WIDTH  = 140.0
    MIN_HEIGHT = 60.0

    def on_start(self) -> None:
        # Do not fire here — runtime fires exec_out after all nodes' on_start()
        # so downstream nodes (Timer, Delay, etc.) are already initialized.
        pass

    def execute(self, trigger_pin: str) -> None:
        pass


class OnPausedNode(NodeBase):
    """Fires exec_out once when the graph is paused."""
    NODE_NAME  = "On Paused"
    NODE_GROUP = "Flow"
    PINS = [
        PinDescriptor("exec_out", PinDirection.OUTPUT, PinType.TICK),
    ]
    MIN_WIDTH  = 140.0
    MIN_HEIGHT = 60.0

    def execute(self, trigger_pin: str) -> None:
        pass


class OnResumedNode(NodeBase):
    """Fires exec_out once when the graph is resumed from pause."""
    NODE_NAME  = "On Resumed"
    NODE_GROUP = "Flow"
    PINS = [
        PinDescriptor("exec_out", PinDirection.OUTPUT, PinType.TICK),
    ]
    MIN_WIDTH  = 140.0
    MIN_HEIGHT = 60.0

    def execute(self, trigger_pin: str) -> None:
        pass


class OnStoppedNode(NodeBase):
    """Fires exec_out once when the graph is stopped."""
    NODE_NAME  = "On Stopped"
    NODE_GROUP = "Flow"
    PINS = [
        PinDescriptor("exec_out", PinDirection.OUTPUT, PinType.TICK),
    ]
    MIN_WIDTH  = 140.0
    MIN_HEIGHT = 60.0

    def execute(self, trigger_pin: str) -> None:
        pass


class IsRunningNode(NodeBase):
    """
    Pure data node — outputs True while the graph is running and not paused,
    False when stopped or paused.  Updated by the runtime before event nodes
    fire so downstream nodes always see the correct state.
    """
    NODE_NAME  = "Is Running"
    NODE_GROUP = "Flow"
    PINS = [
        PinDescriptor("is_running", PinDirection.OUTPUT, PinType.BOOL),
    ]
    MIN_WIDTH  = 140.0
    MIN_HEIGHT = 60.0

    def on_output_wire_connected(self, pin_name: str) -> None:
        # Push current value immediately when a wire is connected.
        self.set_output("is_running", self._data.get("is_running", False))

    def execute(self, trigger_pin: str) -> None:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Comparison nodes — pure data nodes, output a bool result pin only.
# Wire their "result" into a Router node to branch execution.
# ─────────────────────────────────────────────────────────────────────────────

class _CompareNodeBase(NodeBase):
    """
    Pure data node: compares a OP b and pushes a bool on the *result* pin.
    No exec_in / exec_out — connect *result* to a RouterNode to branch.
    """
    NODE_GROUP = "Logic"
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
    NODE_GROUP = "Logic"
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


# ─────────────────────────────────────────────────────────────────────────────
# Router  (routes exec_in to on_true or on_false based on a bool condition)
# ─────────────────────────────────────────────────────────────────────────────

class RouterNode(NodeBase):
    """
    Exec router — reads a bool *condition* pin and forwards the incoming tick
    to either *on_true* or *on_false*.

    Typical wiring:
        [Tick] ──exec──▶ [Router]
        [Equal] ─result─▶ [Router.condition]
        [Router.on_true]  ──▶ ...
        [Router.on_false] ──▶ ...
    """
    NODE_NAME  = "Router"
    NODE_GROUP = "Flow"
    PINS = [
        PinDescriptor("exec_in",   PinDirection.INPUT,  PinType.TICK),
        PinDescriptor("condition", PinDirection.INPUT,  PinType.BOOL, default=False),
        PinDescriptor("on_true",   PinDirection.OUTPUT, PinType.TICK),
        PinDescriptor("on_false",  PinDirection.OUTPUT, PinType.TICK),
    ]
    MIN_WIDTH  = 160.0
    MIN_HEIGHT = 80.0

    def execute(self, trigger_pin: str) -> None:
        cond = bool(self.get_input("condition"))
        self.fire_tick("on_true" if cond else "on_false")

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        painter.setPen(QColor("#80cbc4"))
        painter.setFont(QFont("Courier New", 9))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "T ◀ ▶ F")
