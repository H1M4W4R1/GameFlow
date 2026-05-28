"""Graph nodes for the MausTec Edge-o-Matic 3000."""
from __future__ import annotations

from typing import Any

from core.device_node_base import DeviceNodeBase
from core.types import PinDescriptor, PinDirection, PinType
from devices.maustec.edge_o_matic import DEVICE_TYPE_KEY, _clamp_byte, _parse_inline_value


CONFIG_PARAMETERS: list[tuple[str, PinType, type]] = [
    ("wifi_ssid", PinType.STRING, str),
    ("wifi_key", PinType.STRING, str),
    ("wifi_on", PinType.BOOL, bool),
    ("bt_display_name", PinType.STRING, str),
    ("bt_on", PinType.BOOL, bool),
    ("led_brightness", PinType.INT, int),
    ("websocket_port", PinType.INT, int),
    ("motor_max_speed", PinType.INT, int),
    ("screen_dim_seconds", PinType.INT, int),
    ("pressure_smoothing", PinType.INT, int),
    ("classic_serial", PinType.BOOL, bool),
    ("sensitivity_threshold", PinType.INT, int),
    ("motor_ramp_time_s", PinType.INT, int),
    ("update_frequency_hz", PinType.INT, int),
    ("sensor_sensitivity", PinType.INT, int),
    ("use_average_values", PinType.BOOL, bool),
]


class _EdgeOMaticNodeBase(DeviceNodeBase):
    DEVICE_TYPE_KEY = DEVICE_TYPE_KEY
    ICON_PATH = "assets/icons/maustec/edgeomatic.svg"
    NODE_GROUP = "Devices/MausTec/Edge-o-Matic"
    MIN_WIDTH = 220.0

    def _send_or_continue(self, command: str, params: dict[str, Any]) -> None:
        dev = self.get_device()
        if not dev:
            self.fire_tick("exec_out")
            return
        dev.send_command(
            command,
            params,
            on_success=lambda _: self.fire_tick("exec_out"),
            on_failure=lambda _: self.fire_tick("exec_out"),
        )


class EdgeOMaticSetMotorNode(_EdgeOMaticNodeBase):
    NODE_NAME = "Edge-o-Matic: Set Motor"
    PINS = [
        PinDescriptor("exec_in", PinDirection.INPUT, PinType.TICK),
        PinDescriptor("speed", PinDirection.INPUT, PinType.FLOAT, default=0.0),
        PinDescriptor("exec_out", PinDirection.OUTPUT, PinType.TICK),
    ]
    VARIABLE_INPUTS = {"speed": (float, 0.0)}

    def execute(self, trigger_pin: str) -> None:
        speed = max(0.0, min(1.0, float(self.get_var_input("speed") or 0.0)))
        self._send_or_continue("set_motor", {"speed": round(speed * 255)})


class EdgeOMaticSetMotorRawNode(_EdgeOMaticNodeBase):
    NODE_NAME = "Edge-o-Matic: Set Motor Raw"
    PINS = [
        PinDescriptor("exec_in", PinDirection.INPUT, PinType.TICK),
        PinDescriptor("speed", PinDirection.INPUT, PinType.INT, default=0),
        PinDescriptor("exec_out", PinDirection.OUTPUT, PinType.TICK),
    ]
    VARIABLE_INPUTS = {"speed": (int, 0)}

    def execute(self, trigger_pin: str) -> None:
        speed = _clamp_byte(self.get_var_input("speed") or 0)
        self._send_or_continue("set_motor", {"speed": speed})


class EdgeOMaticAutomaticModeNode(_EdgeOMaticNodeBase):
    NODE_NAME = "Edge-o-Matic: Automatic Mode"
    PINS = [
        PinDescriptor("exec_in", PinDirection.INPUT, PinType.TICK),
        PinDescriptor("exec_out", PinDirection.OUTPUT, PinType.TICK),
    ]

    def execute(self, trigger_pin: str) -> None:
        self._send_or_continue("set_mode", {"mode": "automatic"})


