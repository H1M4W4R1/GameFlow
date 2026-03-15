"""
Utility nodes — Counter, Timer/Delay, Random, Log/Debug.
"""
from __future__ import annotations

import random
import time
import logging
from typing import Any

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui  import QPainter, QColor, QFont, QBrush
from PyQt6.QtCore import Qt

from core.node_base import NodeBase
from core.types     import PinDescriptor, PinDirection, PinType

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# COUNTER
# ─────────────────────────────────────────────────────────────────────────────

class CounterNode(NodeBase):
    """
    Integer counter with three tick inputs: count_up, count_down, reset.
    step / min_val / max_val are configurable via editable fields.
    The large number in the node body shows the live count.

    Bug-fix note: _count is initialised in __init__ so it always exists
    regardless of on_start() call order (prevents AttributeError when
    StartNode fires into CounterNode before CounterNode.on_start() runs).
    """
    NODE_NAME  = "Counter"
    NODE_GROUP = "Utility"
    PINS = [
        PinDescriptor("count_up",   PinDirection.INPUT,  PinType.TICK),
        PinDescriptor("count_down", PinDirection.INPUT,  PinType.TICK),
        PinDescriptor("reset",      PinDirection.INPUT,  PinType.TICK),
        # These pins are hidden when not wired; use VARIABLE_INPUTS editor to set defaults
        PinDescriptor("step",       PinDirection.INPUT,  PinType.INT, optional=True),
        PinDescriptor("min_val",    PinDirection.INPUT,  PinType.INT, optional=True),
        PinDescriptor("max_val",    PinDirection.INPUT,  PinType.INT, optional=True),
        PinDescriptor("count",      PinDirection.OUTPUT, PinType.INT),
        PinDescriptor("exec_out",   PinDirection.OUTPUT, PinType.TICK),
        PinDescriptor("on_min",     PinDirection.OUTPUT, PinType.TICK),
        PinDescriptor("on_max",     PinDirection.OUTPUT, PinType.TICK),
    ]
    # step/min/max: editable inline AND overridable by wiring an INT to the pin
    VARIABLE_INPUTS = {
        "step":    (int,   1),
        "min_val": (int,   0),
        "max_val": (int, 100),
    }
    MIN_WIDTH  = 200.0
    MIN_HEIGHT = 120.0

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._count: int = 0

    def on_start(self) -> None:
        self._count = int(self.get_var_input("min_val") or 0)
        self.set_output("count", self._count)

    def execute(self, trigger_pin: str) -> None:
        step:    int = int(self.get_var_input("step")    or 1)
        min_val: int = int(self.get_var_input("min_val") or 0)
        max_val: int = int(self.get_var_input("max_val") or 100)

        if trigger_pin == "count_up":
            self._count = min(self._count + step, max_val)
        elif trigger_pin == "count_down":
            self._count = max(self._count - step, min_val)
        elif trigger_pin == "reset":
            self._count = min_val

        self.set_output("count", self._count)
        self.fire_tick("exec_out")
        if self._count >= max_val:
            self.fire_tick("on_max")
        if self._count <= min_val:
            self.fire_tick("on_min")
        self.node_changed.emit()

    def get_state(self) -> dict[str, Any]:
        state = super().get_state()
        state["_count"] = self._count
        return state

    def set_state(self, state: dict[str, Any]) -> None:
        super().set_state(state)
        self._count = int(state.get("_count", 0))

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        painter.setPen(QColor("#f95979"))
        painter.setFont(QFont("Courier New", 22, QFont.Weight.Bold))
        # Draw count in the top portion; fields render below automatically
        count_rect = QRectF(rect.x(), rect.y(), rect.width(), 36)
        painter.drawText(count_rect, Qt.AlignmentFlag.AlignCenter, str(self._count))


# ─────────────────────────────────────────────────────────────────────────────
# TIMER / DELAY
# ─────────────────────────────────────────────────────────────────────────────

