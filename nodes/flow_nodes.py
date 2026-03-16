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
    NODE_NAME  = "On Tick"
    NODE_GROUP = "Flow/Events"
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
    NODE_NAME  = "On Tick (Custom)"
    NODE_GROUP = "Flow/Events"
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
    NODE_NAME  = "On Start"
    NODE_GROUP = "Flow/Events"
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
    NODE_NAME  = "On Pause"
    NODE_GROUP = "Flow/Events"
    PINS = [
        PinDescriptor("exec_out", PinDirection.OUTPUT, PinType.TICK),
    ]
    MIN_WIDTH  = 140.0
    MIN_HEIGHT = 60.0

    def execute(self, trigger_pin: str) -> None:
        pass


class OnResumedNode(NodeBase):
    """Fires exec_out once when the graph is resumed from pause."""
    NODE_NAME  = "On Resume"
    NODE_GROUP = "Flow/Events"
    PINS = [
        PinDescriptor("exec_out", PinDirection.OUTPUT, PinType.TICK),
    ]
    MIN_WIDTH  = 140.0
    MIN_HEIGHT = 60.0

    def execute(self, trigger_pin: str) -> None:
        pass


class OnStoppedNode(NodeBase):
    """Fires exec_out once when the graph is stopped."""
    NODE_NAME  = "On Stop"
    NODE_GROUP = "Flow/Events"
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
    NODE_GROUP = "Flow/Status"
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
    NODE_GROUP = "Flow/Redirect"
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


# ─────────────────────────────────────────────────────────────────────────────
# LOOP NODE (always loops exact count)
# ─────────────────────────────────────────────────────────────────────────────

class LoopNode(NodeBase):
    """
    Fires exec_out exactly N times (N = count), then fires on_done.
    count is set via editable field or wired INT input.
    """
    NODE_NAME  = "Loop"
    NODE_GROUP = "Flow/Redirect"
    PINS = [
        PinDescriptor("exec_in",  PinDirection.INPUT,  PinType.TICK),
        PinDescriptor("count",    PinDirection.INPUT,  PinType.INT, optional=True),
        PinDescriptor("exec_out", PinDirection.OUTPUT, PinType.TICK),
        PinDescriptor("on_done",  PinDirection.OUTPUT, PinType.TICK),
    ]
    VARIABLE_INPUTS = {
        "count": (int, 1),
    }
    MIN_WIDTH  = 180.0
    MIN_HEIGHT = 90.0

    def execute(self, trigger_pin: str) -> None:
        n = max(0, int(self.get_var_input("count") or 1))
        for _ in range(n):
            self.fire_tick("exec_out")
        self.fire_tick("on_done")
        self.node_changed.emit()

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        n = max(0, int(self.get_var_input("count") or 1))
        painter.setPen(QColor("#f95979"))
        painter.setFont(QFont("Courier New", 12, QFont.Weight.Bold))
        painter.drawText(
            QRectF(rect.x(), rect.y(), rect.width(), 30),
            Qt.AlignmentFlag.AlignCenter,
            f"↻  ×{n}",
        )


# ─────────────────────────────────────────────────────────────────────────────
# LOOP WHILE (branch on condition: if condition → exec_out, else → on_done)
# ─────────────────────────────────────────────────────────────────────────────

class LoopWhileNode(NodeBase):
    """
    When exec_in fires: if condition is True, fire exec_out; else fire on_done.
    Use for while-style branching (e.g. condition from downstream).
    """
    NODE_NAME  = "Loop While"
    NODE_GROUP = "Flow/Redirect"
    PINS = [
        PinDescriptor("exec_in",   PinDirection.INPUT,  PinType.TICK),
        PinDescriptor("condition", PinDirection.INPUT,  PinType.BOOL),
        PinDescriptor("exec_out", PinDirection.OUTPUT, PinType.TICK),
        PinDescriptor("on_done",   PinDirection.OUTPUT, PinType.TICK),
    ]
    MIN_WIDTH  = 160.0
    MIN_HEIGHT = 90.0

    def execute(self, trigger_pin: str) -> None:
        cond = bool(self.get_input("condition"))
        if cond:
            self.fire_tick("exec_out")
        else:
            self.fire_tick("on_done")
        self.node_changed.emit()

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        cond = bool(self.get_input("condition"))
        painter.setPen(QColor("#f95979") if cond else QColor("#616161"))
        painter.setFont(QFont("Courier New", 10))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "while?")
