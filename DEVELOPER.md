# GameFlow — Developer Guide

This document covers how to extend GameFlow: adding nodes, adding devices, and working with the translation system.

---

## Project Layout

```
GameFlow/
├── core/
│   ├── types.py               — Shared data structures and enums
│   ├── node_base.py           — NodeBase: abstract graph node
│   ├── device_base.py         — DeviceBase: abstract hardware driver
│   ├── device_node_base.py    — DeviceNodeBase: nodes that talk to a device
│   ├── graph_runtime.py       — 10 ms tick loop, wire routing, execution engine
│   ├── device_registry.py     — Auto-discovery of devices and nodes
│   └── localization.py        — CSV-based string localization
│
├── devices/                   — Drop new device drivers here (auto-discovered)
│   ├── serial_device.py
│   ├── ble_device.py
│   ├── tcp_device.py
│   ├── websocket_device.py
│   └── rest_device.py
│
├── nodes/                     — Drop new node files here (auto-discovered)
│   ├── math_nodes.py
│   ├── flow_nodes.py
│   └── ...
│
├── ui/
│   ├── main_window.py         — Application shell, toolbar, layout
│   ├── device_panel.py        — Left sidebar with device list
│   └── node_editor_canvas.py  — Full QPainter node editor (~1200 lines)
│
├── locales/
│   ├── EN.csv                 — English strings (source of truth)
│   └── PL.csv                 — Polish translation
│
├── assets/icons/              — PNG/SVG icons for devices and nodes
└── main.py                    — Entry point
```

---

## Adding a Node

Create a new file under `nodes/` (or add a class to an existing file). The registry auto-discovers any `NodeBase` subclass at startup.

### Minimal example

```python
from core.node_base import NodeBase
from core.types import PinDescriptor, PinDirection, PinType

class MultiplyNode(NodeBase):
    NODE_NAME  = "Multiply"
    NODE_GROUP = "Math"
    PINS = [
        PinDescriptor("exec_in",  PinDirection.INPUT,  PinType.TICK),
        PinDescriptor("a",        PinDirection.INPUT,  PinType.FLOAT, default=1.0),
        PinDescriptor("b",        PinDirection.INPUT,  PinType.FLOAT, default=1.0),
        PinDescriptor("exec_out", PinDirection.OUTPUT, PinType.TICK),
        PinDescriptor("result",   PinDirection.OUTPUT, PinType.FLOAT),
    ]

    def execute(self, trigger_pin: str) -> None:
        a = float(self.get_input("a") or 0.0)
        b = float(self.get_input("b") or 0.0)
        self.set_output("result", a * b)
        self.fire_tick("exec_out")
```

### Pin ordering rules

- `exec_out` (TICK OUTPUT) must always be the **first output pin**.
- All TICK OUTPUTs must come before data output pins.

### NodeBase API

| Method | Description |
|---|---|
| `get_input(pin_name)` | Returns the current value on an input pin |
| `set_output(pin_name, value)` | Sets the value on an output pin |
| `fire_tick(pin_name)` | Fires an execution tick on a TICK output pin |
| `execute(trigger_pin)` | Override this — called every time a tick arrives |

### Variable input pins

Set `VARIABLE_INPUTS = True` to allow the user to add extra input pins at runtime (e.g. for AND/OR gates with N inputs).

### Editable fields

Use `EDITABLE_FIELDS` to expose settings the user can change in the node's property panel:

```python
EDITABLE_FIELDS = [
    {"key": "step", "label": "Step", "type": "float", "default": 1.0},
]
```

### Translations

Every `NODE_NAME` and every pin label that appears in the UI should have a matching key in `locales/EN.csv`. See the **Translation System** section below.

---

## Extending Built-in Abstract Nodes

Reusable node bases should stay abstract or internal. The node registry skips concrete classes whose class name starts with `_`; abstract classes are skipped by the generic subclass loader. This prevents helper bases from appearing in node search.

### `DeviceNodeBase`

Use `core.device_node_base.DeviceNodeBase` for nodes that operate on a live `DeviceBase` instance.

```python
class MyDeviceSetValueNode(DeviceNodeBase):
    NODE_NAME = "My Device: Set Value"
    NODE_GROUP = "Devices/My Device"
    DEVICE_TYPE_KEY = "devices.my_device.MyDevice"
    PINS = [
        PinDescriptor("exec_in", PinDirection.INPUT, PinType.TICK),
        PinDescriptor("value", PinDirection.INPUT, PinType.FLOAT, default=0.5),
        PinDescriptor("exec_out", PinDirection.OUTPUT, PinType.TICK),
    ]

    def execute(self, trigger_pin: str) -> None:
        self.send_to_device(
            "set_value",
            {"value": float(self.get_input("value") or 0.0)},
            on_success=lambda _: self.fire_tick("exec_out"),
        )
```

