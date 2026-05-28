"""MausTec Edge-o-Matic 3000 WebSocket integration."""
from __future__ import annotations

import asyncio
import json
import logging
import threading
from typing import Any, Optional

from core.device_base import DeviceBase, DeviceCommand
from core.device_node_base import register_device_instance
from core.types import ConnectionDescriptor, PortKind

log = logging.getLogger(__name__)

DEVICE_TYPE_KEY = "devices.maustec.edge_o_matic.EdgeOMatic3000"


def _clamp_byte(value: Any) -> int:
    return max(0, min(255, int(round(float(value)))))


def _parse_inline_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return ""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return value


def _next_nonce() -> int:
    _next_nonce.value = (_next_nonce.value % 999999) + 1
    return _next_nonce.value


_next_nonce.value = 0


class EdgeOMatic3000(DeviceBase):
    """
    MausTec Edge-o-Matic 3000 over WebSocket.

    ConnectionDescriptor:
        kind    = PortKind.WEBSOCKET
        address = "ws://<device-ip>:<websocket_port>"
    """

    DEVICE_NAME = "Edge-o-Matic 3000"
    DEVICE_TR_PREFIX = "maustec.edge_o_matic"
    DEVICE_VERSION = "1.0.0"
    MANUFACTURER = "MausTec"
    DEVICE_DESCRIPTION = "Automated edging controller with WebSocket JSON API"
    CONNECTION_KINDS = [PortKind.WEBSOCKET]
    ICON_PATH = "assets/icons/maustec/edgeomatic.svg"
    DEVICE_URL = "https://maustec.io/"

    def __init__(self, descriptor: ConnectionDescriptor, **kwargs) -> None:
        super().__init__(descriptor, **kwargs)
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._ws: Any = None
        self._loop_thread: Optional[threading.Thread] = None
        self._response_waiters: dict[str, list[asyncio.Future]] = {}
        self._last_payload: dict[str, Any] = {}
        self._last_readings: dict[str, Any] = {}

    def _open(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._loop_thread = threading.Thread(
            target=self._loop.run_forever,
            daemon=True,
            name=f"{self.DEVICE_NAME}-loop",
        )
        self._loop_thread.start()
        future = asyncio.run_coroutine_threadsafe(self._async_connect(), self._loop)
        future.result(timeout=10)

    async def _async_connect(self) -> None:
        import websockets  # type: ignore

        self._ws = await websockets.connect(self.descriptor.address)
        asyncio.ensure_future(self._recv_loop(), loop=self._loop)

    async def _recv_loop(self) -> None:
        try:
            async for message in self._ws:
                self._handle_message(message)
        except Exception as exc:
            log.debug("[%s] Receive loop stopped: %s", self.DEVICE_NAME, exc)

    def _handle_message(self, message: Any) -> None:
        try:
            data = json.loads(message) if isinstance(message, str) else message
        except (TypeError, json.JSONDecodeError):
            self.data_received.emit({"type": "raw", "raw": str(message)})
            return

        if not isinstance(data, dict):
            self.data_received.emit({"type": "raw", "raw": data})
            return

        self._last_payload = data
        for key, value in data.items():
            if key == "readings" and isinstance(value, dict):
                self._last_readings = value
            self.data_received.emit({"type": key, "payload": value})
            self._resolve_waiters(key, value)

    def _resolve_waiters(self, key: str, value: Any) -> None:
        waiters = self._response_waiters.get(key, [])
        if not waiters:
            return
        remaining: list[asyncio.Future] = []
        for future in waiters:
            if future.done():
                continue
            wanted_nonce = getattr(future, "_edge_nonce", None)
            if wanted_nonce is not None:
                if not isinstance(value, dict) or value.get("nonce") != wanted_nonce:
                    remaining.append(future)
                    continue
            future.set_result(value)
        self._response_waiters[key] = remaining

    def _close(self) -> None:
        if self._ws and self._loop:
            future = asyncio.run_coroutine_threadsafe(self._ws.close(), self._loop)
            try:
                future.result(timeout=3)
            except Exception:
                pass
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)
        self._ws = None
        self._loop = None

    def _ping(self) -> bool:
        if not self._ws or not self._loop:
            raise ConnectionError("WebSocket not ready")
        if getattr(self._ws, "closed", False):
            raise ConnectionError("WebSocket closed")
        future = asyncio.run_coroutine_threadsafe(self._ws.ping(), self._loop)
        future.result(timeout=3)
        return True

    def _execute_command(self, command: DeviceCommand) -> Any:
        if not self._loop:
            raise ConnectionError("WebSocket not ready")
        future = asyncio.run_coroutine_threadsafe(
            self._dispatch_command(command), self._loop
        )
        return future.result(timeout=8)

    async def _dispatch_command(self, command: DeviceCommand) -> Any:
        name = command.name
        params = command.params

        if name == "set_motor":
            speed = _clamp_byte(params.get("speed", 0))
            await self._send_packet({"setMotor": speed})
            return speed

        if name == "set_mode":
            mode = str(params.get("mode", "manual")).lower()
            if mode not in ("automatic", "manual"):
                raise ValueError("mode must be 'automatic' or 'manual'")
            await self._send_packet({"setMode": mode})
            return mode

        if name == "config_set":
            values = params.get("values")
            if not isinstance(values, dict):
                key = str(params.get("key", "")).strip()
                if not key:
                    raise ValueError("config key is required")
                values = {key: params.get("value")}
            await self._send_packet({"configSet": values})
            return values

        if name == "config_list":
            nonce = int(params.get("nonce") or _next_nonce())
            return await self._request({"configList": {"nonce": nonce}}, "configList", nonce)

        if name == "serial_cmd":
            cmd = str(params.get("cmd", ""))
            nonce = int(params.get("nonce") or _next_nonce())
            return await self._request(
                {"serialCmd": {"cmd": cmd, "nonce": nonce}},
                "serialCmd",
                nonce,
            )

        if name == "get_wifi_status":
            return await self._request({"getWiFiStatus": {}}, "wifiStatus")

        if name == "get_sd_status":
            return await self._request({"getSDStatus": {}}, "sdStatus")

        if name == "raw":
            payload = params.get("payload", {})
            if isinstance(payload, str):
                payload = json.loads(payload)
            if not isinstance(payload, dict):
                raise ValueError("raw WebSocket payload must be a JSON object")
            await self._send_packet(payload)
            return payload

        if name == "stop":
            await self._send_packet({"setMotor": 0, "setMode": "manual"})
            return True

        if name == "get_readings":
            return dict(self._last_readings)

        raise ValueError(f"[{self.DEVICE_NAME}] Unknown command: {name!r}")

    async def _send_packet(self, payload: dict[str, Any]) -> None:
        if not self._ws:
            raise ConnectionError("WebSocket not connected")
        await self._ws.send(json.dumps(payload, separators=(",", ":")))

    async def _request(
        self,
        payload: dict[str, Any],
        response_key: str,
        nonce: Optional[int] = None,
        timeout: float = 5.0,
    ) -> Any:
        if not self._loop:
            raise ConnectionError("WebSocket not ready")
        future = self._loop.create_future()
        if nonce is not None:
            setattr(future, "_edge_nonce", nonce)
        self._response_waiters.setdefault(response_key, []).append(future)
        await self._send_packet(payload)
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        finally:
            waiters = self._response_waiters.get(response_key, [])
            self._response_waiters[response_key] = [w for w in waiters if w is not future]

    def _on_connected(self) -> None:
        register_device_instance(DEVICE_TYPE_KEY, self)

    def get_node_types(self) -> list[str]:
        return [
            "devices.maustec.edgeomatic_nodes.EdgeOMaticSetMotorNode",
            "devices.maustec.edgeomatic_nodes.EdgeOMaticSetMotorRawNode",
            "devices.maustec.edgeomatic_nodes.EdgeOMaticAutomaticModeNode",
            "devices.maustec.edgeomatic_nodes.EdgeOMaticManualModeNode",
            "devices.maustec.edgeomatic_nodes.EdgeOMaticStopNode",
            "devices.maustec.edgeomatic_nodes.EdgeOMaticConfigSetNode",
            "devices.maustec.edgeomatic_nodes.EdgeOMaticConfigureNode",
            "devices.maustec.edgeomatic_nodes.EdgeOMaticConfigListNode",
            "devices.maustec.edgeomatic_nodes.EdgeOMaticSerialCommandNode",
            "devices.maustec.edgeomatic_nodes.EdgeOMaticGetWiFiStatusNode",
            "devices.maustec.edgeomatic_nodes.EdgeOMaticGetSDStatusNode",
            "devices.maustec.edgeomatic_nodes.EdgeOMaticReadingsNode",
            "devices.maustec.edgeomatic_nodes.EdgeOMaticEventNode",
            "devices.maustec.edgeomatic_nodes.EdgeOMaticRawPayloadNode",
        ]


ALL_DEVICE_CLASSES = [EdgeOMatic3000]
