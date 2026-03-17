"""
BLE Device — reference implementation using bleak (async BLE).

Because bleak is async, we run an asyncio event loop in the worker thread.

Device documentation notes
---------------------------
Override NOTIFY_UUID / WRITE_UUID with your device's characteristic UUIDs.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any, Optional

from core.device_base import DeviceBase, DeviceCommand
from core.device_node_base import DeviceNodeBase, register_device_instance
from core.types import ConnectionDescriptor, PortKind, PinDescriptor, PinDirection, PinType

log = logging.getLogger(__name__)

DEVICE_TYPE_KEY = "devices.ble_device.BLEDevice"


class BLEDevice(DeviceBase):
    """
    Generic BLE device via bleak.

    ConnectionDescriptor:
        kind    = PortKind.BLE
        address = "AA:BB:CC:DD:EE:FF"
        extra:
            write_uuid   (str)  GATT characteristic for write-without-response
            notify_uuid  (str)  GATT characteristic to subscribe for notifications
    """

    DEVICE_NAME      = "BLE Device"
    DEVICE_VERSION   = "1.0.0"
    CONNECTION_KINDS = [PortKind.BLE]
    ICON_PATH        = "assets/icons/ble.png"

    # Override these with your device's actual UUIDs
    WRITE_UUID  = "0000fff1-0000-1000-8000-00805f9b34fb"
    NOTIFY_UUID = "0000fff2-0000-1000-8000-00805f9b34fb"

    def __init__(self, descriptor: ConnectionDescriptor, **kwargs) -> None:
        super().__init__(descriptor, **kwargs)
        self._loop:   Optional[asyncio.AbstractEventLoop] = None
        self._client: Any = None   # bleak.BleakClient

    def _open(self) -> None:
        self._loop = asyncio.new_event_loop()
        t = threading.Thread(target=self._loop.run_forever, daemon=True)
        t.start()
        future = asyncio.run_coroutine_threadsafe(self._async_connect(), self._loop)
        future.result(timeout=15)

    async def _async_connect(self) -> None:
        from bleak import BleakClient  # type: ignore
        self._client = BleakClient(self.descriptor.address)
        await self._client.connect()
        notify_uuid = self.descriptor.extra.get("notify_uuid", self.NOTIFY_UUID)
        if notify_uuid:
            await self._client.start_notify(notify_uuid, self._on_notification)

    def _close(self) -> None:
        if self._client and self._loop:
            future = asyncio.run_coroutine_threadsafe(
                self._client.disconnect(), self._loop
            )
            try:
                future.result(timeout=5)
            except Exception:
                pass

    def _ping(self) -> bool:
        if not self._client:
            raise ConnectionError("Not connected")
        # Check bleak internal connected state
        # if not self._client.is_connected: C/O because bleak sucks
        #    raise ConnectionError("BLE disconnected")
        return True

    def _execute_command(self, command: DeviceCommand) -> Any:
        if not self._client or not self._loop:
            raise ConnectionError("BLE not ready")

        if command.name == "write":
            data: bytes = command.params.get("data", b"")
            uuid: str   = command.params.get("uuid", self.descriptor.extra.get("write_uuid", self.WRITE_UUID))
            future = asyncio.run_coroutine_threadsafe(
                self._client.write_gatt_char(uuid, data, response=False),
                self._loop,
            )
            return future.result(timeout=5)

        raise ValueError(f"[BLEDevice] Unknown command: {command.name!r}")

    def _on_notification(self, sender: Any, data: bytes) -> None:
        self.data_received.emit({"sender": str(sender), "data": data.hex()})

    def _on_connected(self) -> None:
        register_device_instance(DEVICE_TYPE_KEY, self)