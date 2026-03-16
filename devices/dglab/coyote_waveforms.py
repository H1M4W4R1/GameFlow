"""
Coyote preset waveform generator nodes.

Each node outputs a CoyoteWaveformFrame every 100 ms (4 × 25 ms samples).
No exec pins — purely data-driven, same pattern as CoyoteWaveformFromInputsNode.

Waveform logic ported from:
  IRIS.Entertainment.Devices.DungeonLab.Coyote.Waveforms.Implementations

C# note: the C# GetFrequencyAt() returns a PERIOD value (1000 / freq_hz),
so each Python implementation converts back: freq_hz = 1000 / cs_period,
which simplifies to just the divisor used in C#'s (ONE_SECOND / divisor).
"""
from __future__ import annotations

import time
from typing import List

from core.types import PinDescriptor, PinDirection, PinType
from devices.dglab.coyote import (
    _CoyoteNodeBase,
    CoyoteWaveformFrame,
    FREQ_INPUT_MIN,
    FREQ_INPUT_MAX,
    WAVEFORM_FREQ_MIN,
    FRAME_SAMPLES,
    SAMPLE_INTERVAL_S,
)

# ── Helpers ───────────────────────────────────────────────────────────────────

_FRAG = 100.0  # ms per intensity-table index step (WAVEFORM_FRAGMENT_DURATION)


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _clamp01(v: float) -> float:
    return max(0.0, min(1.0, v))


# ── Base class ────────────────────────────────────────────────────────────────

class _CoyoteWaveformBaseNode(_CoyoteNodeBase):
    """
    Base for all preset waveform generator nodes.

    Subclasses override _get_intensity_at(t_ms) and _get_frequency_at(t_ms)
    where t_ms is the waveform-local time in milliseconds (loops automatically).

    The 'intensity' variable input (0–1) scales the waveform output amplitude.
    """
    NODE_GROUP = "Devices/DGLab/Coyote/Waveforms"
    PINS = [
        PinDescriptor(
            "intensity", PinDirection.INPUT, PinType.FLOAT, default=1.0,
            tooltip="Amplitude scale applied to the waveform output (0–1).",
        ),
        PinDescriptor("frame", PinDirection.OUTPUT, PinType.COYOTE_FRAME),
    ]
    VARIABLE_INPUTS = {"intensity": (float, 1.0)}

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._last_sample_time: float = 0.0
        self._samples: List[tuple[float, float]] = []
        self._waveform_time_ms: float = 0.0

    def on_start(self) -> None:
        self._last_sample_time = time.monotonic()
        self._samples = []
        self._waveform_time_ms = 0.0

    def _get_intensity_at(self, t_ms: float) -> float:
        raise NotImplementedError

    def _get_frequency_at(self, t_ms: float) -> float:
        raise NotImplementedError

    def on_tick_check(self) -> None:
        now = time.monotonic()
        if now - self._last_sample_time < SAMPLE_INTERVAL_S:
            return
        self._last_sample_time = now

        scale = _clamp01(float(self.get_var_input("intensity") or 1.0))
        intensity = _clamp01(self._get_intensity_at(self._waveform_time_ms)) * scale
        raw_freq = self._get_frequency_at(self._waveform_time_ms)
        frequency = max(float(FREQ_INPUT_MIN), min(float(FREQ_INPUT_MAX), raw_freq))

        self._waveform_time_ms += 25.0  # fixed 25 ms per sample

        self._samples.append((frequency, intensity))
        if len(self._samples) >= FRAME_SAMPLES:
            freqs = [s[0] for s in self._samples[:FRAME_SAMPLES]]
            ints  = [s[1] for s in self._samples[:FRAME_SAMPLES]]
            self._samples = []
            self.set_output("frame", CoyoteWaveformFrame(frequencies=freqs, intensities=ints))

    def execute(self, trigger_pin: str) -> None:
        pass  # data-only; driven by on_tick_check

    def on_stop(self) -> None:
        self._samples = []
        self.set_output("frame", CoyoteWaveformFrame(
            frequencies=[float(WAVEFORM_FREQ_MIN)] * FRAME_SAMPLES,
            intensities=[0.0] * FRAME_SAMPLES,
        ))

    def on_pause(self) -> None:
        self.on_stop()


