"""
Lovense device package.

Exports:
    ALL_DEVICE_CLASSES  — list of all DeviceBase subclasses
    ALL_NODE_CLASSES    — list of all NodeBase subclasses
"""
from __future__ import annotations

from devices.lovense.vibrators    import ALL_DEVICE_CLASSES as _VIB_DEV
from devices.lovense.vibrators    import ALL_NODE_CLASSES   as _VIB_NOD
from devices.lovense.advanced     import ALL_DEVICE_CLASSES as _ADV_DEV
from devices.lovense.advanced     import ALL_NODE_CLASSES   as _ADV_NOD
from devices.lovense.shared_nodes import (
    make_battery_node,
    make_red_light_on_node,
    make_red_light_off_node,
)

# Combine all device classes
ALL_DEVICE_CLASSES = _VIB_DEV + _ADV_DEV

# Generate per-device utility nodes for all devices, then combine
_battery_nodes    = [make_battery_node(cls)       for cls in ALL_DEVICE_CLASSES]
_red_light_nodes  = [n for cls in ALL_DEVICE_CLASSES
                     for n in (make_red_light_on_node(cls), make_red_light_off_node(cls))]
ALL_NODE_CLASSES = _VIB_NOD + _ADV_NOD + _battery_nodes + _red_light_nodes

__all__ = ["ALL_DEVICE_CLASSES", "ALL_NODE_CLASSES"]
