"""
Trigger nodes — edge detection on value changes.

Group: Triggers

Rising Trigger  — outputs TICK when input value rises (false → true, or numerically increases)
Falling Trigger — outputs TICK when input value falls (true → false, or numerically decreases)
DDR Trigger     — outputs TICK on any change (rise or fall)

All trigger nodes:
  • Accept "Any" input and convert to numeric value
  • Bool is converted: True=1, False=0
  • Track the previous value to detect transitions
  • Fire a TICK event when the transition condition is met
"""
from __future__ import annotations

from typing import Any

from PyQt6.QtCore import QRectF
from PyQt6.QtGui import QPainter, QColor, QFont

from core.node_base import NodeBase
from core.types import PinDescriptor, PinDirection, PinType


def _to_numeric(value: Any) -> float:
    """Convert any value to a numeric value for comparison.

    Bool: True=1.0, False=0.0
    Other: try to convert to float, default to 0.0
    """
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Rising Trigger
# ─────────────────────────────────────────────────────────────────────────────

class RisingTriggerNode(NodeBase):
    """
    Rising Trigger: outputs TICK when input value rises.

    Detects transitions from low to high:
    - When numeric value increases: fires TICK
    - Reacts immediately to data changes (no external tick input required)
    """
    NODE_NAME        = "Rising Trigger"
    NODE_GROUP       = "Triggers"
    NODE_TITLE_COLOR = "#1a3a5f"

    PINS = [
        PinDescriptor("input",   PinDirection.INPUT, PinType.ANY, default=0),
        PinDescriptor("exec_out", PinDirection.OUTPUT, PinType.TICK),
        PinDescriptor("result",  PinDirection.OUTPUT, PinType.BOOL),
    ]

    MIN_WIDTH  = 150.0
    MIN_HEIGHT = 70.0

    def __init__(self, **kw: Any) -> None:
        super().__init__(**kw)
        self._prev_value: float = 0.0
        self._fired: bool = False

    def on_start(self) -> None:
        val = self.get_input("input")
        self._prev_value = _to_numeric(val)
        self._fired = False

    def on_data_received(self, pin_name: str, value: Any) -> None:
        if pin_name == "input":
            self._check_transition()

    def execute(self, trigger_pin: str) -> None:
        self._check_transition()

    def _check_transition(self) -> None:
        """Check if value rose and fire TICK once when transition starts."""
        curr_val = _to_numeric(self.get_input("input"))
        rose = curr_val > self._prev_value

        # Fire TICK only when we transition FROM not-rising TO rising
        if rose and not self._fired:
            self.fire_tick("exec_out")
            self._fired = True
        elif not rose:
            # Reset when value stops rising
            self._fired = False

        # Result is true as long as the condition is met
        self.set_output("result", rose)
        self._prev_value = curr_val

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        painter.setPen(QColor("#64b5f6"))
        painter.setFont(QFont("Courier New", 8))
        painter.drawText(rect, 0x0004, "↗ rising")

    def get_state(self) -> dict[str, Any]:
        s = super().get_state()
        s["__prev_value__"] = self._prev_value
        s["__fired__"] = self._fired
        return s

    def set_state(self, state: dict[str, Any]) -> None:
        self._prev_value = float(state.pop("__prev_value__", 0.0))
        self._fired = bool(state.pop("__fired__", False))
        super().set_state(state)


# ─────────────────────────────────────────────────────────────────────────────
# Falling Trigger
# ─────────────────────────────────────────────────────────────────────────────

