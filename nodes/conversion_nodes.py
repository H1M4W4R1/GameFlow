"""
Conversion nodes — unit and type conversion utilities.

Group: Conversion
"""
from __future__ import annotations

from typing import Any

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui  import QPainter, QColor, QFont

from core.node_base import NodeBase
from core.types     import PinDescriptor, PinDirection, PinType


_VAL_COLOR = "#80cbc4"
_NUMERIC_EDGE_CHARS = frozenset("+-0123456789.eE")


def _trim_numeric_edges(value: Any) -> Any:
    """Trim non-numeric wrapper text before numeric conversion."""
    if not isinstance(value, str):
        return value

    start = 0
    end = len(value)

    while start < end and value[start] not in _NUMERIC_EDGE_CHARS:
        start += 1
    while end > start and value[end - 1] not in _NUMERIC_EDGE_CHARS:
        end -= 1

    return value[start:end]


# ─────────────────────────────────────────────────────────────────────────────
# Time ↔ Frequency
# ─────────────────────────────────────────────────────────────────────────────

class TimeFrequencyNode(NodeBase):
    """
    Bidirectional period ↔ frequency converter.

    Wire either input; both outputs are always computed:
        out_hz       = 1 / period_s
        out_period_s = 1 / frequency_hz

    If both inputs are connected, frequency_hz takes priority.
    If neither is connected, the variable-input defaults are used
    (priority: frequency_hz variable input).
    """
    NODE_NAME  = "Time ↔ Frequency"
    NODE_GROUP = "Conversion"
    PINS = [
        PinDescriptor("period_s",     PinDirection.INPUT,  PinType.FLOAT, optional=True),
        PinDescriptor("frequency_hz", PinDirection.INPUT,  PinType.FLOAT, optional=True),
        PinDescriptor("out_hz",       PinDirection.OUTPUT, PinType.FLOAT),
        PinDescriptor("out_period_s", PinDirection.OUTPUT, PinType.FLOAT),
    ]
    VARIABLE_INPUTS = {
        "period_s":     (float, 1.0),
        "frequency_hz": (float, 1.0),
    }
    MIN_WIDTH  = 190.0
    MIN_HEIGHT = 80.0

    def on_start(self) -> None:
        self._compute()

    def on_data_received(self, pin_name: str, value: Any) -> None:
        self._compute()

    def on_var_input_changed(self, pin_name: str, value: Any) -> None:
        self._compute()

    def _compute(self) -> None:
        f_in = self.get_input("frequency_hz")
        p_in = self.get_input("period_s")

        if f_in is not None:
            self._from_hz(float(f_in))
        elif p_in is not None:
            self._from_period(float(p_in))
        else:
            # Neither wired — use variable inputs; frequency_hz takes priority
            fv = self.get_var_input("frequency_hz")
            pv = self.get_var_input("period_s")
            if fv is not None:
                self._from_hz(float(fv))
            elif pv is not None:
                self._from_period(float(pv))

    def _from_hz(self, f: float) -> None:
        f = max(1e-9, f)
        self.set_output("out_hz",       f)
        self.set_output("out_period_s", 1.0 / f)

    def _from_period(self, p: float) -> None:
        p = max(1e-9, p)
        self.set_output("out_period_s", p)
        self.set_output("out_hz",       1.0 / p)

    def execute(self, trigger_pin: str) -> None:
        pass

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        hz = self._data.get("out_hz")
        ps = self._data.get("out_period_s")
        painter.setPen(QColor(_VAL_COLOR))
        painter.setFont(QFont("Courier New", 8))
        lines = []
        if hz is not None:
            lines.append(f"{hz:.4f} Hz")
        if ps is not None:
            lines.append(f"{ps:.4f} s")
        text = "\n".join(lines) if lines else "1 / x"
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

# ─────────────────────────────────────────────────────────────────────────────
# Type Conversion nodes
# ─────────────────────────────────────────────────────────────────────────────

class IntToFloatNode(NodeBase):
    """Converts any value to FLOAT."""
    NODE_NAME  = "Any → Float"
    NODE_GROUP = "Conversion"
    PINS = [
        PinDescriptor("input",  PinDirection.INPUT,  PinType.ANY,   default=0),
        PinDescriptor("output", PinDirection.OUTPUT, PinType.FLOAT),
    ]
    MIN_WIDTH  = 150.0
    MIN_HEIGHT = 60.0

    def on_start(self) -> None:
        self._convert()

    def on_data_received(self, pin_name: str, value: Any) -> None:
        self._convert()

    def execute(self, trigger_pin: str) -> None:
        self._convert()

    def _convert(self) -> None:
        v = _trim_numeric_edges(self.get_input("input"))
        try:
            self.set_output("output", float(v) if v is not None else 0.0)
        except (TypeError, ValueError):
            self.set_output("output", 0.0)

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        painter.setPen(QColor("#90a4ae"))
        painter.setFont(QFont("Courier New", 9))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "any → float")


