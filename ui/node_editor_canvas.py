"""
NodeEditorCanvas — full node graph view.

Layout engine (fixes all overlap / missing-field issues):
─────────────────────────────────────────────────────────
Each node is built from a list of "rows" computed once per draw call:

  Row types:
    PIN_ROW      — a regular input or output pin (or both on same row)
    VAR_ROW      — a VARIABLE_INPUT pin: shows pin circle on left,
                   inline editable/locked field on right
    FIELD_ROW    — a plain EDITABLE_FIELD row (no pin)
    CUSTOM_ROW   — reserved space for paint_custom()

Rows are stacked top-to-bottom below the title bar with no overlap.
pin positions are derived from the same row list used for layout,
so hit-testing is always consistent.

Controls:
  LMB drag node        — move
  MMB drag             — pan
  Scroll wheel         — zoom
  LMB drag output pin  — start wire; release on input pin to connect
  RMB on canvas        — add node context menu (cascading by group)
  Double-click field   — inline editor (Enter commits, Escape cancels)
  Delete               — delete selected node
  Tab                  — cycle to next node
  Shift+Tab            — snap to origin
  Escape               — cancel wire / deselect
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional

from PyQt6.QtCore import Qt, QEvent, QObject, QPointF, QRectF, QPoint, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QAction, QBrush, QColor, QCursor, QFont, QKeyEvent, QLinearGradient,
    QMouseEvent, QPaintEvent, QPainter, QPainterPath, QPen,
    QRadialGradient, QWheelEvent,
)
from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
    QFrame, QLineEdit, QListWidget, QListWidgetItem,
    QMenu, QVBoxLayout, QWidget, QToolTip, QColorDialog, QSpinBox,
    QComboBox,
)

from core.localization import tr
from core.command_history import (
    CommandHistory,
    CtrlPropCmd,
    DeviceCycleCmd, DeviceSelectCmd,
    FieldEditCmd,
    GroupCreateCmd, GroupDeleteCmd, GroupMoveCmd, GroupResizeCmd, GroupRenameCmd,
    NodeAddCmd, NodeDeleteCmd, NodeMoveCmd, NodeRenameCmd,
    PasteCmd,
    WireAddCmd, WireDeleteCmd,
)
from core.graph_runtime import GraphRuntime
from core.node_base import NodeBase
from core.types import (
    PIN_COLORS, PIN_COMPATIBILITY, PinDescriptor,
    PinDirection, PinType, WireDescriptor,
)

log = logging.getLogger(__name__)


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
    DYN_FIELD  = auto()   # node-owned dynamic field row
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
    is_dynamic: bool = False
    dynamic_index: int = -1


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
    dynamic_pin_names: set[str] = set()
    for method_name in ("get_dynamic_output_pin_names", "get_dynamic_input_pin_names"):
        if hasattr(node, method_name):
            try:
                dynamic_pin_names.update(getattr(node, method_name)())
            except Exception:
                pass
    if hasattr(node, "get_dynamic_output_pin_names"):
        try:
            dynamic_pin_names.update(node.get_dynamic_output_pin_names())
        except Exception:
            pass

    in_pins  = [p for p in node.PINS
                if p.direction == PinDirection.INPUT  and p.pin_type != PinType.TICK
                and p.name not in var_names and p.name not in dynamic_pin_names]
    in_ticks = [p for p in node.PINS
                if p.direction == PinDirection.INPUT  and p.pin_type == PinType.TICK]
    out_pins = [p for p in node.PINS
                if p.direction == PinDirection.OUTPUT and p.name not in dynamic_pin_names]

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

    if hasattr(node, "get_dynamic_field_specs"):
        try:
            specs = node.get_dynamic_field_specs()
        except Exception:
            specs = []
        for spec in specs:
            idx, _value, pin_name = spec[:3]
            direction = spec[3] if len(spec) > 3 else PinDirection.OUTPUT
            pin_desc = next((p for p in node.PINS if p.name == pin_name), None)
            r = _Row(kind=_RowKind.DYN_FIELD, y=y, field_name=str(idx),
                     field_type=str)
            if direction == PinDirection.INPUT or str(direction).upper().endswith("INPUT"):
                r.in_pin = pin_desc
            else:
                r.out_pin = pin_desc
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


# ── Canvas ────────────────────────────────────────────────────────────────────

class NodeEditorCanvas(QWidget):
    wire_created      = pyqtSignal(object)
    node_selected     = pyqtSignal(str)
    status_message    = pyqtSignal(str)
    device_highlighted = pyqtSignal(object)   # Optional[str] — device_id or None

    def __init__(
        self,
        runtime:      GraphRuntime,
        node_menu_fn,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._runtime      = runtime
        self._node_menu_fn = node_menu_fn

        self._offset = QPointF(0, 0)
        self._zoom   = 1.0

        self._panning          = False
        self._pan_start        = QPointF()
        self._pan_offset_start = QPointF()

        self._dragging_node    : Optional[str]    = None
        self._drag_start_scene : QPointF          = QPointF()
        self._drag_node_start  : QPointF          = QPointF()
        self._selected_node    : Optional[str]    = None
        self._selected_nodes   : set              = set()   # multi-select set
        self._drag_nodes_start : dict             = {}      # {node_id: QPointF} for multi-drag

        self._rubber_band_active: bool    = False
        self._rubber_band_origin: QPointF = QPointF()   # view-space start
        self._rubber_band_cur   : QPointF = QPointF()   # view-space current

        self._wire_src   : Optional[RenderedPin]  = None
        self._wire_mouse : QPointF                = QPointF()

        self._rendered_pins   : list[RenderedPin]   = []
        self._rendered_fields : list[RenderedField] = []
        self._rendered_wires  : list[tuple[str, QPainterPath]] = []  # (wire_id, path)
        self._selected_wire   : Optional[str]       = None
        self._active_editor   : Optional[QLineEdit] = None
        self._clipboard       : Optional[dict] = None   # {"nodes": [...], "wires": [...]}

        self._tab_index = 0

        # Undo / redo history
        self._history: CommandHistory = CommandHistory()
        self._last_pasted_group_id: Optional[str] = None   # set by add_pasted_group

        # Device selector hit areas (node_id, scene_rect) — rebuilt each paint
        self._rendered_device_selectors: list[tuple[str, QRectF]] = []
        # Title bar hit areas (node_id, scene_rect) — rebuilt each paint
        self._rendered_title_bars: list[tuple[str, QRectF]] = []
        self._rendered_title_status: list[tuple[str, QRectF]] = []
        # Node highlighted by an in-progress device drag
        self._drag_highlight_node: Optional[str] = None

        # Active control-panel interaction (Slider, Button, Toggle, etc.)
        self._ctrl_node_id: Optional[str]   = None
        self._ctrl_rect:    Optional[QRectF] = None

        # ── Groups ────────────────────────────────────────────────────────────
        self._groups: dict[str, NodeGroup] = {}
        self._selected_group: Optional[str] = None

        self._dragging_group: Optional[str]    = None
        self._drag_group_start: QPointF        = QPointF()
        self._drag_group_pos_start: QPointF    = QPointF()
        self._drag_group_nodes_start: dict[str, QPointF] = {}

        self._resizing_group: Optional[str]    = None
        self._resize_corner: str               = ""
        self._resize_group_start: Optional[QRectF] = None
        self._resize_mouse_start: QPointF      = QPointF()

        # Group hit areas — rebuilt each paint
        self._rendered_group_title_bars:   list[tuple[str, QRectF]]        = []
        self._rendered_group_resize_handles: list[tuple[str, str, QRectF]] = []

        # Hover state for tooltips
        self._hovered_pin:  Optional[RenderedPin]  = None
        self._hovered_node: Optional[str]          = None
        self._hovered_title_status: Optional[str]  = None
        self._tooltip_timer = QTimer(self)
        self._tooltip_timer.setSingleShot(True)
        self._tooltip_timer.timeout.connect(self._show_hover_tooltip)
        self._last_mouse_view: QPointF = QPointF()

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setAcceptDrops(True)

        self._runtime.node_added.connect(lambda _: self.update())
        self._runtime.node_removed.connect(self._on_node_removed_from_groups)
        self._runtime.node_removed.connect(lambda _: self.update())
        self._runtime.wire_added.connect(lambda _: self.update())
        self._runtime.wire_removed.connect(lambda _: self.update())
        self._runtime.tick_fired.connect(self.update)

    # ── Coordinate helpers ────────────────────────────────────────────────────

    def _s2v(self, pt: QPointF) -> QPointF:
        return QPointF(pt.x() * self._zoom + self._offset.x(),
                       pt.y() * self._zoom + self._offset.y())

    def _v2s(self, pt: QPointF) -> QPointF:
        return QPointF((pt.x() - self._offset.x()) / self._zoom,
                       (pt.y() - self._offset.y()) / self._zoom)

    # ── Paint ─────────────────────────────────────────────────────────────────

    def paintEvent(self, event: QPaintEvent) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.fillRect(self.rect(), COL_BG)
        self._draw_grid(p)
        p.save()
        p.translate(self._offset)
        p.scale(self._zoom, self._zoom)
        self._draw_groups(p)
        self._rendered_pins.clear()
        self._rendered_fields.clear()
        self._rendered_device_selectors.clear()
        self._rendered_title_bars.clear()
        self._rendered_title_status.clear()
        for node in self._runtime.nodes.values():
            self._draw_node(p, node)
        self._draw_wires(p)
        if self._wire_src:
            self._draw_pending_wire(p)
        p.restore()
        if self._rubber_band_active:
            self._draw_rubber_band(p)

    # ── Grid ──────────────────────────────────────────────────────────────────

    def _draw_grid(self, p: QPainter) -> None:
        w, h = self.width(), self.height()
        for step, col in [
            (GRID_MINOR * self._zoom, COL_GRID_MINOR),
            (GRID_MAJOR * self._zoom, COL_GRID_MAJOR),
        ]:
            ox = self._offset.x() % step
            oy = self._offset.y() % step
            p.setPen(QPen(col, 1))
            x = ox
            while x < w:
                p.drawLine(int(x), 0, int(x), h); x += step
            y = oy
            while y < h:
                p.drawLine(0, int(y), w, int(y)); y += step

    def _draw_rubber_band(self, p: QPainter) -> None:
        """Draw the rubber-band selection rectangle in view (widget) coordinates."""
        ox, oy = self._rubber_band_origin.x(), self._rubber_band_origin.y()
        cx, cy = self._rubber_band_cur.x(),    self._rubber_band_cur.y()
        rect = QRectF(min(ox, cx), min(oy, cy), abs(cx - ox), abs(cy - oy))
        if rect.width() < 2 and rect.height() < 2:
            return
        p.setPen(QPen(QColor("#f95979"), 1, Qt.PenStyle.DashLine))
        p.setBrush(QBrush(QColor(249, 89, 121, 30)))
        p.drawRect(rect)

    # ── Groups ────────────────────────────────────────────────────────────────

    def _draw_groups(self, p: QPainter) -> None:
        self._rendered_group_title_bars.clear()
        self._rendered_group_resize_handles.clear()
        for grp in self._groups.values():
            self._draw_group(p, grp)

    def _draw_group(self, p: QPainter, grp: NodeGroup) -> None:
        selected = grp.group_id == self._selected_group
        base = QColor(grp.color)
        rect = grp.body_rect()

        # Shadow
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(0, 0, 0, 40)))
        p.drawRoundedRect(rect.adjusted(4, 4, 4, 4), 10, 10)

        # Body fill + border
        fill_a  = 45 if selected else 25
        pen_a   = 200 if selected else 110
        pen_w   = 2.0 if selected else 1.5
        pen_sty = Qt.PenStyle.SolidLine if selected else Qt.PenStyle.DashLine
        p.setBrush(QBrush(QColor(base.red(), base.green(), base.blue(), fill_a)))
        p.setPen(QPen(QColor(base.red(), base.green(), base.blue(), pen_a), pen_w, pen_sty))
        p.drawRoundedRect(rect, 10, 10)

        # Title bar (rounded top, straight bottom)
        tr = grp.title_rect()
        tp = QPainterPath()
        tp.addRoundedRect(tr, 10, 10)
        tp.addRect(QRectF(grp.x, grp.y + 6, grp.width, GROUP_TITLE_H - 6))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(base.red(), base.green(), base.blue(), 90)))
        p.drawPath(tp)

        # Group name
        p.setPen(QColor("#ffd0de"))
        p.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        p.drawText(
            QRectF(grp.x + 10, grp.y, grp.width - 20, GROUP_TITLE_H),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            grp.name,
        )

        # Register title bar for hit-testing
        self._rendered_group_title_bars.append((grp.group_id, QRectF(tr)))

        # Corner resize handles
        h = GROUP_RESIZE_H
        hc = QColor(base.red(), base.green(), base.blue(), 180)
        hf = QColor(base.red(), base.green(), base.blue(), 50)
        for corner, cx, cy in [
            ("nw", grp.x,                  grp.y),
            ("ne", grp.x + grp.width - h,  grp.y),
            ("sw", grp.x,                  grp.y + grp.height - h),
            ("se", grp.x + grp.width - h,  grp.y + grp.height - h),
        ]:
            hr = QRectF(cx, cy, h, h)
            p.setPen(QPen(hc, 1.5))
            p.setBrush(QBrush(hf))
            p.drawRect(hr)
            self._rendered_group_resize_handles.append((grp.group_id, corner, hr))

    # ── Node ──────────────────────────────────────────────────────────────────

    def _draw_node(self, p: QPainter, node: NodeBase) -> None:
        selected  = node.node_id == self._selected_node or node.node_id in self._selected_nodes
        drag_hl   = node.node_id == self._drag_highlight_node
        width     = _node_width(node)
        extra     = _device_sel_extra(node)
        body_top  = node.y + TITLE_H + extra
        rows      = _build_rows(node, body_top)
        total_h   = _node_total_height(node)
        rect      = QRectF(node.x, node.y, width, total_h)

        # Shadow
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(0, 0, 0, 80)))
        p.drawRoundedRect(rect.adjusted(4, 4, 4, 4), NODE_RADIUS, NODE_RADIUS)

        # Body
        if drag_hl:
            border_col = QColor("#00e5ff")
            border_w   = 2
        elif selected:
            border_col = COL_NODE_SEL_BORDER
            border_w   = 2
        else:
            border_col = COL_NODE_BORDER
            border_w   = 1
        p.setPen(QPen(border_col, border_w))
        p.setBrush(QBrush(QColor("#220d1430" if selected else "#220d14")))
        p.drawRoundedRect(rect, NODE_RADIUS, NODE_RADIUS)

        # Title bar
        title_rect = QRectF(node.x, node.y, width, TITLE_H)
        tp = QPainterPath()
        tp.setFillRule(Qt.FillRule.WindingFill)
        tp.addRoundedRect(title_rect, NODE_RADIUS, NODE_RADIUS)
        tp.addRect(QRectF(node.x, node.y + NODE_RADIUS, width, TITLE_H - NODE_RADIUS))
        grad = QLinearGradient(title_rect.topLeft(), title_rect.bottomLeft())
        _tc = node.NODE_TITLE_COLOR.strip() if node.NODE_TITLE_COLOR else ""
        if _tc:
            _base = QColor(_tc)
            grad.setColorAt(0, _base)
            grad.setColorAt(1, _base.darker(160))
        else:
            grad.setColorAt(0, QColor("#c90084"))
            grad.setColorAt(1, QColor("#45072f"))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(grad))
        p.drawPath(tp)

        p.setPen(COL_TITLE_TEXT)
        p.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        p.drawText(
            QRectF(node.x + PIN_RADIUS + 6, node.y, width - PIN_RADIUS * 2 - 12, TITLE_H),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            node.custom_name or _node_display_name(node.__class__),
        )
        self._rendered_title_bars.append((node.node_id, QRectF(title_rect)))

        # Device status dot + optional selector row
        from core.device_node_base import DeviceNodeBase
        if isinstance(node, DeviceNodeBase):
            node.paint_device_status(p, title_rect)
            if extra:
                sel_rect = QRectF(node.x, node.y + TITLE_H, width, DEVICE_SEL_H)
                self._draw_device_selector(p, node, sel_rect)
        elif hasattr(node, "paint_title_status"):
            try:
                node.paint_title_status(p, title_rect)
                self._rendered_title_status.append(
                    (node.node_id, self._title_status_rect(title_rect))
                )
            except Exception:
                pass

        # Draw each row
        for row in rows:
            if row.kind == _RowKind.PIN:
                self._draw_pin_row(p, node, row, width)
            elif row.kind == _RowKind.VAR:
                self._draw_var_row(p, node, row, width)
            elif row.kind == _RowKind.FIELD:
                self._draw_field_row(p, node, row, width)
            elif row.kind == _RowKind.DYN_FIELD:
                self._draw_dynamic_field_row(p, node, row, width)
            elif row.kind == _RowKind.CUSTOM:
                custom_rect = QRectF(node.x + 4, row.y, width - 8, row.h)
                try:
                    node.paint_custom(p, custom_rect)
                except Exception:
                    pass

        # Selection glow
        if selected:
            glow = QRadialGradient(rect.center(), max(width, total_h) * 0.7)
            glow.setColorAt(0.7, QColor(0, 0, 0, 0))
            glow.setColorAt(1.0, QColor("#f9597920"))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(glow))
            p.drawRoundedRect(rect.adjusted(-6, -6, 6, 6), NODE_RADIUS + 4, NODE_RADIUS + 4)

    def _draw_pin_row(self, p: QPainter, node: NodeBase, row: _Row, width: float) -> None:
        cy = row.y + row.h / 2

        if row.in_pin:
            pin   = row.in_pin
            px    = node.x
            color = _pin_color(pin.pin_type)
            p.setPen(QPen(color.darker(140), 1.5))
            p.setBrush(QBrush(color))
            p.drawEllipse(QPointF(px, cy), PIN_RADIUS, PIN_RADIUS)
            self._rendered_pins.append(
                RenderedPin(node.node_id, pin.name, pin.pin_type,
                            PinDirection.INPUT, QPointF(px, cy))
            )
            p.setPen(COL_PIN_TEXT)
            p.setFont(QFont("Segoe UI", 8))
            p.drawText(
                QRectF(node.x + PIN_RADIUS + 4, row.y, width / 2 - PIN_RADIUS - 6, row.h),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                pin.name,
            )

        if row.out_pin:
            pin   = row.out_pin
            px    = node.x + width
            color = _pin_color(pin.pin_type)
            p.setPen(QPen(color.darker(140), 1.5))
            p.setBrush(QBrush(color))
            p.drawEllipse(QPointF(px, cy), PIN_RADIUS, PIN_RADIUS)
            self._rendered_pins.append(
                RenderedPin(node.node_id, pin.name, pin.pin_type,
                            PinDirection.OUTPUT, QPointF(px, cy))
            )
            p.setPen(COL_PIN_TEXT)
            p.setFont(QFont("Segoe UI", 8))
            p.drawText(
                QRectF(node.x + width / 2, row.y, width / 2 - PIN_RADIUS - 6, row.h),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                pin.name,
            )

    def _draw_var_row(self, p: QPainter, node: NodeBase, row: _Row, width: float) -> None:
        """
        Variable-input row: pin circle on the left edge, field pill on the right.
        When connected  → field shows live value, locked (dimmed).
        When free       → field shows local default, editable (bright border).
        """
        cy        = row.y + row.h / 2
        connected = self._runtime.is_pin_connected(node.node_id, row.var_name)
        val       = node.get_var_input(row.var_name)

        # Pin circle (always visible so users can wire it)
        if row.var_pin:
            px    = node.x
            color = _pin_color(row.var_pin.pin_type)
            p.setPen(QPen(color.darker(140), 1.5))
            p.setBrush(QBrush(color))
            p.drawEllipse(QPointF(px, cy), PIN_RADIUS, PIN_RADIUS)
            self._rendered_pins.append(
                RenderedPin(node.node_id, row.var_name, row.var_pin.pin_type,
                            PinDirection.INPUT, QPointF(px, cy))
            )

        # Field pill
        pill_x   = node.x + PIN_RADIUS * 2 + 4
        pill_w   = width - PIN_RADIUS * 2 - 8
        pill_rect = QRectF(pill_x, row.y + 1, pill_w, row.h - 2)

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor("#1e0d18" if connected else "#2d1020")))
        p.drawRoundedRect(pill_rect, 4, 4)
        border_col = QColor("#4a2030") if connected else QColor("#f95979")
        p.setPen(QPen(border_col, 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(pill_rect, 4, 4)

        # Label
        label = row.var_name.replace("_", " ")
        p.setPen(QColor("#5a3040" if connected else "#9a5070"))
        p.setFont(QFont("Segoe UI", 7))
        p.drawText(
            QRectF(pill_rect.x() + 4, row.y, LABEL_W, row.h),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            label,
        )

        # Value
        display, val_color = _format_value(val, row.var_type, dim=connected)
        if connected:
            display += " 🔒"
        p.setPen(val_color)
        p.setFont(QFont("Courier New", 8 if connected else 9,
                        QFont.Weight.Normal if connected else QFont.Weight.Bold))
        p.drawText(
            QRectF(pill_rect.x() + LABEL_W + 2, row.y,
                   pill_w - LABEL_W - 6, row.h),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
            display,
        )

        if not connected:
            self._rendered_fields.append(
                RenderedField(node.node_id, row.var_name, row.var_type, pill_rect, is_var=True)
            )

    def _draw_field_row(self, p: QPainter, node: NodeBase, row: _Row, width: float) -> None:
        """Plain editable field row — no pin circle."""
        val = node.get_field(row.field_name)

        pill_rect = QRectF(node.x + FIELD_INSET, row.y + 1,
                           width - FIELD_INSET * 2, row.h - 2)

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor("#2d1020")))
        p.drawRoundedRect(pill_rect, 4, 4)
        p.setPen(QPen(QColor("#6b3050"), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(pill_rect, 4, 4)

        label = row.field_name.replace("_", " ")
        p.setPen(QColor("#7a4060"))
        p.setFont(QFont("Segoe UI", 7))
        p.drawText(
            QRectF(pill_rect.x() + 4, row.y, LABEL_W, row.h),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            label,
        )

        display, val_color = _format_value(val, row.field_type, dim=False)
        p.setPen(val_color)
        p.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        p.drawText(
            QRectF(pill_rect.x() + LABEL_W + 2, row.y,
                   pill_rect.width() - LABEL_W - 6, row.h),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
            display,
        )

        self._rendered_fields.append(
            RenderedField(node.node_id, row.field_name, row.field_type, pill_rect, is_var=False)
        )

    def _draw_dynamic_field_row(self, p: QPainter, node: NodeBase, row: _Row, width: float) -> None:
        """Node-owned dynamic text field with one optional output pin on the right."""
        try:
            idx = int(row.field_name)
            value = node.get_dynamic_field_value(idx)
        except Exception:
            idx = -1
            value = ""

        if row.in_pin:
            cy    = row.y + row.h / 2
            px    = node.x
            color = _pin_color(row.in_pin.pin_type)
            p.setPen(QPen(color.darker(140), 1.5))
            p.setBrush(QBrush(color))
            p.drawEllipse(QPointF(px, cy), PIN_RADIUS, PIN_RADIUS)
            self._rendered_pins.append(
                RenderedPin(node.node_id, row.in_pin.name, row.in_pin.pin_type,
                            PinDirection.INPUT, QPointF(px, cy))
            )

        output_label_w = 78.0 if row.out_pin else 0.0
        input_offset = PIN_RADIUS * 2 + 4 if row.in_pin else 0.0
        pill_rect = QRectF(
            node.x + FIELD_INSET + input_offset,
            row.y + 1,
            max(70.0, width - FIELD_INSET * 2 - input_offset - (PIN_RADIUS * 2) - output_label_w),
            row.h - 2,
        )

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor("#2d1020")))
        p.drawRoundedRect(pill_rect, 4, 4)
        p.setPen(QPen(QColor("#6b3050"), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(pill_rect, 4, 4)

        display = str(value or "")
        p.setPen(QColor("#ffd0de" if display else "#7a4060"))
        p.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        p.drawText(
            pill_rect.adjusted(6, 0, -6, 0),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            display,
        )

        self._rendered_fields.append(
            RenderedField(node.node_id, row.field_name, str, pill_rect,
                          is_var=False, is_dynamic=True, dynamic_index=idx)
        )

        if row.out_pin:
            cy    = row.y + row.h / 2
            px    = node.x + width
            color = _pin_color(row.out_pin.pin_type)
            p.setPen(QPen(color.darker(140), 1.5))
            p.setBrush(QBrush(color))
            p.drawEllipse(QPointF(px, cy), PIN_RADIUS, PIN_RADIUS)
            self._rendered_pins.append(
                RenderedPin(node.node_id, row.out_pin.name, row.out_pin.pin_type,
                            PinDirection.OUTPUT, QPointF(px, cy))
            )
            p.setPen(COL_PIN_TEXT)
            p.setFont(QFont("Segoe UI", 8))
            p.drawText(
                QRectF(node.x + width - PIN_RADIUS - output_label_w, row.y,
                       output_label_w - 6, row.h),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                row.out_pin.name,
            )

    def _draw_device_selector(self, p: QPainter, node: NodeBase, rect: QRectF) -> None:
        """Paint the device-selector pill row below the title bar."""
        from core.device_node_base import DeviceNodeBase, get_device_alias
        if not isinstance(node, DeviceNodeBase):
            return

        # Background band
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor("#1e0810")))
        p.drawRect(rect)

        # Top separator line
        p.setPen(QPen(QColor("#45072f"), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawLine(rect.topLeft(), rect.topRight())

        # Status dot
        _status_colors = {"CONNECTED": "#4caf50", "UNKNOWN": "#ffb300",
                          "DISCONNECTED": "#616161"}
        dot_r  = 4.0
        cy     = rect.center().y()
        dot_cx = rect.left() + 10.0
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(_status_colors.get(node.device_status().name, "#616161"))))
        p.drawEllipse(QPointF(dot_cx, cy), dot_r, dot_r)

        # Alias text
        dev   = node.get_device()
        alias = get_device_alias(dev) if dev else "—"
        if len(alias) > 15:
            alias = alias[:12] + "…"
        p.setPen(QColor("#ffd0de"))
        p.setFont(QFont("Segoe UI", 8))
        p.drawText(
            QRectF(rect.left() + 20.0, rect.top(), rect.width() - 34.0, rect.height()),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            alias,
        )

        # Chevron ▾
        p.setPen(QColor("#c8889a"))
        p.setFont(QFont("Segoe UI", 9))
        p.drawText(
            QRectF(rect.right() - 16.0, rect.top(), 14.0, rect.height()),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignCenter,
            "▾",
        )

        # Register for hit testing
        self._rendered_device_selectors.append((node.node_id, QRectF(rect)))

    # ── Wire drawing ──────────────────────────────────────────────────────────

    def _draw_wires(self, p: QPainter) -> None:
        p.setBrush(Qt.BrushStyle.NoBrush)
        self._rendered_wires.clear()
        for wire in self._runtime.wires.values():
            sp = self._find_pin_pos(wire.src_node, wire.src_pin)
            dp = self._find_pin_pos(wire.dst_node, wire.dst_pin)
            if sp and dp:
                selected   = wire.wire_id == self._selected_wire
                self_loop  = wire.src_node == wire.dst_node
                if self_loop:
                    path = self._make_self_loop_path(sp.scene_pos, dp.scene_pos,
                                                     wire.src_node)
                else:
                    path = self._make_bezier_path(sp.scene_pos, dp.scene_pos)
                self._rendered_wires.append((wire.wire_id, path))
                self._draw_wire_path(p, path, sp.pin_type,
                                     alpha=240 if selected else 220,
                                     width=3.5 if selected else 2.5,
                                     highlight=selected)

    def _make_bezier_path(self, p1: QPointF, p2: QPointF) -> QPainterPath:
        dx   = abs(p2.x() - p1.x()) * 0.5 + 40
        path = QPainterPath(p1)
        path.cubicTo(QPointF(p1.x() + dx, p1.y()),
                     QPointF(p2.x() - dx, p2.y()), p2)
        return path

    def _make_self_loop_path(self, p1: QPointF, p2: QPointF,
                               node_id: str) -> QPainterPath:
        """
        Route a self-loop wire cleanly around the outside of the node.

        The wire exits the right edge of the output pin, curves down and
        around below the node, then enters the left edge at the input pin.
        This avoids the wire passing through the node body.

        Layout:
                  [OUTPUT pin] ──► ctrl1
                                       │
                                  (arc below node)
                                       │
                  [INPUT  pin] ◄── ctrl2
        """
        node = self._runtime.get_node(node_id)
        if node is None:
            return self._make_bezier_path(p1, p2)

        nw   = _node_width(node)
        nh   = _node_total_height(node)
        # Bottom-centre of node in scene coords
        bot_y   = node.y + nh + 24      # 24 px clearance below node
        right_x = node.x + nw + 32      # 32 px clearance to the right

        path = QPainterPath(p1)
        path.cubicTo(
            QPointF(right_x,     p1.y()),       # ctrl1: swing right from output
            QPointF(right_x,     bot_y),         # ctrl2: drop below node
            QPointF((p1.x() + p2.x()) / 2, bot_y),  # mid-bottom
        )
        path.cubicTo(
            QPointF(node.x - 24, bot_y),         # ctrl3: come back from left
            QPointF(node.x - 24, p2.y()),         # ctrl4: rise to input height
            p2,
        )
        return path

    def _draw_wire_path(self, p: QPainter, path: QPainterPath,
                        pt: PinType, alpha: int = 220,
                        width: float = 2.5, highlight: bool = False) -> None:
        col = _pin_color(pt)
        col.setAlpha(alpha)
        p.setPen(QPen(COL_WIRE_SHADOW, width + 2)); p.drawPath(path)
        if highlight:
            glow = QColor("#f95979"); glow.setAlpha(80)
            p.setPen(QPen(glow, width + 6)); p.drawPath(path)
        p.setPen(QPen(col, width)); p.drawPath(path)

    def _draw_pending_wire(self, p: QPainter) -> None:
        if self._wire_src:
            path = self._make_bezier_path(self._wire_src.scene_pos, self._wire_mouse)
            self._draw_wire_path(p, path, self._wire_src.pin_type, alpha=160, width=2.0)

    # ── Hit testing ───────────────────────────────────────────────────────────

    def _hit_pin(self, sp: QPointF) -> Optional[RenderedPin]:
        for rp in self._rendered_pins:
            dx = rp.scene_pos.x() - sp.x()
            dy = rp.scene_pos.y() - sp.y()
            if dx*dx + dy*dy <= (PIN_RADIUS + 3)**2:
                return rp
        return None

    def _hit_field(self, sp: QPointF) -> Optional[RenderedField]:
        for rf in self._rendered_fields:
            if rf.scene_rect.contains(sp):
                return rf
        return None

    def _hit_node(self, sp: QPointF) -> Optional[str]:
        for node in reversed(list(self._runtime.nodes.values())):
            w = _node_width(node)
            h = _node_total_height(node)
            if QRectF(node.x, node.y, w, h).contains(sp):
                return node.node_id
        return None

    def _hit_device_selector(self, sp: QPointF) -> Optional[str]:
        """Return node_id if sp is inside a device-selector pill row."""
        for node_id, rect in self._rendered_device_selectors:
            if rect.contains(sp):
                return node_id
        return None

    def _hit_ctrl(self, sp: QPointF) -> Optional[tuple]:
        """Return (node_id, ctrl_rect) if sp falls inside a node's CUSTOM row."""
        for node in self._runtime.nodes.values():
            extra    = _device_sel_extra(node)
            body_top = node.y + TITLE_H + extra
            rows     = _build_rows(node, body_top)
            width    = _node_width(node)
            for row in rows:
                if row.kind == _RowKind.CUSTOM:
                    rect = QRectF(node.x + 4, row.y, width - 8, row.h)
                    if rect.contains(sp):
                        return (node.node_id, rect)
        return None

    def _hit_title_bar(self, sp: QPointF) -> Optional[str]:
        """Return node_id if sp is inside a node title bar."""
        for node_id, rect in self._rendered_title_bars:
            if rect.contains(sp):
                return node_id
        return None

    def _hit_title_status(self, sp: QPointF) -> Optional[str]:
        """Return node_id if sp is inside a node's title status icon."""
        for node_id, rect in self._rendered_title_status:
            if rect.contains(sp):
                return node_id
        return None

    def _title_status_rect(self, title_rect: QRectF) -> QRectF:
        dot_d = 10.0
        return QRectF(
            title_rect.right() - dot_d - 4,
            title_rect.top() + (title_rect.height() - dot_d) / 2,
            dot_d,
            dot_d,
        )

    def _hit_group_title(self, sp: QPointF) -> Optional[str]:
        """Return group_id if sp is inside a group title bar."""
        for gid, rect in self._rendered_group_title_bars:
            if rect.contains(sp):
                return gid
        return None

    def _hit_group_resize(self, sp: QPointF) -> Optional[tuple]:
        """Return (group_id, corner) if sp is on a resize handle."""
        for gid, corner, rect in self._rendered_group_resize_handles:
            if rect.contains(sp):
                return gid, corner
        return None

    def _show_device_menu(self, node: NodeBase, instances: list,
                          global_pos: QPoint) -> None:
        """Pop up a QMenu to choose a device for this node."""
        from core.device_node_base import DeviceNodeBase, get_device_alias
        if not isinstance(node, DeviceNodeBase):
            return
        current_dev = node.get_device()
        current_id  = current_dev.device_id if current_dev else ""
        menu = QMenu(self)
        menu.setStyleSheet(_MENU_STYLE)
        for dev in instances:
            alias = get_device_alias(dev)
            a = QAction(alias, menu)
            a.setCheckable(True)
            a.setChecked(dev.device_id == current_id)
            a.triggered.connect(
                lambda _checked, did=dev.device_id, n=node, oid=current_id:
                    self._on_device_select(n, oid, did)
            )
            menu.addAction(a)
        menu.exec(global_pos)

    def _on_device_select(self, node, old_device_id: str, new_device_id: str) -> None:
        from core.device_node_base import DeviceNodeBase
        if isinstance(node, DeviceNodeBase):
            node.select_device(new_device_id)
            if old_device_id != new_device_id:
                self._history.push(DeviceSelectCmd(node, old_device_id, new_device_id))
        self.update()

    def _hit_wire(self, scene_pos: QPointF, threshold: float = 6.0) -> Optional[str]:
        """Return wire_id of the wire closest to scene_pos within threshold px."""
        best_id   : Optional[str] = None
        best_dist : float         = threshold
        for wire_id, path in self._rendered_wires:
            # Sample path at intervals to find min distance to click point
            total = path.length()
            steps = max(20, int(total / 8))
            for i in range(steps + 1):
                pt = path.pointAtPercent(i / steps)
                dx = pt.x() - scene_pos.x()
                dy = pt.y() - scene_pos.y()
                dist = (dx * dx + dy * dy) ** 0.5
                if dist < best_dist:
                    best_dist = dist
                    best_id   = wire_id
        return best_id

    def _find_pin_pos(self, node_id: str, pin_name: str) -> Optional[RenderedPin]:
        for rp in self._rendered_pins:
            if rp.node_id == node_id and rp.pin_name == pin_name:
                return rp
        return None

    # ── Group membership ──────────────────────────────────────────────────────

    def _update_node_group_membership(self, node_id: str) -> None:
        """Re-assign node to whichever group contains its centre, or none."""
        node = self._runtime.get_node(node_id)
        if not node:
            return
        cx = node.x + _node_width(node) / 2
        cy = node.y + _node_total_height(node) / 2
        center = QPointF(cx, cy)
        for grp in self._groups.values():
            grp.node_ids.discard(node_id)
        for grp in self._groups.values():
            if grp.inner_rect().contains(center):
                grp.node_ids.add(node_id)
                break
        self.update()

    def _update_group_membership(self, group_id: str) -> None:
        """After moving/resizing a group, refresh which nodes belong to it."""
        grp = self._groups.get(group_id)
        if not grp:
            return
        inner = grp.inner_rect()
        for node in self._runtime.nodes.values():
            cx = node.x + _node_width(node) / 2
            cy = node.y + _node_total_height(node) / 2
            center = QPointF(cx, cy)
            if inner.contains(center):
                for g in self._groups.values():
                    if g.group_id != group_id:
                        g.node_ids.discard(node.node_id)
                grp.node_ids.add(node.node_id)
            else:
                grp.node_ids.discard(node.node_id)
        self.update()

    def _on_node_removed_from_groups(self, node_id: str) -> None:
        for grp in self._groups.values():
            grp.node_ids.discard(node_id)

    def _add_group(self, scene_pos: QPointF) -> None:
        grp = NodeGroup(x=scene_pos.x() - 20, y=scene_pos.y() - 20)
        self._groups[grp.group_id] = grp
        self._selected_group = grp.group_id
        self.update()
        self._history.push(GroupCreateCmd(self._groups, grp))
        self._open_group_rename_editor(grp.group_id)

    # ── Group serialization ───────────────────────────────────────────────────

    def get_saved_groups(self) -> list:
        from core.types import SavedGroup
        return [
            SavedGroup(
                group_id = g.group_id, name = g.name,
                x = g.x, y = g.y, width = g.width, height = g.height,
                color = g.color, node_ids = list(g.node_ids),
            )
            for g in self._groups.values()
        ]

    def load_saved_groups(self, saved_groups: list) -> None:
        self._groups.clear()
        for sg in saved_groups:
            grp = NodeGroup(
                group_id = sg.group_id, name = sg.name,
                x = sg.x, y = sg.y, width = sg.width, height = sg.height,
                color = sg.color, node_ids = set(sg.node_ids),
            )
            self._groups[grp.group_id] = grp
        self.update()

    def add_pasted_group(self, gd: dict, id_map: dict, paste_x: float, paste_y: float) -> None:
        """Create a group from pasted clipboard data, remapping old node IDs to new ones."""
        grp = NodeGroup(
            name     = gd["name"],
            color    = gd["color"],
            x        = paste_x + gd["dx"],
            y        = paste_y + gd["dy"],
            width    = gd["width"],
            height   = gd["height"],
            node_ids = set(id_map.values()),
        )
        self._groups[grp.group_id] = grp
        self._last_pasted_group_id = grp.group_id   # tracked for PasteCmd
        self.update()

    # ── Mouse ─────────────────────────────────────────────────────────────────

    def mousePressEvent(self, event: QMouseEvent) -> None:
        scene = self._v2s(event.position())

        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning          = True
            self._pan_start        = event.position()
            self._pan_offset_start = QPointF(self._offset)
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return

        if event.button() == Qt.MouseButton.LeftButton:
            # Group resize handle
            res = self._hit_group_resize(scene)
            if res:
                gid, corner = res
                grp = self._groups[gid]
                self._resizing_group      = gid
                self._resize_corner       = corner
                self._resize_group_start  = QRectF(grp.x, grp.y, grp.width, grp.height)
                self._resize_mouse_start  = scene
                self._selected_group      = gid
                self._selected_node       = None
                self._selected_wire       = None
                self.update(); return

            # Group title bar drag (only when no node is under cursor)
            gt_gid = self._hit_group_title(scene)
            if gt_gid and not self._hit_node(scene):
                grp = self._groups[gt_gid]
                self._dragging_group       = gt_gid
                self._drag_group_start     = scene
                self._drag_group_pos_start = QPointF(grp.x, grp.y)
                self._drag_group_nodes_start = {
                    nid: QPointF(n.x, n.y)
                    for nid in grp.node_ids
                    if (n := self._runtime.get_node(nid)) is not None
                }
                self._selected_group = gt_gid
                self._selected_node  = None
                self._selected_wire  = None
                self.update(); return

            hp = self._hit_pin(scene)
            if hp:
                if hp.direction == PinDirection.OUTPUT:
                    self._wire_src = hp; self._wire_mouse = scene
                    self._selected_wire = None; self.update(); return
                elif self._wire_src:
                    self._try_connect(self._wire_src, hp)
                    self._wire_src = None; self.update(); return

            # Control-panel node interaction (Slider, Button, Toggle, etc.)
            if not self._wire_src:
                ctrl_hit = self._hit_ctrl(scene)
                if ctrl_hit:
                    nid, rect = ctrl_hit
                    node = self._runtime.get_node(nid)
                    if node and node.on_ctrl_press(scene, rect, event.modifiers()):
                        self._ctrl_node_id   = nid
                        self._ctrl_rect      = rect
                        if node.should_select_on_ctrl_press():
                            self._selected_node  = nid
                            self._selected_nodes = {nid}
                            self._selected_wire  = None
                            self.node_selected.emit(nid)
                        self.update()
                        return

            # Device-selector pill click — show device picker menu
            ds_nid = self._hit_device_selector(scene)
            if ds_nid:
                node = self._runtime.get_node(ds_nid)
                if node is not None:
                    from core.device_node_base import DeviceNodeBase, get_instances
                    if isinstance(node, DeviceNodeBase) and node.DEVICE_TYPE_KEY:
                        instances = get_instances(node.DEVICE_TYPE_KEY)
                        if instances:
                            self._show_device_menu(node, instances,
                                                   event.globalPosition().toPoint())
                self._selected_node = ds_nid
                self._selected_wire = None
                node_obj = self._runtime.get_node(ds_nid)
                from core.device_node_base import DeviceNodeBase
                _dev = node_obj.get_device() if isinstance(node_obj, DeviceNodeBase) else None
                self.device_highlighted.emit(_dev.device_id if _dev else None)
                self.node_selected.emit(ds_nid)
                self.update()
                return

            nid = self._hit_node(scene)
            if nid:
                shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
                if shift:
                    # Shift+click: toggle this node in/out of multi-select
                    if nid in self._selected_nodes:
                        self._selected_nodes.discard(nid)
                    else:
                        self._selected_nodes.add(nid)
                    self._selected_node  = nid if nid in self._selected_nodes else None
                    self._selected_wire  = None
                    self._selected_group = None
                    self.update(); return

                # Normal click — keep existing multi-selection if this node is in it,
                # otherwise collapse to single selection
                if nid not in self._selected_nodes:
                    self._selected_nodes = {nid}
                self._selected_node  = nid
                self._selected_wire  = None
                self._selected_group = None
                self._dragging_node  = nid
                self._drag_start_scene = scene
                node = self._runtime.get_node(nid)
                if node:
                    self._drag_node_start = QPointF(node.x, node.y)
                # Store starting positions of ALL selected nodes for multi-drag
                self._drag_nodes_start = {}
                for sid in self._selected_nodes:
                    sn = self._runtime.get_node(sid)
                    if sn:
                        self._drag_nodes_start[sid] = QPointF(sn.x, sn.y)
                self.node_selected.emit(nid)
                # Highlight the specific device this node is using
                node_obj = self._runtime.get_node(nid)
                from core.device_node_base import DeviceNodeBase
                _dev = node_obj.get_device() if isinstance(node_obj, DeviceNodeBase) else None
                self.device_highlighted.emit(_dev.device_id if _dev else None)
                self.update(); return

            # Try wire hit
            wid = self._hit_wire(scene)
            if wid:
                self._selected_wire  = wid
                self._selected_node = None
                self.update(); return

            self._selected_node  = None
            self._selected_nodes = set()
            self._selected_wire  = None
            self._selected_group = None
            self.device_highlighted.emit(None)
            # Start rubber-band selection
            self._rubber_band_active = True
            self._rubber_band_origin = event.position()
            self._rubber_band_cur    = event.position()
            self.update()

        if event.button() == Qt.MouseButton.RightButton:
            rf = self._hit_field(scene)
            nid = self._hit_node(scene)
            if nid:
                self._show_node_context_menu(nid, event.globalPosition().toPoint(), rf)
            else:
                self._show_context_menu(event.globalPosition().toPoint(), scene)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        self._last_mouse_view = event.position()
        # Update hover state for tooltips
        if not self._panning and not self._dragging_node and not self._wire_src:
            scene = self._v2s(event.position())
            hp = self._hit_pin(scene)
            hs = self._hit_title_status(scene)
            new_hovered_pin  = hp
            new_hovered_status = hs if not hp else None
            new_hovered_node = self._hit_node(scene) if not hp and not hs else None
            if (
                new_hovered_pin != self._hovered_pin
                or new_hovered_status != self._hovered_title_status
                or new_hovered_node != self._hovered_node
            ):
                self._hovered_pin  = new_hovered_pin
                self._hovered_title_status = new_hovered_status
                self._hovered_node = new_hovered_node
                self._tooltip_timer.stop()
                QToolTip.hideText()
                if new_hovered_pin or new_hovered_status or new_hovered_node:
                    self._tooltip_timer.start(500)
        if self._resizing_group:
            scene = self._v2s(event.position())
            grp   = self._groups.get(self._resizing_group)
            if grp and self._resize_group_start:
                dx = scene.x() - self._resize_mouse_start.x()
                dy = scene.y() - self._resize_mouse_start.y()
                sr = self._resize_group_start
                snap = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
                if "e" in self._resize_corner:
                    raw = sr.width() + dx
                    if snap: raw = round(raw / GRID_MINOR) * GRID_MINOR
                    grp.width  = max(GROUP_MIN_W, raw)
                if "s" in self._resize_corner:
                    raw = sr.height() + dy
                    if snap: raw = round(raw / GRID_MINOR) * GRID_MINOR
                    grp.height = max(GROUP_MIN_H, raw)
                if "w" in self._resize_corner:
                    nw = sr.width() - dx
                    if snap: nw = round(nw / GRID_MINOR) * GRID_MINOR
                    if nw >= GROUP_MIN_W:
                        grp.x = sr.right() - nw; grp.width = nw
                if "n" in self._resize_corner:
                    nh = sr.height() - dy
                    if snap: nh = round(nh / GRID_MINOR) * GRID_MINOR
                    if nh >= GROUP_MIN_H:
                        grp.y = sr.bottom() - nh; grp.height = nh
            self.update(); return

        if self._dragging_group:
            scene = self._v2s(event.position())
            grp   = self._groups.get(self._dragging_group)
            if grp:
                dx = scene.x() - self._drag_group_start.x()
                dy = scene.y() - self._drag_group_start.y()
                raw_x = self._drag_group_pos_start.x() + dx
                raw_y = self._drag_group_pos_start.y() + dy
                if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    raw_x = round(raw_x / GRID_MINOR) * GRID_MINOR
                    raw_y = round(raw_y / GRID_MINOR) * GRID_MINOR
                snap_dx = raw_x - self._drag_group_pos_start.x()
                snap_dy = raw_y - self._drag_group_pos_start.y()
                grp.x = raw_x
                grp.y = raw_y
                for nid, sp in self._drag_group_nodes_start.items():
                    n = self._runtime.get_node(nid)
                    if n:
                        n.x = sp.x() + snap_dx
                        n.y = sp.y() + snap_dy
            self.update(); return

        if self._rubber_band_active:
            self._rubber_band_cur = event.position()
            origin_s = self._v2s(self._rubber_band_origin)
            cur_s    = self._v2s(self._rubber_band_cur)
            sel_rect = QRectF(
                min(origin_s.x(), cur_s.x()), min(origin_s.y(), cur_s.y()),
                abs(cur_s.x() - origin_s.x()), abs(cur_s.y() - origin_s.y()),
            )
            new_sel: set = set()
            for node in self._runtime.nodes.values():
                nr = QRectF(node.x, node.y, _node_width(node), _node_total_height(node))
                if sel_rect.intersects(nr):
                    new_sel.add(node.node_id)
            self._selected_nodes = new_sel
            self._selected_node  = next(iter(new_sel)) if len(new_sel) == 1 else None
            self.update(); return

        if self._ctrl_node_id:
            scene = self._v2s(event.position())
            node  = self._runtime.get_node(self._ctrl_node_id)
            if node and self._ctrl_rect:
                node.on_ctrl_drag(scene, self._ctrl_rect)
            self.update(); return

        if self._panning:
            self._offset = self._pan_offset_start + (event.position() - self._pan_start)
            self.update(); return
        if self._dragging_node:
            scene = self._v2s(event.position())
            dx = scene.x() - self._drag_start_scene.x()
            dy = scene.y() - self._drag_start_scene.y()
            snap = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            if len(self._drag_nodes_start) > 1:
                for sid, sp in self._drag_nodes_start.items():
                    sn = self._runtime.get_node(sid)
                    if sn:
                        raw_x = sp.x() + dx
                        raw_y = sp.y() + dy
                        if snap:
                            raw_x = round(raw_x / GRID_MINOR) * GRID_MINOR
                            raw_y = round(raw_y / GRID_MINOR) * GRID_MINOR
                        sn.x = raw_x
                        sn.y = raw_y
            else:
                node = self._runtime.get_node(self._dragging_node)
                if node:
                    raw_x = self._drag_node_start.x() + dx
                    raw_y = self._drag_node_start.y() + dy
                    if snap:
                        raw_x = round(raw_x / GRID_MINOR) * GRID_MINOR
                        raw_y = round(raw_y / GRID_MINOR) * GRID_MINOR
                    node.x = raw_x
                    node.y = raw_y
            self.update(); return
        if self._wire_src:
            self._wire_mouse = self._v2s(event.position()); self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
        if event.button() == Qt.MouseButton.LeftButton:
            if self._ctrl_node_id:
                node = self._runtime.get_node(self._ctrl_node_id)
                if node:
                    node.on_ctrl_release()
                self._ctrl_node_id = None
                self._ctrl_rect    = None
                self.update()
            if self._rubber_band_active:
                self._rubber_band_active = False
                self.update()
            if self._dragging_node:
                nid = self._dragging_node
                self._dragging_node = None
                if self._drag_nodes_start:
                    moves: dict = {}
                    for sid, sp in self._drag_nodes_start.items():
                        n = self._runtime.get_node(sid)
                        if n and (n.x != sp.x() or n.y != sp.y()):
                            moves[sid] = (sp.x(), sp.y(), n.x, n.y)
                    if moves:
                        self._history.push(NodeMoveCmd(self._runtime, moves))
                    for sid in list(self._drag_nodes_start.keys()):
                        self._update_node_group_membership(sid)
                    self._drag_nodes_start = {}
                else:
                    n = self._runtime.get_node(nid)
                    if n:
                        ds = self._drag_node_start
                        if n.x != ds.x() or n.y != ds.y():
                            self._history.push(NodeMoveCmd(
                                self._runtime,
                                {nid: (ds.x(), ds.y(), n.x, n.y)},
                            ))
                    self._update_node_group_membership(nid)
            if self._dragging_group:
                gid = self._dragging_group
                self._dragging_group = None
                grp = self._groups.get(gid)
                if grp:
                    gb = self._drag_group_pos_start
                    ga = (grp.x, grp.y)
                    if ga != (gb.x(), gb.y()):
                        node_moves: dict = {}
                        for nid2, sp2 in self._drag_group_nodes_start.items():
                            n2 = self._runtime.get_node(nid2)
                            if n2:
                                node_moves[nid2] = (sp2.x(), sp2.y(), n2.x, n2.y)
                        self._history.push(GroupMoveCmd(
                            self._runtime, self._groups, gid,
                            (gb.x(), gb.y()), ga, node_moves,
                        ))
                self._update_group_membership(gid)
            if self._resizing_group:
                gid = self._resizing_group
                self._resizing_group = None
                grp = self._groups.get(gid)
                if grp and self._resize_group_start:
                    sr = self._resize_group_start
                    before = (sr.x(), sr.y(), sr.width(), sr.height())
                    after  = (grp.x, grp.y, grp.width, grp.height)
                    if before != after:
                        self._history.push(GroupResizeCmd(self._groups, gid, before, after))
                self._update_group_membership(gid)
            if self._wire_src:
                hp = self._hit_pin(self._v2s(event.position()))
                if hp and hp.direction == PinDirection.INPUT:
                    self._try_connect(self._wire_src, hp)
                self._wire_src = None; self.update()

    # ── Drag-and-drop (device panel → node) ──────────────────────────────────

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasText() and event.mimeData().text().startswith("device:"):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        text = event.mimeData().text() if event.mimeData().hasText() else ""
        if not text.startswith("device:"):
            event.ignore()
            return
        device_id = text[len("device:"):]
        scene = self._v2s(event.position())

        from core.device_node_base import DeviceNodeBase, get_type_key_for_device
        type_key = get_type_key_for_device(device_id)

        new_target: Optional[str] = None
        if type_key:
            for node in reversed(list(self._runtime.nodes.values())):
                w = _node_width(node)
                h = _node_total_height(node)
                if QRectF(node.x, node.y, w, h).contains(scene):
                    if isinstance(node, DeviceNodeBase) and node.DEVICE_TYPE_KEY == type_key:
                        new_target = node.node_id
                    break

        if new_target != self._drag_highlight_node:
            self._drag_highlight_node = new_target
            self.update()
        event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:
        self._drag_highlight_node = None
        self.update()

    def dropEvent(self, event) -> None:
        text = event.mimeData().text() if event.mimeData().hasText() else ""
        if not text.startswith("device:"):
            event.ignore()
            self._drag_highlight_node = None
            return
        device_id = text[len("device:"):]
        if self._drag_highlight_node:
            node = self._runtime.get_node(self._drag_highlight_node)
            if node:
                from core.device_node_base import DeviceNodeBase
                if isinstance(node, DeviceNodeBase):
                    node.select_device(device_id)
        self._drag_highlight_node = None
        self.update()
        event.acceptProposedAction()

    def wheelEvent(self, event: QWheelEvent) -> None:
        factor    = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        old_scene = self._v2s(event.position())
        self._zoom = max(0.2, min(4.0, self._zoom * factor))
        new_view  = QPointF(old_scene.x() * self._zoom + self._offset.x(),
                            old_scene.y() * self._zoom + self._offset.y())
        self._offset += event.position() - new_view
        self.update()

    # ── Tooltip ───────────────────────────────────────────────────────────────

    def _show_hover_tooltip(self) -> None:
        """Called by _tooltip_timer — shows QToolTip for pin or node."""
        global_pos = self.mapToGlobal(self._last_mouse_view.toPoint())

        # Pin tooltip
        if self._hovered_pin:
            rp        = self._hovered_pin
            node      = self._runtime.get_node(rp.node_id)
            pin_desc  = None
            if node:
                pin_desc = next(
                    (p for p in node.PINS if p.name == rp.pin_name), None
                )
            direction = "→ OUT" if rp.direction.name == "OUTPUT" else "← IN"
            type_name = rp.pin_type.name
            if pin_desc and pin_desc.tooltip:
                text = (f"<b>{rp.pin_name}</b>  <small>{direction} · {type_name}</small>"
                        f"<br><small style='color:#aaa'>{pin_desc.tooltip}</small>")
            else:
                optional = " · optional" if (pin_desc and pin_desc.optional) else ""
                text = (f"<b>{rp.pin_name}</b>"
                        f"<br>{direction} · <b>{type_name}</b>{optional}")
            QToolTip.showText(global_pos, text, self)
            return

        if self._hovered_title_status:
            node = self._runtime.get_node(self._hovered_title_status)
            tooltip = ""
            if node and hasattr(node, "title_status_tooltip"):
                try:
                    tooltip = str(node.title_status_tooltip())
                except Exception:
                    tooltip = ""
            if tooltip:
                QToolTip.showText(global_pos, tooltip, self)
            return

        # Node tooltip — only when NODE_TOOLTIP is set
        if self._hovered_node:
            node = self._runtime.get_node(self._hovered_node)
            if node and node.NODE_TOOLTIP:
                QToolTip.showText(global_pos, node.NODE_TOOLTIP, self)
            return

        QToolTip.hideText()

    # ── Double-click inline editor ────────────────────────────────────────────

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        scene = self._v2s(event.position())
        # Field / var-input editor (takes priority)
        rf = self._hit_field(scene)
        if rf:
            self._open_editor(rf, event.position())
            return
        # Double-click on group title → rename group (only when no node is above)
        if not self._hit_node(scene):
            gt_gid = self._hit_group_title(scene)
            if gt_gid:
                self._open_group_rename_editor(gt_gid)
                return
        # Double-click on title bar → rename node
        title_nid = self._hit_title_bar(scene)
        if title_nid:
            self._open_node_rename_editor(title_nid)
            return
        # Double-click on a DeviceNodeBase body (non-title) → cycle device
        nid = self._hit_node(scene)
        if nid:
            node = self._runtime.get_node(nid)
            if node is not None:
                from core.device_node_base import DeviceNodeBase
                if isinstance(node, DeviceNodeBase):
                    old_dev = node.get_device()
                    old_did = old_dev.device_id if old_dev else None
                    node.cycle_device()
                    self._history.push(DeviceCycleCmd(node, old_did))
                    self.update()
                    return
        super().mouseDoubleClickEvent(event)

    def _open_editor(self, rf: RenderedField, view_pos: QPointF) -> None:
        self._close_editor()
        node = self._runtime.get_node(rf.node_id)
        if not node:
            return
        # ColorPicker: for editable field named "color" (str), open QColorDialog
        if not rf.is_var and rf.field_name == "color":
            old_color = node.get_field("color") or "#ffffff"
            initial = _parse_hex_to_qcolor(str(old_color))
            color = QColorDialog.getColor(initial, self, "Pick color")
            if color.isValid():
                hex_val = f"#{color.red():02x}{color.green():02x}{color.blue():02x}"
                node.set_field("color", hex_val)
                if old_color != hex_val:
                    self._history.push(FieldEditCmd(
                        self._runtime, rf.node_id, "color", False, old_color, hex_val
                    ))
                self.update()
                return
        tl = self._s2v(rf.scene_rect.topLeft())
        br = self._s2v(rf.scene_rect.bottomRight())

        editor = QLineEdit(self)
        editor.setObjectName("FieldEditor")
        editor.setStyleSheet("""
            QLineEdit#FieldEditor {
                background: #1a0a0f; color: #ffd0de;
                border: 1px solid #f95979; border-radius: 4px;
                padding: 0 4px; font-family: 'Courier New'; font-size: 9pt;
            }
        """)
        if rf.is_dynamic and hasattr(node, "get_dynamic_field_value"):
            old_val = node.get_dynamic_field_value(rf.dynamic_index)
        else:
            old_val = (node.get_var_input(rf.field_name) if rf.is_var
                       else node.get_field(rf.field_name))
        editor.setText(str(old_val) if old_val is not None else "")
        editor.selectAll()
        editor.setGeometry(int(tl.x()), int(tl.y()),
                           int(br.x() - tl.x()), int(br.y() - tl.y()))
        editor.show()
        editor.setFocus()

        _field_committed = [False]

        def _commit() -> None:
            if _field_committed[0]:
                return
            _field_committed[0] = True
            raw = editor.text()
            if rf.is_dynamic and hasattr(node, "set_dynamic_field_value"):
                old_pins = self._dynamic_pin_names(node)
                node.set_dynamic_field_value(rf.dynamic_index, raw)
                self._remove_missing_dynamic_wires(rf.node_id, old_pins)
            elif rf.is_var:
                node.set_var_input(rf.field_name, raw)
            else:
                node.set_field(rf.field_name, raw)
            if rf.is_dynamic and hasattr(node, "get_dynamic_field_value"):
                new_val = node.get_dynamic_field_value(rf.dynamic_index)
            else:
                new_val = (node.get_var_input(rf.field_name) if rf.is_var
                           else node.get_field(rf.field_name))
            if not rf.is_dynamic and str(old_val) != str(new_val):
                self._history.push(FieldEditCmd(
                    self._runtime, rf.node_id, rf.field_name, rf.is_var, old_val, new_val
                ))
            self._close_editor()
            self.update()

        editor.returnPressed.connect(_commit)
        editor.editingFinished.connect(_commit)
        editor._cancel = self._close_editor  # type: ignore[attr-defined]
        editor.installEventFilter(self)
        self._active_editor = editor

    def _close_editor(self) -> None:
        if self._active_editor:
            ed = self._active_editor
            self._active_editor = None   # clear first to block re-entrant calls
            ed.hide()
            ed.deleteLater()

    def _open_node_rename_editor(self, node_id: str) -> None:
        """Show an inline QLineEdit over the title bar to rename a node."""
        node = self._runtime.get_node(node_id)
        if not node:
            return
        self._close_editor()
        width = _node_width(node)
        title_scene = QRectF(node.x, node.y, width, TITLE_H)
        tl = self._s2v(title_scene.topLeft())
        br = self._s2v(title_scene.bottomRight())

        editor = QLineEdit(self)
        editor.setObjectName("TitleEditor")
        editor.setStyleSheet("""
            QLineEdit#TitleEditor {
                background: #2d1020; color: #ffd0de;
                border: 1px solid #f95979; border-radius: 4px;
                padding: 0 8px; font-family: 'Segoe UI'; font-size: 9pt;
                font-weight: bold;
            }
        """)
        old_name = node.custom_name
        editor.setText(node.custom_name or _node_display_name(node.__class__))
        editor.selectAll()
        editor.setGeometry(int(tl.x()), int(tl.y()),
                           int(br.x() - tl.x()), int(br.y() - tl.y()))
        editor.show()
        editor.setFocus()

        _committed = [False]

        def _commit() -> None:
            if _committed[0]:
                return
            _committed[0] = True
            text = editor.text().strip()
            new_name = text if text and text != _node_display_name(node.__class__) else None
            node.custom_name = new_name
            if old_name != new_name:
                self._history.push(NodeRenameCmd(self._runtime, node_id, old_name, new_name))
            node.node_changed.emit()
            self._close_editor()
            self.update()

        editor.returnPressed.connect(_commit)
        editor.editingFinished.connect(_commit)
        editor._cancel = self._close_editor  # type: ignore[attr-defined]
        editor.installEventFilter(self)
        self._active_editor = editor

    def _open_ctrl_label_editor(self, node: "NodeBase", scene_rect: QRectF) -> None:
        """Inline QLineEdit over a control-panel widget's label area."""
        self._close_editor()
        tl = self._s2v(scene_rect.topLeft())
        br = self._s2v(scene_rect.bottomRight())

        editor = QLineEdit(self)
        editor.setObjectName("CtrlLabelEditor")
        editor.setStyleSheet("""
            QLineEdit#CtrlLabelEditor {
                background: #1e0a30; color: #ffd0de;
                border: 1px solid #ea80fc; border-radius: 6px;
                padding: 0 6px; font-family: 'Segoe UI'; font-size: 9pt;
                font-weight: bold;
            }
        """)
        editor.setText(node.get_ctrl_label())  # type: ignore[union-attr]
        editor.selectAll()
        editor.setGeometry(int(tl.x()), int(tl.y()),
                           int(br.x() - tl.x()), int(br.y() - tl.y()))
        editor.show()
        editor.setFocus()

        _committed = [False]

        def _commit() -> None:
            if _committed[0]:
                return
            _committed[0] = True
            node.set_ctrl_label(editor.text())  # type: ignore[union-attr]
            self._close_editor()
            self.update()

        editor.returnPressed.connect(_commit)
        editor.editingFinished.connect(_commit)
        editor._cancel = self._close_editor  # type: ignore[attr-defined]
        editor.installEventFilter(self)
        self._active_editor = editor

    def _open_group_rename_editor(self, group_id: str) -> None:
        """Show an inline QLineEdit over the group title bar to rename a group."""
        grp = self._groups.get(group_id)
        if not grp:
            return
        self._close_editor()
        title_scene = grp.title_rect()
        tl = self._s2v(title_scene.topLeft())
        br = self._s2v(title_scene.bottomRight())

        editor = QLineEdit(self)
        editor.setObjectName("TitleEditor")
        editor.setStyleSheet("""
            QLineEdit#TitleEditor {
                background: #2d1020; color: #ffd0de;
                border: 1px solid #f95979; border-radius: 4px;
                padding: 0 8px; font-family: 'Segoe UI'; font-size: 9pt;
                font-weight: bold;
            }
        """)
        old_grp_name = grp.name
        editor.setText(grp.name)
        editor.selectAll()
        editor.setGeometry(int(tl.x()), int(tl.y()),
                           int(br.x() - tl.x()), int(br.y() - tl.y()))
        editor.show()
        editor.setFocus()

        _committed = [False]

        def _commit() -> None:
            if _committed[0]:
                return
            _committed[0] = True
            text = editor.text().strip()
            new_grp_name = text if text else "Group"
            grp.name = new_grp_name
            if old_grp_name != new_grp_name:
                self._history.push(GroupRenameCmd(
                    self._groups, group_id, old_grp_name, new_grp_name
                ))
            self._close_editor()
            self.update()

        editor.returnPressed.connect(_commit)
        editor.editingFinished.connect(_commit)
        editor._cancel = self._close_editor  # type: ignore[attr-defined]
        editor.installEventFilter(self)
        self._active_editor = editor

    def eventFilter(self, obj, event) -> bool:
        from PyQt6.QtCore import QEvent
        if (obj is self._active_editor
                and event.type() == QEvent.Type.KeyPress
                and event.key() == Qt.Key.Key_Escape):
            fn = getattr(obj, "_cancel", None)
            if fn: fn()
            return True
        return super().eventFilter(obj, event)

    # ── Keyboard ──────────────────────────────────────────────────────────────

    def clear_history(self) -> None:
        """Reset undo/redo stacks (call after new graph or load)."""
        self._history.clear()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        ctrl = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)

        if ctrl and event.key() == Qt.Key.Key_Z:
            self._history.undo()
            self.update()
            return
        if ctrl and event.key() == Qt.Key.Key_Y:
            self._history.redo()
            self.update()
            return

        if event.key() == Qt.Key.Key_F2:
            if self._selected_group:
                self._open_group_rename_editor(self._selected_group)
                return
            if self._selected_node:
                self._open_node_rename_editor(self._selected_node)
            return

        if event.key() == Qt.Key.Key_Delete:
            if self._selected_group:
                self._delete_selected_group()
                return
            if self._selected_wire:
                wire = self._runtime.wires.get(self._selected_wire)
                self._runtime.remove_wire(self._selected_wire)
                if wire:
                    self._history.push(WireDeleteCmd(self._runtime, wire))
                self._selected_wire = None; self.update(); return
            if self._selected_nodes or self._selected_node:
                self._delete_selected_nodes()
                return

        if ctrl and event.key() == Qt.Key.Key_A:
            self._selected_nodes = set(self._runtime.nodes.keys())
            self._selected_node  = None
            self._selected_wire  = None
            self._selected_group = None
            self.update(); return

        if ctrl and event.key() == Qt.Key.Key_C:
            self._copy_selected(); return
        if ctrl and event.key() == Qt.Key.Key_X:
            self._cut_selected(); return
        if ctrl and event.key() == Qt.Key.Key_V:
            self._paste_clipboard(); return
        if ctrl and event.key() == Qt.Key.Key_D:
            self._duplicate_selected(); return

        if event.key() == Qt.Key.Key_Tab:
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self._center_origin()
            else:
                self._tab_cycle()
            return

        shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        if shift and event.key() == Qt.Key.Key_F:
            global_pos = QCursor.pos()
            widget_pos = self.mapFromGlobal(global_pos)
            scene_pos = self._v2s(QPointF(widget_pos))
            self._open_node_search(global_pos, scene_pos)
            return

        if event.key() == Qt.Key.Key_Escape:
            self._wire_src       = None
            self._selected_node  = None
            self._selected_nodes = set()
            self._selected_wire  = None
            self._selected_group = None
            self.device_highlighted.emit(None)
            self.update()

        super().keyPressEvent(event)

    # ── Delete helpers ────────────────────────────────────────────────────────

    def _delete_selected_group(self) -> None:
        grp = self._groups.get(self._selected_group)
        if grp:
            # Collect data before deletion
            group_nodes: list = []
            collected_ids: set = set()
            group_wires: list = []
            for nid in list(grp.node_ids):
                node = self._runtime.get_node(nid)
                if node:
                    group_nodes.append(node)
            for nid in list(grp.node_ids):
                for w in self._runtime.wires.values():
                    if (w.src_node == nid or w.dst_node == nid) and w.wire_id not in collected_ids:
                        collected_ids.add(w.wire_id)
                        group_wires.append(w)
            # Perform deletion
            self._groups.pop(self._selected_group, None)
            for nid in list(grp.node_ids):
                self._runtime.remove_node(nid)
            self._history.push(GroupDeleteCmd(
                self._runtime, self._groups, grp, group_nodes, group_wires
            ))
        self._selected_group = None
        self.update()

    def _delete_selected_nodes(self, description: str = "Delete") -> None:
        nids = list(self._selected_nodes) if self._selected_nodes else (
            [self._selected_node] if self._selected_node else []
        )
        if not nids:
            return
        if len(nids) > 1:
            self._history.begin_macro(description)
        for nid in nids:
            node = self._runtime.get_node(nid)
            if node:
                wires = [w for w in self._runtime.wires.values()
                         if w.src_node == nid or w.dst_node == nid]
                group_membership = {gid for gid, g in self._groups.items()
                                    if nid in g.node_ids}
                self._runtime.remove_node(nid)
                self._history.push(NodeDeleteCmd(
                    self._runtime, node, wires, self._groups, group_membership
                ))
        if len(nids) > 1:
            self._history.end_macro()
        self._selected_nodes = set()
        self._selected_node  = None
        self.update()

    def _copy_selected(self) -> None:
        # Group copy: when a group is selected with no individual node selection
        if self._selected_group and not self._selected_nodes and not self._selected_node:
            grp = self._groups.get(self._selected_group)
            if grp and grp.node_ids:
                nodes = [n for nid in grp.node_ids
                         if (n := self._runtime.get_node(nid)) is not None]
                if nodes:
                    target_ids = {n.node_id for n in nodes}
                    ref_x = min(n.x for n in nodes)
                    ref_y = min(n.y for n in nodes)
                    node_entries = [
                        {
                            "type_key": f"{n.__class__.__module__}.{n.__class__.__name__}",
                            "state":    n.get_state(),
                            "dx": n.x - ref_x + 30.0,
                            "dy": n.y - ref_y + 30.0,
                            "old_id": n.node_id,
                        }
                        for n in nodes
                    ]
                    wire_entries = [
                        {
                            "src_node": w.src_node, "src_pin": w.src_pin,
                            "dst_node": w.dst_node, "dst_pin": w.dst_pin,
                        }
                        for w in self._runtime.wires.values()
                        if w.src_node in target_ids and w.dst_node in target_ids
                    ]
                    group_entry = {
                        "name":   grp.name,
                        "color":  grp.color,
                        "dx":     grp.x - ref_x + 30.0,
                        "dy":     grp.y - ref_y + 30.0,
                        "width":  grp.width,
                        "height": grp.height,
                    }
                    self._clipboard = {"nodes": node_entries, "wires": wire_entries,
                                       "group": group_entry}
            return

        targets = list(self._selected_nodes) if self._selected_nodes else (
            [self._selected_node] if self._selected_node else []
        )
        if not targets:
            return
        nodes = [n for nid in targets if (n := self._runtime.get_node(nid)) is not None]
        if not nodes:
            return
        target_ids = {n.node_id for n in nodes}
        ref_x = min(n.x for n in nodes)
        ref_y = min(n.y for n in nodes)
        node_entries = [
            {
                "type_key": f"{n.__class__.__module__}.{n.__class__.__name__}",
                "state":    n.get_state(),
                "dx": n.x - ref_x + 30.0,
                "dy": n.y - ref_y + 30.0,
                "old_id": n.node_id,
            }
            for n in nodes
        ]
        # Capture wires whose both endpoints are within the copied set
        wire_entries = [
            {
                "src_node": w.src_node, "src_pin": w.src_pin,
                "dst_node": w.dst_node, "dst_pin": w.dst_pin,
            }
            for w in self._runtime.wires.values()
            if w.src_node in target_ids and w.dst_node in target_ids
        ]
        self._clipboard = {"nodes": node_entries, "wires": wire_entries}

    def _cut_selected(self) -> None:
        self._copy_selected()
        self._delete_selected_nodes(description="Cut")

    def _paste_clipboard(self) -> None:
        if not self._clipboard:
            return
        # Paste at current cursor position if it's within the canvas,
        # otherwise fall back to canvas centre + offset.
        mx, my = self._last_mouse_view.x(), self._last_mouse_view.y()
        if 0 <= mx <= self.width() and 0 <= my <= self.height():
            paste_scene = self._v2s(QPointF(mx, my))
        else:
            paste_scene = self._v2s(QPointF(self.width() / 2, self.height() / 2))
        import json as _json
        payload_dict = {
            "paste_x": paste_scene.x(),
            "paste_y": paste_scene.y(),
            "nodes":   self._clipboard["nodes"],
            "wires":   self._clipboard["wires"],
        }
        if "group" in self._clipboard:
            payload_dict["group"] = self._clipboard["group"]
        payload = _json.dumps(payload_dict)

        # Capture what gets created — signals are synchronous on the main thread
        _created_node_ids: list[str] = []
        _created_wire_ids: list[str] = []

        def _on_node(nid: str) -> None:
            _created_node_ids.append(nid)

        def _on_wire(wire) -> None:
            _created_wire_ids.append(wire.wire_id)

        self._runtime.node_added.connect(_on_node)
        self._runtime.wire_added.connect(_on_wire)
        self._last_pasted_group_id = None
        self.status_message.emit(f"__paste_nodes__{payload}")
        self._runtime.node_added.disconnect(_on_node)
        self._runtime.wire_added.disconnect(_on_wire)

        if _created_node_ids or _created_wire_ids:
            nodes = [n for nid in _created_node_ids
                     if (n := self._runtime.get_node(nid)) is not None]
            wires = [w for wid in _created_wire_ids
                     if (w := self._runtime.wires.get(wid)) is not None]
            group = (self._groups.get(self._last_pasted_group_id)
                     if self._last_pasted_group_id else None)
            self._history.push(PasteCmd(self._runtime, self._groups, nodes, wires, group))

    def _duplicate_selected(self) -> None:
        self._copy_selected()
        self._paste_clipboard()

    def _tab_cycle(self) -> None:
        nodes = list(self._runtime.nodes.values())
        if not nodes: return
        self._tab_index = (self._tab_index + 1) % len(nodes)
        node = nodes[self._tab_index]
        self._selected_node = node.node_id
        self._center_scene(QPointF(node.x + _node_width(node) / 2,
                                   node.y + _node_total_height(node) / 2))
        self.update()

    def _center_origin(self) -> None:
        self._selected_node = None
        self._offset = QPointF(self.width() / 2, self.height() / 2)
        self._zoom   = 1.0; self.update()

    def _center_scene(self, sp: QPointF) -> None:
        self._offset = QPointF(self.width()  / 2 - sp.x() * self._zoom,
                               self.height() / 2 - sp.y() * self._zoom)

    # ── Wire creation ─────────────────────────────────────────────────────────

    def _try_connect(self, src: RenderedPin, dst: RenderedPin) -> None:
        # Self-loops are allowed for both data and tick pins (feedback connections)
        is_self_loop = src.node_id == dst.node_id
        if is_self_loop and dst.direction != PinDirection.INPUT:
            return
        if dst.pin_type not in PIN_COMPATIBILITY.get(src.pin_type, set()):
            self.status_message.emit(
                f"Type mismatch: {src.pin_type.name} → {dst.pin_type.name}")
            return
        wire = WireDescriptor(
            wire_id  = str(uuid.uuid4()),
            src_node = src.node_id, src_pin = src.pin_name,
            dst_node = dst.node_id, dst_pin = dst.pin_name,
        )
        if self._runtime.add_wire(wire):
            self._history.push(WireAddCmd(self._runtime, wire))
            self.wire_created.emit(wire)
        else:
            self.status_message.emit("Could not create wire")

    # ── Context menu ──────────────────────────────────────────────────────────

    # ── Node right-click context menu ─────────────────────────────────────────

    def _get_ctrl_rect(self, node_id: str) -> Optional[QRectF]:
        """Return the CUSTOM row scene rect for a node, or None."""
        node = self._runtime.get_node(node_id)
        if not node:
            return None
        extra    = _device_sel_extra(node)
        body_top = node.y + TITLE_H + extra
        rows     = _build_rows(node, body_top)
        width    = _node_width(node)
        for row in rows:
            if row.kind == _RowKind.CUSTOM:
                return QRectF(node.x + 4, row.y, width - 8, row.h)
        return None

    def _show_node_context_menu(self, node_id: str, global_pos: QPoint,
                                field_hit: Optional[RenderedField] = None) -> None:
        node = self._runtime.get_node(node_id)
        if not node:
            return
        menu = QMenu(self)
        menu.setStyleSheet(_MENU_STYLE)

        rename_act = QAction(tr("ui.canvas.menu.rename"), menu)
        rename_act.triggered.connect(lambda: self._open_node_rename_editor(node_id))
        menu.addAction(rename_act)

        before_node_actions = len(menu.actions())
        node._get_context_menu(self, menu, field_hit)
        if len(menu.actions()) > before_node_actions:
            menu.addSeparator()

        dup_act = QAction(tr("ui.canvas.menu.duplicate"), menu)
        dup_act.triggered.connect(lambda: self._duplicate_node(node_id))
        menu.addAction(dup_act)

        node_wires = [w for w in self._runtime.wires.values()
                      if w.src_node == node_id or w.dst_node == node_id]
        disc_act = QAction(tr("ui.canvas.menu.remove_connections"), menu)
        disc_act.setEnabled(bool(node_wires))
        disc_act.triggered.connect(lambda: self._remove_node_connections(node_id))
        menu.addAction(disc_act)

        del_act = QAction(tr("ui.canvas.menu.delete"), menu)
        del_act.triggered.connect(lambda: self._delete_node(node_id))
        menu.addAction(del_act)

        menu.exec(global_pos)

    def _duplicate_node(self, node_id: str) -> None:
        self._selected_nodes = {node_id}
        self._selected_node  = node_id
        self._duplicate_selected()

    def _remove_node_connections(self, node_id: str) -> None:
        wires = [w for w in self._runtime.wires.values()
                 if w.src_node == node_id or w.dst_node == node_id]
        if not wires:
            return
        self._history.begin_macro("Remove connections")
        for wire in wires:
            self._runtime.remove_wire(wire.wire_id)
            self._history.push(WireDeleteCmd(self._runtime, wire))
        self._history.end_macro()
        self.update()

    def _open_event_name_dialog(self, node_id: str) -> None:
        node = self._runtime.get_node(node_id)
        if not node or not hasattr(node, "get_event_name") or not hasattr(node, "set_event_name"):
            return

        dlg = QDialog(self)
        dlg.setWindowTitle(tr("ui.dialog.event_name.title", default="Edit Event Name"))
        dlg.setModal(True)
        dlg.setStyleSheet("""
            QDialog { background: #1a0a0f; color: #ffd0de; }
            QLabel  { color: #ffd0de; }
            QLineEdit {
                background: #12070b; color: #ffd0de;
                border: 1px solid #f95979; border-radius: 4px;
                padding: 4px;
            }
            QPushButton {
                background: #2a1018; color: #ffd0de;
                border: 1px solid #45072f; border-radius: 4px;
                padding: 4px 10px;
            }
            QPushButton:hover { background: #c90084; border-color: #c90084; }
        """)

        layout = QVBoxLayout(dlg)
        editor = QLineEdit(dlg)
        editor.setText(str(node.get_event_name()))
        editor.selectAll()
        layout.addWidget(editor)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            dlg,
        )
        layout.addWidget(buttons)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)

        if dlg.exec() == QDialog.DialogCode.Accepted:
            node.set_event_name(editor.text())
            self.update()

    def _open_websocket_config_dialog(self, node_id: str) -> None:
        node = self._runtime.get_node(node_id)
        if not node or not hasattr(node, "get_websocket_config") or not hasattr(node, "set_websocket_config"):
            return

        host, port = node.get_websocket_config()

        dlg = QDialog(self)
        dlg.setWindowTitle(tr("ui.dialog.websocket_server.title", default="WebSocket Server"))
        dlg.setModal(True)
        dlg.setStyleSheet("""
            QDialog { background: #1a0a0f; color: #ffd0de; }
            QLabel  { color: #ffd0de; }
            QLineEdit, QSpinBox {
                background: #12070b; color: #ffd0de;
                border: 1px solid #f95979; border-radius: 4px;
                padding: 4px;
            }
            QPushButton {
                background: #2a1018; color: #ffd0de;
                border: 1px solid #45072f; border-radius: 4px;
                padding: 4px 10px;
            }
            QPushButton:hover { background: #c90084; border-color: #c90084; }
        """)

        layout = QVBoxLayout(dlg)
        form = QFormLayout()
        host_editor = QLineEdit(dlg)
        host_editor.setText(str(host))
        port_editor = QSpinBox(dlg)
        port_editor.setRange(1, 65535)
        port_editor.setValue(int(port))
        form.addRow(tr("ui.dialog.websocket_server.host", default="Host:"), host_editor)
        form.addRow(tr("ui.dialog.websocket_server.port", default="Port:"), port_editor)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            dlg,
        )
        layout.addWidget(buttons)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)

        if dlg.exec() == QDialog.DialogCode.Accepted:
            node.set_websocket_config(host_editor.text(), port_editor.value())
            self.update()

    def _open_mqtt_config_dialog(self, node_id: str) -> None:
        node = self._runtime.get_node(node_id)
        if not node or not hasattr(node, "get_mqtt_config") or not hasattr(node, "set_mqtt_config"):
            return

        host, port = node.get_mqtt_config()

        dlg = QDialog(self)
        dlg.setWindowTitle(tr("ui.dialog.mqtt_server.title", default="MQTT Server"))
        dlg.setModal(True)
        dlg.setStyleSheet("""
            QDialog { background: #1a0a0f; color: #ffd0de; }
            QLabel  { color: #ffd0de; }
            QLineEdit, QSpinBox {
                background: #12070b; color: #ffd0de;
                border: 1px solid #f95979; border-radius: 4px;
                padding: 4px;
            }
            QPushButton {
                background: #2a1018; color: #ffd0de;
                border: 1px solid #45072f; border-radius: 4px;
                padding: 4px 10px;
            }
            QPushButton:hover { background: #c90084; border-color: #c90084; }
        """)

        layout = QVBoxLayout(dlg)
        form = QFormLayout()
        host_editor = QLineEdit(dlg)
        host_editor.setText(str(host))
        port_editor = QSpinBox(dlg)
        port_editor.setRange(1, 65535)
        port_editor.setValue(int(port))
        form.addRow(tr("ui.dialog.mqtt_server.host", default="Host:"), host_editor)
        form.addRow(tr("ui.dialog.mqtt_server.port", default="Port:"), port_editor)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            dlg,
        )
        layout.addWidget(buttons)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)

        if dlg.exec() == QDialog.DialogCode.Accepted:
            node.set_mqtt_config(host_editor.text(), port_editor.value())
            self.update()

    def _open_voice_recognition_dialog(self, node_id: str) -> None:
        node = self._runtime.get_node(node_id)
        if not node or not hasattr(node, "get_voice_recognition_config"):
            return
        if not hasattr(node, "set_voice_recognition_config"):
            return

        current_mic, sensitivity = node.get_voice_recognition_config()
        audio_devices = [("microphone", None, "Default microphone", True)]
        if hasattr(node, "list_voice_audio_devices"):
            audio_devices = node.list_voice_audio_devices()
        elif hasattr(node, "list_voice_microphones"):
            audio_devices = [
                ("microphone", mic_index, mic_name, True)
                for mic_index, mic_name in node.list_voice_microphones()
            ]

        dlg = QDialog(self)
        dlg.setWindowTitle(tr("ui.dialog.voice_recognition.title", default="Voice Recognition"))
        dlg.setModal(True)
        dlg.setStyleSheet("""
            QDialog { background: #1a0a0f; color: #ffd0de; }
            QLabel  { color: #ffd0de; }
            QComboBox, QSpinBox {
                background: #12070b; color: #ffd0de;
                border: 1px solid #f95979; border-radius: 4px;
                padding: 4px;
            }
            QPushButton {
                background: #2a1018; color: #ffd0de;
                border: 1px solid #45072f; border-radius: 4px;
                padding: 4px 10px;
            }
            QPushButton:hover { background: #c90084; border-color: #c90084; }
        """)

        layout = QVBoxLayout(dlg)
        form = QFormLayout()

        mic_editor = QComboBox(dlg)
        selected_index = 0
        for idx, (device_kind, mic_index, mic_name, enabled) in enumerate(audio_devices):
            if device_kind == "group":
                label = tr(
                    f"ui.dialog.voice_recognition.group.{str(mic_name).lower()}",
                    default=str(mic_name),
                )
            else:
                label = str(mic_name or tr("ui.dialog.voice_recognition.default_mic", default="Default microphone"))
            mic_editor.addItem(label, mic_index)
            item = mic_editor.model().item(idx)
            if item is not None and not enabled:
                item.setEnabled(False)
            if enabled and mic_index == current_mic:
                selected_index = idx
        mic_editor.setCurrentIndex(selected_index)

        sensitivity_editor = QSpinBox(dlg)
        sensitivity_editor.setRange(0, 100)
        sensitivity_editor.setValue(int(sensitivity))

        form.addRow(tr("ui.dialog.voice_recognition.microphone", default="Microphone:"), mic_editor)
        form.addRow(tr("ui.dialog.voice_recognition.sensitivity", default="Sensitivity:"), sensitivity_editor)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            dlg,
        )
        layout.addWidget(buttons)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)

        if dlg.exec() == QDialog.DialogCode.Accepted:
            mic_index = mic_editor.currentData()
            node.set_voice_recognition_config(mic_index, sensitivity_editor.value())
            self.update()

    def _remove_missing_dynamic_wires(self, node_id: str, old_pins: set[str]) -> None:
        node = self._runtime.get_node(node_id)
        if not node:
            return
        new_pins = self._dynamic_pin_names(node)
        removed_pins = old_pins - new_pins
        if not removed_pins:
            return
        for wire in list(self._runtime.wires.values()):
            if ((wire.src_node == node_id and wire.src_pin in removed_pins) or
                    (wire.dst_node == node_id and wire.dst_pin in removed_pins)):
                self._runtime.remove_wire(wire.wire_id)

    def _dynamic_pin_names(self, node: NodeBase) -> set[str]:
        names: set[str] = set()
        for method_name in ("get_dynamic_output_pin_names", "get_dynamic_input_pin_names"):
            if hasattr(node, method_name):
                try:
                    names.update(getattr(node, method_name)())
                except Exception:
                    pass
        return names

    def _move_dynamic_field(self, node_id: str, index: int, delta: int) -> None:
        node = self._runtime.get_node(node_id)
        if not node or not hasattr(node, "move_dynamic_field"):
            return
        node.move_dynamic_field(index, delta)
        self.update()

    def _set_channel_count(self, node_id: str, count: int) -> None:
        """
        Change the channel count of a MUX/DEMUX node.
        Wires connected to pins being removed are deleted first (with undo support).
        """
        node = self._runtime.get_node(node_id)
        if not node or not hasattr(node, "get_channel_count"):
            return
        old_count = node.get_channel_count()
        if count == old_count:
            return
        # Determine which pin names will disappear
        is_mux = any(p.name.startswith("in_") for p in node.PINS
                     if p.direction.name == "INPUT")
        prefix = "in_" if is_mux else "out_"
        removed_pins = {f"{prefix}{i}" for i in range(count, old_count)}
        dead_wires = [
            w for w in self._runtime.wires.values()
            if (w.src_node == node_id and w.src_pin in removed_pins) or
               (w.dst_node == node_id and w.dst_pin in removed_pins)
        ]
        if dead_wires or True:   # always wrap in a macro for clean undo
            self._history.begin_macro(f"Set channel count → {count}")
            for wire in dead_wires:
                self._runtime.remove_wire(wire.wire_id)
                self._history.push(WireDeleteCmd(self._runtime, wire))
            node.set_channel_count(count)
            self._history.end_macro()
        self.update()

    def _set_sample_count(self, node_id: str, count: int) -> None:
        node = self._runtime.get_node(node_id)
        if not node or not hasattr(node, "set_sample_count"):
            return
        node.set_sample_count(count)
        self.update()

    def _set_waveform_range(self, node_id: str, mode: str) -> None:
        node = self._runtime.get_node(node_id)
        if not node or not hasattr(node, "set_waveform_range"):
            return
        node.set_waveform_range(mode)
        self.update()

    def _open_waveform_custom_range_dialog(self, node_id: str) -> None:
        node = self._runtime.get_node(node_id)
        if not node or not hasattr(node, "get_custom_range"):
            return
        old_min, old_max = node.get_custom_range()

        dlg = QDialog(self)
        dlg.setWindowTitle(tr("ui.dialog.waveform_range.title", default="Waveform Y-Axis Range"))
        dlg.setStyleSheet("""
            QDialog      { background: #220d14; color: #ffd0de; }
            QLabel        { color: #ffd0de; font-family: 'Segoe UI'; font-size: 9pt; }
            QDoubleSpinBox {
                background: #2a0e1a; color: #ffd0de;
                border: 1px solid #45072f; border-radius: 3px;
                padding: 3px 6px; font-family: 'Courier New'; font-size: 9pt;
            }
            QDoubleSpinBox:focus { border-color: #c90084; }
            QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
                background: #3a0d22; border: none; width: 16px;
            }
            QPushButton {
                background: #3a0d22; color: #ffd0de;
                border: 1px solid #45072f; border-radius: 3px;
                padding: 4px 12px; font-family: 'Segoe UI'; font-size: 9pt;
            }
            QPushButton:hover   { background: #c90084; border-color: #c90084; }
            QPushButton:default { border-color: #c90084; }
        """)

        layout = QFormLayout(dlg)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        min_spin = QDoubleSpinBox()
        min_spin.setRange(-1e9, 1e9)
        min_spin.setDecimals(4)
        min_spin.setSingleStep(0.1)
        min_spin.setValue(old_min)

        max_spin = QDoubleSpinBox()
        max_spin.setRange(-1e9, 1e9)
        max_spin.setDecimals(4)
        max_spin.setSingleStep(0.1)
        max_spin.setValue(old_max)

        layout.addRow("Min:", min_spin)
        layout.addRow("Max:", max_spin)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addRow(buttons)

        if dlg.exec() == QDialog.DialogCode.Accepted:
            new_min = min_spin.value()
            new_max = max_spin.value()
            if new_min != old_min or new_max != old_max:
                node.set_custom_range(new_min, new_max)
            self.update()

    def _open_sample_count_dialog(self, node_id: str) -> None:
        node = self._runtime.get_node(node_id)
        if not node or not hasattr(node, "get_custom_sample_count"):
            return
        old_count = node.get_custom_sample_count()

        dlg = QDialog(self)
        dlg.setWindowTitle(tr("ui.dialog.sample_count.title", default="Sample Count"))
        dlg.setStyleSheet("""
            QDialog      { background: #220d14; color: #ffd0de; }
            QLabel        { color: #ffd0de; font-family: 'Segoe UI'; font-size: 9pt; }
            QSpinBox {
                background: #2a0e1a; color: #ffd0de;
                border: 1px solid #45072f; border-radius: 3px;
                padding: 3px 6px; font-family: 'Courier New'; font-size: 9pt;
            }
            QSpinBox:focus { border-color: #c90084; }
            QSpinBox::up-button, QSpinBox::down-button {
                background: #3a0d22; border: none; width: 16px;
            }
            QPushButton {
                background: #3a0d22; color: #ffd0de;
                border: 1px solid #45072f; border-radius: 3px;
                padding: 4px 12px; font-family: 'Segoe UI'; font-size: 9pt;
            }
            QPushButton:hover   { background: #c90084; border-color: #c90084; }
            QPushButton:default { border-color: #c90084; }
        """)

        layout = QFormLayout(dlg)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        count_spin = QSpinBox()
        count_spin.setRange(10, 500)
        count_spin.setSingleStep(10)
        count_spin.setValue(old_count)

        layout.addRow("Count:", count_spin)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addRow(buttons)

        if dlg.exec() == QDialog.DialogCode.Accepted:
            new_count = count_spin.value()
            if new_count != old_count:
                node.set_custom_sample_count(new_count)
            self.update()

    def _delete_node(self, node_id: str) -> None:
        self._selected_nodes = {node_id}
        self._selected_node  = node_id
        self._delete_selected_nodes("Delete")

    def _trigger_ctrl_label_editor(self, node_id: str) -> None:
        node = self._runtime.get_node(node_id)
        if not node:
            return
        ctrl_rect = self._get_ctrl_rect(node_id)
        if ctrl_rect is None:
            return
        lbl_rect = (node.ctrl_label_rect(ctrl_rect)  # type: ignore[union-attr]
                    if hasattr(node, "ctrl_label_rect") else ctrl_rect)
        self._open_ctrl_label_editor(node, lbl_rect)

    def _open_ctrl_color_picker(self, node_id: str) -> None:
        node = self._runtime.get_node(node_id)
        if not node or not hasattr(node, "get_ctrl_color"):
            return
        old_color = node.get_ctrl_color()
        initial   = _parse_hex_to_qcolor(str(old_color))
        color     = QColorDialog.getColor(initial, self, "Button color")
        if color.isValid():
            new_color = f"#{color.red():02x}{color.green():02x}{color.blue():02x}"
            if new_color != old_color:
                node.set_ctrl_color(new_color)
                self._history.push(CtrlPropCmd(
                    self._runtime, node_id,
                    "set_ctrl_color", old_color, new_color, "Button color",
                ))
            self.update()

    def _open_ctrl_range_dialog(self, node_id: str) -> None:
        node = self._runtime.get_node(node_id)
        if not node or not hasattr(node, "get_ctrl_range"):
            return
        old_min, old_max = node.get_ctrl_range()

        dlg = QDialog(self)
        dlg.setWindowTitle(tr("ui.dialog.slider_range.title"))
        dlg.setStyleSheet("""
            QDialog      { background: #220d14; color: #ffd0de; }
            QLabel        { color: #ffd0de; font-family: 'Segoe UI'; font-size: 9pt; }
            QDoubleSpinBox {
                background: #2a0e1a; color: #ffd0de;
                border: 1px solid #45072f; border-radius: 3px;
                padding: 3px 6px; font-family: 'Courier New'; font-size: 9pt;
            }
            QDoubleSpinBox:focus { border-color: #c90084; }
            QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
                background: #3a0d22; border: none; width: 16px;
            }
            QPushButton {
                background: #3a0d22; color: #ffd0de;
                border: 1px solid #45072f; border-radius: 3px;
                padding: 4px 12px; font-family: 'Segoe UI'; font-size: 9pt;
            }
            QPushButton:hover   { background: #c90084; border-color: #c90084; }
            QPushButton:default { border-color: #c90084; }
        """)

        layout = QFormLayout(dlg)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        min_spin = QDoubleSpinBox()
        min_spin.setRange(-1e9, 1e9)
        min_spin.setDecimals(4)
        min_spin.setSingleStep(0.1)
        min_spin.setValue(old_min)

        max_spin = QDoubleSpinBox()
        max_spin.setRange(-1e9, 1e9)
        max_spin.setDecimals(4)
        max_spin.setSingleStep(0.1)
        max_spin.setValue(old_max)

        layout.addRow("Min:", min_spin)
        layout.addRow("Max:", max_spin)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addRow(buttons)

        if dlg.exec() == QDialog.DialogCode.Accepted:
            new_min = min_spin.value()
            new_max = max_spin.value()
            if new_min != old_min or new_max != old_max:
                node.set_ctrl_range(new_min, new_max)
                self._history.push(CtrlPropCmd(
                    self._runtime, node_id,
                    "set_ctrl_range", (old_min, old_max), (new_min, new_max), "Set range",
                ))
            self.update()

    def _set_ctrl_scale(self, node_id: str, mode: str) -> None:
        node = self._runtime.get_node(node_id)
        if not node or not hasattr(node, "set_ctrl_scale"):
            return
        old_mode = node.get_ctrl_scale()
        if old_mode == mode:
            return
        node.set_ctrl_scale(mode)
        self._history.push(CtrlPropCmd(
            self._runtime, node_id,
            "set_ctrl_scale", old_mode, mode, "Scale mode",
        ))
        self.update()

    def _set_touchpad_mode(self, node_id: str, mode: str) -> None:
        node = self._runtime.get_node(node_id)
        if not node or not hasattr(node, "set_touchpad_mode"):
            return
        old_mode = node.get_touchpad_mode()
        if old_mode == mode:
            return
        node.set_touchpad_mode(mode)
        self._history.push(CtrlPropCmd(
            self._runtime, node_id,
            "set_touchpad_mode", old_mode, mode, "Touchpad mode",
        ))
        self.update()

    def _show_context_menu(self, global_pos, scene_pos: QPointF) -> None:
        menu = QMenu(self)
        menu.setStyleSheet(_MENU_STYLE)

        search_act = QAction(tr("ui.canvas.menu.search_nodes"), menu)
        search_act.triggered.connect(lambda: self._open_node_search(global_pos, scene_pos))
        menu.addAction(search_act)

        add_grp = QAction(tr("ui.canvas.menu.add_group"), menu)
        add_grp.triggered.connect(lambda: self._add_group(scene_pos))
        menu.addAction(add_grp)
        menu.addSeparator()

        structure = self._node_menu_fn()

        # Build nested menus from "/" delimited group paths
        # e.g. "Devices/Lovense/Domi" → Menu > Lovense > Domi > [actions]
        # Cache of path → QMenu so we reuse parent menus
        submenu_cache: dict[str, QMenu] = {}

        def _get_or_create_submenu(path: str, parent: QMenu) -> QMenu:
            if path in submenu_cache:
                return submenu_cache[path]
            parts = path.split("/")
            cur_parent = parent
            built_path = ""
            for part in parts:
                built_path = (built_path + "/" + part).lstrip("/")
                if built_path not in submenu_cache:
                    sub = QMenu(part, cur_parent)
                    sub.setStyleSheet(_MENU_STYLE)
                    cur_parent.addMenu(sub)
                    submenu_cache[built_path] = sub
                cur_parent = submenu_cache[built_path]
            return cur_parent

        for group, items in sorted(structure.items()):
            sub = _get_or_create_submenu(group, menu)
            for name, key in sorted(items):
                a = QAction(name, sub)
                a.setData((key, scene_pos))
                a.triggered.connect(self._on_add_action)
                sub.addAction(a)

        menu.exec(global_pos)

    def _on_add_action(self) -> None:
        a: QAction = self.sender()
        key, sp    = a.data()
        self._add_node_at(key, sp)

    def _add_node_at(self, key: str, sp: QPointF) -> None:
        """Add a node by type-key at scene position sp and push to undo history."""
        # Capture what gets created — node_added is synchronous on the main thread
        _created: list[str] = []
        def _on_added(nid: str) -> None:
            _created.append(nid)
        self._runtime.node_added.connect(_on_added)
        self.status_message.emit(f"__add_node__{key}__{sp.x()}__{sp.y()}")
        self._runtime.node_added.disconnect(_on_added)
        if _created:
            node = self._runtime.get_node(_created[0])
            if node:
                self._history.push(NodeAddCmd(self._runtime, node))

    def _open_node_search(self, global_pos: QPoint, scene_pos: QPointF) -> None:
        """Open the floating node search popup."""
        structure = self._node_menu_fn()
        flat_nodes: list[tuple[str, str]] = []
        for group, items in sorted(structure.items()):
            display_group = group.replace("/", " › ")
            for name, key in sorted(items):
                flat_nodes.append((f"{display_group} / {name}", key))

        popup = _NodeSearchPopup(flat_nodes, scene_pos, self)
        popup.node_selected.connect(self._add_node_at)
        popup.move(global_pos)
        popup.show()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_hex_to_qcolor(s: str) -> QColor:
    """Parse #RRGGBB or #RRGGBBAA into QColor."""
    s = (s or "").strip()
    if not s.startswith("#") or len(s) < 7:
        return QColor(255, 255, 255)
    s = s[1:]
    try:
        r = int(s[0:2], 16)
        g = int(s[2:4], 16)
        b = int(s[4:6], 16)
        return QColor(r, g, b)
    except ValueError:
        return QColor(255, 255, 255)


