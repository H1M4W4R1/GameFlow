"""
Lovense single/dual-motor vibrator devices and their graph nodes.

Devices covered:
  LovenseLush        — insertable vibrator (1 motor)           [S]
  LovenseLushAnal    — anal vibrator (1 motor)                 [AN]
  LovenseHush        — vibrating butt plug (1 motor)           [Z]
  LovenseDomi        — wand vibrator (1 motor, high-power)     [W]
  LovenseAmbi        — clitoral vibrator (1 motor)             [L]
  LovenseFerri       — magnetic clip vibrator (1 motor)        [X]
  LovenseOsci        — oscillating G-spot vibrator (1 motor)   [O]
  LovenseGemini      — couples vibrator (2 motors)             [N]
  LovenseGush        — male masturbator (1 motor)              [ED]
  LovenseGush2       — male masturbator v2 (1 motor)           [EZ]
  LovenseCalor       — sleeve vibrator (1 motor)               [T]
  LovenseTenera      — clitoral suction vibe (1 motor)         [Q]
  LovenseVulse       — thrusting vibrator (1 motor)            [SD]
  LovenseMission     — couples vibe (1 motor)                  [V]
  LovenseMission2    — couples vibe v2 (1 motor)               [CA]
  LovenseDolce       — dual-motor vibrator                     [J]
  LovenseOsci3       — dual-stimulation G-spot                 [OC]
  LovenseHyphy       — dual-vibrator                           [EB]
"""
from __future__ import annotations

from typing import Any

from core.device_node_base import DeviceNodeBase
from core.types import PinDescriptor, PinDirection, PinType
from devices.lovense._base import _LovenseBLEBase

MANUFACTURER = "Lovense"


# ─────────────────────────────────────────────────────────────────────────────
# Single-motor vibrators
# ─────────────────────────────────────────────────────────────────────────────

class LovenseLush(_LovenseBLEBase):
    DEVICE_NAME        = "Lush"
    DEVICE_TR_PREFIX   = "lovense.lush"
    DEVICE_DESCRIPTION = "Insertable wearable vibrator"
    DEVICE_IDENTIFIER  = "S"
    BLE_NAME_PREFIXES  = ("LVS-S", "LOVE-S", "LVS-Lush", "LOVE-Lush")
    VIBRATOR_COUNT     = 1
    VIBRATOR_NAMES     = ["Vibrate"]
    ICON_PATH          = "assets/icons/lovense/lush.svg"
    DEVICE_URL         = "https://www.lovense.com/lush-4-best-bluetooth-remote-controlled-g-spot-vibrator"

    def get_node_types(self) -> list[str]:
        return [_vib_key(self, 0)]


class LovenseLushAnal(_LovenseBLEBase):
    DEVICE_NAME        = "Lush Anal"
    DEVICE_TR_PREFIX   = "lovense.lush_anal"
    DEVICE_DESCRIPTION = "Anal vibrator"
    DEVICE_IDENTIFIER  = "AN"
    BLE_NAME_PREFIXES  = ("LVS-AN", "LOVE-AN")
    VIBRATOR_COUNT     = 1
    VIBRATOR_NAMES     = ["Vibrate"]
    ICON_PATH          = "assets/icons/lovense/lush_anal.svg"

    def get_node_types(self) -> list[str]:
        return [_vib_key(self, 0)]


class LovenseHush(_LovenseBLEBase):
    DEVICE_NAME        = "Hush"
    DEVICE_TR_PREFIX   = "lovense.hush"
    DEVICE_DESCRIPTION = "Vibrating butt plug"
    DEVICE_IDENTIFIER  = "Z"
    BLE_NAME_PREFIXES  = ("LVS-Z", "LOVE-Z", "LVS-Hush", "LOVE-Hush")
    VIBRATOR_COUNT     = 1
    VIBRATOR_NAMES     = ["Vibrate"]
    ICON_PATH          = "assets/icons/lovense/hush.svg"
    DEVICE_URL         = "https://www.lovense.com/vibrating-butt-plug?code=hush2xs"

    def get_node_types(self) -> list[str]:
        return [_vib_key(self, 0)]


