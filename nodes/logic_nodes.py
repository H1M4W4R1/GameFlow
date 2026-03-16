"""
Logic nodes — AND, OR, NOT boolean operations.

Design rules:
  • All logic nodes are PURE DATA — no exec_in / exec_out.
  • AND and OR accept a variable number of inputs; one trailing empty pin is
    always kept so the user can wire a new signal without first adding a pin.
  • Unconnected input pins are ignored during computation.
  • Inputs accept any type — truthy evaluation via bool().
  • Output is always BOOL.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui  import QPainter, QColor, QFont

from core.node_base import NodeBase
from core.types     import PinDescriptor, PinDirection, PinType

if False:
    from core.graph_runtime import GraphRuntime


# ─────────────────────────────────────────────────────────────────────────────
# Variable-input base for AND / OR
# ─────────────────────────────────────────────────────────────────────────────

class _MultiInputLogicNode(NodeBase):
    """
    Base for AND / OR nodes.

    Starts with two inputs; grows as inputs are connected.
    Always keeps exactly one trailing unconnected input pin so the user always
    has a free socket to wire into.  Disconnecting a pin trims excess empties.
    """

    NODE_GROUP   = "Logic"
    MIN_WIDTH    = 140.0
    MIN_HEIGHT   = 70.0
    PAINT_SYMBOL: str = "?"

    # Class-level PINS intentionally empty; each instance builds its own list.
    PINS: list[PinDescriptor] = []

    def __init__(self, *args, **kwargs) -> None:
        # Build instance-level PINS before super().__init__() because
        # super() reads self.PINS to populate default pin data.
        self.PINS = [
            PinDescriptor("in_0", PinDirection.INPUT, PinType.ANY, default=False),
            PinDescriptor("in_1", PinDirection.INPUT, PinType.ANY, default=False),
            PinDescriptor("result", PinDirection.OUTPUT, PinType.BOOL),
        ]
        super().__init__(*args, **kwargs)

    # ── Runtime attachment ───────────────────────────────────────────────────

    def _attach_runtime(
        self,
        runtime:  "GraphRuntime",
        push_cb:  Callable[[str, str, Any], None],
        tick_cb:  Callable[[str, str], None],
    ) -> None:
        super()._attach_runtime(runtime, push_cb, tick_cb)
        # Connect to wire events so pin count stays correct whether or not the
        # graph is currently running.
        runtime.wire_added.connect(self._on_wire_changed)
        runtime.wire_removed.connect(self._on_wire_changed)

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def on_start(self) -> None:
        self._sync_pins()
        self._compute()

    # ── Wire-change handler ──────────────────────────────────────────────────

    def _on_wire_changed(self, *args) -> None:
        """Called whenever any wire is added or removed in the graph."""
        self._sync_pins()
        self._compute()

    # ── Pin management ───────────────────────────────────────────────────────

    def _input_pins(self) -> list[PinDescriptor]:
        return [p for p in self.PINS if p.direction == PinDirection.INPUT]

    def _sync_pins(self) -> None:
        """
        Ensure exactly one trailing unconnected input pin exists.

        'Trailing' means the pin appears after the last connected input.
        Holes (unconnected pins before a connected one) are left untouched so
        that in-flight serialization round-trips cleanly.
        """
        if self._runtime is None:
            return

        inputs = self._input_pins()

        # Find the index of the last connected input.
        last_connected = -1
        for i, p in enumerate(inputs):
            if self._runtime.is_pin_connected(self.node_id, p.name):
                last_connected = i

        # Trailing unconnected = every pin after the last connected one.
        trailing = [inputs[i] for i in range(last_connected + 1, len(inputs))]

        changed = False

        if not trailing:
            # All inputs are connected — append a fresh empty pin.
            new_name = f"in_{len(inputs)}"
            self.PINS.insert(
                len(self.PINS) - 1,   # insert before the output pin
                PinDescriptor(new_name, PinDirection.INPUT, PinType.ANY, default=False),
            )
            self._data.setdefault(new_name, False)
            changed = True

        elif len(trailing) > 1:
            # More than one trailing empty — trim from the end, but never drop
            # below 2 total inputs.
            while len(trailing) > 1:
                inputs = self._input_pins()
                if len(inputs) <= 2:
                    break
                pin_to_remove = trailing.pop()   # remove last trailing
                self.PINS.remove(pin_to_remove)
                self._data.pop(pin_to_remove.name, None)
                changed = True

        if changed:
            self.node_changed.emit()

    # ── Computation ──────────────────────────────────────────────────────────

    def _connected_values(self) -> list[bool]:
        """Return bool values for all currently connected input pins."""
        result = []
        for p in self._input_pins():
            if self._runtime and self._runtime.is_pin_connected(self.node_id, p.name):
                v = self.get_input(p.name)
                result.append(bool(v) if v is not None else False)
        return result

    def _compute(self) -> None:
        raise NotImplementedError

    def on_data_received(self, pin_name: str, value: Any) -> None:
        self._compute()

    def execute(self, trigger_pin: str) -> None:
        self._compute()

    # ── State serialisation ──────────────────────────────────────────────────

    def get_state(self) -> dict[str, Any]:
        state = super().get_state()
        state["__pin_count__"] = len(self._input_pins())
        return state

    def set_state(self, state: dict[str, Any]) -> None:
        pin_count = state.pop("__pin_count__", 2)
        # Grow the PINS list to match the saved count before calling super()
        # (super reads self.PINS when restoring pin values).
        current = len(self._input_pins())
        while current < pin_count:
            new_name = f"in_{current}"
            self.PINS.insert(
                len(self.PINS) - 1,
                PinDescriptor(new_name, PinDirection.INPUT, PinType.ANY, default=False),
            )
            self._data.setdefault(new_name, False)
            current += 1
        super().set_state(state)

    # ── Painting ─────────────────────────────────────────────────────────────

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        painter.setPen(QColor("#ffb74d"))
        painter.setFont(QFont("Courier New", 12, QFont.Weight.Bold))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self.PAINT_SYMBOL)


# ─────────────────────────────────────────────────────────────────────────────
# AND
# ─────────────────────────────────────────────────────────────────────────────

class AndNode(_MultiInputLogicNode):
    """All connected inputs must be truthy → True.  Output is False when no
    inputs are connected."""
    NODE_NAME    = "AND"
    PAINT_SYMBOL = "AND"

    def _compute(self) -> None:
        values = self._connected_values()
        self.set_output("result", all(values) if values else False)


# ─────────────────────────────────────────────────────────────────────────────
# OR
# ─────────────────────────────────────────────────────────────────────────────

class OrNode(_MultiInputLogicNode):
    """At least one connected input must be truthy → True.  Output is False
    when no inputs are connected."""
    NODE_NAME    = "OR"
    PAINT_SYMBOL = "OR"

    def _compute(self) -> None:
        values = self._connected_values()
        self.set_output("result", any(values))


# ─────────────────────────────────────────────────────────────────────────────
# NOT
# ─────────────────────────────────────────────────────────────────────────────

class NotNode(NodeBase):
    """Logical NOT — inverts the truthiness of the input.
    Outputs True when input is disconnected (treat absent signal as False)."""
    NODE_NAME  = "NOT"
    NODE_GROUP = "Logic"
    PINS = [
        PinDescriptor("input",  PinDirection.INPUT,  PinType.ANY, default=False),
        PinDescriptor("result", PinDirection.OUTPUT, PinType.BOOL),
    ]
    MIN_WIDTH  = 130.0
    MIN_HEIGHT = 60.0

    def on_start(self) -> None:
        self._compute()

    def on_data_received(self, pin_name: str, value: Any) -> None:
        self._compute()

    def execute(self, trigger_pin: str) -> None:
        self._compute()

    def _compute(self) -> None:
        v = self.get_input("input")
        self.set_output("result", not bool(v) if v is not None else True)

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        painter.setPen(QColor("#ffb74d"))
        painter.setFont(QFont("Courier New", 12, QFont.Weight.Bold))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "NOT")
