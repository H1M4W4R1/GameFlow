"""
Control-panel nodes — interactive UI widgets embedded in the node graph.

SliderNode      — drag to set a float in [min, max] with linear/exp/log scale
ButtonNode      — monostable: outputs 1.0 while pressed, 0.0 when released
ToggleNode      — bistable: click to flip between 0.0 and 1.0
TimeSelectorNode — HH:MM:SS picker with ▲/▼ arrows, outputs total seconds
"""
from __future__ import annotations

import math
from typing import Any, Optional

from PyQt6.QtCore import Qt, QRectF, QPointF
from PyQt6.QtGui import (
    QBrush, QColor, QFont, QLinearGradient, QPainter, QPen,
)

from core.node_base import NodeBase
from core.types import PinDescriptor, PinDirection, PinType


# ── Slider ─────────────────────────────────────────────────────────────────────

class SliderNode(NodeBase):
    """Drag the track to output a float in [0, 1]."""

    NODE_NAME        = "Slider"
    NODE_GROUP       = "Controls"
    NODE_TITLE_COLOR = "#1e3a5f"

    PINS = [
        PinDescriptor("value", PinDirection.OUTPUT, PinType.FLOAT),
    ]

    MIN_WIDTH  = 200.0
    MIN_HEIGHT = 100.0   # allocates ~40 px for the custom track area

    def __init__(self, **kw: Any) -> None:
        super().__init__(**kw)
        self._value:   float = 0.0   # normalized drag position [0, 1]
        self._min_val: float = 0.0
        self._max_val: float = 1.0
        self._scale:   str   = "linear"  # "linear" | "exponential" | "logarithmic"

    # ── output mapping ─────────────────────────────────────────────────────────

    def _compute_output(self) -> float:
        """Map normalized [0,1] drag position through scale to [min_val, max_val]."""
        t = self._value
        if self._scale == "exponential":
            t = t * t
        elif self._scale == "logarithmic":
            t = math.sqrt(t)
        return self._min_val + t * (self._max_val - self._min_val)

    # ── lifecycle ──────────────────────────────────────────────────────────────

    def on_start(self) -> None:
        self.set_output("value", self._compute_output())

    def execute(self, trigger_pin: str) -> None:
        self.set_output("value", self._compute_output())

    def on_output_wire_connected(self, pin_name: str) -> None:
        self.set_output("value", self._compute_output())

    # ── range / scale protocol (duck-typed by canvas context menu) ─────────────

    def get_ctrl_range(self) -> tuple[float, float]:
        return (self._min_val, self._max_val)

    def set_ctrl_range(self, min_val: float, max_val: float) -> None:
        self._min_val = float(min_val)
        self._max_val = float(max_val)
        self.set_output("value", self._compute_output())
        self.node_changed.emit()

    def get_ctrl_scale(self) -> str:
        return self._scale

    def set_ctrl_scale(self, mode: str) -> None:
        if mode in ("linear", "exponential", "logarithmic"):
            self._scale = mode
            self.set_output("value", self._compute_output())
            self.node_changed.emit()

    # ── ctrl interaction ───────────────────────────────────────────────────────

    def on_ctrl_press(self, scene_pos: QPointF, ctrl_rect: QRectF, modifiers: Qt.KeyboardModifiers = Qt.KeyboardModifier.NoModifier) -> bool:
        self._update_from_scene(scene_pos, ctrl_rect)
        return True

    def on_ctrl_drag(self, scene_pos: QPointF, ctrl_rect: QRectF) -> None:
        self._update_from_scene(scene_pos, ctrl_rect)

    def _update_from_scene(self, scene_pos: QPointF, ctrl_rect: QRectF) -> None:
        pad     = 14.0
        track_w = ctrl_rect.width() - pad * 2
        if track_w <= 0:
            return
        raw         = scene_pos.x() - ctrl_rect.x() - pad
        self._value = max(0.0, min(1.0, raw / track_w))
        self.set_output("value", self._compute_output())
        self.node_changed.emit()

    # ── painting ───────────────────────────────────────────────────────────────

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        pad      = 14.0
        cy       = rect.y() + rect.height() * 0.55
        track_h  = 8.0
        track_x  = rect.x() + pad
        track_w  = rect.width() - pad * 2
        track_rect = QRectF(track_x, cy - track_h / 2, track_w, track_h)

        # Track background
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor("#0d0509")))
        painter.drawRoundedRect(track_rect, track_h / 2, track_h / 2)

        # Filled portion (based on normalized drag position)
        filled_w = track_w * self._value
        if filled_w > 0.5:
            fill_rect = QRectF(track_x, track_rect.y(), filled_w, track_h)
            grad = QLinearGradient(fill_rect.left(), 0, fill_rect.right(), 0)
            grad.setColorAt(0.0, QColor("#1565c0"))
            grad.setColorAt(1.0, QColor("#4fc3f7"))
            painter.setBrush(QBrush(grad))
            painter.drawRoundedRect(fill_rect, track_h / 2, track_h / 2)

        # Thumb
        thumb_x = track_x + self._value * track_w
        painter.setPen(QPen(QColor("#81d4fa"), 1.5))
        painter.setBrush(QBrush(QColor("#e1f5fe")))
        painter.drawEllipse(QPointF(thumb_x, cy), 7.0, 7.0)

        # Value label — shows actual output value (top-right of custom area)
        output_val = self._compute_output()
        painter.setPen(QColor("#4fc3f7"))
        painter.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        label_rect = QRectF(rect.x(), rect.y() + 2, rect.width() - 4, 14)
        painter.drawText(
            label_rect,
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            f"{output_val:.3f}",
        )

        # Scale indicator (bottom-left, tiny) when non-linear
        if self._scale != "linear":
            painter.setPen(QColor("#455a64"))
            painter.setFont(QFont("Segoe UI", 7))
            ind = "exp" if self._scale == "exponential" else "log"
            painter.drawText(
                QRectF(rect.x() + 2, rect.y() + 2, 28, 12),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                ind,
            )

    # ── state persistence ──────────────────────────────────────────────────────

    def get_state(self) -> dict[str, Any]:
        s = super().get_state()
        s["__ctrl_value__"] = self._value
        s["__ctrl_min__"]   = self._min_val
        s["__ctrl_max__"]   = self._max_val
        s["__ctrl_scale__"] = self._scale
        return s

    def set_state(self, state: dict[str, Any]) -> None:
        v     = state.pop("__ctrl_value__", None)
        mn    = state.pop("__ctrl_min__",   None)
        mx    = state.pop("__ctrl_max__",   None)
        scale = state.pop("__ctrl_scale__", None)
        super().set_state(state)
        if v is not None:     self._value   = float(v)
        if mn is not None:    self._min_val = float(mn)
        if mx is not None:    self._max_val = float(mx)
        if scale is not None: self._scale   = str(scale)

    def should_select_on_ctrl_press(self) -> bool:
        """Don't select the node when clicking on the control."""
        return False