def _format_value(val, typ: type, dim: bool) -> tuple[str, QColor]:
    """Return (display_string, QColor) for a field value."""
    if typ is bool:
        v     = bool(val)
        label = "true" if v else "false"
        if dim:
            return label, QColor("#4a5040" if v else "#504040")
        return label, QColor("#4caf50" if v else "#ef5350")
    elif typ is float:
        label = f"{float(val):.4g}" if val is not None else "0"
        return label, QColor("#3a7080" if dim else "#4fc3f7")
    elif typ is int:
        label = str(int(val)) if val is not None else "0"
        return label, QColor("#607040" if dim else "#aed581")
    else:
        label = str(val) if val is not None else ""
        if len(label) > 18:
            label = label[:15] + "…"
        return label, QColor("#604080" if dim else "#ce93d8")


_MENU_STYLE = """
QMenu {
    background-color: #220d14; color: #ffd0de;
    border: 1px solid #45072f; border-radius: 4px;
    padding: 4px; font-family: 'Segoe UI'; font-size: 9pt;
}
QMenu::item:selected { background-color: #c90084; border-radius: 3px; }
QMenu::item          { padding: 4px 20px 4px 12px; }
QMenu::separator     { background: #45072f; height: 1px; margin: 4px 8px; }
"""

_SEARCH_POPUP_STYLE = """
QFrame {
    background: #220d14; border: 1px solid #45072f; border-radius: 6px;
}
QLineEdit {
    background: #2a0e1a; color: #ffd0de;
    border: 1px solid #45072f; border-radius: 3px;
    padding: 5px 8px; font-family: 'Segoe UI'; font-size: 10pt;
}
QLineEdit:focus { border-color: #c90084; }
QListWidget {
    background: #220d14; color: #ffd0de;
    border: none; outline: none;
    font-family: 'Segoe UI'; font-size: 9pt;
}
QListWidget::item { padding: 4px 10px; border-radius: 3px; }
QListWidget::item:selected { background: #c90084; color: #fff; }
QListWidget::item:hover { background: #3a0d22; }
QScrollBar:vertical { width: 6px; background: #1a0510; border: none; }
QScrollBar::handle:vertical { background: #45072f; border-radius: 3px; min-height: 20px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""


class _NodeSearchPopup(QFrame):
    """Floating search popup for quick node addition via the right-click menu."""

    node_selected = pyqtSignal(str, QPointF)  # (node_key, scene_pos)

    def __init__(
        self,
        flat_nodes: list[tuple[str, str]],
        scene_pos: QPointF,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self._flat_nodes = flat_nodes
        self._scene_pos = scene_pos

        self.setStyleSheet(_SEARCH_POPUP_STYLE)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        self._search = QLineEdit()
        self._search.setPlaceholderText(tr("ui.canvas.menu.search_nodes"))
        layout.addWidget(self._search)

        self._list = QListWidget()
        self._list.setFixedHeight(260)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.itemActivated.connect(self._confirm_selection)
        layout.addWidget(self._list)

        self._search.textChanged.connect(self._filter)
        self._search.installEventFilter(self)
        self._list.installEventFilter(self)

        self.setFixedWidth(320)
        self._populate(flat_nodes)

    # ── population / filtering ─────────────────────────────────────────────

    def _populate(self, nodes: list[tuple[str, str]]) -> None:
        self._list.clear()
        for label, key in nodes:
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, key)
            self._list.addItem(item)
        if self._list.count():
            self._list.setCurrentRow(0)

    def _filter(self, text: str) -> None:
        q = text.strip().lower()
        filtered = [
            (lbl, key) for lbl, key in self._flat_nodes
            if not q or q in lbl.lower()
        ]
        self._populate(filtered)

    # ── selection ──────────────────────────────────────────────────────────

    def _confirm_selection(self, item: QListWidgetItem | None = None) -> None:
        if item is None:
            item = self._list.currentItem()
        if item:
            key = item.data(Qt.ItemDataRole.UserRole)
            if key:
                self.node_selected.emit(key, self._scene_pos)
        self.close()

    # ── keyboard routing ───────────────────────────────────────────────────

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if obj is self._search:
                if key == Qt.Key.Key_Down:
                    self._list.setFocus()
                    if self._list.count():
                        self._list.setCurrentRow(0)
                    return True
                if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    self._confirm_selection()
                    return True
                if key == Qt.Key.Key_Escape:
                    self.close()
                    return True
            elif obj is self._list:
                if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    self._confirm_selection()
                    return True
                if key == Qt.Key.Key_Escape:
                    self.close()
                    return True
                # Any printable key while list is focused → redirect to search bar
                if key not in (
                    Qt.Key.Key_Up, Qt.Key.Key_Down,
                    Qt.Key.Key_PageUp, Qt.Key.Key_PageDown,
                    Qt.Key.Key_Home, Qt.Key.Key_End,
                ):
                    self._search.setFocus()
                    self._search.event(event)
                    return True
        return super().eventFilter(obj, event)

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        self._search.setFocus()