# ── Waveform nodes ────────────────────────────────────────────────────────────

class CoyoteBreathWaveformNode(_CoyoteWaveformBaseNode):
    """
    Breathing pattern: gradual 8-step intensity build over 800 ms, 300 ms silence.
    Fixed frequency: 10 Hz.
    """
    NODE_NAME = "Coyote: Waveform Breath"

    _PULSE = 800.0
    _TOTAL = 1100.0
    _INT   = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0, 1.0, 1.0]

    def _get_intensity_at(self, t: float) -> float:
        t %= self._TOTAL
        if t > self._PULSE:
            return 0.0
        return self._INT[int(t / _FRAG) % len(self._INT)]

    def _get_frequency_at(self, t: float) -> float:
        return 10.0  # Hz


class CoyoteCompressWaveformNode(_CoyoteWaveformBaseNode):
    """
    Full-intensity compression with descending frequency sweep (74→26 Hz) over
    1100 ms, followed by 1000 ms at 10 Hz.
    """
    NODE_NAME = "Coyote: Waveform Compress"

    _PART_A = 1100.0
    _TOTAL  = 2100.0

    def _get_intensity_at(self, t: float) -> float:
        return 1.0

    def _get_frequency_at(self, t: float) -> float:
        t %= self._TOTAL
        if t < self._PART_A:
            return _lerp(74.0, 26.0, _clamp01(t / self._PART_A))
        return 10.0  # Hz


class CoyoteFlirtOneWaveformNode(_CoyoteWaveformBaseNode):
    """
    Two-part flirt: 4000 ms gradual build (10→30 Hz sweep) then 2200 ms
    on/off pulse at 10 Hz, with 100 ms pause.
    """
    NODE_NAME = "Coyote: Waveform Flirt 1"

    _PAUSE   = 100.0
    _PULSE_A = 4000.0
    _PULSE_B = 2200.0
    _PULSE   = 6200.0
    _TOTAL   = 6300.0
    _INT_A   = [0.0, 0.25, 0.5, 0.75, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0]
    _INT_B   = [0.0, 1.0]

    def _get_intensity_at(self, t: float) -> float:
        t %= self._TOTAL
        if t > self._PULSE:
            return 0.0
        if t < self._PULSE_A:
            return self._INT_A[int(t / _FRAG) % len(self._INT_A)]
        return self._INT_B[int((t - self._PULSE_A) / _FRAG) % len(self._INT_B)]

    def _get_frequency_at(self, t: float) -> float:
        t %= self._TOTAL
        if t > self._PULSE_A:
            return 10.0  # Hz
        pulse_time = len(self._INT_A) * _FRAG
        p = _clamp01((t % pulse_time) / pulse_time)
        return _lerp(10.0, 30.0, p)


class CoyoteFlirtTwoWaveformNode(_CoyoteWaveformBaseNode):
    """
    Extended two-part flirt: 4000 ms 11-step ramp (37→16 Hz), then 4000 ms
    on/off pulse (10→30 Hz sweep), with 200 ms pause.
    """
    NODE_NAME = "Coyote: Waveform Flirt 2"

    _PAUSE   = 200.0
    _PULSE_A = 4000.0
    _PULSE_B = 4000.0
    _PULSE   = 8000.0
    _TOTAL   = 8200.0
    _INT_A   = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
    _INT_B   = [0.0, 1.0]

    def _get_intensity_at(self, t: float) -> float:
        t %= self._TOTAL
        if t > self._PULSE:
            return 0.0
        if t < self._PULSE_A:
            return self._INT_A[int(t / _FRAG) % len(self._INT_A)]
        return self._INT_B[int((t - self._PULSE_A) / _FRAG) % len(self._INT_B)]

    def _get_frequency_at(self, t: float) -> float:
        t %= self._TOTAL
        if t > self._PULSE_A:
            p = _clamp01((t - self._PULSE_A) / self._PULSE_B)
            return _lerp(10.0, 30.0, p)
        pulse_time = len(self._INT_A) * _FRAG
        p = _clamp01((t % pulse_time) / pulse_time)
        return _lerp(37.0, 16.0, p)