class TimerNode(NodeBase):
    """
    Starts a countdown when 'start' tick fires; fires exec_out after delay_ms.
    delay_ms is set via editable field (double-click); can also be overridden
    by connecting a FLOAT wire to delay_ms_in.
    Runtime calls on_tick_check() every 10 ms via graph_runtime.
    """
    NODE_NAME  = "Timer / Delay"
    NODE_GROUP = "Utility"
    PINS = [
        PinDescriptor("start",      PinDirection.INPUT,  PinType.TICK),
        PinDescriptor("stop",       PinDirection.INPUT,  PinType.TICK),
        PinDescriptor("delay_ms",   PinDirection.INPUT,  PinType.FLOAT, optional=True),
        PinDescriptor("exec_out",   PinDirection.OUTPUT, PinType.TICK),
        PinDescriptor("elapsed_ms", PinDirection.OUTPUT, PinType.FLOAT),
    ]
    # delay_ms: editable inline; override by wiring a FLOAT to the delay_ms pin.
    # loop: when True the timer automatically restarts after firing exec_out.
    VARIABLE_INPUTS = {
        "delay_ms": (float, 1000.0),
    }
    EDITABLE_FIELDS = {
        "loop": (bool, False),
    }
    MIN_WIDTH  = 200.0
    MIN_HEIGHT = 100.0

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._active:     bool  = False
        self._start_time: float = 0.0

    def on_start(self) -> None:
        self._active     = False
        self._start_time = 0.0

    def execute(self, trigger_pin: str) -> None:
        if trigger_pin == "start":
            self._active     = True
            self._start_time = time.monotonic()
        elif trigger_pin == "stop":
            self._active = False

    def on_tick_check(self) -> None:
        """Called by the runtime tick loop every 10 ms."""
        if not self._active:
            return
        delay_ms = float(self.get_var_input("delay_ms") or 1000.0)
        elapsed  = (time.monotonic() - self._start_time) * 1000.0
        self.set_output("elapsed_ms", elapsed)
        if elapsed >= delay_ms:
            self.fire_tick("exec_out")
            loop = bool(self.get_field("loop"))
            if loop:
                # Restart immediately — keep _active True, reset start time
                self._start_time = time.monotonic()
            else:
                self._active = False
            self.node_changed.emit()

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        if not self._active:
            return
        delay_ms = float(self.get_var_input("delay_ms") or 1000.0)
        elapsed   = (time.monotonic() - self._start_time) * 1000.0
        pct       = min(1.0, elapsed / max(1.0, delay_ms))
        bar_w     = (rect.width() - 8) * pct
        bar_rect  = QRectF(rect.x() + 4, rect.y() + 4, bar_w, 8)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor("#f95979")))
        painter.drawRoundedRect(bar_rect, 3, 3)
        painter.setPen(QColor("#c8889a"))
        painter.setFont(QFont("Courier New", 8))
        painter.drawText(
            QRectF(rect.x(), rect.y() + 14, rect.width(), 18),
            Qt.AlignmentFlag.AlignCenter,
            f"{elapsed:.0f} / {delay_ms:.0f} ms",
        )


# ─────────────────────────────────────────────────────────────────────────────
# RANDOM VALUE
# ─────────────────────────────────────────────────────────────────────────────

class RandomNode(NodeBase):
    """
    Generates a uniform random float in [min_val, max_val] on each exec tick.
    Range limits set via editable fields.
    """
    NODE_NAME  = "Random"
    NODE_GROUP = "Utility"
    PINS = [
        PinDescriptor("exec_in",  PinDirection.INPUT,  PinType.TICK),
        PinDescriptor("value",    PinDirection.OUTPUT, PinType.FLOAT),
        PinDescriptor("exec_out", PinDirection.OUTPUT, PinType.TICK),
    ]
    VARIABLE_INPUTS = {
        "min_val": (float, 0.0),
        "max_val": (float, 1.0),
    }
    MIN_WIDTH  = 160.0
    MIN_HEIGHT = 90.0

    def execute(self, trigger_pin: str) -> None:
        lo = float(self.get_var_input("min_val") or 0.0)
        hi = float(self.get_var_input("max_val") or 1.0)
        self.set_output("value", random.uniform(lo, hi))
        self.fire_tick("exec_out")


