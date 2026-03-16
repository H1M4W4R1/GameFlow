"""
MainWindow — top-level application window.

Layout:
    ┌─────────────────────────────────────────────────────────┐
    │  TOP BAR  [SensoryFlow]  [Save] [Load]  ──  [▶ Run]    │
    ├────────────┬────────────────────────────────────────────┤
    │  DEVICES   │                                            │
    │  ● Dev A   │        NODE EDITOR CANVAS                  │
    │  ● Dev B   │                                            │
    │  [+]       │                                            │
    ├────────────┴────────────────────────────────────────────┤
    │  STATUS BAR                                             │
    └─────────────────────────────────────────────────────────┘
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from PyQt6.QtCore  import Qt, QPointF, QPoint, QTimer
from PyQt6.QtGui   import QIcon, QKeySequence, QShortcut, QFont, QColor, QMouseEvent, QPainter, QPen, QBrush
from PyQt6.QtCore  import QRect, QSize, QPoint, QRectF
from PyQt6.QtSvg   import QSvgRenderer
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton,
    QLabel, QFileDialog, QSizePolicy, QFrame, QDialog,
)

from core.device_registry    import DeviceRegistry
from core.graph_runtime      import GraphRuntime
from core.device_persistence import save_devices, load_devices
from core.types           import SavedGraph, ConnectionDescriptor, WireDescriptor
from ui.device_panel      import DevicePanel
from ui.node_editor_canvas import NodeEditorCanvas

log = logging.getLogger(__name__)


class MainWindow(QWidget):
    def __init__(
        self,
        registry: DeviceRegistry,
        runtime:  GraphRuntime,
    ) -> None:
        super().__init__()
        self._registry   = registry
        self._runtime    = runtime
        self._graph_path: Optional[Path] = None
        self._dirty      = False
        self._loading    = False

        # Frameless window
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.Window
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setWindowTitle("SensoryFlow")
        self.resize(1400, 900)
        self.setStyleSheet(_APP_STYLE)

        # Drag state for custom title bar
        self._drag_active = False
        self._drag_pos    = QPoint()

        self._build_ui()
        self._connect_signals()
        self._place_default_nodes()
        QTimer.singleShot(200, self._on_post_show)

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Custom title bar (drag + window controls)
        root.addWidget(self._make_top_bar())

        # Main area (device panel + canvas)
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self._device_panel = DevicePanel(self._registry)
        body.addWidget(self._device_panel)

        # Divider
        div = QFrame()
        div.setFrameShape(QFrame.Shape.VLine)
        div.setStyleSheet("border: none; background: #45072f;")
        div.setFixedWidth(1)
        body.addWidget(div)

        self._canvas = NodeEditorCanvas(
            self._runtime,
            self._registry.get_node_menu_structure,
        )
        self._canvas.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        body.addWidget(self._canvas)

        body_widget = QWidget()
        body_widget.setLayout(body)
        root.addWidget(body_widget, stretch=1)

        # Status bar (plain QLabel, not QStatusBar which requires QMainWindow)
        self._status_bar = QLabel("Ready.")
        self._status_bar.setFixedHeight(22)
        self._status_bar.setStyleSheet(
            "background: #45072f; color: #c8889a; font-size: 8pt; padding: 2px 10px;"
        )
        root.addWidget(self._status_bar)

        # Resize grip (bottom-right corner)
        self._resize_handle = _ResizeHandle(self)
        # Positioned in resizeEvent

    def _make_top_bar(self) -> QWidget:
        """
        Custom frameless title bar.

        Left:    Logo  |  Save  Load
        Centre:  [← drag zone →]  graph-filename
        Right:   ▶  ⏺  ■  |  —  □  ✕
        """
        bar = _TitleBar(self)
        bar.setFixedHeight(48)
        bar.setObjectName("TitleBar")
        bar.setStyleSheet(
            "QWidget#TitleBar {"
            "  background: qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            "    stop:0 #45072f, stop:0.6 #220d14, stop:1 #1a0a0f);"
            "  border-bottom: 1px solid #c90084;"
            "}"
        )
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(10, 0, 6, 0)
        layout.setSpacing(6)

        # ── Logo (pure text — no background, transparent) ──────────────────
        logo = QLabel()
        logo.setText(
            "<span style='color:#f95979;font-size:13pt;"
            "font-family:Segoe UI,Ubuntu,sans-serif;"
            "letter-spacing:1px;'>⬡</span>"
            "<span style='color:#ffd0de;font-size:10pt;"
            "font-family:Segoe UI,Ubuntu,sans-serif;"
            "font-weight:bold;letter-spacing:3px;'> SENSORY</span>"
            "<span style='color:#f95979;font-size:10pt;"
            "font-family:Segoe UI,Ubuntu,sans-serif;"
            "font-weight:bold;letter-spacing:3px;'>FLOW</span>"
        )
        logo.setStyleSheet("background:transparent;")
        layout.addWidget(logo)

        layout.addSpacing(4)

        # ── File buttons ───────────────────────────────────────────────────
        self._new_btn  = QPushButton("+")
        self._new_btn.setFixedSize(30, 30)
        self._new_btn.setToolTip("New Graph  (Ctrl+N)")
        self._new_btn.setStyleSheet("""
            QPushButton { background:transparent; color:#c8889a; border:none;
                          font-size:18pt; font-weight:bold;
                          padding: 0 0 6px 0; margin:0; }
            QPushButton:hover { color:#f95979; }
        """)
        self._save_btn = _ToolButton("save.svg", "💾", "Save Graph  (Ctrl+S)", ghost=True)
        self._load_btn = _ToolButton("load.svg", "📂", "Load Graph  (Ctrl+O)", ghost=True)
        layout.addWidget(self._new_btn)
        layout.addWidget(self._save_btn)
        layout.addWidget(self._load_btn)

        # ── Centre area: left drag zone | project name | right drag zone ──
        drag_left = _DragZone(self)
        layout.addWidget(drag_left, stretch=1)

        self._graph_name_label = QLabel("Untitled")
        self._graph_name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._graph_name_label.setStyleSheet(
            "color:#7a4060;font-size:8pt;background:transparent;")
        layout.addWidget(self._graph_name_label)

        drag_right = _DragZone(self)
        layout.addWidget(drag_right, stretch=1)

        layout.addSpacing(2)

        # ── Playback buttons ───────────────────────────────────────────────
        self._run_btn   = _ToolButton("play.svg",  "▶", "Run Graph  (F5)",  accent=True)
        self._pause_btn = _ToolButton("pause.svg", "⏺", "Pause Graph  (F7)")
        self._stop_btn  = _ToolButton("stop.svg",  "■", "Stop Graph  (F6)")
        self._pause_btn.setEnabled(False)
        self._stop_btn.setEnabled(False)
        layout.addWidget(self._run_btn)
        layout.addWidget(self._pause_btn)
        layout.addWidget(self._stop_btn)

        # ── Separator ──────────────────────────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setFixedWidth(1)
        sep.setStyleSheet("background:#45072f;border:none;")
        layout.addWidget(sep)
        layout.addSpacing(2)

        # ── Window control buttons ─────────────────────────────────────────
        self._min_btn  = _WinButton("—", "#ffd0de", self._on_minimize)
        self._max_btn  = _WinButton("□", "#ffd0de", self._on_maximize)
        self._close_btn= _WinButton("✕", "#f95979", self._on_close_window)
        layout.addWidget(self._min_btn)
        layout.addWidget(self._max_btn)
        layout.addWidget(self._close_btn)

        return bar

    def _connect_signals(self) -> None:
        self._new_btn.clicked.connect(self._on_new)
        self._save_btn.clicked.connect(self._on_save)
        self._load_btn.clicked.connect(self._on_load)
        self._run_btn.clicked.connect(self._on_run)
        self._pause_btn.clicked.connect(self._on_pause)
        self._stop_btn.clicked.connect(self._on_stop)

        QShortcut(QKeySequence("Ctrl+N"), self).activated.connect(self._on_new)
        QShortcut(QKeySequence("Ctrl+S"), self).activated.connect(self._on_save)
        QShortcut(QKeySequence("Ctrl+O"), self).activated.connect(self._on_load)
        QShortcut(QKeySequence("F5"),     self).activated.connect(self._on_run)
        QShortcut(QKeySequence("F6"),     self).activated.connect(self._on_stop)
        QShortcut(QKeySequence("F7"),     self).activated.connect(self._on_pause)

        # Dirty tracking — any structural change marks the graph modified
        self._runtime.node_added.connect(lambda _: self._mark_dirty())
        self._runtime.node_removed.connect(lambda _: self._mark_dirty())
        self._runtime.wire_added.connect(lambda _: self._mark_dirty())
        self._runtime.wire_removed.connect(lambda _: self._mark_dirty())

        self._device_panel.add_device_requested.connect(self._on_add_device)
        self._device_panel.remove_device_requested.connect(self._on_remove_device)
        self._device_panel.rename_device_requested.connect(self._on_rename_device)

        self._canvas.status_message.connect(self._handle_canvas_message)
        self._canvas.device_highlighted.connect(self._device_panel.highlight_device)
        self._runtime.runtime_error.connect(
            lambda msg: self._status_bar.setText(f"⚠ {msg}")
        )
        self._runtime.running_changed.connect(self._on_running_changed)
        self._runtime.paused_changed.connect(self._on_paused_changed)
        self._registry.log_message.connect(
            lambda msg: self._status_bar.setText(msg)
        )

    # ── Default graph ─────────────────────────────────────────────────────────

    def _place_default_nodes(self) -> None:
        self._loading = True
        try:
            from nodes.flow_nodes import TickNode, StartNode
            tick  = TickNode()
            tick.x, tick.y = 60, 120
            start = StartNode()
            start.x, start.y = 60, 240
            self._runtime.add_node(tick)
            self._runtime.add_node(start)
        finally:
            self._loading = False

    # ── Run / stop ────────────────────────────────────────────────────────────

    def _on_run(self) -> None:
        if not self._runtime.is_running:
            self._runtime.start()

    def _on_stop(self) -> None:
        if self._runtime.is_running:
            self._runtime.stop()

    def _on_minimize(self) -> None:
        self.showMinimized()

    def _on_maximize(self) -> None:
        if self.isMaximized():
            self.showNormal()
            self._max_btn.set_char('□')
        else:
            self.showMaximized()
            self._max_btn.set_char('❐')

    def _on_close_window(self) -> None:
        self.close()

    def _on_pause(self) -> None:
        self._runtime.toggle_pause()

    def _on_running_changed(self, running: bool) -> None:
        self._run_btn.setEnabled(not running)
        self._pause_btn.setEnabled(running)
        self._stop_btn.setEnabled(running)
        self._status_bar.setText("▶ Running" if running else "■ Stopped")

    def _on_paused_changed(self, paused: bool) -> None:
        self._pause_btn.set_svg("resume.svg" if paused else "pause.svg")
        self._pause_btn.setToolTip("Resume Graph  (F7)" if paused else "Pause Graph  (F7)")
        self._status_bar.setText("⏺ Paused" if paused else "▶ Running")

    # ── New / dirty tracking ──────────────────────────────────────────────────

    def _mark_dirty(self) -> None:
        if self._loading:
            return
        if not self._dirty:
            self._dirty = True
            self._update_title_label()

    def _mark_clean(self) -> None:
        self._dirty = False
        self._update_title_label()

    def _update_title_label(self) -> None:
        name = self._graph_path.stem if self._graph_path else "Untitled"
        self._graph_name_label.setText(f"{name} •" if self._dirty else name)

    def _confirm_discard_changes(self) -> bool:
        """Show a save/discard/cancel dialog when there are unsaved changes.

        Returns True if the caller should proceed, False if the user cancelled.
        """
        if not self._dirty:
            return True
        result = _ConfirmDialog(
            self,
            "Unsaved Changes",
            "The current graph has unsaved changes.",
        ).exec()
        if result == _ConfirmDialog.SAVE:
            self._on_save()
            # If the save dialog was cancelled _dirty is still True
            return not self._dirty
        if result == _ConfirmDialog.DISCARD:
            return True
        return False  # Cancel

    def _on_new(self) -> None:
        if not self._confirm_discard_changes():
            return
        was_running = self._runtime.is_running
        if was_running:
            self._runtime.stop()
        self._loading = True
        try:
            self._canvas.load_saved_groups([])
            for nid in list(self._runtime.nodes.keys()):
                self._runtime.remove_node(nid)
        finally:
            self._loading = False
        self._graph_path = None
        self._place_default_nodes()
        self._mark_clean()
        self._status_bar.setText("New graph created.")
        if was_running:
            self._runtime.start()

    # ── Save / load ───────────────────────────────────────────────────────────

    def _on_save(self) -> None:
        if not self._graph_path:
            path, _ = QFileDialog.getSaveFileName(
                self, "Save Graph", "untitled.sfgraph",
                "SensoryFlow Graph (*.sfgraph);;JSON (*.json)"
            )
            if not path:
                return
            self._graph_path = Path(path)

        name  = self._graph_path.stem
        graph = self._runtime.to_saved_graph(name)
        graph.groups = self._canvas.get_saved_groups()
        try:
            self._graph_path.write_text(
                json.dumps(graph.to_dict(), indent=2), encoding="utf-8"
            )
            self._mark_clean()
            self._status_bar.setText(f"Saved → {self._graph_path}")
        except Exception as exc:
            log.error("Save failed: %s", exc)
            self._status_bar.setText(f"Save failed: {exc}")

    def _on_load(self) -> None:
        if not self._confirm_discard_changes():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Graph", "",
            "SensoryFlow Graph (*.sfgraph);;JSON (*.json)"
        )
        if not path:
            return
        try:
            data  = json.loads(Path(path).read_text(encoding="utf-8"))
            graph = SavedGraph.from_dict(data)
            self._load_graph(graph)
            self._graph_path = Path(path)
            self._mark_clean()
            self._status_bar.setText(f"Loaded ← {path}")
        except Exception as exc:
            log.error("Load failed: %s", exc)
            self._status_bar.setText(f"Load failed: {exc}")

    def _load_graph(self, graph: SavedGraph) -> None:
        was_running = self._runtime.is_running
        if was_running:
            self._runtime.stop()

        self._loading = True
        try:
            # Clear current graph (nodes and groups)
            self._canvas.load_saved_groups([])
            for nid in list(self._runtime.nodes.keys()):
                self._runtime.remove_node(nid)

            # Recreate nodes
            for sn in graph.nodes:
                node = self._registry.create_node(sn.type_key, node_id=sn.node_id)
                if node:
                    node.x = sn.x
                    node.y = sn.y
                    node.set_state(sn.state)
                    self._runtime.add_node(node)
                else:
                    log.warning("Unknown node type: %s", sn.type_key)

            # Recreate wires
            for wire in graph.wires:
                self._runtime.add_wire(wire)

            # Restore groups
            self._canvas.load_saved_groups(graph.groups)

            # Restore device aliases
            if graph.device_aliases:
                from core.device_node_base import set_device_alias
                for device_id, alias in graph.device_aliases.items():
                    set_device_alias(device_id, alias)
                    row = self._device_panel._rows.get(device_id)
                    if row:
                        row.set_alias(alias)
        finally:
            self._loading = False

        if was_running:
            self._runtime.start()

    # ── Device management ─────────────────────────────────────────────────────

    def _on_add_device(self, class_key: str, descriptor: ConnectionDescriptor) -> None:
        device = self._registry.create_device(class_key, descriptor)
        if device:
            self._status_bar.setText(
                f"Connecting to {device.DEVICE_NAME} @ {descriptor.address}…")

    def _on_rename_device(self, device_id: str, alias: str) -> None:
        self._registry.rename_device(device_id, alias)

    def _on_remove_device(self, device_id: str) -> None:
        self._registry.remove_device(device_id)

    # ── Canvas message relay (add node) ──────────────────────────────────────

    def _handle_canvas_message(self, msg: str) -> None:
        if msg.startswith("__add_node__"):
            parts    = msg.split("__")
            type_key = parts[2]
            x        = float(parts[3])
            y        = float(parts[4])
            node = self._registry.create_node(type_key)
            if node:
                node.x = x
                node.y = y
                self._runtime.add_node(node)
        elif msg.startswith("__paste_nodes__"):
            import json as _json, uuid as _uuid
            data = _json.loads(msg[len("__paste_nodes__"):])
            paste_x = data["paste_x"]
            paste_y = data["paste_y"]
            id_map: dict[str, str] = {}
            for entry in data["nodes"]:
                node = self._registry.create_node(entry["type_key"])
                if node:
                    node.set_state(entry["state"])
                    node.x = paste_x + entry["dx"]
                    node.y = paste_y + entry["dy"]
                    self._runtime.add_node(node)
                    id_map[entry["old_id"]] = node.node_id
            for wd in data.get("wires", []):
                new_src = id_map.get(wd["src_node"])
                new_dst = id_map.get(wd["dst_node"])
                if new_src and new_dst:
                    wire = WireDescriptor(
                        wire_id  = str(_uuid.uuid4()),
                        src_node = new_src, src_pin = wd["src_pin"],
                        dst_node = new_dst, dst_pin = wd["dst_pin"],
                    )
                    self._runtime.add_wire(wire)
            if "group" in data and id_map:
                self._canvas.add_pasted_group(data["group"], id_map, paste_x, paste_y)
        else:
            self._status_bar.setText(msg)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "_resize_handle"):
            maximised = self.isMaximized()
            self._resize_handle.setVisible(not maximised)
            if not maximised:
                sz = self._resize_handle.size()
                self._resize_handle.move(
                    self.width()  - sz.width(),
                    self.height() - sz.height(),
                )
                self._resize_handle.raise_()

    def _on_post_show(self) -> None:
        """Restore saved devices after the window is visible."""
        try:
            load_devices(self._registry)
        except Exception as exc:
            log.warning('Could not restore devices: %s', exc)

    def closeEvent(self, event) -> None:
        if not self._confirm_discard_changes():
            event.ignore()
            return
        self._runtime.stop()
        try:
            save_devices(self._registry)
        except Exception as exc:
            log.warning('Could not save devices: %s', exc)
        super().closeEvent(event)


# ─── Helpers ─────────────────────────────────────────────────────────────────

_ICON_DIR = Path(__file__).parent.parent / "assets" / "icons" / "ui"


class _ConfirmDialog(QDialog):
    """Styled Save / Discard / Cancel dialog matching the app theme."""

    SAVE    = 0
    DISCARD = 1
    CANCEL  = 2

    def __init__(self, parent: QWidget, title: str, message: str) -> None:
        super().__init__(
            parent,
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog,
        )
        self.setModal(True)
        self.setFixedWidth(360)
        self.setStyleSheet("""
            QDialog {
                background: #220d14;
                border: 1px solid #c90084;
                border-radius: 8px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 16)
        layout.setSpacing(12)

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(
            "color:#f95979; font-size:11pt; font-weight:bold; background:transparent;"
        )
        layout.addWidget(title_lbl)

        msg_lbl = QLabel(message)
        msg_lbl.setWordWrap(True)
        msg_lbl.setStyleSheet("color:#ffd0de; background:transparent;")
        layout.addWidget(msg_lbl)

        layout.addSpacing(4)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addStretch()

        _btn_style = (
            "QPushButton {{ background:{bg}; color:{fg}; border:{bd};"
            " border-radius:5px; padding:4px 16px; }}"
            "QPushButton:hover {{ background:#f95979; color:#fff; border:none; }}"
        )

        save_btn = QPushButton("Save")
        save_btn.setFixedHeight(30)
        save_btn.setStyleSheet(
            _btn_style.format(bg="#c90084", fg="#fff", bd="none")
        )

        discard_btn = QPushButton("Discard")
        discard_btn.setFixedHeight(30)
        discard_btn.setStyleSheet(
            _btn_style.format(bg="#45072f", fg="#ffd0de", bd="1px solid #c90084")
        )

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedHeight(30)
        cancel_btn.setStyleSheet(
            _btn_style.format(bg="#2d1020", fg="#c8889a", bd="none")
        )

        for btn in (save_btn, discard_btn, cancel_btn):
            btn.setMinimumWidth(80)
            btn_row.addWidget(btn)

        save_btn.clicked.connect(lambda: self.done(self.SAVE))
        discard_btn.clicked.connect(lambda: self.done(self.DISCARD))
        cancel_btn.clicked.connect(lambda: self.done(self.CANCEL))

        layout.addLayout(btn_row)


class _ToolButton(QPushButton):
    """
    Push button that renders an SVG icon.

    Parameters
    ----------
    svg_name : filename inside assets/icons/ui/, e.g. "play.svg".
               Falls back to text label if the file doesn't exist.
    label    : fallback text (and accessibility label).
    """

    def __init__(self, svg_name: str, label: str,
                 tooltip: str = "", accent: bool = False,
                 ghost: bool = False) -> None:
        super().__init__()
        self.setFixedSize(34, 34)
        self.setToolTip(tooltip)
        self._accent   = accent
        self._ghost    = ghost
        self._label    = label
        self._renderer = self._load_svg(svg_name)
        self._apply_style()

    def _load_svg(self, name: str) -> Optional[QSvgRenderer]:
        path = _ICON_DIR / name
        if path.exists():
            r = QSvgRenderer(str(path))
            return r if r.isValid() else None
        return None

    def set_svg(self, svg_name: str) -> None:
        """Swap icon at runtime (e.g. play ↔ resume)."""
        self._renderer = self._load_svg(svg_name)
        self.update()

    def _apply_style(self) -> None:
        if self._ghost:
            self.setStyleSheet("""
                QPushButton {
                    background: transparent;
                    border: none;
                    border-radius: 6px;
                }
                QPushButton:hover { background: rgba(249,89,121,0.12); }
                QPushButton:disabled { background: transparent; }
            """)
            return
        bg = "#c90084" if self._accent else "#45072f"
        self.setStyleSheet(f"""
            QPushButton {{
                background: {bg};
                border: none;
                border-radius: 6px;
            }}
            QPushButton:hover {{ background: #f95979; }}
            QPushButton:disabled {{ background: #2d1020; }}
        """)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)   # draw background / border
        if self._renderer is None:
            # Fallback: draw text label
            p = QPainter(self)
            p.setPen(QColor("#ffd0de" if self.isEnabled() else "#6b3050"))
            p.setFont(QFont("Segoe UI Symbol", 11))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._label)
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.isEnabled():
            p.setOpacity(0.3)
        margin = 7
        r = QRectF(margin, margin,
                   self.width() - margin * 2, self.height() - margin * 2)
        self._renderer.render(p, r)


