"""
Debug nodes — display and inspection nodes for debugging graph data.

All display nodes update instantly when upstream data arrives
(on_data_received), so no exec-tick is required.

Nodes
-----
LogNode            — logs a labelled value; shows last message in body
NumericDisplayNode — shows live numeric value in large text
TextDisplayNode    — shows live string/any value as wrapped text
TimeDisplayNode    — converts seconds or milliseconds to HH:MM:SS
StateIndicatorNode — coloured circle + TRUE/FALSE for a boolean input
WaveformDisplayNode — scrolling oscilloscope-style waveform history
TouchpadDisplayNode — displays x/y coordinates as a point on a touchpad grid
"""
from __future__ import annotations

import logging
from collections import deque
from typing import Any

from PyQt6.QtCore import QRectF, Qt, QPointF
from PyQt6.QtGui  import QAction, QPainter, QColor, QFont, QPen, QPainterPath, QBrush
from PyQt6.QtWidgets import QMenu

from core.localization import tr
from core.node_base import NodeBase
from core.types     import PinDescriptor, PinDirection, PinType

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# LOG / DEBUG
# ─────────────────────────────────────────────────────────────────────────────

class LogNode(NodeBase):
    """
    Logs a labelled value when triggered; shows the last logged message
    inside the node body.  Label is set via editable field.
    """
    NODE_NAME  = "Log / Debug"
    NODE_GROUP = "Debug"
    PINS = [
        PinDescriptor("exec_in",  PinDirection.INPUT,  PinType.TICK),
        PinDescriptor("value",    PinDirection.INPUT,  PinType.ANY,  default=""),
        PinDescriptor("exec_out", PinDirection.OUTPUT, PinType.TICK),
    ]
    EDITABLE_FIELDS = {
        "label": (str, "LOG"),
    }
    MIN_WIDTH  = 200.0
    MIN_HEIGHT = 90.0

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._last_msg: str = ""

    def execute(self, trigger_pin: str) -> None:
        label = str(self.get_field("label") or "LOG")
        value = self.get_input("value")
        msg   = f"[{label}] {value}"
        log.info(msg)
        self.log_message.emit(msg)
        self._last_msg = msg
        self.fire_tick("exec_out")
        self.node_changed.emit()

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        painter.setPen(QColor("#aed581"))
        painter.setFont(QFont("Courier New", 8))
        txt = self._last_msg
        if len(txt) > 28:
            txt = txt[:25] + "…"
        painter.drawText(
            QRectF(rect.x(), rect.y(), rect.width(), 20),
            Qt.AlignmentFlag.AlignCenter,
            txt,
        )


# ─────────────────────────────────────────────────────────────────────────────
# NUMERIC DISPLAY
# ─────────────────────────────────────────────────────────────────────────────

class NumericDisplayNode(NodeBase):
    """
    Shows a live numeric value in a large font.
    Updates instantly whenever upstream data is pushed — no tick required.
    'decimals' field controls how many decimal places are shown.
    """
    NODE_NAME  = "Numeric Display"
    NODE_GROUP = "Debug"
    PINS = [
        PinDescriptor("value", PinDirection.INPUT, PinType.FLOAT),
    ]
    EDITABLE_FIELDS = {
        "decimals": (int, 2),
    }
    MIN_WIDTH  = 180.0
    MIN_HEIGHT = 80.0

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._display_value: float = 0.0

    def on_data_received(self, pin_name: str, value: Any) -> None:
        if pin_name == "value":
            try:
                self._display_value = float(value)
            except (TypeError, ValueError):
                pass
            self.node_changed.emit()

    def execute(self, trigger_pin: str) -> None:
        pass

    def get_state(self) -> dict[str, Any]:
        state = super().get_state()
        state["_display_value"] = self._display_value
        return state

    def set_state(self, state: dict[str, Any]) -> None:
        super().set_state(state)
        self._display_value = float(state.get("_display_value", 0.0))

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        decimals = max(0, int(self.get_field("decimals") or 2))
        fmt      = f"{self._display_value:.{decimals}f}"
        painter.setPen(QColor("#4fc3f7"))
        painter.setFont(QFont("Courier New", 20, QFont.Weight.Bold))
        painter.drawText(
            QRectF(rect.x(), rect.y(), rect.width(), 36),
            Qt.AlignmentFlag.AlignCenter,
            fmt,
        )


