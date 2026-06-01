"""
DeviceRegistry — scans /devices/ and /nodes/ for subclasses, manages live instances.
"""
from __future__ import annotations

import importlib
import importlib.util
import logging
import sys
from pathlib import Path
from typing import Optional, Type

from PyQt6.QtCore import QObject, pyqtSignal

from core.device_base import DeviceBase
from core.node_base import NodeBase
from core.types import ConnectionDescriptor, DeviceStatus

log = logging.getLogger(__name__)


class DeviceRegistry(QObject):
    """
    • Auto-discovers DeviceBase subclasses from the /devices/ package.
    • Auto-discovers NodeBase subclasses from the /nodes/ package.
    • Manages live DeviceBase instances and notifies the UI on status changes.
    """

    device_added    = pyqtSignal(str)          # device_id
    device_removed  = pyqtSignal(str)          # device_id
    device_status   = pyqtSignal(str, object)  # device_id, DeviceStatus
    log_message     = pyqtSignal(str)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        # type_name → class
        self._device_classes: dict[str, Type[DeviceBase]] = {}
        self._node_classes:   dict[str, Type[NodeBase]]   = {}
        # device_id → instance
        self._devices: dict[str, DeviceBase] = {}
        # device_id → class_key (needed for persistence)
        self._device_class_keys: dict[str, str] = {}

    # ── Discovery ─────────────────────────────────────────────────────────────

    def discover(self, devices_path: Path, nodes_path: Path, plugins_path: Optional[Path] = None) -> None:
        self._discover_devices(devices_path)
        self._discover_nodes(nodes_path)
        if plugins_path is not None:
            self._discover_devices(plugins_path)
            self._discover_nodes(plugins_path)

    def _discover_devices(self, path: Path) -> None:
        for cls in _load_subclasses(path, DeviceBase):
            key = f"{cls.__module__}.{cls.__name__}"
            self._device_classes[key] = cls
            log.info("Discovered device: %s (%s)", cls.DEVICE_NAME, key)

    def _discover_nodes(self, path: Path) -> None:
        for cls in _load_subclasses(path, NodeBase):
            if cls.__name__.startswith("_"):
                continue   # skip internal base classes
            key = f"{cls.__module__}.{cls.__name__}"
            self._node_classes[key] = cls
            log.info("Discovered node: %s (%s)", cls.NODE_NAME, key)

    # ── Device management ─────────────────────────────────────────────────────

    def create_device(
        self,
        class_key:   str,
        descriptor:  ConnectionDescriptor,
        device_id:   Optional[str] = None,
        alias:       Optional[str] = None,
    ) -> Optional[DeviceBase]:
        cls = self._device_classes.get(class_key)
        if not cls:
            log.error("Unknown device class: %s", class_key)
            return None

        device = cls(descriptor=descriptor, device_id=device_id)

        # Register alias
        from core.device_node_base import (
            set_device_alias, get_or_create_alias, register_device_instance,
        )
        if alias:
            set_device_alias(device.device_id, alias)
        else:
            # Will auto-assign "DeviceName #N" on first call to get_or_create_alias
            get_or_create_alias(device, class_key)

        device.status_changed.connect(
            lambda status, did=device.device_id: self.device_status.emit(did, status)
        )
        device.log_message.connect(self.log_message)
        self._devices[device.device_id] = device
        self._device_class_keys[device.device_id] = class_key
        device.connect_device()
        self.device_added.emit(device.device_id)
        return device

    def rename_device(self, device_id: str, new_alias: str) -> None:
        from core.device_node_base import set_device_alias
        set_device_alias(device_id, new_alias)

    def remove_device(self, device_id: str) -> None:
        device = self._devices.pop(device_id, None)
        self._device_class_keys.pop(device_id, None)
        if device:
            type_key = f"{device.__class__.__module__}.{device.__class__.__name__}"
            from core.device_node_base import unregister_device_instance
            unregister_device_instance(type_key, device_id)
            device.disconnect_device()
            self.device_removed.emit(device_id)

    def get_device_class_key(self, device_id: str) -> Optional[str]:
        return self._device_class_keys.get(device_id)

    def get_device(self, device_id: str) -> Optional[DeviceBase]:
        return self._devices.get(device_id)

    @property
    def devices(self) -> dict[str, DeviceBase]:
        return dict(self._devices)

    # ── Node class registry ───────────────────────────────────────────────────

    def create_node(self, type_key: str, node_id: Optional[str] = None) -> Optional[NodeBase]:
        cls = self._node_classes.get(type_key)
        if not cls:
            log.error("Unknown node class: %s", type_key)
            return None
        return cls(node_id=node_id)

    @property
    def node_classes(self) -> dict[str, Type[NodeBase]]:
        return dict(self._node_classes)

    @property
    def device_classes(self) -> dict[str, Type[DeviceBase]]:
        return dict(self._device_classes)

    def get_node_menu_structure(self) -> dict[str, list[tuple[str, str]]]:
        """Returns  {group: [(display_name, type_key), ...]}  for the context menu.
        Classes whose __name__ starts with '_' are considered internal and excluded."""
        structure: dict[str, list[tuple[str, str]]] = {}
        for key, cls in self._node_classes.items():
            if cls.__name__.startswith("_"):
                continue   # internal / abstract base class
            group = cls.NODE_GROUP
            if group.startswith("Invalid"):
                continue   # broken / unresolvable node class
            structure.setdefault(cls.display_group(), []).append((cls.display_name(), key))
        return structure


# ---------------------------------------------------------------------------
# Generic subclass loader
# ---------------------------------------------------------------------------

def _load_subclasses(path: Path, base_class: type) -> list[type]:
    """Import all .py files under *path* and collect subclasses of *base_class*."""
    found: list[type] = []
    if not path.exists():
        return found

    # Add parent to sys.path so imports work
    parent = str(path.parent)
    if parent not in sys.path:
        sys.path.insert(0, parent)

    for file_path in _iter_module_files(path):
        module_name = _module_name_for_file(path, file_path)
        try:
            mod = _import_module_from_file(module_name, file_path)
            for attr_name in dir(mod):
                obj = getattr(mod, attr_name)
                if (
                    isinstance(obj, type)
                    and issubclass(obj, base_class)
                    and obj is not base_class
                    and not getattr(obj, "__abstractmethods__", None)
                ):
                    found.append(obj)
        except Exception as exc:
            log.warning("Could not load module %s: %s", module_name, exc)
    return found


def _iter_module_files(path: Path) -> list[Path]:
    return sorted(
        file_path
        for file_path in path.rglob("*.py")
        if file_path.name != "__init__.py"
    )


def _module_name_for_file(root: Path, file_path: Path) -> str:
    relative = file_path.relative_to(root.parent).with_suffix("")
    parts = relative.parts
    if all(part.isidentifier() for part in parts):
        return ".".join(parts)

    fallback = "_".join(_sanitize_module_part(part) for part in parts)
    return f"_gameflow_plugin_{fallback}"


def _sanitize_module_part(part: str) -> str:
    cleaned = "".join(char if char.isalnum() or char == "_" else "_" for char in part)
    if not cleaned or cleaned[0].isdigit():
        cleaned = f"_{cleaned}"
    return cleaned


def _import_module_from_file(module_name: str, file_path: Path):
    if module_name.startswith("_gameflow_plugin_"):
        existing = sys.modules.get(module_name)
        if existing is not None:
            return existing

        spec = importlib.util.spec_from_file_location(module_name, file_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot create import spec for {file_path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module

    return importlib.import_module(module_name)
