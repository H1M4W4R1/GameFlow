"""
Filter nodes — discrete-time IIR signal filters.

Design rules:
  • Pure DATA nodes — no exec_in / exec_out / TICK I/O.
  • React to incoming pin changes via on_data_received().
  • Implemented as 1st-order RC IIR approximations.
  • Filter state resets automatically when cutoff_hz changes.
  • sample_rate defaults to 100 Hz (matches the 10 ms tick loop) but
    can be overridden via an EDITABLE_FIELD.

Group: Math / Filters
"""
from __future__ import annotations

import math
import time
from typing import Any

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui  import QPainter, QColor, QFont

from core.node_base import NodeBase
from core.types     import PinDescriptor, PinDirection, PinType


# ─────────────────────────────────────────────────────────────────────────────
# Shared base
# ─────────────────────────────────────────────────────────────────────────────

class _FilterBase(NodeBase):
    """
    Base for LPF / HPF / BPF nodes.

    Subclasses must implement _filter(x: float) -> float and
    _reset_state() to clear any internal filter memory.
    """
    NODE_GROUP = "Math / Filters"
    PINS = [
        PinDescriptor("value",      PinDirection.INPUT,  PinType.FLOAT, default=0.0),
        PinDescriptor("cutoff_hz",  PinDirection.INPUT,  PinType.FLOAT, default=1.0),
        PinDescriptor("result",     PinDirection.OUTPUT, PinType.FLOAT),
    ]
    EDITABLE_FIELDS = {
        "cutoff_hz":   (float, 1.0),
        "sample_rate": (float, 100.0),
    }
    MIN_WIDTH  = 170.0
    MIN_HEIGHT = 80.0

    # ── label drawn in the node body (set by subclass) ─────────────────────
    PAINT_LABEL: str = "filter"
    PAINT_COLOR: str = "#4fc3f7"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._last_cutoff: float | None = None
        self._last_t: float = 0.0
        self._reset_state()

    # ── helpers ────────────────────────────────────────────────────────────

    def _cutoff(self) -> float:
        v = self.get_input("cutoff_hz")
        if v is None:
            v = self.get_field("cutoff_hz")
        return max(1e-6, float(v) if v is not None else 1.0)

    def _sample_rate(self) -> float:
        v = self.get_field("sample_rate")
        return max(1.0, float(v) if v is not None else 100.0)

    def _dt(self) -> float:
        return 1.0 / self._sample_rate()

    def _alpha_lpf(self) -> float:
        """RC low-pass alpha: α = dt / (RC + dt)  where RC = 1 / (2π·fc)."""
        fc = self._cutoff()
        dt = self._dt()
        rc = 1.0 / (2.0 * math.pi * fc)
        return dt / (rc + dt)

    def _maybe_reset(self) -> None:
        """Reset filter state if cutoff_hz has changed."""
        c = self._cutoff()
        if self._last_cutoff != c:
            self._last_cutoff = c
            self._reset_state()

    # ── abstract interface ─────────────────────────────────────────────────

    def _reset_state(self) -> None:
        raise NotImplementedError

    def _filter(self, x: float) -> float:
        raise NotImplementedError

    # ── NodeBase callbacks ─────────────────────────────────────────────────

    def on_start(self) -> None:
        self._reset_state()
        self._last_cutoff = None

    def on_data_received(self, pin_name: str, value: Any) -> None:
        self._maybe_reset()
        x = float(self.get_input("value") or 0.0)
        self.set_output("result", self._filter(x))

    def on_field_changed(self, name: str, value: Any) -> None:
        self._reset_state()
        self._last_cutoff = None

    # ── paint ──────────────────────────────────────────────────────────────

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        fc = self._cutoff()
        painter.setPen(QColor(self.PAINT_COLOR))
        painter.setFont(QFont("Courier New", 10, QFont.Weight.Bold))
        painter.drawText(
            QRectF(rect.x(), rect.y(), rect.width(), rect.height() * 0.55),
            Qt.AlignmentFlag.AlignCenter,
            self.PAINT_LABEL,
        )
        painter.setPen(QColor("#90a4ae"))
        painter.setFont(QFont("Courier New", 8))
        painter.drawText(
            QRectF(rect.x(), rect.y() + rect.height() * 0.55,
                   rect.width(), rect.height() * 0.45),
            Qt.AlignmentFlag.AlignCenter,
            f"fc = {fc:.3g} Hz",
        )


# ─────────────────────────────────────────────────────────────────────────────
# Low-Pass Filter  (1st-order RC IIR)
# ─────────────────────────────────────────────────────────────────────────────

class LowPassFilterNode(_FilterBase):
    """
    1st-order RC low-pass filter.

    y[n] = α · x[n] + (1 − α) · y[n−1]
    α = dt / (RC + dt),  RC = 1 / (2π · fc)

    Passes low frequencies, attenuates high frequencies above fc.
    """
    NODE_NAME    = "Low Pass Filter"
    PAINT_LABEL  = "LPF"
    PAINT_COLOR  = "#4fc3f7"   # light blue

    def _reset_state(self) -> None:
        self._y_prev: float = 0.0

    def _filter(self, x: float) -> float:
        a = self._alpha_lpf()
        self._y_prev = a * x + (1.0 - a) * self._y_prev
        return self._y_prev


# ─────────────────────────────────────────────────────────────────────────────
# High-Pass Filter  (1st-order RC IIR)
# ─────────────────────────────────────────────────────────────────────────────