class CoyoteGrainTouchWaveformNode(_CoyoteWaveformBaseNode):
    """
    Unbroken grainy texture: 2800 ms with [on, on, on, off] pattern cycling
    while frequency sweeps from 10 to 48 Hz.
    """
    NODE_NAME = "Coyote: Waveform Grain Touch"

    _PULSE = 2800.0
    _TOTAL = 2800.0
    _INT   = [1.0, 1.0, 1.0, 0.0]

    def _get_intensity_at(self, t: float) -> float:
        t %= self._TOTAL
        return self._INT[int(t / _FRAG) % len(self._INT)]

    def _get_frequency_at(self, t: float) -> float:
        t %= self._TOTAL
        return _lerp(10.0, 48.0, _clamp01(t / self._PULSE))


class CoyoteHeartbeatWaveformNode(_CoyoteWaveformBaseNode):
    """
    Double-beat heartbeat: 600 ms sharp burst at 160 Hz, then 2800 ms
    complex beat pattern at 10 Hz, with 100 ms pause.
    """
    NODE_NAME = "Coyote: Waveform Heartbeat"

    _PAUSE   = 100.0
    _PULSE_A = 600.0
    _PULSE_B = 2800.0
    _PULSE   = 3400.0
    _TOTAL   = 3500.0
    _INT_B   = [0.0, 0.0, 0.0, 0.0, 0.0, 0.75, 0.85, 0.9, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0]

    def _get_intensity_at(self, t: float) -> float:
        t %= self._TOTAL
        if t > self._PULSE:
            return 0.0
        if t < self._PULSE_A:
            return 1.0
        return self._INT_B[int((t - self._PULSE_A) / _FRAG) % len(self._INT_B)]

    def _get_frequency_at(self, t: float) -> float:
        t %= self._TOTAL
        if t < self._PULSE_A:
            return 160.0  # Hz — sharp initial burst
        return 10.0  # Hz


class CoyoteKnockWaveformNode(_CoyoteWaveformBaseNode):
    """
    Syncopated knock: 4200 ms [on×3, off×4] rhythm at 24 Hz, then 4000 ms
    sustained buzz at 160 Hz, with 200 ms pause.
    """
    NODE_NAME = "Coyote: Waveform Knock"

    _PAUSE   = 200.0
    _PULSE_A = 4200.0
    _PULSE_B = 4000.0
    _PULSE   = 8200.0
    _TOTAL   = 8400.0
    _INT_A   = [1.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0]

    def _get_intensity_at(self, t: float) -> float:
        t %= self._TOTAL
        if t > self._PULSE:
            return 0.0
        if t < self._PULSE_A:
            return self._INT_A[int(t / _FRAG) % len(self._INT_A)]
        return 1.0

    def _get_frequency_at(self, t: float) -> float:
        t %= self._TOTAL
        if t < self._PULSE_A:
            return 24.0   # Hz
        return 160.0      # Hz — high-frequency sustained buzz


class CoyoteKreepClickWaveformNode(_CoyoteWaveformBaseNode):
    """
    Creepy clicking: 800 ms [on, off, on, dim, dimmer] decay pattern at 10 Hz,
    looping continuously.
    """
    NODE_NAME = "Coyote: Waveform Kreep Click"

    _TOTAL = 800.0
    _INT   = [1.0, 0.0, 1.0, 0.65, 0.35]

    def _get_intensity_at(self, t: float) -> float:
        t %= self._TOTAL
        return self._INT[int(t / _FRAG) % len(self._INT)]

    def _get_frequency_at(self, t: float) -> float:
        return 10.0  # Hz


