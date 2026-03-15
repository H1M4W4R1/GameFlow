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

from PyQt6.QtCore import Qt, QPointF, QRectF, QPoint, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QAction, QBrush, QColor, QFont, QKeyEvent, QLinearGradient,
    QMouseEvent, QPaintEvent, QPainter, QPainterPath, QPen,
    QRadialGradient, QWheelEvent,
)
from PyQt6.QtWidgets import QLineEdit, QMenu, QWidget, QToolTip

from core.graph_runtime import GraphRuntime
from core.node_base import NodeBase
from core.types import (
    PIN_COLORS, PIN_COMPATIBILITY, PinDescriptor,
    PinDirection, PinType, WireDescriptor,
)

log = logging.getLogger(__name__)

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

PIN_RADIUS   = 6.0
TITLE_H      = 28.0
ROW_H        = 22.0      # height of every row (pin, var-input, field)
ROW_PAD      = 2.0       # vertical gap between rows
ROW_MARGIN   = 6.0       # top/bottom padding inside body
NODE_RADIUS  = 8.0
GRID_MINOR   = 20
GRID_MAJOR   = 100
LABEL_W      = 58.0      # pixel width reserved for the left-side label in rows
FIELD_INSET  = 8.0       # horizontal inset for field pill from node edge


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


def _node_total_height(node: NodeBase) -> float:
    rows = _build_rows(node, TITLE_H)
    if not rows:
        return TITLE_H + ROW_MARGIN * 2
    last = rows[-1]
    return last.y + last.h + ROW_MARGIN


def _node_width(node: NodeBase) -> float:
    return max(node.MIN_WIDTH, 190.0)


# ── Canvas ────────────────────────────────────────────────────────────────────

