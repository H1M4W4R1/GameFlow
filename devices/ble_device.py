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
        if not self._client.is_connected:
            raise ConnectionError("BLE disconnected")
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


# ─────────────────────────────────────────────────────────────────────────────
# TCP Device
# ─────────────────────────────────────────────────────────────────────────────

import socket
from core.types import PortKind

TCP_DEVICE_TYPE_KEY = "devices.ble_device.TCPDevice"


class TCPDevice(DeviceBase):
    """
    Generic TCP socket device.

    ConnectionDescriptor:
        kind    = PortKind.TCP
        address = "192.168.1.100:8080"
        extra:
            timeout  (float)  default 2.0
    """

    DEVICE_NAME      = "TCP Device"
    DEVICE_VERSION   = "1.0.0"
    CONNECTION_KINDS = [PortKind.TCP]
    ICON_PATH        = "assets/icons/tcp.png"

    def __init__(self, descriptor: ConnectionDescriptor, **kwargs) -> None:
        super().__init__(descriptor, **kwargs)
        self._sock: Optional[socket.socket] = None

    def _open(self) -> None:
        host, _, port_str = self.descriptor.address.rpartition(":")
        port    = int(port_str)
        timeout = float(self.descriptor.extra.get("timeout", 2.0))
        self._sock = socket.create_connection((host, port), timeout=timeout)

    def _close(self) -> None:
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

    def _ping(self) -> bool:
        if not self._sock:
            raise ConnectionError("Not connected")
        self._sock.sendall(b"PING\n")
        resp = self._sock.recv(16)
        if b"PONG" not in resp:
            raise IOError(f"Bad ping: {resp!r}")
        return True

    def _execute_command(self, command: DeviceCommand) -> Any:
        if not self._sock:
            raise ConnectionError("Socket not open")

        if command.name == "send":
            payload: bytes = command.params.get("data", b"")
            self._sock.sendall(payload)
            return True

        if command.name == "send_recv":
            payload = command.params.get("data", b"")
            self._sock.sendall(payload)
            return self._sock.recv(1024)

        raise ValueError(f"[TCPDevice] Unknown command: {command.name!r}")

    def _on_connected(self) -> None:
        register_device_instance(TCP_DEVICE_TYPE_KEY, self)


# ─────────────────────────────────────────────────────────────────────────────
# WebSocket Device
# ─────────────────────────────────────────────────────────────────────────────

WS_DEVICE_TYPE_KEY = "devices.ble_device.WebSocketDevice"


class WebSocketDevice(DeviceBase):
    """
    WebSocket device via websockets library.

    ConnectionDescriptor:
        kind    = PortKind.WEBSOCKET
        address = "ws://192.168.1.1:8765/ws"
    """

    DEVICE_NAME      = "WebSocket Device"
    DEVICE_VERSION   = "1.0.0"
    CONNECTION_KINDS = [PortKind.WEBSOCKET]
    ICON_PATH        = "assets/icons/websocket.png"

    def __init__(self, descriptor: ConnectionDescriptor, **kwargs) -> None:
        super().__init__(descriptor, **kwargs)
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._ws:   Any = None

    def _open(self) -> None:
        self._loop = asyncio.new_event_loop()
        t = threading.Thread(target=self._loop.run_forever, daemon=True)
        t.start()
        future = asyncio.run_coroutine_threadsafe(self._async_connect(), self._loop)
        future.result(timeout=10)

    async def _async_connect(self) -> None:
        import websockets  # type: ignore
        self._ws = await websockets.connect(self.descriptor.address)
        asyncio.ensure_future(self._recv_loop(), loop=self._loop)

    async def _recv_loop(self) -> None:
        try:
            async for message in self._ws:
                self.data_received.emit({"message": message})
        except Exception:
            pass

    def _close(self) -> None:
        if self._ws and self._loop:
            future = asyncio.run_coroutine_threadsafe(self._ws.close(), self._loop)
            try:
                future.result(timeout=3)
            except Exception:
                pass

    def _ping(self) -> bool:
        if not self._ws or self._ws.closed:
            raise ConnectionError("WebSocket closed")
        return True

    def _execute_command(self, command: DeviceCommand) -> Any:
        if not self._ws or not self._loop:
            raise ConnectionError("WebSocket not ready")

        if command.name == "send":
            msg = command.params.get("message", "")
            future = asyncio.run_coroutine_threadsafe(
                self._ws.send(msg), self._loop
            )
            return future.result(timeout=5)

        raise ValueError(f"[WebSocketDevice] Unknown command: {command.name!r}")

    def _on_connected(self) -> None:
        register_device_instance(WS_DEVICE_TYPE_KEY, self)


# ─────────────────────────────────────────────────────────────────────────────
# REST Polling Device
# ─────────────────────────────────────────────────────────────────────────────

import time as _time

REST_DEVICE_TYPE_KEY = "devices.ble_device.RESTDevice"


class RESTDevice(DeviceBase):
    """
    REST API polling device.

    ConnectionDescriptor:
        kind    = PortKind.REST
        address = "http://192.168.1.1:8080"   # base URL
        extra:
            poll_path   (str)   endpoint to poll, default "/status"
            poll_sec    (float) polling interval, default 1.0
            headers     (dict)  additional headers, e.g. {"Authorization": "Bearer …"}
    """

    DEVICE_NAME      = "REST API Device"
    DEVICE_VERSION   = "1.0.0"
    CONNECTION_KINDS = [PortKind.REST]
    ICON_PATH        = "assets/icons/rest.png"

    def __init__(self, descriptor: ConnectionDescriptor, **kwargs) -> None:
        super().__init__(descriptor, **kwargs)
        self._session:    Any   = None
        self._last_poll:  float = 0.0

    def _open(self) -> None:
        import requests  # type: ignore
        self._session = requests.Session()
        extra_headers = self.descriptor.extra.get("headers", {})
        self._session.headers.update(extra_headers)
        # Verify we can reach the server
        self._ping()

    def _close(self) -> None:
        if self._session:
            self._session.close()
            self._session = None

    def _ping(self) -> bool:
        if not self._session:
            raise ConnectionError("Session not open")
        path = self.descriptor.extra.get("poll_path", "/status")
        url  = self.descriptor.address.rstrip("/") + path
        resp = self._session.get(url, timeout=3)
        resp.raise_for_status()
        poll_sec = float(self.descriptor.extra.get("poll_sec", 1.0))
        now = _time.monotonic()
        if now - self._last_poll >= poll_sec:
            self._last_poll = now
            try:
                payload = resp.json()
            except Exception:
                payload = {"raw": resp.text}
            self.data_received.emit(payload)
        return True

    def _execute_command(self, command: DeviceCommand) -> Any:
        if not self._session:
            raise ConnectionError("Not connected")

        if command.name == "get":
            path = command.params.get("path", "/")
            url  = self.descriptor.address.rstrip("/") + path
            resp = self._session.get(url, timeout=5)
            resp.raise_for_status()
            return resp.json()

        if command.name == "post":
            path = command.params.get("path", "/")
            body = command.params.get("body", {})
            url  = self.descriptor.address.rstrip("/") + path
            resp = self._session.post(url, json=body, timeout=5)
            resp.raise_for_status()
            return resp.json()

        raise ValueError(f"[RESTDevice] Unknown command: {command.name!r}")

    def _on_connected(self) -> None:
        register_device_instance(REST_DEVICE_TYPE_KEY, self)
