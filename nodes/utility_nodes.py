"""
Utility nodes — Counter, Random, Beep.

Timer and Delay are in nodes.time_nodes.
Log/Debug and display nodes are in nodes.debug_nodes.
"""
from __future__ import annotations

import random
import sys
import threading
import time
from typing import Any

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui  import QPainter, QColor, QFont

from core.node_base import NodeBase
from core.types     import PinDescriptor, PinDirection, PinType


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
        PinDescriptor("hold",       PinDirection.INPUT,  PinType.BOOL),
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
    MIN_HEIGHT = 100.0

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

        # Handle hold input
        held = bool(self.get_input("hold"))
        if held and trigger_pin != "reset":
            return

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
# RANDOM VALUE
# ─────────────────────────────────────────────────────────────────────────────

class RandomNode(NodeBase):
    """
    Generates a uniform random float in [min_val, max_val] on each exec tick.
    min_val / max_val can be set via inline editors or overridden by wiring a
    FLOAT pin directly (same VARIABLE_INPUTS pattern as CounterNode).
    """
    NODE_NAME  = "Randomizer"
    NODE_GROUP = "Utility"
    PINS = [
        PinDescriptor("exec_in",  PinDirection.INPUT,  PinType.TICK),
        PinDescriptor("min_val",  PinDirection.INPUT,  PinType.FLOAT, optional=True),
        PinDescriptor("max_val",  PinDirection.INPUT,  PinType.FLOAT, optional=True),
        PinDescriptor("exec_out", PinDirection.OUTPUT, PinType.TICK),
        PinDescriptor("value",    PinDirection.OUTPUT, PinType.FLOAT),
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
# RANDOM DATA (asynchronous — updates every graph tick)
# ─────────────────────────────────────────────────────────────────────────────

class RandomDataNode(NodeBase):
    """
    Pure data node that pushes a new random float on every graph tick (~10 ms).
    No exec flow required — behaves like a continuously changing data source.
    min_val / max_val can be set via inline editors or overridden by wiring a
    FLOAT pin directly.
    """
    NODE_NAME  = "Random"
    NODE_GROUP = "Utility"
    _TR_KEY    = "random_data"
    PINS = [
        PinDescriptor("min_val", PinDirection.INPUT,  PinType.FLOAT, optional=True),
        PinDescriptor("max_val", PinDirection.INPUT,  PinType.FLOAT, optional=True),
        PinDescriptor("value",   PinDirection.OUTPUT, PinType.FLOAT),
    ]
    VARIABLE_INPUTS = {
        "min_val": (float, 0.0),
        "max_val": (float, 1.0),
    }
    MIN_WIDTH  = 160.0
    MIN_HEIGHT = 80.0

    def on_start(self) -> None:
        self._push()

    def on_tick_check(self) -> None:
        self._push()

    def execute(self, trigger_pin: str) -> None:
        pass

    def _push(self) -> None:
        lo = float(self.get_var_input("min_val") or 0.0)
        hi = float(self.get_var_input("max_val") or 1.0)
        self.set_output("value", random.uniform(lo, hi))


# ─────────────────────────────────────────────────────────────────────────────
# BEEP (PC SPEAKER)
# ─────────────────────────────────────────────────────────────────────────────

class BeepNode(NodeBase):
    """
    Plays a PC speaker beep when triggered via TICK input.
    Frequency (Hz) and duration (ms) can be set via wired pins or inline fields.
    Beep runs in a background thread so it does not block the graph.

    On Windows uses winsound.Beep(); on other platforms attempts the 'beep' CLI.
    """
    NODE_NAME  = "Beep (PC)"
    NODE_GROUP = "Utility"
    _TR_KEY    = "beep"
    PINS = [
        PinDescriptor("exec_in",   PinDirection.INPUT,  PinType.TICK),
        PinDescriptor("frequency", PinDirection.INPUT,  PinType.FLOAT, optional=True),
        PinDescriptor("duration",  PinDirection.INPUT,  PinType.FLOAT, optional=True),
        PinDescriptor("exec_out",  PinDirection.OUTPUT, PinType.TICK),
    ]
    VARIABLE_INPUTS = {
        "frequency": (float, 440.0),
        "duration":  (float, 200.0),
    }
    MIN_WIDTH  = 170.0
    MIN_HEIGHT = 90.0

    def execute(self, trigger_pin: str) -> None:
        freq = float(self.get_var_input("frequency") or 440.0)
        dur  = float(self.get_var_input("duration")  or 200.0)
        freq = max(37.0, min(32767.0, freq))
        dur  = max(1.0, dur)

        def _beep():
            try:
                if sys.platform == "win32":
                    import winsound
                    winsound.Beep(int(freq), int(dur))
                else:
                    import subprocess
                    subprocess.run(
                        ["beep", f"-f{int(freq)}", f"-l{int(dur)}"],
                        check=False,
                    )
            except Exception:
                pass

        threading.Thread(target=_beep, daemon=True).start()
        self.fire_tick("exec_out")


# ─────────────────────────────────────────────────────────────────────────────
# FREQUENCY GENERATOR
# ─────────────────────────────────────────────────────────────────────────────

class FrequencyGeneratorNode(NodeBase):
    """
    Fires exec_out at a configurable rate (Hz) continuously while the graph runs.
    'frequency' can be wired from an external float or set via the inline field.
    'enable' (optional bool) gates the output — when not wired, always enabled.
    Frequency is read on every tick so changes take effect immediately.
    """
    NODE_NAME  = "Frequency Generator"
    NODE_GROUP = "Utility"
    PINS = [
        PinDescriptor("frequency", PinDirection.INPUT,  PinType.FLOAT, optional=True),
        PinDescriptor("enable",    PinDirection.INPUT,  PinType.BOOL,  optional=True),
        PinDescriptor("exec_out",  PinDirection.OUTPUT, PinType.TICK),
    ]
    VARIABLE_INPUTS = {
        "frequency": (float, 1.0),
    }
    MIN_WIDTH  = 190.0
    MIN_HEIGHT = 90.0

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._next_fire: float = 0.0

    def on_start(self) -> None:
        self._next_fire = time.monotonic()

    def on_tick_check(self) -> None:
        enable = self.get_input("enable")
        if enable is not None and not bool(enable):
            return
        freq = float(self.get_var_input("frequency") or 1.0)
        freq = max(0.001, freq)
        now = time.monotonic()
        if now >= self._next_fire:
            self._next_fire = now + 1.0 / freq
            self.fire_tick("exec_out")
            self.node_changed.emit()

    def execute(self, trigger_pin: str) -> None:
        pass

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        freq = float(self.get_var_input("frequency") or 1.0)
        enable = self.get_input("enable")
        enabled = enable is None or bool(enable)
        color = QColor("#80cbc4") if enabled else QColor("#666666")
        painter.setPen(color)
        painter.setFont(QFont("Courier New", 9))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, f"{freq:.4g} Hz")