# ── Button ─────────────────────────────────────────────────────────────────────

class ButtonNode(NodeBase):
    """Monostable push button: fires Tick events on press and release."""

    NODE_NAME        = "Button"
    NODE_GROUP       = "Controls"
    NODE_TITLE_COLOR = "#3a1a5f"

    PINS = [
        PinDescriptor("on_pressed", PinDirection.OUTPUT, PinType.TICK),
        PinDescriptor("on_released", PinDirection.OUTPUT, PinType.TICK),
        PinDescriptor("pressed", PinDirection.OUTPUT, PinType.BOOL),
    ]

    MIN_WIDTH  = 180.0
    MIN_HEIGHT = 96.0   # ~36 px custom zone

    _DEFAULT_LABEL = "PRESS"
    _DEFAULT_COLOR = "#9c27b0"

    def __init__(self, **kw: Any) -> None:
        super().__init__(**kw)
        self._pressed:   bool = False
        self._label:     str  = self._DEFAULT_LABEL
        self._btn_color: str  = self._DEFAULT_COLOR

    # ── lifecycle ──────────────────────────────────────────────────────────────

    def on_start(self) -> None:
        self._pressed = False
        self.set_output("pressed", False)

    def execute(self, trigger_pin: str) -> None:
        pass

    def on_stop(self) -> None:
        self._pressed = False
        self.set_output("pressed", False)
        self.node_changed.emit()

    def on_output_wire_connected(self, pin_name: str) -> None:
        self.set_output("pressed", self._pressed)

    # ── ctrl interaction ───────────────────────────────────────────────────────

    def on_ctrl_press(self, scene_pos: QPointF, ctrl_rect: QRectF, modifiers: Qt.KeyboardModifiers = Qt.KeyboardModifier.NoModifier) -> bool:
        self._pressed = True
        self.fire_tick("on_pressed")
        self.set_output("pressed", True)
        self.node_changed.emit()
        return True

    def on_ctrl_release(self) -> None:
        self._pressed = False
        self.fire_tick("on_released")
        self.set_output("pressed", False)
        self.node_changed.emit()

    # ── label-editing protocol (duck-typed by the canvas on double-click) ──────

    def get_ctrl_label(self) -> str:
        return self._label

    def set_ctrl_label(self, text: str) -> None:
        self._label = text.strip() or self._DEFAULT_LABEL
        self.node_changed.emit()

    def ctrl_label_rect(self, ctrl_rect: QRectF) -> QRectF:
        """Scene rect of the button face — used to position the inline editor."""
        pad = 8.0
        return QRectF(
            ctrl_rect.x() + pad,      ctrl_rect.y() + 4,
            ctrl_rect.width() - pad * 2, ctrl_rect.height() - 8,
        )

    # ── color protocol (duck-typed by canvas context menu) ─────────────────────

    def get_ctrl_color(self) -> str:
        return self._btn_color

    def set_ctrl_color(self, hex_color: str) -> None:
        self._btn_color = hex_color
        self.node_changed.emit()

    # ── painting ───────────────────────────────────────────────────────────────

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        pad      = 8.0
        btn_rect = QRectF(
            rect.x() + pad, rect.y() + 4,
            rect.width() - pad * 2, rect.height() - 8,
        )

        accent = QColor(self._btn_color)
        h, s, v, _ = accent.getHsvF()

        if self._pressed:
            bg_col     = QColor.fromHsvF(h, min(s + 0.05, 1.0), max(0.01, v * 0.55))
            border_col = QColor.fromHsvF(h, max(0.0, s - 0.3),  min(1.0, v + 0.35))
            text_col   = QColor("#ffffff")
            offset     = 1.0
        else:
            bg_col     = QColor.fromHsvF(h, min(s + 0.05, 1.0), max(0.01, v * 0.22))
            border_col = accent
            text_col   = QColor.fromHsvF(h, max(0.0, s - 0.2),  min(1.0, v + 0.2))
            offset     = 0.0

        draw_rect = btn_rect.adjusted(0, offset, 0, offset)
        painter.setPen(QPen(border_col, 1.5))
        painter.setBrush(QBrush(bg_col))
        painter.drawRoundedRect(draw_rect, 6, 6)

        painter.setPen(text_col)
        painter.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        painter.drawText(draw_rect, Qt.AlignmentFlag.AlignCenter, self._label)

    # ── state persistence ──────────────────────────────────────────────────────

    def get_state(self) -> dict[str, Any]:
        s = super().get_state()
        s["__ctrl_label__"] = self._label
        s["__ctrl_color__"] = self._btn_color
        return s

    def set_state(self, state: dict[str, Any]) -> None:
        lbl   = state.pop("__ctrl_label__", None)
        color = state.pop("__ctrl_color__", None)
        super().set_state(state)
        if lbl is not None:   self._label     = str(lbl) or self._DEFAULT_LABEL
        if color is not None: self._btn_color = str(color)

    def should_select_on_ctrl_press(self) -> bool:
        """Don't select the node when clicking on the control."""
        return False


