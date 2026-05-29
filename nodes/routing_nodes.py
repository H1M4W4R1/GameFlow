"""
Routing nodes — Multiplexer (MUX) and Demultiplexer (DEMUX).

Design rules:
  • Both nodes are PURE DATA — no exec_in / exec_out.
  • Channel count is configurable (2–8) via the right-click context menu.
  • 'channel' pin is a VARIABLE_INPUT: inline-editable field AND wirable INT pin.
  • MUX:  N data inputs  → 1 output  (selected by channel index).
  • DEMUX: 1 data input  → N outputs (routed to the output at channel index;
           all other outputs receive None).
  • paint_custom() highlights the active channel in the node body.
"""
from __future__ import annotations

from typing import Any, Callable

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui  import QAction, QPainter, QColor, QFont
from PyQt6.QtWidgets import QMenu

from core.command_history import WireDeleteCmd
from core.localization import tr
from core.node_base import NodeBase
from core.types     import PinDescriptor, PinDirection, PinType

if False:
    from core.graph_runtime import GraphRuntime

_MIN_CHANNELS = 2
_MAX_CHANNELS = 8
_DEFAULT_CHANNELS = 4

_COLOR_ACTIVE = QColor("#f95979")


# ─────────────────────────────────────────────────────────────────────────────
# Shared base helpers
# ─────────────────────────────────────────────────────────────────────────────

class _RoutingNodeBase(NodeBase):
    """
    Common infrastructure for MUX / DEMUX.

    Subclasses provide:
        _build_pins(n)  → list[PinDescriptor]
        _compute()      → None
        _channel_pins() → list[str]   pin names that change with channel count
    """
    NODE_GROUP = "Logic/Routing"
    PINS: list[PinDescriptor] = []

    _DEFAULT_CHANNELS = _DEFAULT_CHANNELS

    def __init__(self, *args, **kwargs) -> None:
        # Build instance-level PINS and VARIABLE_INPUTS before super().__init__
        self.VARIABLE_INPUTS = {"channel": (int, 0)}
        self.PINS = self._build_pins(self._DEFAULT_CHANNELS)
        super().__init__(*args, **kwargs)
        self._channel_count: int = self._DEFAULT_CHANNELS

    # ── Abstract / override ──────────────────────────────────────────────────

    def _build_pins(self, n: int) -> list[PinDescriptor]:
        raise NotImplementedError

    def _compute(self) -> None:
        raise NotImplementedError

    def _channel_pin_names(self, count: int) -> list[str]:
        """Return pin names that are added/removed when channel count changes."""
        raise NotImplementedError

    # ── Public API for canvas ────────────────────────────────────────────────

    def get_channel_count(self) -> int:
        return self._channel_count

    def set_channel_count(self, n: int) -> None:
        n = max(_MIN_CHANNELS, min(_MAX_CHANNELS, int(n)))
        if n == self._channel_count:
            return
        self.PINS = self._build_pins(n)
        # Initialise data slots for any new pins
        for name in self._channel_pin_names(n):
            self._data.setdefault(name, None)
        # Drop data slots for removed pins
        keep = set(p.name for p in self.PINS)
        for k in list(self._data.keys()):
            if k not in keep and k.startswith(("in_", "out_")):
                self._data.pop(k, None)
        self._channel_count = n
        self._compute()
        self.node_changed.emit()

    def _get_context_menu(self, canvas: Any, menu: QMenu, field_hit: Any = None) -> None:
        ch_menu = QMenu(tr("ui.canvas.menu.channel_count"), menu)
        ch_menu.setStyleSheet(menu.styleSheet())
        current_ch = self.get_channel_count()
        for n_ch in range(_MIN_CHANNELS, _MAX_CHANNELS + 1):
            act = QAction(str(n_ch), ch_menu)
            act.setCheckable(True)
            act.setChecked(current_ch == n_ch)
            act.triggered.connect(lambda _checked, count=n_ch: self._set_channel_count(canvas, count))
            ch_menu.addAction(act)
        menu.addMenu(ch_menu)

    def _set_channel_count(self, canvas: Any, count: int) -> None:
        old_count = self.get_channel_count()
        if count == old_count:
            return
        is_mux = any(p.name.startswith("in_") for p in self.PINS
                     if p.direction.name == "INPUT")
        prefix = "in_" if is_mux else "out_"
        removed_pins = {f"{prefix}{i}" for i in range(count, old_count)}
        dead_wires = [
            w for w in canvas._runtime.wires.values()
            if (w.src_node == self.node_id and w.src_pin in removed_pins) or
               (w.dst_node == self.node_id and w.dst_pin in removed_pins)
        ]

        canvas._history.begin_macro(f"Set channel count -> {count}")
        for wire in dead_wires:
            canvas._runtime.remove_wire(wire.wire_id)
            canvas._history.push(WireDeleteCmd(canvas._runtime, wire))
        self.set_channel_count(count)
        canvas._history.end_macro()
        canvas.update()

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def on_start(self) -> None:
        self._compute()

    def on_data_received(self, pin_name: str, value: Any) -> None:
        self._compute()

    def on_var_input_changed(self, pin_name: str, value: Any) -> None:
        if pin_name == "channel":
            self._compute()

    def execute(self, trigger_pin: str) -> None:
        self._compute()

    # ── State serialisation ──────────────────────────────────────────────────

    def get_state(self) -> dict[str, Any]:
        state = super().get_state()
        state["__channel_count__"] = self._channel_count
        return state

    def set_state(self, state: dict[str, Any]) -> None:
        count = int(state.pop("__channel_count__", _DEFAULT_CHANNELS))
        count = max(_MIN_CHANNELS, min(_MAX_CHANNELS, count))
        # Rebuild PINS before super() restores pin values
        self.PINS = self._build_pins(count)
        self._channel_count = count
        super().set_state(state)

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _active_channel(self) -> int:
        ch = int(self.get_var_input("channel") or 0)
        if ch < 0:
            return 0
        return ch % self._channel_count


