"""
Input event handlers and related methods extracted from node_editor_canvas.py.

This module contains all mouse event handlers, keyboard handlers, drag-and-drop
handlers, field editing, wire connection, clipboard operations, and navigation
helpers extracted from the NodeEditorCanvas class.

Methods should be called with 'canvas' as the first parameter since they are
module-level functions rather than class methods.
"""
from __future__ import annotations

import json as _json
import logging
from typing import Optional

from PyQt6.QtCore import Qt, QEvent, QPointF, QRectF, QPoint
from PyQt6.QtGui import (
    QAction, QCursor, QKeyEvent, QMouseEvent, QWheelEvent,
)
from PyQt6.QtWidgets import (
    QMenu, QToolTip, QLineEdit, QColorDialog
)

from core.command_history import (
    DeviceCycleCmd, DeviceSelectCmd,
    FieldEditCmd,
    GroupMoveCmd, GroupResizeCmd, GroupRenameCmd,
    NodeDeleteCmd, NodeMoveCmd, NodeRenameCmd,
    PasteCmd,
    WireAddCmd, WireDeleteCmd,
)
from core.types import (
    PinDirection, WireDescriptor,
    PIN_COMPATIBILITY,
)
from ui.node_editor_dialogs import _parse_hex_to_qcolor

log = logging.getLogger(__name__)

# Visual constants (reuse from canvas)
TITLE_H = 28.0
DEVICE_SEL_H = 24.0
ROW_H = 22.0
ROW_PAD = 2.0
ROW_MARGIN = 6.0
GRID_MINOR = 20
GRID_MAJOR = 100
GROUP_MIN_W = 60
GROUP_MIN_H = 60
LABEL_W = 58.0
FIELD_INSET = 8.0

_MENU_STYLE = """
QMenu {
    background-color: #220d14; color: #ffd0de;
    border: 1px solid #45072f; border-radius: 4px;
    padding: 4px; font-family: 'Sergoe UI'; font-size: 9pt;
}
QMenu::item:selected { background-color: #c90084; border-radius: 3px; }
QMenu::item          { padding: 4px 20px 4px 12px; }
QMenu::separator     { background: #45072f; height: 1px; margin: 4px 8px; }
"""


# ── Mouse Event Handlers ──────────────────────────────────────────────────────