class EdgeOMaticManualModeNode(_EdgeOMaticNodeBase):
    NODE_NAME = "Edge-o-Matic: Manual Mode"
    PINS = [
        PinDescriptor("exec_in", PinDirection.INPUT, PinType.TICK),
        PinDescriptor("exec_out", PinDirection.OUTPUT, PinType.TICK),
    ]

    def execute(self, trigger_pin: str) -> None:
        self._send_or_continue("set_mode", {"mode": "manual"})


class EdgeOMaticStopNode(_EdgeOMaticNodeBase):
    NODE_NAME = "Edge-o-Matic: Stop"
    PINS = [
        PinDescriptor("exec_in", PinDirection.INPUT, PinType.TICK),
        PinDescriptor("exec_out", PinDirection.OUTPUT, PinType.TICK),
    ]

    def execute(self, trigger_pin: str) -> None:
        self._send_or_continue("stop", {})


class EdgeOMaticConfigSetNode(_EdgeOMaticNodeBase):
    NODE_NAME = "Edge-o-Matic: Set Config Parameter"
    PINS = [
        PinDescriptor("exec_in", PinDirection.INPUT, PinType.TICK),
        PinDescriptor("key", PinDirection.INPUT, PinType.STRING, default="motor_max_speed"),
        PinDescriptor("value", PinDirection.INPUT, PinType.ANY, default=255),
        PinDescriptor("exec_out", PinDirection.OUTPUT, PinType.TICK),
    ]
    VARIABLE_INPUTS = {"key": (str, "motor_max_speed"), "value": (str, "255")}

    def execute(self, trigger_pin: str) -> None:
        key = str(self.get_var_input("key") or "").strip()
        value = _parse_inline_value(self.get_var_input("value"))
        if not key:
            self.fire_tick("exec_out")
            return
        self._send_or_continue("config_set", {"key": key, "value": value})


class EdgeOMaticConfigureNode(_EdgeOMaticNodeBase):
    NODE_NAME = "Edge-o-Matic: Configure"
    MIN_WIDTH = 260.0
    PINS = [
        PinDescriptor("exec_in", PinDirection.INPUT, PinType.TICK),
        *[
            PinDescriptor(name, PinDirection.INPUT, pin_type, optional=True, default=None)
            for name, pin_type, _ in CONFIG_PARAMETERS
        ],
        PinDescriptor("exec_out", PinDirection.OUTPUT, PinType.TICK),
    ]
    VARIABLE_INPUTS = {
        name: (value_type, None)
        for name, _, value_type in CONFIG_PARAMETERS
    }

    def execute(self, trigger_pin: str) -> None:
        values: dict[str, Any] = {}
        for name, _, value_type in CONFIG_PARAMETERS:
            value = self.get_var_input(name)
            if value is None:
                continue
            if isinstance(value, str):
                value = value.strip()
                if value == "":
                    continue
                if value_type is not str:
                    value = _parse_inline_value(value)
            values[name] = value

        if not values:
            self.fire_tick("exec_out")
            return
        self._send_or_continue("config_set", {"values": values})


class EdgeOMaticConfigListNode(_EdgeOMaticNodeBase):
    NODE_NAME = "Edge-o-Matic: Get Config"
    PINS = [
        PinDescriptor("exec_in", PinDirection.INPUT, PinType.TICK),
        PinDescriptor("exec_out", PinDirection.OUTPUT, PinType.TICK),
        PinDescriptor("config", PinDirection.OUTPUT, PinType.ANY),
    ]

    def execute(self, trigger_pin: str) -> None:
        def done(payload: Any) -> None:
            config = payload.get("config", payload) if isinstance(payload, dict) else payload
            self.set_output("config", config)
            self.fire_tick("exec_out")

        def fail(_: Exception) -> None:
            self.set_output("config", {})
            self.fire_tick("exec_out")

        dev = self.get_device()
        if dev:
            dev.send_command("config_list", {}, on_success=done, on_failure=fail)
        else:
            fail(ConnectionError("No device"))


