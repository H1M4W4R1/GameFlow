"""
DGLab Coyote (郊狼) pulse host v3 — BLE dual-channel estim device.

Protocol (README_V3):
  Service 0x180C: Write 0x150A (commands), Notify 0x150B (responses).
  Service 0x180A: Read/Notify 0x1500 (battery, 1 byte).
  B0 (20 bytes): strength + waveform, send every 100ms.
  BF (7 bytes): soft limit + balance (persistent); must send after each connect.
  B1 (notify): sequence + current A/B strength.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, List, Optional

from core.device_base import DeviceBase, DeviceCommand
from core.device_node_base import DeviceNodeBase, register_device_instance
from core.types import (
    ConnectionDescriptor,
    PortKind,
    PinDescriptor,
    PinDirection,
    PinType,
)

log = logging.getLogger(__name__)

# ── GATT UUIDs (16-bit in base 0000xxxx-0000-1000-8000-00805f9b34fb) ─────────

SERVICE_CMD_UUID = "0000180c-0000-1000-8000-00805f9b34fb"
CHAR_WRITE_UUID = "0000150a-0000-1000-8000-00805f9b34fb"
CHAR_NOTIFY_UUID = "0000150b-0000-1000-8000-00805f9b34fb"
SERVICE_BATTERY_UUID = "0000180a-0000-1000-8000-00805f9b34fb"
CHAR_BATTERY_UUID = "00001500-0000-1000-8000-00805f9b34fb"

# Strength: 0–200. Waveform freq 10–240 (or map from 10–1000), intensity 0–100.
STRENGTH_MIN, STRENGTH_MAX = 0, 200
WAVEFORM_FREQ_MIN, WAVEFORM_FREQ_MAX = 10, 240
WAVEFORM_INT_MIN, WAVEFORM_INT_MAX = 0, 100
WAVEFORM_DISABLE_INT = 101

STRENGTH_NO_CHANGE = 0x00
STRENGTH_REL_PLUS = 0x01
STRENGTH_REL_MINUS = 0x02
STRENGTH_ABS = 0x03

# User-facing frequency range (maps to protocol 10–240)
FREQ_INPUT_MIN, FREQ_INPUT_MAX = 10, 1000


# ── Coyote waveform frame (custom type for graph) ──────────────────────────────

SAMPLE_INTERVAL_S = 0.025   # 25 ms per sample
FRAME_SAMPLES = 4           # 4 parts → 100 ms frame


@dataclass
class CoyoteWaveformFrame:
    """
    Waveform data for one Coyote channel over 100 ms: 4 (frequency, intensity) parts.
    Either 4-part (frequencies[4], intensities[4]) or single (frequency, intensity)
    repeated for all 4 slots. Intensities are 0–1; frequencies are device range 10–1000.
    """
    frequencies: List[float]   # length 4 (device range 10–1000)
    intensities: List[float]   # length 4 (0–1)

    def to_dict(self) -> dict[str, Any]:
        return {
            "frequencies": list(self.frequencies),
            "intensities": list(self.intensities),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CoyoteWaveformFrame":
        if "frequencies" in d and "intensities" in d:
            f = d["frequencies"]
            i = d["intensities"]
            return cls(
                frequencies=(list(f) + [10.0] * 4)[:4],
                intensities=(list(i) + [0.0] * 4)[:4],
            )
        # Backward compat: single frequency + intensity
        freq = float(d.get("frequency", 10))
        intensity = float(d.get("intensity", 0.0))
        return cls(
            frequencies=[freq] * 4,
            intensities=[intensity] * 4,
        )


def _freq_input_to_protocol(value: float) -> int:
    """
    Map user-range frequency (10–1000) to protocol waveform frequency (10–240).

    Per README V3:
        10..100  → value                       (1:1, protocol 10–100)
        101..600 → (value - 100) // 5 + 100   (protocol 100–200)
        601..1000→ (value - 600) // 10 + 200  (protocol 200–240)

    Values outside 10–1000 return WAVEFORM_FREQ_MIN (10).
    Integer division is intentional — resolution is 5 Hz per step in mid-range,
    10 Hz per step in high-range, matching the README specification exactly.
    """
    v = int(round(value))
    if v < FREQ_INPUT_MIN or v > FREQ_INPUT_MAX:
        return WAVEFORM_FREQ_MIN        # out-of-range: safe fallback
    if v <= 100:
        return v                        # 10–100  → 10–100 (1:1)
    if v <= 600:
        return (v - 100) // 5 + 100    # 101–600 → 100–200
    return (v - 600) // 10 + 200       # 601–1000→ 200–240


def _clamp_strength(v: int) -> int:
    return max(STRENGTH_MIN, min(STRENGTH_MAX, int(v)))


def _clamp_freq(v: int) -> int:
    return max(WAVEFORM_FREQ_MIN, min(WAVEFORM_FREQ_MAX, int(v)))


def _clamp_intensity(v: int) -> int:
    return max(WAVEFORM_INT_MIN, min(WAVEFORM_INT_MAX, int(v)))


def frame_to_device_format(
    frame: CoyoteWaveformFrame,
    force_silent: bool = False,
) -> tuple[List[int], List[int]]:
    """
    Convert a CoyoteWaveformFrame to (freqs[4], intensities[4]) for B0.

    force_silent=True   -- zero all intensities and put WAVEFORM_DISABLE_INT (101)
                           in slot [3] to guarantee the device discards all 4 samples.
    all-zero intensities -- also gets the disable sentinel automatically so silence
                           is explicit rather than a near-zero residual tickle.

    README: if ANY intensity value is out of valid range (> 100), the device
    discards ALL 4 samples for that channel.  We exploit slot [3] = 101 as
    the channel-disable marker when the channel should be silent.
    """
    freqs_raw = (frame.frequencies + [float(WAVEFORM_FREQ_MIN)] * 4)[:4]
    ints_raw  = (frame.intensities  + [0.0] * 4)[:4]

    freqs = [_freq_input_to_protocol(f) for f in freqs_raw]

    if force_silent:
        ints = [0, 0, 0, WAVEFORM_DISABLE_INT]
    else:
        ints = [
            int(round(max(0.0, min(1.0, float(i))) * 100.0))
            for i in ints_raw
        ]
        # Make silence explicit to avoid residual stimulation from near-zero values
        if all(v == 0 for v in ints):
            ints = [0, 0, 0, WAVEFORM_DISABLE_INT]

    return (freqs, ints)


def pack_b0(
    seq: int,
    strength_mode_a: int,
    strength_mode_b: int,
    strength_a: int,
    strength_b: int,
    freq_a: List[int],
    int_a: List[int],
    freq_b: List[int],
    int_b: List[int],
) -> bytes:
    """
    Build 20-byte B0 command. No endian conversion per V3.

    Byte 1 layout (from README):
      high nibble (bits 7-4): sequence number (0-15)
      low  nibble (bits 3-0): mode_A(bits 3-2) | mode_B(bits 1-0)

    Verified against README example:
      seq=0, mode_A=01(rel+), mode_B=00, sa=5, sb=0
      → byte1 = (0<<4)|(01<<2)|(00) = 0x04  ✓  (HEX: B00405...)
    """
    assert len(freq_a) == 4 and len(int_a) == 4 and len(freq_b) == 4 and len(int_b) == 4
    byte0 = 0xB0
    # seq in high nibble, mode_A in bits 3-2, mode_B in bits 1-0
    byte1 = ((seq & 0x0F) << 4) | ((strength_mode_a & 0x03) << 2) | (strength_mode_b & 0x03)
    return bytes([
        byte0, byte1,
        strength_a & 0xFF, strength_b & 0xFF,
        *[f & 0xFF for f in freq_a],
        *[i & 0xFF for i in int_a],
        *[f & 0xFF for f in freq_b],
        *[i & 0xFF for i in int_b],
    ])


def pack_bf(
    soft_limit_a: int,
    soft_limit_b: int,
    freq_balance_a: int,
    freq_balance_b: int,
    int_balance_a: int,
    int_balance_b: int,
) -> bytes:
    """Build 7-byte BF command. Values: soft limit 0–200, balance 0–255."""
    return bytes([
        0xBF,
        _clamp_strength(soft_limit_a) & 0xFF,
        _clamp_strength(soft_limit_b) & 0xFF,
        max(0, min(255, freq_balance_a)) & 0xFF,
        max(0, min(255, freq_balance_b)) & 0xFF,
        max(0, min(255, int_balance_a)) & 0xFF,
        max(0, min(255, int_balance_b)) & 0xFF,
    ])


def parse_b1(data: bytes) -> Optional[tuple[int, int, int]]:
    """Parse B1 notify: (seq, strength_a, strength_b)."""
    if len(data) < 4 or data[0] != 0xB1:
        return None
    return (data[1], data[2], data[3])


# ── Device ──────────────────────────────────────────────────────────────────

DEVICE_TYPE_KEY = "devices.dglab.coyote.Coyote"


class Coyote(DeviceBase):
    """
    DGLab Coyote pulse host v3 — dual-channel estim over BLE.

    ConnectionDescriptor:
        kind    = PortKind.BLE
        address = "AA:BB:CC:DD:EE:FF" or from BLE scan
    """

    DEVICE_NAME = "Coyote"
    DEVICE_VERSION = "3.0.0"
    MANUFACTURER = "DGLab"
    DEVICE_DESCRIPTION = "Dual-channel estim pulse host (v3 BLE)"
    CONNECTION_KINDS = [PortKind.BLE]
    ICON_PATH = "assets/icons/dglab/coyote.svg"
    BLE_SERVICE_UUID = SERVICE_CMD_UUID
    # BLE advertisement name prefixes (per README: "47L121000" for pulse host)
    BLE_NAME_PREFIXES = ("47L",)
    DEVICE_URL = "https://dungeon-lab.com/e-stim-unit3.0.php"

    def __init__(self, descriptor: ConnectionDescriptor, **kwargs) -> None:
        super().__init__(descriptor, **kwargs)
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._client: Any = None
        self._stop_timer: asyncio.Event = asyncio.Event()
        self._strength_a: int = 0
        self._strength_b: int = 0
        self._waveform_a_freq: List[int] = [10, 10, 10, 10]
        self._waveform_a_int: List[int] = [0, 0, 0, WAVEFORM_DISABLE_INT]
        self._waveform_b_freq: List[int] = [10, 10, 10, 10]
        self._waveform_b_int: List[int] = [0, 0, 0, WAVEFORM_DISABLE_INT]
        self._soft_limit_a: int = 200
        self._soft_limit_b: int = 200
        self._freq_balance_a: int = 128
        self._freq_balance_b: int = 128
        self._int_balance_a: int = 128
        self._int_balance_b: int = 128
        self._pending_strength_a: Optional[int] = None
        self._pending_strength_b: Optional[int] = None
        self._seq: int = 0
        # Per-channel ack gating (README: wait for B1 ack before next strength change)
        self._input_allowed_a: bool = True
        self._input_allowed_b: bool = True
        self._last_seq_a: int = 0
        self._last_seq_b: int = 0
        # Output gate: when False, B0 loop sends disable-sentinel intensities
        self._gate_open: bool = True

    def _open(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._stop_timer = asyncio.Event()
        t = threading.Thread(
            target=self._loop.run_forever,
            daemon=True,
            name=f"{self.DEVICE_NAME}-loop",
        )
        t.start()
        future = asyncio.run_coroutine_threadsafe(
            self._async_connect(), self._loop
        )
        future.result(timeout=20)

    async def _async_connect(self) -> None:
        from bleak import BleakClient
        self._client = BleakClient(self.descriptor.address)
        await self._client.connect()
        await self._client.start_notify(CHAR_NOTIFY_UUID, self._on_notify)
        try:
            await self._client.start_notify(
                CHAR_BATTERY_UUID, self._on_battery_notify
            )
        except Exception:
            pass
        try:
            bat = await self._client.read_gatt_char(CHAR_BATTERY_UUID)
            if len(bat) >= 1:
                self._update_battery(bat[0] & 0xFF)
        except Exception:
            pass
        await self._write_char(
            pack_bf(
                self._soft_limit_a,
                self._soft_limit_b,
                self._freq_balance_a,
                self._freq_balance_b,
                self._int_balance_a,
                self._int_balance_b,
            )
        )
        asyncio.ensure_future(self._b0_loop(), loop=self._loop)

    def _on_notify(self, _sender: Any, data: bytes) -> None:
        if len(data) < 1:
            return
        if data[0] == 0xB1:
            parsed = parse_b1(data)
            if parsed:
                _seq, sa, sb = parsed
                self._strength_a = sa
                self._strength_b = sb
                # Release ack gate for the channel that was acknowledged
                if _seq != 0:
                    if _seq == self._last_seq_a:
                        self._input_allowed_a = True
                    if _seq == self._last_seq_b:
                        self._input_allowed_b = True
                else:
                    # seq=0 means hardware-triggered change (wheel), always release
                    self._input_allowed_a = True
                    self._input_allowed_b = True
                self.data_received.emit({
                    "type": "strength",
                    "strength_a": sa,
                    "strength_b": sb,
                    "seq": _seq,
                })

    def _on_battery_notify(self, _sender: Any, data: bytes) -> None:
        if data:
            self._update_battery(data[0] & 0xFF)

    async def _b0_loop(self) -> None:
        while (
            not self._stop_timer.is_set()
            and self._client
            and self._client.is_connected
        ):
            try:
                mode_a = STRENGTH_NO_CHANGE
                mode_b = STRENGTH_NO_CHANGE
                sa, sb = self._strength_a, self._strength_b
                if self._pending_strength_a is not None:
                    mode_a = STRENGTH_ABS
                    sa = _clamp_strength(self._pending_strength_a)
                    self._pending_strength_a = None
                if self._pending_strength_b is not None:
                    mode_b = STRENGTH_ABS
                    sb = _clamp_strength(self._pending_strength_b)
                    self._pending_strength_b = None
                # Gate: when closed, override intensities with disable sentinel
                _int_a = self._waveform_a_int if self._gate_open else [0, 0, 0, WAVEFORM_DISABLE_INT]
                _int_b = self._waveform_b_int if self._gate_open else [0, 0, 0, WAVEFORM_DISABLE_INT]
                payload = pack_b0(
                    self._seq & 0x0F,
                    mode_a,
                    mode_b,
                    sa,
                    sb,
                    self._waveform_a_freq,
                    _int_a,
                    self._waveform_b_freq,
                    _int_b,
                )
                await self._write_char(payload)
                if mode_a != STRENGTH_NO_CHANGE or mode_b != STRENGTH_NO_CHANGE:
                    self._seq = (self._seq % 15) + 1  # 1–15; 0 reserved for no-ack
                self._strength_a, self._strength_b = sa, sb
            except Exception as e:
                log.debug("[Coyote] B0 loop write error: %s", e)
            await asyncio.sleep(0.1)

    async def _write_char(self, payload: bytes) -> None:
        if not self._client:
            raise ConnectionError("Not connected")
        await self._client.write_gatt_char(
            CHAR_WRITE_UUID, payload, response=False
        )

    def _close(self) -> None:
        self._stop_timer.set()
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
            log.debug("[Coyote] Disconnect error: %s", e)

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

    async def _dispatch_command(self, command: DeviceCommand) -> Any:
        name = command.name
        params = command.params

        if name == "set_strength_a":
            v = _clamp_strength(params.get("value", 0))
            self._pending_strength_a = v
            return v

        if name == "set_strength_b":
            v = _clamp_strength(params.get("value", 0))
            self._pending_strength_b = v
            return v

        if name == "set_strength_both":
            a = _clamp_strength(params.get("value_a", 0))
            b = _clamp_strength(params.get("value_b", 0))
            self._pending_strength_a = a
            self._pending_strength_b = b
            return (a, b)

        if name == "set_waveform_a":
            freqs = params.get("freqs", [10, 10, 10, 10])
            ints = params.get("intensities", [0, 0, 0, 0])
            self._waveform_a_freq = [
                _clamp_freq(f) for f in (freqs + [10] * 4)[:4]
            ]
            self._waveform_a_int = [
                _clamp_intensity(i) for i in (ints + [0] * 4)[:4]
            ]
            return True

        if name == "set_waveform_b":
            freqs = params.get("freqs", [10, 10, 10, 10])
            ints = params.get("intensities", [0, 0, 0, 0])
            self._waveform_b_freq = [
                _clamp_freq(f) for f in (freqs + [10] * 4)[:4]
            ]
            self._waveform_b_int = [
                _clamp_intensity(i) for i in (ints + [0] * 4)[:4]
            ]
            return True

        if name == "set_soft_limit":
            self._soft_limit_a = _clamp_strength(params.get("limit_a", 200))
            self._soft_limit_b = _clamp_strength(params.get("limit_b", 200))
            self._freq_balance_a = max(
                0, min(255, int(params.get("freq_balance_a", 128)))
            )
            self._freq_balance_b = max(
                0, min(255, int(params.get("freq_balance_b", 128)))
            )
            self._int_balance_a = max(
                0, min(255, int(params.get("int_balance_a", 128)))
            )
            self._int_balance_b = max(
                0, min(255, int(params.get("int_balance_b", 128)))
            )
            if self._client and self._client.is_connected:
                await self._write_char(
                    pack_bf(
                        self._soft_limit_a,
                        self._soft_limit_b,
                        self._freq_balance_a,
                        self._freq_balance_b,
                        self._int_balance_a,
                        self._int_balance_b,
                    )
                )
            return True

        if name == "set_output_gate":
            # enabled=True  → open gate (waveform flows through)
            # enabled=False → close gate (disable sentinel sent until re-enabled)
            self._gate_open = bool(params.get("enabled", True))
            return self._gate_open

        if name == "stop":
            self._pending_strength_a = 0
            self._pending_strength_b = 0
            self._waveform_a_int = [0, 0, 0, WAVEFORM_DISABLE_INT]
            self._waveform_b_int = [0, 0, 0, WAVEFORM_DISABLE_INT]
            self._gate_open = True   # reset gate so next enable works cleanly
            return True

        if name == "get_battery":
            if self._client:
                data = await self._client.read_gatt_char(CHAR_BATTERY_UUID)
                level = data[0] & 0xFF if data else -1
                self._update_battery(level)
                return level
            return -1

        if name == "get_strength":
            return {
                "strength_a": self._strength_a,
                "strength_b": self._strength_b,
            }

        raise ValueError(f"[{self.DEVICE_NAME}] Unknown command: {name!r}")

    def _on_connected(self) -> None:
        register_device_instance(DEVICE_TYPE_KEY, self)

    def get_node_types(self) -> list[str]:
        return [
            f"{__name__}.CoyoteWaveformFromInputsNode",
            f"{__name__}.CoyoteSetWaveformANode",
            f"{__name__}.CoyoteSetWaveformBNode",
            f"{__name__}.CoyoteSetStrengthANode",
            f"{__name__}.CoyoteSetStrengthBNode",
            f"{__name__}.CoyoteSetStrengthBothNode",
            f"{__name__}.CoyoteSetSoftLimitNode",
            f"{__name__}.CoyoteStopNode",
            f"{__name__}.CoyoteGetBatteryNode",
            f"{__name__}.CoyoteGetStrengthNode",
        ]


# ── Nodes ───────────────────────────────────────────────────────────────────

class _CoyoteNodeBase(DeviceNodeBase):
    DEVICE_TYPE_KEY = DEVICE_TYPE_KEY
    ICON_PATH = "assets/icons/dglab/coyote.svg"
    NODE_GROUP = "Devices/DGLab/Coyote"




class CoyoteWaveformFromInputsNode(_CoyoteNodeBase):
    """
    Data-only node: samples intensity (0–1) and frequency (10–1000) every 25 ms
    and outputs a 4-part CoyoteWaveformFrame every 100 ms, ready for Set Waveform nodes.
    Uses on_tick_check (runtime calls every 10 ms); no exec pins.
    """
    NODE_NAME = "Coyote: Build Waveform"
    PINS = [
        PinDescriptor("intensity", PinDirection.INPUT, PinType.FLOAT, default=0.0),
        PinDescriptor("frequency", PinDirection.INPUT, PinType.FLOAT, default=10.0),
        PinDescriptor("frame", PinDirection.OUTPUT, PinType.COYOTE_FRAME),
    ]
    VARIABLE_INPUTS = {"intensity": (float, 0.0), "frequency": (float, 10.0)}

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._last_sample_time: float = 0.0
        self._samples: List[tuple[float, float]] = []  # (frequency, intensity)

    def on_start(self) -> None:
        self._last_sample_time = time.monotonic()
        self._samples = []

    def on_tick_check(self) -> None:
        now = time.monotonic()
        if now - self._last_sample_time < SAMPLE_INTERVAL_S:
            return
        self._last_sample_time = now
        intensity = float(self.get_var_input("intensity") or 0.0)
        intensity = max(0.0, min(1.0, intensity))
        frequency = float(self.get_var_input("frequency") or 10.0)
        frequency = max(FREQ_INPUT_MIN, min(FREQ_INPUT_MAX, frequency))
        self._samples.append((frequency, intensity))
        if len(self._samples) >= FRAME_SAMPLES:
            freqs = [s[0] for s in self._samples[:FRAME_SAMPLES]]
            ints = [s[1] for s in self._samples[:FRAME_SAMPLES]]
            self._samples = []
            frame = CoyoteWaveformFrame(frequencies=freqs, intensities=ints)
            self.set_output("frame", frame)

    def execute(self, trigger_pin: str) -> None:
        pass  # Data-only; driven by on_tick_check

    def on_stop(self) -> None:
        """Zero the output frame when the graph stops so downstream nodes get clean state."""
        self._samples = []
        silent = CoyoteWaveformFrame(
            frequencies=[float(WAVEFORM_FREQ_MIN)] * FRAME_SAMPLES,
            intensities=[0.0] * FRAME_SAMPLES,
        )
        self.set_output("frame", silent)

    def on_pause(self) -> None:
        self.on_stop()  # same action: emit a zero frame



class CoyoteSetWaveformANode(_CoyoteNodeBase):
    """
    Sends the connected CoyoteWaveformFrame to channel A every 100 ms.
    Data-only: no exec pins; uses on_tick_check to sample and send frame.
    """
    NODE_NAME = "Coyote: Set waveform A"
    PINS = [
        PinDescriptor("frame", PinDirection.INPUT, PinType.COYOTE_FRAME),
    ]

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._last_send_time: float = 0.0

    def on_start(self) -> None:
        self._last_send_time = time.monotonic()

    def on_tick_check(self) -> None:
        now = time.monotonic()
        if now - self._last_send_time < 0.1:  # 100 ms
            return
        self._last_send_time = now
        dev = self.get_device()
        if not dev:
            return
        raw = self.get_input("frame")
        if raw is None:
            return
        if isinstance(raw, dict):
            frame = CoyoteWaveformFrame.from_dict(raw)
        elif isinstance(raw, CoyoteWaveformFrame):
            frame = raw
        else:
            return
        freqs, ints = frame_to_device_format(frame)
        self.send_to_device("set_waveform_a", {"freqs": freqs, "intensities": ints})

    def execute(self, trigger_pin: str) -> None:
        pass  # Data-only; driven by on_tick_check

    def _silence(self) -> None:
        """Send a zero-intensity waveform to silence channel A immediately."""
        dev = self.get_device()
        if not dev:
            return
        silent_frame = CoyoteWaveformFrame(
            frequencies=[float(WAVEFORM_FREQ_MIN)] * FRAME_SAMPLES,
            intensities=[0.0] * FRAME_SAMPLES,
        )
        freqs, ints = frame_to_device_format(silent_frame, force_silent=True)
        self.send_to_device("set_waveform_a", {"freqs": freqs, "intensities": ints})

    def on_stop(self) -> None:
        self._silence()

    def on_pause(self) -> None:
        self._silence()



class CoyoteSetWaveformBNode(_CoyoteNodeBase):
    """
    Sends the connected CoyoteWaveformFrame to channel B every 100 ms.
    Data-only: no exec pins; uses on_tick_check to sample and send frame.
    """
    NODE_NAME = "Coyote: Set waveform B"
    PINS = [
        PinDescriptor("frame", PinDirection.INPUT, PinType.COYOTE_FRAME),
    ]

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._last_send_time: float = 0.0

    def on_start(self) -> None:
        self._last_send_time = time.monotonic()

    def on_tick_check(self) -> None:
        now = time.monotonic()
        if now - self._last_send_time < 0.1:  # 100 ms
            return
        self._last_send_time = now
        dev = self.get_device()
        if not dev:
            return
        raw = self.get_input("frame")
        if raw is None:
            return
        if isinstance(raw, dict):
            frame = CoyoteWaveformFrame.from_dict(raw)
        elif isinstance(raw, CoyoteWaveformFrame):
            frame = raw
        else:
            return
        freqs, ints = frame_to_device_format(frame)
        self.send_to_device("set_waveform_b", {"freqs": freqs, "intensities": ints})

    def execute(self, trigger_pin: str) -> None:
        pass  # Data-only; driven by on_tick_check

    def _silence(self) -> None:
        """Send a zero-intensity waveform to silence channel B immediately."""
        dev = self.get_device()
        if not dev:
            return
        silent_frame = CoyoteWaveformFrame(
            frequencies=[float(WAVEFORM_FREQ_MIN)] * FRAME_SAMPLES,
            intensities=[0.0] * FRAME_SAMPLES,
        )
        freqs, ints = frame_to_device_format(silent_frame, force_silent=True)
        self.send_to_device("set_waveform_b", {"freqs": freqs, "intensities": ints})

    def on_stop(self) -> None:
        self._silence()

    def on_pause(self) -> None:
        self._silence()



class CoyoteSetStrengthANode(_CoyoteNodeBase):
    NODE_NAME = "Coyote: Set strength A"
    PINS = [
        PinDescriptor("exec_in", PinDirection.INPUT, PinType.TICK),
        PinDescriptor("exec_out", PinDirection.OUTPUT, PinType.TICK),
        PinDescriptor("value", PinDirection.INPUT, PinType.INT, default=0),
    ]
    VARIABLE_INPUTS = {"value": (int, 0)}

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._last_value: int = 0

    def execute(self, trigger_pin: str) -> None:
        dev = self.get_device()
        if not dev:
            self.fire_tick("exec_out")
            return
        v = int(self.get_var_input("value") or 0)
        self._last_value = v
        self.send_to_device(
            "set_strength_a",
            {"value": v},
            on_success=lambda _: self.fire_tick("exec_out"),
        )

    def on_stop(self) -> None:
        dev = self.get_device()
        if dev:
            self.send_to_device("set_strength_a", {"value": 0})

    def on_pause(self) -> None:
        self.on_stop()

    def on_resume(self) -> None:
        dev = self.get_device()
        if dev and self._last_value > 0:
            self.send_to_device("set_strength_a", {"value": self._last_value})


class CoyoteSetStrengthBNode(_CoyoteNodeBase):
    NODE_NAME = "Coyote: Set strength B"
    PINS = [
        PinDescriptor("exec_in", PinDirection.INPUT, PinType.TICK),
        PinDescriptor("value", PinDirection.INPUT, PinType.INT, default=0),
        PinDescriptor("exec_out", PinDirection.OUTPUT, PinType.TICK),
    ]
    VARIABLE_INPUTS = {"value": (int, 0)}

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._last_value: int = 0

    def execute(self, trigger_pin: str) -> None:
        dev = self.get_device()
        if not dev:
            self.fire_tick("exec_out")
            return
        v = int(self.get_var_input("value") or 0)
        self._last_value = v
        self.send_to_device(
            "set_strength_b",
            {"value": v},
            on_success=lambda _: self.fire_tick("exec_out"),
        )

    def on_stop(self) -> None:
        dev = self.get_device()
        if dev:
            self.send_to_device("set_strength_b", {"value": 0})

    def on_pause(self) -> None:
        self.on_stop()

    def on_resume(self) -> None:
        dev = self.get_device()
        if dev and self._last_value > 0:
            self.send_to_device("set_strength_b", {"value": self._last_value})


class CoyoteSetStrengthBothNode(_CoyoteNodeBase):
    NODE_NAME = "Coyote: Set strength A and B"
    PINS = [
        PinDescriptor("exec_in", PinDirection.INPUT, PinType.TICK),
        PinDescriptor("value_a", PinDirection.INPUT, PinType.INT, default=0),
        PinDescriptor("value_b", PinDirection.INPUT, PinType.INT, default=0),
        PinDescriptor("exec_out", PinDirection.OUTPUT, PinType.TICK),
    ]
    VARIABLE_INPUTS = {"value_a": (int, 0), "value_b": (int, 0)}

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._last_a: int = 0
        self._last_b: int = 0

    def execute(self, trigger_pin: str) -> None:
        dev = self.get_device()
        if not dev:
            self.fire_tick("exec_out")
            return
        a = int(self.get_var_input("value_a") or 0)
        b = int(self.get_var_input("value_b") or 0)
        self._last_a = a
        self._last_b = b
        self.send_to_device(
            "set_strength_both",
            {"value_a": a, "value_b": b},
            on_success=lambda _: self.fire_tick("exec_out"),
        )

    def on_stop(self) -> None:
        dev = self.get_device()
        if dev:
            self.send_to_device("set_strength_both", {"value_a": 0, "value_b": 0})

    def on_pause(self) -> None:
        self.on_stop()

    def on_resume(self) -> None:
        dev = self.get_device()
        if dev and (self._last_a > 0 or self._last_b > 0):
            self.send_to_device("set_strength_both", {"value_a": self._last_a, "value_b": self._last_b})


class CoyoteSetSoftLimitNode(_CoyoteNodeBase):
    NODE_NAME = "Coyote: Set soft limit (BF)"
    PINS = [
        PinDescriptor("exec_in", PinDirection.INPUT, PinType.TICK),
        PinDescriptor("limit_a", PinDirection.INPUT, PinType.INT, default=200),
        PinDescriptor("limit_b", PinDirection.INPUT, PinType.INT, default=200),
        PinDescriptor("exec_out", PinDirection.OUTPUT, PinType.TICK),
    ]
    VARIABLE_INPUTS = {"limit_a": (int, 200), "limit_b": (int, 200)}

    def execute(self, trigger_pin: str) -> None:
        dev = self.get_device()
        if not dev:
            self.fire_tick("exec_out")
            return
        a = int(self.get_var_input("limit_a") or 200)
        b = int(self.get_var_input("limit_b") or 200)
        self.send_to_device(
            "set_soft_limit",
            {"limit_a": a, "limit_b": b},
            on_success=lambda _: self.fire_tick("exec_out"),
        )


class CoyoteStopNode(_CoyoteNodeBase):
    NODE_NAME = "Coyote: Stop"
    PINS = [
        PinDescriptor("exec_in", PinDirection.INPUT, PinType.TICK),
        PinDescriptor("exec_out", PinDirection.OUTPUT, PinType.TICK),
    ]

    def execute(self, trigger_pin: str) -> None:
        dev = self.get_device()
        if dev:
            self.send_to_device(
                "stop", {}, on_success=lambda _: self.fire_tick("exec_out")
            )
        else:
            self.fire_tick("exec_out")


class CoyoteGetBatteryNode(_CoyoteNodeBase):
    NODE_NAME = "Coyote: Get battery"
    PINS = [
        PinDescriptor("exec_in", PinDirection.INPUT, PinType.TICK),
        PinDescriptor("exec_out", PinDirection.OUTPUT, PinType.TICK),
        PinDescriptor("level", PinDirection.OUTPUT, PinType.INT),
    ]

    def execute(self, trigger_pin: str) -> None:
        dev = self.get_device()
        if not dev:
            self.set_output("level", -1)
            self.fire_tick("exec_out")
            return

        def done(level: int) -> None:
            self.set_output("level", level)
            self.fire_tick("exec_out")

        def fail(_: Exception) -> None:
            self.set_output("level", -1)
            self.fire_tick("exec_out")

        dev.send_command("get_battery", {}, on_success=done, on_failure=fail)


class CoyoteGetStrengthNode(_CoyoteNodeBase):
    NODE_NAME = "Coyote: Get strength"
    PINS = [
        PinDescriptor("exec_in", PinDirection.INPUT, PinType.TICK),
        PinDescriptor("exec_out", PinDirection.OUTPUT, PinType.TICK),
        PinDescriptor("strength_a", PinDirection.OUTPUT, PinType.INT),
        PinDescriptor("strength_b", PinDirection.OUTPUT, PinType.INT),
    ]

    def execute(self, trigger_pin: str) -> None:
        dev = self.get_device()
        if not dev:
            self.set_output("strength_a", 0)
            self.set_output("strength_b", 0)
            self.fire_tick("exec_out")
            return

        def done(result: dict) -> None:
            self.set_output("strength_a", result.get("strength_a", 0))
            self.set_output("strength_b", result.get("strength_b", 0))
            self.fire_tick("exec_out")

        def fail(_: Exception) -> None:
            self.set_output("strength_a", 0)
            self.set_output("strength_b", 0)
            self.fire_tick("exec_out")

        dev.send_command(
            "get_strength", {}, on_success=done, on_failure=fail
        )


class CoyoteOutputGateNode(_CoyoteNodeBase):
    """
    Output gate — enables or disables Coyote stimulation output on each TICK.

    When 'enabled' is True  (or >0):  the output gate is opened; the B0 loop
                                       sends waveform intensities normally.
    When 'enabled' is False (or 0):   the output gate is closed; the B0 loop
                                       sends the disable-sentinel ([0,0,0,101])
                                       for both channels every 100 ms until
                                       the gate is opened again.

    The gate does NOT modify or reset the stored waveform/strength state —
    re-enabling immediately resumes from wherever the waveform nodes left off.

    'enabled' can be:
      • Wired from a Bool output (e.g. a Condition node, a toggle)
      • Set via the inline VARIABLE_INPUT field (double-click the row)
      • Left unwired to act as a manual on/off triggered by exec_in ticks

    Typical usage:
        Timer → CoyoteOutputGate(enabled=true)  → enable output for N seconds
        Timer → CoyoteOutputGate(enabled=false) → disable output for N seconds
    """
    NODE_NAME = "Coyote: Enable/Disable"
    MIN_WIDTH = 200.0
    PINS = [
        PinDescriptor("exec_in",  PinDirection.INPUT,  PinType.TICK,
                      tooltip="Fire to apply the current 'enabled' value to the output gate."),
        PinDescriptor("enabled",  PinDirection.INPUT,  PinType.BOOL, optional=True,
                      tooltip="True = output on, False = output silenced. "
                              "Can be wired from any Bool source."),
        PinDescriptor("exec_out", PinDirection.OUTPUT, PinType.TICK,
                      tooltip="Fires after the gate state has been applied."),
    ]
    VARIABLE_INPUTS = {
        "enabled": (bool, True),
    }
    EDITABLE_FIELDS = {}

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._gate_state: bool = True   # last known gate state (for display)

    def execute(self, trigger_pin: str) -> None:
        enabled = bool(self.get_var_input("enabled"))
        dev = self.get_device()
        if dev:
            self._gate_state = enabled
            self.send_to_device(
                "set_output_gate",
                {"enabled": enabled},
                on_success=lambda _: self.fire_tick("exec_out"),
            )
        else:
            self.fire_tick("exec_out")
        self.node_changed.emit()

    def paint_custom(self, painter, rect) -> None:
        from PyQt6.QtGui import QColor, QFont
        from PyQt6.QtCore import Qt
        enabled = bool(self.get_var_input("enabled"))
        if enabled:
            color = QColor("#4caf50")
            label = "OUTPUT  ON"
        else:
            color = QColor("#ef5350")
            label = "OUTPUT  OFF"
        painter.setPen(color)
        painter.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)


# ── Exports ─────────────────────────────────────────────────────────────────

ALL_DEVICE_CLASSES = [Coyote]

from devices.dglab.coyote_waveforms import ALL_WAVEFORM_NODE_CLASSES

ALL_NODE_CLASSES = [
    CoyoteWaveformFromInputsNode,
    CoyoteSetWaveformANode,
    CoyoteSetWaveformBNode,
    CoyoteSetStrengthANode,
    CoyoteSetStrengthBNode,
    CoyoteSetStrengthBothNode,
    CoyoteSetSoftLimitNode,
    CoyoteOutputGateNode,
    CoyoteStopNode,
    CoyoteGetBatteryNode,
    CoyoteGetStrengthNode,
    *ALL_WAVEFORM_NODE_CLASSES,
]
