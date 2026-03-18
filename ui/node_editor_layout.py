"""Layout helpers, rendering data structures, and visual constants for NodeEditorCanvas."""

import uuid
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional

from PyQt6.QtCore import QPointF, QRectF
from PyQt6.QtGui import QColor

from core.node_base import NodeBase
from core.types import PIN_COLORS, PinDescriptor, PinDirection, PinType


def _node_display_name(node_or_cls) -> str:
    """Return localized display name for a node instance or class."""
    if hasattr(node_or_cls, 'display_name'):
        return node_or_cls.display_name()
    return node_or_cls.NODE_NAME


# ── Visual constants ──────────────────────────────────────────────────────────
COL_BG              = QColor("#1a0a0f")
COL_GRID_MINOR      = QColor("#2a1018")
COL_GRID_MAJOR      = QColor("#3d1525")
COL_NODE_BG         = QColor("#220d14")
COL_NODE_BORDER     = QColor("#45072f")
COL_NODE_SEL_BORDER = QColor("#f95979")
COL_TITLE_TEXT      = QColor("#ffd0de")
COL_PIN_TEXT        = QColor("#c8889a")
COL_WIRE_SHADOW     = QColor("#00000080")

PIN_RADIUS    = 6.0
TITLE_H       = 28.0
DEVICE_SEL_H  = 24.0     # height of the device-selector pill row
ROW_H         = 22.0      # height of every row (pin, var-input, field)
ROW_PAD       = 2.0       # vertical gap between rows
ROW_MARGIN    = 6.0       # top/bottom padding inside body
NODE_RADIUS   = 8.0
GRID_MINOR    = 20
GRID_MAJOR    = 100
LABEL_W       = 58.0      # pixel width reserved for the left-side label in rows
FIELD_INSET   = 8.0       # horizontal inset for field pill from node edge

GROUP_TITLE_H  = 24.0
GROUP_RESIZE_H =  8.0    # corner resize-handle size
GROUP_MIN_W    = 150.0
GROUP_MIN_H    =  80.0


def _pin_color(pt: PinType) -> QColor:
    return QColor(PIN_COLORS.get(pt, "#90a4ae"))


# ── Row descriptors ───────────────────────────────────────────────────────────

class _RowKind(Enum):
    PIN        = auto()   # left pin, right pin (either may be None)
    VAR        = auto()   # variable-input pin row (pin circle + inline field)
    FIELD      = auto()   # editable field row (no pin circle)
    CUSTOM     = auto()   # paint_custom() zone


@dataclass
class _Row:
    kind:       _RowKind
    y:          float           # scene y of row top
    h:          float = ROW_H
    # PIN rows
    in_pin:     Optional[PinDescriptor] = None
    out_pin:    Optional[PinDescriptor] = None
    # VAR rows
    var_pin:    Optional[PinDescriptor] = None
    var_name:   str = ""
    var_type:   type = float
    # FIELD rows
    field_name: str = ""
    field_type: type = float
    # cached scene-y centre for pin circles
    pin_cy:     float = 0.0

    def __post_init__(self) -> None:
        self.pin_cy = self.y + self.h / 2


# ── Hit-test records ──────────────────────────────────────────────────────────

@dataclass
class RenderedPin:
    node_id:   str
    pin_name:  str
    pin_type:  PinType
    direction: PinDirection
    scene_pos: QPointF


@dataclass
class RenderedField:
    node_id:    str
    field_name: str
    field_type: type
    scene_rect: QRectF
    is_var:     bool = False   # True → call set_var_input; False → set_field


# ── Group ─────────────────────────────────────────────────────────────────────

