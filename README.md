<div align="center">
  <h1>GameFlow</h1>
  <img src="https://github.com/H1M4W4R1/GameFlow/blob/master/gh_images/screenshot.png" alt="Preview screenshot"/>
</div>

GameFlow is a visual node-graph application for creating automated experiences with connected hardware devices: BLE, Serial, TCP, WebSocket, REST, and device-specific integrations.

You build experiences by connecting nodes together on a canvas. Each node does something: generates a waveform, controls a device, waits for a timer, checks a condition, parses JSON, reacts to a WebSocket message, or routes execution flow. Nodes talk to each other through wires, so most graphs can be built without writing code.

Originally this package was named SensoryFlow and was oriented towards adult entertainment industry, however due to
enormous amount of alternative usages it was rebranded into GameFlow, as its main purpose is to integrate external feedback
devices with games.

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

Devices appear in the left panel when they are added or discovered. 

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

The full node list is intentionally not maintained here because GameFlow has built-in node search and auto-discovers nodes from the codebase at startup.

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

Tick output ordering matters for node authors: an `exec_out` output should be the first output pin, and all `TICK` outputs should be listed before data outputs. This keeps rendering and execution behavior predictable.

---

## Extending GameFlow

For full implementation details, see [DEVELOPER.md](DEVELOPER.md). Keep user-facing behavior in this README and deeper code examples in the developer guide.

---

## Language

The interface supports multiple languages through CSV files in `locales/`. English is the source language, and Polish is currently included for testing.

When adding or renaming user-visible UI strings, add matching keys to the relevant locale CSV files. Core strings live in `locales/*.csv`; plugin strings live in `plugins/<plugin_name>/locales/*.csv`. Missing keys fall back to English or to the provided default.

---

## Graph File Format

`.sfgraph` files are plain JSON and can be opened in any text editor. They store:

- nodes, including their type keys, positions, and state
- wires between node pins
- device aliases
- canvas groups

The node `type_key` is the fully-qualified Python class path, such as `nodes.math_nodes.MultiplyNode` for built-ins or `plugins.my_plugin.my_nodes.MyNode` for plugin nodes. If a type key cannot be found when loading a graph, that node is skipped with a warning.

---

## License

Do What The F*ck You Want To Public License. See [LICENSE.md](LICENSE.md).
