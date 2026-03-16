"""
Lovense multi-feature devices.

  LovenseEdge  — prostate massager: 2 independent vibrators
                 Motor 0: Internal (insertable tip)
                 Motor 1: Perineum (external pad)

  LovenseDiamo — cock ring: 1 vibrator

  LovenseMax   — male masturbator: 1 vibrator + air pump (inflate/deflate)

  LovenseNora  — rabbit vibrator: 1 vibrator + 1 rotating head
"""
from __future__ import annotations

from typing import Any

from core.device_node_base import DeviceNodeBase
from core.types import PinDescriptor, PinDirection, PinType
from devices.lovense._base import _LovenseBLEBase, VIBRATE_MAX
from devices.lovense.vibrators import _make_stop_node

MANUFACTURER = "Lovense"


# ─────────────────────────────────────────────────────────────────────────────
# Edge — dual vibrator prostate massager
# ─────────────────────────────────────────────────────────────────────────────

class LovenseEdge(_LovenseBLEBase):
    DEVICE_NAME        = "Edge"
    DEVICE_DESCRIPTION = "Dual-motor prostate massager"
    DEVICE_IDENTIFIER  = "P"
    VIBRATOR_COUNT     = 2
    VIBRATOR_NAMES     = ["Vibrate Internal", "Vibrate Perineum"]
    ICON_PATH          = "assets/icons/lovense/edge.svg"


class EdgeVibrateInternal(DeviceNodeBase):
    """Vibrate the insertable internal tip of the Edge."""
    NODE_NAME       = "Edge: Vibrate Internal"
    NODE_GROUP      = "Devices/Lovense/Edge"
    DEVICE_TYPE_KEY = f"{LovenseEdge.__module__}.LovenseEdge"
    ICON_PATH       = LovenseEdge.ICON_PATH
    PINS = [
        PinDescriptor("exec_in",   PinDirection.INPUT,  PinType.TICK),
        PinDescriptor("intensity", PinDirection.INPUT,  PinType.FLOAT, optional=True),
        PinDescriptor("exec_out",  PinDirection.OUTPUT, PinType.TICK),
    ]
    VARIABLE_INPUTS = {"intensity": (float, 0.5)}

    def execute(self, trigger_pin: str) -> None:
        dev = self.get_device()
        if dev:
            dev.vibrate(0, float(self.get_var_input("intensity") or 0.0),
                        on_success=lambda _: self.fire_tick("exec_out"))
        else:
            self.fire_tick("exec_out")


class EdgeVibratePerineum(DeviceNodeBase):
    """Vibrate the external perineum pad of the Edge."""
    NODE_NAME       = "Edge: Vibrate Perineum"
    NODE_GROUP      = "Devices/Lovense/Edge"
    DEVICE_TYPE_KEY = f"{LovenseEdge.__module__}.LovenseEdge"
    ICON_PATH       = LovenseEdge.ICON_PATH
    PINS = [
        PinDescriptor("exec_in",   PinDirection.INPUT,  PinType.TICK),
        PinDescriptor("intensity", PinDirection.INPUT,  PinType.FLOAT, optional=True),
        PinDescriptor("exec_out",  PinDirection.OUTPUT, PinType.TICK),
    ]
    VARIABLE_INPUTS = {"intensity": (float, 0.5)}

    def execute(self, trigger_pin: str) -> None:
        dev = self.get_device()
        if dev:
            dev.vibrate(1, float(self.get_var_input("intensity") or 0.0),
                        on_success=lambda _: self.fire_tick("exec_out"))
        else:
            self.fire_tick("exec_out")


