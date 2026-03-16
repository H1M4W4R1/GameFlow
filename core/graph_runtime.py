"""
GraphRuntime — owns the tick loop, wire topology, and node execution.

The runtime runs in its own thread (10 ms tick).
All node execute() calls happen on that thread.
Qt signals are used to cross back into the UI thread.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Optional

from PyQt6.QtCore import QObject, pyqtSignal

from core.types import WireDescriptor, SavedGraph, SavedNode, PinType, PinDirection
from core.node_base import NodeBase

log = logging.getLogger(__name__)

TICK_INTERVAL_S: float = 0.010   # 10 ms


class GraphRuntime(QObject):
    """
    Manages:
        • node registry (node_id → NodeBase)
        • wire topology (source pin → list[dest pins])
        • background tick thread (10 ms)
        • push-data and fire-tick dispatch
    """

    tick_fired      = pyqtSignal()           # emitted every tick (for UI)
    node_added      = pyqtSignal(str)        # node_id
    node_removed    = pyqtSignal(str)        # node_id
    wire_added      = pyqtSignal(object)     # WireDescriptor
    wire_removed    = pyqtSignal(str)        # wire_id
    runtime_error   = pyqtSignal(str)        # error message
    runtime_warning = pyqtSignal(str)        # non-fatal warning (e.g. tick cycle)
    running_changed = pyqtSignal(bool)
    paused_changed  = pyqtSignal(bool)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._nodes:  dict[str, NodeBase]         = {}
        self._wires:  dict[str, WireDescriptor]   = {}

        # Topology cache: (node_id, pin_name) → list[(dst_node_id, dst_pin)]
        self._data_routes: dict[tuple[str, str], list[tuple[str, str]]] = {}
        self._tick_routes: dict[tuple[str, str], list[tuple[str, str]]] = {}
        # Reverse map: (dst_node_id, dst_pin) → (src_node_id, src_pin) | None
        # Used to answer "is this input pin connected?"
        self._dst_to_src:  dict[tuple[str, str], tuple[str, str]]       = {}

        self._running:     bool                    = False
        self._paused:      bool                    = False
        self._stop_event:  threading.Event         = threading.Event()
        self._pause_event: threading.Event         = threading.Event()
        self._tick_thread: Optional[threading.Thread] = None
        self._lock:        threading.Lock          = threading.Lock()
        # Per-thread re-entrance tracking for tick propagation (cycle guard)
        self._tick_local:  threading.local         = threading.local()

    # ── Node management ──────────────────────────────────────────────────────

    def add_node(self, node: NodeBase) -> None:
        with self._lock:
            node._attach_runtime(self, self._push_data, self._fire_tick)
            self._nodes[node.node_id] = node
        self.node_added.emit(node.node_id)

    def remove_node(self, node_id: str) -> None:
        with self._lock:
            # Remove all wires connected to this node
            dead_wires = [
                wid for wid, w in self._wires.items()
                if w.src_node == node_id or w.dst_node == node_id
            ]
            for wid in dead_wires:
                self._remove_wire_locked(wid)
            self._nodes.pop(node_id, None)
        self.node_removed.emit(node_id)

    def get_node(self, node_id: str) -> Optional[NodeBase]:
        return self._nodes.get(node_id)

    @property
    def nodes(self) -> dict[str, NodeBase]:
        return dict(self._nodes)

    # ── Wire management ──────────────────────────────────────────────────────

    def add_wire(self, wire: WireDescriptor) -> bool:
        """Returns False if the wire is invalid (type mismatch, missing pins)."""
        if not self._validate_wire(wire):
            return False
        with self._lock:
            self._wires[wire.wire_id] = wire
            self._rebuild_routes_locked()
            cycles = self._find_tick_cycles_locked()
        self.wire_added.emit(wire)
        if cycles:
            names = self._cycle_node_names(cycles[0])
            self.runtime_warning.emit(
                f"Tick cycle detected: {names} — execution will stop at re-entry"
            )
        return True

    def remove_wire(self, wire_id: str) -> None:
        with self._lock:
            self._remove_wire_locked(wire_id)
        self.wire_removed.emit(wire_id)

    @property
    def wires(self) -> dict[str, WireDescriptor]:
        return dict(self._wires)

    def is_pin_connected(self, node_id: str, pin_name: str) -> bool:
        """Return True if the given input pin has at least one wire going into it."""
        return (node_id, pin_name) in self._dst_to_src

    def get_connected_src(self, node_id: str, pin_name: str) -> Optional[tuple[str, str]]:
        """Return (src_node_id, src_pin) for a connected input pin, or None."""
        return self._dst_to_src.get((node_id, pin_name))

    # ── Execution ────────────────────────────────────────────────────────────

    def start(self) -> None:
        if self._running:
            return
        self._stop_event.clear()
        self._running = True
        for node in self._nodes.values():
            try:
                node.on_start()
            except Exception as exc:
                log.error("on_start error in %s: %s", node, exc)
        # Fire Start node outputs after all nodes are initialized, so downstream
        # nodes (e.g. Timer, Delay) are not reset after receiving the start tick.
        from nodes.flow_nodes import StartNode
        for node in self._nodes.values():
            if isinstance(node, StartNode):
                try:
                    self._fire_tick(node.node_id, "exec_out")
                except Exception as exc:
                    log.error("Start node fire error in %s: %s", node, exc)
        self._tick_thread = threading.Thread(
            target=self._tick_loop, name="GraphRuntime-tick", daemon=True
        )
        self._tick_thread.start()
        self.running_changed.emit(True)
        log.info("GraphRuntime started.")

    def stop(self) -> None:
        if not self._running:
            return
        self._stop_event.set()
        self._running = False
        if self._tick_thread:
            self._tick_thread.join(timeout=1.0)
        for node in self._nodes.values():
            try:
                node.on_stop()
            except Exception as exc:
                log.error("on_stop error in %s: %s", node, exc)
        self.running_changed.emit(False)
        log.info("GraphRuntime stopped.")

    def pause(self) -> None:
        """Pause the tick loop without stopping nodes (no on_stop() called)."""
        if self._running and not self._paused:
            self._paused = True
            self._pause_event.set()
            for node in self._nodes.values():
                try:
                    node.on_pause()
                except Exception as exc:
                    log.error("on_pause error in %s: %s", node, exc)
            self.paused_changed.emit(True)
            log.info("GraphRuntime paused.")

    def resume(self) -> None:
        """Resume a paused graph."""
        if self._running and self._paused:
            self._paused = False
            self._pause_event.clear()
            for node in self._nodes.values():
                try:
                    node.on_resume()
                except Exception as exc:
                    log.error("on_resume error in %s: %s", node, exc)
            self.paused_changed.emit(False)
            log.info("GraphRuntime resumed.")

    def toggle_pause(self) -> None:
        if self._paused:
            self.resume()
        else:
            self.pause()

    @property
    def is_paused(self) -> bool:
        return self._paused

    @property
    def is_running(self) -> bool:
        return self._running

    # ── Save / Load ──────────────────────────────────────────────────────────

    def to_saved_graph(self, name: str = "Untitled") -> SavedGraph:
        from core.device_node_base import _DEVICE_ALIASES
        nodes = [
            SavedNode(
                node_id  = n.node_id,
                type_key = _type_key(n),
                x        = n.x,
                y        = n.y,
                state    = n.get_state(),
            )
            for n in self._nodes.values()
        ]
        return SavedGraph(
            name           = name,
            nodes          = nodes,
            wires          = list(self._wires.values()),
            device_aliases = dict(_DEVICE_ALIASES),
        )

    # ── Internal ─────────────────────────────────────────────────────────────

    def _tick_loop(self) -> None:
        """Background thread: fires Tick nodes every 10 ms. Honours pause."""
        while not self._stop_event.is_set():
            if self._paused:
                time.sleep(0.05)   # lightweight poll while paused
                continue
            t_start = time.monotonic()
            self.tick_fired.emit()
            self._dispatch_tick_nodes()
            elapsed = time.monotonic() - t_start
            sleep_for = max(0.0, TICK_INTERVAL_S - elapsed)
            time.sleep(sleep_for)

    def _dispatch_tick_nodes(self) -> None:
        """
        Drive all clock-like nodes every 10 ms:
          TickNode, ConfigurableTickNode -> execute("tick")
          Any node with on_tick_check      -> call it (Delay, Timer, time sources)
        """
        from nodes.flow_nodes import TickNode, ConfigurableTickNode
        with self._lock:
            all_nodes = list(self._nodes.values())
        for node in all_nodes:
            try:
                if isinstance(node, (TickNode, ConfigurableTickNode)):
                    node.execute("tick")
                elif hasattr(node, "on_tick_check"):
                    node.on_tick_check()
            except Exception as exc:
                log.error("Tick dispatch error in %s: %s", node, exc)
                self.runtime_error.emit(str(exc))

    def _push_data(self, src_node_id: str, src_pin: str, value: Any) -> None:
        """Called by a node's set_output — propagate value to connected inputs."""
        key = (src_node_id, src_pin)
        destinations = self._data_routes.get(key, [])
        # Determine the source pin type for coercion
        src_node = self._nodes.get(src_node_id)
        src_pin_type = None
        if src_node:
            for pin in src_node.PINS:
                if pin.name == src_pin:
                    src_pin_type = pin.pin_type
                    break
        for dst_node_id, dst_pin in destinations:
            node = self._nodes.get(dst_node_id)
            if node:
                try:
                    node.receive_data(dst_pin, value, src_pin_type)
                except Exception as exc:
                    log.error("Data propagation error: %s", exc)

    def _fire_tick(self, src_node_id: str, src_pin: str) -> None:
        """Called by a node's fire_tick — propagate tick to connected tick inputs.

        A per-thread call stack guards against infinite loops caused by tick
        cycles in the graph.  If the same (node, pin) is seen a second time
        on the same call stack, propagation stops and an error is emitted.
        """
        # --- cycle / infinite-loop guard ---
        if not hasattr(self._tick_local, "stack"):
            self._tick_local.stack = set()
        call_key = (src_node_id, src_pin)
        if call_key in self._tick_local.stack:
            log.error("Infinite tick loop: %s:%s already firing", src_node_id, src_pin)
            self.runtime_error.emit(
                f"Infinite loop stopped: tick cycle at node {src_node_id[:8]}:{src_pin}"
            )
            return
        self._tick_local.stack.add(call_key)
        try:
            key = (src_node_id, src_pin)
            destinations = self._tick_routes.get(key, [])
            for dst_node_id, dst_pin in destinations:
                node = self._nodes.get(dst_node_id)
                if node:
                    try:
                        node.receive_tick(dst_pin)
                    except Exception as exc:
                        log.error("Tick propagation error: %s", exc)
                        self.runtime_error.emit(str(exc))
        finally:
            self._tick_local.stack.discard(call_key)

    def _validate_wire(self, wire: WireDescriptor) -> bool:
        src_node = self._nodes.get(wire.src_node)
        dst_node = self._nodes.get(wire.dst_node)
        if not src_node or not dst_node:
            return False

        src_pin = _find_pin(src_node, wire.src_pin, PinDirection.OUTPUT)
        dst_pin = _find_pin(dst_node, wire.dst_pin, PinDirection.INPUT)
        if not src_pin or not dst_pin:
            return False

        from core.types import PIN_COMPATIBILITY
        return dst_pin.pin_type in PIN_COMPATIBILITY.get(src_pin.pin_type, set())

    def _remove_wire_locked(self, wire_id: str) -> None:
        self._wires.pop(wire_id, None)
        self._rebuild_routes_locked()

    def _find_tick_cycles_locked(self) -> list[list[str]]:
        """Return a list of tick cycles (each cycle is a list of node_ids).
        Must be called with self._lock already held (uses self._tick_routes).
        Uses iterative DFS to avoid Python recursion limits.
        """
        # Build node-level adjacency from tick routes
        adj: dict[str, list[str]] = {}
        for (src_node, _src_pin), dests in self._tick_routes.items():
            for dst_node, _dst_pin in dests:
                adj.setdefault(src_node, [])
                if dst_node not in adj[src_node]:
                    adj[src_node].append(dst_node)

        WHITE, GRAY, BLACK = 0, 1, 2
        color: dict[str, int] = {nid: WHITE for nid in self._nodes}
        parent: dict[str, Optional[str]] = {nid: None for nid in self._nodes}
        cycles: list[list[str]] = []

        for start in list(self._nodes.keys()):
            if color.get(start, WHITE) != WHITE:
                continue
            # Iterative DFS using explicit stack of (node, iterator)
            stack: list[tuple[str, Any]] = [(start, iter(adj.get(start, [])))]
            color[start] = GRAY
            while stack:
                node, children = stack[-1]
                try:
                    child = next(children)
                    if color.get(child, WHITE) == GRAY:
                        # Back edge — reconstruct cycle path
                        cycle = [child]
                        cur = node
                        while cur != child:
                            cycle.append(cur)
                            cur = parent.get(cur) or cur
                            if cur in cycle:  # safety guard
                                break
                        cycle.reverse()
                        cycles.append(cycle)
                    elif color.get(child, WHITE) == WHITE:
                        color[child] = GRAY
                        parent[child] = node
                        stack.append((child, iter(adj.get(child, []))))
                except StopIteration:
                    color[node] = BLACK
                    stack.pop()

        return cycles

    def _cycle_node_names(self, cycle: list[str]) -> str:
        """Convert a list of node_ids to a readable name string."""
        parts = []
        for nid in cycle:
            node = self._nodes.get(nid)
            name = node.NODE_NAME if node else nid[:8]
            parts.append(name)
        return " → ".join(parts) + " → ..."

    def _rebuild_routes_locked(self) -> None:
        """Rebuild the (node, pin) → [(node, pin)] routing tables."""
        data_routes: dict[tuple[str, str], list[tuple[str, str]]] = {}
        tick_routes: dict[tuple[str, str], list[tuple[str, str]]] = {}

        for wire in self._wires.values():
            src_node = self._nodes.get(wire.src_node)
            if not src_node:
                continue
            src_pin_desc = _find_pin(src_node, wire.src_pin, PinDirection.OUTPUT)
            if not src_pin_desc:
                continue

            key = (wire.src_node, wire.src_pin)
            if src_pin_desc.pin_type == PinType.TICK:
                tick_routes.setdefault(key, []).append((wire.dst_node, wire.dst_pin))
            else:
                data_routes.setdefault(key, []).append((wire.dst_node, wire.dst_pin))

        self._data_routes = data_routes
        self._tick_routes = tick_routes

        # Rebuild reverse map
        dst_to_src: dict[tuple[str, str], tuple[str, str]] = {}
        for wire in self._wires.values():
            dst_to_src[(wire.dst_node, wire.dst_pin)] = (wire.src_node, wire.src_pin)
        self._dst_to_src = dst_to_src


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_pin(
    node: NodeBase,
    name: str,
    direction: PinDirection,
) -> Optional[Any]:
    for pin in node.PINS:
        if pin.name == name and pin.direction == direction:
            return pin
    return None


def _type_key(node: NodeBase) -> str:
    return f"{node.__class__.__module__}.{node.__class__.__name__}"