class EdgeOMaticSerialCommandNode(_EdgeOMaticNodeBase):
    NODE_NAME = "Edge-o-Matic: Serial Command"
    PINS = [
        PinDescriptor("exec_in", PinDirection.INPUT, PinType.TICK),
        PinDescriptor("cmd", PinDirection.INPUT, PinType.STRING, default="help"),
        PinDescriptor("exec_out", PinDirection.OUTPUT, PinType.TICK),
        PinDescriptor("text", PinDirection.OUTPUT, PinType.STRING),
    ]
    VARIABLE_INPUTS = {"cmd": (str, "help")}

    def execute(self, trigger_pin: str) -> None:
        cmd = str(self.get_var_input("cmd") or "")

        def done(payload: Any) -> None:
            text = payload.get("text", "") if isinstance(payload, dict) else str(payload)
            self.set_output("text", text)
            self.fire_tick("exec_out")

        def fail(exc: Exception) -> None:
            self.set_output("text", str(exc))
            self.fire_tick("exec_out")

        dev = self.get_device()
        if dev:
            dev.send_command("serial_cmd", {"cmd": cmd}, on_success=done, on_failure=fail)
        else:
            fail(ConnectionError("No device"))


class EdgeOMaticGetWiFiStatusNode(_EdgeOMaticNodeBase):
    NODE_NAME = "Edge-o-Matic: Get WiFi Status"
    PINS = [
        PinDescriptor("exec_in", PinDirection.INPUT, PinType.TICK),
        PinDescriptor("exec_out", PinDirection.OUTPUT, PinType.TICK),
        PinDescriptor("ssid", PinDirection.OUTPUT, PinType.STRING),
        PinDescriptor("ip", PinDirection.OUTPUT, PinType.STRING),
        PinDescriptor("rssi", PinDirection.OUTPUT, PinType.INT),
        PinDescriptor("status", PinDirection.OUTPUT, PinType.ANY),
    ]

    def execute(self, trigger_pin: str) -> None:
        def done(payload: Any) -> None:
            status = payload if isinstance(payload, dict) else {}
            self.set_output("ssid", str(status.get("ssid", "")))
            self.set_output("ip", str(status.get("ip", "")))
            self.set_output("rssi", int(status.get("rssi", 0) or 0))
            self.set_output("status", status)
            self.fire_tick("exec_out")

        def fail(_: Exception) -> None:
            self.set_output("status", {})
            self.fire_tick("exec_out")

        dev = self.get_device()
        if dev:
            dev.send_command("get_wifi_status", {}, on_success=done, on_failure=fail)
        else:
            fail(ConnectionError("No device"))


class EdgeOMaticGetSDStatusNode(_EdgeOMaticNodeBase):
    NODE_NAME = "Edge-o-Matic: Get SD Status"
    PINS = [
        PinDescriptor("exec_in", PinDirection.INPUT, PinType.TICK),
        PinDescriptor("exec_out", PinDirection.OUTPUT, PinType.TICK),
        PinDescriptor("size", PinDirection.OUTPUT, PinType.INT),
        PinDescriptor("card_type", PinDirection.OUTPUT, PinType.STRING),
        PinDescriptor("status", PinDirection.OUTPUT, PinType.ANY),
    ]

    def execute(self, trigger_pin: str) -> None:
        def done(payload: Any) -> None:
            status = payload if isinstance(payload, dict) else {}
            self.set_output("size", int(status.get("size", 0) or 0))
            self.set_output("card_type", str(status.get("type", "")))
            self.set_output("status", status)
            self.fire_tick("exec_out")

        def fail(_: Exception) -> None:
            self.set_output("status", {})
            self.fire_tick("exec_out")

        dev = self.get_device()
        if dev:
            dev.send_command("get_sd_status", {}, on_success=done, on_failure=fail)
        else:
            fail(ConnectionError("No device"))


