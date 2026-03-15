"""
device_persistence.py — save and restore known devices between runs.

Saved to: ~/.sensoryflow/devices.json
Format:
{
  "version": 1,
  "devices": [
    {
      "device_id":  "uuid",
      "class_key":  "devices.lovense.vibrators.LovenseDomi",
      "alias":      "Domi #1",
      "descriptor": {"kind": "ble", "address": "AA:BB:CC:DD:EE:FF", "extra": {}}
    }
  ],
  "aliases": {
    "uuid": "Domi #1"
  }
}
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.device_registry import DeviceRegistry

log = logging.getLogger(__name__)

_CONFIG_DIR  = Path.home() / ".sensoryflow"
_DEVICES_FILE = _CONFIG_DIR / "devices.json"
_FORMAT_VER  = 1


def save_devices(registry: "DeviceRegistry") -> None:
    """Persist all currently known devices (connected or not) to disk."""
    from core.device_node_base import _DEVICE_ALIASES

    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    devices_out = []
    for device_id, device in registry.devices.items():
        class_key = registry.get_device_class_key(device_id) or ""
        alias     = _DEVICE_ALIASES.get(device_id, device.DEVICE_NAME)
        devices_out.append({
            "device_id":  device_id,
            "class_key":  class_key,
            "alias":      alias,
            "descriptor": device.descriptor.to_dict(),
        })

    payload = {
        "version": _FORMAT_VER,
        "devices": devices_out,
        "aliases": dict(_DEVICE_ALIASES),
    }

    try:
        _DEVICES_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        log.info("Saved %d device(s) to %s", len(devices_out), _DEVICES_FILE)
    except Exception as exc:
        log.error("Failed to save devices: %s", exc)


def load_devices(registry: "DeviceRegistry") -> None:
    """Restore and reconnect all previously known devices."""
    if not _DEVICES_FILE.exists():
        return

    try:
        payload = json.loads(_DEVICES_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        log.error("Failed to read devices file: %s", exc)
        return

    if payload.get("version") != _FORMAT_VER:
        log.warning("devices.json version mismatch — skipping restore")
        return

    # Restore aliases first so they're available before devices connect
    from core.device_node_base import set_device_alias, _DEVICE_ALIASES
    for did, alias in payload.get("aliases", {}).items():
        set_device_alias(did, alias)

    from core.types import ConnectionDescriptor
    restored = 0
    for entry in payload.get("devices", []):
        try:
            class_key  = entry["class_key"]
            device_id  = entry["device_id"]
            alias      = entry.get("alias", "")
            descriptor = ConnectionDescriptor.from_dict(entry["descriptor"])
            device = registry.create_device(
                class_key = class_key,
                descriptor = descriptor,
                device_id  = device_id,
                alias      = alias or None,
            )
            if device:
                restored += 1
        except Exception as exc:
            log.warning("Could not restore device %s: %s",
                        entry.get("device_id", "?"), exc)

    log.info("Restored %d device(s) from %s", restored, _DEVICES_FILE)
