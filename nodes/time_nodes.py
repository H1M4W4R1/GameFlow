"""
Time nodes — time sources, Delay, Timer, and delta time.

All time values use seconds (float) unless named _ms.
DateTime pin type carries epoch seconds (float) for compatibility with math.
"""
from __future__ import annotations

import time
from typing import Any

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui  import QPainter, QColor, QFont, QBrush

from core.node_base import NodeBase
from core.types     import PinDescriptor, PinDirection, PinType


# ─────────────────────────────────────────────────────────────────────────────
# Time Since Start
# ─────────────────────────────────────────────────────────────────────────────

class TimeSinceStartNode(NodeBase):
    """Outputs seconds (float) since the graph started. Updates every tick check."""
    NODE_NAME  = "Time Since Start"
    NODE_GROUP = "Time"
    PINS = [
        PinDescriptor("seconds", PinDirection.OUTPUT, PinType.FLOAT),
    ]
    MIN_WIDTH  = 160.0
    MIN_HEIGHT = 60.0

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._start: float = 0.0

    def on_start(self) -> None:
        self._start = time.monotonic()
        self.set_output("seconds", 0.0)

    def on_tick_check(self) -> None:
        self.set_output("seconds", time.monotonic() - self._start)


# ─────────────────────────────────────────────────────────────────────────────
# Epoch Milliseconds
# ─────────────────────────────────────────────────────────────────────────────

class EpochMillisecondsNode(NodeBase):
    """Outputs current time as milliseconds since Unix epoch. Updates every tick check."""
    NODE_NAME  = "Epoch Milliseconds"
    NODE_GROUP = "Time"
    PINS = [
        PinDescriptor("ms", PinDirection.OUTPUT, PinType.FLOAT),
    ]
    MIN_WIDTH  = 180.0
    MIN_HEIGHT = 60.0

    def on_start(self) -> None:
        self._update()

    def on_tick_check(self) -> None:
        self._update()

    def _update(self) -> None:
        self.set_output("ms", time.time() * 1000.0)


# ─────────────────────────────────────────────────────────────────────────────
# Current DateTime (epoch seconds)
# ─────────────────────────────────────────────────────────────────────────────

class CurrentDateTimeNode(NodeBase):
    """Outputs current time as DATETIME (epoch seconds, float). Updates every tick check."""
    NODE_NAME  = "Current DateTime"
    NODE_GROUP = "Time"
    PINS = [
        PinDescriptor("datetime", PinDirection.OUTPUT, PinType.DATETIME),
    ]
    MIN_WIDTH  = 160.0
    MIN_HEIGHT = 60.0

    def on_start(self) -> None:
        self.set_output("datetime", time.time())

    def on_tick_check(self) -> None:
        self.set_output("datetime", time.time())


# ─────────────────────────────────────────────────────────────────────────────
# Specified DateTime (epoch seconds from editable or input)
# ─────────────────────────────────────────────────────────────────────────────

class SpecifiedDateTimeNode(NodeBase):
    """
    Outputs a fixed or wired DateTime (epoch seconds).
    Editable field: epoch seconds (float). Or connect a float to override.
    """
    NODE_NAME  = "Specified DateTime"
    NODE_GROUP = "Time"
    PINS = [
        PinDescriptor("epoch_seconds", PinDirection.INPUT, PinType.FLOAT, optional=True),
        PinDescriptor("datetime",     PinDirection.OUTPUT, PinType.DATETIME),
    ]
    EDITABLE_FIELDS = {
        "epoch_seconds": (float, 0.0),
    }
    MIN_WIDTH  = 180.0
    MIN_HEIGHT = 70.0

    def on_start(self) -> None:
        self._compute()

    def on_data_received(self, pin_name: str, value: Any) -> None:
        self._compute()

    def _compute(self) -> None:
        v = self.get_input("epoch_seconds")
        if v is not None:
            sec = float(v)
        else:
            sec = float(self.get_field("epoch_seconds") or 0.0)
        self.set_output("datetime", sec)

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        painter.setPen(QColor("#ba68c8"))
        painter.setFont(QFont("Courier New", 8))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "epoch s")


# ─────────────────────────────────────────────────────────────────────────────
# Delay (one-shot: start → wait delay_ms → exec_out once)
# ─────────────────────────────────────────────────────────────────────────────