class FloatToIntNode(NodeBase):
    """Converts any value to INT (rounds to nearest integer)."""
    NODE_NAME  = "Any → Int"
    NODE_GROUP = "Conversion"
    PINS = [
        PinDescriptor("input",  PinDirection.INPUT,  PinType.ANY, default=0),
        PinDescriptor("output", PinDirection.OUTPUT, PinType.INT),
    ]
    MIN_WIDTH  = 150.0
    MIN_HEIGHT = 60.0

    def on_start(self) -> None:
        self._convert()

    def on_data_received(self, pin_name: str, value: Any) -> None:
        self._convert()

    def execute(self, trigger_pin: str) -> None:
        self._convert()

    def _convert(self) -> None:
        v = _trim_numeric_edges(self.get_input("input"))
        try:
            self.set_output("output", int(round(float(v))) if v is not None else 0)
        except (TypeError, ValueError):
            self.set_output("output", 0)

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        painter.setPen(QColor("#90a4ae"))
        painter.setFont(QFont("Courier New", 9))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "any → int")


class BoolToFloatNode(NodeBase):
    """Converts any value to BOOL (truthy/falsy). For float input, value is floored to int first."""
    NODE_NAME  = "Any → Bool"
    NODE_GROUP = "Conversion"
    PINS = [
        PinDescriptor("input",  PinDirection.INPUT,  PinType.ANY,  default=False),
        PinDescriptor("output", PinDirection.OUTPUT, PinType.BOOL),
    ]
    MIN_WIDTH  = 155.0
    MIN_HEIGHT = 60.0

    def on_start(self) -> None:
        self._convert()

    def on_data_received(self, pin_name: str, value: Any) -> None:
        self._convert()

    def execute(self, trigger_pin: str) -> None:
        self._convert()

    def _convert(self) -> None:
        v = self.get_input("input")
        if isinstance(v, float):
            # Floor float to int, then convert to bool
            self.set_output("output", bool(int(v)))
        else:
            # For bool and other types, convert directly to bool
            self.set_output("output", bool(v))

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        painter.setPen(QColor("#90a4ae"))
        painter.setFont(QFont("Courier New", 9))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "any → bool")


class AnyToStringNode(NodeBase):
    """Converts any value to its string representation."""
    NODE_NAME  = "Any → String"
    NODE_GROUP = "Conversion"
    PINS = [
        PinDescriptor("input",  PinDirection.INPUT,  PinType.ANY,    default=0),
        PinDescriptor("output", PinDirection.OUTPUT, PinType.STRING),
    ]
    MIN_WIDTH  = 155.0
    MIN_HEIGHT = 60.0

    def on_start(self) -> None:
        self._convert()

    def on_data_received(self, pin_name: str, value: Any) -> None:
        self._convert()

    def execute(self, trigger_pin: str) -> None:
        self._convert()

    def _convert(self) -> None:
        v = self.get_input("input")
        self.set_output("output", str(v) if v is not None else "")

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        painter.setPen(QColor("#90a4ae"))
        painter.setFont(QFont("Courier New", 9))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "any → str")


class StringToFloatNode(NodeBase):
    """Parses any value as a string then to float (outputs 0.0 if parse fails)."""
    NODE_NAME  = "Any → String → Float"
    NODE_GROUP = "Conversion"
    PINS = [
        PinDescriptor("input",  PinDirection.INPUT,  PinType.ANY, default=0),
        PinDescriptor("output", PinDirection.OUTPUT, PinType.FLOAT),
        PinDescriptor("valid",  PinDirection.OUTPUT, PinType.BOOL),
    ]
    MIN_WIDTH  = 160.0
    MIN_HEIGHT = 60.0

    def on_start(self) -> None:
        self._convert()

    def on_data_received(self, pin_name: str, value: Any) -> None:
        self._convert()

    def execute(self, trigger_pin: str) -> None:
        self._convert()

    def _convert(self) -> None:
        s = str(self.get_input("input") or "")
        try:
            self.set_output("output", float(s))
            self.set_output("valid",  True)
        except ValueError:
            self.set_output("output", 0.0)
            self.set_output("valid",  False)

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        painter.setPen(QColor("#90a4ae"))
        painter.setFont(QFont("Courier New", 9))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "any → str → float")