@dataclass
class NodeGroup:
    group_id: str   = field(default_factory=lambda: str(uuid.uuid4()))
    name:     str   = "Group"
    x:        float = 0.0
    y:        float = 0.0
    width:    float = 240.0
    height:   float = 180.0
    color:    str   = "#1a4a7a"
    node_ids: set   = field(default_factory=set)

    def body_rect(self) -> QRectF:
        return QRectF(self.x, self.y, self.width, self.height)

    def title_rect(self) -> QRectF:
        return QRectF(self.x, self.y, self.width, GROUP_TITLE_H)

    def inner_rect(self) -> QRectF:
        return QRectF(self.x, self.y + GROUP_TITLE_H,
                      self.width, self.height - GROUP_TITLE_H)


# ── Layout builder ────────────────────────────────────────────────────────────

def _build_rows(node: NodeBase, body_top: float) -> list[_Row]:
    """
    Build the ordered row list for a node.

    Rules:
      1. Pair in-pins and out-pins side-by-side where possible.
         VAR_INPUT pins are pulled out of the pairing and get their own row.
      2. After all pin rows: one VAR row per VARIABLE_INPUT.
      3. After var rows: one FIELD row per EDITABLE_FIELD.
      4. If paint_custom requests extra height: a CUSTOM row at the bottom.
    """
    var_names = set(node.VARIABLE_INPUTS.keys())

    in_pins  = [p for p in node.PINS
                if p.direction == PinDirection.INPUT  and p.pin_type != PinType.TICK
                and p.name not in var_names]
    in_ticks = [p for p in node.PINS
                if p.direction == PinDirection.INPUT  and p.pin_type == PinType.TICK]
    out_pins = [p for p in node.PINS if p.direction == PinDirection.OUTPUT]

    # Pair inputs and outputs on the same row where possible
    n_paired = max(len(in_pins) + len(in_ticks), len(out_pins))
    all_in   = in_ticks + in_pins    # ticks first so they appear at top
    rows: list[_Row] = []
    y = body_top + ROW_MARGIN

    for i in range(n_paired):
        ip = all_in[i]  if i < len(all_in)  else None
        op = out_pins[i] if i < len(out_pins) else None
        r = _Row(kind=_RowKind.PIN, y=y, in_pin=ip, out_pin=op)
        rows.append(r)
        y += ROW_H + ROW_PAD

    # VAR rows (one per VARIABLE_INPUT)
    for vname, (vtype, _) in node.VARIABLE_INPUTS.items():
        vpin = next((p for p in node.PINS if p.name == vname), None)
        r = _Row(kind=_RowKind.VAR, y=y,
                 var_pin=vpin, var_name=vname, var_type=vtype)
        rows.append(r)
        y += ROW_H + ROW_PAD

    # FIELD rows
    for fname, (ftype, _) in node.EDITABLE_FIELDS.items():
        r = _Row(kind=_RowKind.FIELD, y=y, field_name=fname, field_type=ftype)
        rows.append(r)
        y += ROW_H + ROW_PAD

    # CUSTOM zone — only if node requests extra MIN_HEIGHT
    custom_budget = node.MIN_HEIGHT - 60.0
    if custom_budget > 0:
        r = _Row(kind=_RowKind.CUSTOM, y=y, h=max(custom_budget, 30.0))
        rows.append(r)

    return rows


def _device_sel_extra(node: NodeBase) -> float:
    """Return DEVICE_SEL_H when 2+ devices of this node's type are connected."""
    from core.device_node_base import DeviceNodeBase, get_instances
    if not isinstance(node, DeviceNodeBase) or not node.DEVICE_TYPE_KEY:
        return 0.0
    return DEVICE_SEL_H if len(get_instances(node.DEVICE_TYPE_KEY)) >= 2 else 0.0


def _node_total_height(node: NodeBase) -> float:
    extra = _device_sel_extra(node)
    rows  = _build_rows(node, TITLE_H + extra)
    if not rows:
        return TITLE_H + extra + ROW_MARGIN * 2
    last = rows[-1]
    return last.y + last.h + ROW_MARGIN


def _node_width(node: NodeBase) -> float:
    return max(node.MIN_WIDTH, 190.0)