def mousePressEvent(canvas, event: QMouseEvent) -> None:
    scene = canvas._v2s(event.position())

    if event.button() == Qt.MouseButton.MiddleButton:
        canvas._panning          = True
        canvas._pan_start        = event.position()
        canvas._pan_offset_start = QPointF(canvas._offset)
        canvas.setCursor(Qt.CursorShape.ClosedHandCursor)
        return

    if event.button() == Qt.MouseButton.LeftButton:
        # Group resize handle
        res = canvas._hit_group_resize(scene)
        if res:
            gid, corner = res
            grp = canvas._groups[gid]
            canvas._resizing_group      = gid
            canvas._resize_corner       = corner
            canvas._resize_group_start  = QRectF(grp.x, grp.y, grp.width, grp.height)
            canvas._resize_mouse_start  = scene
            canvas._selected_group      = gid
            canvas._selected_node       = None
            canvas._selected_wire       = None
            canvas.update(); return

        # Group title bar drag (only when no node is under cursor)
        gt_gid = canvas._hit_group_title(scene)
        if gt_gid and not canvas._hit_node(scene):
            grp = canvas._groups[gt_gid]
            canvas._dragging_group       = gt_gid
            canvas._drag_group_start     = scene
            canvas._drag_group_pos_start = QPointF(grp.x, grp.y)
            canvas._drag_group_nodes_start = {
                nid: QPointF(n.x, n.y)
                for nid in grp.node_ids
                if (n := canvas._runtime.get_node(nid)) is not None
            }
            canvas._selected_group = gt_gid
            canvas._selected_node  = None
            canvas._selected_wire  = None
            canvas.update(); return

        hp = canvas._hit_pin(scene)
        if hp:
            if hp.direction == PinDirection.OUTPUT:
                canvas._wire_src = hp; canvas._wire_mouse = scene
                canvas._selected_wire = None; canvas.update(); return
            elif canvas._wire_src:
                _try_connect(canvas, canvas._wire_src, hp)
                canvas._wire_src = None; canvas.update(); return

        # Control-panel node interaction (Slider, Button, Toggle, etc.)
        if not canvas._wire_src:
            ctrl_hit = canvas._hit_ctrl(scene)
            if ctrl_hit:
                nid, rect = ctrl_hit
                node = canvas._runtime.get_node(nid)
                if node and node.on_ctrl_press(scene, rect, event.modifiers()):
                    canvas._ctrl_node_id   = nid
                    canvas._ctrl_rect      = rect
                    if node.should_select_on_ctrl_press():
                        canvas._selected_node  = nid
                        canvas._selected_nodes = {nid}
                        canvas._selected_wire  = None
                        canvas.node_selected.emit(nid)
                    canvas.update()
                    return

        # Device-selector pill click — show device picker menu
        ds_nid = canvas._hit_device_selector(scene)
        if ds_nid:
            node = canvas._runtime.get_node(ds_nid)
            if node is not None:
                from core.device_node_base import DeviceNodeBase, get_instances
                if isinstance(node, DeviceNodeBase) and node.DEVICE_TYPE_KEY:
                    instances = get_instances(node.DEVICE_TYPE_KEY)
                    if instances:
                        _show_device_menu(canvas, node, instances,
                                         event.globalPosition().toPoint())
            canvas._selected_node = ds_nid
            canvas._selected_wire = None
            node_obj = canvas._runtime.get_node(ds_nid)
            from core.device_node_base import DeviceNodeBase
            _dev = node_obj.get_device() if isinstance(node_obj, DeviceNodeBase) else None
            canvas.device_highlighted.emit(_dev.device_id if _dev else None)
            canvas.node_selected.emit(ds_nid)
            canvas.update()
            return

        nid = canvas._hit_node(scene)
        if nid:
            shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            if shift:
                # Shift+click: toggle this node in/out of multi-select
                if nid in canvas._selected_nodes:
                    canvas._selected_nodes.discard(nid)
                else:
                    canvas._selected_nodes.add(nid)
                canvas._selected_node  = nid if nid in canvas._selected_nodes else None
                canvas._selected_wire  = None
                canvas._selected_group = None
                canvas.update(); return

            # Normal click — keep existing multi-selection if this node is in it,
            # otherwise collapse to single selection
            if nid not in canvas._selected_nodes:
                canvas._selected_nodes = {nid}
            canvas._selected_node  = nid
            canvas._selected_wire  = None
            canvas._selected_group = None
            canvas._dragging_node  = nid
            canvas._drag_start_scene = scene
            node = canvas._runtime.get_node(nid)
            if node:
                canvas._drag_node_start = QPointF(node.x, node.y)
            # Store starting positions of ALL selected nodes for multi-drag
            canvas._drag_nodes_start = {}
            for sid in canvas._selected_nodes:
                sn = canvas._runtime.get_node(sid)
                if sn:
                    canvas._drag_nodes_start[sid] = QPointF(sn.x, sn.y)
            canvas.node_selected.emit(nid)
            # Highlight the specific device this node is using
            node_obj = canvas._runtime.get_node(nid)
            from core.device_node_base import DeviceNodeBase
            _dev = node_obj.get_device() if isinstance(node_obj, DeviceNodeBase) else None
            canvas.device_highlighted.emit(_dev.device_id if _dev else None)
            canvas.update(); return

        # Try wire hit
        wid = canvas._hit_wire(scene)
        if wid:
            canvas._selected_wire  = wid
            canvas._selected_node = None
            canvas.update(); return

        canvas._selected_node  = None
        canvas._selected_nodes = set()
        canvas._selected_wire  = None
        canvas._selected_group = None
        canvas.device_highlighted.emit(None)
        # Start rubber-band selection
        canvas._rubber_band_active = True
        canvas._rubber_band_origin = event.position()
        canvas._rubber_band_cur    = event.position()
        canvas.update()

    if event.button() == Qt.MouseButton.RightButton:
        nid = canvas._hit_node(scene)
        if nid:
            canvas._show_node_context_menu(nid, event.globalPosition().toPoint())
        else:
            canvas._show_context_menu(event.globalPosition().toPoint(), scene)


