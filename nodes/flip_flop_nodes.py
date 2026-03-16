"""
Flip-flop nodes — digital logic latches driven by tick signals.

All four classic flip-flop types are provided:
  D   — Data / Delay       Q follows D on rising CLK edge
  T   — Toggle             Q toggles on rising CLK edge when T is high (or always)
  JK  — J-K               J sets, K clears, J=K=1 toggles
  SR  — Set-Reset          S sets Q, R clears Q (S=R=1 is undefined / no change)

Each node:
  • Has a CLK tick input  — the rising edge that latches state
  • Has optional data inputs (BOOL) — D, T, J, K, S, R
  • Outputs Q and Q̄ (Q_not) as BOOL data pins
  • Fires a tick on "changed" only when Q actually changes value
  • Has an active-low asynchronous reset via the ~RST BOOL pin (pull low to reset)
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
    An asynchronous active-low reset (~RST=False) forces Q=False immediately.
    """
    NODE_NAME    = "D Flip-Flop"
    NODE_GROUP   = "Logic/Gates"
    NODE_VERSION = "1.0.0"
    NODE_TITLE_COLOR = "#2d4a6e"

    PINS = [
        PinDescriptor("clk",   PinDirection.INPUT,  PinType.TICK,
                      tooltip="Clock — latches D → Q on each tick"),
        PinDescriptor("d",     PinDirection.INPUT,  PinType.BOOL, default=False,
                      tooltip="Data input"),
        PinDescriptor("rst_n", PinDirection.INPUT,  PinType.BOOL, default=True,
                      tooltip="Async reset, active-low (False = reset Q to 0)"),
        PinDescriptor("q",     PinDirection.OUTPUT, PinType.BOOL, default=False,
                      tooltip="Output Q"),
        PinDescriptor("q_not", PinDirection.OUTPUT, PinType.BOOL, default=True,
                      tooltip="Inverted output Q̄"),
        PinDescriptor("changed", PinDirection.OUTPUT, PinType.TICK,
                      tooltip="Fires when Q changes value"),
    ]

    VARIABLE_INPUTS = {
        "d":     (bool, False),
        "rst_n": (bool, True),
    }

    MIN_WIDTH  = 160.0
    MIN_HEIGHT = 80.0

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._q: bool = False

    def on_start(self) -> None:
        self._q = False
        self._push_state()

    def on_data_received(self, pin_name: str, value: Any) -> None:
        # Async reset: react immediately when rst_n goes low
        if pin_name == "rst_n" and not bool(value):
            old = self._q
            self._q = False
            self._push_state()
            if old:
                self.fire_tick("changed")

    def execute(self, trigger_pin: str) -> None:
        rst_n = bool(self.get_var_input("rst_n"))
        if not rst_n:
            old = self._q
            self._q = False
            self._push_state()
            if old:
                self.fire_tick("changed")
            return

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
    holds its current value.  Connect T to a constant True to get a simple
    divide-by-2 toggle on every tick.
    """
    NODE_NAME    = "T Flip-Flop"
    NODE_GROUP   = "Logic/Gates"
    NODE_VERSION = "1.0.0"
    NODE_TITLE_COLOR = "#2d4a6e"

    PINS = [
        PinDescriptor("clk",   PinDirection.INPUT,  PinType.TICK,
                      tooltip="Clock — evaluates toggle on each tick"),
        PinDescriptor("t",     PinDirection.INPUT,  PinType.BOOL, default=True,
                      tooltip="Toggle enable (True = toggle Q on CLK)"),
        PinDescriptor("rst_n", PinDirection.INPUT,  PinType.BOOL, default=True,
                      tooltip="Async reset, active-low (False = reset Q to 0)"),
        PinDescriptor("q",     PinDirection.OUTPUT, PinType.BOOL, default=False,
                      tooltip="Output Q"),
        PinDescriptor("q_not", PinDirection.OUTPUT, PinType.BOOL, default=True,
                      tooltip="Inverted output Q̄"),
        PinDescriptor("changed", PinDirection.OUTPUT, PinType.TICK,
                      tooltip="Fires when Q changes value"),
    ]

    VARIABLE_INPUTS = {
        "t":     (bool, True),
        "rst_n": (bool, True),
    }

    MIN_WIDTH  = 160.0
    MIN_HEIGHT = 80.0

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._q: bool = False

    def on_start(self) -> None:
        self._q = False
        self._push_state()

    def on_data_received(self, pin_name: str, value: Any) -> None:
        if pin_name == "rst_n" and not bool(value):
            old = self._q
            self._q = False
            self._push_state()
            if old:
                self.fire_tick("changed")

    def execute(self, trigger_pin: str) -> None:
        rst_n = bool(self.get_var_input("rst_n"))
        if not rst_n:
            old = self._q
            self._q = False
            self._push_state()
            if old:
                self.fire_tick("changed")
            return

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
        PinDescriptor("clk",   PinDirection.INPUT,  PinType.TICK,
                      tooltip="Clock — evaluates J/K on each tick"),
        PinDescriptor("j",     PinDirection.INPUT,  PinType.BOOL, default=False,
                      tooltip="J (Set) input"),
        PinDescriptor("k",     PinDirection.INPUT,  PinType.BOOL, default=False,
                      tooltip="K (Reset) input"),
        PinDescriptor("rst_n", PinDirection.INPUT,  PinType.BOOL, default=True,
                      tooltip="Async reset, active-low (False = reset Q to 0)"),
        PinDescriptor("q",     PinDirection.OUTPUT, PinType.BOOL, default=False,
                      tooltip="Output Q"),
        PinDescriptor("q_not", PinDirection.OUTPUT, PinType.BOOL, default=True,
                      tooltip="Inverted output Q̄"),
        PinDescriptor("changed", PinDirection.OUTPUT, PinType.TICK,
                      tooltip="Fires when Q changes value"),
    ]

    VARIABLE_INPUTS = {
        "j":     (bool, False),
        "k":     (bool, False),
        "rst_n": (bool, True),
    }

    MIN_WIDTH  = 160.0
    MIN_HEIGHT = 90.0

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._q: bool = False

    def on_start(self) -> None:
        self._q = False
        self._push_state()

    def on_data_received(self, pin_name: str, value: Any) -> None:
        if pin_name == "rst_n" and not bool(value):
            old = self._q
            self._q = False
            self._push_state()
            if old:
                self.fire_tick("changed")

    def execute(self, trigger_pin: str) -> None:
        rst_n = bool(self.get_var_input("rst_n"))
        if not rst_n:
            old = self._q
            self._q = False
            self._push_state()
            if old:
                self.fire_tick("changed")
            return

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
        PinDescriptor("clk",   PinDirection.INPUT,  PinType.TICK,
                      tooltip="Clock — evaluates S/R on each tick"),
        PinDescriptor("s",     PinDirection.INPUT,  PinType.BOOL, default=False,
                      tooltip="S (Set) input — forces Q = 1"),
        PinDescriptor("r",     PinDirection.INPUT,  PinType.BOOL, default=False,
                      tooltip="R (Reset) input — forces Q = 0"),
        PinDescriptor("rst_n", PinDirection.INPUT,  PinType.BOOL, default=True,
                      tooltip="Async reset, active-low (False = reset Q to 0)"),
        PinDescriptor("q",     PinDirection.OUTPUT, PinType.BOOL, default=False,
                      tooltip="Output Q"),
        PinDescriptor("q_not", PinDirection.OUTPUT, PinType.BOOL, default=True,
                      tooltip="Inverted output Q̄"),
        PinDescriptor("changed", PinDirection.OUTPUT, PinType.TICK,
                      tooltip="Fires when Q changes value"),
    ]

    VARIABLE_INPUTS = {
        "s":     (bool, False),
        "r":     (bool, False),
        "rst_n": (bool, True),
    }

    MIN_WIDTH  = 160.0
    MIN_HEIGHT = 90.0

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._q: bool = False

    def on_start(self) -> None:
        self._q = False
        self._push_state()

    def on_data_received(self, pin_name: str, value: Any) -> None:
        if pin_name == "rst_n" and not bool(value):
            old = self._q
            self._q = False
            self._push_state()
            if old:
                self.fire_tick("changed")

    def execute(self, trigger_pin: str) -> None:
        rst_n = bool(self.get_var_input("rst_n"))
        if not rst_n:
            old = self._q
            self._q = False
            self._push_state()
            if old:
                self.fire_tick("changed")
            return

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