# ─────────────────────────────────────────────────────────────────────────────
# MUX  (N inputs → 1 output)
# ─────────────────────────────────────────────────────────────────────────────

class MuxNode(_RoutingNodeBase):
    """
    Multiplexer: selects one of N data inputs and forwards it to 'output'.
    'channel' (0-based) picks the active input.
    Inactive inputs are ignored.  Changing channel or any input immediately
    updates the output.
    """
    NODE_NAME  = "Multiplexer"
    MIN_WIDTH  = 190.0
    MIN_HEIGHT = 80.0

    def _build_pins(self, n: int) -> list[PinDescriptor]:
        pins: list[PinDescriptor] = [
            PinDescriptor("channel", PinDirection.INPUT,  PinType.INT, default=0,
                          tooltip="0-based index of the input to forward to output."),
        ]
        for i in range(n):
            pins.append(PinDescriptor(f"in_{i}", PinDirection.INPUT, PinType.ANY))
        pins.append(PinDescriptor("output", PinDirection.OUTPUT, PinType.ANY))
        return pins

    def _channel_pin_names(self, count: int) -> list[str]:
        return [f"in_{i}" for i in range(count)]

    def _compute(self) -> None:
        ch = self._active_channel()
        val = self.get_input(f"in_{ch}")
        self.set_output("output", val)

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        ch = self._active_channel()
        painter.setPen(_COLOR_ACTIVE)
        painter.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, f"CH{ch}")


# ─────────────────────────────────────────────────────────────────────────────
# DEMUX  (1 input → N outputs)
# ─────────────────────────────────────────────────────────────────────────────

class DemuxNode(_RoutingNodeBase):
    """
    Demultiplexer: routes 'input' to one of N outputs selected by 'channel'.
    All other outputs receive None (disconnected / zero).
    Changing channel or the input value immediately re-routes.
    """
    NODE_NAME  = "Demultiplexer"
    MIN_WIDTH  = 190.0
    MIN_HEIGHT = 80.0

    def _build_pins(self, n: int) -> list[PinDescriptor]:
        pins: list[PinDescriptor] = [
            PinDescriptor("input",   PinDirection.INPUT,  PinType.ANY),
            PinDescriptor("channel", PinDirection.INPUT,  PinType.INT, default=0,
                          tooltip="0-based index of the output to route input to."),
        ]
        for i in range(n):
            pins.append(PinDescriptor(f"out_{i}", PinDirection.OUTPUT, PinType.ANY))
        return pins

    def _channel_pin_names(self, count: int) -> list[str]:
        return [f"out_{i}" for i in range(count)]

    def _compute(self) -> None:
        ch  = self._active_channel()
        val = self.get_input("input")
        for i in range(self._channel_count):
            self.set_output(f"out_{i}", val if i == ch else None)

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        ch = self._active_channel()
        painter.setPen(_COLOR_ACTIVE)
        painter.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, f"CH{ch}")
