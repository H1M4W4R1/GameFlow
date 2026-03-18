"""
Flip-flop nodes — digital logic latches driven by tick signals.

Synchronous nodes (all driven by CLK tick + reset tick):
  D   — Data / Delay       Q follows D on rising CLK edge
  T   — Toggle             Q toggles on rising CLK edge when T is high (or always)
  JK  — J-K               J sets, K clears, J=K=1 toggles
  SR  — Set-Reset          S sets Q, R clears Q (S=R=1 is undefined / no change)

Asynchronous nodes (no CLK; respond immediately to tick inputs on S/R, J/K, T):
  Async SR  — Set-Reset      responds to S/R ticks asynchronously
  Async JK  — J-K           responds to J/K ticks asynchronously
  Async T   — Toggle        responds to T ticks asynchronously

Memory Cell:
  Async Memory Cell — stores a value, outputs it; load tick input to update

Each node:
  • Has TICK inputs for control signals (no boolean inputs)
  • Outputs Q and Q̄ (Q_not) as BOOL data pins (except Memory Cell)
  • Fires a tick on "changed" only when Q actually changes value
  • Has a RESET tick input that forces Q=False when fired
"""
from __future__ import annotations

from typing import Any

from core.node_base import NodeBase
from core.types     import PinDescriptor, PinDirection, PinType


# ─────────────────────────────────────────────────────────────────────────────
# D Flip-Flop
# ─────────────────────────────────────────────────────────────────────────────

class DFlipFlopNode(NodeBase):
    """
    D (Data / Delay) Flip-Flop.

    On every rising CLK tick the output Q is latched to the current value of D.
    A reset tick input forces Q=False immediately.
    """
    NODE_NAME    = "D Flip-Flop"
    NODE_GROUP   = "Logic/Gates"
    NODE_VERSION = "1.0.0"
    NODE_TITLE_COLOR = "#2d4a6e"

    PINS = [
        PinDescriptor("changed", PinDirection.OUTPUT, PinType.TICK,
                      tooltip="Fires when Q changes value"),
        PinDescriptor("clk",   PinDirection.INPUT,  PinType.TICK,
                      tooltip="Clock — latches D → Q on each tick"),
        PinDescriptor("d",     PinDirection.INPUT,  PinType.BOOL, default=False,
                      tooltip="Data input"),
        PinDescriptor("reset", PinDirection.INPUT,  PinType.TICK,
                      tooltip="Async reset tick — forces Q to 0"),
        PinDescriptor("q",     PinDirection.OUTPUT, PinType.BOOL, default=False,
                      tooltip="Output Q"),
        PinDescriptor("q_not", PinDirection.OUTPUT, PinType.BOOL, default=True,
                      tooltip="Inverted output Q̄"),
    ]

    VARIABLE_INPUTS = {
        "d": (bool, False),
    }

    MIN_WIDTH  = 160.0
    MIN_HEIGHT = 80.0

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._q: bool = False

    def on_start(self) -> None:
        self._q = False
        self._push_state()

    def execute(self, trigger_pin: str) -> None:
        # Reset takes priority
        if trigger_pin == "reset":
            old = self._q
            self._q = False
            self._push_state()
            if old:
                self.fire_tick("changed")
            return

        # CLK: latch D → Q
        if trigger_pin == "clk":
            d   = bool(self.get_var_input("d"))
            old = self._q
            self._q = d
            self._push_state()
            if self._q != old:
                self.fire_tick("changed")

    def _push_state(self) -> None:
        self.set_output("q",     self._q)
        self.set_output("q_not", not self._q)

    def get_state(self) -> dict[str, Any]:
        s = super().get_state()
        s["__q__"] = self._q
        return s

    def set_state(self, state: dict[str, Any]) -> None:
        self._q = bool(state.pop("__q__", False))
        super().set_state(state)
        self._push_state()


# ─────────────────────────────────────────────────────────────────────────────
# T Flip-Flop
# ─────────────────────────────────────────────────────────────────────────────