# ── Toggle ─────────────────────────────────────────────────────────────────────

class ToggleNode(NodeBase):
    """Bistable toggle: click to flip between False (OFF) and True (ON)."""

    NODE_NAME        = "Toggle"
    NODE_GROUP       = "Controls"
    NODE_TITLE_COLOR = "#0d3320"

    PINS = [
        PinDescriptor("output", PinDirection.OUTPUT, PinType.BOOL),
    ]

    MIN_WIDTH  = 180.0
    MIN_HEIGHT = 90.0   # ~30 px custom zone

    def __init__(self, **kw: Any) -> None:
        super().__init__(**kw)
        self._state: bool = False

    # ── lifecycle ──────────────────────────────────────────────────────────────

    def on_start(self) -> None:
        self.set_output("output", self._state)

    def execute(self, trigger_pin: str) -> None:
        pass

    def on_output_wire_connected(self, pin_name: str) -> None:
        self.set_output("output", self._state)

    # ── ctrl interaction ───────────────────────────────────────────────────────

    def on_ctrl_press(self, scene_pos: QPointF, ctrl_rect: QRectF, modifiers: Qt.KeyboardModifiers = Qt.KeyboardModifier.NoModifier) -> bool:
        self._state = not self._state
        self.set_output("output", self._state)
        self.node_changed.emit()
        return True

    # ── painting ───────────────────────────────────────────────────────────────

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        pill_w  = min(rect.width() - 24.0, 86.0)
        pill_h  = min(rect.height() - 6.0, 28.0)
        pill_x  = rect.x() + (rect.width() - pill_w) / 2.0
        pill_y  = rect.y() + (rect.height() - pill_h) / 2.0
        pill_r  = pill_h / 2.0
        pill_rect = QRectF(pill_x, pill_y, pill_w, pill_h)

        # Thumb zone width = pill_r * 2 (diameter); the opposite half is the label zone.
        label_zone_w = pill_w - pill_r * 2
        if self._state:
            bg_col     = QColor("#1b5e20")
            border_col = QColor("#66bb6a")
            thumb_col  = QColor("#c8e6c9")
            thumb_x    = pill_x + pill_w - pill_r - 3.0
            label      = "ON"
            # Label centered in the left (non-thumb) zone
            label_rect = QRectF(pill_x, pill_y, label_zone_w, pill_h)
        else:
            bg_col     = QColor("#12060e")
            border_col = QColor("#555555")
            thumb_col  = QColor("#9e9e9e")
            thumb_x    = pill_x + pill_r + 3.0
            label      = "OFF"
            # Label centered in the right (non-thumb) zone
            label_rect = QRectF(pill_x + pill_r * 2, pill_y, label_zone_w, pill_h)

        painter.setPen(QPen(border_col, 1.5))
        painter.setBrush(QBrush(bg_col))
        painter.drawRoundedRect(pill_rect, pill_r, pill_r)

        # Thumb
        cy = pill_y + pill_h / 2.0
        r  = pill_r - 3.0
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(thumb_col))
        painter.drawEllipse(QPointF(thumb_x, cy), r, r)

        # Label — always centred inside its zone
        painter.setPen(border_col)
        painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, label)

    # ── state persistence ──────────────────────────────────────────────────────

    def get_state(self) -> dict[str, Any]:
        s = super().get_state()
        s["__ctrl_state__"] = self._state
        return s

    def set_state(self, state: dict[str, Any]) -> None:
        v = state.pop("__ctrl_state__", None)
        super().set_state(state)
        if v is not None:
            self._state = bool(v)

    def should_select_on_ctrl_press(self) -> bool:
        """Don't select the node when clicking on the control."""
        return False


