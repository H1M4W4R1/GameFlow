"""
Lovense shared utility nodes available for any connected Lovense device.
"""
from __future__ import annotations

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui  import QPainter, QColor, QFont

from core.device_node_base import DeviceNodeBase
from core.node_base import NodeBase
from core.types import PinDescriptor, PinDirection, PinType


def make_battery_node(device_cls) -> type:
    """Create a GetBattery node for any Lovense device class."""
    device_type_key = f"{device_cls.__module__}.{device_cls.__name__}"

    class _BatteryNode(DeviceNodeBase):
        NODE_NAME       = f"{device_cls.DEVICE_NAME}: Get Battery"
        NODE_GROUP      = f"Devices/Lovense/{device_cls.DEVICE_NAME}"
        DEVICE_TYPE_KEY = device_type_key
        ICON_PATH       = device_cls.ICON_PATH
        PINS = [
            PinDescriptor("exec_in",  PinDirection.INPUT,  PinType.TICK),
            PinDescriptor("level",    PinDirection.OUTPUT, PinType.INT),
            PinDescriptor("exec_out", PinDirection.OUTPUT, PinType.TICK),
        ]

        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            self._last_level: int = -1

        def on_start(self) -> None:
            dev = self.get_device()
            if dev:
                # Subscribe to battery updates
                dev.battery_changed.connect(self._on_battery)

        def _on_battery(self, level: int) -> None:
            self._last_level = level
            self.set_output("level", level)
            self.node_changed.emit()

        def execute(self, trigger_pin: str) -> None:
            dev = self.get_device()
            if dev:
                dev.request_battery()
            self.set_output("level", self._last_level)
            self.fire_tick("exec_out")

        def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
            lvl = self._last_level
            if lvl < 0:
                text  = "— %"
                color = QColor("#6b3050")
            elif lvl <= 20:
                text  = f"{lvl}%"
                color = QColor("#ef5350")
            elif lvl <= 50:
                text  = f"{lvl}%"
                color = QColor("#ffb74d")
            else:
                text  = f"{lvl}%"
                color = QColor("#4caf50")
            painter.setPen(color)
            painter.setFont(QFont("Courier New", 18, QFont.Weight.Bold))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

    _BatteryNode.__name__     = f"Battery_{device_cls.__name__}"
    _BatteryNode.__qualname__ = _BatteryNode.__name__
    return _BatteryNode
