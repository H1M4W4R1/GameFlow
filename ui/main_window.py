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
    QLabel, QFileDialog, QSizePolicy, QFrame,
)

from core.device_registry    import DeviceRegistry
from core.graph_runtime      import GraphRuntime
from core.device_persistence import save_devices, load_devices
from core.types           import SavedGraph, ConnectionDescriptor
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

        layout.addSpacing(10)

        # ── File buttons ───────────────────────────────────────────────────
        self._save_btn = _ToolButton("save.svg", "💾", "Save Graph  (Ctrl+S)")
        self._load_btn = _ToolButton("load.svg", "📂", "Load Graph  (Ctrl+O)")
        layout.addWidget(self._save_btn)
        layout.addWidget(self._load_btn)

        # ── Drag zone (stretchy centre) + filename ─────────────────────────
        drag_zone = _DragZone(self)   # transparent, pass mouse events to window
        layout.addWidget(drag_zone, stretch=1)

        self._graph_name_label = QLabel("Untitled")
        self._graph_name_label.setStyleSheet(
            "color:#7a4060;font-size:8pt;background:transparent;")
        layout.addWidget(self._graph_name_label)

        layout.addSpacing(6)

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
        self._save_btn.clicked.connect(self._on_save)
        self._load_btn.clicked.connect(self._on_load)
        self._run_btn.clicked.connect(self._on_run)
        self._pause_btn.clicked.connect(self._on_pause)
        self._stop_btn.clicked.connect(self._on_stop)

        QShortcut(QKeySequence("Ctrl+S"), self).activated.connect(self._on_save)
        QShortcut(QKeySequence("Ctrl+O"), self).activated.connect(self._on_load)
        QShortcut(QKeySequence("F5"),     self).activated.connect(self._on_run)
        QShortcut(QKeySequence("F6"),     self).activated.connect(self._on_stop)
        QShortcut(QKeySequence("F7"),     self).activated.connect(self._on_pause)

        self._device_panel.add_device_requested.connect(self._on_add_device)
        self._device_panel.remove_device_requested.connect(self._on_remove_device)
        self._device_panel.rename_device_requested.connect(self._on_rename_device)

        self._canvas.status_message.connect(self._handle_canvas_message)
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
        from nodes.flow_nodes import TickNode, StartNode
        tick  = TickNode()
        tick.x, tick.y = 60, 120
        start = StartNode()
        start.x, start.y = 60, 240
        self._runtime.add_node(tick)
        self._runtime.add_node(start)

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
        try:
            self._graph_path.write_text(
                json.dumps(graph.to_dict(), indent=2), encoding="utf-8"
            )
            self._graph_name_label.setText(name)
            self._status_bar.setText(f"Saved → {self._graph_path}")
        except Exception as exc:
            log.error("Save failed: %s", exc)
            self._status_bar.setText(f"Save failed: {exc}")

    def _on_load(self) -> None:
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
            self._graph_name_label.setText(graph.name)
            self._status_bar.setText(f"Loaded ← {path}")
        except Exception as exc:
            log.error("Load failed: %s", exc)
            self._status_bar.setText(f"Load failed: {exc}")

    def _load_graph(self, graph: SavedGraph) -> None:
        was_running = self._runtime.is_running
        if was_running:
            self._runtime.stop()

        # Clear current graph
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

        if was_running:
            self._runtime.start()

    # ── Device management ─────────────────────────────────────────────────────

    def _on_add_device(self, class_key: str, descriptor: ConnectionDescriptor) -> None:
        device = self._registry.create_device(class_key, descriptor)
        if device:
            self._status_bar.setText(
                f"Connecting to {device.DEVICE_NAME} @ {descriptor.address}…", 3000
            )

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
        else:
            self._status_bar.setText(msg)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "_resize_handle"):
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
        self._runtime.stop()
        try:
            save_devices(self._registry)
        except Exception as exc:
            log.warning('Could not save devices: %s', exc)
        super().closeEvent(event)


# ─── Helpers ─────────────────────────────────────────────────────────────────

_ICON_DIR = Path(__file__).parent.parent / "assets" / "icons" / "ui"


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
                 tooltip: str = "", accent: bool = False) -> None:
        super().__init__()
        self.setFixedSize(34, 34)
        self.setToolTip(tooltip)
        self._accent   = accent
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
        # Three diagonal grip lines
        for i, (x1, y1, x2, y2) in enumerate([
            (sz-4,  2,   sz-2, 4),
            (sz-9,  2,   sz-2, 9),
            (sz-14, 2,   sz-2, 14),
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