# ─────────────────────────────────────────────────────────────────────────────
# TEXT DISPLAY
# ─────────────────────────────────────────────────────────────────────────────

class TextDisplayNode(NodeBase):
    """
    Shows a live string value inside the node body.
    Updates instantly whenever upstream data is pushed — no tick required.
    Long strings are truncated with an ellipsis.
    """
    NODE_NAME  = "Text Display"
    NODE_GROUP = "Debug"
    PINS = [
        PinDescriptor("value", PinDirection.INPUT, PinType.ANY, default=""),
    ]
    MIN_WIDTH  = 200.0
    MIN_HEIGHT = 65.0

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._display_text: str = ""

    def on_data_received(self, pin_name: str, value: Any) -> None:
        if pin_name == "value":
            self._display_text = str(value) if value is not None else ""
            self.node_changed.emit()

    def execute(self, trigger_pin: str) -> None:
        pass

    def get_state(self) -> dict[str, Any]:
        state = super().get_state()
        state["_display_text"] = self._display_text
        return state

    def set_state(self, state: dict[str, Any]) -> None:
        super().set_state(state)
        self._display_text = str(state.get("_display_text", ""))

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        max_chars = int(rect.width() / 7.5)
        display   = self._display_text
        if len(display) > max_chars:
            display = display[:max_chars - 1] + "…"
        painter.setPen(QColor("#ce93d8"))
        painter.setFont(QFont("Courier New", 9))
        painter.drawText(
            QRectF(rect.x(), rect.y(), rect.width(), 28),
            Qt.AlignmentFlag.AlignCenter,
            display,
        )


# ─────────────────────────────────────────────────────────────────────────────
# TIME DISPLAY  (seconds or milliseconds → HH:MM:SS)
# ─────────────────────────────────────────────────────────────────────────────

def _to_hhmmss(raw: float) -> str:
    """Convert seconds (float) to HH:MM:SS string."""
    total_s = int(max(0.0, raw))
    h = total_s // 3600
    m = (total_s % 3600) // 60
    s = total_s % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


class TimeDisplayNode(NodeBase):
    """
    Converts a seconds (float) value to HH:MM:SS format and displays it in
    the node body.  Updates instantly on every data push — no tick required.
    """
    NODE_NAME  = "Time Display"
    NODE_GROUP = "Debug"
    PINS = [
        PinDescriptor("value", PinDirection.INPUT, PinType.FLOAT),
    ]
    MIN_WIDTH  = 200.0
    MIN_HEIGHT = 100.0

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._raw_value: float = 0.0

    def on_data_received(self, pin_name: str, value: Any) -> None:
        if pin_name == "value":
            try:
                self._raw_value = float(value)
            except (TypeError, ValueError):
                pass
            self.node_changed.emit()

    def execute(self, trigger_pin: str) -> None:
        pass

    def get_state(self) -> dict[str, Any]:
        state = super().get_state()
        state["_raw_value"] = self._raw_value
        return state

    def set_state(self, state: dict[str, Any]) -> None:
        super().set_state(state)
        self._raw_value = float(state.get("_raw_value", 0.0))

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        painter.setPen(QColor("#ffb74d"))
        painter.setFont(QFont("Courier New", 18, QFont.Weight.Bold))
        painter.drawText(
            QRectF(rect.x(), rect.y(), rect.width(), 36),
            Qt.AlignmentFlag.AlignCenter,
            _to_hhmmss(self._raw_value),
        )

        painter.setPen(QColor("#616161"))
        painter.setFont(QFont("Courier New", 7))