class _EdgeOMaticDataNode(_EdgeOMaticNodeBase):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._connected_dev = None

    def on_start(self) -> None:
        self._connected_dev = None
        self._sync_device_signal()

    def on_stop(self) -> None:
        self._disconnect_signal()

    def on_tick_check(self) -> None:
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

    def _on_data(self, payload: dict[str, Any]) -> None:
        pass

    def execute(self, trigger_pin: str) -> None:
        pass


class EdgeOMaticReadingsNode(_EdgeOMaticDataNode):
    NODE_NAME = "Edge-o-Matic: On Readings"
    PINS = [
        PinDescriptor("on_readings", PinDirection.OUTPUT, PinType.TICK),
        PinDescriptor("pressure", PinDirection.OUTPUT, PinType.FLOAT),
        PinDescriptor("pavg", PinDirection.OUTPUT, PinType.FLOAT),
        PinDescriptor("motor", PinDirection.OUTPUT, PinType.INT),
        PinDescriptor("arousal", PinDirection.OUTPUT, PinType.FLOAT),
        PinDescriptor("millis", PinDirection.OUTPUT, PinType.INT),
        PinDescriptor("readings", PinDirection.OUTPUT, PinType.ANY),
    ]

    def _on_data(self, payload: dict[str, Any]) -> None:
        if payload.get("type") != "readings":
            return
        readings = payload.get("payload") or {}
        if not isinstance(readings, dict):
            return
        self.set_output("pressure", float(readings.get("pressure", 0) or 0))
        self.set_output("pavg", float(readings.get("pavg", 0) or 0))
        self.set_output("motor", int(readings.get("motor", 0) or 0))
        self.set_output("arousal", float(readings.get("arousal", 0) or 0))
        self.set_output("millis", int(readings.get("millis", 0) or 0))
        self.set_output("readings", readings)
        self.fire_tick("on_readings")


class EdgeOMaticEventNode(_EdgeOMaticDataNode):
    NODE_NAME = "Edge-o-Matic: On Event"
    PINS = [
        PinDescriptor("on_event", PinDirection.OUTPUT, PinType.TICK),
        PinDescriptor("event_type", PinDirection.OUTPUT, PinType.STRING),
        PinDescriptor("payload", PinDirection.OUTPUT, PinType.ANY),
    ]

    def _on_data(self, payload: dict[str, Any]) -> None:
        event_type = str(payload.get("type", ""))
        if event_type == "readings":
            return
        self.set_output("event_type", event_type)
        self.set_output("payload", payload.get("payload"))
        self.fire_tick("on_event")


class EdgeOMaticRawPayloadNode(_EdgeOMaticNodeBase):
    NODE_NAME = "Edge-o-Matic: Send Raw Payload"
    PINS = [
        PinDescriptor("exec_in", PinDirection.INPUT, PinType.TICK),
        PinDescriptor("payload", PinDirection.INPUT, PinType.ANY, default={}),
        PinDescriptor("exec_out", PinDirection.OUTPUT, PinType.TICK),
    ]
    VARIABLE_INPUTS = {"payload": (str, "{}")}

    def execute(self, trigger_pin: str) -> None:
        payload = self.get_var_input("payload")
        self._send_or_continue("raw", {"payload": payload})


ALL_NODE_CLASSES = [
    EdgeOMaticSetMotorNode,
    EdgeOMaticSetMotorRawNode,
    EdgeOMaticAutomaticModeNode,
    EdgeOMaticManualModeNode,
    EdgeOMaticStopNode,
    EdgeOMaticConfigSetNode,
    EdgeOMaticConfigureNode,
    EdgeOMaticConfigListNode,
    EdgeOMaticSerialCommandNode,
    EdgeOMaticGetWiFiStatusNode,
    EdgeOMaticGetSDStatusNode,
    EdgeOMaticReadingsNode,
    EdgeOMaticEventNode,
    EdgeOMaticRawPayloadNode,
]
