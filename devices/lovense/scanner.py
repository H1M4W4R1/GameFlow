"""
scanner.py — BLE advertisement scanner for Lovense devices.

Uses bleak.BleakScanner to listen for advertisements matching:
  - Name prefix "LVS-" or "LOVE-"
  - Or any of the known Lovense GATT service UUIDs in the advertisement

Name → device class mapping:
  The DeviceType character embedded in the BLE name (e.g. "LVS-A011" → 'A' = Nora)
  is matched against each _LovenseBLEBase subclass's DEVICE_IDENTIFIER.
  Newer toys use full product names (e.g. "LVS-Edge36") which are matched
  against DEVICE_NAME (case-insensitive prefix).

Usage:
    scanner = LovenseScanner(device_classes)
    scanner.device_found.connect(my_slot)   # (name, address, class_key)
    scanner.scan_finished.connect(done_slot)
    scanner.start()
    # ...
    scanner.stop()
"""
from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any, Optional

from PyQt6.QtCore import QObject, pyqtSignal

log = logging.getLogger(__name__)

# All name prefixes Lovense devices advertise under
_NAME_PREFIXES = ("LVS-", "LOVE-")

# All known Lovense GATT service UUIDs (static ones only; variable gen3 too noisy to list)
_LOVENSE_SERVICE_UUIDS = {
    "0000fff0-0000-1000-8000-00805f9b34fb",   # Gen1
    "6e400001-b5a3-f393-e0a9-e50e24dcca9e",   # Gen2 (NUS)
}

# Device identifier → subclass, built lazily from the registry
# Maps single-letter or two-letter DEVICE_IDENTIFIER to class_key
_IDENT_MAP:     dict[str, str] = {}   # e.g. "Z" → "devices.lovense.vibrators.LovenseHush"
_NAME_MAP:      dict[str, str] = {}   # e.g. "edge" → "devices.lovense.advanced.LovenseEdge"
_MAP_BUILT:     bool           = False


def _build_maps(device_classes: dict[str, type]) -> None:
    global _MAP_BUILT
    if _MAP_BUILT:
        return
    for key, cls in device_classes.items():
        ident = getattr(cls, "DEVICE_IDENTIFIER", "")
        name  = getattr(cls, "DEVICE_NAME", "")
        if ident:
            _IDENT_MAP[ident.upper()] = key
        if name:
            _NAME_MAP[name.lower()] = key
    _MAP_BUILT = True


def _classify_advertisement(adv_name: str, device_classes: dict[str, type]) -> Optional[str]:
    """
    Given a BLE advertisement name (e.g. "LVS-Edge36", "LVS-A011"),
    return the class_key of the best-matching Lovense device class, or None.

    Matching strategy (most-specific first):
      1. Strip "LVS-" / "LOVE-" prefix, remove trailing digits (firmware version)
      2. Try full product name match against DEVICE_NAME  (e.g. "edge")
      3. Try single/dual character DEVICE_IDENTIFIER match (e.g. "A" = Nora)
      4. Fall back to generic Lovense base if nothing matched
    """
    _build_maps(device_classes)

    name_upper = adv_name.upper()
    stripped   = ""
    for prefix in ("LVS-", "LOVE-"):
        if name_upper.startswith(prefix):
            stripped = name_upper[len(prefix):]
            break

    if not stripped:
        return None

    # Remove trailing digits (firmware version, e.g. "EDGE36" → "EDGE")
    base = stripped.rstrip("0123456789")

    # 1. Try full name match (case-insensitive)
    if base.lower() in _NAME_MAP:
        return _NAME_MAP[base.lower()]

    # 2. Try two-letter identifier (e.g. "GU" = Gush, "EF" = Exomoon)
    if len(base) >= 2 and base[:2] in _IDENT_MAP:
        return _IDENT_MAP[base[:2]]

    # 3. Try single-letter identifier
    if base and base[0] in _IDENT_MAP:
        return _IDENT_MAP[base[0]]

    # 4. No specific match — return None (caller may show "Unknown Lovense")
    log.debug("Unrecognised Lovense name: %r (base=%r)", adv_name, base)
    return None


# ── Scanner ───────────────────────────────────────────────────────────────────

class LovenseScanner(QObject):
    """
    Wraps bleak.BleakScanner in a background thread and emits Qt signals
    for each Lovense device discovered.

    Signals:
        device_found(adv_name, address, class_key)
            — fired for every new Lovense advertisement seen.
              class_key may be "" if the device model couldn't be identified.
        scan_error(message)
            — fired if bleak raises an exception during scanning.
        scan_finished()
            — fired when stop() is called and the scanner thread exits.
    """

    device_found  = pyqtSignal(str, str, str)   # name, address, class_key
    scan_error    = pyqtSignal(str)
    scan_finished = pyqtSignal()

    def __init__(self, device_classes: dict[str, type],
                 parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._device_classes = device_classes
        self._loop:   Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread]          = None
        self._seen:   set[str] = set()   # addresses already emitted
        self._active: bool     = False

    def start(self) -> None:
        """Begin BLE scanning in a daemon thread."""
        if self._active:
            return
        self._active = True
        self._seen.clear()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="LovenseScanner"
        )
        self._thread.start()

    def stop(self) -> None:
        """Signal the scanner to stop; scan_finished emitted when done."""
        self._active = False
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        try:
            self._loop.run_until_complete(self._scan_loop())
        except Exception as exc:
            log.error("Scanner error: %s", exc)
            self.scan_error.emit(str(exc))
        finally:
            self._loop.close()
            self.scan_finished.emit()

    async def _scan_loop(self) -> None:
        try:
            from bleak import BleakScanner  # type: ignore
        except ImportError:
            self.scan_error.emit(
                "bleak is not installed. Run: pip install bleak"
            )
            return

        def _callback(device: Any, advertisement_data: Any) -> None:
            if not self._active:
                return
            name    = device.name or ""
            address = device.address

            # Filter: name prefix OR known service UUID in advertisement
            is_lovense = any(name.upper().startswith(p) for p in _NAME_PREFIXES)
            if not is_lovense:
                adv_uuids = {
                    str(u).lower()
                    for u in (advertisement_data.service_uuids or [])
                }
                is_lovense = bool(adv_uuids & _LOVENSE_SERVICE_UUIDS)

            if not is_lovense:
                return

            if address in self._seen:
                return
            self._seen.add(address)

            class_key = _classify_advertisement(name, self._device_classes) or ""
            log.info("Lovense found: %r %s → %s", name, address, class_key or "(unknown)")
            self.device_found.emit(name, address, class_key)

        scanner = BleakScanner(detection_callback=_callback)
        await scanner.start()

        # Run until stop() calls loop.stop()
        while self._active:
            await asyncio.sleep(0.2)

        await scanner.stop()
