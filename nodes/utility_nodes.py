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
from PyQt6.QtGui  import QAction, QPainter, QColor, QFont
from PyQt6.QtWidgets import QMenu

from core.node_base import NodeBase
from core.localization import tr
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
        PinDescriptor("exec_out", PinDirection.OUTPUT, PinType.TICK),
        PinDescriptor("on_min", PinDirection.OUTPUT, PinType.TICK),
        PinDescriptor("on_max", PinDirection.OUTPUT, PinType.TICK),
        PinDescriptor("count",      PinDirection.OUTPUT, PinType.INT),

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
    NODE_GROUP = "Math/Random"
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
    NODE_GROUP = "Math/Random"
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
    NODE_GROUP = "Time/Waveforms"
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
    Samples the current ANY input each time trigger receives a tick.

    Sample Last preserves the original value. Numeric sample modes are based
    on values that can be converted to float and are kept in a bounded buffer.
    exec_out fires after outputs are updated so device notification nodes can
    be driven from the sampled values.
    """
    NODE_NAME  = "Sample & Hold"
    NODE_GROUP = "Utility"
    _MODES = {
        "max": "Sample Max",
        "min": "Sample Min",
        "avg": "Sample Avg",
        "last": "Sample Last",
        "median": "Sample Median",
    }
    PINS = [
        PinDescriptor("trigger",       PinDirection.INPUT,  PinType.TICK),
        PinDescriptor("reset",         PinDirection.INPUT,  PinType.TICK),
        PinDescriptor("input",         PinDirection.INPUT,  PinType.ANY),
        PinDescriptor("max_samples",   PinDirection.INPUT,  PinType.INT, optional=True),
        PinDescriptor("exec_out",      PinDirection.OUTPUT, PinType.TICK),
        PinDescriptor("value",         PinDirection.OUTPUT, PinType.ANY),
        PinDescriptor("sample_count",  PinDirection.OUTPUT, PinType.INT),
    ]
    VARIABLE_INPUTS = {
        "max_samples": (int, 100),
    }
    MIN_WIDTH  = 210.0
    MIN_HEIGHT = 140.0

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._values: list[Any] = []
        self._numeric_values: list[float | None] = []
        self._last: Any = None
        self._sample_mode: str = "last"

    def on_start(self) -> None:
        self._reset()
        self._publish()

    def execute(self, trigger_pin: str) -> None:
        if trigger_pin == "reset":
            self._reset()
            self._publish()
            self.node_changed.emit()
            return
        self._sample()
        self._publish()
        self.fire_tick("exec_out")
        self.node_changed.emit()

    def on_var_input_changed(self, pin_name: str, value: Any) -> None:
        if pin_name == "max_samples":
            self._trim()
            self._publish()

    def get_sample_mode(self) -> str:
        return self._sample_mode

    def set_sample_mode(self, mode: str) -> None:
        if mode not in self._MODES:
            return
        self._sample_mode = mode
        self._publish()
        self.node_changed.emit()

    def _get_context_menu(self, canvas: Any, menu: QMenu, field_hit: Any = None) -> None:
        mode_menu = QMenu(tr("ui.canvas.menu.sampler_mode", default="Sample mode"), menu)
        mode_menu.setStyleSheet(menu.styleSheet())
        for mode, label in self._MODES.items():
            act = QAction(label, mode_menu)
            act.setCheckable(True)
            act.setChecked(mode == self._sample_mode)
            act.triggered.connect(
                lambda _checked, m=mode: self._set_sample_mode(canvas, m)
            )
            mode_menu.addAction(act)
        menu.addMenu(mode_menu)

    def _set_sample_mode(self, canvas: Any, mode: str) -> None:
        self.set_sample_mode(mode)
        canvas.update()

    def _reset(self) -> None:
        self._values.clear()
        self._numeric_values.clear()
        self._last = None

    def _max_samples(self) -> int:
        try:
            return max(1, int(self.get_var_input("max_samples") or 100))
        except (TypeError, ValueError):
            return 100

    def _sample(self) -> None:
        value = self.get_input("input")
        self._last = value
        self._values.append(value)
        try:
            numeric_value = float(value)
        except (TypeError, ValueError):
            numeric_value = None
        self._numeric_values.append(numeric_value)
        self._trim()

    def _trim(self) -> None:
        max_samples = self._max_samples()
        if len(self._values) > max_samples:
            del self._values[:-max_samples]
        if len(self._numeric_values) > max_samples:
            del self._numeric_values[:-max_samples]

    def _numeric(self) -> list[float]:
        return [v for v in self._numeric_values if v is not None]

    def _median(self, values: list[float]) -> float:
        ordered = sorted(values)
        mid = len(ordered) // 2
        if len(ordered) % 2 == 1:
            return ordered[mid]
        return (ordered[mid - 1] + ordered[mid]) / 2.0

    def _publish(self) -> None:
        if self._sample_mode == "last":
            sample = self._last
        else:
            numeric = self._numeric()
            if not numeric:
                sample = 0.0
            elif self._sample_mode == "max":
                sample = max(numeric)
            elif self._sample_mode == "min":
                sample = min(numeric)
            elif self._sample_mode == "avg":
                sample = sum(numeric) / len(numeric)
            elif self._sample_mode == "median":
                sample = self._median(numeric)
            else:
                sample = self._last
        self.set_output("value", sample)
        self.set_output("sample_count", len(self._values))

    def get_state(self) -> dict[str, Any]:
        state = super().get_state()
        state["_sample_mode"] = self._sample_mode
        return state

    def set_state(self, state: dict[str, Any]) -> None:
        mode = state.pop("_sample_mode", "last")
        super().set_state(state)
        self._sample_mode = mode if mode in self._MODES else "last"

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        painter.setPen(QColor("#80cbc4"))
        painter.setFont(QFont("Courier New", 8))
        label = f"{self._MODES[self._sample_mode]} n={len(self._values)}"
        if self._last is not None:
            label += f" last={str(self._last)[:12]}"
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)


# ─────────────────────────────────────────────────────────────────────────────
# VALUE PORTAL INPUT / OUTPUT
# ─────────────────────────────────────────────────────────────────────────────

class ValuePortalInput(NodeBase):
    """
    Input side of a value portal. Stores the most recent value received on
    'input'. ValuePortalOutput nodes with the same name read it directly.
    The portal name is the node's custom_name (set by renaming the node).
    """
    NODE_NAME  = "Value Portal Input"
    NODE_GROUP = "Portals"
    _TR_KEY    = "value_portal_input"
    PINS = [
        PinDescriptor("input", PinDirection.INPUT, PinType.ANY),
    ]
    MIN_WIDTH  = 160.0
    MIN_HEIGHT = 80.0

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._stored_value: Any = None

    @property
    def _portal_name(self) -> str:
        return self.custom_name or "Portal"

    def execute(self, trigger_pin: str) -> None:
        pass

    def on_data_received(self, pin_name: str, value: Any) -> None:
        if pin_name == "input":
            self._stored_value = value
            self.node_changed.emit()


class ValuePortalOutput(NodeBase):
    """
    Output side of a value portal. Scans the runtime each tick for a
    ValuePortalInput with the same name and pushes its stored value.
    The portal name is the node's custom_name (set by renaming the node).
    """
    NODE_NAME  = "Value Portal Output"
    NODE_GROUP = "Portals"
    _TR_KEY    = "value_portal_output"
    PINS = [
        PinDescriptor("value", PinDirection.OUTPUT, PinType.ANY),
    ]
    MIN_WIDTH  = 160.0
    MIN_HEIGHT = 80.0

    @property
    def _portal_name(self) -> str:
        return self.custom_name or "Portal"

    def execute(self, trigger_pin: str) -> None:
        pass

    def on_tick_check(self) -> None:
        if self._runtime is None:
            return
        name = self._portal_name
        for node in self._runtime.nodes.values():
            if isinstance(node, ValuePortalInput) and node._portal_name == name:
                self.set_output("value", node._stored_value)
                break


# ─────────────────────────────────────────────────────────────────────────────
# TICK PORTAL INPUT / OUTPUT
# ─────────────────────────────────────────────────────────────────────────────

class TickPortalInput(NodeBase):
    """
    Input side of a tick portal. When a TICK arrives on 'exec_in', fires all
    TickPortalOutput nodes with the same name, then fires 'exec_out'.
    The portal name is the node's custom_name (set by renaming the node).
    Matching is done dynamically at fire-time so renames take effect immediately.
    """
    NODE_NAME  = "Tick Portal Input"
    NODE_GROUP = "Portals"
    _TR_KEY    = "tick_portal_input"
    PINS = [
        PinDescriptor("exec_in",  PinDirection.INPUT,  PinType.TICK),
        PinDescriptor("exec_out", PinDirection.OUTPUT, PinType.TICK),
    ]
    MIN_WIDTH  = 160.0
    MIN_HEIGHT = 80.0

    @property
    def _portal_name(self) -> str:
        return self.custom_name or "Portal"

    def execute(self, trigger_pin: str) -> None:
        """Fire all matching tick portal outputs, then fire exec_out."""
        if trigger_pin == "exec_in":
            if self._runtime is not None:
                name = self._portal_name
                for node in self._runtime.nodes.values():
                    if isinstance(node, TickPortalOutput) and node._portal_name == name:
                        node.fire_tick("exec_out")
            self.fire_tick("exec_out")
            self.node_changed.emit()


class TickPortalOutput(NodeBase):
    """
    Output side of a tick portal. Fires 'exec_out' whenever a matching
    TickPortalInput (with the same name) receives a tick.
    The portal name is the node's custom_name (set by renaming the node).
    """
    NODE_NAME  = "Tick Portal Output"
    NODE_GROUP = "Portals"
    _TR_KEY    = "tick_portal_output"
    PINS = [
        PinDescriptor("exec_out", PinDirection.OUTPUT, PinType.TICK),
    ]
    MIN_WIDTH  = 160.0
    MIN_HEIGHT = 80.0

    @property
    def _portal_name(self) -> str:
        return self.custom_name or "Portal"

    def execute(self, trigger_pin: str) -> None:
        pass