# ── Time Selector ──────────────────────────────────────────────────────────────

class TimeSelectorNode(NodeBase):
    """
    HH:MM:SS time picker.
    Click the ▲/▼ arrows above/below each field to change the value.
    Output is the total number of seconds (float).
    """

    NODE_NAME        = "Time Selector"
    NODE_GROUP       = "Controls"
    NODE_TITLE_COLOR = "#3a2800"

    PINS = [
        PinDescriptor("seconds", PinDirection.OUTPUT, PinType.FLOAT),
    ]

    MIN_WIDTH  = 210.0
    MIN_HEIGHT = 135.0   # ~75 px custom zone

    def __init__(self, **kw: Any) -> None:
        super().__init__(**kw)
        self._hours:   int = 0
        self._minutes: int = 0
        self._seconds: int = 0

    # ── helpers ────────────────────────────────────────────────────────────────

    def _total(self) -> float:
        return float(self._hours * 3600 + self._minutes * 60 + self._seconds)

    # ── lifecycle ──────────────────────────────────────────────────────────────

    def on_start(self) -> None:
        self.set_output("seconds", self._total())

    def execute(self, trigger_pin: str) -> None:
        pass

    def on_output_wire_connected(self, pin_name: str) -> None:
        self.set_output("seconds", self._total())

    # ── ctrl interaction ───────────────────────────────────────────────────────

    def on_ctrl_press(self, scene_pos: QPointF, ctrl_rect: QRectF, modifiers: Qt.KeyboardModifiers = Qt.KeyboardModifier.NoModifier) -> bool:
        col, up = self._hit_arrow(scene_pos, ctrl_rect)
        if col is None:
            return False

        # Calculate delta based on modifier keys
        if modifiers & Qt.KeyboardModifier.AltModifier:
            base_delta = 10
        elif modifiers & Qt.KeyboardModifier.ShiftModifier:
            base_delta = 5
        else:
            base_delta = 1

        delta = base_delta if up else -base_delta

        if col == 0:
            self._hours   = max(0, self._hours + delta)
        elif col == 1:
            self._minutes = max(0, min(59, self._minutes + delta))
        else:
            self._seconds = max(0, min(59, self._seconds + delta))
        self.set_output("seconds", self._total())
        self.node_changed.emit()
        return True

    def _col_rects(self, ctrl_rect: QRectF) -> list[QRectF]:
        """Return the 3 column rectangles within ctrl_rect."""
        w        = ctrl_rect.width()
        h        = ctrl_rect.height()
        sep      = 18.0                         # separator zone width (holds ":")
        col_w    = (w - sep * 2) / 3.0
        x0       = ctrl_rect.x()
        y0       = ctrl_rect.y()
        return [
            QRectF(x0,                       y0, col_w, h),
            QRectF(x0 + col_w + sep,         y0, col_w, h),
            QRectF(x0 + col_w * 2 + sep * 2, y0, col_w, h),
        ]

    def _hit_arrow(
        self, scene_pos: QPointF, ctrl_rect: QRectF
    ) -> tuple[Optional[int], Optional[bool]]:
        """Return (column_index 0-2, is_up) or (None, None)."""
        cols    = self._col_rects(ctrl_rect)
        h       = ctrl_rect.height()
        arrow_h = h / 3.5

        ly = scene_pos.y() - ctrl_rect.y()
        for i, col in enumerate(cols):
            if col.left() <= scene_pos.x() < col.right():
                if ly <= arrow_h:
                    return i, True
                elif ly >= h - arrow_h:
                    return i, False
                return None, None
        return None, None

    # ── painting ───────────────────────────────────────────────────────────────

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        h       = rect.height()
        arrow_h = h / 3.5
        val_h   = h - arrow_h * 2

        cols   = self._col_rects(rect)
        values = [self._hours, self._minutes, self._seconds]

        arrow_font = QFont("Segoe UI", 10)
        val_font   = QFont("Courier New", 13, QFont.Weight.Bold)

        for col_rect, val in zip(cols, values):
            cx = col_rect.x()
            cw = col_rect.width()

            # ▲ up arrow zone
            up_rect = QRectF(cx, rect.y(), cw, arrow_h)
            painter.setPen(QColor("#90a4ae"))
            painter.setFont(arrow_font)
            painter.drawText(up_rect, Qt.AlignmentFlag.AlignCenter, "▲")

            # Value display (dark pill)
            val_rect = QRectF(cx + 2, rect.y() + arrow_h, cw - 4, val_h)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor("#12060e")))
            painter.drawRoundedRect(val_rect, 4, 4)

            painter.setPen(QColor("#ffd0de"))
            painter.setFont(val_font)
            painter.drawText(val_rect, Qt.AlignmentFlag.AlignCenter, f"{val:02d}")

            # ▼ down arrow zone
            dn_rect = QRectF(cx, rect.y() + arrow_h + val_h, cw, arrow_h)
            painter.setPen(QColor("#90a4ae"))
            painter.setFont(arrow_font)
            painter.drawText(dn_rect, Qt.AlignmentFlag.AlignCenter, "▼")

        # ":" separators between columns
        sep_x_offsets = [
            cols[0].right(),
            cols[1].right(),
        ]
        sep_w   = cols[1].left() - cols[0].right()
        sep_h   = val_h
        sep_y   = rect.y() + arrow_h
        painter.setPen(QColor("#9e9e9e"))
        painter.setFont(QFont("Courier New", 12, QFont.Weight.Bold))
        for sx in sep_x_offsets:
            sep_rect = QRectF(sx, sep_y, sep_w, sep_h)
            painter.drawText(sep_rect, Qt.AlignmentFlag.AlignCenter, ":")

    # ── state persistence ──────────────────────────────────────────────────────

    def get_state(self) -> dict[str, Any]:
        s = super().get_state()
        s["__ctrl_hms__"] = [self._hours, self._minutes, self._seconds]
        return s

    def set_state(self, state: dict[str, Any]) -> None:
        hms = state.pop("__ctrl_hms__", None)
        super().set_state(state)
        if hms and len(hms) == 3:
            self._hours   = int(hms[0])
            self._minutes = int(hms[1])
            self._seconds = int(hms[2])

    def should_select_on_ctrl_press(self) -> bool:
        """Don't select the node when clicking on the control."""
        return False


