"""
NodeBase — abstract base class for every node in the graph.

HOW TO IMPLEMENT A NEW NODE
============================
1.  Subclass NodeBase in  /nodes/your_nodes.py
2.  Set class attributes:
        NODE_NAME    = "My Node"
        NODE_GROUP   = "Math"          # context-menu group
        NODE_VERSION = "1.0.0"
        PINS = [
            PinDescriptor("exec_in",  PinDirection.INPUT,  PinType.TICK),
            PinDescriptor("exec_out", PinDirection.OUTPUT, PinType.TICK),
            PinDescriptor("value",    PinDirection.INPUT,  PinType.FLOAT, default=0.0),
            PinDescriptor("result",   PinDirection.OUTPUT, PinType.FLOAT),
        ]
3.  Implement execute() and/or on_data_received() (see docstrings).
4.  For custom UI rendering override paint() — you receive a QPainter.
5.  For device nodes set DEVICE_TYPE_KEY and ICON_PATH.
6.  Drop the file into /nodes/ — auto-discovered at startup.

DATA FLOW
=========
Push model: when an output pin value changes, the runtime calls
push_data(pin_name, value) which propagates to all connected input pins.

TICK FLOW
=========
When a TICK wire fires, the runtime calls  tick(pin_name)  on the target node.
The node's execute() is then called.
"""
from __future__ import annotations

import abc
import logging
import uuid
from typing import Any, Callable, Optional, TYPE_CHECKING

from PyQt6.QtCore import QObject, pyqtSignal, QRectF, QPointF
from PyQt6.QtGui import QPainter, QColor

from core.types import PinDescriptor, PinDirection, PinType, PinType

if TYPE_CHECKING:
    from core.graph_runtime import GraphRuntime

log = logging.getLogger(__name__)


