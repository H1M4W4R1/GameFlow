"""
Lovense single-motor vibrator devices and their graph nodes.

Devices covered:
  LovenseLush   — insertable vibrator (1 motor)
  LovenseHush   — vibrating butt plug (1 motor)
  LovenseDomi   — wand vibrator (1 motor, high-power)
  LovenseAmbi   — clitoral vibrator (1 motor)
  LovenseFerri  — magnetic clip vibrator (1 motor)
  LovenseOsci   — oscillating vibrator (1 motor, uses Vibrate command)
  LovenseGemini — couples vibrator (2 motors)
  LovenseGush   — male masturbator (1 motor)
"""
from __future__ import annotations

from typing import Any

from core.device_node_base import DeviceNodeBase
from core.types import PinDescriptor, PinDirection, PinType
from devices.lovense._base import _LovenseBLEBase

MANUFACTURER = "Lovense"


# ─────────────────────────────────────────────────────────────────────────────
# Devices
# ─────────────────────────────────────────────────────────────────────────────

class LovenseLush(_LovenseBLEBase):
    DEVICE_NAME        = "Lush"
    DEVICE_DESCRIPTION = "Insertable wearable vibrator"
    DEVICE_IDENTIFIER  = "S"
    VIBRATOR_COUNT     = 1
    VIBRATOR_NAMES     = ["Vibrate"]
    ICON_PATH          = "assets/icons/lovense/lush.svg"

    def get_node_types(self) -> list[str]:
        return [_vib_key(self, 0)]


class LovenseHush(_LovenseBLEBase):
    DEVICE_NAME        = "Hush"
    DEVICE_DESCRIPTION = "Vibrating butt plug"
    DEVICE_IDENTIFIER  = "Z"
    VIBRATOR_COUNT     = 1
    VIBRATOR_NAMES     = ["Vibrate"]
    ICON_PATH          = "assets/icons/lovense/hush.svg"

    def get_node_types(self) -> list[str]:
        return [_vib_key(self, 0)]


class LovenseDomi(_LovenseBLEBase):
    DEVICE_NAME        = "Domi"
    DEVICE_DESCRIPTION = "Powerful wand vibrator"
    DEVICE_IDENTIFIER  = "W"
    VIBRATOR_COUNT     = 1
    VIBRATOR_NAMES     = ["Vibrate"]
    ICON_PATH          = "assets/icons/lovense/domi.svg"

    def get_node_types(self) -> list[str]:
        return [_vib_key(self, 0)]


class LovenseAmbi(_LovenseBLEBase):
    DEVICE_NAME        = "Ambi"
    DEVICE_DESCRIPTION = "Clitoral bullet vibrator"
    DEVICE_IDENTIFIER  = "L"
    VIBRATOR_COUNT     = 1
    VIBRATOR_NAMES     = ["Vibrate"]
    ICON_PATH          = "assets/icons/lovense/ambi.svg"

    def get_node_types(self) -> list[str]:
        return [_vib_key(self, 0)]


class LovenseFerri(_LovenseBLEBase):
    DEVICE_NAME        = "Ferri"
    DEVICE_DESCRIPTION = "Magnetic panty vibrator"
    DEVICE_IDENTIFIER  = "X"
    VIBRATOR_COUNT     = 1
    VIBRATOR_NAMES     = ["Vibrate"]
    ICON_PATH          = "assets/icons/lovense/ferri.svg"

    def get_node_types(self) -> list[str]:
        return [_vib_key(self, 0)]


class LovenseOsci(_LovenseBLEBase):
    DEVICE_NAME        = "Osci"
    DEVICE_DESCRIPTION = "Oscillating G-spot vibrator"
    DEVICE_IDENTIFIER  = "O"
    VIBRATOR_COUNT     = 1
    VIBRATOR_NAMES     = ["Oscillate"]
    ICON_PATH          = "assets/icons/lovense/osci.svg"

    def get_node_types(self) -> list[str]:
        return [_vib_key(self, 0)]


class LovenseGush(_LovenseBLEBase):
    DEVICE_NAME        = "Gush"
    DEVICE_DESCRIPTION = "Male masturbator with vibration"
    DEVICE_IDENTIFIER  = "GU"
    VIBRATOR_COUNT     = 1
    VIBRATOR_NAMES     = ["Vibrate"]
    ICON_PATH          = "assets/icons/lovense/gush.svg"

    def get_node_types(self) -> list[str]:
        return [_vib_key(self, 0)]


