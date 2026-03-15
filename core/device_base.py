"""
DeviceBase — abstract base class for all hardware/remote device drivers.

HOW TO IMPLEMENT A NEW DEVICE
==============================
1.  Subclass DeviceBase in  /devices/your_device.py
2.  Set class attributes:
        DEVICE_NAME      = "Human-readable name"
        DEVICE_VERSION   = "1.0.0"
        CONNECTION_KINDS = [PortKind.SERIAL]   # what transports you support
        ICON_PATH        = "assets/icons/my_device.png"   # optional
3.  Implement the abstract methods (see docstrings below).
4.  The base class handles:
        • status transitions (CONNECTED → UNKNOWN → DISCONNECTED)
        • automatic retry with back-off (3 retries before DISCONNECTED)
        • background reconnect loop
        • thread-safe command queue
        • Qt signals for UI updates
5.  Drop the file into /devices/ – it will be auto-discovered at startup.

COMMAND FLOW
============
    UI / Node          DeviceBase              Your subclass
    ─────────────────────────────────────────────────────────
    send_command(cmd)  ──► _cmd_queue          _execute_command(cmd)
                           (worker thread)  ──►  calls your impl
                           on failure       ──►  _on_command_failed()
                                                 retries / marks UNKNOWN
                                                 after 3 × → DISCONNECTED
"""
from __future__ import annotations

import abc
import asyncio
import logging
import threading
import time
from dataclasses import dataclass, field
from queue import Queue, Empty
from typing import Any, Callable, Optional

from PyQt6.QtCore import QObject, pyqtSignal

from core.types import (
    ConnectionDescriptor,
    DeviceStatus,
    PortKind,
)

log = logging.getLogger(__name__)

MAX_RETRIES:      int   = 3
RETRY_DELAY_S:    float = 0.5
RECONNECT_POLL_S: float = 5.0


# ---------------------------------------------------------------------------
# Command envelope
# ---------------------------------------------------------------------------

@dataclass
class DeviceCommand:
    """Wraps a single command to be dispatched to the device worker thread."""
    name:       str
    params:     dict[str, Any] = field(default_factory=dict)
    retries:    int             = 0
    on_success: Optional[Callable[[Any], None]] = None
    on_failure: Optional[Callable[[Exception], None]] = None


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------