class HighPassFilterNode(_FilterBase):
    """
    1st-order RC high-pass filter.

    y[n] = (1 − α) · (y[n−1] + x[n] − x[n−1])
    α = dt / (RC + dt)

    Passes high frequencies, attenuates low frequencies below fc.
    """
    NODE_NAME    = "High Pass Filter"
    PAINT_LABEL  = "HPF"
    PAINT_COLOR  = "#f48fb1"   # pink

    def _reset_state(self) -> None:
        self._x_prev: float = 0.0
        self._y_prev: float = 0.0

    def _filter(self, x: float) -> float:
        a = self._alpha_lpf()   # same α, derived from same RC
        y = (1.0 - a) * (self._y_prev + x - self._x_prev)
        self._x_prev = x
        self._y_prev = y
        return y


# ─────────────────────────────────────────────────────────────────────────────
# Band-Pass Filter  (LPF cascaded with HPF)
# ─────────────────────────────────────────────────────────────────────────────

class BandPassFilterNode(NodeBase):
    """
    1st-order band-pass filter: LPF(fc_high) cascaded with HPF(fc_low).

    Passes frequencies between fc_low and fc_high.
    Both cutoffs are connectable input pins and editable fields.
    Pure data node — no TICK I/O.
    """
    NODE_NAME  = "Band Pass Filter"
    NODE_GROUP = "Math / Filters"
    PINS = [
        PinDescriptor("value",    PinDirection.INPUT,  PinType.FLOAT, default=0.0),
        PinDescriptor("fc_low",   PinDirection.INPUT,  PinType.FLOAT, default=0.5),
        PinDescriptor("fc_high",  PinDirection.INPUT,  PinType.FLOAT, default=10.0),
        PinDescriptor("result",   PinDirection.OUTPUT, PinType.FLOAT),
    ]
    EDITABLE_FIELDS = {
        "fc_low":      (float, 0.5),
        "fc_high":     (float, 10.0),
        "sample_rate": (float, 100.0),
    }
    MIN_WIDTH  = 170.0
    MIN_HEIGHT = 90.0

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._last_fc_low:  float | None = None
        self._last_fc_high: float | None = None
        self._lpf_y: float = 0.0   # LPF stage state
        self._hpf_x: float = 0.0   # HPF stage state (prev input to HPF)
        self._hpf_y: float = 0.0   # HPF stage state (prev output)

    # ── helpers ────────────────────────────────────────────────────────────

    def _fc_low(self) -> float:
        v = self.get_input("fc_low")
        if v is None:
            v = self.get_field("fc_low")
        return max(1e-6, float(v) if v is not None else 0.5)

    def _fc_high(self) -> float:
        v = self.get_input("fc_high")
        if v is None:
            v = self.get_field("fc_high")
        return max(1e-6, float(v) if v is not None else 10.0)

    def _sample_rate(self) -> float:
        v = self.get_field("sample_rate")
        return max(1.0, float(v) if v is not None else 100.0)

    def _dt(self) -> float:
        return 1.0 / self._sample_rate()

    def _alpha(self, fc: float) -> float:
        dt = self._dt()
        rc = 1.0 / (2.0 * math.pi * fc)
        return dt / (rc + dt)

    def _reset_state(self) -> None:
        self._lpf_y = 0.0
        self._hpf_x = 0.0
        self._hpf_y = 0.0

    def _maybe_reset(self) -> None:
        fl = self._fc_low()
        fh = self._fc_high()
        if fl != self._last_fc_low or fh != self._last_fc_high:
            self._last_fc_low  = fl
            self._last_fc_high = fh
            self._reset_state()

    def _filter(self, x: float) -> float:
        fl = self._fc_low()
        fh = self._fc_high()
        # Stage 1 — LPF at fc_high (removes content above the band)
        a_h = self._alpha(fh)
        self._lpf_y = a_h * x + (1.0 - a_h) * self._lpf_y
        # Stage 2 — HPF at fc_low (removes content below the band)
        a_l = self._alpha(fl)
        y = (1.0 - a_l) * (self._hpf_y + self._lpf_y - self._hpf_x)
        self._hpf_x = self._lpf_y
        self._hpf_y = y
        return y

    # ── NodeBase callbacks ─────────────────────────────────────────────────

    def on_start(self) -> None:
        self._reset_state()
        self._last_fc_low  = None
        self._last_fc_high = None

    def on_data_received(self, pin_name: str, value: Any) -> None:
        self._maybe_reset()
        x = float(self.get_input("value") or 0.0)
        self.set_output("result", self._filter(x))

    def on_field_changed(self, name: str, value: Any) -> None:
        self._reset_state()
        self._last_fc_low  = None
        self._last_fc_high = None

    # ── paint ──────────────────────────────────────────────────────────────

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        fl = self._fc_low()
        fh = self._fc_high()
        painter.setPen(QColor("#a5d6a7"))   # soft green
        painter.setFont(QFont("Courier New", 10, QFont.Weight.Bold))
        painter.drawText(
            QRectF(rect.x(), rect.y(), rect.width(), rect.height() * 0.5),
            Qt.AlignmentFlag.AlignCenter,
            "BPF",
        )
        painter.setPen(QColor("#90a4ae"))
        painter.setFont(QFont("Courier New", 7))
        painter.drawText(
            QRectF(rect.x(), rect.y() + rect.height() * 0.5,
                   rect.width(), rect.height() * 0.5),
            Qt.AlignmentFlag.AlignCenter,
            f"{fl:.3g} – {fh:.3g} Hz",
        )