def mouseMoveEvent(canvas, event: QMouseEvent) -> None:
    canvas._last_mouse_view = event.position()
    # Update hover state for tooltips
    if not canvas._panning and not canvas._dragging_node and not canvas._wire_src:
        scene = canvas._v2s(event.position())
        hp = canvas._hit_pin(scene)
        new_hovered_pin  = hp
        new_hovered_node = canvas._hit_node(scene) if not hp else None
        if new_hovered_pin != canvas._hovered_pin or new_hovered_node != canvas._hovered_node:
            canvas._hovered_pin  = new_hovered_pin
            canvas._hovered_node = new_hovered_node
            canvas._tooltip_timer.stop()
            QToolTip.hideText()
            if new_hovered_pin or new_hovered_node:
                canvas._tooltip_timer.start(500)
    if canvas._resizing_group:
        scene = canvas._v2s(event.position())
        grp   = canvas._groups.get(canvas._resizing_group)
        if grp and canvas._resize_group_start:
            dx = scene.x() - canvas._resize_mouse_start.x()
            dy = scene.y() - canvas._resize_mouse_start.y()
            sr = canvas._resize_group_start
            snap = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            if "e" in canvas._resize_corner:
                raw = sr.width() + dx
                if snap: raw = round(raw / GRID_MINOR) * GRID_MINOR
                grp.width  = max(GROUP_MIN_W, raw)
            if "s" in canvas._resize_corner:
                raw = sr.height() + dy
                if snap: raw = round(raw / GRID_MINOR) * GRID_MINOR
                grp.height = max(GROUP_MIN_H, raw)
            if "w" in canvas._resize_corner:
                nw = sr.width() - dx
                if snap: nw = round(nw / GRID_MINOR) * GRID_MINOR
                if nw >= GROUP_MIN_W:
                    grp.x = sr.right() - nw; grp.width = nw
            if "n" in canvas._resize_corner:
                nh = sr.height() - dy
                if snap: nh = round(nh / GRID_MINOR) * GRID_MINOR
                if nh >= GROUP_MIN_H:
                    grp.y = sr.bottom() - nh; grp.height = nh
        canvas.update(); return

    if canvas._dragging_group:
        scene = canvas._v2s(event.position())
        grp   = canvas._groups.get(canvas._dragging_group)
        if grp:
            dx = scene.x() - canvas._drag_group_start.x()
            dy = scene.y() - canvas._drag_group_start.y()
            raw_x = canvas._drag_group_pos_start.x() + dx
            raw_y = canvas._drag_group_pos_start.y() + dy
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                raw_x = round(raw_x / GRID_MINOR) * GRID_MINOR
                raw_y = round(raw_y / GRID_MINOR) * GRID_MINOR
            snap_dx = raw_x - canvas._drag_group_pos_start.x()
            snap_dy = raw_y - canvas._drag_group_pos_start.y()
            grp.x = raw_x
            grp.y = raw_y
            for nid, sp in canvas._drag_group_nodes_start.items():
                n = canvas._runtime.get_node(nid)
                if n:
                    n.x = sp.x() + snap_dx
                    n.y = sp.y() + snap_dy
        canvas.update(); return

    if canvas._rubber_band_active:
        canvas._rubber_band_cur = event.position()
        origin_s = canvas._v2s(canvas._rubber_band_origin)
        cur_s    = canvas._v2s(canvas._rubber_band_cur)
        sel_rect = QRectF(
            min(origin_s.x(), cur_s.x()), min(origin_s.y(), cur_s.y()),
            abs(cur_s.x() - origin_s.x()), abs(cur_s.y() - origin_s.y()),
        )
        new_sel: set = set()
        for node in canvas._runtime.nodes.values():
            from ui.node_editor_canvas import _node_width, _node_total_height
            nr = QRectF(node.x, node.y, _node_width(node), _node_total_height(node))
            if sel_rect.intersects(nr):
                new_sel.add(node.node_id)
        canvas._selected_nodes = new_sel
        canvas._selected_node  = next(iter(new_sel)) if len(new_sel) == 1 else None
        canvas.update(); return

    if canvas._ctrl_node_id:
        scene = canvas._v2s(event.position())
        node  = canvas._runtime.get_node(canvas._ctrl_node_id)
        if node and canvas._ctrl_rect:
            node.on_ctrl_drag(scene, canvas._ctrl_rect)
        canvas.update(); return

    if canvas._panning:
        canvas._offset = canvas._pan_offset_start + (event.position() - canvas._pan_start)
        canvas.update(); return
    if canvas._dragging_node:
        scene = canvas._v2s(event.position())
        dx = scene.x() - canvas._drag_start_scene.x()
        dy = scene.y() - canvas._drag_start_scene.y()
        snap = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        if len(canvas._drag_nodes_start) > 1:
            for sid, sp in canvas._drag_nodes_start.items():
                sn = canvas._runtime.get_node(sid)
                if sn:
                    raw_x = sp.x() + dx
                    raw_y = sp.y() + dy
                    if snap:
                        raw_x = round(raw_x / GRID_MINOR) * GRID_MINOR
                        raw_y = round(raw_y / GRID_MINOR) * GRID_MINOR
                    sn.x = raw_x
                    sn.y = raw_y
        else:
            node = canvas._runtime.get_node(canvas._dragging_node)
            if node:
                raw_x = canvas._drag_node_start.x() + dx
                raw_y = canvas._drag_node_start.y() + dy
                if snap:
                    raw_x = round(raw_x / GRID_MINOR) * GRID_MINOR
                    raw_y = round(raw_y / GRID_MINOR) * GRID_MINOR
                node.x = raw_x
                node.y = raw_y
        canvas.update(); return
    if canvas._wire_src:
        canvas._wire_mouse = canvas._v2s(event.position()); canvas.update()