# ─────────────────────────────────────────────────────────────────────────────
# STATE INDICATOR
# ─────────────────────────────────────────────────────────────────────────────

class StateIndicatorNode(NodeBase):
    """
    Displays a coloured indicator circle and TRUE/FALSE label for a boolean or float input.
    Green = True, Red = False.
    For float input, value is floored to int before converting to bool.
    Updates instantly on every data push — no tick required.
    """
    NODE_NAME  = "State Indicator"
    NODE_GROUP = "Debug"
    PINS = [
        PinDescriptor("state", PinDirection.INPUT, PinType.ANY, default=False),
    ]
    MIN_WIDTH  = 160.0
    MIN_HEIGHT = 110.0

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._state: bool = False

    def on_data_received(self, pin_name: str, value: Any) -> None:
        if pin_name == "state":
            if isinstance(value, float):
                # Floor float to int, then convert to bool
                self._state = bool(int(value))
            else:
                # For bool and other types, convert directly to bool
                self._state = bool(value)
            self.node_changed.emit()

    def execute(self, trigger_pin: str) -> None:
        pass

    def get_state(self) -> dict[str, Any]:
        state = super().get_state()
        state["_state"] = self._state
        return state

    def set_state(self, state: dict[str, Any]) -> None:
        super().set_state(state)
        self._state = bool(state.get("_state", False))

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        color  = QColor("#4caf50") if self._state else QColor("#ef5350")
        text   = "TRUE" if self._state else "FALSE"

        radius = 12
        cx = int(rect.center().x())
        cy = int(rect.y() + radius + 2)
        painter.setBrush(color)
        painter.setPen(color.darker(130))
        painter.drawEllipse(cx - radius, cy - radius, radius * 2, radius * 2)

        painter.setPen(color)
        painter.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        painter.drawText(
            QRectF(rect.x(), rect.y() + radius * 2 + 6, rect.width(), 22),
            Qt.AlignmentFlag.AlignCenter,
            text,
        )


# ─────────────────────────────────────────────────────────────────────────────
# WAVEFORM DISPLAY
# ─────────────────────────────────────────────────────────────────────────────