class DeviceBase(QObject):
    """
    Abstract base for every device driver.

    Signals (connect these in the UI):
        status_changed(DeviceStatus)   – fired whenever status changes
        data_received(dict)            – fired when device pushes unsolicited data
        log_message(str)               – human-readable diagnostic string
    """

    # ── Qt signals ──────────────────────────────────────────────────────────
    status_changed  = pyqtSignal(object)      # DeviceStatus
    data_received   = pyqtSignal(dict)        # arbitrary payload
    log_message     = pyqtSignal(str)
    battery_changed = pyqtSignal(int)         # 0-100, -1 = unsupported

    # ── Override these in subclasses ────────────────────────────────────────
    DEVICE_NAME:        str            = "UnnamedDevice"
    DEVICE_VERSION:     str            = "0.0.0"
    MANUFACTURER:       str            = "Unknown"       # shown in add-device dialog
    DEVICE_DESCRIPTION: str            = ""              # short human description
    CONNECTION_KINDS:   list[PortKind] = []
    ICON_PATH:          Optional[str]  = None            # relative to project root

    # ────────────────────────────────────────────────────────────────────────

    def __init__(
        self,
        descriptor: ConnectionDescriptor,
        device_id:  Optional[str] = None,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        import uuid
        self.device_id:   str                  = device_id or str(uuid.uuid4())
        self.descriptor:  ConnectionDescriptor = descriptor
        self._status:     DeviceStatus         = DeviceStatus.DISCONNECTED
        self._cmd_queue:  Queue[Optional[DeviceCommand]] = Queue()
        self._worker:     Optional[threading.Thread]     = None
        self._reconnect:  Optional[threading.Thread]     = None
        self._stop_event: threading.Event                = threading.Event()

    # ── Public API ──────────────────────────────────────────────────────────

    @property
    def status(self) -> DeviceStatus:
        return self._status

    def connect_device(self) -> None:
        """Start the worker thread and attempt first connection."""
        if self._worker and self._worker.is_alive():
            return
        self._stop_event.clear()
        self._worker = threading.Thread(
            target=self._worker_loop, name=f"{self.DEVICE_NAME}-worker", daemon=True
        )
        self._worker.start()
        log.info("[%s] Worker started for %s", self.DEVICE_NAME, self.descriptor.address)

    def disconnect_device(self) -> None:
        """Gracefully stop all threads and close the connection."""
        self._stop_event.set()
        self._cmd_queue.put(None)   # sentinel to unblock worker
        if self._worker:
            self._worker.join(timeout=3.0)
        try:
            self._close()
        except Exception as exc:
            log.warning("[%s] Error during close: %s", self.DEVICE_NAME, exc)
        self._set_status(DeviceStatus.DISCONNECTED)

    def send_command(
        self,
        name:       str,
        params:     Optional[dict[str, Any]] = None,
        on_success: Optional[Callable[[Any], None]] = None,
        on_failure: Optional[Callable[[Exception], None]] = None,
    ) -> None:
        """Enqueue a command for async dispatch to the device."""
        cmd = DeviceCommand(
            name       = name,
            params     = params or {},
            on_success = on_success,
            on_failure = on_failure,
        )
        self._cmd_queue.put(cmd)

    # ── Battery ──────────────────────────────────────────────────────────────

    @property
    def battery_level(self) -> int:
        """Last known battery level (0-100). -1 = not yet read / unsupported."""
        return getattr(self, "_battery_level", -1)

    def _update_battery(self, level: int) -> None:
        """Call from subclass when a battery reading is received."""
        self._battery_level = max(-1, min(100, int(level)))
        self.battery_changed.emit(self._battery_level)

    def to_dict(self) -> dict[str, Any]:
        return {
            "device_id":   self.device_id,
            "device_name": self.DEVICE_NAME,
            "descriptor":  self.descriptor.to_dict(),
        }

    # ── Abstract interface — implement in subclasses ─────────────────────────

    @abc.abstractmethod
    def _open(self) -> None:
        """
        Open the physical / network connection.
        Raise any exception on failure — the base class will handle retries.
        """

    @abc.abstractmethod
    def _close(self) -> None:
        """Close the connection (called on disconnect or before reconnect)."""

    @abc.abstractmethod
    def _execute_command(self, command: DeviceCommand) -> Any:
        """
        Send *command* to the device and return the result.
        Raise any exception on failure — the base class will handle retries.

        Example implementation:
            def _execute_command(self, command: DeviceCommand) -> Any:
                if command.name == "set_intensity":
                    value = command.params["value"]   # float 0-1
                    self._serial.write(f"I{int(value*255)}\n".encode())
                    return True
                raise ValueError(f"Unknown command: {command.name}")
        """

    @abc.abstractmethod
    def _ping(self) -> bool:
        """
        Lightweight check that the device is still alive.
        Return True if OK, raise or return False on failure.
        Called periodically by the worker to detect silent disconnects.
        """

    # ── Optional hooks ───────────────────────────────────────────────────────

    def _on_connected(self) -> None:
        """Called after a successful _open().  Override for init sequences."""

    def _on_disconnected(self) -> None:
        """Called when status drops to DISCONNECTED.  Override for clean-up."""

    def get_node_types(self) -> list[str]:
        """
        Return list of node type_keys this device contributes to the node graph.
        E.g. ["devices.MyDevice.SetIntensity", "devices.MyDevice.GetSensor"]
        Override in subclass; default returns empty list.
        """
        return []

    # ── Internal machinery ───────────────────────────────────────────────────

    def _set_status(self, new_status: DeviceStatus) -> None:
        if new_status != self._status:
            self._status = new_status
            self.status_changed.emit(new_status)
            self.log_message.emit(
                f"[{self.DEVICE_NAME}] status → {new_status.value}"
            )
            if new_status == DeviceStatus.DISCONNECTED:
                self._on_disconnected()

    def _worker_loop(self) -> None:
        """Main worker: connect, process commands, detect drop-outs."""
        self._attempt_connect()
        while not self._stop_event.is_set():
            try:
                cmd: Optional[DeviceCommand] = self._cmd_queue.get(timeout=1.0)
            except Empty:
                # Periodic ping when idle
                if self._status == DeviceStatus.CONNECTED:
                    try:
                        self._ping()
                    except Exception as exc:
                        log.warning("[%s] Ping failed: %s", self.DEVICE_NAME, exc)
                        self._handle_failure(None, exc)
                continue

            if cmd is None:          # sentinel / stop
                break
            self._dispatch(cmd)

    def _dispatch(self, cmd: DeviceCommand) -> None:
        """Execute a command with retry logic."""
        if self._status == DeviceStatus.DISCONNECTED:
            log.debug("[%s] Dropping command %s — device disconnected", self.DEVICE_NAME, cmd.name)
            if cmd.on_failure:
                cmd.on_failure(ConnectionError("Device is disconnected"))
            return

        try:
            result = self._execute_command(cmd)
            if self._status == DeviceStatus.UNKNOWN:
                self._set_status(DeviceStatus.CONNECTED)   # recovered
            if cmd.on_success:
                cmd.on_success(result)

        except Exception as exc:
            self._handle_failure(cmd, exc)

    def _handle_failure(self, cmd: Optional[DeviceCommand], exc: Exception) -> None:
        if cmd:
            cmd.retries += 1
            if cmd.retries < MAX_RETRIES:
                self._set_status(DeviceStatus.UNKNOWN)
                log.warning(
                    "[%s] Command '%s' failed (attempt %d/%d): %s",
                    self.DEVICE_NAME, cmd.name if cmd else "ping",
                    cmd.retries, MAX_RETRIES, exc,
                )
                time.sleep(RETRY_DELAY_S)
                self._dispatch(cmd)   # retry
                return
        # 3 failures → disconnected, start reconnect loop
        log.error("[%s] Max retries reached, marking DISCONNECTED.", self.DEVICE_NAME)
        self._set_status(DeviceStatus.DISCONNECTED)
        if cmd and cmd.on_failure:
            cmd.on_failure(exc)
        self._start_reconnect_loop()

    def _attempt_connect(self) -> None:
        try:
            self._open()
            self._set_status(DeviceStatus.CONNECTED)
            self._on_connected()
            self.log_message.emit(f"[{self.DEVICE_NAME}] Connected to {self.descriptor.address}")
        except Exception as exc:
            log.error("[%s] Connection failed: %s", self.DEVICE_NAME, exc)
            self._set_status(DeviceStatus.DISCONNECTED)
            self._start_reconnect_loop()

    def _start_reconnect_loop(self) -> None:
        if self._reconnect and self._reconnect.is_alive():
            return
        self._reconnect = threading.Thread(
            target=self._reconnect_loop,
            name=f"{self.DEVICE_NAME}-reconnect",
            daemon=True,
        )
        self._reconnect.start()

    def _reconnect_loop(self) -> None:
        """Poll until connection is restored or stop_event is set."""
        while not self._stop_event.is_set():
            time.sleep(RECONNECT_POLL_S)
            log.info("[%s] Attempting reconnect to %s …", self.DEVICE_NAME, self.descriptor.address)
            try:
                self._close()
            except Exception:
                pass
            try:
                self._open()
                self._set_status(DeviceStatus.CONNECTED)
                self._on_connected()
                self.log_message.emit(f"[{self.DEVICE_NAME}] Reconnected to {self.descriptor.address}")
                return
            except Exception as exc:
                log.warning("[%s] Reconnect failed: %s", self.DEVICE_NAME, exc)
