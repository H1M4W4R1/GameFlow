"""
H1M4W4R1 pump device — BLE pump with valve control via GATT.

GATT service: ae615e5d-b4be-428e-8ff9-9348c929a36e

Characteristics:
  Session duration (sec) — when finished: pump off, valve open
  Pump status 0/1, Valve status 0/1
  Current session time (sec), Current pumping time (sec)
  Expected pumping time (sec) — when finished: pump off
  Lock valve control via remote
"""
from __future__ import annotations

import asyncio
import logging
import struct
import threading
from typing import Any, Optional

from core.device_base import DeviceBase, DeviceCommand
from core.device_node_base import DeviceNodeBase, register_device_instance
from core.types import ConnectionDescriptor, PortKind, PinDescriptor, PinDirection, PinType

log = logging.getLogger(__name__)

# ── GATT UUIDs ─────────────────────────────────────────────────────────────

SERVICE_UUID = "ae615e5d-b4be-428e-8ff9-9348c929a36e"

CHAR_SESSION_DURATION   = "ae615c93-0000-4b7e-95ea-38792724bf8f"  # expected session (sec)
CHAR_PUMP_STATUS       = "ae615056-0001-4c20-a036-408083930b06"  # 0 or 1
CHAR_VALVE_STATUS      = "ae615d1c-0002-440c-8e7a-a976b1e560bc"  # 0 or 1
CHAR_CURRENT_SESSION   = "ae61502e-0003-4bd1-8440-408169e0323a"  # current session (sec)
CHAR_VALVE_LOCK        = "ae615096-0004-49ff-9ab0-fa194359595a"  # lock valve via remote
CHAR_EXPECTED_PUMP     = "ae6152b7-0005-49c3-975e-42c7fa2e14c9"  # expected pumping (sec)
CHAR_CURRENT_PUMP     = "ae6153c8-0006-4dd3-b764-80715dde7cab"  # current pumping (sec)

# Protocol: 0/1 as single byte; times as uint32 LE (seconds)
def _pack_bool(value: bool) -> bytes:
    return bytes([1 if value else 0])

def _pack_uint32(value: int) -> bytes:
    return struct.pack("<I", max(0, min(0xFFFFFFFF, value)))

def _unpack_uint32(data: bytes) -> int:
    if len(data) < 4:
        return 0
    return struct.unpack("<I", data[:4])[0]

def _unpack_bool(data: bytes) -> bool:
    return bool(data[0]) if data else False


# ── Device ──────────────────────────────────────────────────────────────────

DEVICE_TYPE_KEY = "devices.h1m4w4r1.pump.H1M4W4R1Pump"