class WaveformDisplayNode(NodeBase):
    """
    Scrolling oscilloscope-style waveform display.

    Buffers incoming float values and draws them as a continuous trace.
    The Y axis can auto-scale to the visible samples or be set to a fixed range.
    The sample count and range mode are configured via the right-click context menu.
    Updates instantly whenever upstream data is pushed — no tick required.
    """
    NODE_NAME  = "Waveform Display"
    NODE_GROUP = "Debug"
    PINS = [
        PinDescriptor("value", PinDirection.INPUT, PinType.FLOAT),
    ]
    MIN_WIDTH  = 220.0
    MIN_HEIGHT = 130.0

    _MAX_SAMPLES = 500
    _RANGE_PRESETS = {
        "Auto":     (None, None),
        "0 - 1":    (0.0, 1.0),
        "0 - 100":  (0.0, 100.0),
        "0 - 255":  (0.0, 255.0),
        "-1 - 1":   (-1.0, 1.0),
        "-100 - 100": (-100.0, 100.0),
    }

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._buf:               deque[float] = deque(maxlen=self._MAX_SAMPLES)
        self._sample_count:      int          = 200
        self._sample_count_mode: str          = "Preset"
        self._range_mode:        str          = "Auto"
        self._custom_min:        float        = 0.0
        self._custom_max:        float        = 100.0

    def on_start(self) -> None:
        self._buf.clear()

    # ── context-menu API ──────────────────────────────────────────────────────

    def get_sample_count(self) -> int:
        return self._sample_count

    def set_sample_count(self, n: int) -> None:
        self._sample_count = max(10, min(int(n), self._MAX_SAMPLES))
        self._sample_count_mode = "Preset"
        self.node_changed.emit()

    def get_custom_sample_count(self) -> int:
        return self._sample_count

    def set_custom_sample_count(self, n: int) -> None:
        self._sample_count = max(10, min(int(n), self._MAX_SAMPLES))
        self._sample_count_mode = "Custom"
        self.node_changed.emit()

    def get_waveform_range(self) -> str:
        return self._range_mode

    def set_waveform_range(self, mode: str) -> None:
        if mode in self._RANGE_PRESETS or mode == "Custom":
            self._range_mode = mode
            self.node_changed.emit()

    def get_custom_range(self) -> tuple[float, float]:
        return (self._custom_min, self._custom_max)

    def set_custom_range(self, min_val: float, max_val: float) -> None:
        self._custom_min = float(min_val)
        self._custom_max = float(max_val)
        self._range_mode = "Custom"
        self.node_changed.emit()

    def _get_context_menu(self, canvas: Any, menu: QMenu, field_hit: Any = None) -> None:
        sample_menu = QMenu(tr("ui.canvas.menu.sample_count", default="Sample count"), menu)
        sample_menu.setStyleSheet(menu.styleSheet())
        current_samples = self.get_sample_count()
        for n_s in (50, 100, 200, 300, 500):
            act = QAction(str(n_s), sample_menu)
            act.setCheckable(True)
            act.setChecked(current_samples == n_s)
            act.triggered.connect(
                lambda _checked, s=n_s: canvas._set_sample_count(self.node_id, s)
            )
            sample_menu.addAction(act)

        sample_menu.addSeparator()
        custom_samples_act = QAction(
            tr("ui.canvas.menu.custom_sample_count", default="Custom..."),
            sample_menu,
        )
        custom_samples_act.triggered.connect(
            lambda: canvas._open_sample_count_dialog(self.node_id)
        )
        sample_menu.addAction(custom_samples_act)
        menu.addMenu(sample_menu)

        range_menu = QMenu(tr("ui.canvas.menu.waveform_range", default="Y-axis range"), menu)
        range_menu.setStyleSheet(menu.styleSheet())
        current_range = self.get_waveform_range()
        for range_mode in self._RANGE_PRESETS.keys():
            act = QAction(range_mode, range_menu)
            act.setCheckable(True)
            act.setChecked(current_range == range_mode)
            act.triggered.connect(
                lambda _checked, m=range_mode: canvas._set_waveform_range(self.node_id, m)
            )
            range_menu.addAction(act)

        range_menu.addSeparator()
        custom_range_act = QAction(
            tr("ui.canvas.menu.custom_range", default="Custom..."),
            range_menu,
        )
        custom_range_act.setCheckable(True)
        custom_range_act.setChecked(current_range == "Custom")
        custom_range_act.triggered.connect(
            lambda: canvas._open_waveform_custom_range_dialog(self.node_id)
        )
        range_menu.addAction(custom_range_act)
        menu.addMenu(range_menu)

    # ── data / state ──────────────────────────────────────────────────────────

    def on_data_received(self, pin_name: str, value: Any) -> None:
        if pin_name == "value":
            try:
                self._buf.append(float(value))
            except (TypeError, ValueError):
                pass
            self.node_changed.emit()

    def execute(self, trigger_pin: str) -> None:
        pass

    def get_state(self) -> dict[str, Any]:
        state = super().get_state()
        state["_buf"]                = list(self._buf)
        state["_sample_count"]       = self._sample_count
        state["_sample_count_mode"]  = self._sample_count_mode
        state["_range_mode"]         = self._range_mode
        state["_custom_min"]         = self._custom_min
        state["_custom_max"]         = self._custom_max
        return state

    def set_state(self, state: dict[str, Any]) -> None:
        super().set_state(state)
        raw = state.get("_buf", [])
        self._buf = deque(
            (float(v) for v in raw),
            maxlen=self._MAX_SAMPLES,
        )
        self._sample_count = int(state.get("_sample_count", 200))
        self._sample_count_mode = str(state.get("_sample_count_mode", "Preset"))
        self._range_mode = str(state.get("_range_mode", "Auto"))
        self._custom_min = float(state.get("_custom_min", 0.0))
        self._custom_max = float(state.get("_custom_max", 100.0))

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        margin = 4
        x0 = rect.x()     + margin
        w  = rect.width()  - 2 * margin
        y0 = rect.y()      + margin
        # Reserve 14 px at bottom for the value label
        h  = max(1.0, rect.height() - 2 * margin - 14)

        # Scope background
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor("#0d1b1e")))
        painter.drawRoundedRect(QRectF(x0, y0, w, h), 3, 3)

        samples = list(self._buf)[-self._sample_count:]

        if len(samples) < 2:
            painter.setPen(QColor("#4db6ac"))
            painter.setFont(QFont("Courier New", 9))
            painter.drawText(
                QRectF(x0, y0, w, h),
                Qt.AlignmentFlag.AlignCenter,
                "---",
            )
            return

        # Apply range mode: Auto, preset, or custom
        if self._range_mode == "Auto":
            v_min   = min(samples)
            v_max   = max(samples)
        elif self._range_mode == "Custom":
            v_min = self._custom_min
            v_max = self._custom_max
        else:
            preset = self._RANGE_PRESETS.get(self._range_mode, (None, None))
            v_min, v_max = preset
            if v_min is None or v_max is None:
                v_min   = min(samples)
                v_max   = max(samples)
        v_range = max(1e-6, v_max - v_min)

        # Centre gridline
        painter.setPen(QPen(QColor("#1e3a3a"), 1, Qt.PenStyle.DotLine))
        mid_y = y0 + h * 0.5
        painter.drawLine(QPointF(x0, mid_y), QPointF(x0 + w, mid_y))

        # Waveform trace
        n = len(samples)
        path = QPainterPath()
        for i, v in enumerate(samples):
            px = x0 + w * i / (n - 1)
            py = y0 + h * (1.0 - (v - v_min) / v_range)
            if i == 0:
                path.moveTo(px, py)
            else:
                path.lineTo(px, py)

        painter.setPen(QPen(QColor("#4db6ac"), 1.5))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)

        # Min / max labels inside scope corners
        lbl_font = QFont("Courier New", 7)
        painter.setFont(lbl_font)
        painter.setPen(QColor("#3a7a72"))
        lbl_w = w - 4
        painter.drawText(
            QRectF(x0 + 2, y0 + 1,      lbl_w, 12),
            Qt.AlignmentFlag.AlignRight,
            f"{v_max:.3g}",
        )
        painter.drawText(
            QRectF(x0 + 2, y0 + h - 12, lbl_w, 12),
            Qt.AlignmentFlag.AlignRight,
            f"{v_min:.3g}",
        )

        # Current value label
        cur_val = samples[-1]
        painter.setPen(QColor("#80cbc4"))
        painter.setFont(QFont("Courier New", 8))
        painter.drawText(
            QRectF(rect.x(), rect.bottom() - 14, rect.width(), 14),
            Qt.AlignmentFlag.AlignCenter,
            f"{cur_val:.4f}",
        )