def mouseReleaseEvent(canvas, event: QMouseEvent) -> None:
    if event.button() == Qt.MouseButton.MiddleButton:
        canvas._panning = False
        canvas.setCursor(Qt.CursorShape.ArrowCursor)
    if event.button() == Qt.MouseButton.LeftButton:
        if canvas._ctrl_node_id:
            node = canvas._runtime.get_node(canvas._ctrl_node_id)
            if node:
                node.on_ctrl_release()
            canvas._ctrl_node_id = None
            canvas._ctrl_rect    = None
            canvas.update()
        if canvas._rubber_band_active:
            canvas._rubber_band_active = False
            canvas.update()
        if canvas._dragging_node:
            nid = canvas._dragging_node
            canvas._dragging_node = None
            if canvas._drag_nodes_start:
                moves: dict = {}
                for sid, sp in canvas._drag_nodes_start.items():
                    n = canvas._runtime.get_node(sid)
                    if n and (n.x != sp.x() or n.y != sp.y()):
                        moves[sid] = (sp.x(), sp.y(), n.x, n.y)
                if moves:
                    canvas._history.push(NodeMoveCmd(canvas._runtime, moves))
                for sid in list(canvas._drag_nodes_start.keys()):
                    canvas._update_node_group_membership(sid)
                canvas._drag_nodes_start = {}
            else:
                n = canvas._runtime.get_node(nid)
                if n:
                    ds = canvas._drag_node_start
                    if n.x != ds.x() or n.y != ds.y():
                        canvas._history.push(NodeMoveCmd(
                            canvas._runtime,
                            {nid: (ds.x(), ds.y(), n.x, n.y)},
                        ))
                canvas._update_node_group_membership(nid)
        if canvas._dragging_group:
            gid = canvas._dragging_group
            canvas._dragging_group = None
            grp = canvas._groups.get(gid)
            if grp:
                gb = canvas._drag_group_pos_start
                ga = (grp.x, grp.y)
                if ga != (gb.x(), gb.y()):
                    node_moves: dict = {}
                    for nid2, sp2 in canvas._drag_group_nodes_start.items():
                        n2 = canvas._runtime.get_node(nid2)
                        if n2:
                            node_moves[nid2] = (sp2.x(), sp2.y(), n2.x, n2.y)
                    canvas._history.push(GroupMoveCmd(
                        canvas._runtime, canvas._groups, gid,
                        (gb.x(), gb.y()), ga, node_moves,
                    ))
            canvas._update_group_membership(gid)
        if canvas._resizing_group:
            gid = canvas._resizing_group
            canvas._resizing_group = None
            grp = canvas._groups.get(gid)
            if grp and canvas._resize_group_start:
                sr = canvas._resize_group_start
                before = (sr.x(), sr.y(), sr.width(), sr.height())
                after  = (grp.x, grp.y, grp.width, grp.height)
                if before != after:
                    canvas._history.push(GroupResizeCmd(canvas._groups, gid, before, after))
            canvas._update_group_membership(gid)
        if canvas._wire_src:
            hp = canvas._hit_pin(canvas._v2s(event.position()))
            if hp and hp.direction == PinDirection.INPUT:
                _try_connect(canvas, canvas._wire_src, hp)
            canvas._wire_src = None; canvas.update()


def mouseDoubleClickEvent(canvas, event: QMouseEvent) -> None:
    if event.button() != Qt.MouseButton.LeftButton:
        return
    scene = canvas._v2s(event.position())
    # Field / var-input editor (takes priority)
    rf = canvas._hit_field(scene)
    if rf:
        _open_editor(canvas, rf, event.position())
        return
    # Double-click on group title — rename group (only when no node is above)
    if not canvas._hit_node(scene):
        gt_gid = canvas._hit_group_title(scene)
        if gt_gid:
            _open_group_rename_editor(canvas, gt_gid)
            return
    # Double-click on title bar — rename node
    title_nid = canvas._hit_title_bar(scene)
    if title_nid:
        _open_node_rename_editor(canvas, title_nid)
        return
    # Double-click on a DeviceNodeBase body (non-title) — cycle device
    nid = canvas._hit_node(scene)
    if nid:
        node = canvas._runtime.get_node(nid)
        if node is not None:
            from core.device_node_base import DeviceNodeBase
            if isinstance(node, DeviceNodeBase):
                old_dev = node.get_device()
                old_did = old_dev.device_id if old_dev else None
                node.cycle_device()
                canvas._history.push(DeviceCycleCmd(node, old_did))
                canvas.update()
                return
    # Note: super().mouseDoubleClickEvent(event) cannot be called from module function


# ── Drag and Drop ─────────────────────────────────────────────────────────────

def dragEnterEvent(canvas, event) -> None:
    if event.mimeData().hasText() and event.mimeData().text().startswith("device:"):
        event.acceptProposedAction()
    else:
        event.ignore()


