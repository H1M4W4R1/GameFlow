"""
_lovense_base.py — shared BLE transport and protocol for all Lovense devices.

Protocol reference: https://buttplug.io/stpihkal/protocols/lovense/

GATT service/characteristic UUIDs (all firmware generations):
  Gen1/2 service:  0000fff0-0000-1000-8000-00805f9b34fb
    TX char:       0000fff2-0000-1000-8000-00805f9b34fb
    RX char:       0000fff1-0000-1000-8000-00805f9b34fb
  Gen3 service:    59610001-eda-... (varies; scan by name prefix LVS-*/LOVE-*)
  Edge2 service:   50300011-0023-4bd4-bbd5-a6920e4c5653
    TX char:       50300012-0023-4bd4-bbd5-a6920e4c5653
    RX char:       50300013-0023-4bd4-bbd5-a6920e4c5653

Command format: "<Command>[:<arg>][:<arg>];"
Response format: "<value>;"  or  "OK;"  or  "ERR;"

Device identifier letters (returned by DeviceType;):
  R=Diamo  S=Lush  C/A=Nora  B=Max  Z=Hush  L=Ambi
  P=Edge   W=Domi  O=Osci    X=Ferri  EF=Exomoon  G=Gemini  GU=Gush
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any, Callable, Optional

from PyQt6.QtCore import QObject

from core.device_base import DeviceBase, DeviceCommand
from core.types import ConnectionDescriptor, PortKind

log = logging.getLogger(__name__)

# ── Known GATT profiles ───────────────────────────────────────────────────────
# Each entry: (service_uuid, tx_char_uuid, rx_char_uuid)
# Source: https://buttplug.io/stpihkal/protocols/lovense/

_GATT_PROFILES = [
    (
        # Generation 1 — static service
        "0000fff0-0000-1000-8000-00805f9b34fb",
        "0000fff2-0000-1000-8000-00805f9b34fb",   # TX: write / write-without-response
        "0000fff1-0000-1000-8000-00805f9b34fb",   # RX: read / notify
    ),
    (
        # Generation 2 — Nordic UART Service (NUS)
        "6e400001-b5a3-f393-e0a9-e50e24dcca9e",
        "6e400002-b5a3-f393-e0a9-e50e24dcca9e",   # TX: write-without-response / write
        "6e400003-b5a3-f393-e0a9-e50e24dcca9e",   # RX: notify
    ),
]

# Generation 3 — variable service UUID: XY300001-002Z-4bd4-bbd5-a6920e4c5653
#   X ∈ {4, 5}
#   Y ∈ {0..f}
#   Z ∈ {3, 4}
# Generates 2 × 16 × 2 = 64 combinations.
# TX char: XY300002-002Z-4bd4-bbd5-a6920e4c5653
# RX char: XY300003-002Z-4bd4-bbd5-a6920e4c5653
_GEN3_PROFILES: list[tuple[str, str, str]] = []
for _x in (4, 5):
    for _y in range(16):
        for _z in (3, 4):
            _svc = f"{_x:x}{_y:x}300001-002{_z}-4bd4-bbd5-a6920e4c5653"
            _tx  = f"{_x:x}{_y:x}300002-002{_z}-4bd4-bbd5-a6920e4c5653"
            _rx  = f"{_x:x}{_y:x}300003-002{_z}-4bd4-bbd5-a6920e4c5653"
            _GEN3_PROFILES.append((_svc, _tx, _rx))

# Vibration level scale: 0-20 (0=off, 20=max)
VIBRATE_MAX = 20

# ── BLE advertisement filters used by the scanner ────────────────────────────

# Device name prefixes to match during BLE scan
BLE_NAME_PREFIXES: tuple[str, ...] = ("LVS-", "LOVE-")

# All known Lovense service UUIDs (Gen1 + Gen2 static; Gen3 generated below)
BLE_SERVICE_UUIDS: list[str] = (
    [p[0] for p in _GATT_PROFILES] + [p[0] for p in _GEN3_PROFILES]
)

# Map BLE advertisement name suffix fragment → DEVICE_IDENTIFIER
# "LVS-<identifier><firmware>" e.g. "LVS-Z011" → "Z", "LVS-Edge36" → "Edge"
BLE_NAME_TO_IDENTIFIER: dict[str, str] = {
    # Single-char identifiers (old naming convention)
    "S": "S",   # Lush
    "Z": "Z",   # Hush
    "W": "W",   # Domi
    "L": "L",   # Ambi
    "X": "X",   # Ferri
    "O": "O",   # Osci
    "G": "G",   # Gemini
    "P": "P",   # Edge
    "R": "R",   # Diamo
    "B": "B",   # Max
    "A": "A",   # Nora (old)
    "C": "A",   # Nora (very old firmware)
    # Full product-name convention (newer firmware)
    "Lush":   "S",
    "Hush":   "Z",
    "Domi":   "W",
    "Ambi":   "L",
    "Ferri":  "X",
    "Osci":   "O",
    "Gemini": "G",
    "Gush":   "GU",
    "Edge":   "P",
    "Diamo":  "R",
    "Max":    "B",
    "Nora":   "A",
    "Ridge":  "W",   # Domi2 / Ridge
}


class _LovenseBLEBase(DeviceBase):
    """
    Abstract BLE base for all Lovense devices.
    Subclasses only need to set class attributes and implement get_node_types().

    Subclass example:
        class LovenseHush(_LovenseBLEBase):
            DEVICE_NAME        = "Lovense Hush"
            DEVICE_DESCRIPTION = "Vibrating butt plug"
            ICON_PATH          = "assets/icons/lovense/hush.svg"
            DEVICE_IDENTIFIER  = "Z"
            VIBRATOR_COUNT     = 1
            VIBRATOR_NAMES     = ["Vibrate"]
    """

    MANUFACTURER       = "Lovense"
    CONNECTION_KINDS   = [PortKind.BLE]
    ICON_PATH          = "assets/icons/lovense/lovense.svg"

    # Override in subclass
    DEVICE_IDENTIFIER:  str       = ""     # single-letter code from DeviceType response
    VIBRATOR_COUNT:     int       = 1
    VIBRATOR_NAMES:     list[str] = ["Vibrate"]
    SUPPORTS_ROTATE:    bool      = False
    SUPPORTS_AIR:       bool      = False  # Max-style inflate/deflate

    # Battery poll interval (seconds); 0 to disable
    BATTERY_POLL_S: float = 30.0

    def __init__(self, descriptor: ConnectionDescriptor, **kwargs) -> None:
        super().__init__(descriptor, **kwargs)
        self._loop:       Optional[asyncio.AbstractEventLoop] = None
        self._client:     Any = None          # bleak.BleakClient
        self._tx_char:    Optional[str] = None
        self._rx_char:    Optional[str] = None
        self._rx_buffer:  str = ""
        self._pending:    dict[str, asyncio.Future] = {}
        self._last_bat:   float = 0.0
        self._vib_levels: list[int] = [0] * max(1, self.VIBRATOR_COUNT)

    # ── DeviceBase interface ──────────────────────────────────────────────────

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
        await self._detect_gatt_profile()
        if self._rx_char:
            await self._client.start_notify(self._rx_char, self._on_notification)
        # Identify device
        resp = await self._send_command_async("DeviceType")
        if resp:
            self.log_message.emit(f"[{self.DEVICE_NAME}] DeviceType: {resp}")
        # Initial battery read
        await self._read_battery_async()

    async def _detect_gatt_profile(self) -> None:
        """
        Try all known GATT profiles (Gen1, Gen2, all 32 Gen3 variants) until
        one has a matching TX characteristic in the connected device's service table.
        """
        services = self._client.services
        all_profiles = _GATT_PROFILES + _GEN3_PROFILES
        for svc_uuid, tx_uuid, rx_uuid in all_profiles:
            svc = services.get_service(svc_uuid)
            if svc is None:
                continue
            char_uuids = {c.uuid.lower() for c in svc.characteristics}
            if tx_uuid.lower() in char_uuids:
                self._tx_char = tx_uuid
                self._rx_char = rx_uuid
                log.info("[%s] GATT profile: %s", self.DEVICE_NAME, svc_uuid)
                return
        # Descriptor override
        if "tx_char" in self.descriptor.extra:
            self._tx_char = self.descriptor.extra["tx_char"]
            self._rx_char = self.descriptor.extra.get("rx_char", "")
            log.warning("[%s] Using descriptor-override GATT profile", self.DEVICE_NAME)
            return
        raise ConnectionError(
            f"[{self.DEVICE_NAME}] No known GATT profile found on device. "
            "Check that the device is turned on and in range."
        )

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
                await self._send_command_async("PowerOff")
                await self._client.disconnect()
        except Exception as e:
            log.debug("[%s] Disconnect error: %s", self.DEVICE_NAME, e)

    def _ping(self) -> bool:
        if not self._client or not self._loop:
            raise ConnectionError("Not connected")
        if not self._client.is_connected:
            raise ConnectionError("BLE disconnected")
        # Poll battery periodically as the ping
        now = time.monotonic()
        if self.BATTERY_POLL_S > 0 and (now - self._last_bat) >= self.BATTERY_POLL_S:
            future = asyncio.run_coroutine_threadsafe(
                self._read_battery_async(), self._loop
            )
            try:
                future.result(timeout=3)
            except Exception:
                pass
        return True

    def _execute_command(self, command: DeviceCommand) -> Any:
        if not self._loop:
            raise ConnectionError("Not ready")
        future = asyncio.run_coroutine_threadsafe(
            self._dispatch_command(command), self._loop
        )
        return future.result(timeout=5)

    # ── Lovense command dispatch ──────────────────────────────────────────────

    async def _dispatch_command(self, command: DeviceCommand) -> Any:
        name   = command.name
        params = command.params

        if name == "vibrate":
            # params: {"index": 0, "level": 0-20}  or {"levels": [l0, l1, ...]}
            levels = params.get("levels")
            if levels is None:
                idx   = int(params.get("index", 0))
                level = int(params.get("level", 0))
                self._vib_levels[idx] = max(0, min(VIBRATE_MAX, level))
            else:
                for i, l in enumerate(levels[:self.VIBRATOR_COUNT]):
                    self._vib_levels[i] = max(0, min(VIBRATE_MAX, int(l)))
            return await self._send_vibrate()

        if name == "stop":
            self._vib_levels = [0] * self.VIBRATOR_COUNT
            return await self._send_command_async("Vibrate:0")

        if name == "rotate":
            level = int(params.get("level", 0))
            cmd   = f"Rotate:{max(0, min(VIBRATE_MAX, level))}"
            return await self._send_command_async(cmd)

        if name == "rotate_change":
            return await self._send_command_async("RotateChange")

        if name == "air":
            # inflate: Air:In:<steps>;  deflate: Air:Out:<steps>;  level: Air:Level:<0-5>;
            action = params.get("action", "level")
            value  = int(params.get("value", 0))
            cmd_map = {"in": f"Air:In:{value}", "out": f"Air:Out:{value}",
                       "level": f"Air:Level:{value}"}
            return await self._send_command_async(cmd_map.get(action, "Air:Level:0"))

        if name == "battery":
            return await self._read_battery_async()

        if name == "raw":
            return await self._send_command_async(params.get("cmd", ""))

        raise ValueError(f"[{self.DEVICE_NAME}] Unknown command: {name!r}")

    async def _send_vibrate(self) -> str:
        """Build the correct vibrate command for single- or multi-motor devices."""
        if self.VIBRATOR_COUNT == 1:
            cmd = f"Vibrate:{self._vib_levels[0]}"
        else:
            # Multi-motor: Vibrate1:l1;Vibrate2:l2; ... (separate commands)
            # or Vibrate:l; sets all.  Use indexed commands for per-motor control.
            parts = [f"Vibrate{i+1}:{l}" for i, l in enumerate(self._vib_levels)]
            # Send as a batch; devices respond once per command
            for part in parts:
                await self._send_command_async(part)
            return "OK"
        return await self._send_command_async(cmd)

    async def _send_command_async(self, cmd: str, timeout: float = 1.0) -> str:
        """
        Send a semicolon-terminated command and wait up to *timeout* seconds
        for the device to respond via BLE notification.

        The response is captured by _on_notification into self._rx_buffer.
        We poll that buffer for up to *timeout* seconds.
        Non-critical commands (like Vibrate) don't require a response — we
        return "OK" immediately after writing if no response arrives.
        """
        if not self._client or not self._tx_char:
            raise ConnectionError("Not ready")

        # Clear any previous partial response for this command
        self._rx_buffer = ""

        payload = f"{cmd};".encode("ascii")
        await self._client.write_gatt_char(self._tx_char, payload, response=False)

        # Wait for notification response
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            if self._rx_buffer:
                resp = self._rx_buffer.strip().rstrip(";")
                self._rx_buffer = ""
                return resp
            await asyncio.sleep(0.02)

        return "OK"   # no response received — not an error for fire-and-forget commands

    async def _read_battery_async(self) -> int:
        """Send Battery; command and parse the numeric response."""
        resp = await self._send_command_async("Battery", timeout=2.0)
        self._last_bat = time.monotonic()
        if resp.isdigit():
            level = int(resp)
            if 0 <= level <= 100:
                self._update_battery(level)
                return level
        return -1

    def _on_notification(self, sender: Any, data: bytes) -> None:
        """
        Handle incoming BLE notifications from the device.

        All raw text is written to _rx_buffer so _send_command_async can read it.
        Additional parsing happens here for well-known response formats.
        """
        try:
            text = data.decode("ascii", errors="ignore").strip()
        except Exception:
            return

        # Store in buffer so awaited commands can read the response
        self._rx_buffer = text

        clean = text.rstrip(";")

        # Battery response: a plain integer "85"
        if clean.isdigit():
            level = int(clean)
            if 0 <= level <= 100:
                self._update_battery(level)
            return

        # DeviceType response: "<type>:<fw>:<mac>"  e.g. "W:10:AA:BB:CC:DD:EE:FF"
        parts = clean.split(":")
        if 2 <= len(parts) <= 8 and len(parts[0]) <= 3 and parts[0].isalpha():
            dev_ident = parts[0].upper()
            fw        = parts[1] if len(parts) > 1 else "?"
            self.log_message.emit(
                f"[{self.DEVICE_NAME}] DeviceType={dev_ident} FW={fw}"
            )
            # Emit raw data for any listener that wants it
            self.data_received.emit({
                "type": "device_type",
                "identifier": dev_ident,
                "firmware": fw,
                "raw": clean,
            })
            return

        self.data_received.emit({"type": "raw", "raw": clean})

    def _on_connected(self) -> None:
        from core.device_node_base import register_device_instance
        key = f"{self.__class__.__module__}.{self.__class__.__name__}"
        register_device_instance(key, self)

    # ── Convenience helpers for node subclasses ───────────────────────────────

    def vibrate(self, index: int, level: float,
                on_success: Optional[Callable] = None,
                on_failure: Optional[Callable] = None) -> None:
        """Send vibrate 0.0-1.0 float to specified motor index."""
        raw = int(round(level * VIBRATE_MAX))
        self.send_command("vibrate", {"index": index, "level": raw},
                          on_success=on_success, on_failure=on_failure)

    def stop_all(self, on_success: Optional[Callable] = None) -> None:
        self.send_command("stop", {}, on_success=on_success)

    def request_battery(self) -> None:
        self.send_command("battery", {})
