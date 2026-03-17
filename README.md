# SensoryFlow

A visual node-graph application for creating automated experiences with connected hardware devices — vibrators, e-stim devices, pumps, and other BLE/Serial/TCP/WebSocket/REST hardware.

You build experiences by connecting nodes together on a canvas. Each node does something — generates a waveform, controls a device, waits for a timer, checks a condition — and nodes talk to each other through wires. No coding required.

---

## Installation

**Requirements:** Python 3.11 or newer, pip

```bash
pip install -r requirements.txt
python main.py
```

That's it. On first launch the app opens an empty graph canvas.

---

## Supported Devices

| Device | Connection |
|---|---|
| **Lovense** — Lush, Hush, Domi, Ambi, Ferri, Osci, Gush, Gemini, Edge, Diamo, Max, Nora | BLE |
| **DG-Lab Coyote** (e-stim) | BLE |
| **H1M4W4R1 Pump** | BLE / Serial |
| **Generic Serial / COM** | Serial |
| **Generic TCP** | TCP |
| **Generic WebSocket** | WebSocket |
| **Generic REST API** | HTTP |

Devices appear in the left panel when they are discovered. A coloured dot shows their connection status:

| Dot | Meaning |
|---|---|
| Green | Connected and responding |
| Yellow | Last command failed — retrying |
| Gray | Disconnected |

The app retries failed commands automatically (up to 3 times, 0.5 s apart). After that it polls every 5 seconds until the device comes back.

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
| Delete selected node | **Delete** key |
| Cancel / deselect | **Escape** |

### Running a Graph

| Action | How |
|---|---|
| Run | **F5** or the ▶ button in the toolbar |
| Pause | **F7** |
| Stop | **F6** or the ■ button |

### Saving and Loading

| Action | How |
|---|---|
| New graph | **Ctrl+N** |
| Save | **Ctrl+S** or the 💾 button |
| Open | **Ctrl+O** or the 📂 button |

Graphs are saved as `.sfgraph` files (JSON).

---

## Nodes

Nodes are the building blocks of your graph. Each node has **input pins** on the left and **output pins** on the right. Pink/red pins carry execution flow (ticks); coloured pins carry data.

### Pin / Wire Types

| Colour | Type | Carries |
|---|---|---|
| Pink-red | TICK | Execution flow |
| Light blue | FLOAT | Decimal number |
| Green | INT | Integer number |
| Orange | BOOL | True / False |
| Purple | STRING | Text |
| Gray | ANY | Any value |

---

### Built-in Node Groups

#### Flow
Nodes that control when and how the graph runs.

- **On Tick** — fires on every graph tick (10 ms by default)
- **On Tick (Custom)** — fires on a configurable interval
- **On Start / On Pause / On Resume / On Stop** — fires once on each graph state change
- **Is Running** — outputs whether the graph is currently running
- **Router** — passes a tick through one of several outputs based on an index
- **Loop** — repeats a tick a fixed number of times
- **Loop While** — repeats while a condition is true

#### Time
- **Time Since Start** — seconds elapsed since graph started
- **Epoch Seconds** — current Unix timestamp
- **Current DateTime** — current date and time as a value
- **Specified DateTime** — a fixed date/time constant
- **Delay** — waits N seconds before passing the tick along
- **Timer** — fires repeatedly on an interval
- **Delta Time** — time between the last two ticks
- **Countdown** — counts down from a duration and fires on completion

#### Math
Full set of arithmetic, trigonometric, and vector operations — Add, Subtract, Multiply, Divide, Modulo, Power, Sin, Cos, Tan, Sqrt, Exp, Log, Clamp, Lerp, Map Range, Vector2D/3D/4D, Dot/Cross Product, Color operations, DateTime arithmetic, and more.

#### Comparison
- **Equal, Not Equal, Greater, Greater or Equal, Less, Less or Equal**
- **Select** — picks one of two values based on a boolean

#### Logic
Boolean gates: **AND, OR, NOT, NAND, NOR, XOR, XNOR**

#### Flip-Flops
Digital logic memory elements: **D, T, JK, SR Flip-Flop**

#### Waveforms
Generates a continuously cycling signal value (0–1) based on graph time.

- **Sine, Square, Sawtooth, Triangle, Trapezoidal, Noise, Ramp**

Each waveform node lets you set frequency and amplitude. Connect the output to a device's intensity input to create rhythmic patterns.

#### Filters
Signal smoothing:

- **Low Pass Filter** — smooths out rapid changes, keeps slow trends
- **High Pass Filter** — removes slow drift, keeps rapid changes
- **Band Pass Filter** — keeps only a specific frequency range

#### Routing
- **Multiplexer** — selects one of N inputs to pass through
- **Demultiplexer** — routes one input to one of N outputs

#### Constants
Fixed values to feed into other nodes: **Float, Integer, String, Boolean**, plus mathematical constants: **Pi (π), Euler (e), Golden Ratio (φ), Tau (τ)**, and **Color**.

#### Control (Interactive)
Nodes with UI controls you can interact with while the graph is running:

- **Slider** — drag to set a float value in real time
- **Button** — press to send a tick
- **Toggle** — switch a boolean on/off
- **Time Selector** — pick a time value

#### Conversion
Type converters: **Time ↔ Frequency**, **Any → Float / Int / Bool / String**

#### Utility
- **Counter** — increments/decrements and resets
- **Randomizer** — picks a random output tick
- **Random** — outputs a random float
- **Beep (PC)** — plays a beep through the system speaker
- **Frequency Generator** — outputs a value oscillating at a set frequency
- **Sample & Hold** — captures a value and holds it until the next sample tick

#### Debug / Display
Nodes for monitoring what is happening in your graph while it runs:

- **Log / Debug** — prints a value to the log panel
- **Numeric Display** — shows a number on the node
- **Text Display** — shows a string
- **Time Display** — shows a duration
- **State Indicator** — shows a boolean as a coloured light
- **Waveform Display** — draws a live graph of a signal

---

### Device Nodes

Each supported device comes with its own set of nodes. Examples:

**Lovense vibrators** — Vibrate (set intensity 0–1)

**Lovense Edge** — Vibrate Internal, Vibrate Perineum, Vibrate Both

**Lovense Max** — Vibrate, Air Level, Inflate, Deflate, Accelerometer

**Lovense Nora** — Vibrate, Rotate, Reverse Rotation

**DG-Lab Coyote** — Build Waveform, Set Waveform A/B, Set Strength, Enable/Disable, Stop, Get Battery, and 16 built-in waveform presets (Breath, Heartbeat, Tide, Wave Ripple, etc.)

If you have more than one device of the same type connected, a selector pill appears under the node's title bar so you can pick which device that node controls. You can also drag a device from the left panel and drop it onto a compatible node to assign it.

---

## Language

The interface supports multiple languages. Select your language from the settings menu. Currently available: **English**, **Polish (AI-translated for testing)**.

---

## Graph File Format

`.sfgraph` files are plain JSON and can be opened in any text editor. They store the list of nodes (with their positions and settings) and all the wires between them.

---

## License

Do What The F*ck You Want To Public License — see [LICENSE.md](LICENSE.md).