def dragMoveEvent(canvas, event) -> None:
    text = event.mimeData().text() if event.mimeData().hasText() else ""
    if not text.startswith("device:"):
        event.ignore()
        return
    device_id = text[len("device:"):]
    scene = canvas._v2s(event.position())

    from core.device_node_base import DeviceNodeBase, get_type_key_for_device
    from ui.node_editor_canvas import _node_width, _node_total_height

    type_key = get_type_key_for_device(device_id)

    new_target: Optional[str] = None
    if type_key:
        for node in reversed(list(canvas._runtime.nodes.values())):
            w = _node_width(node)
            h = _node_total_height(node)
            if QRectF(node.x, node.y, w, h).contains(scene):
                if isinstance(node, DeviceNodeBase) and node.DEVICE_TYPE_KEY == type_key:
                    new_target = node.node_id
                break

    if new_target != canvas._drag_highlight_node:
        canvas._drag_highlight_node = new_target
        canvas.update()
    event.acceptProposedAction()


def dragLeaveEvent(canvas, event) -> None:
    canvas._drag_highlight_node = None
    canvas.update()


def dropEvent(canvas, event) -> None:
    text = event.mimeData().text() if event.mimeData().hasText() else ""
    if not text.startswith("device:"):
        event.ignore()
        canvas._drag_highlight_node = None
        return
    device_id = text[len("device:"):]
    if canvas._drag_highlight_node:
        node = canvas._runtime.get_node(canvas._drag_highlight_node)
        if node:
            from core.device_node_base import DeviceNodeBase
            if isinstance(node, DeviceNodeBase):
                node.select_device(device_id)
    canvas._drag_highlight_node = None
    canvas.update()
    event.acceptProposedAction()


def wheelEvent(canvas, event: QWheelEvent) -> None:
    factor    = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
    old_scene = canvas._v2s(event.position())
    canvas._zoom = max(0.2, min(4.0, canvas._zoom * factor))
    new_view  = QPointF(old_scene.x() * canvas._zoom + canvas._offset.x(),
                        old_scene.y() * canvas._zoom + canvas._offset.y())
    canvas._offset += event.position() - new_view
    canvas.update()


# ── Tooltip ───────────────────────────────────────────────────────────────────

def _show_hover_tooltip(canvas) -> None:
    """Called by _tooltip_timer — shows QToolTip for pin or node."""
    global_pos = canvas.mapToGlobal(canvas._last_mouse_view.toPoint())

    # Pin tooltip
    if canvas._hovered_pin:
        rp        = canvas._hovered_pin
        node      = canvas._runtime.get_node(rp.node_id)
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
        QToolTip.showText(global_pos, text, canvas)
        return

    # Node tooltip — only when NODE_TOOLTIP is set
    if canvas._hovered_node:
        node = canvas._runtime.get_node(canvas._hovered_node)
        if node and node.NODE_TOOLTIP:
            QToolTip.showText(global_pos, node.NODE_TOOLTIP, canvas)
        return

    QToolTip.hideText()


# ── Field Editing ─────────────────────────────────────────────────────────────

def _open_editor(canvas, rf, view_pos: QPointF) -> None:
    _close_editor(canvas)
    node = canvas._runtime.get_node(rf.node_id)
    if not node:
        return
    # ColorPicker: for editable field named "color" (str), open QColorDialog
    if not rf.is_var and rf.field_name == "color":
        old_color = node.get_field("color") or "#ffffff"
        initial = _parse_hex_to_qcolor(str(old_color))
        color = QColorDialog.getColor(initial, canvas, "Pick color")
        if color.isValid():
            hex_val = f"#{color.red():02x}{color.green():02x}{color.blue():02x}"
            node.set_field("color", hex_val)
            if old_color != hex_val:
                canvas._history.push(FieldEditCmd(
                    canvas._runtime, rf.node_id, "color", False, old_color, hex_val
                ))
            canvas.update()
            return
    tl = canvas._s2v(rf.scene_rect.topLeft())
    br = canvas._s2v(rf.scene_rect.bottomRight())

    editor = QLineEdit(canvas)
    editor.setObjectName("FieldEditor")
    editor.setStyleSheet("""
        QLineEdit#FieldEditor {
            background: #1a0a0f; color: #ffd0de;
            border: 1px solid #f95979; border-radius: 4px;
            padding: 0 4px; font-family: 'Courier New'; font-size: 9pt;
        }
    """)
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
        if rf.is_var:
            node.set_var_input(rf.field_name, raw)
        else:
            node.set_field(rf.field_name, raw)
        new_val = (node.get_var_input(rf.field_name) if rf.is_var
                   else node.get_field(rf.field_name))
        if str(old_val) != str(new_val):
            canvas._history.push(FieldEditCmd(
                canvas._runtime, rf.node_id, rf.field_name, rf.is_var, old_val, new_val
            ))
        _close_editor(canvas)
        canvas.update()

    editor.returnPressed.connect(_commit)
    editor.editingFinished.connect(_commit)
    editor._cancel = lambda: _close_editor(canvas)  # type: ignore[attr-defined]
    editor.installEventFilter(canvas)
    canvas._active_editor = editor