class LovenseDomi(_LovenseBLEBase):
    DEVICE_NAME        = "Domi"
    DEVICE_TR_PREFIX   = "lovense.domi"
    DEVICE_DESCRIPTION = "Powerful wand vibrator"
    DEVICE_IDENTIFIER  = "W"
    BLE_NAME_PREFIXES  = ("LVS-W", "LOVE-W", "LVS-Domi", "LOVE-Domi")
    VIBRATOR_COUNT     = 1
    VIBRATOR_NAMES     = ["Vibrate"]
    SUPPORTS_ALIGHT    = True
    ICON_PATH          = "assets/icons/lovense/domi.svg"
    DEVICE_URL         = "https://www.lovense.com/super-powerful-wand-massager"

    def get_node_types(self) -> list[str]:
        return [_vib_key(self, 0)]


class LovenseAmbi(_LovenseBLEBase):
    DEVICE_NAME        = "Ambi"
    DEVICE_TR_PREFIX   = "lovense.ambi"
    DEVICE_DESCRIPTION = "Clitoral bullet vibrator"
    DEVICE_IDENTIFIER  = "L"
    BLE_NAME_PREFIXES  = ("LVS-L", "LOVE-L", "LVS-Ambi", "LOVE-Ambi")
    VIBRATOR_COUNT     = 1
    VIBRATOR_NAMES     = ["Vibrate"]
    ICON_PATH          = "assets/icons/lovense/ambi.svg"
    DEVICE_URL         = "https://www.lovense.com/mini-bullet-vibrator-for-clitoral-simulation"

    def get_node_types(self) -> list[str]:
        return [_vib_key(self, 0)]


class LovenseFerri(_LovenseBLEBase):
    DEVICE_NAME        = "Ferri"
    DEVICE_TR_PREFIX   = "lovense.ferri"
    DEVICE_DESCRIPTION = "Magnetic panty vibrator"
    DEVICE_IDENTIFIER  = "X"
    BLE_NAME_PREFIXES  = ("LVS-X", "LOVE-X", "LVS-Ferri", "LOVE-Ferri")
    VIBRATOR_COUNT     = 1
    VIBRATOR_NAMES     = ["Vibrate"]
    ICON_PATH          = "assets/icons/lovense/ferri.svg"
    DEVICE_URL         = "https://www.lovense.com/magnetic-panty-vibrator"

    def get_node_types(self) -> list[str]:
        return [_vib_key(self, 0)]


class LovenseOsci(_LovenseBLEBase):
    DEVICE_NAME        = "Osci"
    DEVICE_TR_PREFIX   = "lovense.osci"
    DEVICE_DESCRIPTION = "Oscillating G-spot vibrator"
    DEVICE_IDENTIFIER  = "O"
    BLE_NAME_PREFIXES  = ("LVS-O", "LOVE-O", "LVS-Osci", "LOVE-Osci")
    VIBRATOR_COUNT     = 1
    VIBRATOR_NAMES     = ["Oscillate"]
    ICON_PATH          = "assets/icons/lovense/osci.svg"
    DEVICE_URL         = "https://www.lovense.com/osci-3-gspot-clitoral-dual-stimulation-rabbit-vibrator"

    def get_node_types(self) -> list[str]:
        return [_vib_key(self, 0)]


class LovenseGush(_LovenseBLEBase):
    DEVICE_NAME        = "Gush"
    DEVICE_TR_PREFIX   = "lovense.gush"
    DEVICE_DESCRIPTION = "Male masturbator with vibration"
    DEVICE_IDENTIFIER  = "ED"
    BLE_NAME_PREFIXES  = ("LVS-ED", "LOVE-ED", "LVS-Gush", "LOVE-Gush")
    VIBRATOR_COUNT     = 1
    VIBRATOR_NAMES     = ["Vibrate"]
    ICON_PATH          = "assets/icons/lovense/gush.svg"
    DEVICE_URL         = "https://www.lovense.com/gush-2-best-remote-controlled-vibrating-male-penis-massager"

    def get_node_types(self) -> list[str]:
        return [_vib_key(self, 0)]


