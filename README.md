# SensoryFlow

A Python node-graph application for orchestrating sensual experiences through
connected hardware devices (COM/Serial, BLE, TCP, WebSocket, REST).

---

## Quick Start

```bash
pip install -r requirements.txt
cd sensory_flow
python main.py
```

---

## Architecture

```
sensory_flow/
├── core/
│   ├── types.py            ← All shared typed data structures & enums
│   ├── device_base.py      ← DeviceBase: abstract hardware driver
│   ├── device_node_base.py ← DeviceNodeBase: nodes linked to a device
│   ├── node_base.py        ← NodeBase: abstract graph node
│   ├── graph_runtime.py    ← 10ms tick loop, wire routing, execution engine
│   └── device_registry.py  ← Auto-discovery of devices and nodes
│
├── devices/                ← Drop new device drivers here (auto-discovered)
│   ├── serial_device.py    ← Serial/COM reference implementation
│   └── ble_device.py       ← BLE, TCP, WebSocket, REST implementations
│
├── nodes/                  ← Drop new node types here (auto-discovered)
│   └── builtin_nodes.py    ← Tick, Start, Counter, Timer, Math, Condition,
│                               Random, Log, Clamp
│
├── ui/
│   ├── main_window.py      ← Application shell, top bar, layout
│   ├── device_panel.py     ← Left sidebar with device status indicators
│   └── node_editor_canvas.py ← Full QPainter node editor
│
├── assets/icons/           ← PNG icons referenced by ICON_PATH on devices/nodes
├── requirements.txt
└── main.py                 ← Entry point
```

---

## Node Editor Controls

| Action                        | Input                        |
|-------------------------------|------------------------------|
| Pan view                      | Hold **MMB** + drag          |
| Zoom in / out                 | **Mouse wheel**              |
| Move node                     | **LMB** drag on node         |
| Select node                   | **LMB** click on node        |
| Connect pins                  | **LMB** drag from output pin to input pin |
| Delete selected node          | **Delete**                   |
| Add node                      | **RMB** on empty canvas      |
| Cycle focus to next node      | **Tab**                      |
| Center view on graph origin   | **Shift+Tab**                |
| Cancel wire drag / deselect   | **Escape**                   |
| Run graph                     | **F5** or ▶ button           |
| Stop graph                    | **F6** or ■ button           |
| Save graph                    | **Ctrl+S** or 💾 button      |
| Load graph                    | **Ctrl+O** or 📂 button      |

---

## Adding a New Device

Create `devices/my_device.py`:

```python
from core.device_base import DeviceBase, DeviceCommand
from core.device_node_base import DeviceNodeBase, register_device_instance
from core.types import ConnectionDescriptor, PortKind, PinDescriptor, PinDirection, PinType

DEVICE_TYPE_KEY = "devices.my_device.MyDevice"

class MyDevice(DeviceBase):
    DEVICE_NAME      = "My Device"
    DEVICE_VERSION   = "1.0.0"
    CONNECTION_KINDS = [PortKind.TCP]
    ICON_PATH        = "assets/icons/my_device.png"   # optional

    def _open(self) -> None:
        # open connection using self.descriptor
        ...

    def _close(self) -> None:
        # close connection
        ...

    def _ping(self) -> bool:
        # return True if alive, raise on failure
        ...

    def _execute_command(self, command: DeviceCommand) -> Any:
        if command.name == "vibrate":
            intensity = command.params["intensity"]   # float 0-1
            # send to device
            return True
        raise ValueError(f"Unknown command: {command.name}")

    def _on_connected(self) -> None:
        register_device_instance(DEVICE_TYPE_KEY, self)


# Optional: node that uses the device
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

Drop the file into `/devices/` — it will be auto-discovered at startup.
The device node will appear in the **My Device** group in the RMB context menu,
and will display a live status dot (green/yellow/gray) in the node title bar.

---

## Adding a New Node

Create `nodes/my_nodes.py`:

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
        PinDescriptor("result",   PinDirection.OUTPUT, PinType.FLOAT),
        PinDescriptor("exec_out", PinDirection.OUTPUT, PinType.TICK),
    ]

    def execute(self, trigger_pin: str) -> None:
        a = float(self.get_input("a") or 0.0)
        b = float(self.get_input("b") or 0.0)
        self.set_output("result", a * b)
        self.fire_tick("exec_out")
```

---

## Pin Types & Wire Colours

| Type    | Colour    | Description                     |
|---------|-----------|---------------------------------|
| TICK    | #f95979   | Execution flow                  |
| FLOAT   | #4fc3f7   | 64-bit float                    |
| INT     | #aed581   | 64-bit integer                  |
| BOOL    | #ffb74d   | Boolean                         |
| STRING  | #ce93d8   | Text string                     |
| ANY     | #90a4ae   | Accepts any data type           |

---

## Graph File Format

Graphs are saved as `.sfgraph` (JSON):

```json
{
  "name": "My Experience",
  "nodes": [
    {
      "node_id": "uuid",
      "type_key": "nodes.builtin_nodes.CounterNode",
      "x": 300.0,
      "y": 150.0,
      "state": { "step": 1, "min_val": 0, "max_val": 100 }
    }
  ],
  "wires": [
    {
      "wire_id": "uuid",
      "src_node": "uuid-of-tick",
      "src_pin":  "tick",
      "dst_node": "uuid-of-counter",
      "dst_pin":  "count_up"
    }
  ]
}
```

---

## Device Status

| Colour  | Meaning                                     |
|---------|---------------------------------------------|
| 🟢 Green | CONNECTED — device is responding normally   |
| 🟡 Yellow| UNKNOWN — last command failed, retrying     |
| ⚫ Gray  | DISCONNECTED — 3 retries failed / never seen|

The app automatically retries failed commands up to 3 times (0.5s apart).
After 3 failures, the device is marked DISCONNECTED and a background thread
polls every 5 seconds until reconnection succeeds.

---

## Colour Palette

| Token    | Hex       | Usage                    |
|----------|-----------|--------------------------|
| primary  | #f95979   | Tick wires, accents      |
| hot      | #d62a5e   | Hover states             |
| magenta  | #c90084   | Title bars, run button   |
| deep     | #ae0072   | Borders                  |
| darkest  | #45072f   | Panels, grid major       |
| bg-dark  | #1a0a0f   | Canvas background        |
| bg-node  | #220d14   | Node bodies              |