class FallingTriggerNode(NodeBase):
    """
    Falling Trigger: outputs TICK when input value falls.

    Detects transitions from high to low:
    - When numeric value decreases: fires TICK
    - Reacts immediately to data changes (no external tick input required)
    """
    NODE_NAME        = "Falling Trigger"
    NODE_GROUP       = "Triggers"
    NODE_TITLE_COLOR = "#3a1a5f"

    PINS = [
        PinDescriptor("input",   PinDirection.INPUT, PinType.ANY, default=0),
        PinDescriptor("exec_out", PinDirection.OUTPUT, PinType.TICK),
        PinDescriptor("result",  PinDirection.OUTPUT, PinType.BOOL),
    ]

    MIN_WIDTH  = 150.0
    MIN_HEIGHT = 70.0

    def __init__(self, **kw: Any) -> None:
        super().__init__(**kw)
        self._prev_value: float = 0.0
        self._fired: bool = False

    def on_start(self) -> None:
        val = self.get_input("input")
        self._prev_value = _to_numeric(val)
        self._fired = False

    def on_data_received(self, pin_name: str, value: Any) -> None:
        if pin_name == "input":
            self._check_transition()

    def execute(self, trigger_pin: str) -> None:
        self._check_transition()

    def _check_transition(self) -> None:
        """Check if value fell and fire TICK once when transition starts."""
        curr_val = _to_numeric(self.get_input("input"))
        fell = curr_val < self._prev_value

        # Fire TICK only when we transition FROM not-falling TO falling
        if fell and not self._fired:
            self.fire_tick("exec_out")
            self._fired = True
        elif not fell:
            # Reset when value stops falling
            self._fired = False

        # Result is true as long as the condition is met
        self.set_output("result", fell)
        self._prev_value = curr_val

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        painter.setPen(QColor("#ef5350"))
        painter.setFont(QFont("Courier New", 8))
        painter.drawText(rect, 0x0004, "↘ falling")

    def get_state(self) -> dict[str, Any]:
        s = super().get_state()
        s["__prev_value__"] = self._prev_value
        s["__fired__"] = self._fired
        return s

    def set_state(self, state: dict[str, Any]) -> None:
        self._prev_value = float(state.pop("__prev_value__", 0.0))
        self._fired = bool(state.pop("__fired__", False))
        super().set_state(state)


# ─────────────────────────────────────────────────────────────────────────────
# DDR Trigger (Data Dependency Relay / Dual-edge Detector)
# ─────────────────────────────────────────────────────────────────────────────

class DDRTriggerNode(NodeBase):
    """
    DDR Trigger: outputs TICK when input value changes in any direction.

    Detects any transition:
    - When numeric value changes (rises or falls): fires TICK
    - Reacts immediately to data changes (no external tick input required)

    DDR = "Data Dependency Relay" or "Dual-edge Detection Response"
    """
    NODE_NAME        = "DDR Trigger"
    NODE_GROUP       = "Triggers"
    NODE_TITLE_COLOR = "#2d5a3d"

    PINS = [
        PinDescriptor("input",   PinDirection.INPUT, PinType.ANY, default=0),
        PinDescriptor("exec_out", PinDirection.OUTPUT, PinType.TICK),
        PinDescriptor("result",  PinDirection.OUTPUT, PinType.BOOL),
    ]

    MIN_WIDTH  = 150.0
    MIN_HEIGHT = 70.0

    def __init__(self, **kw: Any) -> None:
        super().__init__(**kw)
        self._prev_value: float = 0.0
        self._fired: bool = False

    def on_start(self) -> None:
        val = self.get_input("input")
        self._prev_value = _to_numeric(val)
        self._fired = False

    def on_data_received(self, pin_name: str, value: Any) -> None:
        if pin_name == "input":
            self._check_transition()

    def execute(self, trigger_pin: str) -> None:
        self._check_transition()

    def _check_transition(self) -> None:
        """Check if value changed and fire TICK once when transition starts."""
        curr_val = _to_numeric(self.get_input("input"))
        changed = curr_val != self._prev_value

        # Fire TICK only when we transition FROM stable TO changing
        if changed and not self._fired:
            self.fire_tick("exec_out")
            self._fired = True
        elif not changed:
            # Reset when value becomes stable
            self._fired = False

        # Result is true as long as the condition is met
        self.set_output("result", changed)
        self._prev_value = curr_val

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        painter.setPen(QColor("#66bb6a"))
        painter.setFont(QFont("Courier New", 8))
        painter.drawText(rect, 0x0004, "↗↘ change")

    def get_state(self) -> dict[str, Any]:
        s = super().get_state()
        s["__prev_value__"] = self._prev_value
        s["__fired__"] = self._fired
        return s

    def set_state(self, state: dict[str, Any]) -> None:
        self._prev_value = float(state.pop("__prev_value__", 0.0))
        self._fired = bool(state.pop("__fired__", False))
        super().set_state(state)