# ─────────────────────────────────────────────────────────────────────────────
# TOUCHPAD DISPLAY
# ─────────────────────────────────────────────────────────────────────────────

class TouchpadDisplayNode(NodeBase):
    """
    Displays x and y coordinates as a point on a touchpad grid (display-only).

    Coordinate system: 0,0 at bottom-left, 1,1 at top-right.
    - x input: 0 at left, 1 at right
    - y input: 0 at bottom, 1 at top

    Updates instantly whenever upstream data is pushed — no tick required.
    """
    NODE_NAME  = "Touchpad Display"
    NODE_GROUP = "Debug"
    PINS = [
        PinDescriptor("x", PinDirection.INPUT, PinType.FLOAT),
        PinDescriptor("y", PinDirection.INPUT, PinType.FLOAT),
    ]
    MIN_WIDTH  = 300.0
    MIN_HEIGHT = 300.0

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._x_value: float = 0.0
        self._y_value: float = 0.0

    def on_data_received(self, pin_name: str, value: Any) -> None:
        if pin_name == "x":
            try:
                self._x_value = max(0.0, min(1.0, float(value)))
            except (TypeError, ValueError):
                pass
            self.node_changed.emit()
        elif pin_name == "y":
            try:
                self._y_value = max(0.0, min(1.0, float(value)))
            except (TypeError, ValueError):
                pass
            self.node_changed.emit()

    def execute(self, trigger_pin: str) -> None:
        pass

    def get_state(self) -> dict[str, Any]:
        state = super().get_state()
        state["_x_value"] = self._x_value
        state["_y_value"] = self._y_value
        return state

    def set_state(self, state: dict[str, Any]) -> None:
        super().set_state(state)
        self._x_value = float(state.get("_x_value", 0.0))
        self._y_value = float(state.get("_y_value", 0.0))

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        pad = 12.0
        # Ensure square aspect ratio and center in node
        side = min(rect.width(), rect.height()) - pad * 2
        # Center horizontally and vertically
        offset_x = (rect.width() - side) / 2
        offset_y = (rect.height() - side) / 2
        pad_rect = QRectF(
            rect.x() + offset_x,
            rect.y() + offset_y,
            side,
            side,
        )

        # Background (dark touchpad area)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor("#0a0a0a")))
        painter.drawRoundedRect(pad_rect, 6, 6)

        # Grid (5x5, with inset to respect rounded corners)
        inset = 4.0  # Inset from edges
        grid_rect = pad_rect.adjusted(inset, inset, -inset, -inset)
        painter.setPen(QPen(QColor("#2a3f7e"), 1.0))
        grid_step_x = grid_rect.width() / 5
        for i in range(1, 5):
            x = grid_rect.x() + grid_step_x * i
            painter.drawLine(QPointF(x, grid_rect.y()), QPointF(x, grid_rect.bottom()))
        grid_step_y = grid_rect.height() / 5
        for i in range(1, 5):
            y = grid_rect.y() + grid_step_y * i
            painter.drawLine(QPointF(grid_rect.x(), y), QPointF(grid_rect.right(), y))

        # Border
        painter.setPen(QPen(QColor("#90a4ae"), 2.5))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(pad_rect, 6, 6)

        # Crosshair / cursor dot at current position
        # Note: y is inverted (0 at bottom, 1 at top)
        cursor_x = pad_rect.x() + self._x_value * pad_rect.width()
        cursor_y = pad_rect.bottom() - self._y_value * pad_rect.height()

        # Crosshair lines
        cross_len = 8.0
        painter.setPen(QPen(QColor("#4fc3f7"), 1.0))
        painter.drawLine(QPointF(cursor_x - cross_len, cursor_y), QPointF(cursor_x + cross_len, cursor_y))
        painter.drawLine(QPointF(cursor_x, cursor_y - cross_len), QPointF(cursor_x, cursor_y + cross_len))

        # Cursor circle
        painter.setPen(QPen(QColor("#81d4fa"), 1.5))
        painter.setBrush(QBrush(QColor("#e1f5fe")))
        painter.drawEllipse(QPointF(cursor_x, cursor_y), 5.0, 5.0)

        # Coordinate labels (bottom-left and bottom-right)
        painter.setPen(QColor("#4fc3f7"))
        painter.setFont(QFont("Courier New", 7, QFont.Weight.Bold))

        x_label_rect = QRectF(pad_rect.x() + 2, pad_rect.bottom() + 2, 40, 10)
        painter.drawText(x_label_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, f"X:{self._x_value:.2f}")

        y_label_rect = QRectF(pad_rect.right() - 42, pad_rect.bottom() + 2, 40, 10)
        painter.drawText(y_label_rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop, f"Y:{self._y_value:.2f}")