class TFlipFlopNode(NodeBase):
    """
    T (Toggle) Flip-Flop.

    On each CLK tick, if T is True the output Q is toggled; if T is False Q
    holds its current value. Connect T to a constant True to get a simple
    divide-by-2 toggle on every tick.
    """
    NODE_NAME    = "T Flip-Flop"
    NODE_GROUP   = "Logic/Gates"
    NODE_VERSION = "1.0.0"
    NODE_TITLE_COLOR = "#2d4a6e"

    PINS = [
        PinDescriptor("changed", PinDirection.OUTPUT, PinType.TICK,
                      tooltip="Fires when Q changes value"),
        PinDescriptor("clk",   PinDirection.INPUT,  PinType.TICK,
                      tooltip="Clock — evaluates toggle on each tick"),
        PinDescriptor("t",     PinDirection.INPUT,  PinType.BOOL, default=True,
                      tooltip="Toggle enable (True = toggle Q on CLK)"),
        PinDescriptor("reset", PinDirection.INPUT,  PinType.TICK,
                      tooltip="Async reset tick — forces Q to 0"),
        PinDescriptor("q",     PinDirection.OUTPUT, PinType.BOOL, default=False,
                      tooltip="Output Q"),
        PinDescriptor("q_not", PinDirection.OUTPUT, PinType.BOOL, default=True,
                      tooltip="Inverted output Q̄"),
    ]

    VARIABLE_INPUTS = {
        "t": (bool, True),
    }

    MIN_WIDTH  = 160.0
    MIN_HEIGHT = 80.0

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._q: bool = False

    def on_start(self) -> None:
        self._q = False
        self._push_state()

    def execute(self, trigger_pin: str) -> None:
        # Reset takes priority
        if trigger_pin == "reset":
            old = self._q
            self._q = False
            self._push_state()
            if old:
                self.fire_tick("changed")
            return

        # CLK: toggle if T is high
        if trigger_pin == "clk":
            t   = bool(self.get_var_input("t"))
            old = self._q
            if t:
                self._q = not self._q
            self._push_state()
            if self._q != old:
                self.fire_tick("changed")

    def _push_state(self) -> None:
        self.set_output("q",     self._q)
        self.set_output("q_not", not self._q)

    def get_state(self) -> dict[str, Any]:
        s = super().get_state()
        s["__q__"] = self._q
        return s

    def set_state(self, state: dict[str, Any]) -> None:
        self._q = bool(state.pop("__q__", False))
        super().set_state(state)
        self._push_state()


# ─────────────────────────────────────────────────────────────────────────────
# JK Flip-Flop
# ─────────────────────────────────────────────────────────────────────────────

class JKFlipFlopNode(NodeBase):
    """
    JK Flip-Flop.

    Clocked truth table (on rising CLK edge):
      J=0 K=0  → hold
      J=1 K=0  → set   (Q = 1)
      J=0 K=1  → reset (Q = 0)
      J=1 K=1  → toggle
    """
    NODE_NAME    = "JK Flip-Flop"
    NODE_GROUP   = "Logic/Gates"
    NODE_VERSION = "1.0.0"
    NODE_TITLE_COLOR = "#2d4a6e"

    PINS = [
        PinDescriptor("changed", PinDirection.OUTPUT, PinType.TICK,
                      tooltip="Fires when Q changes value"),
        PinDescriptor("clk",   PinDirection.INPUT,  PinType.TICK,
                      tooltip="Clock — evaluates J/K on each tick"),
        PinDescriptor("j",     PinDirection.INPUT,  PinType.BOOL, default=False,
                      tooltip="J (Set) input"),
        PinDescriptor("k",     PinDirection.INPUT,  PinType.BOOL, default=False,
                      tooltip="K (Reset) input"),
        PinDescriptor("reset", PinDirection.INPUT,  PinType.TICK,
                      tooltip="Async reset tick — forces Q to 0"),
        PinDescriptor("q",     PinDirection.OUTPUT, PinType.BOOL, default=False,
                      tooltip="Output Q"),
        PinDescriptor("q_not", PinDirection.OUTPUT, PinType.BOOL, default=True,
                      tooltip="Inverted output Q̄"),
    ]

    VARIABLE_INPUTS = {
        "j": (bool, False),
        "k": (bool, False),
    }

    MIN_WIDTH  = 160.0
    MIN_HEIGHT = 90.0

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._q: bool = False

    def on_start(self) -> None:
        self._q = False
        self._push_state()

    def execute(self, trigger_pin: str) -> None:
        # Reset takes priority
        if trigger_pin == "reset":
            old = self._q
            self._q = False
            self._push_state()
            if old:
                self.fire_tick("changed")
            return

        # CLK: evaluate J/K
        if trigger_pin == "clk":
            j   = bool(self.get_var_input("j"))
            k   = bool(self.get_var_input("k"))
            old = self._q

            if j and k:
                self._q = not self._q   # toggle
            elif j:
                self._q = True          # set
            elif k:
                self._q = False         # reset
            # else: hold

            self._push_state()
            if self._q != old:
                self.fire_tick("changed")

    def _push_state(self) -> None:
        self.set_output("q",     self._q)
        self.set_output("q_not", not self._q)

    def get_state(self) -> dict[str, Any]:
        s = super().get_state()
        s["__q__"] = self._q
        return s

    def set_state(self, state: dict[str, Any]) -> None:
        self._q = bool(state.pop("__q__", False))
        super().set_state(state)
        self._push_state()