class _WinButton(QPushButton):
    """Compact window control button (minimize / maximize / close)."""
    def __init__(self, char: str, hover_color: str, slot) -> None:
        super().__init__(char)
        self._hover_color = hover_color
        self.setFixedSize(28, 28)
        self._apply_style()
        self.clicked.connect(slot)

    def set_char(self, char: str) -> None:
        self.setText(char)

    def _apply_style(self) -> None:
        self.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: #6b3050;
                border: none;
                border-radius: 4px;
                font-size: 10pt;
                font-family: 'Segoe UI Symbol', 'Segoe UI', sans-serif;
            }}
            QPushButton:hover {{
                background: #2d1020;
                color: {self._hover_color};
            }}
        """)


class _TitleBar(QWidget):
    """
    Custom title bar that enables window dragging.
    Pass-through: LMB drag moves the parent window.
    Double-click: toggle maximize.
    """
    def __init__(self, window: QWidget) -> None:
        super().__init__(window)
        self._window    = window
        self._dragging  = False
        self._drag_pos  = QPoint()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._drag_pos = (
                event.globalPosition().toPoint() - self._window.frameGeometry().topLeft()
            )
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._dragging and event.buttons() & Qt.MouseButton.LeftButton:
            if self._window.isMaximized():
                self._window.showNormal()
            self._window.move(
                event.globalPosition().toPoint() - self._drag_pos
            )
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._dragging = False

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            if self._window.isMaximized():
                self._window.showNormal()
            else:
                self._window.showMaximized()


class _DragZone(QWidget):
    """
    Transparent spacer that forwards mouse drag events to the title bar
    so the user can drag the window by clicking anywhere in the centre area.
    """
    def __init__(self, window: QWidget) -> None:
        super().__init__()
        self._window   = window
        self._dragging = False
        self._drag_pos = QPoint()
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.setStyleSheet("background: transparent;")

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._drag_pos = (
                event.globalPosition().toPoint() - self._window.frameGeometry().topLeft()
            )
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._dragging and event.buttons() & Qt.MouseButton.LeftButton:
            if self._window.isMaximized():
                self._window.showNormal()
            self._window.move(
                event.globalPosition().toPoint() - self._drag_pos
            )
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._dragging = False

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            if self._window.isMaximized():
                self._window.showNormal()
            else:
                self._window.showMaximized()


class _ResizeHandle(QWidget):
    """Bottom-right corner drag handle for resizing the frameless window."""

    HANDLE_SIZE = 18

    def __init__(self, window: QWidget) -> None:
        super().__init__(window)
        self._window    = window
        self._dragging  = False
        self._drag_start_pos   = QPoint()
        self._drag_start_geom  = None
        self.setFixedSize(self.HANDLE_SIZE, self.HANDLE_SIZE)
        self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.raise_()

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        sz   = self.HANDLE_SIZE
        col  = QColor("#c90084")
        col2 = QColor("#45072f")
        # Three diagonal grip lines (bottom-right corner, lines run NE→SW)
        for i, (x1, y1, x2, y2) in enumerate([
            (sz-2, sz-4,  sz-4,  sz-2),
            (sz-2, sz-9,  sz-9,  sz-2),
            (sz-2, sz-14, sz-14, sz-2),
        ]):
            p.setPen(QPen(col2, 2.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(x1+1, y1+1, x2+1, y2+1)
            p.setPen(QPen(col,  1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(x1, y1, x2, y2)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging          = True
            self._drag_start_pos    = event.globalPosition().toPoint()
            self._drag_start_geom   = self._window.geometry()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if not self._dragging:
            return
        delta = event.globalPosition().toPoint() - self._drag_start_pos
        g     = self._drag_start_geom
        new_w = max(600, g.width()  + delta.x())
        new_h = max(400, g.height() + delta.y())
        self._window.resize(new_w, new_h)
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._dragging = False


_APP_STYLE = """
QWidget {
    font-family: 'Segoe UI', 'Ubuntu', sans-serif;
    font-size: 9pt;
}
QToolTip {
    background: #220d14;
    color: #ffd0de;
    border: 1px solid #c90084;
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 9pt;
}
/* Outer window border */
QWidget[isMainWindow="true"] {
    border: 1px solid #c90084;
    border-radius: 8px;
    background: #1a0a0f;
}
QScrollBar:vertical {
    background: #1a0a0f;
    width: 8px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #45072f;
    border-radius: 4px;
    min-height: 20px;
}
QScrollBar::handle:vertical:hover { background: #c90084; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""