`DeviceNodeBase` provides:

- `get_device()` - selected live device, or the first connected instance of `DEVICE_TYPE_KEY`.
- `select_device(device_id)` and `cycle_device()` - used by the canvas for multi-device selection.
- `device_status()` - status for title-bar indicators.
- `send_to_device(command, params, on_success, on_failure)` - async command dispatch through `DeviceBase`.
- selected-device persistence through `get_state()` / `set_state()`.

Register live devices from the device driver with:

```python
def _on_connected(self) -> None:
    register_device_instance(DEVICE_TYPE_KEY, self)
```

Use the same fully-qualified class key for `DEVICE_TYPE_KEY` and `register_device_instance(...)`.

### `WebSocketNodeBase`

Use `nodes.websocket_server_nodes.WebSocketNodeBase` for event/source nodes that react to JSON messages received by the shared WebSocket server.

The shared server starts when the graph starts and at least one WebSocket node subscribes. Messages are parsed as JSON and delivered to each subscribing node. Subclasses decide whether a message should fire.

```python
from nodes.websocket_server_nodes import WebSocketNodeBase

class WebSocketCommandNode(WebSocketNodeBase):
    __abstractmethods__ = frozenset()
    NODE_NAME = "WebSocket Command"
    NODE_GROUP = "Flow/Events"
    TICK_OUTPUT_PIN = "on_command"
    DATA_OUTPUT_PIN = "data"
    PINS = [
        PinDescriptor("on_command", PinDirection.OUTPUT, PinType.TICK),
        PinDescriptor("data", PinDirection.OUTPUT, PinType.ANY),
    ]

    def should_execute_for_message(self, data: Any) -> bool:
        return isinstance(data, dict) and data.get("type") == "command"
```

Important rules:

- Declare TICK outputs first. If the node has `exec_out`/event outputs, the first output should be the main tick output.
- Set `TICK_OUTPUT_PIN` to the output pin fired by matching messages.
- Set `DATA_OUTPUT_PIN` to the output pin that receives parsed JSON, or `""` if the node does not publish data.
- Implement `should_execute_for_message(data)`.
- Override `on_websocket_message(data)` only if the default behavior is not enough. The default sets `DATA_OUTPUT_PIN`, fires `TICK_OUTPUT_PIN`, and requests a repaint.
- Use `get_websocket_config()` and `set_websocket_config(host, port)` for the shared server address.
- When adding extra saved state, call `super().get_state()` and `super().set_state(state)`.

The existing `WebSocketMessageNode` and `WebSocketEventNode` in `nodes/websocket_server_nodes.py` are the reference implementations.

---

## Adding a Device

Create a new file (or package) under `devices/`. Any `DeviceBase` subclass is auto-discovered at startup.

### Minimal device driver

```python
from core.device_base import DeviceBase, DeviceCommand
from core.device_node_base import DeviceNodeBase, register_device_instance
from core.types import ConnectionDescriptor, PortKind, PinDescriptor, PinDirection, PinType
from typing import Any

DEVICE_TYPE_KEY = "devices.my_device.MyDevice"

class MyDevice(DeviceBase):
    DEVICE_NAME      = "My Device"
    DEVICE_VERSION   = "1.0.0"
    CONNECTION_KINDS = [PortKind.TCP]       # or BLE, SERIAL, WEBSOCKET, REST
    ICON_PATH        = "assets/icons/my_device.png"   # optional

    def _open(self) -> None:
        # Open connection using self.descriptor (ConnectionDescriptor)
        ...

    def _close(self) -> None:
        ...

    def _ping(self) -> bool:
        # Return True if alive, raise on failure
        ...

    def _execute_command(self, command: DeviceCommand) -> Any:
        if command.name == "vibrate":
            intensity = command.params["intensity"]
            # Send bytes / HTTP request / whatever
            return True
        raise ValueError(f"Unknown command: {command.name}")

    def _on_connected(self) -> None:
        register_device_instance(DEVICE_TYPE_KEY, self)
```

### Device node