class LovenseGush2(_LovenseBLEBase):
    DEVICE_NAME        = "Gush 2"
    DEVICE_TR_PREFIX   = "lovense.gush2"
    DEVICE_DESCRIPTION = "Male masturbator v2 with vibration"
    DEVICE_IDENTIFIER  = "EZ"
    BLE_NAME_PREFIXES  = ("LVS-EZ", "LOVE-EZ", "LVS-Gush2", "LOVE-Gush2")
    VIBRATOR_COUNT     = 1
    VIBRATOR_NAMES     = ["Vibrate"]
    ICON_PATH          = "assets/icons/lovense/gush.svg"

    def get_node_types(self) -> list[str]:
        return [_vib_key(self, 0)]


class LovenseCalor(_LovenseBLEBase):
    DEVICE_NAME        = "Calor"
    DEVICE_TR_PREFIX   = "lovense.calor"
    DEVICE_DESCRIPTION = "Vibrating sleeve with warming"
    DEVICE_IDENTIFIER  = "T"
    BLE_NAME_PREFIXES  = ("LVS-T", "LOVE-T", "LVS-Calor", "LOVE-Calor")
    VIBRATOR_COUNT     = 1
    VIBRATOR_NAMES     = ["Vibrate"]
    ICON_PATH          = "assets/icons/lovense/calor.svg"

    def get_node_types(self) -> list[str]:
        return [_vib_key(self, 0)]


class LovenseTenera(_LovenseBLEBase):
    DEVICE_NAME        = "Tenera"
    DEVICE_TR_PREFIX   = "lovense.tenera"
    DEVICE_DESCRIPTION = "Clitoral suction vibrator"
    DEVICE_IDENTIFIER  = "Q"
    BLE_NAME_PREFIXES  = ("LVS-Q", "LOVE-Q", "LVS-Tenera", "LOVE-Tenera")
    VIBRATOR_COUNT     = 1
    VIBRATOR_NAMES     = ["Vibrate"]
    ICON_PATH          = "assets/icons/lovense/tenera.svg"

    def get_node_types(self) -> list[str]:
        return [_vib_key(self, 0)]


class LovenseVulse(_LovenseBLEBase):
    DEVICE_NAME        = "Vulse"
    DEVICE_TR_PREFIX   = "lovense.vulse"
    DEVICE_DESCRIPTION = "Thrusting vibrator"
    DEVICE_IDENTIFIER  = "SD"
    BLE_NAME_PREFIXES  = ("LVS-SD", "LOVE-SD", "LVS-Vulse", "LOVE-Vulse")
    VIBRATOR_COUNT     = 1
    VIBRATOR_NAMES     = ["Vibrate"]
    ICON_PATH          = "assets/icons/lovense/vulse.svg"

    def get_node_types(self) -> list[str]:
        return [_vib_key(self, 0)]


class LovenseMission(_LovenseBLEBase):
    DEVICE_NAME        = "Mission"
    DEVICE_TR_PREFIX   = "lovense.mission"
    DEVICE_DESCRIPTION = "Couples vibrator"
    DEVICE_IDENTIFIER  = "V"
    BLE_NAME_PREFIXES  = ("LVS-V", "LOVE-V", "LVS-Mission", "LOVE-Mission")
    VIBRATOR_COUNT     = 1
    VIBRATOR_NAMES     = ["Vibrate"]
    ICON_PATH          = "assets/icons/lovense/mission.svg"

    def get_node_types(self) -> list[str]:
        return [_vib_key(self, 0)]