class H1M4W4R1Pump(DeviceBase):
    """
    BLE pump with valve. Connect via MAC address or BLE scan.

    ConnectionDescriptor:
        kind    = PortKind.BLE
        address = "AA:BB:CC:DD:EE:FF"
    """

    DEVICE_NAME        = "H1M4W4R1 Pump"
    DEVICE_TR_PREFIX   = "h1m4w4r1.pump"
    DEVICE_VERSION     = "1.0.0"
    MANUFACTURER       = "H1M4W4R1"
    DEVICE_DESCRIPTION = "BLE pump with valve; session and pumping timers"
    CONNECTION_KINDS   = [PortKind.BLE]
    ICON_PATH         = "assets/icons/h1m4w4r1/pump.svg"
    # Used by BLE scan dialog to discover this device
    BLE_SERVICE_UUID   = SERVICE_UUID
    DEVICE_URL         = "https://github.com/H1M4W4R1/RemoteVacuumPump"

    def __init__(self, descriptor: ConnectionDescriptor, **kwargs) -> None:
        super().__init__(descriptor, **kwargs)
        self._loop:   Optional[asyncio.AbstractEventLoop] = None
        self._client: Any = None  # bleak.BleakClient
        self._current_session_sec: int = 0
        self._current_pump_sec: int = 0

    def _open(self) -> None:
        self._loop = asyncio.new_event_loop()
        t = threading.Thread(target=self._loop.run_forever, daemon=True,
                             name=f"{self.DEVICE_NAME}-loop")
        t.start()
        future = asyncio.run_coroutine_threadsafe(self._async_connect(), self._loop)
        future.result(timeout=20)

    async def _async_connect(self) -> None:
        from bleak import BleakClient  # type: ignore
        self._client = BleakClient(self.descriptor.address)
        await self._client.connect()
        # Optional: subscribe to notify on current session / current pump if device supports it
        try:
            await self._client.start_notify(CHAR_CURRENT_SESSION, self._on_session_notify)
        except Exception:
            pass
        try:
            await self._client.start_notify(CHAR_CURRENT_PUMP, self._on_pump_notify)
        except Exception:
            pass
        # Initial read of read-only values
        await self._read_times_async()

    def _on_session_notify(self, _sender: Any, data: bytes) -> None:
        self._current_session_sec = _unpack_uint32(data)
        self.data_received.emit({
            "type": "current_session",
            "seconds": self._current_session_sec,
        })

    def _on_pump_notify(self, _sender: Any, data: bytes) -> None:
        self._current_pump_sec = _unpack_uint32(data)
        self.data_received.emit({
            "type": "current_pump",
            "seconds": self._current_pump_sec,
        })

    async def _read_times_async(self) -> None:
        try:
            data = await self._client.read_gatt_char(CHAR_CURRENT_SESSION)
            self._current_session_sec = _unpack_uint32(data)
        except Exception:
            pass
        try:
            data = await self._client.read_gatt_char(CHAR_CURRENT_PUMP)
            self._current_pump_sec = _unpack_uint32(data)
        except Exception:
            pass

    def _close(self) -> None:
        if self._client and self._loop:
            future = asyncio.run_coroutine_threadsafe(
                self._safe_disconnect(), self._loop
            )
            try:
                future.result(timeout=5)
            except Exception:
                pass
        self._client = None

    async def _safe_disconnect(self) -> None:
        try:
            if self._client and self._client.is_connected:
                await self._client.disconnect()
        except Exception as e:
            log.debug("[%s] Disconnect error: %s", self.DEVICE_NAME, e)

    def _ping(self) -> bool:
        if not self._client or not self._loop:
            raise ConnectionError("Not connected")
        if not self._client.is_connected:
            raise ConnectionError("BLE disconnected")
        return True

    def _execute_command(self, command: DeviceCommand) -> Any:
        if not self._loop:
            raise ConnectionError("Not ready")
        future = asyncio.run_coroutine_threadsafe(
            self._dispatch_command(command), self._loop
        )
        return future.result(timeout=10)

    async def _write_char(self, char_uuid: str, payload: bytes) -> None:
        if not self._client:
            raise ConnectionError("Not connected")
        await self._client.write_gatt_char(char_uuid, payload, response=False)

    async def _read_char(self, char_uuid: str) -> bytes:
        if not self._client:
            raise ConnectionError("Not connected")
        return await self._client.read_gatt_char(char_uuid)

    async def _dispatch_command(self, command: DeviceCommand) -> Any:
        name   = command.name
        params = command.params

        if name == "set_session_duration":
            sec = int(params.get("seconds", 0))
            await self._write_char(CHAR_SESSION_DURATION, _pack_uint32(sec))
            return sec

        if name == "set_pump":
            on = bool(params.get("on", False))
            await self._write_char(CHAR_PUMP_STATUS, _pack_bool(on))
            return on

        if name == "set_valve":
            on = bool(params.get("on", False))
            await self._write_char(CHAR_VALVE_STATUS, _pack_bool(on))
            return on

        if name == "set_expected_pump_time":
            sec = int(params.get("seconds", 0))
            await self._write_char(CHAR_EXPECTED_PUMP, _pack_uint32(sec))
            return sec

        if name == "set_valve_lock":
            lock = bool(params.get("lock", False))
            await self._write_char(CHAR_VALVE_LOCK, _pack_bool(lock))
            return lock

        if name == "get_current_session":
            data = await self._read_char(CHAR_CURRENT_SESSION)
            self._current_session_sec = _unpack_uint32(data)
            return self._current_session_sec

        if name == "get_current_pump":
            data = await self._read_char(CHAR_CURRENT_PUMP)
            self._current_pump_sec = _unpack_uint32(data)
            return self._current_pump_sec

        if name == "stop":
            await self._write_char(CHAR_PUMP_STATUS, _pack_bool(False))
            await self._write_char(CHAR_VALVE_STATUS, _pack_bool(True))
            return True

        raise ValueError(f"[{self.DEVICE_NAME}] Unknown command: {name!r}")

    def _on_connected(self) -> None:
        register_device_instance(DEVICE_TYPE_KEY, self)

    def get_node_types(self) -> list[str]:
        return [
            f"{__name__}.PumpSetSessionDurationNode",
            f"{__name__}.PumpSetPumpNode",
            f"{__name__}.PumpSetValveNode",
            f"{__name__}.PumpSetExpectedPumpTimeNode",
            f"{__name__}.PumpSetValveLockNode",
            f"{__name__}.PumpGetCurrentSessionNode",
            f"{__name__}.PumpGetCurrentPumpNode",
            f"{__name__}.PumpStopNode",
        ]