# ─────────────────────────────────────────────────────────────────────────────
# SR Flip-Flop
# ─────────────────────────────────────────────────────────────────────────────

class SRFlipFlopNode(NodeBase):
    """
    SR (Set-Reset) Flip-Flop.

    Clocked truth table (on rising CLK edge):
      S=0 R=0  → hold
      S=1 R=0  → set   (Q = 1)
      S=0 R=1  → reset (Q = 0)
      S=1 R=1  → undefined / no change (forbidden state)
    """
    NODE_NAME    = "SR Flip-Flop"
    NODE_GROUP   = "Logic/Gates"
    NODE_VERSION = "1.0.0"
    NODE_TITLE_COLOR = "#2d4a6e"

    PINS = [
        PinDescriptor("changed", PinDirection.OUTPUT, PinType.TICK,
                      tooltip="Fires when Q changes value"),
        PinDescriptor("clk",   PinDirection.INPUT,  PinType.TICK,
                      tooltip="Clock — evaluates S/R on each tick"),
        PinDescriptor("s",     PinDirection.INPUT,  PinType.BOOL, default=False,
                      tooltip="S (Set) input — forces Q = 1"),
        PinDescriptor("r",     PinDirection.INPUT,  PinType.BOOL, default=False,
                      tooltip="R (Reset) input — forces Q = 0"),
        PinDescriptor("reset", PinDirection.INPUT,  PinType.TICK,
                      tooltip="Async reset tick — forces Q to 0"),
        PinDescriptor("q",     PinDirection.OUTPUT, PinType.BOOL, default=False,
                      tooltip="Output Q"),
        PinDescriptor("q_not", PinDirection.OUTPUT, PinType.BOOL, default=True,
                      tooltip="Inverted output Q̄"),
    ]

    VARIABLE_INPUTS = {
        "s": (bool, False),
        "r": (bool, False),
    }

    MIN_WIDTH  = 160.0
    MIN_HEIGHT = 90.0

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._q: bool = False

    def on_start(self) -> None:
        self._q = False
        self._push_state()

    def execute(self, trigger_pin: str) -> None:
        # Reset takes priority
        if trigger_pin == "reset":
            old = self._q
            self._q = False
            self._push_state()
            if old:
                self.fire_tick("changed")
            return

        # CLK: evaluate S/R
        if trigger_pin == "clk":
            s   = bool(self.get_var_input("s"))
            r   = bool(self.get_var_input("r"))
            old = self._q

            if s and not r:
                self._q = True   # set
            elif r and not s:
                self._q = False  # reset
            # S=R=0: hold; S=R=1: forbidden → hold

            self._push_state()
            if self._q != old:
                self.fire_tick("changed")

    def _push_state(self) -> None:
        self.set_output("q",     self._q)
        self.set_output("q_not", not self._q)

    def get_state(self) -> dict[str, Any]:
        s = super().get_state()
        s["__q__"] = self._q
        return s

    def set_state(self, state: dict[str, Any]) -> None:
        self._q = bool(state.pop("__q__", False))
        super().set_state(state)
        self._push_state()


# ─────────────────────────────────────────────────────────────────────────────
# Async SR Flip-Flop (no CLK, responds immediately to S/R ticks)
# ─────────────────────────────────────────────────────────────────────────────

