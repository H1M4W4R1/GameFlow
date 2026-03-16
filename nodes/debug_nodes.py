"""
Debug nodes — display and inspection nodes for debugging graph data.

All display nodes update instantly when upstream data arrives
(on_data_received), so no exec-tick is required.

Nodes
-----
LogNode           — logs a labelled value; shows last message in body
NumericDisplayNode — shows live numeric value in large text
TextDisplayNode    — shows live string/any value as wrapped text
TimeDisplayNode    — converts seconds or milliseconds to HH:MM:SS
StateIndicatorNode — coloured circle + TRUE/FALSE for a boolean input
"""
from __future__ import annotations

import logging
from typing import Any

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui  import QPainter, QColor, QFont

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
    Displays a coloured indicator circle and TRUE/FALSE label for a boolean input.
    Green = True, Red = False.
    Updates instantly on every data push — no tick required.
    """
    NODE_NAME  = "State Indicator"
    NODE_GROUP = "Debug"
    PINS = [
        PinDescriptor("state", PinDirection.INPUT, PinType.BOOL, default=False),
    ]
    MIN_WIDTH  = 160.0
    MIN_HEIGHT = 110.0

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._state: bool = False

    def on_data_received(self, pin_name: str, value: Any) -> None:
        if pin_name == "state":
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
