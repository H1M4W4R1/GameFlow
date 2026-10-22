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

### Script Node

Add **Utility → Script Node**, then right-click and choose **Edit script…**.
Configuration is available through the context menu; there are no inline fields.
The editor highlights Python syntax and previews inferred data and event ports
without executing the source. For example:

```python
def on_tick():
    value = read("value")
    gain = read("gain")
    if value > 0:
        write("result", value * gain)
    else:
        write("result", 0)
    emit("done")
```

Every literal `read("name")` creates an `ANY` input and every literal
`write("name", value)` creates an `ANY` output, including calls inside branches
and loops. Names must be nonempty strings of up to 80 characters; computed pin
names are rejected. Input and output names can match. Internal wire identifiers
use separate `input:` and `output:` prefixes; the canvas displays the script names.

Wire values into the data inputs and send a TICK to a named event input such as
`tick` to run its handler. Only event handler definitions are executable entry
points; script code must be inside `def on_name():` functions. Locals start fresh
on each event. All writes and emitted events are staged until the handler succeeds.
Data outputs are published before explicitly emitted events. An output not
written on that run keeps its previous value. Unwired inputs read as `None`.

#### Script events

`emit("name")` creates a named TICK output. A top-level, zero-argument
`def on_name():` creates a matching named TICK input. Connect these event ports
with ordinary TICK wires, including between Script Nodes. For example:

```python
def on_start():
    write("result", read("value") * 2)
    emit("done")

def on_reset():
    write("result", 0)
```

This creates event inputs `start` and `reset`, an event output `done`, a data
input `value`, and a data output `result`. A TICK on `start` runs only `on_start`;
it does not run `on_reset`. Data writes publish first, followed by explicitly
emitted events in call order. There is no implicit completion event. Events are
staged with the writes: a failing handler sends neither. Handlers only update
the data outputs they write; other outputs keep their previous values.

Handler definitions take no parameters, decorators or annotations. `return`
can exit a handler early. Each invocation starts with fresh locals. Place
initial values and calculations inside the handler that uses them; top-level
executable statements are rejected with an editor error.
Event names passed to `emit` must be literal strings, just like read/write names.
Event ports use separate `event_in:` / `event_out:` wire identifiers, so event
and data names can match. Event ports are saved and restored with the source;
source edits support undo/redo for event wires too.

Scripts use a bounded subset of Python: assignments, arithmetic, comparisons,
boolean expressions, conditional expressions, `if/else`, `for`, `while`,
`break`, `continue`, lists, tuples, dictionaries, indexing and slicing.
Available helpers include `range`, `len`, `sum`, `abs`, `min`, `max`, `round`,
`pow`, `int`, `float`, `bool`, `str`, and the math functions listed below.
Imports, function definitions other than event handlers, class definitions, comprehensions, arbitrary attributes
and object method calls are unavailable. Inputs accept numbers, booleans, text,
`None`, and nested lists/tuples/dictionaries; engine-specific objects must first
be converted to those types. Scripts cannot mutate upstream values.

Execution stops after 20,000 interpreter steps or 50 ms. Collections, strings,
integer sizes and powers also have limits. A failure publishes no staged writes
or events, retains the last successful outputs, and disables further
runs until the source is edited, the graph restarts, or **Reset error** is chosen
from the context menu. A red **!** appears in the title; **View error…** shows a
copyable message with the failing source line for execution errors.

### Formula Node

Add **Math / Arithmetic → Formula Node**, then right-click → **Edit formula…**.
Only the formula expression appears on the canvas in a read-only preview,
using the same fitted text style as timer nodes. The calculated result is
available through the `result` output and is not displayed in the node. For example:

```text
gain * sin(2 * pi * frequency * time) + offset
```

`gain`, `frequency`, `time` and `offset` become numeric inputs. Each input accepts
a wire or a constant (initially `0`) configured in the context-menu editor.
Source and constant edits are applied together when the dialog is accepted;
Cancel leaves the node unchanged. The single `result` output updates
when inputs, constants or the formula change, when the graph starts, or when an
output wire is added. This node has no TICK pins.

Operators: `+`, `-`, `*`, `/`, `//`, `%`, `**`, and `^` (power). Functions:
`sin`, `cos`, `tan`, `asin`, `acos`, `atan`, `atan2`, `sinh`, `cosh`, `tanh`,
`sqrt`, `exp`, `log`, `log2`, `log10`, `floor`, `ceil`, `trunc`, `fabs`, `fmod`,
`hypot`, `degrees`, `radians`, `isfinite`, `isinf`, `isnan`, `abs`, `min`, `max`,
`round`, and two-argument `pow`. Math names also accept the `math.` prefix.
Constants are `pi`, `e`, and `tau`. Decimal numbers use a dot.

Invalid formulas and calculation errors show the same title marker and error
menu. The last valid result remains available; changing an input or correcting
the formula retries calculation automatically. Edits preserve matching wires
and constants, remove wires for deleted ports, and support undo/redo. Source,
ports and constants are saved with the graph for both node types.

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
