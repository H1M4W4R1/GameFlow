"""
Time nodes — time sources, Delay, Timer, and delta time.

All time values use seconds (float).
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
    NODE_GROUP = "Time/Acquire"
    PINS = [
        PinDescriptor("seconds", PinDirection.OUTPUT, PinType.FLOAT),
    ]
    MIN_WIDTH  = 160.0
    MIN_HEIGHT = 60.0

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._start:       float        = 0.0
        self._pause_start: float | None = None

    def on_start(self) -> None:
        self._start       = time.monotonic()
        self._pause_start = None
        self.set_output("seconds", 0.0)

    def on_pause(self) -> None:
        self._pause_start = time.monotonic()

    def on_resume(self) -> None:
        if self._pause_start is not None:
            self._start += time.monotonic() - self._pause_start
        self._pause_start = None

    def on_tick_check(self) -> None:
        self.set_output("seconds", time.monotonic() - self._start)


# ─────────────────────────────────────────────────────────────────────────────
# Epoch Seconds
# ─────────────────────────────────────────────────────────────────────────────

class EpochSecondsNode(NodeBase):
    """Outputs current time as seconds since Unix epoch. Updates every tick check."""
    NODE_NAME  = "Epoch Seconds"
    NODE_GROUP = "Time/Acquire"
    PINS = [
        PinDescriptor("seconds", PinDirection.OUTPUT, PinType.FLOAT),
    ]
    MIN_WIDTH  = 160.0
    MIN_HEIGHT = 60.0

    def on_start(self) -> None:
        self._update()

    def on_tick_check(self) -> None:
        self._update()

    def _update(self) -> None:
        self.set_output("seconds", time.time())


# ─────────────────────────────────────────────────────────────────────────────
# Current DateTime (epoch seconds)
# ─────────────────────────────────────────────────────────────────────────────

class CurrentDateTimeNode(NodeBase):
    """Outputs current time as DATETIME (epoch seconds, float). Updates every tick check."""
    NODE_NAME  = "Current DateTime"
    NODE_GROUP = "Time/Acquire"
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
    NODE_GROUP = "Time/Acquire"
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
# Delay (one-shot: start → wait delay_s → exec_out once)
# ─────────────────────────────────────────────────────────────────────────────

class DelayNode(NodeBase):
    """
    When 'start' tick fires, waits delay_s then fires exec_out once.
    'stop' cancels the delay. Does not repeat.
    'hold' (bool) pauses the countdown while True.
    """
    NODE_NAME  = "Delay"
    NODE_GROUP = "Time/Waiting"
    PINS = [
        PinDescriptor("start",      PinDirection.INPUT,  PinType.TICK),
        PinDescriptor("stop",       PinDirection.INPUT,  PinType.TICK),
        PinDescriptor("delay_s",    PinDirection.INPUT,  PinType.FLOAT, optional=True),
        PinDescriptor("hold",       PinDirection.INPUT,  PinType.BOOL,  optional=True),
        PinDescriptor("exec_out",   PinDirection.OUTPUT, PinType.TICK),
        PinDescriptor("elapsed_s",  PinDirection.OUTPUT, PinType.FLOAT),
    ]
    VARIABLE_INPUTS = {
        "delay_s": (float, 1.0),
    }
    MIN_WIDTH  = 180.0
    MIN_HEIGHT = 110.0

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._active:      bool          = False
        self._start_time:  float         = 0.0
        self._pause_start: float | None  = None
        self._hold_start:  float | None  = None

    def on_start(self) -> None:
        self._active      = False
        self._start_time  = 0.0
        self._pause_start = None
        self._hold_start  = None

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
            self._hold_start = None
        elif trigger_pin == "stop":
            self._active     = False
            self._hold_start = None

    def on_tick_check(self) -> None:
        if not self._active:
            return
        held = bool(self.get_input("hold"))
        now  = time.monotonic()
        if held:
            if self._hold_start is None:
                self._hold_start = now
            return
        elif self._hold_start is not None:
            self._start_time += now - self._hold_start
            self._hold_start  = None
        delay_s = float(self.get_var_input("delay_s") or 1.0)
        elapsed = now - self._start_time
        self.set_output("elapsed_s", elapsed)
        if elapsed >= delay_s:
            self.fire_tick("exec_out")
            self._active = False
            self.node_changed.emit()

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        if not self._active:
            return
        delay_s = float(self.get_var_input("delay_s") or 1.0)
        held    = bool(self.get_input("hold"))
        if held and self._hold_start is not None:
            elapsed = self._hold_start - self._start_time
        else:
            elapsed = time.monotonic() - self._start_time
        pct      = min(1.0, elapsed / max(0.001, delay_s))
        bar_w    = (rect.width() - 8) * pct
        bar_rect = QRectF(rect.x() + 4, rect.y() + 4, bar_w, 8)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor("#f95979") if not held else QColor("#888888")))
        painter.drawRoundedRect(bar_rect, 3, 3)
        painter.setPen(QColor("#c8889a"))
        painter.setFont(QFont("Courier New", 8))
        label = f"{elapsed:.2f} / {delay_s:.2f} s" + (" [HOLD]" if held else "")
        painter.drawText(
            QRectF(rect.x(), rect.y() + 14, rect.width(), 18),
            Qt.AlignmentFlag.AlignCenter,
            label,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Timer (repeating: fires exec_out every interval_s)
# ─────────────────────────────────────────────────────────────────────────────

class TimerNode(NodeBase):
    """
    When 'start' tick fires, begins firing exec_out every interval_s.
    'stop' tick stops the timer. Repeating.
    'hold' (bool) pauses firing while True.
    """
    NODE_NAME  = "Timer"
    NODE_GROUP = "Time/Waiting"
    PINS = [
        PinDescriptor("start",      PinDirection.INPUT,  PinType.TICK),
        PinDescriptor("stop",       PinDirection.INPUT,  PinType.TICK),
        PinDescriptor("interval_s", PinDirection.INPUT,  PinType.FLOAT, optional=True),
        PinDescriptor("hold",       PinDirection.INPUT,  PinType.BOOL,  optional=True),
        PinDescriptor("exec_out",   PinDirection.OUTPUT, PinType.TICK),
    ]
    VARIABLE_INPUTS = {
        "interval_s": (float, 1.0),
    }
    MIN_WIDTH  = 180.0
    MIN_HEIGHT = 100.0

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._active:      bool         = False
        self._next_fire:   float        = 0.0
        self._pause_start: float | None = None
        self._hold_start:  float | None = None

    def on_start(self) -> None:
        self._active      = False
        self._next_fire   = 0.0
        self._pause_start = None
        self._hold_start  = None

    def on_pause(self) -> None:
        if self._active:
            self._pause_start = time.monotonic()

    def on_resume(self) -> None:
        if self._active and self._pause_start is not None:
            self._next_fire += time.monotonic() - self._pause_start
        self._pause_start = None

    def execute(self, trigger_pin: str) -> None:
        if trigger_pin == "start":
            self._active     = True
            self._hold_start = None
            interval_s       = max(0.001, float(self.get_var_input("interval_s") or 1.0))
            self._next_fire  = time.monotonic() + interval_s
        elif trigger_pin == "stop":
            self._active     = False
            self._hold_start = None

    def on_tick_check(self) -> None:
        if not self._active:
            return
        held = bool(self.get_input("hold"))
        now  = time.monotonic()
        if held:
            if self._hold_start is None:
                self._hold_start = now
            return
        elif self._hold_start is not None:
            self._next_fire  += now - self._hold_start
            self._hold_start  = None
        if now >= self._next_fire:
            interval_s      = max(0.001, float(self.get_var_input("interval_s") or 1.0))
            self._next_fire = now + interval_s
            self.fire_tick("exec_out")
            self.node_changed.emit()

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        interval_s = max(0.001, float(self.get_var_input("interval_s") or 1.0))
        if self._active:
            held = bool(self.get_input("hold"))
            now  = time.monotonic()
            if held and self._hold_start is not None:
                now = self._hold_start
            elapsed = now - (self._next_fire - interval_s)
            pct     = min(1.0, max(0.0, elapsed / interval_s))
            bar_w   = (rect.width() - 8) * pct
            bar_rect = QRectF(rect.x() + 4, rect.y() + 4, bar_w, 8)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor("#f95979") if not held else QColor("#888888")))
            painter.drawRoundedRect(bar_rect, 3, 3)
            painter.setPen(QColor("#c8889a"))
            painter.setFont(QFont("Courier New", 8))
            label = f"{elapsed:.2f} / {interval_s:.2f} s" + (" [HOLD]" if held else "")
            painter.drawText(
                QRectF(rect.x(), rect.y() + 14, rect.width(), 18),
                Qt.AlignmentFlag.AlignCenter,
                label,
            )
        else:
            painter.setPen(QColor("#f95979"))
            painter.setFont(QFont("Courier New", 8))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, f"every {interval_s:.2f} s")


# ─────────────────────────────────────────────────────────────────────────────
# Delta Time (time since last exec_in; first time = time since start)
# ─────────────────────────────────────────────────────────────────────────────

class DeltaTimeNode(NodeBase):
    """
    On each exec_in tick, outputs the time (seconds) since the previous exec_in.
    On the first exec_in, outputs time since graph start.
    """
    NODE_NAME  = "Delta Time"
    NODE_GROUP = "Time/Acquire"
    PINS = [
        PinDescriptor("exec_in",  PinDirection.INPUT,  PinType.TICK),
        PinDescriptor("delta_s",  PinDirection.OUTPUT, PinType.FLOAT),
        PinDescriptor("exec_out", PinDirection.OUTPUT, PinType.TICK),
    ]
    MIN_WIDTH  = 160.0
    MIN_HEIGHT = 70.0

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._last_time:   float | None = None  # None = first tick, output time since start
        self._start_time:  float        = 0.0
        self._pause_start: float | None = None

    def on_start(self) -> None:
        self._start_time  = time.monotonic()
        self._last_time   = None
        self._pause_start = None

    def on_pause(self) -> None:
        self._pause_start = time.monotonic()

    def on_resume(self) -> None:
        if self._pause_start is not None:
            paused = time.monotonic() - self._pause_start
            self._start_time += paused
            if self._last_time is not None:
                self._last_time += paused
        self._pause_start = None

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


# ─────────────────────────────────────────────────────────────────────────────
# Countdown (one-shot: captures duration on start/reset, counts down to zero)
# ─────────────────────────────────────────────────────────────────────────────

class CountdownNode(NodeBase):
    """
    Captures duration_s on 'start' (or 'reset'), counts down to zero, then
    fires exec_out once.  Changing duration_s after start has no effect until
    the next 'reset' or 'start'.  'hold' (bool) pauses the countdown while True.
    """
    NODE_NAME  = "Countdown"
    NODE_GROUP = "Time/Waiting"
    PINS = [
        PinDescriptor("start",       PinDirection.INPUT,  PinType.TICK),
        PinDescriptor("reset",       PinDirection.INPUT,  PinType.TICK),
        PinDescriptor("duration_s",  PinDirection.INPUT,  PinType.FLOAT, optional=True),
        PinDescriptor("hold",        PinDirection.INPUT,  PinType.BOOL,  optional=True),
        PinDescriptor("exec_out",    PinDirection.OUTPUT, PinType.TICK),
        PinDescriptor("remaining_s", PinDirection.OUTPUT, PinType.FLOAT),
    ]
    VARIABLE_INPUTS = {
        "duration_s": (float, 1.0),
    }
    MIN_WIDTH  = 190.0
    MIN_HEIGHT = 110.0

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._active:      bool         = False
        self._start_time:  float        = 0.0
        self._duration_s:  float        = 1.0   # captured on start/reset
        self._pause_start: float | None = None
        self._hold_start:  float | None = None

    def on_start(self) -> None:
        self._active      = False
        self._start_time  = 0.0
        self._duration_s  = 1.0
        self._pause_start = None
        self._hold_start  = None
        self.set_output("remaining_s", 0.0)

    def on_pause(self) -> None:
        if self._active:
            self._pause_start = time.monotonic()

    def on_resume(self) -> None:
        if self._active and self._pause_start is not None:
            self._start_time += time.monotonic() - self._pause_start
        self._pause_start = None

    def _arm(self) -> None:
        """Capture duration and restart the countdown."""
        self._duration_s = float(self.get_var_input("duration_s") or 1.0)
        self._start_time = time.monotonic()
        self._active     = True
        self._hold_start = None
        self.set_output("remaining_s", self._duration_s)

    def execute(self, trigger_pin: str) -> None:
        if trigger_pin in ("start", "reset"):
            self._arm()

    def on_tick_check(self) -> None:
        if not self._active:
            return
        held = bool(self.get_input("hold"))
        now  = time.monotonic()
        if held:
            if self._hold_start is None:
                self._hold_start = now
            return
        elif self._hold_start is not None:
            self._start_time += now - self._hold_start
            self._hold_start  = None
        elapsed     = now - self._start_time
        remaining_s = max(0.0, self._duration_s - elapsed)
        self.set_output("remaining_s", remaining_s)
        if elapsed >= self._duration_s:
            self.fire_tick("exec_out")
            self._active = False
            self.node_changed.emit()

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        if not self._active:
            remaining = self.get_output("remaining_s") or 0.0
            painter.setPen(QColor("#f95979"))
            painter.setFont(QFont("Courier New", 8))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter,
                             f"{remaining:.2f} s left" if remaining > 0 else "done")
            return
        held = bool(self.get_input("hold"))
        if held and self._hold_start is not None:
            elapsed = self._hold_start - self._start_time
        else:
            elapsed = time.monotonic() - self._start_time
        remaining_s = max(0.0, self._duration_s - elapsed)
        pct         = min(1.0, elapsed / max(0.001, self._duration_s))
        bar_w    = (rect.width() - 8) * (1.0 - pct)
        bar_rect = QRectF(rect.x() + 4, rect.y() + 4, bar_w, 8)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor("#f95979") if not held else QColor("#888888")))
        painter.drawRoundedRect(bar_rect, 3, 3)
        painter.setPen(QColor("#c8889a"))
        painter.setFont(QFont("Courier New", 8))
        label = f"{remaining_s:.2f} / {self._duration_s:.2f} s" + (" [HOLD]" if held else "")
        painter.drawText(
            QRectF(rect.x(), rect.y() + 14, rect.width(), 18),
            Qt.AlignmentFlag.AlignCenter,
            label,
        )
