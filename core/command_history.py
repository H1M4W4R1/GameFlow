"""Undo/redo command system for GameFlow.

Usage::

    history = CommandHistory()

    # After performing an action, push a command that knows how to undo/redo it:
    history.push(SomeCmd(...))

    # Undo / redo:
    history.undo()
    history.redo()

    # Group multiple commands into one undo step:
    history.begin_macro("Paste")
    history.push(cmd1)
    history.push(cmd2)
    history.end_macro()
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.graph_runtime import GraphRuntime
    from core.node_base import NodeBase
    from core.types import WireDescriptor


# ── Base ──────────────────────────────────────────────────────────────────────

class Command:
    description: str = ""

    def undo(self) -> None:
        pass

    def redo(self) -> None:
        pass


class MacroCmd(Command):
    """Groups multiple commands into one logical undo/redo step."""

    def __init__(self, cmds: list[Command], description: str = "") -> None:
        self.cmds = cmds
        self.description = description

    def undo(self) -> None:
        for c in reversed(self.cmds):
            c.undo()

    def redo(self) -> None:
        for c in self.cmds:
            c.redo()


# ── History ───────────────────────────────────────────────────────────────────

class CommandHistory:
    """Maintains undo/redo stacks; commands are pushed *after* they execute."""

    def __init__(self, max_size: int = 100) -> None:
        self._undo: list[Command] = []
        self._redo: list[Command] = []
        self._max = max_size
        self._macro: list[Command] | None = None
        self._macro_desc: str = ""

    def push(self, cmd: Command) -> None:
        """Record an already-executed command for potential undo."""
        if self._macro is not None:
            self._macro.append(cmd)
            return
        self._undo.append(cmd)
        if len(self._undo) > self._max:
            self._undo.pop(0)
        self._redo.clear()

    def begin_macro(self, description: str = "") -> None:
        """Start grouping subsequent push() calls into one undo step."""
        self._macro = []
        self._macro_desc = description

    def end_macro(self) -> None:
        """End grouping; pushes all collected commands as one MacroCmd."""
        cmds, desc = self._macro, self._macro_desc
        self._macro = None
        self._macro_desc = ""
        if cmds:
            self._undo.append(MacroCmd(cmds, desc))
            if len(self._undo) > self._max:
                self._undo.pop(0)
            self._redo.clear()

    def undo(self) -> None:
        if self._undo:
            cmd = self._undo.pop()
            cmd.undo()
            self._redo.append(cmd)

    def redo(self) -> None:
        if self._redo:
            cmd = self._redo.pop()
            cmd.redo()
            self._undo.append(cmd)

    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def clear(self) -> None:
        self._undo.clear()
        self._redo.clear()
        self._macro = None


# ── Node commands ─────────────────────────────────────────────────────────────

class NodeAddCmd(Command):
    def __init__(self, runtime: "GraphRuntime", node: "NodeBase") -> None:
        self._rt = runtime
        self._node = node
        self.description = f"Add {node.NODE_NAME}"

    def undo(self) -> None:
        self._rt.remove_node(self._node.node_id)

    def redo(self) -> None:
        self._rt.add_node(self._node)


class NodeDeleteCmd(Command):
    """Captures a single node deletion with all connected wires at deletion time."""

    def __init__(self, runtime: "GraphRuntime", node: "NodeBase",
                 wires: list["WireDescriptor"],
                 groups: dict,
                 group_membership: set[str]) -> None:
        self._rt = runtime
        self._node = node
        self._wires = list(wires)
        self._groups = groups
        self._group_membership = set(group_membership)
        self.description = f"Delete {node.NODE_NAME}"

    def undo(self) -> None:
        self._rt.add_node(self._node)
        for w in self._wires:
            self._rt.add_wire(w)
        # Restore group membership
        for gid in self._group_membership:
            grp = self._groups.get(gid)
            if grp:
                grp.node_ids.add(self._node.node_id)

    def redo(self) -> None:
        self._rt.remove_node(self._node.node_id)


class NodeMoveCmd(Command):
    """Records node position changes after a drag ends."""

    def __init__(self, runtime: "GraphRuntime",
                 moves: dict[str, tuple[float, float, float, float]]) -> None:
        # moves: node_id → (x_before, y_before, x_after, y_after)
        self._rt = runtime
        self._moves = moves
        self.description = "Move node(s)"

    def undo(self) -> None:
        for nid, (xb, yb, _, _) in self._moves.items():
            n = self._rt.get_node(nid)
            if n:
                n.x, n.y = xb, yb

    def redo(self) -> None:
        for nid, (_, _, xa, ya) in self._moves.items():
            n = self._rt.get_node(nid)
            if n:
                n.x, n.y = xa, ya


class NodeRenameCmd(Command):
    def __init__(self, runtime: "GraphRuntime", node_id: str,
                 old_name: str | None, new_name: str | None) -> None:
        self._rt = runtime
        self._node_id = node_id
        self._old = old_name
        self._new = new_name
        self.description = "Rename node"

    def _apply(self, name: str | None) -> None:
        node = self._rt.get_node(self._node_id)
        if node:
            node.custom_name = name
            node.node_changed.emit()

    def undo(self) -> None:
        self._apply(self._old)

    def redo(self) -> None:
        self._apply(self._new)


# ── Field commands ────────────────────────────────────────────────────────────

class FieldEditCmd(Command):
    def __init__(self, runtime: "GraphRuntime", node_id: str,
                 field_name: str, is_var: bool, old_val, new_val) -> None:
        self._rt = runtime
        self._node_id = node_id
        self._field_name = field_name
        self._is_var = is_var
        self._old = old_val
        self._new = new_val
        self.description = f"Edit {field_name}"

    def _apply(self, val) -> None:
        node = self._rt.get_node(self._node_id)
        if node:
            if self._is_var:
                node.set_var_input(self._field_name, val)
            else:
                node.set_field(self._field_name, val)

    def undo(self) -> None:
        self._apply(self._old)

    def redo(self) -> None:
        self._apply(self._new)


# ── Wire commands ─────────────────────────────────────────────────────────────

class WireAddCmd(Command):
    def __init__(self, runtime: "GraphRuntime", wire: "WireDescriptor") -> None:
        self._rt = runtime
        self._wire = wire
        self.description = "Add wire"

    def undo(self) -> None:
        self._rt.remove_wire(self._wire.wire_id)

    def redo(self) -> None:
        self._rt.add_wire(self._wire)


class WireDeleteCmd(Command):
    def __init__(self, runtime: "GraphRuntime", wire: "WireDescriptor") -> None:
        self._rt = runtime
        self._wire = wire
        self.description = "Delete wire"

    def undo(self) -> None:
        self._rt.add_wire(self._wire)

    def redo(self) -> None:
        self._rt.remove_wire(self._wire.wire_id)


# ── Group commands ────────────────────────────────────────────────────────────

class GroupCreateCmd(Command):
    def __init__(self, groups: dict, group) -> None:
        self._groups = groups
        self._group = group
        self.description = "Create group"

    def undo(self) -> None:
        self._groups.pop(self._group.group_id, None)

    def redo(self) -> None:
        self._groups[self._group.group_id] = self._group


class GroupDeleteCmd(Command):
    """Captures a group deletion including all contained nodes and their wires."""

    def __init__(self, runtime: "GraphRuntime", groups: dict, group,
                 nodes: list["NodeBase"],
                 wires: list["WireDescriptor"]) -> None:
        self._rt = runtime
        self._groups = groups
        self._group = group
        self._original_node_ids = set(group.node_ids)   # snapshot before signals clear it
        self._nodes = list(nodes)
        self._wires = list(wires)
        self.description = f"Delete group '{group.name}'"

    def undo(self) -> None:
        for node in reversed(self._nodes):
            self._rt.add_node(node)
        for w in self._wires:
            self._rt.add_wire(w)
        self._group.node_ids = set(self._original_node_ids)
        self._groups[self._group.group_id] = self._group

    def redo(self) -> None:
        for node in self._nodes:
            self._rt.remove_node(node.node_id)   # cascades wires + clears group node_ids
        self._groups.pop(self._group.group_id, None)


class GroupMoveCmd(Command):
    """Records a group + contained-node move after drag ends."""

    def __init__(self, runtime: "GraphRuntime", groups: dict, group_id: str,
                 grp_before: tuple[float, float], grp_after: tuple[float, float],
                 node_moves: dict[str, tuple[float, float, float, float]]) -> None:
        self._rt = runtime
        self._groups = groups
        self._group_id = group_id
        self._grp_before = grp_before
        self._grp_after = grp_after
        self._node_moves = node_moves
        self.description = "Move group"

    def _apply(self, grp_xy: tuple[float, float],
               node_xys: dict[str, tuple[float, float]]) -> None:
        grp = self._groups.get(self._group_id)
        if grp:
            grp.x, grp.y = grp_xy
        for nid, (x, y) in node_xys.items():
            node = self._rt.get_node(nid)
            if node:
                node.x, node.y = x, y

    def undo(self) -> None:
        node_xys = {nid: (xb, yb) for nid, (xb, yb, _, _) in self._node_moves.items()}
        self._apply(self._grp_before, node_xys)

    def redo(self) -> None:
        node_xys = {nid: (xa, ya) for nid, (_, _, xa, ya) in self._node_moves.items()}
        self._apply(self._grp_after, node_xys)


class GroupResizeCmd(Command):
    """Records a group geometry change after resize ends."""

    def __init__(self, groups: dict, group_id: str,
                 before: tuple[float, float, float, float],
                 after: tuple[float, float, float, float]) -> None:
        self._groups = groups
        self._group_id = group_id
        self._before = before
        self._after = after
        self.description = "Resize group"

    def _apply(self, xywh: tuple[float, float, float, float]) -> None:
        grp = self._groups.get(self._group_id)
        if grp:
            grp.x, grp.y, grp.width, grp.height = xywh

    def undo(self) -> None:
        self._apply(self._before)

    def redo(self) -> None:
        self._apply(self._after)


class GroupRenameCmd(Command):
    def __init__(self, groups: dict, group_id: str,
                 old_name: str, new_name: str) -> None:
        self._groups = groups
        self._group_id = group_id
        self._old = old_name
        self._new = new_name
        self.description = "Rename group"

    def _apply(self, name: str) -> None:
        grp = self._groups.get(self._group_id)
        if grp:
            grp.name = name

    def undo(self) -> None:
        self._apply(self._old)

    def redo(self) -> None:
        self._apply(self._new)


# ── Paste command ─────────────────────────────────────────────────────────────

class PasteCmd(Command):
    """Captures a paste/duplicate operation (multiple nodes + wires + optional group)."""

    def __init__(self, runtime: "GraphRuntime", groups: dict,
                 nodes: list["NodeBase"],
                 wires: list["WireDescriptor"],
                 group=None) -> None:
        self._rt = runtime
        self._groups = groups
        self._nodes = list(nodes)
        self._wires = list(wires)
        self._group = group
        self._group_node_ids = set(group.node_ids) if group else set()
        self.description = "Paste"

    def undo(self) -> None:
        if self._group:
            self._groups.pop(self._group.group_id, None)
        for node in self._nodes:
            self._rt.remove_node(node.node_id)   # cascades wires

    def redo(self) -> None:
        for node in self._nodes:
            self._rt.add_node(node)
        for wire in self._wires:
            self._rt.add_wire(wire)
        if self._group:
            self._group.node_ids = set(self._group_node_ids)
            self._groups[self._group.group_id] = self._group


# ── Device commands ───────────────────────────────────────────────────────────

class DeviceSelectCmd(Command):
    """Records a device selection change on a DeviceNodeBase."""

    def __init__(self, node, old_device_id: str | None,
                 new_device_id: str | None) -> None:
        self._node = node
        self._old = old_device_id
        self._new = new_device_id
        self.description = "Select device"

    def _apply(self, device_id: str | None) -> None:
        if device_id is not None:
            self._node.select_device(device_id)

    def undo(self) -> None:
        self._apply(self._old)

    def redo(self) -> None:
        self._apply(self._new)


class DeviceCycleCmd(Command):
    """Records a device cycle action (double-click on DeviceNodeBase)."""

    def __init__(self, node, old_device_id: str | None) -> None:
        self._node = node
        self._old = old_device_id
        self.description = "Cycle device"

    def undo(self) -> None:
        if self._old is not None:
            self._node.select_device(self._old)

    def redo(self) -> None:
        self._node.cycle_device()


class CtrlPropCmd(Command):
    """Undo/redo a ctrl-property setter call (e.g. set_ctrl_color, set_ctrl_range)."""

    def __init__(self, runtime: "GraphRuntime", node_id: str,
                 setter_name: str, old_val, new_val, desc: str = "") -> None:
        self._rt = runtime
        self._node_id = node_id
        self._setter_name = setter_name
        self._old = old_val
        self._new = new_val
        self.description = desc or setter_name

    def _apply(self, val) -> None:
        node = self._rt.get_node(self._node_id)
        if node:
            setter = getattr(node, self._setter_name, None)
            if setter:
                setter(*val) if isinstance(val, tuple) else setter(val)

    def undo(self) -> None:
        self._apply(self._old)

    def redo(self) -> None:
        self._apply(self._new)
