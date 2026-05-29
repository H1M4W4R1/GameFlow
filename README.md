<div align="center">
  <h1>SensoryFlow</h1>
  <img src="https://github.com/H1M4W4R1/SensoryFlow/blob/master/gh_images/screenshot.png" alt="Preview screenshot"/>
</div>

SensoryFlow is a visual node-graph application for creating automated experiences with connected hardware devices: BLE, Serial, TCP, WebSocket, REST, and device-specific integrations.

You build experiences by connecting nodes together on a canvas. Each node does something: generates a waveform, controls a device, waits for a timer, checks a condition, parses JSON, reacts to a WebSocket message, or routes execution flow. Nodes talk to each other through wires, so most graphs can be built without writing code.

---

## Installation

**Requirements:** Python 3.11 or newer, pip

```bash
pip install -r requirements.txt
python main.py
```

On first launch the app opens an empty graph canvas.

---

## Devices

Devices appear in the left panel when they are added or discovered. SensoryFlow includes specific integrations for devices such as Lovense toys, DG-Lab Coyote, and the H1M4W4R1 pump, plus generic Serial, TCP, WebSocket, REST, and BLE-style device bases.

A colored dot shows device connection status:

| Dot | Meaning |
|---|---|
| Green | Connected and responding |
| Yellow | Last command failed and the app is retrying |
| Gray | Disconnected |

Device commands run asynchronously through `DeviceBase`. Failed commands are retried automatically, and disconnected devices are polled until they come back.

If more than one device of the same type is connected, compatible device nodes show a selector pill under the title bar. You can choose the target device there, or drag a device from the left panel onto a compatible node.

---

## The Node Canvas

The main area of the window is the node canvas. This is where you build your graph.

### Navigation

| Action | How |
|---|---|
| Pan | Hold **middle mouse button** and drag |
| Zoom | **Mouse wheel** |
| Select a node | **Left-click** on it |
| Move a node | **Left-click drag** on its title bar |
| Connect two pins | **Left-click drag** from an output pin to an input pin |
| Disconnect a wire | **Left-click** on the wire |
| Add a node | **Right-click** on empty canvas |
| Search for a node | Use the node search from the canvas menu |
| Delete selected node | **Delete** key |
| Cancel / deselect | **Escape** |

### Running a Graph

| Action | How |
|---|---|
| Run | **F5** or the play button in the toolbar |
| Pause / Resume | **F7** |
| Stop | **F6** or the stop button |

### Saving and Loading

| Action | How |
|---|---|
| New graph | **Ctrl+N** |
| Save | **Ctrl+S** |
| Open | **Ctrl+O** |

Graphs are saved as `.sfgraph` files.

---

## Nodes

Nodes are the building blocks of a graph. Each node has input pins on the left and output pins on the right. TICK pins carry execution flow; data pins carry values.

The full node list is intentionally not maintained here because SensoryFlow has built-in node search and auto-discovers nodes from the codebase at startup.

### Pin / Wire Types

| Type | Carries |
|---|---|
| `TICK` | Execution flow |
| `FLOAT` | Decimal number |
| `INT` | Integer number |
| `BOOL` | True / false |
| `STRING` | Text |
| `ANY` | Any supported value |
| `VECTOR2D`, `VECTOR3D`, `VECTOR4D` | Vector values |
| `COLOR` | Color values |
| `DATETIME` | Date/time values |
| `COYOTE_FRAME` | DG-Lab Coyote waveform frame values |

Tick output ordering matters for node authors: an `exec_out` output should be the first output pin, and all `TICK` outputs should be listed before data outputs. This keeps rendering and execution behavior predictable.

---

## Extending SensoryFlow

For full implementation details, see [DEVELOPER.md](DEVELOPER.md). Keep user-facing behavior in this README and deeper code examples in the developer guide.

### Adding a Node

Create a `NodeBase` subclass in `nodes/`, or add it to an existing node module. `DeviceRegistry` imports Python modules under `nodes/` and auto-registers concrete `NodeBase` subclasses at startup.

A node typically defines:

- `NODE_NAME`: display name
- `NODE_GROUP`: menu/search grouping, such as `Math/Arithmetic` or `Flow/Events`
- `PINS`: `PinDescriptor` entries describing inputs and outputs
- `execute(trigger_pin)`: behavior when a tick input fires

Useful optional hooks include `on_start()`, `on_stop()`, `on_pause()`, `on_resume()`, `on_data_received()`, `on_output_wire_connected()`, `get_state()`, `set_state()`, and `paint_custom()`.

Use `EDITABLE_FIELDS` for node-local settings and `VARIABLE_INPUTS` for pins that can either receive a wire or expose an inline editable default.

When adding user-visible node names, groups, menu labels, or pin labels, add translation keys to every file in `locales/*.csv`.

### Adding a Device

Create a `DeviceBase` subclass in `devices/`. `DeviceRegistry` imports modules under `devices/` and auto-registers concrete `DeviceBase` subclasses at startup.

A device driver typically defines:

- `DEVICE_NAME`, `DEVICE_VERSION`, `MANUFACTURER`, and `DEVICE_DESCRIPTION`
- `CONNECTION_KINDS`, using `PortKind` values such as `BLE`, `SERIAL`, `TCP`, `WEBSOCKET`, `REST`, or `MOCK`
- `ICON_PATH`, if the device has an icon
- `_open()`, `_close()`, `_ping()`, and `_execute_command(command)`

The base class owns the command queue, worker thread, retry behavior, status transitions, reconnect loop, and Qt signals. Device-specific nodes should normally subclass `DeviceNodeBase`, set `DEVICE_TYPE_KEY` to the device class key, and call `send_to_device(...)` from `execute()`.

Register live device instances in `_on_connected()` with `register_device_instance(type_key, self)` so `DeviceNodeBase` can find them and support multi-device selection.

### Extending Built-in Abstract Nodes

Some modules provide reusable abstract node bases for common behavior. Keep the base class internal by naming it with a leading underscore, or by leaving it abstract, so auto-discovery does not expose it as a menu item.

`DeviceNodeBase` is for graph nodes that target a live `DeviceBase` instance. It handles selected-device persistence, automatic fallback to the first connected instance, status display, and `send_to_device(...)`.

`WebSocketNodeBase` in `nodes/websocket_server_nodes.py` is for event-style nodes driven by JSON received on the shared WebSocket server. Subclasses set `TICK_OUTPUT_PIN`, optionally set `DATA_OUTPUT_PIN`, declare output pins with all `TICK` outputs first, and implement `should_execute_for_message(data)`. Override `on_websocket_message(data)` only when the default behavior of setting the data output and firing the tick output is not enough.

For stateful abstract bases, call `super().get_state()` and `super().set_state(state)` so graph files remain compatible with built-in persistence.

---

## Language

The interface supports multiple languages through CSV files in `locales/`. English is the source language, and Polish is currently included for testing.

When adding or renaming user-visible UI strings, add matching keys to every locale CSV file. Missing keys fall back to English or to the provided default.

---

## Graph File Format

`.sfgraph` files are plain JSON and can be opened in any text editor. They store:

- nodes, including their type keys, positions, and state
- wires between node pins
- device aliases
- canvas groups

The node `type_key` is the fully-qualified Python class path, such as `nodes.math_nodes.MultiplyNode`. If a type key cannot be found when loading a graph, that node is skipped with a warning.

---

## License

Do What The F*ck You Want To Public License. See [LICENSE.md](LICENSE.md).