class AsyncSRFlipFlopNode(NodeBase):
    """
    Asynchronous SR (Set-Reset) Flip-Flop.

    Responds immediately to S and R tick inputs (no clock). Truth table:
      S fires  → Q = 1 (set)
      R fires  → Q = 0 (reset)
      Both fire / S fires while R held high → hold last state
    """
    NODE_NAME    = "Async SR Flip-Flop"
    NODE_GROUP   = "Logic/Gates"
    NODE_VERSION = "1.0.0"
    NODE_TITLE_COLOR = "#3d5a7e"

    PINS = [
        PinDescriptor("changed", PinDirection.OUTPUT, PinType.TICK,
                      tooltip="Fires when Q changes value"),
        PinDescriptor("s",       PinDirection.INPUT,  PinType.TICK,
                      tooltip="S (Set) tick — forces Q = 1"),
        PinDescriptor("r",       PinDirection.INPUT,  PinType.TICK,
                      tooltip="R (Reset) tick — forces Q = 0"),
        PinDescriptor("reset",   PinDirection.INPUT,  PinType.TICK,
                      tooltip="Async reset tick — forces Q to 0"),
        PinDescriptor("q",       PinDirection.OUTPUT, PinType.BOOL, default=False,
                      tooltip="Output Q"),
        PinDescriptor("q_not",   PinDirection.OUTPUT, PinType.BOOL, default=True,
                      tooltip="Inverted output Q̄"),
    ]

    VARIABLE_INPUTS = {}

    MIN_WIDTH  = 160.0
    MIN_HEIGHT = 90.0

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._q: bool = False

    def on_start(self) -> None:
        self._q = False
        self._push_state()

    def execute(self, trigger_pin: str) -> None:
        old = self._q

        if trigger_pin == "reset":
            self._q = False
        elif trigger_pin == "s":
            self._q = True
        elif trigger_pin == "r":
            self._q = False

        self._push_state()
        if self._q != old:
            self.fire_tick("changed")

    def _push_state(self) -> None:
        self.set_output("q",     self._q)
        self.set_output("q_not", not self._q)

    def get_state(self) -> dict[str, Any]:
        s = super().get_state()
        s["__q__"] = self._q
        return s

    def set_state(self, state: dict[str, Any]) -> None:
        self._q = bool(state.pop("__q__", False))
        super().set_state(state)
        self._push_state()


# ─────────────────────────────────────────────────────────────────────────────
# Async JK Flip-Flop (no CLK, responds immediately to J/K ticks)
# ─────────────────────────────────────────────────────────────────────────────

class AsyncJKFlipFlopNode(NodeBase):
    """
    Asynchronous JK Flip-Flop.

    Responds immediately to J and K tick inputs (no clock). Truth table:
      J fires  → Q = 1 (set)
      K fires  → Q = 0 (reset)
      If both fire in same execution: K takes precedence (resets)
    """
    NODE_NAME    = "Async JK Flip-Flop"
    NODE_GROUP   = "Logic/Gates"
    NODE_VERSION = "1.0.0"
    NODE_TITLE_COLOR = "#3d5a7e"

    PINS = [
        PinDescriptor("changed", PinDirection.OUTPUT, PinType.TICK,
                      tooltip="Fires when Q changes value"),
        PinDescriptor("j",       PinDirection.INPUT,  PinType.TICK,
                      tooltip="J (Set) tick — forces Q = 1"),
        PinDescriptor("k",       PinDirection.INPUT,  PinType.TICK,
                      tooltip="K (Reset) tick — forces Q = 0"),
        PinDescriptor("reset",   PinDirection.INPUT,  PinType.TICK,
                      tooltip="Async reset tick — forces Q to 0"),
        PinDescriptor("q",       PinDirection.OUTPUT, PinType.BOOL, default=False,
                      tooltip="Output Q"),
        PinDescriptor("q_not",   PinDirection.OUTPUT, PinType.BOOL, default=True,
                      tooltip="Inverted output Q̄"),
    ]

    VARIABLE_INPUTS = {}

    MIN_WIDTH  = 160.0
    MIN_HEIGHT = 90.0

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._q: bool = False

    def on_start(self) -> None:
        self._q = False
        self._push_state()

    def execute(self, trigger_pin: str) -> None:
        old = self._q

        if trigger_pin == "reset":
            self._q = False
        elif trigger_pin == "k":
            self._q = False
        elif trigger_pin == "j":
            self._q = True

        self._push_state()
        if self._q != old:
            self.fire_tick("changed")

    def _push_state(self) -> None:
        self.set_output("q",     self._q)
        self.set_output("q_not", not self._q)

    def get_state(self) -> dict[str, Any]:
        s = super().get_state()
        s["__q__"] = self._q
        return s

    def set_state(self, state: dict[str, Any]) -> None:
        self._q = bool(state.pop("__q__", False))
        super().set_state(state)
        self._push_state()


# ─────────────────────────────────────────────────────────────────────────────
# Async T Flip-Flop (no CLK, toggles on T tick)
# ─────────────────────────────────────────────────────────────────────────────

