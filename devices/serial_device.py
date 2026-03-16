"""
SerialDevice — reference implementation of a COM/Serial device.

This file shows the FULL pattern for adding a new device:
  1. Subclass DeviceBase → handles the transport.
  2. Subclass DeviceNodeBase for each command → auto-registered as graph nodes.

The nodes declared here will appear under the "SerialDevice" group in the
context menu, and each will show a live status dot (green/yellow/gray) that
reflects the connected device's current state.

Device documentation notes
---------------------------
Protocol: newline-terminated ASCII commands over a serial port.
  SET_INTENSITY <0-255>\\n   → set output intensity
  GET_SENSOR\\n               → device replies  SENSOR <float>\\n
  PING\\n                     → device replies  PONG\\n
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from core.device_base import DeviceBase, DeviceCommand
from core.device_node_base import DeviceNodeBase, register_device_instance
from core.types import (
    ConnectionDescriptor,
    DeviceStatus,
    PinDescriptor,
    PinDirection,
    PinType,
    PortKind,
)

log = logging.getLogger(__name__)

DEVICE_TYPE_KEY = "devices.serial_device.SerialDevice"


# ─────────────────────────────────────────────────────────────────────────────
# Transport
# ─────────────────────────────────────────────────────────────────────────────

class SerialDevice(DeviceBase):
    """
    Generic ASCII-protocol serial device.

    ConnectionDescriptor.extra:
        baud     (int)  default 115200
        timeout  (float) default 1.0
    """

    DEVICE_NAME      = "Serial Device"
    DEVICE_VERSION   = "1.0.0"
    CONNECTION_KINDS = [PortKind.SERIAL]
    ICON_PATH        = "assets/icons/serial.png"   # optional

    def __init__(self, descriptor: ConnectionDescriptor, **kwargs) -> None:
        super().__init__(descriptor, **kwargs)
        self._serial = None   # serial.Serial instance

    # ── DeviceBase interface ─────────────────────────────────────────────────

    def _open(self) -> None:
        import serial   # type: ignore  (pyserial)
        baud    = int(self.descriptor.extra.get("baud",    115200))
        timeout = float(self.descriptor.extra.get("timeout", 1.0))
        self._serial = serial.Serial(
            port     = self.descriptor.address,
            baudrate = baud,
            timeout  = timeout,
        )

    def _close(self) -> None:
        if self._serial and self._serial.is_open:
            self._serial.close()
        self._serial = None

    def _ping(self) -> bool:
        if not self._serial or not self._serial.is_open:
            raise ConnectionError("Port not open")
        self._serial.write(b"PING\n")
        response = self._serial.readline().decode("ascii", errors="ignore").strip()
        if response != "PONG":
            raise IOError(f"Unexpected ping response: {response!r}")
        return True

    def _execute_command(self, command: DeviceCommand) -> Any:
        if not self._serial or not self._serial.is_open:
            raise ConnectionError("Serial port not open")

        if command.name == "set_intensity":
            value = int(float(command.params.get("value", 0)) * 255)
            self._serial.write(f"SET_INTENSITY {value}\n".encode())
            return True

        if command.name == "get_sensor":
            self._serial.write(b"GET_SENSOR\n")
            line = self._serial.readline().decode("ascii", errors="ignore").strip()
            # expected: "SENSOR 0.345"
            parts = line.split()
            if len(parts) == 2 and parts[0] == "SENSOR":
                value = float(parts[1])
                self.data_received.emit({"pin": "sensor_value", "value": value})
                return value
            raise IOError(f"Bad sensor response: {line!r}")

        raise ValueError(f"[SerialDevice] Unknown command: {command.name!r}")

    # ── Node contribution ────────────────────────────────────────────────────

    def _on_connected(self) -> None:
        register_device_instance(DEVICE_TYPE_KEY, self)

    def get_node_types(self) -> list[str]:
        return [
            f"{DEVICE_TYPE_KEY}.SetIntensity",
            f"{DEVICE_TYPE_KEY}.GetSensor",
        ]
