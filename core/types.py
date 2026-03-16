"""
Core types, enums, and typed data structures for SensoryFlow.
All inter-module data exchange should use these types.
"""
from __future__ import annotations
from enum import Enum, auto
from dataclasses import dataclass, field
from typing import Any, Optional, TYPE_CHECKING
import uuid

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# Device status
# ---------------------------------------------------------------------------

class DeviceStatus(Enum):
    CONNECTED    = "connected"     # green  – responding normally
    UNKNOWN      = "unknown"       # yellow – last command failed, retrying
    DISCONNECTED = "disconnected"  # gray   – 3 retries exhausted / never seen


# ---------------------------------------------------------------------------
# Port / connection descriptor
# ---------------------------------------------------------------------------

class PortKind(Enum):
    SERIAL    = "serial"
    BLE       = "ble"
    TCP       = "tcp"
    WEBSOCKET = "websocket"
    REST      = "rest"
    MOCK      = "mock"


@dataclass
class ConnectionDescriptor:
    """Everything needed to (re-)open a device connection."""
    kind: PortKind
    address: str                        # COM3, BT-MAC, host:port, URL …
    extra: dict[str, Any] = field(default_factory=dict)   # baud, service UUID, …

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind":    self.kind.value,
            "address": self.address,
            "extra":   self.extra,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ConnectionDescriptor":
        return cls(
            kind    = PortKind(d["kind"]),
            address = d["address"],
            extra   = d.get("extra", {}),
        )


# ---------------------------------------------------------------------------
# Node pin (socket) types
# ---------------------------------------------------------------------------

class PinDirection(Enum):
    INPUT  = auto()
    OUTPUT = auto()


class PinType(Enum):
    """Determines visual colour and compatibility rules."""
    TICK     = auto()   # execution flow (pink wire)
    FLOAT    = auto()   # float64
    INT      = auto()   # int64
    BOOL     = auto()   # bool
    STRING   = auto()   # str
    ANY      = auto()   # accepts/emits any data type
    VECTOR2D = auto()   # (x, y)
    VECTOR3D = auto()   # (x, y, z)
    VECTOR4D = auto()   # (x, y, z, w)
    COLOR    = auto()   # (r, g, b, a) 0–1 float
    DATETIME = auto()   # datetime-like (seconds since epoch or datetime)
    COYOTE_FRAME = auto()  # CoyoteWaveformFrame (intensity 0–1, frequency device range)


PIN_COLORS: dict[PinType, str] = {
    PinType.TICK:     "#f95979",
    PinType.FLOAT:    "#4fc3f7",
    PinType.INT:      "#aed581",
    PinType.BOOL:     "#ffb74d",
    PinType.STRING:   "#ce93d8",
    PinType.ANY:      "#90a4ae",
    PinType.VECTOR2D: "#81c784",
    PinType.VECTOR3D: "#66bb6a",
    PinType.VECTOR4D: "#4caf50",
    PinType.COLOR:    "#e57373",
    PinType.DATETIME: "#ba68c8",
    PinType.COYOTE_FRAME: "#b39ddb",
}

# Which PinTypes can connect to which.
# INT and FLOAT are mutually compatible — values are auto-coerced at receive time.
PIN_COMPATIBILITY: dict[PinType, set[PinType]] = {
    PinType.TICK:     {PinType.TICK},
    PinType.FLOAT:    {PinType.FLOAT, PinType.INT, PinType.ANY},
    PinType.INT:      {PinType.INT, PinType.FLOAT, PinType.ANY},
    PinType.BOOL:     {PinType.BOOL, PinType.ANY},
    PinType.STRING:   {PinType.STRING, PinType.ANY},
    PinType.ANY:      {PinType.FLOAT, PinType.INT, PinType.BOOL, PinType.STRING,
                       PinType.VECTOR2D, PinType.VECTOR3D, PinType.VECTOR4D,
                       PinType.COLOR, PinType.DATETIME, PinType.COYOTE_FRAME, PinType.ANY},
    PinType.VECTOR2D: {PinType.VECTOR2D, PinType.ANY},
    PinType.VECTOR3D: {PinType.VECTOR3D, PinType.ANY},
    PinType.VECTOR4D: {PinType.VECTOR4D, PinType.ANY},
    PinType.COLOR:    {PinType.COLOR, PinType.ANY},
    PinType.DATETIME: {PinType.DATETIME, PinType.ANY},
    PinType.COYOTE_FRAME: {PinType.COYOTE_FRAME, PinType.ANY},
}