class CoyoteQuickPressWaveformNode(_CoyoteWaveformBaseNode):
    """
    Quick press: 4400 ms alternating [on, off] at 10 Hz, then 200 ms silence.
    """
    NODE_NAME = "Coyote: Waveform Quick Press"

    _PULSE = 4400.0
    _TOTAL = 4600.0
    _INT   = [1.0, 0.0]

    def _get_intensity_at(self, t: float) -> float:
        t %= self._TOTAL
        if t > self._PULSE:
            return 0.0
        return self._INT[int(t / _FRAG) % len(self._INT)]

    def _get_frequency_at(self, t: float) -> float:
        return 10.0  # Hz


class CoyoteRainSweptWaveformNode(_CoyoteWaveformBaseNode):
    """
    Rain sweep: 3900 ms building [0.35, 0.65, 1] at 14 Hz, then 3600 ms
    full intensity at 58 Hz, with 200 ms pause.
    """
    NODE_NAME = "Coyote: Waveform Rain Swept"

    _PAUSE   = 200.0
    _PULSE_A = 3900.0
    _PULSE_B = 3600.0
    _PULSE   = 7500.0
    _TOTAL   = 7700.0
    _INT_A   = [0.35, 0.65, 1.0]

    def _get_intensity_at(self, t: float) -> float:
        t %= self._TOTAL
        if t > self._PULSE:
            return 0.0
        if t < self._PULSE_A:
            return self._INT_A[int(t / _FRAG) % len(self._INT_A)]
        return 1.0

    def _get_frequency_at(self, t: float) -> float:
        t %= self._TOTAL
        if t < self._PULSE_A:
            return 14.0   # Hz
        return 58.0       # Hz


class CoyoteRhythmicWaveformNode(_CoyoteWaveformBaseNode):
    """
    Complex 26-step rhythmic pattern with multiple buildups and releases over
    2600 ms at 10 Hz, with 100 ms pause.
    """
    NODE_NAME = "Coyote: Waveform Rhythmic"

    _PULSE = 2600.0
    _TOTAL = 2700.0
    _INT   = [
        0.0, 0.2, 0.4, 0.6, 0.8, 1.0, 0.0, 0.25, 0.5, 0.75, 1.0,
        0.35, 0.65, 1.0, 0.0, 0.5, 1.0, 0.0, 1.0, 0.0, 1.0, 0.0,
        1.0, 0.0, 1.0, 0.0,
    ]

    def _get_intensity_at(self, t: float) -> float:
        t %= self._TOTAL
        if t > self._PULSE:
            return 0.0
        return self._INT[int(t / _FRAG) % len(self._INT)]

    def _get_frequency_at(self, t: float) -> float:
        return 10.0  # Hz


class CoyoteSignalWaveformNode(_CoyoteWaveformBaseNode):
    """
    Alert signal: 2000 ms sharp burst at 550 Hz, then 2000 ms building
    [0, 0.35, 0.65, 1] at 10→30 Hz sweep, no pause.
    """
    NODE_NAME = "Coyote: Waveform Signal"

    _PULSE_A = 2000.0
    _PULSE_B = 2000.0
    _TOTAL   = 4000.0
    _INT_B   = [0.0, 0.35, 0.65, 1.0]

    def _get_intensity_at(self, t: float) -> float:
        t %= self._TOTAL
        if t < self._PULSE_A:
            return 1.0
        return self._INT_B[int((t - self._PULSE_A) / _FRAG) % len(self._INT_B)]

    def _get_frequency_at(self, t: float) -> float:
        t %= self._TOTAL
        if t < self._PULSE_A:
            return 550.0  # Hz — high-frequency alert
        pulse_time = len(self._INT_B) * _FRAG
        p = _clamp01(((t - self._PULSE_A) % pulse_time) / pulse_time)
        return _lerp(10.0, 30.0, p)


class CoyoteSpringWaveformNode(_CoyoteWaveformBaseNode):
    """
    Spring/elastic: 4800 ms [0, 0.35, 0.65, 1] repeating buildup while
    frequency sweeps from 10 to 40 Hz, with 200 ms pause.
    """
    NODE_NAME = "Coyote: Waveform Spring"

    _PULSE = 4800.0
    _TOTAL = 5000.0
    _INT   = [0.0, 0.35, 0.65, 1.0]

    def _get_intensity_at(self, t: float) -> float:
        t %= self._TOTAL
        if t > self._PULSE:
            return 0.0
        return self._INT[int(t / _FRAG) % len(self._INT)]

    def _get_frequency_at(self, t: float) -> float:
        t %= self._TOTAL
        return _lerp(10.0, 40.0, _clamp01(t / self._PULSE))


