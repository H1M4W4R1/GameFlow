"""Rendering and hit-testing methods for NodeEditorCanvas."""

from typing import Optional

from PyQt6.QtCore import Qt, QPointF, QRectF
from PyQt6.QtGui import (
    QBrush, QColor, QFont, QLinearGradient,
    QPaintEvent, QPainter, QPainterPath, QPen,
    QRadialGradient,
)

from core.types import PinDirection, PinType
from ui.node_editor_layout import (
    COL_BG, COL_GRID_MAJOR, COL_GRID_MINOR, COL_NODE_BG, COL_NODE_BORDER,
    COL_NODE_SEL_BORDER, COL_PIN_TEXT, COL_TITLE_TEXT, COL_WIRE_SHADOW,
    DEVICE_SEL_H, FIELD_INSET, GRID_MAJOR, GRID_MINOR, GROUP_RESIZE_H,
    GROUP_TITLE_H, LABEL_W, NODE_RADIUS, PIN_RADIUS, ROW_MARGIN, TITLE_H,
    _RowKind, _build_rows, _device_sel_extra, _node_total_height, _node_width,
    RenderedPin, RenderedField, _pin_color, _node_display_name,
)


def _paint_event(canvas, p: QPainter) -> None:
    """Render the entire canvas. Called from NodeEditorCanvas.paintEvent()."""
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    p.fillRect(canvas.rect(), COL_BG)
    _draw_grid(canvas, p)
    p.save()
    p.translate(canvas._offset)
    p.scale(canvas._zoom, canvas._zoom)
    _draw_groups(canvas, p)
    canvas._rendered_pins.clear()
    canvas._rendered_fields.clear()
    canvas._rendered_device_selectors.clear()
    canvas._rendered_title_bars.clear()
    for node in canvas._runtime.nodes.values():
        _draw_node(canvas, p, node)
    _draw_wires(canvas, p)
    if canvas._wire_src:
        _draw_pending_wire(canvas, p)
    p.restore()
    if canvas._rubber_band_active:
        _draw_rubber_band(canvas, p)


def _draw_grid(canvas, p: QPainter) -> None:
    """Draw the background grid."""
    w, h = canvas.width(), canvas.height()
    for step, col in [
        (GRID_MINOR * canvas._zoom, COL_GRID_MINOR),
        (GRID_MAJOR * canvas._zoom, COL_GRID_MAJOR),
    ]:
        ox = canvas._offset.x() % step
        oy = canvas._offset.y() % step
        p.setPen(QPen(col, 1))
        x = ox
        while x < w:
            p.drawLine(int(x), 0, int(x), h)
            x += step
        y = oy
        while y < h:
            p.drawLine(0, int(y), w, int(y))
            y += step


def _draw_rubber_band(canvas, p: QPainter) -> None:
    """Draw the rubber-band selection rectangle in view (widget) coordinates."""
    ox, oy = canvas._rubber_band_origin.x(), canvas._rubber_band_origin.y()
    cx, cy = canvas._rubber_band_cur.x(),    canvas._rubber_band_cur.y()
    rect = QRectF(min(ox, cx), min(oy, cy), abs(cx - ox), abs(cy - oy))
    if rect.width() < 2 and rect.height() < 2:
        return
    p.setPen(QPen(QColor("#f95979"), 1, Qt.PenStyle.DashLine))
    p.setBrush(QBrush(QColor(249, 89, 121, 30)))
    p.drawRect(rect)


def _draw_groups(canvas, p: QPainter) -> None:
    """Draw all groups."""
    canvas._rendered_group_title_bars.clear()
    canvas._rendered_group_resize_handles.clear()
    for grp in canvas._groups.values():
        _draw_group(canvas, p, grp)


def _draw_group(canvas, p: QPainter, grp) -> None:
    """Draw a single group."""
    selected = grp.group_id == canvas._selected_group
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
    canvas._rendered_group_title_bars.append((grp.group_id, QRectF(tr)))

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
        canvas._rendered_group_resize_handles.append((grp.group_id, corner, hr))


def _draw_node(canvas, p: QPainter, node) -> None:
    """Draw a single node with all its pins, fields, and custom content."""
    selected  = node.node_id == canvas._selected_node or node.node_id in canvas._selected_nodes
    drag_hl   = node.node_id == canvas._drag_highlight_node
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
    canvas._rendered_title_bars.append((node.node_id, QRectF(title_rect)))

    # Device status dot + optional selector row
    from core.device_node_base import DeviceNodeBase
    if isinstance(node, DeviceNodeBase):
        node.paint_device_status(p, title_rect)
        if extra:
            sel_rect = QRectF(node.x, node.y + TITLE_H, width, DEVICE_SEL_H)
            _draw_device_selector(canvas, p, node, sel_rect)

    # Draw each row
    for row in rows:
        if row.kind == _RowKind.PIN:
            _draw_pin_row(canvas, p, node, row, width)
        elif row.kind == _RowKind.VAR:
            _draw_var_row(canvas, p, node, row, width)
        elif row.kind == _RowKind.FIELD:
            _draw_field_row(canvas, p, node, row, width)
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


