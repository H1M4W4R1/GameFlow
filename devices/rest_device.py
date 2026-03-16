# ─────────────────────────────────────────────────────────────────────────────
# REST Polling Device
# ─────────────────────────────────────────────────────────────────────────────

import time as _time
from typing import Any

from core.device_base import DeviceCommand, DeviceBase
from core.device_node_base import register_device_instance
from core.types import ConnectionDescriptor, PortKind

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