"""
DeviceNodeBase — base for nodes tightly coupled to a DeviceBase instance.

Multi-device support
--------------------
Multiple devices of the same type (e.g. two Domi wands) are supported via a
per-node "device_id" EDITABLE_FIELD.  The field is rendered as a dropdown-style
row inside the node body showing the user-assigned device name.

When only one device of a given type is connected the field is hidden and that
device is used automatically.  When 2+ are connected the user double-clicks the
field to cycle through them (or the dropdown opens).

Device naming
-------------
Devices get a user-editable alias stored in DeviceRegistry._device_aliases.
The alias defaults to  "<DeviceName> #N"  (e.g. "Domi #1", "Domi #2").
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui  import QPainter, QColor, QFont, QPen, QBrush

from core.node_base  import NodeBase
from core.device_base import DeviceBase
from core.types import DeviceStatus, PinDescriptor, PinDirection, PinType

log = logging.getLogger(__name__)

# ── Global registry: type_key → ordered list of live DeviceBase instances ────
# List preserves connection order; index 0 = first connected.
_DEVICE_INSTANCES: dict[str, list[DeviceBase]] = {}


def register_device_instance(type_key: str, device: DeviceBase) -> None:
    lst = _DEVICE_INSTANCES.setdefault(type_key, [])
    # Avoid duplicates (e.g. on reconnect)
    if not any(d.device_id == device.device_id for d in lst):
        lst.append(device)


def unregister_device_instance(type_key: str, device_id: str) -> None:
    lst = _DEVICE_INSTANCES.get(type_key, [])
    _DEVICE_INSTANCES[type_key] = [d for d in lst if d.device_id != device_id]


def get_instances(type_key: str) -> list[DeviceBase]:
    return _DEVICE_INSTANCES.get(type_key, [])


def get_type_key_for_device(device_id: str) -> Optional[str]:
    """Return the DEVICE_TYPE_KEY for the registry that contains device_id."""
    for type_key, instances in _DEVICE_INSTANCES.items():
        if any(d.device_id == device_id for d in instances):
            return type_key
    return None


# ── Device alias store (device_id → display name) ────────────────────────────
_DEVICE_ALIASES: dict[str, str] = {}


def set_device_alias(device_id: str, name: str) -> None:
    _DEVICE_ALIASES[device_id] = name


def get_device_alias(device: DeviceBase) -> str:
    return _DEVICE_ALIASES.get(device.device_id, device.DEVICE_NAME)


def get_or_create_alias(device: DeviceBase, type_key: str) -> str:
    """Return existing alias or generate 'DeviceName #N' for new devices."""
    if device.device_id in _DEVICE_ALIASES:
        return _DEVICE_ALIASES[device.device_id]
    # Count how many devices of this type were added before this one
    instances = get_instances(type_key)
    idx = next((i for i, d in enumerate(instances)
                if d.device_id == device.device_id), 0)
    alias = f"{device.DEVICE_NAME} #{idx + 1}"
    _DEVICE_ALIASES[device.device_id] = alias
    return alias


# ── DeviceNodeBase ────────────────────────────────────────────────────────────

class DeviceNodeBase(NodeBase):
    """
    Base for device-specific graph nodes.

    Set in subclass:
        DEVICE_TYPE_KEY = "devices.lovense.vibrators.LovenseDomi"
        ICON_PATH       = "assets/icons/lovense/domi.svg"
        NODE_NAME       = "Domi: Vibrate"
        NODE_GROUP      = "Lovense/Domi"
        PINS            = [...]

    Reads / writes the bound device via:
        self.get_device()   → DeviceBase | None  (respects _selected_device_id)
    """

    DEVICE_TYPE_KEY: Optional[str] = None

    # ── Device selection ──────────────────────────────────────────────────────

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # device_id of the currently selected device instance.
        # "" means "use the first available" (auto-select for single-device setups).
        self._selected_device_id: str = ""

    def get_device(self) -> Optional[DeviceBase]:
        """Return the bound DeviceBase instance, or None if unavailable."""
        if not self.DEVICE_TYPE_KEY:
            return None
        instances = get_instances(self.DEVICE_TYPE_KEY)
        if not instances:
            return None
        # If a specific device was selected, find it
        if self._selected_device_id:
            match = next((d for d in instances
                          if d.device_id == self._selected_device_id), None)
            if match:
                return match
        # Fall back to first available
        return instances[0]

    def select_device(self, device_id: str) -> None:
        self._selected_device_id = device_id
        self.node_changed.emit()

    def cycle_device(self) -> None:
        """Cycle to the next connected instance of this device type."""
        if not self.DEVICE_TYPE_KEY:
            return
        instances = get_instances(self.DEVICE_TYPE_KEY)
        if len(instances) <= 1:
            return
        ids = [d.device_id for d in instances]
        try:
            cur_idx = ids.index(self._selected_device_id)
            self._selected_device_id = ids[(cur_idx + 1) % len(ids)]
        except ValueError:
            self._selected_device_id = ids[0]
        self.node_changed.emit()

    def device_status(self) -> DeviceStatus:
        dev = self.get_device()
        return dev.status if dev else DeviceStatus.DISCONNECTED

    def send_to_device(
        self,
        command: str,
        params: Optional[dict[str, Any]] = None,
        on_success=None,
        on_failure=None,
    ) -> None:
        dev = self.get_device()
        if dev is None or dev.status == DeviceStatus.DISCONNECTED:
            log.warning("[%s] Cannot send '%s': device unavailable",
                        self.NODE_NAME, command)
            return
        dev.send_command(command, params, on_success, on_failure)

    # ── State persistence ─────────────────────────────────────────────────────

    def get_state(self) -> dict[str, Any]:
        state = super().get_state()
        state["__selected_device_id__"] = self._selected_device_id
        return state

    def set_state(self, state: dict[str, Any]) -> None:
        self._selected_device_id = state.pop("__selected_device_id__", "")
        super().set_state(state)

    # ── Visual ────────────────────────────────────────────────────────────────

    def paint_device_status(self, painter: QPainter, rect: QRectF) -> None:
        """Status dot in top-right of title bar."""
        status = self.device_status()
        color  = QColor(_STATUS_COLOR[status])

        dot_r = 5.0
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(color))
        painter.drawEllipse(
            QRectF(rect.right() - dot_r * 2 - 4,
                   rect.top()  + (rect.height() - dot_r * 2) / 2,
                   dot_r * 2, dot_r * 2)
        )


_STATUS_COLOR: dict[DeviceStatus, str] = {
    DeviceStatus.CONNECTED:    "#4caf50",
    DeviceStatus.UNKNOWN:      "#ffb300",
    DeviceStatus.DISCONNECTED: "#616161",
}