def _draw_pin_row(canvas, p: QPainter, node, row, width: float) -> None:
    """Draw a PIN row with input and/or output pins."""
    cy = row.y + row.h / 2

    if row.in_pin:
        pin   = row.in_pin
        px    = node.x
        color = _pin_color(pin.pin_type)
        p.setPen(QPen(color.darker(140), 1.5))
        p.setBrush(QBrush(color))
        p.drawEllipse(QPointF(px, cy), PIN_RADIUS, PIN_RADIUS)
        canvas._rendered_pins.append(
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
        canvas._rendered_pins.append(
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


def _draw_var_row(canvas, p: QPainter, node, row, width: float) -> None:
    """
    Variable-input row: pin circle on the left edge, field pill on the right.
    When connected  → field shows live value, locked (dimmed).
    When free       → field shows local default, editable (bright border).
    """
    from ui.node_editor_dialogs import _format_value

    cy        = row.y + row.h / 2
    connected = canvas._runtime.is_pin_connected(node.node_id, row.var_name)
    val       = node.get_var_input(row.var_name)

    # Pin circle (always visible so users can wire it)
    if row.var_pin:
        px    = node.x
        color = _pin_color(row.var_pin.pin_type)
        p.setPen(QPen(color.darker(140), 1.5))
        p.setBrush(QBrush(color))
        p.drawEllipse(QPointF(px, cy), PIN_RADIUS, PIN_RADIUS)
        canvas._rendered_pins.append(
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
        canvas._rendered_fields.append(
            RenderedField(node.node_id, row.var_name, row.var_type, pill_rect, is_var=True)
        )


def _draw_field_row(canvas, p: QPainter, node, row, width: float) -> None:
    """Draw a FIELD row — plain editable field with no pin circle."""
    from ui.node_editor_dialogs import _format_value

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

    canvas._rendered_fields.append(
        RenderedField(node.node_id, row.field_name, row.field_type, pill_rect, is_var=False)
    )


def _draw_device_selector(canvas, p: QPainter, node, rect: QRectF) -> None:
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
    canvas._rendered_device_selectors.append((node.node_id, QRectF(rect)))


def _draw_wires(canvas, p: QPainter) -> None:
    """Draw all wires in the graph."""
    p.setBrush(Qt.BrushStyle.NoBrush)
    canvas._rendered_wires.clear()
    for wire in canvas._runtime.wires.values():
        sp = _find_pin_pos(canvas, wire.src_node, wire.src_pin)
        dp = _find_pin_pos(canvas, wire.dst_node, wire.dst_pin)
        if sp and dp:
            selected   = wire.wire_id == canvas._selected_wire
            self_loop  = wire.src_node == wire.dst_node
            if self_loop:
                path = _make_self_loop_path(canvas, sp.scene_pos, dp.scene_pos,
                                            wire.src_node)
            else:
                path = _make_bezier_path(sp.scene_pos, dp.scene_pos)
            canvas._rendered_wires.append((wire.wire_id, path))
            _draw_wire_path(p, path, sp.pin_type,
                            alpha=240 if selected else 220,
                            width=3.5 if selected else 2.5,
                            highlight=selected)


def _make_bezier_path(p1: QPointF, p2: QPointF) -> QPainterPath:
    """Generate a smooth cubic Bezier curve from p1 to p2."""
    dx   = abs(p2.x() - p1.x()) * 0.5 + 40
    path = QPainterPath(p1)
    path.cubicTo(QPointF(p1.x() + dx, p1.y()),
                 QPointF(p2.x() - dx, p2.y()), p2)
    return path


def _make_self_loop_path(canvas, p1: QPointF, p2: QPointF, node_id: str) -> QPainterPath:
    """
    Route a self-loop wire cleanly around the outside of the node.

    The wire exits the right edge of the output pin, curves down and
    around below the node, then enters the left edge at the input pin.
    This avoids the wire passing through the node body.
    """
    node = canvas._runtime.get_node(node_id)
    if node is None:
        return _make_bezier_path(p1, p2)

    nw   = _node_width(node)
    nh   = _node_total_height(node)
    # Bottom-centre of node in scene coords
    bot_y   = node.y + nh + 24      # 24 px clearance below node
    right_x = node.x + nw + 32      # 32 px clearance to the right

    path = QPainterPath(p1)
    path.cubicTo(
        QPointF(right_x,     p1.y()),       # ctrl1: swing right from output
        QPointF(right_x,     bot_y),        # ctrl2: drop below node
        QPointF((p1.x() + p2.x()) / 2, bot_y),  # mid-bottom
    )
    path.cubicTo(
        QPointF(node.x - 24, bot_y),        # ctrl3: come back from left
        QPointF(node.x - 24, p2.y()),       # ctrl4: rise to input height
        p2,
    )
    return path


def _draw_wire_path(p: QPainter, path: QPainterPath,
                    pt: PinType, alpha: int = 220,
                    width: float = 2.5, highlight: bool = False) -> None:
    """Draw a wire path with shadow and optional glow."""
    col = _pin_color(pt)
    col.setAlpha(alpha)
    p.setPen(QPen(COL_WIRE_SHADOW, width + 2))
    p.drawPath(path)
    if highlight:
        glow = QColor("#f95979")
        glow.setAlpha(80)
        p.setPen(QPen(glow, width + 6))
        p.drawPath(path)
    p.setPen(QPen(col, width))
    p.drawPath(path)


def _draw_pending_wire(canvas, p: QPainter) -> None:
    """Draw the wire being dragged from a source pin."""
    if canvas._wire_src:
        path = _make_bezier_path(canvas._wire_src.scene_pos, canvas._wire_mouse)
        _draw_wire_path(p, path, canvas._wire_src.pin_type, alpha=160, width=2.0)


# ── Hit Testing ────────────────────────────────────────────────────────────

def _hit_pin(canvas, sp: QPointF) -> Optional[RenderedPin]:
    """Check if point hits any pin; return the RenderedPin if so."""
    for rp in canvas._rendered_pins:
        dx = rp.scene_pos.x() - sp.x()
        dy = rp.scene_pos.y() - sp.y()
        if dx*dx + dy*dy <= (PIN_RADIUS + 3)**2:
            return rp
    return None


def _hit_field(canvas, sp: QPointF) -> Optional[RenderedField]:
    """Check if point hits any field; return the RenderedField if so."""
    for rf in canvas._rendered_fields:
        if rf.scene_rect.contains(sp):
            return rf
    return None


def _hit_node(canvas, sp: QPointF) -> Optional[str]:
    """Check if point hits any node; return node_id if so."""
    for node in reversed(list(canvas._runtime.nodes.values())):
        w = _node_width(node)
        h = _node_total_height(node)
        if QRectF(node.x, node.y, w, h).contains(sp):
            return node.node_id
    return None


def _hit_device_selector(canvas, sp: QPointF) -> Optional[str]:
    """Return node_id if sp is inside a device-selector pill row."""
    for node_id, rect in canvas._rendered_device_selectors:
        if rect.contains(sp):
            return node_id
    return None


def _hit_ctrl(canvas, sp: QPointF) -> Optional[tuple]:
    """Return (node_id, ctrl_rect) if sp falls inside a node's CUSTOM row."""
    for node in canvas._runtime.nodes.values():
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


def _hit_title_bar(canvas, sp: QPointF) -> Optional[str]:
    """Return node_id if sp is inside a node title bar."""
    for node_id, rect in canvas._rendered_title_bars:
        if rect.contains(sp):
            return node_id
    return None


def _hit_group_title(canvas, sp: QPointF) -> Optional[str]:
    """Return group_id if sp is inside a group title bar."""
    for gid, rect in canvas._rendered_group_title_bars:
        if rect.contains(sp):
            return gid
    return None


def _hit_group_resize(canvas, sp: QPointF) -> Optional[tuple]:
    """Return (group_id, corner) if sp is on a resize handle."""
    for gid, corner, rect in canvas._rendered_group_resize_handles:
        if rect.contains(sp):
            return gid, corner
    return None


def _hit_wire(canvas, scene_pos: QPointF, threshold: float = 6.0) -> Optional[str]:
    """Return wire_id of the wire closest to scene_pos within threshold px."""
    best_id   : Optional[str] = None
    best_dist : float         = threshold
    for wire_id, path in canvas._rendered_wires:
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


def _find_pin_pos(canvas, node_id: str, pin_name: str) -> Optional[RenderedPin]:
    """Find the RenderedPin for a given node and pin name."""
    for rp in canvas._rendered_pins:
        if rp.node_id == node_id and rp.pin_name == pin_name:
            return rp
    return None


def _get_ctrl_rect(canvas, node_id: str) -> Optional[QRectF]:
    """Return the CUSTOM row scene rect for a node, or None."""
    node = canvas._runtime.get_node(node_id)
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
