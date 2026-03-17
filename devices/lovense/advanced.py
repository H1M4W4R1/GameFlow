"""
Lovense multi-feature devices.

  LovenseEdge        — prostate massager: 2 vibrators               [P]
  LovenseDiamo       — cock ring: 1 vibrator                         [R]
  LovenseMax         — male masturbator: 1 vibrator + air pump       [B]
  LovenseNora        — rabbit vibrator: 1 vibrator + rotating head   [A/C]
  LovenseSolace      — stroker / sex machine (oscillate)             [H]
  LovenseSolacePro   — stroker with motion control                   [BA]
  LovenseSexMachine  — full sex machine (oscillate)                  [F]
  LovenseMiniSexMachine — compact sex machine (oscillate)            [FS]
  LovenseRidge       — prostate: 1 vibrator + rotate                 [EL]
  LovenseGravity     — dual: vibrate + oscillate                     [EA]
  LovenseSpinel      — dual: vibrate + oscillate (thrusting)         [WD]
  LovenseFlexer      — dual vibrators + finger flex/rotate           [EI]
  LovenseLapis       — 3-motor vibrator                              [U]
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
    DEVICE_TR_PREFIX   = "lovense.edge"
    DEVICE_DESCRIPTION = "Dual-motor prostate massager"
    DEVICE_IDENTIFIER  = "P"
    BLE_NAME_PREFIXES  = ("LVS-P", "LOVE-P", "LVS-Edge", "LOVE-Edge")
    VIBRATOR_COUNT     = 2
    VIBRATOR_NAMES     = ["Vibrate Internal", "Vibrate Perineum"]
    ICON_PATH          = "assets/icons/lovense/edge.svg"
    DEVICE_URL         = "https://www.lovense.com/adjustable-prostate-massager"


class EdgeVibrateInternal(DeviceNodeBase):
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
    DEVICE_TR_PREFIX   = "lovense.diamo"
    DEVICE_DESCRIPTION = "Vibrating cock ring"
    DEVICE_IDENTIFIER  = "R"
    BLE_NAME_PREFIXES  = ("LVS-R", "LOVE-R", "LVS-Diamo", "LOVE-Diamo")
    VIBRATOR_COUNT     = 1
    VIBRATOR_NAMES     = ["Vibrate"]
    ICON_PATH          = "assets/icons/lovense/diamo.svg"
    DEVICE_URL         = "https://www.lovense.com/bluetooth-vibrating-cock-ring"


class DiamoVibrate(DeviceNodeBase):
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
    DEVICE_TR_PREFIX   = "lovense.max"
    DEVICE_DESCRIPTION = "Male masturbator — vibration + air pump"
    DEVICE_IDENTIFIER  = "B"
    BLE_NAME_PREFIXES  = ("LVS-B", "LOVE-B", "LVS-Max", "LOVE-Max")
    VIBRATOR_COUNT     = 1
    VIBRATOR_NAMES     = ["Vibrate"]
    SUPPORTS_AIR           = True
    SUPPORTS_ACCELEROMETER = True
    ICON_PATH          = "assets/icons/lovense/max.svg"
    DEVICE_URL         = "https://www.lovense.com/male-masturbators"


class MaxVibrate(DeviceNodeBase):
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


class MaxAccelerometerEnable(DeviceNodeBase):
    NODE_NAME       = "Max: Accelerometer Enable"
    NODE_GROUP      = "Devices/Lovense/Max"
    DEVICE_TYPE_KEY = f"{LovenseMax.__module__}.LovenseMax"
    ICON_PATH       = LovenseMax.ICON_PATH
    PINS = [
        PinDescriptor("exec_in",  PinDirection.INPUT,  PinType.TICK),
        PinDescriptor("exec_out", PinDirection.OUTPUT, PinType.TICK),
    ]

    def execute(self, trigger_pin: str) -> None:
        dev = self.get_device()
        if dev:
            dev.send_command("accelerometer", {"action": "start"},
                             on_success=lambda _: self.fire_tick("exec_out"))
        else:
            self.fire_tick("exec_out")


class MaxAccelerometerDisable(DeviceNodeBase):
    NODE_NAME       = "Max: Accelerometer Disable"
    NODE_GROUP      = "Devices/Lovense/Max"
    DEVICE_TYPE_KEY = f"{LovenseMax.__module__}.LovenseMax"
    ICON_PATH       = LovenseMax.ICON_PATH
    PINS = [
        PinDescriptor("exec_in",  PinDirection.INPUT,  PinType.TICK),
        PinDescriptor("exec_out", PinDirection.OUTPUT, PinType.TICK),
    ]

    def execute(self, trigger_pin: str) -> None:
        dev = self.get_device()
        if dev:
            dev.send_command("accelerometer", {"action": "stop"},
                             on_success=lambda _: self.fire_tick("exec_out"))
        else:
            self.fire_tick("exec_out")


class MaxAccelerometerEvent(DeviceNodeBase):
    NODE_NAME       = "Max: Accelerometer"
    NODE_GROUP      = "Devices/Lovense/Max"
    DEVICE_TYPE_KEY = f"{LovenseMax.__module__}.LovenseMax"
    ICON_PATH       = LovenseMax.ICON_PATH
    PINS = [
        PinDescriptor("on_event", PinDirection.OUTPUT, PinType.TICK),
        PinDescriptor("x",        PinDirection.OUTPUT, PinType.FLOAT),
        PinDescriptor("y",        PinDirection.OUTPUT, PinType.FLOAT),
        PinDescriptor("z",        PinDirection.OUTPUT, PinType.FLOAT),
    ]

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._connected_dev = None

    def on_start(self) -> None:
        self._connected_dev = None
        self._sync_device_signal()

    def on_stop(self) -> None:
        self._disconnect_signal()

    def on_tick_check(self) -> None:
        # Re-wire if device becomes available after graph start or changes.
        self._sync_device_signal()

    def _sync_device_signal(self) -> None:
        dev = self.get_device()
        if dev is self._connected_dev:
            return
        self._disconnect_signal()
        self._connected_dev = dev
        if dev:
            dev.data_received.connect(self._on_data)

    def _disconnect_signal(self) -> None:
        if self._connected_dev is not None:
            try:
                self._connected_dev.data_received.disconnect(self._on_data)
            except Exception:
                pass
            self._connected_dev = None

    def _on_data(self, payload: dict) -> None:
        if payload.get("type") != "accelerometer":
            return
        self.set_output("x", payload["x"])
        self.set_output("y", payload["y"])
        self.set_output("z", payload["z"])
        self.fire_tick("on_event")

    def execute(self, trigger_pin: str) -> None:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Nora — rabbit vibrator: vibrator + rotation
# ─────────────────────────────────────────────────────────────────────────────

class LovenseNora(_LovenseBLEBase):
    DEVICE_NAME               = "Nora"
    DEVICE_TR_PREFIX          = "lovense.nora"
    DEVICE_DESCRIPTION        = "Rabbit vibrator — vibration + rotating head"
    DEVICE_IDENTIFIER         = "A"
    DEVICE_IDENTIFIER_ALIASES = ["C"]   # old firmware
    BLE_NAME_PREFIXES  = ("LVS-A", "LOVE-A", "LVS-C", "LOVE-C", "LVS-Nora", "LOVE-Nora")
    VIBRATOR_COUNT     = 1
    VIBRATOR_NAMES     = ["Vibrate"]
    SUPPORTS_ROTATE    = True
    ICON_PATH          = "assets/icons/lovense/nora.svg"
    DEVICE_URL         = "https://www.lovense.com/rabbit-vibrator"


class NoraVibrate(DeviceNodeBase):
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
# Solace / Solace Pro — stroker / sex machine
# ─────────────────────────────────────────────────────────────────────────────

class LovenseSolace(_LovenseBLEBase):
    DEVICE_NAME        = "Solace"
    DEVICE_TR_PREFIX   = "lovense.solace"
    DEVICE_DESCRIPTION = "Automatic stroker"
    DEVICE_IDENTIFIER  = "H"
    BLE_NAME_PREFIXES  = ("LVS-H", "LOVE-H", "LVS-Solace", "LOVE-Solace")
    VIBRATOR_COUNT     = 1
    VIBRATOR_NAMES     = ["Stroke Speed"]
    ICON_PATH          = "assets/icons/lovense/solace.svg"
    DEVICE_URL         = "https://www.lovense.com/solace-automatic-hands-free-male-masturbator"


class LovenseSolacePro(_LovenseBLEBase):
    DEVICE_NAME        = "Solace Pro"
    DEVICE_TR_PREFIX   = "lovense.solace_pro"
    DEVICE_DESCRIPTION = "Automatic stroker with motion control"
    DEVICE_IDENTIFIER  = "BA"
    BLE_NAME_PREFIXES  = ("LVS-BA", "LOVE-BA")
    VIBRATOR_COUNT     = 1
    VIBRATOR_NAMES     = ["Stroke Speed"]
    ICON_PATH          = "assets/icons/lovense/solace_pro.svg"
    DEVICE_URL         = "https://www.lovense.com/solace-pro-ai-automatic-blowjob-machine-men"


class LovenseSexMachine(_LovenseBLEBase):
    DEVICE_NAME        = "Sex Machine"
    DEVICE_TR_PREFIX   = "lovense.sex_machine"
    DEVICE_DESCRIPTION = "Motorised sex machine"
    DEVICE_IDENTIFIER  = "F"
    BLE_NAME_PREFIXES  = ("LVS-F", "LOVE-F")
    VIBRATOR_COUNT     = 1
    VIBRATOR_NAMES     = ["Thrust Speed"]
    ICON_PATH          = "assets/icons/lovense/sex_machine.svg"
    DEVICE_URL         = "https://www.lovense.com/lovense-sex-machine"


class LovenseMiniSexMachine(_LovenseBLEBase):
    DEVICE_NAME        = "Mini Sex Machine"
    DEVICE_TR_PREFIX   = "lovense.mini_sex_machine"
    DEVICE_DESCRIPTION = "Compact motorised sex machine"
    DEVICE_IDENTIFIER  = "FS"
    BLE_NAME_PREFIXES  = ("LVS-FS", "LOVE-FS")
    VIBRATOR_COUNT     = 1
    VIBRATOR_NAMES     = ["Thrust Speed"]
    ICON_PATH          = "assets/icons/lovense/mini_sex_machine.svg"
    DEVICE_URL         = "https://www.lovense.com/mini-thrusting-app-controlled-dildo-machine"


def _make_single_vibe_node(device_cls, label: str) -> type:
    """Create a single vibrate/speed node for oscillate/stroker devices."""
    device_type_key = f"{device_cls.__module__}.{device_cls.__name__}"
    node_name       = f"{device_cls.DEVICE_NAME}: {label}"
    node_group      = f"Devices/Lovense/{device_cls.DEVICE_NAME}"

    class _Node(DeviceNodeBase):
        NODE_NAME       = node_name
        NODE_GROUP      = node_group
        DEVICE_TYPE_KEY = device_type_key
        ICON_PATH       = device_cls.ICON_PATH
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

    _Node.__name__     = f"Speed_{device_cls.__name__}"
    _Node.__qualname__ = _Node.__name__
    return _Node


_SolaceSpeedNode     = _make_single_vibe_node(LovenseSolace, "Stroke Speed")
_SolaceProSpeedNode  = _make_single_vibe_node(LovenseSolacePro, "Stroke Speed")
_SexMachineSpeedNode = _make_single_vibe_node(LovenseSexMachine, "Thrust Speed")
_MiniMachineSpeedNode = _make_single_vibe_node(LovenseMiniSexMachine, "Thrust Speed")
_SolaceStop          = _make_stop_node(LovenseSolace)
_SolaceProStop       = _make_stop_node(LovenseSolacePro)
_SexMachineStop      = _make_stop_node(LovenseSexMachine)
_MiniMachineStop     = _make_stop_node(LovenseMiniSexMachine)


# ─────────────────────────────────────────────────────────────────────────────
# Ridge — vibrate + rotate (like Nora but different form factor)
# ─────────────────────────────────────────────────────────────────────────────

class LovenseRidge(_LovenseBLEBase):
    DEVICE_NAME        = "Ridge"
    DEVICE_TR_PREFIX   = "lovense.ridge"
    DEVICE_DESCRIPTION = "Prostate massager — vibration + rotation"
    DEVICE_IDENTIFIER  = "EL"
    BLE_NAME_PREFIXES  = ("LVS-EL", "LOVE-EL", "LVS-Ridge", "LOVE-Ridge")
    VIBRATOR_COUNT     = 1
    VIBRATOR_NAMES     = ["Vibrate"]
    SUPPORTS_ROTATE    = True
    ICON_PATH          = "assets/icons/lovense/ridge.svg"
    DEVICE_URL         = "https://www.lovense.com/ridge-vibrating-rotating-anal-beads"


class RidgeVibrate(DeviceNodeBase):
    NODE_NAME       = "Ridge: Vibrate"
    NODE_GROUP      = "Devices/Lovense/Ridge"
    DEVICE_TYPE_KEY = f"{LovenseRidge.__module__}.LovenseRidge"
    ICON_PATH       = LovenseRidge.ICON_PATH
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


class RidgeRotate(DeviceNodeBase):
    NODE_NAME       = "Ridge: Rotate"
    NODE_GROUP      = "Devices/Lovense/Ridge"
    DEVICE_TYPE_KEY = f"{LovenseRidge.__module__}.LovenseRidge"
    ICON_PATH       = LovenseRidge.ICON_PATH
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


_RidgeStopNode = _make_stop_node(LovenseRidge)


# ─────────────────────────────────────────────────────────────────────────────
# Gravity / Spinel — vibrate + oscillate (two independent channels)
# ─────────────────────────────────────────────────────────────────────────────

class LovenseGravity(_LovenseBLEBase):
    DEVICE_NAME        = "Gravity"
    DEVICE_TR_PREFIX   = "lovense.gravity"
    DEVICE_DESCRIPTION = "Dual-stimulation — vibration + oscillation"
    DEVICE_IDENTIFIER  = "EA"
    BLE_NAME_PREFIXES  = ("LVS-EA", "LOVE-EA", "LVS-Gravity", "LOVE-Gravity")
    VIBRATOR_COUNT     = 2
    VIBRATOR_NAMES     = ["Vibrate", "Oscillate"]
    ICON_PATH          = "assets/icons/lovense/gravity.svg"
    DEVICE_URL         = "https://www.lovense.com/thrusting-vibrating-dildo"


class LovenseSpinel(_LovenseBLEBase):
    DEVICE_NAME        = "Spinel"
    DEVICE_TR_PREFIX   = "lovense.spinel"
    DEVICE_DESCRIPTION = "Attachment vibe + thrusting motor"
    DEVICE_IDENTIFIER  = "WD"
    BLE_NAME_PREFIXES  = ("LVS-WD", "LOVE-WD", "LVS-Spinel", "LOVE-Spinel")
    VIBRATOR_COUNT     = 2
    VIBRATOR_NAMES     = ["Vibrate", "Thrust"]
    ICON_PATH          = "assets/icons/lovense/spinel.svg"
    DEVICE_URL         = "https://www.lovense.com/spinel-app-controlled-ultra-high-speed-thrusting-vibrating-dildo"


def _make_dual_vibe_nodes(device_cls) -> list[type]:
    device_type_key = f"{device_cls.__module__}.{device_cls.__name__}"
    node_group      = f"Devices/Lovense/{device_cls.DEVICE_NAME}"
    label0, label1  = device_cls.VIBRATOR_NAMES

    class _Node0(DeviceNodeBase):
        NODE_NAME       = f"{device_cls.DEVICE_NAME}: {label0}"
        NODE_GROUP      = node_group
        DEVICE_TYPE_KEY = device_type_key
        ICON_PATH       = device_cls.ICON_PATH
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

    class _Node1(DeviceNodeBase):
        NODE_NAME       = f"{device_cls.DEVICE_NAME}: {label1}"
        NODE_GROUP      = node_group
        DEVICE_TYPE_KEY = device_type_key
        ICON_PATH       = device_cls.ICON_PATH
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

    class _NodeBoth(DeviceNodeBase):
        NODE_NAME       = f"{device_cls.DEVICE_NAME}: Both"
        NODE_GROUP      = node_group
        DEVICE_TYPE_KEY = device_type_key
        ICON_PATH       = device_cls.ICON_PATH
        PINS = [
            PinDescriptor("exec_in",  PinDirection.INPUT,  PinType.TICK),
            PinDescriptor("motor_0",  PinDirection.INPUT,  PinType.FLOAT, optional=True),
            PinDescriptor("motor_1",  PinDirection.INPUT,  PinType.FLOAT, optional=True),
            PinDescriptor("exec_out", PinDirection.OUTPUT, PinType.TICK),
        ]
        VARIABLE_INPUTS = {"motor_0": (float, 0.5), "motor_1": (float, 0.5)}

        def execute(self, trigger_pin: str) -> None:
            dev = self.get_device()
            if dev:
                l0 = max(0.0, min(1.0, float(self.get_var_input("motor_0") or 0.0)))
                l1 = max(0.0, min(1.0, float(self.get_var_input("motor_1") or 0.0)))
                dev.send_command(
                    "vibrate",
                    {"levels": [int(l0 * VIBRATE_MAX), int(l1 * VIBRATE_MAX)]},
                    on_success=lambda _: self.fire_tick("exec_out"),
                )
            else:
                self.fire_tick("exec_out")

    n = device_cls.__name__
    _Node0.__name__ = _Node0.__qualname__ = f"Motor0_{n}"
    _Node1.__name__ = _Node1.__qualname__ = f"Motor1_{n}"
    _NodeBoth.__name__ = _NodeBoth.__qualname__ = f"Both_{n}"
    return [_Node0, _Node1, _NodeBoth, _make_stop_node(device_cls)]


_GravityNodes = _make_dual_vibe_nodes(LovenseGravity)
_SpinelNodes  = _make_dual_vibe_nodes(LovenseSpinel)


# ─────────────────────────────────────────────────────────────────────────────
# Flexer — dual vibrators + finger flex/rotate
# ─────────────────────────────────────────────────────────────────────────────

class LovenseFlexer(_LovenseBLEBase):
    DEVICE_NAME        = "Flexer"
    DEVICE_TR_PREFIX   = "lovense.flexer"
    DEVICE_DESCRIPTION = "Dual-motor vibrator + rotating finger (requires FW3+)"
    DEVICE_IDENTIFIER  = "EI"
    BLE_NAME_PREFIXES  = ("LVS-EI", "LOVE-EI", "LVS-Flexer", "LOVE-Flexer")
    VIBRATOR_COUNT     = 2
    VIBRATOR_NAMES     = ["Vibrate Internal", "Vibrate External"]
    SUPPORTS_ROTATE    = True
    ICON_PATH          = "assets/icons/lovense/flexer.svg"
    DEVICE_URL         = "https://www.lovense.com/dual-wearable-panty-vibrator"


class FlexerVibrateInternal(DeviceNodeBase):
    NODE_NAME       = "Flexer: Vibrate Internal"
    NODE_GROUP      = "Devices/Lovense/Flexer"
    DEVICE_TYPE_KEY = f"{LovenseFlexer.__module__}.LovenseFlexer"
    ICON_PATH       = LovenseFlexer.ICON_PATH
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


class FlexerVibrateExternal(DeviceNodeBase):
    NODE_NAME       = "Flexer: Vibrate External"
    NODE_GROUP      = "Devices/Lovense/Flexer"
    DEVICE_TYPE_KEY = f"{LovenseFlexer.__module__}.LovenseFlexer"
    ICON_PATH       = LovenseFlexer.ICON_PATH
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


class FlexerRotate(DeviceNodeBase):
    NODE_NAME       = "Flexer: Finger Speed"
    NODE_GROUP      = "Devices/Lovense/Flexer"
    DEVICE_TYPE_KEY = f"{LovenseFlexer.__module__}.LovenseFlexer"
    ICON_PATH       = LovenseFlexer.ICON_PATH
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


_FlexerStopNode = _make_stop_node(LovenseFlexer)


# ─────────────────────────────────────────────────────────────────────────────
# Lapis — 3-motor vibrator
# ─────────────────────────────────────────────────────────────────────────────

class LovenseLapis(_LovenseBLEBase):
    DEVICE_NAME        = "Lapis"
    DEVICE_TR_PREFIX   = "lovense.lapis"
    DEVICE_DESCRIPTION = "Triple-motor vibrator — tip, internal, external"
    DEVICE_IDENTIFIER  = "U"
    BLE_NAME_PREFIXES  = ("LVS-U", "LOVE-U", "LVS-Lapis", "LOVE-Lapis")
    VIBRATOR_COUNT     = 3
    VIBRATOR_NAMES     = ["Vibrate Tip", "Vibrate Internal", "Vibrate External"]
    ICON_PATH          = "assets/icons/lovense/lapis.svg"
    DEVICE_URL         = "https://www.lovense.com/lapis-strapless-strap-on-double-sided-dildo"


def _make_lapis_nodes() -> list[type]:
    device_type_key = f"{LovenseLapis.__module__}.LovenseLapis"
    node_group      = "Devices/Lovense/Lapis"
    labels = LovenseLapis.VIBRATOR_NAMES
    nodes  = []
    for idx, lbl in enumerate(labels):
        _idx = idx

        class _N(DeviceNodeBase):
            NODE_NAME       = f"Lapis: {lbl}"
            NODE_GROUP      = node_group
            DEVICE_TYPE_KEY = device_type_key
            ICON_PATH       = LovenseLapis.ICON_PATH
            PINS = [
                PinDescriptor("exec_in",   PinDirection.INPUT,  PinType.TICK),
                PinDescriptor("intensity", PinDirection.INPUT,  PinType.FLOAT, optional=True),
                PinDescriptor("exec_out",  PinDirection.OUTPUT, PinType.TICK),
            ]
            VARIABLE_INPUTS = {"intensity": (float, 0.5)}
            _MOTOR = _idx

            def execute(self, trigger_pin: str) -> None:
                dev = self.get_device()
                if dev:
                    dev.vibrate(self._MOTOR,
                                float(self.get_var_input("intensity") or 0.0),
                                on_success=lambda _: self.fire_tick("exec_out"))
                else:
                    self.fire_tick("exec_out")

        _N.__name__ = _N.__qualname__ = f"LapisVib{idx}"
        nodes.append(_N)

    class _All(DeviceNodeBase):
        NODE_NAME       = "Lapis: All Motors"
        NODE_GROUP      = node_group
        DEVICE_TYPE_KEY = device_type_key
        ICON_PATH       = LovenseLapis.ICON_PATH
        PINS = [
            PinDescriptor("exec_in",    PinDirection.INPUT,  PinType.TICK),
            PinDescriptor("tip",        PinDirection.INPUT,  PinType.FLOAT, optional=True),
            PinDescriptor("internal",   PinDirection.INPUT,  PinType.FLOAT, optional=True),
            PinDescriptor("external",   PinDirection.INPUT,  PinType.FLOAT, optional=True),
            PinDescriptor("exec_out",   PinDirection.OUTPUT, PinType.TICK),
        ]
        VARIABLE_INPUTS = {"tip": (float, 0.5), "internal": (float, 0.5), "external": (float, 0.5)}

        def execute(self, trigger_pin: str) -> None:
            dev = self.get_device()
            if dev:
                levels = [
                    int(max(0.0, min(1.0, float(self.get_var_input(k) or 0.0))) * VIBRATE_MAX)
                    for k in ("tip", "internal", "external")
                ]
                dev.send_command("vibrate", {"levels": levels},
                                 on_success=lambda _: self.fire_tick("exec_out"))
            else:
                self.fire_tick("exec_out")

    _All.__name__ = _All.__qualname__ = "LapisAll"
    nodes.append(_All)
    nodes.append(_make_stop_node(LovenseLapis))
    return nodes


_LapisNodes = _make_lapis_nodes()


# ─────────────────────────────────────────────────────────────────────────────
# Module-level export lists
# ─────────────────────────────────────────────────────────────────────────────

ALL_DEVICE_CLASSES = [
    LovenseEdge, LovenseDiamo, LovenseMax, LovenseNora,
    LovenseSolace, LovenseSolacePro, LovenseSexMachine, LovenseMiniSexMachine,
    LovenseRidge, LovenseGravity, LovenseSpinel, LovenseFlexer, LovenseLapis,
]

ALL_NODE_CLASSES = [
    # Edge
    EdgeVibrateInternal, EdgeVibratePerineum, EdgeVibrateBoth, _EdgeStopNode,
    # Diamo
    DiamoVibrate, _DiamoStopNode,
    # Max
    MaxVibrate, MaxAirLevel, MaxAirInflate, MaxAirDeflate, _MaxStopNode,
    MaxAccelerometerEnable, MaxAccelerometerDisable, MaxAccelerometerEvent,
    # Nora
    NoraVibrate, NoraRotate, NoraRotateChange, _NoraStopNode,
    # Solace / machines
    _SolaceSpeedNode, _SolaceStop,
    _SolaceProSpeedNode, _SolaceProStop,
    _SexMachineSpeedNode, _SexMachineStop,
    _MiniMachineSpeedNode, _MiniMachineStop,
    # Ridge
    RidgeVibrate, RidgeRotate, _RidgeStopNode,
    # Gravity + Spinel (dual vibe + oscillate)
    *_GravityNodes,
    *_SpinelNodes,
    # Flexer
    FlexerVibrateInternal, FlexerVibrateExternal, FlexerRotate, _FlexerStopNode,
    # Lapis
    *_LapisNodes,
]
