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
from typing import Optional

from PyQt6.QtCore import Qt, QEvent, QPointF, QRectF, QPoint, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QKeyEvent, QMouseEvent, QPaintEvent, QPainter, QWheelEvent, QAction,
)
from PyQt6.QtWidgets import (
    QWidget, QLineEdit, QMenu, QDialog, QFormLayout, QDialogButtonBox,
    QDoubleSpinBox, QSpinBox, QColorDialog,
)

from core.command_history import (
    CommandHistory, NodeAddCmd, WireDeleteCmd, CtrlPropCmd,
)
from core.localization import tr
from core.graph_runtime import GraphRuntime
from core.node_base import NodeBase
from core.types import PinDirection, WireDescriptor

# Import from new modules
from ui.node_editor_layout import (
    _Row, _RowKind, RenderedPin, RenderedField, NodeGroup,
    _build_rows, _device_sel_extra, _node_total_height, _node_width, _node_display_name,
)
from ui.node_editor_rendering import (
    _paint_event, _hit_pin, _hit_field, _hit_node, _hit_device_selector, _hit_ctrl,
    _hit_title_bar, _hit_group_title, _hit_group_resize, _hit_wire, _find_pin_pos, _get_ctrl_rect,
)
from ui.node_editor_input import (
    mousePressEvent as _mousePressEvent,
    mouseMoveEvent as _mouseMoveEvent,
    mouseReleaseEvent as _mouseReleaseEvent,
    mouseDoubleClickEvent as _mouseDoubleClickEvent,
    dragEnterEvent as _dragEnterEvent,
    dragMoveEvent as _dragMoveEvent,
    dragLeaveEvent as _dragLeaveEvent,
    dropEvent as _dropEvent,
    wheelEvent as _wheelEvent,
    _show_hover_tooltip as _show_hover_tooltip_fn,
    _open_editor as _open_editor_fn,
    _close_editor as _close_editor_fn,
    _open_node_rename_editor as _open_node_rename_editor_fn,
    _open_ctrl_label_editor as _open_ctrl_label_editor_fn,
    _open_group_rename_editor as _open_group_rename_editor_fn,
    eventFilter as _eventFilter,
    clear_history as _clear_history,
    keyPressEvent as _keyPressEvent,
    _delete_selected_nodes,
    _copy_selected,
    _cut_selected,
    _paste_clipboard,
    _duplicate_selected,
    _tab_cycle,
    _center_origin,
    _center_scene,
    _try_connect,
    _show_device_menu,
    _on_device_select,
    _open_node_search,
    _MENU_STYLE,
)

log = logging.getLogger(__name__)