class EdgeVibrateBoth(DeviceNodeBase):
    """Control both Edge motors simultaneously with independent intensities."""
    NODE_NAME       = "Edge: Vibrate Both"
    NODE_GROUP      = "Devices/Lovense/Edge"
    DEVICE_TYPE_KEY = f"{LovenseEdge.__module__}.LovenseEdge"
    ICON_PATH       = LovenseEdge.ICON_PATH
    PINS = [
        PinDescriptor("exec_in",   PinDirection.INPUT,  PinType.TICK),
        PinDescriptor("internal",  PinDirection.INPUT,  PinType.FLOAT, optional=True),
        PinDescriptor("perineum",  PinDirection.INPUT,  PinType.FLOAT, optional=True),
        PinDescriptor("exec_out",  PinDirection.OUTPUT, PinType.TICK),
    ]
    VARIABLE_INPUTS = {
        "internal":  (float, 0.5),
        "perineum":  (float, 0.5),
    }

    def execute(self, trigger_pin: str) -> None:
        dev = self.get_device()
        if dev:
            lv_int = max(0.0, min(1.0, float(self.get_var_input("internal") or 0.0)))
            lv_per = max(0.0, min(1.0, float(self.get_var_input("perineum") or 0.0)))
            dev.send_command(
                "vibrate",
                {"levels": [int(lv_int * VIBRATE_MAX), int(lv_per * VIBRATE_MAX)]},
                on_success=lambda _: self.fire_tick("exec_out"),
            )
        else:
            self.fire_tick("exec_out")


_EdgeStopNode = _make_stop_node(LovenseEdge)


# ─────────────────────────────────────────────────────────────────────────────
# Diamo — cock ring vibrator
# ─────────────────────────────────────────────────────────────────────────────

class LovenseDiamo(_LovenseBLEBase):
    DEVICE_NAME        = "Diamo"
    DEVICE_DESCRIPTION = "Vibrating cock ring"
    DEVICE_IDENTIFIER  = "R"
    VIBRATOR_COUNT     = 1
    VIBRATOR_NAMES     = ["Vibrate"]
    ICON_PATH          = "assets/icons/lovense/diamo.svg"


class DiamoVibrate(DeviceNodeBase):
    """Vibrate the Diamo cock ring."""
    NODE_NAME       = "Diamo: Vibrate"
    NODE_GROUP      = "Devices/Lovense/Diamo"
    DEVICE_TYPE_KEY = f"{LovenseDiamo.__module__}.LovenseDiamo"
    ICON_PATH       = LovenseDiamo.ICON_PATH
    PINS = [
        PinDescriptor("exec_in",   PinDirection.INPUT,  PinType.TICK),
        PinDescriptor("intensity", PinDirection.INPUT,  PinType.FLOAT, optional=True),
        PinDescriptor("exec_out",  PinDirection.OUTPUT, PinType.TICK),
    ]
    VARIABLE_INPUTS = {"intensity": (float, 0.5)}

    def execute(self, trigger_pin: str) -> None:
        dev = self.get_device()
        if dev:
            dev.vibrate(0, float(self.get_var_input("intensity") or 0.0),
                        on_success=lambda _: self.fire_tick("exec_out"))
        else:
            self.fire_tick("exec_out")


_DiamoStopNode = _make_stop_node(LovenseDiamo)


# ─────────────────────────────────────────────────────────────────────────────
# Max — male masturbator: vibrator + air pump
# ─────────────────────────────────────────────────────────────────────────────

class LovenseMax(_LovenseBLEBase):
    DEVICE_NAME        = "Max"
    DEVICE_DESCRIPTION = "Male masturbator — vibration + air pump"
    DEVICE_IDENTIFIER  = "B"
    VIBRATOR_COUNT     = 1
    VIBRATOR_NAMES     = ["Vibrate"]
    SUPPORTS_AIR       = True
    ICON_PATH          = "assets/icons/lovense/max.svg"


class MaxVibrate(DeviceNodeBase):
    """Vibrate the Max masturbator."""
    NODE_NAME       = "Max: Vibrate"
    NODE_GROUP      = "Devices/Lovense/Max"
    DEVICE_TYPE_KEY = f"{LovenseMax.__module__}.LovenseMax"
    ICON_PATH       = LovenseMax.ICON_PATH
    PINS = [
        PinDescriptor("exec_in",   PinDirection.INPUT,  PinType.TICK),
        PinDescriptor("intensity", PinDirection.INPUT,  PinType.FLOAT, optional=True),
        PinDescriptor("exec_out",  PinDirection.OUTPUT, PinType.TICK),
    ]
    VARIABLE_INPUTS = {"intensity": (float, 0.5)}

    def execute(self, trigger_pin: str) -> None:
        dev = self.get_device()
        if dev:
            dev.vibrate(0, float(self.get_var_input("intensity") or 0.0),
                        on_success=lambda _: self.fire_tick("exec_out"))
        else:
            self.fire_tick("exec_out")