# ── Nodes ────────────────────────────────────────────────────────────────────

def _pump_node_key(suffix: str) -> str:
    return f"{DEVICE_TYPE_KEY}.{suffix}"


class _PumpNodeBase(DeviceNodeBase):
    DEVICE_TYPE_KEY = DEVICE_TYPE_KEY
    ICON_PATH       = "assets/icons/h1m4w4r1/pump.svg"
    NODE_GROUP      = "Devices/H1M4W4R1/Pump"


class PumpSetSessionDurationNode(_PumpNodeBase):
    NODE_NAME = "Pump: Set session duration"
    PINS = [
        PinDescriptor("exec_in",   PinDirection.INPUT,  PinType.TICK),
        PinDescriptor("seconds",   PinDirection.INPUT,  PinType.INT, default=300),
        PinDescriptor("exec_out",  PinDirection.OUTPUT, PinType.TICK),
    ]
    VARIABLE_INPUTS = {"seconds": (int, 300)}

    def execute(self, trigger_pin: str) -> None:
        dev = self.get_device()
        if not dev:
            self.fire_tick("exec_out")
            return
        sec = int(self.get_var_input("seconds") or 300)
        sec = max(0, min(0xFFFFFFFF, sec))
        self.send_to_device("set_session_duration", {"seconds": sec},
                            on_success=lambda _: self.fire_tick("exec_out"))


class PumpSetPumpNode(_PumpNodeBase):
    NODE_NAME = "Pump: Set pump on/off"
    PINS = [
        PinDescriptor("exec_in",   PinDirection.INPUT,  PinType.TICK),
        PinDescriptor("on",        PinDirection.INPUT,  PinType.BOOL, default=True),
        PinDescriptor("exec_out",  PinDirection.OUTPUT, PinType.TICK),
    ]
    VARIABLE_INPUTS = {"on": (bool, True)}

    def execute(self, trigger_pin: str) -> None:
        dev = self.get_device()
        if not dev:
            self.fire_tick("exec_out")
            return
        on = bool(self.get_var_input("on") if self.get_var_input("on") is not None else True)
        self.send_to_device("set_pump", {"on": on},
                            on_success=lambda _: self.fire_tick("exec_out"))


class PumpSetValveNode(_PumpNodeBase):
    NODE_NAME = "Pump: Set valve on/off"
    PINS = [
        PinDescriptor("exec_in",   PinDirection.INPUT,  PinType.TICK),
        PinDescriptor("on",        PinDirection.INPUT,  PinType.BOOL, default=False),
        PinDescriptor("exec_out",  PinDirection.OUTPUT, PinType.TICK),
    ]
    VARIABLE_INPUTS = {"on": (bool, False)}

    def execute(self, trigger_pin: str) -> None:
        dev = self.get_device()
        if not dev:
            self.fire_tick("exec_out")
            return
        on = bool(self.get_var_input("on") if self.get_var_input("on") is not None else False)
        self.send_to_device("set_valve", {"on": on},
                            on_success=lambda _: self.fire_tick("exec_out"))