def _close_editor(canvas) -> None:
    if canvas._active_editor:
        ed = canvas._active_editor
        canvas._active_editor = None   # clear first to block re-entrant calls
        ed.hide()
        ed.deleteLater()


def _open_node_rename_editor(canvas, node_id: str) -> None:
    """Show an inline QLineEdit over the title bar to rename a node."""
    node = canvas._runtime.get_node(node_id)
    if not node:
        return
    _close_editor(canvas)
    from ui.node_editor_canvas import _node_width, _node_display_name
    width = _node_width(node)
    title_scene = QRectF(node.x, node.y, width, TITLE_H)
    tl = canvas._s2v(title_scene.topLeft())
    br = canvas._s2v(title_scene.bottomRight())

    editor = QLineEdit(canvas)
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
            canvas._history.push(NodeRenameCmd(canvas._runtime, node_id, old_name, new_name))
        node.node_changed.emit()
        _close_editor(canvas)
        canvas.update()

    editor.returnPressed.connect(_commit)
    editor.editingFinished.connect(_commit)
    editor._cancel = lambda: _close_editor(canvas)  # type: ignore[attr-defined]
    editor.installEventFilter(canvas)
    canvas._active_editor = editor


def _open_ctrl_label_editor(canvas, node, scene_rect: QRectF) -> None:
    """Inline QLineEdit over a control-panel widget's label area."""
    _close_editor(canvas)
    tl = canvas._s2v(scene_rect.topLeft())
    br = canvas._s2v(scene_rect.bottomRight())

    editor = QLineEdit(canvas)
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
        _close_editor(canvas)
        canvas.update()

    editor.returnPressed.connect(_commit)
    editor.editingFinished.connect(_commit)
    editor._cancel = lambda: _close_editor(canvas)  # type: ignore[attr-defined]
    editor.installEventFilter(canvas)
    canvas._active_editor = editor


def _open_group_rename_editor(canvas, group_id: str) -> None:
    """Show an inline QLineEdit over the group title bar to rename a group."""
    grp = canvas._groups.get(group_id)
    if not grp:
        return
    _close_editor(canvas)
    title_scene = grp.title_rect()
    tl = canvas._s2v(title_scene.topLeft())
    br = canvas._s2v(title_scene.bottomRight())

    editor = QLineEdit(canvas)
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
            canvas._history.push(GroupRenameCmd(
                canvas._groups, group_id, old_grp_name, new_grp_name
            ))
        _close_editor(canvas)
        canvas.update()

    editor.returnPressed.connect(_commit)
    editor.editingFinished.connect(_commit)
    editor._cancel = lambda: _close_editor(canvas)  # type: ignore[attr-defined]
    editor.installEventFilter(canvas)
    canvas._active_editor = editor


def eventFilter(canvas, obj, event) -> bool:
    if (obj is canvas._active_editor
            and event.type() == QEvent.Type.KeyPress
            and event.key() == Qt.Key.Key_Escape):
        fn = getattr(obj, "_cancel", None)
        if fn: fn()
        return True
    # Note: Cannot call super().eventFilter in module function
    return False


# ── Keyboard ──────────────────────────────────────────────────────────────────

def clear_history(canvas) -> None:
    """Reset undo/redo stacks (call after new graph or load)."""
    canvas._history.clear()


def keyPressEvent(canvas, event: QKeyEvent) -> None:
    ctrl = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)

    if ctrl and event.key() == Qt.Key.Key_Z:
        canvas._history.undo()
        canvas.update()
        return
    if ctrl and event.key() == Qt.Key.Key_Y:
        canvas._history.redo()
        canvas.update()
        return

    if event.key() == Qt.Key.Key_F2:
        if canvas._selected_group:
            _open_group_rename_editor(canvas, canvas._selected_group)
            return
        if canvas._selected_node:
            _open_node_rename_editor(canvas, canvas._selected_node)
        return

    if event.key() == Qt.Key.Key_Delete:
        if canvas._selected_group:
            canvas._delete_selected_group()
            return
        if canvas._selected_wire:
            wire = canvas._runtime.wires.get(canvas._selected_wire)
            canvas._runtime.remove_wire(canvas._selected_wire)
            if wire:
                canvas._history.push(WireDeleteCmd(canvas._runtime, wire))
            canvas._selected_wire = None; canvas.update(); return
        if canvas._selected_nodes or canvas._selected_node:
            _delete_selected_nodes(canvas)
            return

    if ctrl and event.key() == Qt.Key.Key_A:
        canvas._selected_nodes = set(canvas._runtime.nodes.keys())
        canvas._selected_node  = None
        canvas._selected_wire  = None
        canvas._selected_group = None
        canvas.update(); return

    if ctrl and event.key() == Qt.Key.Key_C:
        _copy_selected(canvas); return
    if ctrl and event.key() == Qt.Key.Key_X:
        _cut_selected(canvas); return
    if ctrl and event.key() == Qt.Key.Key_V:
        _paste_clipboard(canvas); return
    if ctrl and event.key() == Qt.Key.Key_D:
        _duplicate_selected(canvas); return

    if event.key() == Qt.Key.Key_Tab:
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            _center_origin(canvas)
        else:
            _tab_cycle(canvas)
        return

    shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
    if shift and event.key() == Qt.Key.Key_F:
        global_pos = QCursor.pos()
        widget_pos = canvas.mapFromGlobal(global_pos)
        scene_pos = canvas._v2s(QPointF(widget_pos))
        _open_node_search(canvas, global_pos, scene_pos)
        return

    if event.key() == Qt.Key.Key_Escape:
        canvas._wire_src       = None
        canvas._selected_node  = None
        canvas._selected_nodes = set()
        canvas._selected_wire  = None
        canvas._selected_group = None
        canvas.device_highlighted.emit(None)
        canvas.update()