class NodeBase(QObject):
    """
    Abstract base for all graph nodes.

    Lifecycle
    ---------
    on_start()        Called once when the graph starts running.
    execute(pin)      Called every time a TICK arrives on *pin*.
    on_stop()         Called when the graph stops.

    Data I/O
    --------
    Read incoming data:   self.get_input(pin_name) → Any
    Push outgoing data:   self.set_output(pin_name, value)
    Fire a tick output:   self.fire_tick(pin_name)
    """

    # Qt signals
    node_changed = pyqtSignal()          # request UI repaint
    log_message  = pyqtSignal(str)

    # ── Override in subclasses ────────────────────────────────────────────────
    NODE_NAME:    str       = "Unnamed Node"
    NODE_GROUP:   str       = "Misc"
    NODE_VERSION: str       = "1.0.0"
    PINS:         list[PinDescriptor] = []

    # Inline-editable fields rendered inside the node body.
    # Format: { field_name: (python_type, default_value) }
    # Values are NOT connectable pins — they are node-local configuration.
    EDITABLE_FIELDS: dict[str, tuple[type, Any]] = {}

    # Variable inputs: pins that show an inline editor when NOT connected,
    # and display the live wired value (locked) when a wire IS connected.
    # Format: { pin_name: (python_type, default_value) }
    # The pin MUST also be declared in PINS as a normal INPUT pin.
    # Use get_var_input(pin_name) to read the effective value.
    VARIABLE_INPUTS: dict[str, tuple[type, Any]] = {}

    # For device-linked nodes
    DEVICE_TYPE_KEY: Optional[str] = None   # matches DeviceBase subclass name
    ICON_PATH:       Optional[str] = None

    # Visual sizing hint (canvas units); override for wider nodes
    MIN_WIDTH:  float = 180.0
    MIN_HEIGHT: float = 60.0

    # Optional hover tooltip shown when the user hovers over the node title bar.
    # Leave empty ("") to show nothing (tooltip not yet implemented in canvas,
    # placeholder for future use).
    NODE_TOOLTIP: str = ""

    # Custom title-bar gradient colour.  Leave empty to use the default palette.
    # Accepts any CSS hex colour, e.g. "#1a6b3a".  The gradient goes from this
    # colour at the top to a darker version at the bottom.
    NODE_TITLE_COLOR: str = ""

    # ─────────────────────────────────────────────────────────────────────────

    def __init__(
        self,
        node_id:   Optional[str] = None,
        parent:    Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self.node_id: str = node_id or str(uuid.uuid4())

        # Runtime position on canvas (scene coords)
        self.x: float = 0.0
        self.y: float = 0.0

        # Pin value store: pin_name → current value
        self._data: dict[str, Any] = {}

        # Callbacks injected by GraphRuntime
        self._push_cb:  Optional[Callable[[str, str, Any], None]] = None
        self._tick_cb:  Optional[Callable[[str, str], None]]      = None

        # Populate pin defaults
        for pin in self.PINS:
            if pin.default is not None:
                self._data[pin.name] = pin.default

        # Populate editable field defaults
        self._fields: dict[str, Any] = {
            name: default for name, (typ, default) in self.EDITABLE_FIELDS.items()
        }

        # Populate variable input defaults (used when pin is not wired)
        self._var_inputs: dict[str, Any] = {
            name: default for name, (typ, default) in self.VARIABLE_INPUTS.items()
        }

        # Runtime reference (set by GraphRuntime after construction)
        self._runtime: Optional["GraphRuntime"] = None

    # ── Public API (called by runtime / other nodes) ─────────────────────────

    def get_input(self, pin_name: str) -> Any:
        """Read the current value on an input pin."""
        return self._data.get(pin_name)

    def set_output(self, pin_name: str, value: Any) -> None:
        """Write an output pin and propagate the value downstream."""
        self._data[pin_name] = value
        if self._push_cb:
            self._push_cb(self.node_id, pin_name, value)

    def get_field(self, name: str) -> Any:
        """Read a node-local editable field value."""
        if name in self._fields:
            return self._fields[name]
        # Fallback to EDITABLE_FIELDS default
        if name in self.EDITABLE_FIELDS:
            return self.EDITABLE_FIELDS[name][1]
        return None

    def set_field(self, name: str, raw_value: str) -> None:
        """
        Set a field from a raw string (as typed by the user in the inline editor).
        Automatically coerces to the declared type.
        Emits node_changed to trigger a repaint.
        """
        if name not in self.EDITABLE_FIELDS:
            return
        typ, _ = self.EDITABLE_FIELDS[name]
        try:
            if typ is bool:
                coerced: Any = raw_value.strip().lower() in ("1", "true", "yes", "on")
            else:
                coerced = typ(raw_value)
        except (ValueError, TypeError):
            return   # silently ignore bad input
        self._fields[name] = coerced
        self.on_field_changed(name, coerced)
        self.node_changed.emit()

    def on_field_changed(self, name: str, value: Any) -> None:
        """Called after a field is changed via set_field(). Override to react."""

    # ── Variable inputs ────────────────────────────────────────────────────────

    def get_var_input(self, pin_name: str) -> Any:
        """
        Read a variable input pin's effective value:
        • If a wire is connected → return the live wired value from _data.
        • If not connected      → return the locally stored default from _var_inputs.
        """
        if self._is_var_input_connected(pin_name):
            return self._data.get(pin_name)
        return self._var_inputs.get(pin_name,
               self.VARIABLE_INPUTS.get(pin_name, (None, None))[1])

    def set_var_input(self, pin_name: str, raw_value: str) -> None:
        """
        Set the local default for a variable input (called by the inline editor
        in the canvas when the pin has no wire).  Coerces to declared type.
        """
        if pin_name not in self.VARIABLE_INPUTS:
            return
        typ, _ = self.VARIABLE_INPUTS[pin_name]
        try:
            if typ is bool:
                coerced: Any = raw_value.strip().lower() in ("1", "true", "yes", "on")
            else:
                coerced = typ(raw_value)
        except (ValueError, TypeError):
            return
        self._var_inputs[pin_name] = coerced
        self.on_var_input_changed(pin_name, coerced)
        self.node_changed.emit()

    def on_var_input_changed(self, pin_name: str, value: Any) -> None:
        """Called after a variable input default is changed. Override to react."""

    def _is_var_input_connected(self, pin_name: str) -> bool:
        """Check runtime for a wire going into this pin."""
        if self._runtime is None:
            return False
        return self._runtime.is_pin_connected(self.node_id, pin_name)

    def fire_tick(self, pin_name: str) -> None:
        """Send a TICK signal on an output tick-pin."""
        if self._tick_cb:
            self._tick_cb(self.node_id, pin_name)

    def receive_data(self, pin_name: str, value: Any, src_pin_type: "Optional[PinType]" = None) -> None:
        """
        Called by runtime when upstream pushes data to one of our input pins.
        Applies PIN_COERCIONS if the src and dst types differ (e.g. INT→FLOAT).
        """
        # Find declared dst pin type
        dst_pin_type: Optional[PinType] = None
        for pin in self.PINS:
            if pin.name == pin_name:
                dst_pin_type = pin.pin_type
                break

        coerced = value
        if src_pin_type is not None and dst_pin_type is not None and src_pin_type != dst_pin_type:
            from core.types import PIN_COERCIONS, PinType as _PT
            coerce_fn = PIN_COERCIONS.get((src_pin_type, dst_pin_type))
            if coerce_fn is not None:
                try:
                    coerced = coerce_fn(value)
                except (TypeError, ValueError):
                    coerced = value   # pass through on failure

        self._data[pin_name] = coerced
        self.on_data_received(pin_name, coerced)

    def receive_tick(self, pin_name: str) -> None:
        """Called by runtime when a TICK arrives on one of our input tick-pins."""
        self.execute(pin_name)

    # ── Abstract / override interface ────────────────────────────────────────

    def on_start(self) -> None:
        """Called once when graph execution starts. Override for init."""

    @abc.abstractmethod
    def execute(self, trigger_pin: str) -> None:
        """
        Core execution method. Called whenever a TICK arrives.
        *trigger_pin* identifies which tick input fired (allows multi-input nodes).

        Typical pattern:
            def execute(self, trigger_pin: str) -> None:
                value = self.get_input("value")
                result = value * 2
                self.set_output("result", result)
                self.fire_tick("exec_out")
        """

    def on_data_received(self, pin_name: str, value: Any) -> None:
        """
        Called whenever a data input pin receives a new value.
        Override if the node needs to react immediately to incoming data
        (e.g. a display node that updates its UI on every value push).
        Default implementation does nothing.
        """

    def on_stop(self) -> None:
        """Called when graph execution stops. Override for clean-up."""

    # ── State serialisation (for save/load) ──────────────────────────────────

    def get_state(self) -> dict[str, Any]:
        """
        Return serialisable node state (persisted in the JSON graph file).
        Saves both pin values and editable field values.
        Override to add extra fields; call super().get_state() first.
        """
        state: dict[str, Any] = {}
        for pin in self.PINS:
            if pin.direction == PinDirection.INPUT and pin.pin_type != PinType.TICK:
                state[pin.name] = self._data.get(pin.name, pin.default)
        # Persist editable fields under a namespaced key to avoid collisions
        if self._fields:
            state["__fields__"] = dict(self._fields)
        # Persist variable input local defaults
        if self._var_inputs:
            state["__var_inputs__"] = dict(self._var_inputs)
        return state

    def set_state(self, state: dict[str, Any]) -> None:
        """Restore state loaded from disk. Override alongside get_state()."""
        fields = state.pop("__fields__", {})
        for key, val in fields.items():
            if key in self.EDITABLE_FIELDS:
                self._fields[key] = val
        var_inputs = state.pop("__var_inputs__", {})
        for key, val in var_inputs.items():
            if key in self.VARIABLE_INPUTS:
                self._var_inputs[key] = val
        for key, val in state.items():
            self._data[key] = val

    # ── Visual / painting ────────────────────────────────────────────────────

    def bounding_rect(self) -> QRectF:
        """Override to report actual painted size (used by hit-testing)."""
        return QRectF(self.x, self.y, self.MIN_WIDTH, self.MIN_HEIGHT)

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        """
        Optional extra rendering inside the node body.
        *rect* is the inner content area (below the title bar).
        Called after the default node frame is drawn.

        Example — big counter display:
            def paint_custom(self, painter, rect):
                painter.setPen(QColor("#f95979"))
                painter.setFont(QFont("Courier New", 28, QFont.Weight.Bold))
                painter.drawText(rect, Qt.AlignmentFlag.AlignCenter,
                                 str(self._data.get("count", 0)))
        """

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _attach_runtime(
        self,
        runtime:  "GraphRuntime",
        push_cb:  Callable[[str, str, Any], None],
        tick_cb:  Callable[[str, str], None],
    ) -> None:
        self._runtime = runtime
        self._push_cb = push_cb
        self._tick_cb = tick_cb

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} id={self.node_id[:8]} name={self.NODE_NAME!r}>"
