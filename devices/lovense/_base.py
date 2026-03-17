"""
_lovense_base.py — shared BLE transport and protocol for all Lovense devices.

Protocol reference: https://buttplug.io/stpihkal/protocols/lovense/

GATT service/characteristic UUIDs (all firmware generations):
  Gen1/2 service:  0000fff0-0000-1000-8000-00805f9b34fb
    TX char:       0000fff2-0000-1000-8000-00805f9b34fb
    RX char:       0000fff1-0000-1000-8000-00805f9b34fb
  Gen2 NUS service: 6e400001-b5a3-f393-e0a9-e50e24dcca9e
    TX char:       6e400002-b5a3-f393-e0a9-e50e24dcca9e
    RX char:       6e400003-b5a3-f393-e0a9-e50e24dcca9e
  Gen3 service:    XY300001-002Z-4bd4-bbd5-a6920e4c5653 (many variants)

Command format: "<Command>[:<arg>][:<arg>];"
Response format: "<value>;"  or  "OK;"  or  "ERR;"

Device identifier letters (returned by DeviceType;):
  S=Lush   AN=LushAnal  Z=Hush   W=Domi   L=Ambi   X=Ferri
  O=Osci   OC=Osci3     N=Gemini J=Dolce  P=Edge   R=Diamo
  B=Max    A/C=Nora     ED=Gush  EZ=Gush2 EB=Hyphy T=Calor
  Q=Tenera SD=Vulse     V=Mission CA=Mission2
  H=Solace BA=SolacePro EL=Ridge EA=Gravity WD=Spinel
  EI=Flexer U=Lapis      F=SexMachine FS=MiniSexMachine
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
# Single-char identifiers: byte1=ord(X), byte2=0x30 ('0'), e.g. P→50300001
_GEN3_PROFILES: list[tuple[str, str, str]] = []
for _x in (4, 5):
    for _y in range(16):
        for _z in (3, 4):
            _svc = f"{_x:x}{_y:x}300001-002{_z}-4bd4-bbd5-a6920e4c5653"
            _tx  = f"{_x:x}{_y:x}300002-002{_z}-4bd4-bbd5-a6920e4c5653"
            _rx  = f"{_x:x}{_y:x}300003-002{_z}-4bd4-bbd5-a6920e4c5653"
            _GEN3_PROFILES.append((_svc, _tx, _rx))

# Generation 3 — multi-char identifier devices: service UUID encodes the
# identifier as ASCII hex, e.g. "EL" → 0x45 0x4c → 454c0001-002Z-...
# These are NOT covered by the XY300001 generator above.
_MULTI_CHAR_IDENTIFIERS = [
    "AN", "OC", "ED", "EZ", "EB", "CA", "SD", "BA",
    "EL", "EA", "WD", "EI", "FS",
]
for _ident in _MULTI_CHAR_IDENTIFIERS:
    _b1, _b2 = ord(_ident[0]), ord(_ident[1])
    _prefix   = f"{_b1:02x}{_b2:02x}"
    for _z in (3, 4):
        _svc = f"{_prefix}0001-002{_z}-4bd4-bbd5-a6920e4c5653"
        _tx  = f"{_prefix}0002-002{_z}-4bd4-bbd5-a6920e4c5653"
        _rx  = f"{_prefix}0003-002{_z}-4bd4-bbd5-a6920e4c5653"
        _GEN3_PROFILES.append((_svc, _tx, _rx))

# Vibration level scale: 0-20 (0=off, 20=max)
VIBRATE_MAX = 20

# ── BLE advertisement filters ─────────────────────────────────────────────────

# Fallback name prefixes (used by LovenseUnknownDevice generic class)
BLE_NAME_PREFIXES: tuple[str, ...] = ("LVS-", "LOVE-")

# All known Lovense service UUIDs (Gen1 + Gen2 static; Gen3 generated)
BLE_SERVICE_UUIDS: list[str] = (
    [p[0] for p in _GATT_PROFILES] + [p[0] for p in _GEN3_PROFILES]
)

# ── Global identifier → class_key registry ───────────────────────────────────
# Populated automatically when each _LovenseBLEBase subclass is defined.
# Key: DEVICE_IDENTIFIER (upper), Value: "<module>.<ClassName>"

_IDENTIFIER_TO_CLASS_KEY: dict[str, str] = {}


def _lookup_class_key_by_identifier(identifier: str) -> str:
    """Return the class_key for a DeviceType; identifier, or '' if unknown."""
    return _IDENTIFIER_TO_CLASS_KEY.get(identifier.upper(), "")


class _LovenseBLEBase(DeviceBase):
    """
    Abstract BLE base for all Lovense devices.
    Subclasses set class attributes and implement get_node_types().

    Subclass example:
        class LovenseHush(_LovenseBLEBase):
            DEVICE_NAME        = "Lovense Hush"
            DEVICE_DESCRIPTION = "Vibrating butt plug"
            ICON_PATH          = "assets/icons/lovense/hush.svg"
            DEVICE_IDENTIFIER  = "Z"
            BLE_NAME_PREFIXES  = ("LVS-Z", "LOVE-Z", "LVS-Hush", "LOVE-Hush")
            VIBRATOR_COUNT     = 1
            VIBRATOR_NAMES     = ["Vibrate"]
    """

    MANUFACTURER       = "Lovense"
    CONNECTION_KINDS   = [PortKind.BLE]
    ICON_PATH          = "assets/icons/lovense/lovense.svg"

    # Override in subclass —————————————————————————————————————————————————————
    # Primary identifier returned by DeviceType;
    DEVICE_IDENTIFIER:  str       = ""
    # Additional identifiers (e.g. Nora's old-firmware "C")
    DEVICE_IDENTIFIER_ALIASES: list[str] = []
    # BLE advertisement name prefixes (should be device-specific, e.g. ("LVS-Z",))
    BLE_NAME_PREFIXES:  tuple     = ("LVS-", "LOVE-")

    VIBRATOR_COUNT:     int       = 1
    VIBRATOR_NAMES:     list[str] = ["Vibrate"]
    SUPPORTS_ROTATE:    bool      = False
    SUPPORTS_AIR:       bool      = False       # Max-style inflate/deflate
    SUPPORTS_ACCELEROMETER: bool  = False       # Max: StartMove/StopMove
    SUPPORTS_ALIGHT:    bool      = False       # Domi: ALight:On/Off

    BATTERY_POLL_S: float = 30.0

    # ── Auto-register identifiers when subclass is defined ────────────────────

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        class_key = f"{cls.__module__}.{cls.__name__}"
        ident = getattr(cls, "DEVICE_IDENTIFIER", "")
        if ident:
            _IDENTIFIER_TO_CLASS_KEY[ident.upper()] = class_key
        for alias in getattr(cls, "DEVICE_IDENTIFIER_ALIASES", []):
            if alias:
                _IDENTIFIER_TO_CLASS_KEY[alias.upper()] = class_key

    def __init__(self, descriptor: ConnectionDescriptor, **kwargs) -> None:
        super().__init__(descriptor, **kwargs)
        self._loop:       Optional[asyncio.AbstractEventLoop] = None
        self._client:     Any = None
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
        # Subscribe to every notify-capable characteristic in the matched service.
        # Devices like Max send accelerometer data on a separate notify characteristic
        # that is not the primary RX char, so subscribing to only _rx_char misses it.
        await self._subscribe_all_notify_chars()
        # Identify device via DeviceType; command
        resp = await self._send_command_async("DeviceType", timeout=2.0)
        if resp:
            self._handle_device_type_response(resp)
        # Initial battery read
        await self._read_battery_async()

    async def _subscribe_all_notify_chars(self) -> None:
        """Subscribe _on_notification to every NOTIFY char in the matched service."""
        if not self._tx_char:
            return
        tx_lower = self._tx_char.lower()
        for svc in self._client.services:
            if not any(c.uuid.lower() == tx_lower for c in svc.characteristics):
                continue
            for char in svc.characteristics:
                if "notify" in char.properties:
                    try:
                        await self._client.start_notify(char.uuid, self._on_notification)
                        log.info("[%s] Subscribed notify: %s", self.DEVICE_NAME, char.uuid)
                    except Exception as exc:
                        log.debug("[%s] Could not subscribe to %s: %s",
                                  self.DEVICE_NAME, char.uuid, exc)
            return

    def _handle_device_type_response(self, resp: str) -> None:
        """
        Parse DeviceType; response: "<identifier>:<fw>:<mac>..."
        Verify the identifier matches this class. If not, emit data_received
        with type "device_type_mismatch" so the UI/registry can inform the user.
        """
        clean  = resp.strip().rstrip(";")
        parts  = clean.split(":")
        if not parts or not parts[0]:
            return

        detected = parts[0].upper()
        fw       = parts[1] if len(parts) > 1 else "?"
        my_key   = f"{self.__class__.__module__}.{self.__class__.__name__}"

        self.log_message.emit(
            f"[{self.DEVICE_NAME}] DeviceType={detected} FW={fw}"
        )

        # Emit generic event
        self.data_received.emit({
            "type":       "device_type",
            "identifier": detected,
            "firmware":   fw,
            "raw":        clean,
        })

        # Check for mismatch (detected identifier doesn't match this class)
        all_idents = {self.DEVICE_IDENTIFIER.upper()} | {
            a.upper() for a in self.DEVICE_IDENTIFIER_ALIASES
        }
        if detected not in all_idents:
            expected_key = _lookup_class_key_by_identifier(detected)
            log.warning(
                "[%s] DeviceType mismatch: device reports %r, "
                "expected one of %r (class=%s). Correct class: %s",
                self.DEVICE_NAME, detected, sorted(all_idents), my_key,
                expected_key or "(unknown)",
            )
            self.data_received.emit({
                "type":         "device_type_mismatch",
                "detected":     detected,
                "firmware":     fw,
                "current_key":  my_key,
                "expected_key": expected_key,
            })

    async def _detect_gatt_profile(self) -> None:
        """Try all known GATT profiles until one matches."""
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
            action = params.get("action", "level")
            value  = int(params.get("value", 0))
            cmd_map = {"in": f"Air:In:{value}", "out": f"Air:Out:{value}",
                       "level": f"Air:Level:{value}"}
            return await self._send_command_async(cmd_map.get(action, "Air:Level:0"))

        if name == "battery":
            return await self._read_battery_async()

        if name == "raw":
            return await self._send_command_async(params.get("cmd", ""))

        if name == "accelerometer":
            action = params.get("action", "start")
            cmd = "StartMove:1" if action == "start" else "StopMove:1"
            return await self._send_command_async(cmd)

        if name == "light":
            action = params.get("action", "on")
            if action == "get":
                return await self._send_command_async("GetLight")
            cmd = "Light:on" if action == "on" else "Light:off"
            return await self._send_command_async(cmd)

        if name == "alight":
            action = params.get("action", "on")
            if action == "get":
                return await self._send_command_async("GetAlight")
            cmd = "ALight:On" if action == "on" else "ALight:Off"
            return await self._send_command_async(cmd)

        raise ValueError(f"[{self.DEVICE_NAME}] Unknown command: {name!r}")

    async def _send_vibrate(self) -> str:
        """Build the correct vibrate command for single- or multi-motor devices."""
        if self.VIBRATOR_COUNT == 1:
            cmd = f"Vibrate:{self._vib_levels[0]}"
        else:
            parts = [f"Vibrate{i+1}:{l}" for i, l in enumerate(self._vib_levels)]
            for part in parts:
                await self._send_command_async(part, 0.01)
            return "OK"
        return await self._send_command_async(cmd, 0.01)

    async def _send_command_async(self, cmd: str, timeout: float = 1.0) -> str:
        if not self._client or not self._tx_char:
            raise ConnectionError("Not ready")

        self._rx_buffer = ""
        payload = f"{cmd};".encode("ascii")
        await self._client.write_gatt_char(self._tx_char, payload, response=False)

        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            if self._rx_buffer:
                resp = self._rx_buffer.strip().rstrip(";")
                self._rx_buffer = ""
                return resp
            await asyncio.sleep(0.02)

        return "OK"

    async def _read_battery_async(self) -> int:
        resp = await self._send_command_async("Battery", timeout=2.0)
        self._last_bat = time.monotonic()
        if resp.isdigit():
            level = int(resp)
            if 0 <= level <= 100:
                self._update_battery(level)
                return level
        return -1

    def _on_notification(self, sender: Any, data: bytes) -> None:
        try:
            text = data.decode("ascii", errors="ignore").strip()
        except Exception:
            return

        self._rx_buffer = text
        clean = text.rstrip(";")

        # Battery response: plain integer
        if clean.isdigit():
            level = int(clean)
            if 0 <= level <= 100:
                self._update_battery(level)
            return

        # Accelerometer frame: "G" + 12 hex chars
        if (clean.startswith("G") and len(clean) == 13
                and self.SUPPORTS_ACCELEROMETER):
            try:
                import struct
                raw = bytes.fromhex(clean[1:])
                x, y, z = struct.unpack_from("<hhh", raw)
                self.data_received.emit({
                    "type": "accelerometer",
                    "x": float(x),
                    "y": float(y),
                    "z": float(z),
                })
                return
            except (ValueError, struct.error):
                pass

        # DeviceType response: "<identifier>:<fw>:<mac...>"
        # identifier may contain letters, digits, hyphens (e.g. "EI-FW3")
        parts = clean.split(":")
        if (len(parts) >= 2
                and 1 <= len(parts[0]) <= 8
                and parts[0].replace("-", "").isalnum()
                and not parts[0].isdigit()):
            dev_ident = parts[0].upper()
            fw        = parts[1] if len(parts) > 1 else "?"
            self.log_message.emit(
                f"[{self.DEVICE_NAME}] DeviceType={dev_ident} FW={fw}"
            )
            self.data_received.emit({
                "type":       "device_type",
                "identifier": dev_ident,
                "firmware":   fw,
                "raw":        clean,
            })
            return

        self.data_received.emit({"type": "raw", "raw": clean})

    def _on_connected(self) -> None:
        from core.device_node_base import register_device_instance
        key = f"{self.__class__.__module__}.{self.__class__.__name__}"
        register_device_instance(key, self)

    # ── Convenience helpers ───────────────────────────────────────────────────

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
