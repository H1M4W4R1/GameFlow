"""
DGLab devices — Coyote (郊狼) pulse host v3 and future DGLab hardware.

Coyote: BLE dual-channel estim; protocol B0/BF/B1, waveform frame from intensity+frequency.
"""
from __future__ import annotations

from devices.dglab.coyote import (
    ALL_DEVICE_CLASSES,
    ALL_NODE_CLASSES,
    CoyoteWaveformFrame,
)

__all__ = ["ALL_DEVICE_CLASSES", "ALL_NODE_CLASSES", "CoyoteWaveformFrame"]
