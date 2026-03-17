"""
Waveform nodes — continuous time-based signal generators.

All waveforms:
  • Run continuously while the graph is active.
  • Pause/resume without phase drift (paused intervals are excluded from phase time).
  • Expose frequency, amplitude, and offset as VARIABLE_INPUTS (wire a pin or
    type a value directly on the node).

Group: Time/Waveforms
"""
from __future__ import annotations

import math
import random
import time
from PyQt6.QtCore import QRectF, Qt, QPointF
from PyQt6.QtGui  import QPainter, QColor, QFont, QPen, QPainterPath, QBrush

from core.node_base import NodeBase
from core.types     import PinDescriptor, PinDirection, PinType


_WAVE_COLOR = "#4db6ac"   # teal waveform line
_VAL_COLOR  = "#80cbc4"   # lighter teal for value text


# ─────────────────────────────────────────────────────────────────────────────
# Shared pause-aware base
# ─────────────────────────────────────────────────────────────────────────────

class _WaveformBase(NodeBase):
    """
    Adds pause-aware phase-time tracking to all waveform nodes.

    _phase_t() returns effective running time, i.e. time.monotonic() minus any
    accumulated pause duration.  on_pause/on_resume shift _wf_start so callers
    never need to subtract pause time manually.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._wf_start:       float        = 0.0
        self._wf_pause_start: float | None = None

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def on_start(self) -> None:
        self._wf_start       = time.monotonic()
        self._wf_pause_start = None

    def on_pause(self) -> None:
        self._wf_pause_start = time.monotonic()

    def on_resume(self) -> None:
        if self._wf_pause_start is not None:
            self._wf_start += time.monotonic() - self._wf_pause_start
        self._wf_pause_start = None

    # ── helpers ───────────────────────────────────────────────────────────────

    def _phase_t(self) -> float:
        """Effective running time, paused intervals excluded."""
        return time.monotonic() - self._wf_start

    def _vf(self, name: str, default: float) -> float:
        """Read a VARIABLE_INPUT as float with a fallback default."""
        v = self.get_var_input(name)
        return float(v) if v is not None else default

    # ── generic waveform preview ──────────────────────────────────────────────

    def _draw_wave_preview(
        self,
        painter:   QPainter,
        rect:      QRectF,
        sample_fn,             # (t: float) -> float
        period:    float,
        cur_val:   float,
    ) -> None:
        """
        Draw an animated waveform preview inside *rect*.

        Shows the last 2 full periods ending at the current phase time.
        The current numeric value is printed at the bottom.
        """
        N      = 100
        margin = 4
        x0 = rect.x()     + margin
        w  = rect.width()  - 2 * margin
        y0 = rect.y()      + margin
        # Leave 14 px at bottom for the numeric value label
        h  = max(1.0, rect.height() - 2 * margin - 14)

        t_cur   = self._phase_t()
        t_start = t_cur - 2 * max(1e-6, period)

        # Sample the waveform
        samples = [sample_fn(t_start + 2 * period * i / N) for i in range(N + 1)]
        v_min   = min(samples)
        v_max   = max(samples)
        v_range = max(1e-6, v_max - v_min)

        path = QPainterPath()
        for i, v in enumerate(samples):
            px = x0 + w * i / N
            py = y0 + h * (1.0 - (v - v_min) / v_range)
            if i == 0:
                path.moveTo(px, py)
            else:
                path.lineTo(px, py)

        painter.setPen(QPen(QColor(_WAVE_COLOR), 1.5))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)

        # Vertical "now" indicator at right edge
        painter.setPen(QPen(QColor("#ffffff"), 1, Qt.PenStyle.DotLine))
        painter.drawLine(QPointF(x0 + w, y0), QPointF(x0 + w, y0 + h))

        # Current value label
        painter.setPen(QColor(_VAL_COLOR))
        painter.setFont(QFont("Courier New", 8))
        painter.drawText(
            QRectF(rect.x(), rect.bottom() - 14, rect.width(), 14),
            Qt.AlignmentFlag.AlignCenter,
            f"{cur_val:.4f}",
        )


# ─────────────────────────────────────────────────────────────────────────────
# Sine Waveform
# ─────────────────────────────────────────────────────────────────────────────

class SineWaveformNode(_WaveformBase):
    """
    Continuous sine wave.
    Formula: ((sin(−π/2 + 2π·f·t) + 1) / 2) · A + O
    Default range (A=1, O=0): [0, 1]
    """
    NODE_NAME  = "Sine Waveform"
    NODE_GROUP = "Time/Waveforms"
    PINS = [
        PinDescriptor("frequency", PinDirection.INPUT,  PinType.FLOAT, optional=True),
        PinDescriptor("amplitude", PinDirection.INPUT,  PinType.FLOAT, optional=True),
        PinDescriptor("offset",    PinDirection.INPUT,  PinType.FLOAT, optional=True),
        PinDescriptor("value",     PinDirection.OUTPUT, PinType.FLOAT),
    ]
    VARIABLE_INPUTS = {
        "frequency": (float, 1.0),
        "amplitude": (float, 1.0),
        "offset":    (float, 0.0),
    }
    MIN_WIDTH  = 180.0
    MIN_HEIGHT = 110.0

    def _compute(self, t: float) -> float:
        f = max(1e-6, self._vf("frequency", 1.0))
        a = self._vf("amplitude", 1.0)
        o = self._vf("offset",    0.0)
        return ((math.sin(-math.pi / 2 + 2 * math.pi * f * t) + 1.0) / 2.0) * a + o

    def on_tick_check(self) -> None:
        self.set_output("value", self._compute(self._phase_t()))

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        t = self._phase_t()
        f = max(1e-6, self._vf("frequency", 1.0))
        self._draw_wave_preview(painter, rect, self._compute, 1.0 / f, self._compute(t))


# ─────────────────────────────────────────────────────────────────────────────
# Square (Rectangular) Waveform
# ─────────────────────────────────────────────────────────────────────────────

class SquareWaveformNode(_WaveformBase):
    """
    Square wave with configurable duty cycle.
    Active phase output: amplitude + offset.
    Inactive phase output: offset.
    """
    NODE_NAME  = "Square Waveform"
    NODE_GROUP = "Time/Waveforms"
    PINS = [
        PinDescriptor("frequency",  PinDirection.INPUT,  PinType.FLOAT, optional=True),
        PinDescriptor("amplitude",  PinDirection.INPUT,  PinType.FLOAT, optional=True),
        PinDescriptor("offset",     PinDirection.INPUT,  PinType.FLOAT, optional=True),
        PinDescriptor("duty_cycle", PinDirection.INPUT,  PinType.FLOAT, optional=True),
        PinDescriptor("value",      PinDirection.OUTPUT, PinType.FLOAT),
    ]
    VARIABLE_INPUTS = {
        "frequency":  (float, 1.0),
        "amplitude":  (float, 1.0),
        "offset":     (float, 0.0),
        "duty_cycle": (float, 0.5),
    }
    MIN_WIDTH  = 180.0
    MIN_HEIGHT = 120.0

    def _compute(self, t: float) -> float:
        f  = max(1e-6, self._vf("frequency",  1.0))
        a  = self._vf("amplitude",  1.0)
        o  = self._vf("offset",     0.0)
        dc = max(0.0, min(1.0, self._vf("duty_cycle", 0.5)))
        phase = math.fmod(t, 1.0 / f) * f   # normalised [0, 1)
        return (a + o) if phase < dc else o

    def on_tick_check(self) -> None:
        self.set_output("value", self._compute(self._phase_t()))

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        t = self._phase_t()
        f = max(1e-6, self._vf("frequency", 1.0))
        self._draw_wave_preview(painter, rect, self._compute, 1.0 / f, self._compute(t))


# ─────────────────────────────────────────────────────────────────────────────
# Sawtooth Waveform
# ─────────────────────────────────────────────────────────────────────────────

class SawtoothWaveformNode(_WaveformBase):
    """
    Sawtooth (ramp) wave.  Rising by default; set inverted=True for falling ramp.
    Raw formula (rising): fmod(f·t, 1)  →  [0, 1], then scaled to [O, A+O].
    """
    NODE_NAME  = "Sawtooth Waveform"
    NODE_GROUP = "Time/Waveforms"
    PINS = [
        PinDescriptor("frequency", PinDirection.INPUT,  PinType.FLOAT, optional=True),
        PinDescriptor("amplitude", PinDirection.INPUT,  PinType.FLOAT, optional=True),
        PinDescriptor("offset",    PinDirection.INPUT,  PinType.FLOAT, optional=True),
        PinDescriptor("value",     PinDirection.OUTPUT, PinType.FLOAT),
    ]
    VARIABLE_INPUTS = {
        "frequency": (float, 1.0),
        "amplitude": (float, 1.0),
        "offset":    (float, 0.0),
    }
    EDITABLE_FIELDS = {
        "inverted": (bool, False),
    }
    MIN_WIDTH  = 180.0
    MIN_HEIGHT = 110.0

    def _compute(self, t: float) -> float:
        f        = max(1e-6, self._vf("frequency", 1.0))
        a        = self._vf("amplitude", 1.0)
        o        = self._vf("offset",    0.0)
        inverted = bool(self.get_field("inverted"))
        raw      = math.fmod(f * t, 1.0)   # [0, 1)
        if inverted:
            raw = 1.0 - raw
        return raw * a + o

    def on_tick_check(self) -> None:
        self.set_output("value", self._compute(self._phase_t()))

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        t = self._phase_t()
        f = max(1e-6, self._vf("frequency", 1.0))
        self._draw_wave_preview(painter, rect, self._compute, 1.0 / f, self._compute(t))


# ─────────────────────────────────────────────────────────────────────────────
# Triangle Waveform
# ─────────────────────────────────────────────────────────────────────────────

class TriangleWaveformNode(_WaveformBase):
    """
    Triangle wave (symmetric rise and fall).
    Formula: 1 − |2·fmod(f·t, 1) − 1|  →  [0, 1], then scaled to [O, A+O].
    """
    NODE_NAME  = "Triangle Waveform"
    NODE_GROUP = "Time/Waveforms"
    PINS = [
        PinDescriptor("frequency", PinDirection.INPUT,  PinType.FLOAT, optional=True),
        PinDescriptor("amplitude", PinDirection.INPUT,  PinType.FLOAT, optional=True),
        PinDescriptor("offset",    PinDirection.INPUT,  PinType.FLOAT, optional=True),
        PinDescriptor("value",     PinDirection.OUTPUT, PinType.FLOAT),
    ]
    VARIABLE_INPUTS = {
        "frequency": (float, 1.0),
        "amplitude": (float, 1.0),
        "offset":    (float, 0.0),
    }
    MIN_WIDTH  = 180.0
    MIN_HEIGHT = 110.0

    def _compute(self, t: float) -> float:
        f = max(1e-6, self._vf("frequency", 1.0))
        a = self._vf("amplitude", 1.0)
        o = self._vf("offset",    0.0)
        raw = 1.0 - abs(2.0 * math.fmod(f * t, 1.0) - 1.0)   # [0, 1]
        return raw * a + o

    def on_tick_check(self) -> None:
        self.set_output("value", self._compute(self._phase_t()))

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        t = self._phase_t()
        f = max(1e-6, self._vf("frequency", 1.0))
        self._draw_wave_preview(painter, rect, self._compute, 1.0 / f, self._compute(t))


# ─────────────────────────────────────────────────────────────────────────────
# Trapezoidal Waveform
# ─────────────────────────────────────────────────────────────────────────────

class TrapezoidalWaveformNode(_WaveformBase):
    """
    Four-phase trapezoidal wave:
        ramp-up → hold-max → ramp-down → hold-min → repeat
    All phase durations in seconds; period = sum of all four phases.
    No frequency input — period is determined by the phase durations.
    """
    NODE_NAME  = "Trapezoidal Waveform"
    NODE_GROUP = "Time/Waveforms"
    PINS = [
        PinDescriptor("ramp_up_s",   PinDirection.INPUT,  PinType.FLOAT, optional=True),
        PinDescriptor("hold_max_s",  PinDirection.INPUT,  PinType.FLOAT, optional=True),
        PinDescriptor("ramp_down_s", PinDirection.INPUT,  PinType.FLOAT, optional=True),
        PinDescriptor("hold_min_s",  PinDirection.INPUT,  PinType.FLOAT, optional=True),
        PinDescriptor("amplitude",   PinDirection.INPUT,  PinType.FLOAT, optional=True),
        PinDescriptor("offset",      PinDirection.INPUT,  PinType.FLOAT, optional=True),
        PinDescriptor("value",       PinDirection.OUTPUT, PinType.FLOAT),
    ]
    VARIABLE_INPUTS = {
        "ramp_up_s":   (float, 0.25),
        "hold_max_s":  (float, 0.25),
        "ramp_down_s": (float, 0.25),
        "hold_min_s":  (float, 0.25),
        "amplitude":   (float, 1.0),
        "offset":      (float, 0.0),
    }
    MIN_WIDTH  = 200.0
    MIN_HEIGHT = 160.0

    def _phase_params(self) -> tuple[float, float, float, float, float, float]:
        ru = max(1e-4, self._vf("ramp_up_s",   0.25))
        hm = max(0.0,  self._vf("hold_max_s",  0.25))
        rd = max(1e-4, self._vf("ramp_down_s", 0.25))
        hl = max(0.0,  self._vf("hold_min_s",  0.25))
        a  = self._vf("amplitude", 1.0)
        o  = self._vf("offset",    0.0)
        return ru, hm, rd, hl, a, o

    def _compute(self, t: float) -> float:
        ru, hm, rd, hl, a, o = self._phase_params()
        period = ru + hm + rd + hl
        tp = math.fmod(t, period)
        if tp < ru:
            raw = tp / ru
        elif tp < ru + hm:
            raw = 1.0
        elif tp < ru + hm + rd:
            raw = 1.0 - (tp - ru - hm) / rd
        else:
            raw = 0.0
        return raw * a + o

    def on_tick_check(self) -> None:
        self.set_output("value", self._compute(self._phase_t()))

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        t = self._phase_t()
        ru, hm, rd, hl, _, _ = self._phase_params()
        period = ru + hm + rd + hl
        self._draw_wave_preview(painter, rect, self._compute, period, self._compute(t))


# ─────────────────────────────────────────────────────────────────────────────
# Noise Waveform
# ─────────────────────────────────────────────────────────────────────────────

class NoiseWaveformNode(_WaveformBase):
    """
    Stepped random noise updated at update_hz.
    Output: random value in [offset, offset + amplitude].
    The value holds constant between updates (sample-and-hold).
    """
    NODE_NAME  = "Noise Waveform"
    NODE_GROUP = "Time/Waveforms"
    PINS = [
        PinDescriptor("amplitude", PinDirection.INPUT,  PinType.FLOAT, optional=True),
        PinDescriptor("offset",    PinDirection.INPUT,  PinType.FLOAT, optional=True),
        PinDescriptor("update_hz", PinDirection.INPUT,  PinType.FLOAT, optional=True),
        PinDescriptor("value",     PinDirection.OUTPUT, PinType.FLOAT),
    ]
    VARIABLE_INPUTS = {
        "amplitude": (float, 1.0),
        "offset":    (float, 0.0),
        "update_hz": (float, 10.0),
    }
    MIN_WIDTH  = 180.0
    MIN_HEIGHT = 80.0

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._next_update: float = 0.0
        self._current_val: float = 0.0

    def on_start(self) -> None:
        super().on_start()
        self._next_update = 0.0
        self._current_val = 0.0

    def on_tick_check(self) -> None:
        t  = self._phase_t()
        hz = max(1e-3, self._vf("update_hz", 10.0))
        if t >= self._next_update:
            a = self._vf("amplitude", 1.0)
            o = self._vf("offset",    0.0)
            self._current_val = random.random() * a + o
            self._next_update = t + 1.0 / hz
        self.set_output("value", self._current_val)

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        v = self._current_val
        a = max(1e-6, self._vf("amplitude", 1.0))
        o = self._vf("offset", 0.0)
        pct   = max(0.0, min(1.0, (v - o) / a))
        bar_w = (rect.width() - 8) * pct
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(_WAVE_COLOR)))
        painter.drawRoundedRect(
            QRectF(rect.x() + 4, rect.y() + 4, bar_w, 8), 3, 3
        )
        painter.setPen(QColor(_VAL_COLOR))
        painter.setFont(QFont("Courier New", 8))
        painter.drawText(
            QRectF(rect.x(), rect.y() + 14, rect.width(), 18),
            Qt.AlignmentFlag.AlignCenter,
            f"{v:.4f}",
        )


# ─────────────────────────────────────────────────────────────────────────────
# Ramp Waveform
# ─────────────────────────────────────────────────────────────────────────────

class RampWaveformNode(_WaveformBase):
    """
    One-shot linear ramp from start_val to end_val over duration_s, then holds.
    Fires exec_out once when the ramp completes.
    'reset' TICK restarts the ramp from the beginning.

    The ramp begins automatically when the graph starts.
    Pause/resume preserves exact ramp position without drift.
    """
    NODE_NAME  = "Ramp Waveform"
    NODE_GROUP = "Time/Waveforms"
    PINS = [
        PinDescriptor("reset",      PinDirection.INPUT,  PinType.TICK),
        PinDescriptor("start_val",  PinDirection.INPUT,  PinType.FLOAT, optional=True),
        PinDescriptor("end_val",    PinDirection.INPUT,  PinType.FLOAT, optional=True),
        PinDescriptor("duration_s", PinDirection.INPUT,  PinType.FLOAT, optional=True),
        PinDescriptor("exec_out",   PinDirection.OUTPUT, PinType.TICK),
        PinDescriptor("value",      PinDirection.OUTPUT, PinType.FLOAT),
    ]
    VARIABLE_INPUTS = {
        "start_val":  (float, 0.0),
        "end_val":    (float, 1.0),
        "duration_s": (float, 1.0),
    }
    MIN_WIDTH  = 190.0
    MIN_HEIGHT = 110.0

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._ramp_offset: float = 0.0   # _phase_t() value when ramp last started
        self._fired:       bool  = False  # True after exec_out has fired

    def on_start(self) -> None:
        super().on_start()           # initialises _wf_start; _phase_t() → 0
        self._ramp_offset = 0.0
        self._fired       = False

    def execute(self, trigger_pin: str) -> None:
        if trigger_pin == "reset":
            self._ramp_offset = self._phase_t()
            self._fired       = False
            self.node_changed.emit()

    def on_tick_check(self) -> None:
        dur = max(1e-4, self._vf("duration_s", 1.0))
        s   = self._vf("start_val", 0.0)
        e   = self._vf("end_val",   1.0)
        elapsed = self._phase_t() - self._ramp_offset
        t = min(1.0, elapsed / dur)
        self.set_output("value", s + (e - s) * t)
        if t >= 1.0 and not self._fired:
            self.fire_tick("exec_out")
            self._fired = True
            self.node_changed.emit()

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        dur     = max(1e-4, self._vf("duration_s", 1.0))
        s       = self._vf("start_val", 0.0)
        e       = self._vf("end_val",   1.0)
        elapsed = self._phase_t() - self._ramp_offset
        pct     = min(1.0, elapsed / dur)

        bar_w    = (rect.width() - 8) * pct
        bar_rect = QRectF(rect.x() + 4, rect.y() + 4, bar_w, 8)
        painter.setPen(Qt.PenStyle.NoPen)
        color = QColor("#888888") if self._fired else QColor(_WAVE_COLOR)
        painter.setBrush(QBrush(color))
        painter.drawRoundedRect(bar_rect, 3, 3)

        cur_val = s + (e - s) * pct
        painter.setPen(QColor(_VAL_COLOR))
        painter.setFont(QFont("Courier New", 8))
        status = "done" if self._fired else f"{elapsed:.2f} / {dur:.2f} s"
        painter.drawText(
            QRectF(rect.x(), rect.y() + 14, rect.width(), 18),
            Qt.AlignmentFlag.AlignCenter,
            status,
        )
        painter.drawText(
            QRectF(rect.x(), rect.y() + 30, rect.width(), 18),
            Qt.AlignmentFlag.AlignCenter,
            f"{cur_val:.4f}  ({s:.3g} → {e:.3g})",
        )