# ─────────────────────────────────────────────────────────────────────────────
# SAMPLE AND HOLD
# ─────────────────────────────────────────────────────────────────────────────

class SampleAndHoldNode(NodeBase):
    """
    On each 'trigger' tick, captures the current 'input' value and holds it
    on 'value' until the next trigger. exec_out fires after each sample.
    The held value persists across ticks — only updated on trigger.
    """
    NODE_NAME  = "Sample & Hold"
    NODE_GROUP = "Utility"
    PINS = [
        PinDescriptor("trigger",  PinDirection.INPUT,  PinType.TICK),
        PinDescriptor("input",    PinDirection.INPUT,  PinType.ANY),
        PinDescriptor("exec_out", PinDirection.OUTPUT, PinType.TICK),
        PinDescriptor("value",    PinDirection.OUTPUT, PinType.ANY),
    ]
    MIN_WIDTH  = 170.0
    MIN_HEIGHT = 80.0

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._held: Any = None

    def on_start(self) -> None:
        self._held = None

    def execute(self, trigger_pin: str) -> None:
        self._held = self.get_input("input")
        self.set_output("value", self._held)
        self.fire_tick("exec_out")
        self.node_changed.emit()

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        v = self._held
        if v is None:
            label = "—"
        elif isinstance(v, float):
            label = f"{v:.4g}"
        elif isinstance(v, int):
            label = str(v)
        elif isinstance(v, (tuple, list)):
            parts = ", ".join(f"{x:.3g}" for x in list(v)[:3])
            label = f"({parts}{'…' if len(v) > 3 else ''})"
        else:
            label = str(v)[:16]
        painter.setPen(QColor("#80cbc4"))
        painter.setFont(QFont("Courier New", 9))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)