class CoyoteStrongerWaveformNode(_CoyoteWaveformBaseNode):
    """
    Building strength: 2200 ms staggered pulses [0, 0.3, 0, 0.5, 0, 0.75,
    0, 0.85, 0, 1, 0] with increasing peaks at 10 Hz, with 100 ms pause.
    """
    NODE_NAME = "Coyote: Waveform Stronger"

    _PULSE = 2200.0
    _TOTAL = 2300.0
    _INT   = [0.0, 0.3, 0.0, 0.5, 0.0, 0.75, 0.0, 0.85, 0.0, 1.0, 0.0]

    def _get_intensity_at(self, t: float) -> float:
        t %= self._TOTAL
        if t > self._PULSE:
            return 0.0
        return self._INT[int(t / _FRAG) % len(self._INT)]

    def _get_frequency_at(self, t: float) -> float:
        return 10.0  # Hz


class CoyoteTideWaveformNode(_CoyoteWaveformBaseNode):
    """
    Tidal wave: 2200 ms smooth bell-curve [0→1→0.7] while frequency sweeps
    from 10 to 42 Hz, with 100 ms pause.
    """
    NODE_NAME = "Coyote: Waveform Tide"

    _PULSE = 2200.0
    _TOTAL = 2300.0
    _INT   = [0.0, 0.15, 0.3, 0.45, 0.65, 0.8, 1.0, 0.9, 0.85, 0.75, 0.7]

    def _get_intensity_at(self, t: float) -> float:
        t %= self._TOTAL
        if t > self._PULSE:
            return 0.0
        return self._INT[int(t / _FRAG) % len(self._INT)]

    def _get_frequency_at(self, t: float) -> float:
        t %= self._TOTAL
        return _lerp(10.0, 42.0, _clamp01(t / self._PULSE))


class CoyoteWaveRippleWaveformNode(_CoyoteWaveformBaseNode):
    """
    Wave ripple: 5600 ms [0, 0.5, 1, 0.75] pulsing cycle while frequency
    sweeps 10→110 Hz segment by segment, with 100 ms pause.
    """
    NODE_NAME = "Coyote: Waveform Wave Ripple"

    _PULSE = 5600.0
    _TOTAL = 5700.0
    _INT   = [0.0, 0.5, 1.0, 0.75]

    def _get_intensity_at(self, t: float) -> float:
        t %= self._TOTAL
        if t > self._PULSE:
            return 0.0
        return self._INT[int(t / _FRAG) % len(self._INT)]

    def _get_frequency_at(self, t: float) -> float:
        t %= self._TOTAL
        segment_time = _FRAG * len(self._INT)  # 400 ms per frequency segment
        segment_idx = int(t / segment_time)
        percentage = _clamp01(segment_idx * segment_time / self._PULSE)
        return _lerp(10.0, 110.0, percentage)


# ── Exports ───────────────────────────────────────────────────────────────────

ALL_WAVEFORM_NODE_CLASSES = [
    CoyoteBreathWaveformNode,
    CoyoteCompressWaveformNode,
    CoyoteFlirtOneWaveformNode,
    CoyoteFlirtTwoWaveformNode,
    CoyoteGrainTouchWaveformNode,
    CoyoteHeartbeatWaveformNode,
    CoyoteKnockWaveformNode,
    CoyoteKreepClickWaveformNode,
    CoyoteQuickPressWaveformNode,
    CoyoteRainSweptWaveformNode,
    CoyoteRhythmicWaveformNode,
    CoyoteSignalWaveformNode,
    CoyoteSpringWaveformNode,
    CoyoteStrongerWaveformNode,
    CoyoteTideWaveformNode,
    CoyoteWaveRippleWaveformNode,
]