# ─────────────────────────────────────────────────────────────────────────────
# LOG / DEBUG
# ─────────────────────────────────────────────────────────────────────────────

class LogNode(NodeBase):
    """
    Logs a labelled value when triggered; shows the last logged message
    inside the node body.  Label is set via editable field.
    """
    NODE_NAME  = "Log / Debug"
    NODE_GROUP = "Utility"
    PINS = [
        PinDescriptor("exec_in",  PinDirection.INPUT,  PinType.TICK),
        PinDescriptor("value",    PinDirection.INPUT,  PinType.ANY,  default=""),
        PinDescriptor("exec_out", PinDirection.OUTPUT, PinType.TICK),
    ]
    EDITABLE_FIELDS = {
        "label": (str, "LOG"),
    }
    MIN_WIDTH  = 200.0
    MIN_HEIGHT = 90.0

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._last_msg: str = ""

    def execute(self, trigger_pin: str) -> None:
        label = str(self.get_field("label") or "LOG")
        value = self.get_input("value")
        msg   = f"[{label}] {value}"
        log.info(msg)
        self.log_message.emit(msg)
        self._last_msg = msg
        self.fire_tick("exec_out")
        self.node_changed.emit()

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        painter.setPen(QColor("#aed581"))
        painter.setFont(QFont("Courier New", 8))
        txt = self._last_msg
        if len(txt) > 28:
            txt = txt[:25] + "…"
        painter.drawText(
            QRectF(rect.x(), rect.y(), rect.width(), 20),
            Qt.AlignmentFlag.AlignCenter,
            txt,
        )


# ─────────────────────────────────────────────────────────────────────────────
# LOOP NODE
# ─────────────────────────────────────────────────────────────────────────────

class LoopNode(NodeBase):
    """
    Gates exec_out based on a loop condition.

    When enabled (loop == True):  every tick on exec_in fires exec_out AND
                                  loops back, creating a self-sustaining cycle.
    When disabled:                exec_in fires exec_out once, then stops.

    The 'loop' pin can be connected from a Bool source OR set via the
    inline VARIABLE_INPUTS field (double-click when not wired).

    Typical use:  Timer exec_out → LoopNode exec_in → downstream action
                                                     ↑ loop back auto-fires

    Safety: a loop counter prevents infinite tight loops within a single
    tick by capping at max_iterations (default 1 — loops per-tick only).
    """
    NODE_NAME  = "Loop"
    NODE_GROUP = "Flow"
    PINS = [
        PinDescriptor("exec_in",  PinDirection.INPUT,  PinType.TICK),
        PinDescriptor("loop",     PinDirection.INPUT,  PinType.BOOL, optional=True),
        PinDescriptor("exec_out", PinDirection.OUTPUT, PinType.TICK),
        PinDescriptor("on_done",  PinDirection.OUTPUT, PinType.TICK),
    ]
    VARIABLE_INPUTS = {
        "loop": (bool, True),
    }
    EDITABLE_FIELDS = {
        "max_iterations": (int, 1),
    }
    MIN_WIDTH  = 180.0
    MIN_HEIGHT = 90.0

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._iteration: int = 0

    def execute(self, trigger_pin: str) -> None:
        loop      = bool(self.get_var_input("loop"))
        max_iter  = int(self.get_field("max_iterations") or 1)
        self._iteration = 0

        if not loop:
            self.fire_tick("exec_out")
            self.fire_tick("on_done")
            return

        while self._iteration < max_iter:
            self._iteration += 1
            self.fire_tick("exec_out")

        self.fire_tick("on_done")
        self.node_changed.emit()

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        loop    = bool(self.get_var_input("loop"))
        max_i   = int(self.get_field("max_iterations") or 1)
        color   = QColor("#f95979") if loop else QColor("#616161")
        label   = f"↻  ×{max_i}" if loop else "→  ×1"
        painter.setPen(color)
        painter.setFont(QFont("Courier New", 12, QFont.Weight.Bold))
        painter.drawText(
            QRectF(rect.x(), rect.y(), rect.width(), 30),
            Qt.AlignmentFlag.AlignCenter,
            label,
        )