class LovenseMission2(_LovenseBLEBase):
    DEVICE_NAME        = "Mission 2"
    DEVICE_TR_PREFIX   = "lovense.mission2"
    DEVICE_DESCRIPTION = "Couples vibrator v2"
    DEVICE_IDENTIFIER  = "CA"
    BLE_NAME_PREFIXES  = ("LVS-CA", "LOVE-CA")
    VIBRATOR_COUNT     = 1
    VIBRATOR_NAMES     = ["Vibrate"]
    ICON_PATH          = "assets/icons/lovense/mission.svg"

    def get_node_types(self) -> list[str]:
        return [_vib_key(self, 0)]


# ─────────────────────────────────────────────────────────────────────────────
# Dual-motor vibrators
# ─────────────────────────────────────────────────────────────────────────────

class LovenseGemini(_LovenseBLEBase):
    DEVICE_NAME        = "Gemini"
    DEVICE_TR_PREFIX   = "lovense.gemini"
    DEVICE_DESCRIPTION = "Couples vibrator — 2 independent motors"
    DEVICE_IDENTIFIER  = "N"
    BLE_NAME_PREFIXES  = ("LVS-N", "LOVE-N", "LVS-Gemini", "LOVE-Gemini")
    VIBRATOR_COUNT     = 2
    VIBRATOR_NAMES     = ["Vibrate Left", "Vibrate Right"]
    ICON_PATH          = "assets/icons/lovense/gemini.svg"
    DEVICE_URL         = "https://www.lovense.com/app-controlled-vibrating-nipple-clamps-clit-clamps"

    def get_node_types(self) -> list[str]:
        return [_vib_key(self, 0), _vib_key(self, 1)]


class LovenseDolce(_LovenseBLEBase):
    DEVICE_NAME        = "Dolce"
    DEVICE_TR_PREFIX   = "lovense.dolce"
    DEVICE_DESCRIPTION = "Dual-stimulation vibrator — 2 independent motors"
    DEVICE_IDENTIFIER  = "J"
    BLE_NAME_PREFIXES  = ("LVS-J", "LOVE-J", "LVS-Dolce", "LOVE-Dolce")
    VIBRATOR_COUNT     = 2
    VIBRATOR_NAMES     = ["Vibrate Tip", "Vibrate Base"]
    ICON_PATH          = "assets/icons/lovense/dolce.svg"

    def get_node_types(self) -> list[str]:
        return [_vib_key(self, 0), _vib_key(self, 1)]


class LovenseOsci3(_LovenseBLEBase):
    DEVICE_NAME        = "Osci 3"
    DEVICE_TR_PREFIX   = "lovense.osci3"
    DEVICE_DESCRIPTION = "Dual-stimulation G-spot oscillator"
    DEVICE_IDENTIFIER  = "OC"
    BLE_NAME_PREFIXES  = ("LVS-OC", "LOVE-OC", "LVS-Osci3", "LOVE-Osci3")
    VIBRATOR_COUNT     = 2
    VIBRATOR_NAMES     = ["Oscillate Internal", "Oscillate External"]
    ICON_PATH          = "assets/icons/lovense/osci.svg"

    def get_node_types(self) -> list[str]:
        return [_vib_key(self, 0), _vib_key(self, 1)]


class LovenseHyphy(_LovenseBLEBase):
    DEVICE_NAME        = "Hyphy"
    DEVICE_TR_PREFIX   = "lovense.hyphy"
    DEVICE_DESCRIPTION = "Dual-vibrator"
    DEVICE_IDENTIFIER  = "EB"
    BLE_NAME_PREFIXES  = ("LVS-EB", "LOVE-EB", "LVS-Hyphy", "LOVE-Hyphy")
    VIBRATOR_COUNT     = 2
    VIBRATOR_NAMES     = ["Vibrate 1", "Vibrate 2"]
    ICON_PATH          = "assets/icons/lovense/hyphy.svg"

    def get_node_types(self) -> list[str]:
        return [_vib_key(self, 0), _vib_key(self, 1)]