class NodeEditorCanvas(QWidget):
    """
    The main node editor canvas widget.

    Responsibilities:
      - Widget setup and event delegation
      - Coordinate transformation (_s2v, _v2s)
      - Node/group/wire management (add, remove, update)
      - Undo/redo history
      - Signals for wire creation and node selection
    """

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
        self._rendered_wires  : list[tuple[str, any]] = []  # (wire_id, path)
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
        """Convert scene coordinates to view (widget) coordinates."""
        return QPointF(pt.x() * self._zoom + self._offset.x(),
                       pt.y() * self._zoom + self._offset.y())

    def _v2s(self, pt: QPointF) -> QPointF:
        """Convert view (widget) coordinates to scene coordinates."""
        return QPointF((pt.x() - self._offset.x()) / self._zoom,
                       (pt.y() - self._offset.y()) / self._zoom)

    # ── Hit Testing Wrappers (delegates to rendering module) ─────────────────

    def _hit_pin(self, sp: QPointF) -> Optional[RenderedPin]:
        """Check if point hits any pin."""
        return _hit_pin(self, sp)

    def _hit_field(self, sp: QPointF) -> Optional[RenderedField]:
        """Check if point hits any field."""
        return _hit_field(self, sp)

    def _hit_node(self, sp: QPointF) -> Optional[str]:
        """Check if point hits any node."""
        return _hit_node(self, sp)

    def _hit_device_selector(self, sp: QPointF) -> Optional[str]:
        """Check if point hits a device selector."""
        return _hit_device_selector(self, sp)

    def _hit_ctrl(self, sp: QPointF) -> Optional[tuple]:
        """Check if point hits a control widget."""
        return _hit_ctrl(self, sp)

    def _hit_title_bar(self, sp: QPointF) -> Optional[str]:
        """Check if point hits a node title bar."""
        return _hit_title_bar(self, sp)

    def _hit_group_title(self, sp: QPointF) -> Optional[str]:
        """Check if point hits a group title bar."""
        return _hit_group_title(self, sp)

    def _hit_group_resize(self, sp: QPointF) -> Optional[tuple]:
        """Check if point hits a group resize handle."""
        return _hit_group_resize(self, sp)

    def _hit_wire(self, scene_pos: QPointF, threshold: float = 6.0) -> Optional[str]:
        """Check if point hits a wire."""
        return _hit_wire(self, scene_pos, threshold)

    def _find_pin_pos(self, node_id: str, pin_name: str) -> Optional[RenderedPin]:
        """Find the RenderedPin for a given node and pin name."""
        return _find_pin_pos(self, node_id, pin_name)

    # ── Paint ─────────────────────────────────────────────────────────────────

    def paintEvent(self, event: QPaintEvent) -> None:
        """Render the entire canvas."""
        p = QPainter(self)
        _paint_event(self, p)

    # ── Event Handlers (delegates to node_editor_input) ────────────────────────

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Delegate to input module."""
        _mousePressEvent(self, event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Delegate to input module."""
        _mouseMoveEvent(self, event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """Delegate to input module."""
        _mouseReleaseEvent(self, event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        """Delegate to input module."""
        _mouseDoubleClickEvent(self, event)

    def dragEnterEvent(self, event) -> None:
        """Delegate to input module."""
        _dragEnterEvent(self, event)

    def dragMoveEvent(self, event) -> None:
        """Delegate to input module."""
        _dragMoveEvent(self, event)

    def dragLeaveEvent(self, event) -> None:
        """Delegate to input module."""
        _dragLeaveEvent(self, event)

    def dropEvent(self, event) -> None:
        """Delegate to input module."""
        _dropEvent(self, event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        """Delegate to input module."""
        _wheelEvent(self, event)

    def eventFilter(self, obj, event) -> bool:
        """Delegate to input module."""
        return _eventFilter(self, obj, event)

    def clear_history(self) -> None:
        """Delegate to input module."""
        _clear_history(self)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Delegate to input module."""
        _keyPressEvent(self, event)

    # ── Input/Editor Helper Wrappers ───────────────────────────────────────────

    def _show_hover_tooltip(self) -> None:
        """Show tooltip for hovered pin."""
        _show_hover_tooltip_fn(self)

    def _open_editor(self, rf: RenderedField, view_pos: QPointF) -> None:
        """Open inline field editor."""
        _open_editor_fn(self, rf, view_pos)

    def _close_editor(self) -> None:
        """Close inline field editor."""
        _close_editor_fn(self)

    def _open_node_rename_editor(self, node_id: str) -> None:
        """Open node name editor."""
        _open_node_rename_editor_fn(self, node_id)

    def _open_ctrl_label_editor(self, node: NodeBase, scene_rect: QRectF) -> None:
        """Open control label editor."""
        _open_ctrl_label_editor_fn(self, node, scene_rect)

    def _open_group_rename_editor(self, group_id: str) -> None:
        """Open group name editor."""
        _open_group_rename_editor_fn(self, group_id)

    def _delete_selected_nodes(self, description: str = "Delete") -> None:
        """Delete selected nodes."""
        _delete_selected_nodes(self, description)

    def _copy_selected(self) -> None:
        """Copy selected nodes and wires to clipboard."""
        _copy_selected(self)

    def _cut_selected(self) -> None:
        """Cut selected nodes and wires to clipboard."""
        _cut_selected(self)

    def _paste_clipboard(self) -> None:
        """Paste nodes and wires from clipboard."""
        _paste_clipboard(self)

    def _duplicate_selected(self) -> None:
        """Duplicate selected nodes."""
        _duplicate_selected(self)

    def _tab_cycle(self) -> None:
        """Cycle to next node."""
        _tab_cycle(self)

    def _center_origin(self) -> None:
        """Center view on scene origin."""
        _center_origin(self)

    def _center_scene(self, sp: QPointF) -> None:
        """Center view on scene position."""
        _center_scene(self, sp)

    def _try_connect(self, src: RenderedPin, dst: RenderedField) -> None:
        """Try to create a wire connection."""
        _try_connect(self, src, dst)

    def _show_device_menu(self, node: NodeBase, instances: list, global_pos: QPoint) -> None:
        """Show device selector menu."""
        _show_device_menu(self, node, instances, global_pos)

    def _on_device_select(self, node, old_device_id: str, new_device_id: str) -> None:
        """Handle device selection change."""
        _on_device_select(self, node, old_device_id, new_device_id)

    def _open_node_search(self, global_pos: QPoint, scene_pos: QPointF) -> None:
        """Open node search popup."""
        _open_node_search(self, global_pos, scene_pos)

    # ── Node and Group Management ──────────────────────────────────────────────

    def _update_node_group_membership(self, node_id: str) -> None:
        """Update which group(s) this node belongs to based on its position."""
        node = self._runtime.get_node(node_id)
        if not node:
            return

        # Check which groups contain this node
        for grp in self._groups.values():
            if grp.inner_rect().contains(QPointF(node.x + 10, node.y + 10)):
                if node_id not in grp.node_ids:
                    grp.node_ids.add(node_id)
            else:
                grp.node_ids.discard(node_id)

    def _update_group_membership(self, group_id: str) -> None:
        """Update which nodes belong to a group based on the group's position."""
        grp = self._groups.get(group_id)
        if not grp:
            return

        grp.node_ids.clear()
        inner = grp.inner_rect()
        for node in self._runtime.nodes.values():
            if inner.contains(QPointF(node.x + 10, node.y + 10)):
                grp.node_ids.add(node.node_id)

    def _on_node_removed_from_groups(self, node_id: str) -> None:
        """Called when a node is removed; clean it from all groups."""
        for grp in self._groups.values():
            grp.node_ids.discard(node_id)

    def _add_group(self, scene_pos: QPointF) -> None:
        """Create a new group and push to history."""
        from ui.node_editor_layout import NodeGroup
        from core.command_history import GroupCreateCmd
        grp = NodeGroup(x=scene_pos.x(), y=scene_pos.y())
        self._groups[grp.group_id] = grp
        self._history.push(GroupCreateCmd(self._groups, grp))
        self.update()

    def get_saved_groups(self) -> list:
        """Serialize groups for saving."""
        return [
            {
                "group_id": g.group_id,
                "name": g.name,
                "x": g.x,
                "y": g.y,
                "width": g.width,
                "height": g.height,
                "color": g.color,
                "node_ids": list(g.node_ids),
            }
            for g in self._groups.values()
        ]

    def load_saved_groups(self, saved_groups: list) -> None:
        """Restore groups from saved data."""
        from ui.node_editor_layout import NodeGroup
        self._groups.clear()
        for gd in saved_groups:
            grp = NodeGroup(
                group_id=gd.get("group_id", ""),
                name=gd.get("name", "Group"),
                x=gd.get("x", 0),
                y=gd.get("y", 0),
                width=gd.get("width", 240),
                height=gd.get("height", 180),
                color=gd.get("color", "#1a4a7a"),
                node_ids=set(gd.get("node_ids", [])),
            )
            self._groups[grp.group_id] = grp
        self.update()

    def add_pasted_group(self, gd: dict, id_map: dict, paste_x: float, paste_y: float) -> None:
        """Add a pasted group, remapping node IDs and offsetting position."""
        from ui.node_editor_layout import NodeGroup
        new_node_ids = {id_map.get(nid, nid) for nid in gd.get("node_ids", [])}
        grp = NodeGroup(
            group_id=gd.get("group_id", ""),
            name=gd.get("name", "Group"),
            x=gd.get("x", 0) + paste_x,
            y=gd.get("y", 0) + paste_y,
            width=gd.get("width", 240),
            height=gd.get("height", 180),
            color=gd.get("color", "#1a4a7a"),
            node_ids=new_node_ids,
        )
        self._groups[grp.group_id] = grp
        self._last_pasted_group_id = grp.group_id
        self.update()

    def _delete_selected_group_wrapper(self) -> None:
        """Delete the selected group."""
        from core.command_history import GroupDeleteCmd
        if self._selected_group:
            grp = self._groups.pop(self._selected_group, None)
            if grp:
                self._history.push(GroupDeleteCmd(self._groups, grp))
                self._selected_group = None
                self.update()

    def _get_ctrl_rect(self, node_id: str) -> Optional[QRectF]:
        """Return the CUSTOM row scene rect for a node, or None."""
        return _get_ctrl_rect(self, node_id)

    # ── Context Menus ──────────────────────────────────────────────────────────

    def _show_node_context_menu(self, node_id: str, global_pos: QPoint) -> None:
        """Show the node context menu with control-specific options."""
        node = self._runtime.get_node(node_id)
        if not node:
            return
        menu = QMenu(self)
        menu.setStyleSheet(_MENU_STYLE)

        rename_act = QAction(tr("ui.canvas.menu.rename"), menu)
        rename_act.triggered.connect(lambda: self._open_node_rename_editor(node_id))
        menu.addAction(rename_act)

        # Control-specific actions (grouped with a separator when any are present)
        ctrl_actions: list = []

        if hasattr(node, "get_ctrl_label") and hasattr(node, "set_ctrl_label"):
            lbl_act = QAction(tr("ui.canvas.menu.rename_label"), menu)
            lbl_act.triggered.connect(lambda: self._trigger_ctrl_label_editor(node_id))
            ctrl_actions.append(lbl_act)

        if hasattr(node, "get_ctrl_color") and hasattr(node, "set_ctrl_color"):
            color_act = QAction(tr("ui.canvas.menu.button_color"), menu)
            color_act.triggered.connect(lambda: self._open_ctrl_color_picker(node_id))
            ctrl_actions.append(color_act)

        if hasattr(node, "get_ctrl_range") and hasattr(node, "set_ctrl_range"):
            range_act = QAction(tr("ui.canvas.menu.set_range"), menu)
            range_act.triggered.connect(lambda: self._open_ctrl_range_dialog(node_id))
            ctrl_actions.append(range_act)

        if hasattr(node, "get_ctrl_scale") and hasattr(node, "set_ctrl_scale"):
            scale_menu = QMenu(tr("ui.canvas.menu.scale_mode"), menu)
            scale_menu.setStyleSheet(_MENU_STYLE)
            current_scale = node.get_ctrl_scale()
            for mode, label in [
                ("linear",      "Linear"),
                ("exponential", "Exponential"),
                ("logarithmic", "Logarithmic"),
            ]:
                act = QAction(label, scale_menu)
                act.setCheckable(True)
                act.setChecked(current_scale == mode)
                act.triggered.connect(
                    lambda _checked, m=mode: self._set_ctrl_scale(node_id, m)
                )
                scale_menu.addAction(act)
            ctrl_actions.append(scale_menu)

        if hasattr(node, "get_channel_count") and hasattr(node, "set_channel_count"):
            ch_menu = QMenu(tr("ui.canvas.menu.channel_count"), menu)
            ch_menu.setStyleSheet(_MENU_STYLE)
            current_ch = node.get_channel_count()
            for n_ch in range(2, 9):
                act = QAction(str(n_ch), ch_menu)
                act.setCheckable(True)
                act.setChecked(current_ch == n_ch)
                act.triggered.connect(
                    lambda _checked, count=n_ch: self._set_channel_count(node_id, count)
                )
                ch_menu.addAction(act)
            ctrl_actions.append(ch_menu)

        if hasattr(node, "get_sample_count") and hasattr(node, "set_sample_count"):
            sample_menu = QMenu(tr("ui.canvas.menu.sample_count", default="Sample count"), menu)
            sample_menu.setStyleSheet(_MENU_STYLE)
            current_samples = node.get_sample_count()
            for n_s in (50, 100, 200, 300, 500):
                act = QAction(str(n_s), sample_menu)
                act.setCheckable(True)
                act.setChecked(current_samples == n_s)
                act.triggered.connect(
                    lambda _checked, s=n_s: self._set_sample_count(node_id, s)
                )
                sample_menu.addAction(act)

            # Add custom sample count option
            if hasattr(node, "get_custom_sample_count") and hasattr(node, "set_custom_sample_count"):
                sample_menu.addSeparator()
                custom_act = QAction(tr("ui.canvas.menu.custom_sample_count", default="Custom…"), sample_menu)
                custom_act.triggered.connect(
                    lambda: self._open_sample_count_dialog(node_id)
                )
                sample_menu.addAction(custom_act)

            ctrl_actions.append(sample_menu)

        if hasattr(node, "get_waveform_range") and hasattr(node, "set_waveform_range"):
            range_menu = QMenu(tr("ui.canvas.menu.waveform_range", default="Y-axis range"), menu)
            range_menu.setStyleSheet(_MENU_STYLE)
            current_range = node.get_waveform_range()
            range_options = getattr(node, "_RANGE_PRESETS", {}).keys()
            for range_mode in range_options:
                act = QAction(range_mode, range_menu)
                act.setCheckable(True)
                act.setChecked(current_range == range_mode)
                act.triggered.connect(
                    lambda _checked, m=range_mode: self._set_waveform_range(node_id, m)
                )
                range_menu.addAction(act)

            # Add custom range option
            if hasattr(node, "get_custom_range") and hasattr(node, "set_custom_range"):
                range_menu.addSeparator()
                custom_act = QAction(tr("ui.canvas.menu.custom_range", default="Custom…"), range_menu)
                custom_act.setCheckable(True)
                custom_act.setChecked(current_range == "Custom")
                custom_act.triggered.connect(
                    lambda: self._open_waveform_custom_range_dialog(node_id)
                )
                range_menu.addAction(custom_act)

            ctrl_actions.append(range_menu)

        if hasattr(node, "get_touchpad_mode") and hasattr(node, "set_touchpad_mode"):
            mode_menu = QMenu(tr("ui.canvas.menu.touchpad_mode", default="Release Mode"), menu)
            mode_menu.setStyleSheet(_MENU_STYLE)
            current_mode = node.get_touchpad_mode()
            for mode, label in [
                ("reset", "Reset to 0,0"),
                ("hold",  "Keep Last Value"),
            ]:
                act = QAction(label, mode_menu)
                act.setCheckable(True)
                act.setChecked(current_mode == mode)
                act.triggered.connect(
                    lambda _checked, m=mode: self._set_touchpad_mode(node_id, m)
                )
                mode_menu.addAction(act)
            ctrl_actions.append(mode_menu)

        if ctrl_actions:
            menu.addSeparator()
            for item in ctrl_actions:
                if isinstance(item, QMenu):
                    menu.addMenu(item)
                else:
                    menu.addAction(item)

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

    def _trigger_ctrl_label_editor(self, node_id: str) -> None:
        """Open label editor for a control widget."""
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
        """Open color picker for control widget."""
        from ui.node_editor_dialogs import _parse_hex_to_qcolor
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
        """Open range dialog for control slider."""
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
        """Set the scale mode for a control widget."""
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
        """Set the touchpad release mode."""
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

    def _show_context_menu(self, global_pos: QPoint, scene_pos: QPointF) -> None:
        """Show the right-click context menu for adding nodes and groups."""
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
        """Handle add node action from context menu."""
        a: QAction = self.sender()
        key, sp = a.data()
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

    # ── Specialized node operations ────────────────────────────────────────────

    def _duplicate_node(self, node_id: str) -> None:
        """Create a copy of a node."""
        from core.command_history import NodeAddCmd
        node = self._runtime.get_node(node_id)
        if not node:
            return

        _created: list[str] = []
        def _on_added(nid: str) -> None:
            _created.append(nid)

        self._runtime.node_added.connect(_on_added)
        new_node = node.__class__()
        self._runtime.add_node(new_node, x=node.x + 40, y=node.y + 40)
        self._runtime.node_added.disconnect(_on_added)

        if _created:
            self._history.push(NodeAddCmd(self._runtime, self._runtime.get_node(_created[0])))

    def _remove_node_connections(self, node_id: str) -> None:
        """Remove all wires connected to this node."""
        from core.command_history import WireDeleteCmd
        wires_to_remove = []
        for w_id, w in list(self._runtime.wires.items()):
            if w.src_node == node_id or w.dst_node == node_id:
                wires_to_remove.append((w_id, w))

        for w_id, w in wires_to_remove:
            self._runtime.remove_wire(w_id)
            self._history.push(WireDeleteCmd(self._runtime, w))

    def _set_channel_count(self, node_id: str, count: int) -> None:
        """Set the channel count for a compatible node."""
        from core.command_history import CtrlPropCmd
        node = self._runtime.get_node(node_id)
        if node and hasattr(node, 'set_channel_count'):
            old_val = getattr(node, 'channel_count', None)
            node.set_channel_count(count)
            if old_val is not None:
                self._history.push(CtrlPropCmd(node, 'channel_count', old_val, count))
            self.update()

    def _set_sample_count(self, node_id: str, count: int) -> None:
        """Set the sample count for a compatible node."""
        from core.command_history import CtrlPropCmd
        node = self._runtime.get_node(node_id)
        if node and hasattr(node, 'set_sample_count'):
            old_val = getattr(node, 'sample_count', None)
            node.set_sample_count(count)
            if old_val is not None:
                self._history.push(CtrlPropCmd(node, 'sample_count', old_val, count))
            self.update()

    def _set_waveform_range(self, node_id: str, mode: str) -> None:
        """Set the waveform range mode."""
        from core.command_history import CtrlPropCmd
        node = self._runtime.get_node(node_id)
        if node and hasattr(node, 'set_waveform_range'):
            old_val = getattr(node, 'waveform_range_mode', None)
            node.set_waveform_range(mode)
            if old_val is not None:
                self._history.push(CtrlPropCmd(node, 'waveform_range_mode', old_val, mode))
            self.update()

    def _open_waveform_custom_range_dialog(self, node_id: str) -> None:
        """Open dialog for custom waveform range."""
        from PyQt6.QtWidgets import QDialog, QFormLayout, QDoubleSpinBox, QDialogButtonBox
        from PyQt6.QtCore import Qt
        node = self._runtime.get_node(node_id)
        if not node or not hasattr(node, 'waveform_custom_min'):
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("Custom Waveform Range")
        layout = QFormLayout(dlg)

        min_spin = QDoubleSpinBox()
        min_spin.setValue(float(getattr(node, 'waveform_custom_min', 0)))
        layout.addRow("Min:", min_spin)

        max_spin = QDoubleSpinBox()
        max_spin.setValue(float(getattr(node, 'waveform_custom_max', 1)))
        layout.addRow("Max:", max_spin)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addRow(buttons)

        if dlg.exec() == QDialog.DialogCode.Accepted:
            from core.command_history import CtrlPropCmd
            old_min = getattr(node, 'waveform_custom_min', 0)
            old_max = getattr(node, 'waveform_custom_max', 1)
            node.waveform_custom_min = min_spin.value()
            node.waveform_custom_max = max_spin.value()
            self._history.push(CtrlPropCmd(node, 'waveform_range', (old_min, old_max),
                                          (min_spin.value(), max_spin.value())))
            self.update()

    def _open_sample_count_dialog(self, node_id: str) -> None:
        """Open dialog for sample count."""
        from PyQt6.QtWidgets import QDialog, QFormLayout, QSpinBox, QDialogButtonBox
        from PyQt6.QtCore import Qt
        node = self._runtime.get_node(node_id)
        if not node or not hasattr(node, 'sample_count'):
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("Sample Count")
        layout = QFormLayout(dlg)

        spin = QSpinBox()
        spin.setMinimum(1)
        spin.setMaximum(10000)
        spin.setValue(int(getattr(node, 'sample_count', 100)))
        layout.addRow("Samples:", spin)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addRow(buttons)

        if dlg.exec() == QDialog.DialogCode.Accepted:
            from core.command_history import CtrlPropCmd
            old_val = getattr(node, 'sample_count', 100)
            node.sample_count = spin.value()
            self._history.push(CtrlPropCmd(node, 'sample_count', old_val, spin.value()))
            self.update()

    def _delete_node(self, node_id: str) -> None:
        """Delete a node and all its connections."""
        from core.command_history import NodeDeleteCmd
        node = self._runtime.get_node(node_id)
        if not node:
            return

        self._remove_node_connections(node_id)
        self._runtime.remove_node(node_id)
        self._history.push(NodeDeleteCmd(self._runtime, node))
        self._selected_node = None
        self._selected_nodes.discard(node_id)
        self.update()