# ── Clipboard & Deletion ──────────────────────────────────────────────────────

def _copy_selected(canvas) -> None:
    # Group copy: when a group is selected with no individual node selection
    if canvas._selected_group and not canvas._selected_nodes and not canvas._selected_node:
        grp = canvas._groups.get(canvas._selected_group)
        if grp and grp.node_ids:
            nodes = [n for nid in grp.node_ids
                     if (n := canvas._runtime.get_node(nid)) is not None]
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
                    for w in canvas._runtime.wires.values()
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
                canvas._clipboard = {"nodes": node_entries, "wires": wire_entries,
                                   "group": group_entry}
        return

    targets = list(canvas._selected_nodes) if canvas._selected_nodes else (
        [canvas._selected_node] if canvas._selected_node else []
    )
    if not targets:
        return
    nodes = [n for nid in targets if (n := canvas._runtime.get_node(nid)) is not None]
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
        for w in canvas._runtime.wires.values()
        if w.src_node in target_ids and w.dst_node in target_ids
    ]
    canvas._clipboard = {"nodes": node_entries, "wires": wire_entries}


def _cut_selected(canvas) -> None:
    _copy_selected(canvas)
    _delete_selected_nodes(canvas, description="Cut")


def _paste_clipboard(canvas) -> None:
    if not canvas._clipboard:
        return
    # Paste at current cursor position if it's within the canvas,
    # otherwise fall back to canvas centre + offset.
    mx, my = canvas._last_mouse_view.x(), canvas._last_mouse_view.y()
    if 0 <= mx <= canvas.width() and 0 <= my <= canvas.height():
        paste_scene = canvas._v2s(QPointF(mx, my))
    else:
        paste_scene = canvas._v2s(QPointF(canvas.width() / 2, canvas.height() / 2))
    payload_dict = {
        "paste_x": paste_scene.x(),
        "paste_y": paste_scene.y(),
        "nodes":   canvas._clipboard["nodes"],
        "wires":   canvas._clipboard["wires"],
    }
    if "group" in canvas._clipboard:
        payload_dict["group"] = canvas._clipboard["group"]
    payload = _json.dumps(payload_dict)

    # Capture what gets created — signals are synchronous on the main thread
    _created_node_ids: list[str] = []
    _created_wire_ids: list[str] = []

    def _on_node(nid: str) -> None:
        _created_node_ids.append(nid)

    def _on_wire(wire) -> None:
        _created_wire_ids.append(wire.wire_id)

    canvas._runtime.node_added.connect(_on_node)
    canvas._runtime.wire_added.connect(_on_wire)
    canvas._last_pasted_group_id = None
    canvas.status_message.emit(f"__paste_nodes__{payload}")
    canvas._runtime.node_added.disconnect(_on_node)
    canvas._runtime.wire_added.disconnect(_on_wire)

    if _created_node_ids or _created_wire_ids:
        nodes = [n for nid in _created_node_ids
                 if (n := canvas._runtime.get_node(nid)) is not None]
        wires = [w for wid in _created_wire_ids
                 if (w := canvas._runtime.wires.get(wid)) is not None]
        group = (canvas._groups.get(canvas._last_pasted_group_id)
                 if canvas._last_pasted_group_id else None)
        canvas._history.push(PasteCmd(canvas._runtime, canvas._groups, nodes, wires, group))


def _duplicate_selected(canvas) -> None:
    _copy_selected(canvas)
    _paste_clipboard(canvas)