```python
class MyDeviceVibrateNode(DeviceNodeBase):
    NODE_NAME       = "MyDevice: Vibrate"
    NODE_GROUP      = "My Device"
    DEVICE_TYPE_KEY = DEVICE_TYPE_KEY
    PINS = [
        PinDescriptor("exec_in",   PinDirection.INPUT,  PinType.TICK),
        PinDescriptor("intensity", PinDirection.INPUT,  PinType.FLOAT, default=0.5),
        PinDescriptor("exec_out",  PinDirection.OUTPUT, PinType.TICK),
    ]

    def execute(self, trigger_pin: str) -> None:
        intensity = float(self.get_input("intensity") or 0.0)
        self.send_to_device(
            "vibrate",
            {"intensity": intensity},
            on_success=lambda _: self.fire_tick("exec_out"),
        )
```

`send_to_device(command_name, params, on_success, on_failure)` queues the command on the device's command thread. Retries and status management are handled by `DeviceBase` automatically.

### Multiple devices of the same type

When 2+ devices of the same `DEVICE_TYPE_KEY` are connected, the canvas shows a device selector pill below the node's title bar. The user can pick which device instance the node controls. Drag a device row from the left panel onto a compatible node to assign it directly.

### Connection kinds

| `PortKind` | Description |
|---|---|
| `BLE` | Bluetooth Low Energy via `bleak` |
| `SERIAL` | COM / Serial port via `pyserial` |
| `TCP` | Raw TCP socket |
| `WEBSOCKET` | WebSocket via `websockets` |
| `REST` | HTTP REST API via `requests` |

---

## Pin Types

| `PinType` | Wire colour | Carries |
|---|---|---|
| `TICK` | `#f95979` | Execution flow |
| `FLOAT` | `#4fc3f7` | 64-bit float |
| `INT` | `#aed581` | 64-bit integer |
| `BOOL` | `#ffb74d` | Boolean |
| `STRING` | `#ce93d8` | Text string |
| `ANY` | `#90a4ae` | Any value |

---

## Translation System

GameFlow uses a simple CSV-based system. Strings live in `locales/<LANG>.csv`. Each row is:

```
key,translated string
```

For example:

```
node.math.add.name,Add
node.math.add.pin.a,A
ui.button.run_graph,Run Graph  (F5)
```

### Loading

At startup, `core/localization.py` loads the CSV for the user's preferred language (stored in `~/.gameflow/settings.json`). Falls back to English if a key is missing.

```python
from core.localization import tr

label = tr("node.math.add.name", default="Add")
```

The `tr()` function returns the translated string for the key, or the `default` (or the key itself) if no translation exists.

### Adding translations for a new node

When you add a new node, add all displayable strings to **both** `locales/EN.csv` and `locales/PL.csv` (and any other locale files present). The EN file is the source of truth.

Suggested key naming:

```
node.<group>.<node_slug>.name           — Node display name
node.<group>.<node_slug>.pin.<pin_name> — Pin label
node.<group>.<node_slug>.field.<key>    — Editable field label
```

### Adding a new language

1. Copy `locales/EN.csv` to `locales/<LANG_CODE>.csv` (e.g. `DE.csv`).
2. Translate each value (right-hand side of each row). Do not change keys.
3. Add the language code and display name to the language selector in `ui/main_window.py`.
4. Add a flag icon to `assets/icons/lang/<LANG_CODE>.svg` (optional).

The app will pick up the new file automatically on the next launch.

---

## Graph Runtime

The graph runs on a 10 ms tick loop (`core/graph_runtime.py`). Each tick:

1. All `On Tick` source nodes are fired.
2. Ticks propagate through wires synchronously in topological order.
3. Device commands are dispatched asynchronously on per-device threads.

Avoid blocking in `execute()` — long operations (network I/O, sleep) belong in device command handlers or user can use `Delay` nodes.

---

## Graph File Format

`.sfgraph` files are JSON:

```json
{
  "name": "My Experience",
  "nodes": [
    {
      "node_id": "uuid",
      "type_key": "nodes.math_nodes.MultiplyNode",
      "x": 300.0,
      "y": 150.0,
      "state": { "some_field": 1.0 }
    }
  ],
  "wires": [
    {
      "wire_id": "uuid",
      "src_node": "uuid-a",
      "src_pin":  "exec_out",
      "dst_node": "uuid-b",
      "dst_pin":  "exec_in"
    }
  ]
}
```

`type_key` is the fully-qualified Python class path (module + class name). If a `type_key` is not found at load time, that node is skipped with a warning.

---

## UI Colour Palette

| Token | Hex | Usage |
|---|---|---|
| primary | `#f95979` | Tick wires, accents |
| hot | `#d62a5e` | Hover states |
| magenta | `#c90084` | Title bars, run button |
| deep | `#ae0072` | Borders |
| darkest | `#45072f` | Panels, grid major |
| bg-dark | `#1a0a0f` | Canvas background |
| bg-node | `#220d14` | Node bodies |
