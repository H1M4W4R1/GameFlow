# ─────────────────────────────────────────────────────────────────────────────
# WebSocket Device
# ─────────────────────────────────────────────────────────────────────────────
import asyncio
import threading
from typing import Optional, Any

from core.device_base import DeviceCommand, DeviceBase
from core.device_node_base import register_device_instance
from core.types import ConnectionDescriptor, PortKind

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