class MaxAirLevel(DeviceNodeBase):
    """Set absolute air/constriction level on the Max (0 = fully deflated, 5 = max)."""
    NODE_NAME       = "Max: Air Level"
    NODE_GROUP      = "Devices/Lovense/Max"
    DEVICE_TYPE_KEY = f"{LovenseMax.__module__}.LovenseMax"
    ICON_PATH       = LovenseMax.ICON_PATH
    PINS = [
        PinDescriptor("exec_in",  PinDirection.INPUT,  PinType.TICK),
        PinDescriptor("level",    PinDirection.INPUT,  PinType.INT, optional=True),
        PinDescriptor("exec_out", PinDirection.OUTPUT, PinType.TICK),
    ]
    VARIABLE_INPUTS = {"level": (int, 3)}

    def execute(self, trigger_pin: str) -> None:
        dev = self.get_device()
        if dev:
            level = max(0, min(5, int(self.get_var_input("level") or 0)))
            dev.send_command("air", {"action": "level", "value": level},
                             on_success=lambda _: self.fire_tick("exec_out"))
        else:
            self.fire_tick("exec_out")


class MaxAirInflate(DeviceNodeBase):
    """Inflate the Max by N steps relative to current level."""
    NODE_NAME       = "Max: Inflate"
    NODE_GROUP      = "Devices/Lovense/Max"
    DEVICE_TYPE_KEY = f"{LovenseMax.__module__}.LovenseMax"
    ICON_PATH       = LovenseMax.ICON_PATH
    PINS = [
        PinDescriptor("exec_in",  PinDirection.INPUT,  PinType.TICK),
        PinDescriptor("steps",    PinDirection.INPUT,  PinType.INT, optional=True),
        PinDescriptor("exec_out", PinDirection.OUTPUT, PinType.TICK),
    ]
    VARIABLE_INPUTS = {"steps": (int, 1)}

    def execute(self, trigger_pin: str) -> None:
        dev = self.get_device()
        if dev:
            steps = max(1, int(self.get_var_input("steps") or 1))
            dev.send_command("air", {"action": "in", "value": steps},
                             on_success=lambda _: self.fire_tick("exec_out"))
        else:
            self.fire_tick("exec_out")


class MaxAirDeflate(DeviceNodeBase):
    """Deflate the Max by N steps relative to current level."""
    NODE_NAME       = "Max: Deflate"
    NODE_GROUP      = "Devices/Lovense/Max"
    DEVICE_TYPE_KEY = f"{LovenseMax.__module__}.LovenseMax"
    ICON_PATH       = LovenseMax.ICON_PATH
    PINS = [
        PinDescriptor("exec_in",  PinDirection.INPUT,  PinType.TICK),
        PinDescriptor("steps",    PinDirection.INPUT,  PinType.INT, optional=True),
        PinDescriptor("exec_out", PinDirection.OUTPUT, PinType.TICK),
    ]
    VARIABLE_INPUTS = {"steps": (int, 1)}

    def execute(self, trigger_pin: str) -> None:
        dev = self.get_device()
        if dev:
            steps = max(1, int(self.get_var_input("steps") or 1))
            dev.send_command("air", {"action": "out", "value": steps},
                             on_success=lambda _: self.fire_tick("exec_out"))
        else:
            self.fire_tick("exec_out")


_MaxStopNode = _make_stop_node(LovenseMax)


# ─────────────────────────────────────────────────────────────────────────────
# Nora — rabbit vibrator: vibrator + rotation
# ─────────────────────────────────────────────────────────────────────────────

class LovenseNora(_LovenseBLEBase):
    DEVICE_NAME        = "Nora"
    DEVICE_DESCRIPTION = "Rabbit vibrator — vibration + rotating head"
    DEVICE_IDENTIFIER  = "A"   # also "C" on older firmware
    VIBRATOR_COUNT     = 1
    VIBRATOR_NAMES     = ["Vibrate"]
    SUPPORTS_ROTATE    = True
    ICON_PATH          = "assets/icons/lovense/nora.svg"