def _delete_selected_nodes(canvas, description: str = "Delete") -> None:
    nodeIdentifiers = list(canvas._selected_nodes) if canvas._selected_nodes else (
        [canvas._selected_node] if canvas._selected_node else []
    )
    if not nodeIdentifiers:
        return
    if len(nodeIdentifiers) > 1:
        canvas._history.begin_macro(description)
    for nid in nodeIdentifiers:
        node = canvas._runtime.get_node(nid)
        if node:
            wires = [w for w in canvas._runtime.wires.values()
                     if w.src_node == nid or w.dst_node == nid]
            group_membership = {gid for gid, g in canvas._groups.items()
                                if nid in g.node_ids}
            canvas._runtime.remove_node(nid)
            canvas._history.push(NodeDeleteCmd(
                canvas._runtime, node, wires, canvas._groups, group_membership
            ))
    if len(nodeIdentifiers) > 1:
        canvas._history.end_macro()
    canvas._selected_nodes = set()
    canvas._selected_node  = None
    canvas.update()


# ── Navigation ────────────────────────────────────────────────────────────────

def _tab_cycle(canvas) -> None:
    nodes = list(canvas._runtime.nodes.values())
    if not nodes: return
    from ui.node_editor_canvas import _node_width, _node_total_height
    canvas._tab_index = (canvas._tab_index + 1) % len(nodes)
    node = nodes[canvas._tab_index]
    canvas._selected_node = node.node_id
    _center_scene(canvas, QPointF(node.x + _node_width(node) / 2,
                                   node.y + _node_total_height(node) / 2))
    canvas.update()


def _center_origin(canvas) -> None:
    canvas._selected_node = None
    canvas._offset = QPointF(canvas.width() / 2, canvas.height() / 2)
    canvas._zoom   = 1.0; canvas.update()


def _center_scene(canvas, sp: QPointF) -> None:
    canvas._offset = QPointF(canvas.width()  / 2 - sp.x() * canvas._zoom,
                             canvas.height() / 2 - sp.y() * canvas._zoom)


# ── Wire Creation ─────────────────────────────────────────────────────────────

def _try_connect(canvas, src, dst) -> None:
    # Self-loops are allowed for both data and tick pins (feedback connections)
    is_self_loop = src.node_id == dst.node_id
    if is_self_loop and dst.direction != PinDirection.INPUT:
        return
    if dst.pin_type not in PIN_COMPATIBILITY.get(src.pin_type, set()):
        canvas.status_message.emit(
            f"Type mismatch: {src.pin_type.name} → {dst.pin_type.name}")
        return
    import uuid
    wire = WireDescriptor(
        wire_id  = str(uuid.uuid4()),
        src_node = src.node_id, src_pin = src.pin_name,
        dst_node = dst.node_id, dst_pin = dst.pin_name,
    )
    if canvas._runtime.add_wire(wire):
        canvas._history.push(WireAddCmd(canvas._runtime, wire))
        canvas.wire_created.emit(wire)
    else:
        canvas.status_message.emit("Could not create wire")


# ── Device Menu ───────────────────────────────────────────────────────────────

def _show_device_menu(canvas, node, instances: list, global_pos: QPoint) -> None:
    """Pop up a QMenu to choose a device for this node."""
    from core.device_node_base import DeviceNodeBase, get_device_alias
    if not isinstance(node, DeviceNodeBase):
        return
    current_dev = node.get_device()
    current_id  = current_dev.device_id if current_dev else ""
    menu = QMenu(canvas)
    menu.setStyleSheet(_MENU_STYLE)
    for dev in instances:
        alias = get_device_alias(dev)
        a = QAction(alias, menu)
        a.setCheckable(True)
        a.setChecked(dev.device_id == current_id)
        a.triggered.connect(
            lambda _checked, did=dev.device_id, n=node, oid=current_id:
                _on_device_select(canvas, n, oid, did)
        )
        menu.addAction(a)
    menu.exec(global_pos)


def _on_device_select(canvas, node, old_device_id: str, new_device_id: str) -> None:
    from core.device_node_base import DeviceNodeBase
    if isinstance(node, DeviceNodeBase):
        node.select_device(new_device_id)
        if old_device_id != new_device_id:
            canvas._history.push(DeviceSelectCmd(node, old_device_id, new_device_id))
    canvas.update()


# ── Node Search ───────────────────────────────────────────────────────────────

def _open_node_search(canvas, global_pos: QPoint, scene_pos: QPointF) -> None:
    """Open the floating node search popup."""
    from ui.node_editor_dialogs import _NodeSearchPopup
    structure = canvas._node_menu_fn()
    flat_nodes: list[tuple[str, str]] = []
    for group, items in sorted(structure.items()):
        display_group = group.replace("/", " › ")
        for name, key in sorted(items):
            flat_nodes.append((f"{display_group} / {name}", key))

    popup = _NodeSearchPopup(flat_nodes, scene_pos, canvas)
    popup.node_selected.connect(canvas._add_node_at)
    popup.move(global_pos)
    popup.show()