# ── Touchpad ───────────────────────────────────────────────────────────────

class TouchpadNode(NodeBase):
    """
    Touchpad input: outputs x and y coordinates [0, 1] based on mouse position.

    Coordinate system: 0,0 at bottom-left, 1,1 at top-right.
    - x: 0 at left, 1 at right
    - y: 0 at bottom, 1 at top

    When LMB is pressed over the touchpad area, outputs update with normalized position.

    When mouse is released, mode determines behavior:
    - "reset": outputs reset to 0.0, 0.0
    - "hold": outputs hold last pressed position
    """

    NODE_NAME        = "Touchpad"
    NODE_GROUP       = "Controls"
    NODE_TITLE_COLOR = "#1a3a5f"

    PINS = [
        PinDescriptor("x", PinDirection.OUTPUT, PinType.FLOAT),
        PinDescriptor("y", PinDirection.OUTPUT, PinType.FLOAT),
    ]

    MIN_WIDTH  = 300.0   # Touchpad fills node width
    MIN_HEIGHT = 300.0   # Node is square to match width

    def __init__(self, **kw: Any) -> None:
        super().__init__(**kw)
        self._x_value:    float = 0.0   # normalized position [0, 1]
        self._y_value:    float = 0.0
        self._mode:       str   = "reset"  # "reset" | "hold"
        self._is_pressed: bool  = False

    # ── lifecycle ──────────────────────────────────────────────────────────────

    def on_start(self) -> None:
        self.set_output("x", self._x_value)
        self.set_output("y", self._y_value)

    def execute(self, trigger_pin: str) -> None:
        pass

    def on_stop(self) -> None:
        self._is_pressed = False

    def on_output_wire_connected(self, pin_name: str) -> None:
        self.set_output("x", self._x_value)
        self.set_output("y", self._y_value)

    # ── touchpad mode protocol (duck-typed by canvas context menu) ────────────

    def get_touchpad_mode(self) -> str:
        return self._mode

    def set_touchpad_mode(self, mode: str) -> None:
        if mode in ("reset", "hold"):
            self._mode = mode
            self.node_changed.emit()

    # ── ctrl interaction ───────────────────────────────────────────────────────

    def on_ctrl_press(self, scene_pos: QPointF, ctrl_rect: QRectF, modifiers: Qt.KeyboardModifiers = Qt.KeyboardModifier.NoModifier) -> bool:
        self._is_pressed = True
        self._update_from_scene(scene_pos, ctrl_rect)
        return True

    def on_ctrl_drag(self, scene_pos: QPointF, ctrl_rect: QRectF) -> None:
        if self._is_pressed:
            self._update_from_scene(scene_pos, ctrl_rect)

    def on_ctrl_release(self) -> None:
        self._is_pressed = False
        if self._mode == "reset":
            self._x_value = 0.0
            self._y_value = 0.0
            self.set_output("x", 0.0)
            self.set_output("y", 0.0)
        # else: "hold" mode keeps last value (no action needed)
        self.node_changed.emit()

    def should_select_on_ctrl_press(self) -> bool:
        """Don't select the node when clicking on the touchpad."""
        return False

    def _update_from_scene(self, scene_pos: QPointF, ctrl_rect: QRectF) -> None:
        """Update x, y based on mouse position within the touchpad area.

        Coordinate system: 0,0 at bottom-left, 1,1 at top-right.
        """
        pad = 12.0
        # Ensure square aspect ratio and center (same as paint_custom)
        side = min(ctrl_rect.width(), ctrl_rect.height()) - pad * 2

        if side <= 0:
            return

        # Calculate centered position
        offset_x = (ctrl_rect.width() - side) / 2
        offset_y = (ctrl_rect.height() - side) / 2

        # Clamp position to pad boundaries
        local_x = scene_pos.x() - ctrl_rect.x() - offset_x
        local_y = scene_pos.y() - ctrl_rect.y() - offset_y

        self._x_value = max(0.0, min(1.0, local_x / side))
        # Invert y: 0 at bottom, 1 at top
        self._y_value = max(0.0, min(1.0, 1.0 - (local_y / side)))

        self.set_output("x", self._x_value)
        self.set_output("y", self._y_value)
        self.node_changed.emit()

    # ── painting ───────────────────────────────────────────────────────────────

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

        # Border (on top: drawn last)
        border_col = QColor("#64b5f6") if self._is_pressed else QColor("#90a4ae")
        painter.setPen(QPen(border_col, 2.5))
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

        # Mode indicator (tiny, top-right)
        if self._mode == "hold":
            painter.setPen(QColor("#90a4ae"))
            painter.setFont(QFont("Segoe UI", 6))
            painter.drawText(
                QRectF(pad_rect.right() - 28, pad_rect.y() + 1, 26, 8),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                "HOLD"
            )

    # ── state persistence ──────────────────────────────────────────────────────

    def get_state(self) -> dict[str, Any]:
        s = super().get_state()
        s["__ctrl_x__"]    = self._x_value
        s["__ctrl_y__"]    = self._y_value
        s["__ctrl_mode__"] = self._mode
        return s

    def set_state(self, state: dict[str, Any]) -> None:
        x    = state.pop("__ctrl_x__",    None)
        y    = state.pop("__ctrl_y__",    None)
        mode = state.pop("__ctrl_mode__", None)
        super().set_state(state)
        if x is not None:    self._x_value = float(x)
        if y is not None:    self._y_value = float(y)
        if mode is not None: self._mode    = str(mode)