class NoraVibrate(DeviceNodeBase):
    """Vibrate the Nora's vibration motor."""
    NODE_NAME       = "Nora: Vibrate"
    NODE_GROUP      = "Devices/Lovense/Nora"
    DEVICE_TYPE_KEY = f"{LovenseNora.__module__}.LovenseNora"
    ICON_PATH       = LovenseNora.ICON_PATH
    PINS = [
        PinDescriptor("exec_in",   PinDirection.INPUT,  PinType.TICK),
        PinDescriptor("intensity", PinDirection.INPUT,  PinType.FLOAT, optional=True),
        PinDescriptor("exec_out",  PinDirection.OUTPUT, PinType.TICK),
    ]
    VARIABLE_INPUTS = {"intensity": (float, 0.5)}

    def execute(self, trigger_pin: str) -> None:
        dev = self.get_device()
        if dev:
            dev.vibrate(0, float(self.get_var_input("intensity") or 0.0),
                        on_success=lambda _: self.fire_tick("exec_out"))
        else:
            self.fire_tick("exec_out")


class NoraRotate(DeviceNodeBase):
    """Control the rotation speed of Nora's rotating head (0.0–1.0)."""
    NODE_NAME       = "Nora: Rotate"
    NODE_GROUP      = "Devices/Lovense/Nora"
    DEVICE_TYPE_KEY = f"{LovenseNora.__module__}.LovenseNora"
    ICON_PATH       = LovenseNora.ICON_PATH
    PINS = [
        PinDescriptor("exec_in",  PinDirection.INPUT,  PinType.TICK),
        PinDescriptor("speed",    PinDirection.INPUT,  PinType.FLOAT, optional=True),
        PinDescriptor("exec_out", PinDirection.OUTPUT, PinType.TICK),
    ]
    VARIABLE_INPUTS = {"speed": (float, 0.5)}

    def execute(self, trigger_pin: str) -> None:
        dev = self.get_device()
        if dev:
            speed = max(0.0, min(1.0, float(self.get_var_input("speed") or 0.0)))
            raw   = int(round(speed * VIBRATE_MAX))
            dev.send_command("rotate", {"level": raw},
                             on_success=lambda _: self.fire_tick("exec_out"))
        else:
            self.fire_tick("exec_out")


class NoraRotateChange(DeviceNodeBase):
    """Reverse the rotation direction of Nora's head."""
    NODE_NAME       = "Nora: Reverse Rotation"
    NODE_GROUP      = "Devices/Lovense/Nora"
    DEVICE_TYPE_KEY = f"{LovenseNora.__module__}.LovenseNora"
    ICON_PATH       = LovenseNora.ICON_PATH
    PINS = [
        PinDescriptor("exec_in",  PinDirection.INPUT,  PinType.TICK),
        PinDescriptor("exec_out", PinDirection.OUTPUT, PinType.TICK),
    ]

    def execute(self, trigger_pin: str) -> None:
        dev = self.get_device()
        if dev:
            dev.send_command("rotate_change", {},
                             on_success=lambda _: self.fire_tick("exec_out"))
        else:
            self.fire_tick("exec_out")


_NoraStopNode = _make_stop_node(LovenseNora)


# ─────────────────────────────────────────────────────────────────────────────
# Module-level export lists
# ─────────────────────────────────────────────────────────────────────────────

ALL_DEVICE_CLASSES = [LovenseEdge, LovenseDiamo, LovenseMax, LovenseNora]

ALL_NODE_CLASSES = [
    # Edge
    EdgeVibrateInternal, EdgeVibratePerineum, EdgeVibrateBoth, _EdgeStopNode,
    # Diamo
    DiamoVibrate, _DiamoStopNode,
    # Max
    MaxVibrate, MaxAirLevel, MaxAirInflate, MaxAirDeflate, _MaxStopNode,
    # Nora
    NoraVibrate, NoraRotate, NoraRotateChange, _NoraStopNode,
]