class PumpSetExpectedPumpTimeNode(_PumpNodeBase):
    NODE_NAME = "Pump: Set expected pumping time"
    PINS = [
        PinDescriptor("exec_in",   PinDirection.INPUT,  PinType.TICK),
        PinDescriptor("seconds",   PinDirection.INPUT,  PinType.INT, default=0),
        PinDescriptor("exec_out",  PinDirection.OUTPUT, PinType.TICK),
    ]
    VARIABLE_INPUTS = {"seconds": (int, 0)}

    def execute(self, trigger_pin: str) -> None:
        dev = self.get_device()
        if not dev:
            self.fire_tick("exec_out")
            return
        sec = int(self.get_var_input("seconds") or 0)
        sec = max(0, min(0xFFFFFFFF, sec))
        self.send_to_device("set_expected_pump_time", {"seconds": sec},
                            on_success=lambda _: self.fire_tick("exec_out"))


class PumpSetValveLockNode(_PumpNodeBase):
    NODE_NAME = "Pump: Lock valve (remote)"
    PINS = [
        PinDescriptor("exec_in",   PinDirection.INPUT,  PinType.TICK),
        PinDescriptor("lock",      PinDirection.INPUT,  PinType.BOOL, default=False),
        PinDescriptor("exec_out",  PinDirection.OUTPUT, PinType.TICK),
    ]
    VARIABLE_INPUTS = {"lock": (bool, False)}

    def execute(self, trigger_pin: str) -> None:
        dev = self.get_device()
        if not dev:
            self.fire_tick("exec_out")
            return
        lock = bool(self.get_var_input("lock") if self.get_var_input("lock") is not None else False)
        self.send_to_device("set_valve_lock", {"lock": lock},
                            on_success=lambda _: self.fire_tick("exec_out"))


class PumpGetCurrentSessionNode(_PumpNodeBase):
    NODE_NAME = "Pump: Get current session time"
    PINS = [
        PinDescriptor("exec_in",   PinDirection.INPUT,  PinType.TICK),
        PinDescriptor("exec_out", PinDirection.OUTPUT, PinType.TICK),
        PinDescriptor("seconds",   PinDirection.OUTPUT, PinType.INT),
    ]

    def execute(self, trigger_pin: str) -> None:
        dev = self.get_device()
        if not dev:
            self.set_output("seconds", 0)
            self.fire_tick("exec_out")
            return

        def done(sec: int) -> None:
            self.set_output("seconds", sec)
            self.fire_tick("exec_out")

        def fail(_: Exception) -> None:
            self.set_output("seconds", 0)
            self.fire_tick("exec_out")

        dev.send_command("get_current_session", {}, on_success=done, on_failure=fail)


class PumpGetCurrentPumpNode(_PumpNodeBase):
    NODE_NAME = "Pump: Get current pumping time"
    PINS = [
        PinDescriptor("exec_in",   PinDirection.INPUT,  PinType.TICK),
        PinDescriptor("exec_out", PinDirection.OUTPUT, PinType.TICK),
        PinDescriptor("seconds",   PinDirection.OUTPUT, PinType.INT),
    ]

    def execute(self, trigger_pin: str) -> None:
        dev = self.get_device()
        if not dev:
            self.set_output("seconds", 0)
            self.fire_tick("exec_out")
            return

        def done(sec: int) -> None:
            self.set_output("seconds", sec)
            self.fire_tick("exec_out")

        def fail(_: Exception) -> None:
            self.set_output("seconds", 0)
            self.fire_tick("exec_out")

        dev.send_command("get_current_pump", {}, on_success=done, on_failure=fail)


class PumpStopNode(_PumpNodeBase):
    NODE_NAME = "Pump: Stop (pump off, valve open)"
    PINS = [
        PinDescriptor("exec_in",  PinDirection.INPUT,  PinType.TICK),
        PinDescriptor("exec_out", PinDirection.OUTPUT, PinType.TICK),
    ]

    def execute(self, trigger_pin: str) -> None:
        dev = self.get_device()
        if dev:
            self.send_to_device("stop", {}, on_success=lambda _: self.fire_tick("exec_out"))
        else:
            self.fire_tick("exec_out")


# ── Exports for registry ─────────────────────────────────────────────────────

ALL_DEVICE_CLASSES = [H1M4W4R1Pump]

ALL_NODE_CLASSES = [
    PumpSetSessionDurationNode,
    PumpSetPumpNode,
    PumpSetValveNode,
    PumpSetExpectedPumpTimeNode,
    PumpSetValveLockNode,
    PumpGetCurrentSessionNode,
    PumpGetCurrentPumpNode,
    PumpStopNode,
]