class AsyncTFlipFlopNode(NodeBase):
    """
    Asynchronous T (Toggle) Flip-Flop.

    Responds immediately to T tick input (no clock).
      T fires → Q toggles (Q = not Q)
    """
    NODE_NAME    = "Async T Flip-Flop"
    NODE_GROUP   = "Logic/Gates"
    NODE_VERSION = "1.0.0"
    NODE_TITLE_COLOR = "#3d5a7e"

    PINS = [
        PinDescriptor("changed", PinDirection.OUTPUT, PinType.TICK,
                      tooltip="Fires when Q changes value"),
        PinDescriptor("t",       PinDirection.INPUT,  PinType.TICK,
                      tooltip="T (Toggle) tick — toggles Q"),
        PinDescriptor("reset",   PinDirection.INPUT,  PinType.TICK,
                      tooltip="Async reset tick — forces Q to 0"),
        PinDescriptor("q",       PinDirection.OUTPUT, PinType.BOOL, default=False,
                      tooltip="Output Q"),
        PinDescriptor("q_not",   PinDirection.OUTPUT, PinType.BOOL, default=True,
                      tooltip="Inverted output Q̄"),
    ]

    VARIABLE_INPUTS = {}

    MIN_WIDTH  = 160.0
    MIN_HEIGHT = 80.0

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._q: bool = False

    def on_start(self) -> None:
        self._q = False
        self._push_state()

    def execute(self, trigger_pin: str) -> None:
        old = self._q

        if trigger_pin == "reset":
            self._q = False
        elif trigger_pin == "t":
            self._q = not self._q

        self._push_state()
        if self._q != old:
            self.fire_tick("changed")

    def _push_state(self) -> None:
        self.set_output("q",     self._q)
        self.set_output("q_not", not self._q)

    def get_state(self) -> dict[str, Any]:
        s = super().get_state()
        s["__q__"] = self._q
        return s

    def set_state(self, state: dict[str, Any]) -> None:
        self._q = bool(state.pop("__q__", False))
        super().set_state(state)
        self._push_state()


# ─────────────────────────────────────────────────────────────────────────────
# Async Memory Cell (stores a variable, outputs current value on load).
# ─────────────────────────────────────────────────────────────────────────────

class AsyncMemoryCellNode(NodeBase):
    """
    Asynchronous Memory Cell.

    Stores any variable type (float, int, bool, string, etc.) and outputs it.
    On load tick: captures the current input value and stores it.
    On reset tick: clears to default value (0 for numbers, False for bool, etc.)

    Use "store" variable input to provide the data to store.
    """
    NODE_NAME    = "Async Memory Cell"
    NODE_GROUP   = "Logic/Gates"
    NODE_VERSION = "1.0.0"
    NODE_TITLE_COLOR = "#3d5a7e"

    PINS = [
        PinDescriptor("changed", PinDirection.OUTPUT, PinType.TICK,
                      tooltip="Fires when stored value changes"),
        PinDescriptor("load",    PinDirection.INPUT,  PinType.TICK,
                      tooltip="Load tick — captures input value and stores it"),
        PinDescriptor("store",   PinDirection.INPUT,  PinType.ANY, default=0,
                      tooltip="Data to store (any type)"),
        PinDescriptor("reset",   PinDirection.INPUT,  PinType.TICK,
                      tooltip="Async reset tick — clears to default"),
        PinDescriptor("output",  PinDirection.OUTPUT, PinType.ANY, default=0,
                      tooltip="Currently stored value"),
    ]

    VARIABLE_INPUTS = {
        "store": (object, 0),
    }

    MIN_WIDTH  = 160.0
    MIN_HEIGHT = 90.0

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._stored: Any = 0

    def on_start(self) -> None:
        self._stored = 0
        self._push_state()

    def execute(self, trigger_pin: str) -> None:
        old = self._stored

        if trigger_pin == "load":
            # Capture the current input value
            self._stored = self.get_var_input("store")
        elif trigger_pin == "reset":
            self._stored = 0

        self._push_state()
        if self._stored != old:
            self.fire_tick("changed")

    def _push_state(self) -> None:
        self.set_output("output", self._stored)

    def get_state(self) -> dict[str, Any]:
        s = super().get_state()
        s["__stored__"] = self._stored
        return s

    def set_state(self, state: dict[str, Any]) -> None:
        self._stored = state.pop("__stored__", 0)
        super().set_state(state)
        self._push_state()