# ─────────────────────────────────────────────────────────────────────────────
# Shared node factory helpers
# ─────────────────────────────────────────────────────────────────────────────

def _vib_key(device: _LovenseBLEBase, motor_index: int) -> str:
    cls = device.__class__
    return f"{cls.__module__}.{cls.__name__}.Vibrate{motor_index}"


def _make_vibrate_node(
    device_cls,
    motor_index: int,
    motor_label: str,
) -> type:
    device_type_key = f"{device_cls.__module__}.{device_cls.__name__}"
    node_name       = f"{device_cls.DEVICE_NAME}: {motor_label}"
    node_group      = f"Devices/Lovense/{device_cls.DEVICE_NAME}"
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
    node_group      = f"Devices/Lovense/{device_cls.DEVICE_NAME}"

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
# Registry
# ─────────────────────────────────────────────────────────────────────────────

_VIBRATOR_DEVICES = [
    # Single-motor
    LovenseLush, LovenseLushAnal, LovenseHush, LovenseDomi, LovenseAmbi,
    LovenseFerri, LovenseOsci, LovenseGush, LovenseGush2,
    LovenseCalor, LovenseTenera, LovenseVulse, LovenseMission, LovenseMission2,
    # Dual-motor
    LovenseGemini, LovenseDolce, LovenseOsci3, LovenseHyphy,
]

ALL_DEVICE_CLASSES = _VIBRATOR_DEVICES

ALL_NODE_CLASSES: list[type] = []
for _dev_cls in _VIBRATOR_DEVICES:
    for _i, _label in enumerate(_dev_cls.VIBRATOR_NAMES):
        ALL_NODE_CLASSES.append(_make_vibrate_node(_dev_cls, _i, _label))
    ALL_NODE_CLASSES.append(_make_stop_node(_dev_cls))


# ─────────────────────────────────────────────────────────────────────────────
# Domi — ambient ring light nodes
# ─────────────────────────────────────────────────────────────────────────────

class DomiAmbientLightOn(DeviceNodeBase):
    """Enable the ambient ring light on the Domi."""
    NODE_NAME       = "Domi: Ambient Light On"
    NODE_GROUP      = "Devices/Lovense/Domi"
    DEVICE_TYPE_KEY = f"{LovenseDomi.__module__}.LovenseDomi"
    ICON_PATH       = LovenseDomi.ICON_PATH
    PINS = [
        PinDescriptor("exec_in",  PinDirection.INPUT,  PinType.TICK),
        PinDescriptor("exec_out", PinDirection.OUTPUT, PinType.TICK),
    ]

    def execute(self, trigger_pin: str) -> None:
        dev = self.get_device()
        if dev:
            dev.send_command("alight", {"action": "on"},
                             on_success=lambda _: self.fire_tick("exec_out"))
        else:
            self.fire_tick("exec_out")


class DomiAmbientLightOff(DeviceNodeBase):
    """Disable the ambient ring light on the Domi."""
    NODE_NAME       = "Domi: Ambient Light Off"
    NODE_GROUP      = "Devices/Lovense/Domi"
    DEVICE_TYPE_KEY = f"{LovenseDomi.__module__}.LovenseDomi"
    ICON_PATH       = LovenseDomi.ICON_PATH
    PINS = [
        PinDescriptor("exec_in",  PinDirection.INPUT,  PinType.TICK),
        PinDescriptor("exec_out", PinDirection.OUTPUT, PinType.TICK),
    ]

    def execute(self, trigger_pin: str) -> None:
        dev = self.get_device()
        if dev:
            dev.send_command("alight", {"action": "off"},
                             on_success=lambda _: self.fire_tick("exec_out"))
        else:
            self.fire_tick("exec_out")


ALL_NODE_CLASSES += [DomiAmbientLightOn, DomiAmbientLightOff]