class LovenseGemini(_LovenseBLEBase):
    DEVICE_NAME        = "Gemini"
    DEVICE_DESCRIPTION = "Couples vibrator — 2 independent motors"
    DEVICE_IDENTIFIER  = "G"
    VIBRATOR_COUNT     = 2
    VIBRATOR_NAMES     = ["Vibrate Left", "Vibrate Right"]
    ICON_PATH          = "assets/icons/lovense/gemini.svg"

    def get_node_types(self) -> list[str]:
        return [_vib_key(self, 0), _vib_key(self, 1)]


# ─────────────────────────────────────────────────────────────────────────────
# Shared node factory helper
# ─────────────────────────────────────────────────────────────────────────────

def _vib_key(device: _LovenseBLEBase, motor_index: int) -> str:
    cls = device.__class__
    return f"{cls.__module__}.{cls.__name__}.Vibrate{motor_index}"


def _make_vibrate_node(
    device_cls,
    motor_index: int,
    motor_label: str,
) -> type:
    """
    Dynamically create a VibrateNode class for a specific device motor.
    Returns a new class each time — used to populate node registry.
    """
    device_type_key = f"{device_cls.__module__}.{device_cls.__name__}"
    node_name       = f"{device_cls.DEVICE_NAME}: {motor_label}"
    node_group      = f"Lovense/{device_cls.DEVICE_NAME}"
    icon_path       = device_cls.ICON_PATH

    class _VibrateNode(DeviceNodeBase):
        NODE_NAME       = node_name
        NODE_GROUP      = node_group
        DEVICE_TYPE_KEY = device_type_key
        ICON_PATH       = icon_path
        PINS = [
            PinDescriptor("exec_in",   PinDirection.INPUT,  PinType.TICK),
            PinDescriptor("intensity", PinDirection.INPUT,  PinType.FLOAT, default=0.0),
            PinDescriptor("exec_out",  PinDirection.OUTPUT, PinType.TICK),
        ]
        VARIABLE_INPUTS = {
            "intensity": (float, 0.5),
        }
        _MOTOR_INDEX = motor_index

        def execute(self, trigger_pin: str) -> None:
            dev = self.get_device()
            if dev is None:
                self.fire_tick("exec_out")
                return
            intensity = float(self.get_var_input("intensity") or 0.0)
            intensity = max(0.0, min(1.0, intensity))
            dev.vibrate(
                self._MOTOR_INDEX,
                intensity,
                on_success=lambda _: self.fire_tick("exec_out"),
            )

    _VibrateNode.__name__     = f"Vibrate{motor_index}_{device_cls.__name__}"
    _VibrateNode.__qualname__ = _VibrateNode.__name__
    return _VibrateNode


def _make_stop_node(device_cls) -> type:
    device_type_key = f"{device_cls.__module__}.{device_cls.__name__}"
    node_name       = f"{device_cls.DEVICE_NAME}: Stop All"
    node_group      = f"Lovense/{device_cls.DEVICE_NAME}"

    class _StopNode(DeviceNodeBase):
        NODE_NAME       = node_name
        NODE_GROUP      = node_group
        DEVICE_TYPE_KEY = device_type_key
        ICON_PATH       = device_cls.ICON_PATH
        PINS = [
            PinDescriptor("exec_in",  PinDirection.INPUT,  PinType.TICK),
            PinDescriptor("exec_out", PinDirection.OUTPUT, PinType.TICK),
        ]

        def execute(self, trigger_pin: str) -> None:
            dev = self.get_device()
            if dev:
                dev.stop_all(on_success=lambda _: self.fire_tick("exec_out"))
            else:
                self.fire_tick("exec_out")

    _StopNode.__name__     = f"Stop_{device_cls.__name__}"
    _StopNode.__qualname__ = _StopNode.__name__
    return _StopNode


# ─────────────────────────────────────────────────────────────────────────────
# Registry of all generated node classes for this module
# ─────────────────────────────────────────────────────────────────────────────

_VIBRATOR_DEVICES = [
    LovenseLush, LovenseHush, LovenseDomi, LovenseAmbi,
    LovenseFerri, LovenseOsci, LovenseGush, LovenseGemini,
]

# All device classes
ALL_DEVICE_CLASSES = _VIBRATOR_DEVICES

# All node classes (vibrate + stop per device)
ALL_NODE_CLASSES: list[type] = []
for _dev_cls in _VIBRATOR_DEVICES:
    for _i, _label in enumerate(_dev_cls.VIBRATOR_NAMES):
        ALL_NODE_CLASSES.append(_make_vibrate_node(_dev_cls, _i, _label))
    ALL_NODE_CLASSES.append(_make_stop_node(_dev_cls))