class NodeEditorCanvas(QWidget):
    wire_created   = pyqtSignal(object)
    node_selected  = pyqtSignal(str)
    status_message = pyqtSignal(str)

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

        self._wire_src   : Optional[RenderedPin]  = None
        self._wire_mouse : QPointF                = QPointF()

        self._rendered_pins   : list[RenderedPin]   = []
        self._rendered_fields : list[RenderedField] = []
        self._rendered_wires  : list[tuple[str, QPainterPath]] = []  # (wire_id, path)
        self._selected_wire   : Optional[str]       = None
        self._active_editor   : Optional[QLineEdit] = None
        self._clipboard       : Optional[list[dict]] = None   # copied node states

        self._tab_index = 0

        # Hover state for tooltips
        self._hovered_pin:  Optional[RenderedPin]  = None
        self._hovered_node: Optional[str]          = None
        self._tooltip_timer = QTimer(self)
        self._tooltip_timer.setSingleShot(True)
        self._tooltip_timer.timeout.connect(self._show_hover_tooltip)
        self._last_mouse_view: QPointF = QPointF()

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)

        self._runtime.node_added.connect(lambda _: self.update())
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
        self._draw_wires(p)
        if self._wire_src:
            self._draw_pending_wire(p)
        self._rendered_pins.clear()
        self._rendered_fields.clear()
        for node in self._runtime.nodes.values():
            self._draw_node(p, node)
        p.restore()

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

    # ── Node ──────────────────────────────────────────────────────────────────

    def _draw_node(self, p: QPainter, node: NodeBase) -> None:
        selected = node.node_id == self._selected_node
        width    = _node_width(node)
        body_top = node.y + TITLE_H
        rows     = _build_rows(node, body_top)
        total_h  = _node_total_height(node)
        rect     = QRectF(node.x, node.y, width, total_h)

        # Shadow
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(0, 0, 0, 80)))
        p.drawRoundedRect(rect.adjusted(4, 4, 4, 4), NODE_RADIUS, NODE_RADIUS)

        # Body
        p.setPen(QPen(COL_NODE_SEL_BORDER if selected else COL_NODE_BORDER,
                      2 if selected else 1))
        p.setBrush(QBrush(QColor("#220d1430" if selected else "#220d14")))
        p.drawRoundedRect(rect, NODE_RADIUS, NODE_RADIUS)

        # Title bar
        title_rect = QRectF(node.x, node.y, width, TITLE_H)
        tp = QPainterPath()
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
            node.NODE_NAME,
        )

        # Device status dot
        from core.device_node_base import DeviceNodeBase
        if isinstance(node, DeviceNodeBase):
            node.paint_device_status(p, title_rect)

        # Draw each row
        for row in rows:
            if row.kind == _RowKind.PIN:
                self._draw_pin_row(p, node, row, width)
            elif row.kind == _RowKind.VAR:
                self._draw_var_row(p, node, row, width)
            elif row.kind == _RowKind.FIELD:
                self._draw_field_row(p, node, row, width)
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

    # ── Wire drawing ──────────────────────────────────────────────────────────

    def _draw_wires(self, p: QPainter) -> None:
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
            hp = self._hit_pin(scene)
            if hp:
                if hp.direction == PinDirection.OUTPUT:
                    self._wire_src = hp; self._wire_mouse = scene
                    self._selected_wire = None; self.update(); return
                elif self._wire_src:
                    self._try_connect(self._wire_src, hp)
                    self._wire_src = None; self.update(); return

            nid = self._hit_node(scene)
            if nid:
                self._selected_node = nid
                self._selected_wire  = None
                self._dragging_node = nid
                self._drag_start_scene = scene
                node = self._runtime.get_node(nid)
                if node:
                    self._drag_node_start = QPointF(node.x, node.y)
                self.node_selected.emit(nid)
                self.update(); return

            # Try wire hit
            wid = self._hit_wire(scene)
            if wid:
                self._selected_wire  = wid
                self._selected_node = None
                self.update(); return

            self._selected_node = None
            self._selected_wire  = None
            self.update()

        if event.button() == Qt.MouseButton.RightButton:
            if not self._hit_node(scene):
                self._show_context_menu(event.globalPosition().toPoint(), scene)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        self._last_mouse_view = event.position()
        # Update hover state for tooltips
        if not self._panning and not self._dragging_node and not self._wire_src:
            scene = self._v2s(event.position())
            hp = self._hit_pin(scene)
            new_hovered_pin  = hp
            new_hovered_node = self._hit_node(scene) if not hp else None
            if new_hovered_pin != self._hovered_pin or new_hovered_node != self._hovered_node:
                self._hovered_pin  = new_hovered_pin
                self._hovered_node = new_hovered_node
                self._tooltip_timer.stop()
                QToolTip.hideText()
                if new_hovered_pin or new_hovered_node:
                    self._tooltip_timer.start(500)
        if self._panning:
            self._offset = self._pan_offset_start + (event.position() - self._pan_start)
            self.update(); return
        if self._dragging_node:
            scene = self._v2s(event.position())
            node  = self._runtime.get_node(self._dragging_node)
            if node:
                node.x = self._drag_node_start.x() + scene.x() - self._drag_start_scene.x()
                node.y = self._drag_node_start.y() + scene.y() - self._drag_start_scene.y()
            self.update(); return
        if self._wire_src:
            self._wire_mouse = self._v2s(event.position()); self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging_node = None
            if self._wire_src:
                hp = self._hit_pin(self._v2s(event.position()))
                if hp and hp.direction == PinDirection.INPUT:
                    self._try_connect(self._wire_src, hp)
                self._wire_src = None; self.update()

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
        # Double-click on a DeviceNodeBase title bar → cycle device
        nid = self._hit_node(scene)
        if nid:
            node = self._runtime.get_node(nid)
            if node is not None:
                from core.device_node_base import DeviceNodeBase
                if isinstance(node, DeviceNodeBase):
                    node.cycle_device()
                    self.update()
                    return
        super().mouseDoubleClickEvent(event)

    def _open_editor(self, rf: RenderedField, view_pos: QPointF) -> None:
        self._close_editor()
        node = self._runtime.get_node(rf.node_id)
        if not node:
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
        current = (node.get_var_input(rf.field_name) if rf.is_var
                   else node.get_field(rf.field_name))
        editor.setText(str(current) if current is not None else "")
        editor.selectAll()
        editor.setGeometry(int(tl.x()), int(tl.y()),
                           int(br.x() - tl.x()), int(br.y() - tl.y()))
        editor.show()
        editor.setFocus()

        def _commit() -> None:
            if rf.is_var:
                node.set_var_input(rf.field_name, editor.text())
            else:
                node.set_field(rf.field_name, editor.text())
            self._close_editor()
            self.update()

        editor.returnPressed.connect(_commit)
        editor.editingFinished.connect(_commit)
        editor._cancel = self._close_editor  # type: ignore[attr-defined]
        editor.installEventFilter(self)
        self._active_editor = editor

    def _close_editor(self) -> None:
        if self._active_editor:
            self._active_editor.hide()
            self._active_editor.deleteLater()
            self._active_editor = None

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

    def keyPressEvent(self, event: QKeyEvent) -> None:
        ctrl = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)

        if event.key() == Qt.Key.Key_Delete:
            if self._selected_wire:
                self._runtime.remove_wire(self._selected_wire)
                self._selected_wire = None; self.update(); return
            if self._selected_node:
                self._runtime.remove_node(self._selected_node)
                self._selected_node = None; self.update(); return

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

        if event.key() == Qt.Key.Key_Escape:
            self._wire_src      = None
            self._selected_node = None
            self._selected_wire  = None
            self.update()

        super().keyPressEvent(event)

    def _copy_selected(self) -> None:
        if not self._selected_node:
            return
        node = self._runtime.get_node(self._selected_node)
        if node:
            import json
            self._clipboard = [{
                "type_key": f"{node.__class__.__module__}.{node.__class__.__name__}",
                "state":    node.get_state(),
                "dx": 30.0, "dy": 30.0,
            }]

    def _cut_selected(self) -> None:
        self._copy_selected()
        if self._selected_node:
            self._runtime.remove_node(self._selected_node)
            self._selected_node = None
            self.update()

    def _paste_clipboard(self) -> None:
        if not self._clipboard:
            return
        for entry in self._clipboard:
            self.status_message.emit(
                f"__add_node__{entry['type_key']}__"
                f"{self._v2s(QPointF(self.width()/2, self.height()/2)).x() + entry['dx']}__"
                f"{self._v2s(QPointF(self.width()/2, self.height()/2)).y() + entry['dy']}"
            )

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
        # Allow self-loops only for TICK pins (exec feedback loops)
        is_self_loop = src.node_id == dst.node_id
        if is_self_loop and src.pin_type != PinType.TICK:
            self.status_message.emit("Self-loops are only allowed for TICK pins")
            return
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
            self.wire_created.emit(wire)
        else:
            self.status_message.emit("Could not create wire")

    # ── Context menu ──────────────────────────────────────────────────────────

    def _show_context_menu(self, global_pos, scene_pos: QPointF) -> None:
        menu = QMenu(self)
        menu.setStyleSheet(_MENU_STYLE)
        structure = self._node_menu_fn()

        # Build nested menus from "/" delimited group paths
        # e.g. "Lovense/Domi" → Menu > Lovense > Domi > [actions]
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
        self.status_message.emit(f"__add_node__{key}__{sp.x()}__{sp.y()}")


# ── Helpers ───────────────────────────────────────────────────────────────────

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