# Auto-coercion applied in NodeBase.receive_data when src/dst types differ.
# Maps (src_type, dst_type) → coerce_fn
PIN_COERCIONS: dict[tuple[PinType, PinType], object] = {
    (PinType.INT,   PinType.FLOAT): float,
    (PinType.FLOAT, PinType.INT):   lambda v: int(round(float(v))),
    (PinType.BOOL,  PinType.INT):   int,
    (PinType.BOOL,  PinType.FLOAT): float,
    (PinType.INT,   PinType.ANY):   lambda v: v,
    (PinType.FLOAT, PinType.ANY):   lambda v: v,
}


@dataclass
class PinDescriptor:
    """
    Static declaration of a pin on a node.

    Fields
    ------
    tooltip : shown in the canvas when the user hovers over this pin's circle.
              Falls back to "<name>  [TYPE]" if empty.
              Use the @pin_tooltip decorator for multi-line / rich descriptions.
    """
    name:       str
    direction:  PinDirection
    pin_type:   PinType
    optional:   bool = False
    default:    Any  = None
    tooltip:    str  = ""       # hover text; auto-generated if empty


def pin_tooltip(description: str):
    """
    Decorator factory for adding rich tooltip text to a PinDescriptor inside
    a PINS list.  Because PINS is a list of dataclass instances (not defs),
    this is used as a standalone helper rather than a traditional decorator:

        PINS = [
            pin_tooltip("Trigger execution — fires when a tick arrives.")(
                PinDescriptor("exec_in", PinDirection.INPUT, PinType.TICK)
            ),
            PinDescriptor("value", PinDirection.INPUT, PinType.FLOAT),
        ]

    Or more simply, just set tooltip= directly:

        PinDescriptor("exec_in", PinDirection.INPUT, PinType.TICK,
                      tooltip="Trigger execution.")
    """
    def _apply(pin: PinDescriptor) -> PinDescriptor:
        pin.tooltip = description
        return pin
    return _apply


# ---------------------------------------------------------------------------
# Connection between two pins
# ---------------------------------------------------------------------------

@dataclass
class WireDescriptor:
    wire_id:    str = field(default_factory=lambda: str(uuid.uuid4()))
    src_node:   str = ""     # node_id
    src_pin:    str = ""     # pin name
    dst_node:   str = ""
    dst_pin:    str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "wire_id":  self.wire_id,
            "src_node": self.src_node,
            "src_pin":  self.src_pin,
            "dst_node": self.dst_node,
            "dst_pin":  self.dst_pin,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "WireDescriptor":
        return cls(**d)


# ---------------------------------------------------------------------------
# Saved graph on disk
# ---------------------------------------------------------------------------

@dataclass
class SavedNode:
    node_id:   str
    type_key:  str           # e.g. "builtin.Counter"
    x:         float
    y:         float
    state:     dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"node_id": self.node_id, "type_key": self.type_key,
                "x": self.x, "y": self.y, "state": self.state}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SavedNode":
        return cls(**d)


@dataclass
class SavedGraph:
    name:    str
    nodes:   list[SavedNode]          = field(default_factory=list)
    wires:   list[WireDescriptor]     = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name":  self.name,
            "nodes": [n.to_dict() for n in self.nodes],
            "wires": [w.to_dict() for w in self.wires],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SavedGraph":
        return cls(
            name  = d.get("name", "Untitled"),
            nodes = [SavedNode.from_dict(n) for n in d.get("nodes", [])],
            wires = [WireDescriptor.from_dict(w) for w in d.get("wires", [])],
        )