class DelayNode(NodeBase):
    """
    When 'start' tick fires, waits delay_ms then fires exec_out once.
    'stop' cancels the delay. Does not repeat.
    """
    NODE_NAME  = "Delay"
    NODE_GROUP = "Time"
    PINS = [
        PinDescriptor("start",      PinDirection.INPUT,  PinType.TICK),
        PinDescriptor("stop",       PinDirection.INPUT,  PinType.TICK),
        PinDescriptor("delay_ms",   PinDirection.INPUT,  PinType.FLOAT, optional=True),
        PinDescriptor("exec_out",   PinDirection.OUTPUT, PinType.TICK),
        PinDescriptor("elapsed_ms", PinDirection.OUTPUT, PinType.FLOAT),
    ]
    VARIABLE_INPUTS = {
        "delay_ms": (float, 1000.0),
    }
    MIN_WIDTH  = 180.0
    MIN_HEIGHT = 100.0

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._active:      bool          = False
        self._start_time:  float         = 0.0
        self._pause_start: float | None  = None

    def on_start(self) -> None:
        self._active      = False
        self._start_time  = 0.0
        self._pause_start = None

    def on_pause(self) -> None:
        if self._active:
            self._pause_start = time.monotonic()

    def on_resume(self) -> None:
        if self._active and self._pause_start is not None:
            self._start_time += time.monotonic() - self._pause_start
        self._pause_start = None

    def execute(self, trigger_pin: str) -> None:
        if trigger_pin == "start":
            self._active     = True
            self._start_time = time.monotonic()
        elif trigger_pin == "stop":
            self._active = False

    def on_tick_check(self) -> None:
        if not self._active:
            return
        delay_ms = float(self.get_var_input("delay_ms") or 1000.0)
        elapsed  = (time.monotonic() - self._start_time) * 1000.0
        self.set_output("elapsed_ms", elapsed)
        if elapsed >= delay_ms:
            self.fire_tick("exec_out")
            self._active = False
            self.node_changed.emit()

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        if not self._active:
            return
        delay_ms = float(self.get_var_input("delay_ms") or 1000.0)
        elapsed  = (time.monotonic() - self._start_time) * 1000.0
        pct      = min(1.0, elapsed / max(1.0, delay_ms))
        bar_w    = (rect.width() - 8) * pct
        bar_rect = QRectF(rect.x() + 4, rect.y() + 4, bar_w, 8)
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
# Timer (repeating: fires exec_out every interval_ms)
# ─────────────────────────────────────────────────────────────────────────────

class TimerNode(NodeBase):
    """
    When 'start' tick fires, begins firing exec_out every interval_ms.
    'stop' tick stops the timer. Repeating.
    """
    NODE_NAME  = "Timer"
    NODE_GROUP = "Time"
    PINS = [
        PinDescriptor("start",        PinDirection.INPUT,  PinType.TICK),
        PinDescriptor("stop",         PinDirection.INPUT,  PinType.TICK),
        PinDescriptor("interval_ms", PinDirection.INPUT,  PinType.FLOAT, optional=True),
        PinDescriptor("exec_out",    PinDirection.OUTPUT, PinType.TICK),
    ]
    VARIABLE_INPUTS = {
        "interval_ms": (float, 1000.0),
    }
    MIN_WIDTH  = 180.0
    MIN_HEIGHT = 90.0

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._active:      bool         = False
        self._next_fire:   float        = 0.0
        self._pause_start: float | None = None

    def on_start(self) -> None:
        self._active      = False
        self._next_fire   = 0.0
        self._pause_start = None

    def on_pause(self) -> None:
        if self._active:
            self._pause_start = time.monotonic()

    def on_resume(self) -> None:
        if self._active and self._pause_start is not None:
            self._next_fire += time.monotonic() - self._pause_start
        self._pause_start = None

    def execute(self, trigger_pin: str) -> None:
        if trigger_pin == "start":
            self._active    = True
            interval_s      = max(0.01, float(self.get_var_input("interval_ms") or 1000.0) / 1000.0)
            self._next_fire = time.monotonic() + interval_s
        elif trigger_pin == "stop":
            self._active = False

    def on_tick_check(self) -> None:
        if not self._active:
            return
        now = time.monotonic()
        if now >= self._next_fire:
            interval_ms = float(self.get_var_input("interval_ms") or 1000.0)
            interval_s  = max(0.01, interval_ms / 1000.0)
            self._next_fire = now + interval_s
            self.fire_tick("exec_out")
            self.node_changed.emit()

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        interval_ms = float(self.get_var_input("interval_ms") or 1000.0)
        interval_s  = max(0.01, interval_ms / 1000.0)
        if self._active:
            now       = time.monotonic()
            interval_start = self._next_fire - interval_s
            elapsed   = now - interval_start
            pct       = min(1.0, max(0.0, elapsed / interval_s))
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
                f"{elapsed * 1000:.0f} / {interval_ms:.0f} ms",
            )
        else:
            painter.setPen(QColor("#f95979"))
            painter.setFont(QFont("Courier New", 8))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, f"every {interval_ms:.0f} ms")


# ─────────────────────────────────────────────────────────────────────────────
# Delta Time (time since last exec_in; first time = time since start)
# ─────────────────────────────────────────────────────────────────────────────

class DeltaTimeNode(NodeBase):
    """
    On each exec_in tick, outputs the time (seconds) since the previous exec_in.
    On the first exec_in, outputs time since graph start.
    """
    NODE_NAME  = "Delta Time"
    NODE_GROUP = "Time"
    PINS = [
        PinDescriptor("exec_in",   PinDirection.INPUT,  PinType.TICK),
        PinDescriptor("delta_s",  PinDirection.OUTPUT, PinType.FLOAT),
        PinDescriptor("exec_out", PinDirection.OUTPUT, PinType.TICK),
    ]
    MIN_WIDTH  = 160.0
    MIN_HEIGHT = 70.0

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._last_time: float | None = None  # None = first tick, output time since start
        self._start_time: float = 0.0

    def on_start(self) -> None:
        self._start_time = time.monotonic()
        self._last_time  = None

    def execute(self, trigger_pin: str) -> None:
        now = time.monotonic()
        if self._last_time is None:
            delta = now - self._start_time
        else:
            delta = now - self._last_time
        self._last_time = now
        self.set_output("delta_s", delta)
        self.fire_tick("exec_out")
        self.node_changed.emit()

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        painter.setPen(QColor("#ba68c8"))
        painter.setFont(QFont("Courier New", 8))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "Δt")
