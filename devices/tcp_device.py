import socket
from typing import Any, Optional

from core.device_base import DeviceCommand, DeviceBase
from core.device_node_base import register_device_instance
from core.types import ConnectionDescriptor, PortKind

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