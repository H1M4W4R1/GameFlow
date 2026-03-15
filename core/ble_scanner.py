"""
BLEScanner — discovers nearby BLE devices and identifies Lovense toys.

Runs bleak's BleakScanner in a background asyncio loop and emits Qt signals
when devices are found or the scan finishes.

Usage:
    scanner = BLEScanner(device_classes)
    scanner.device_found.connect(my_slot)   # (address, name, class_key, rssi)
    scanner.scan_finished.connect(...)
    scanner.scan_error.connect(...)
    scanner.start(timeout_s=10.0)           # non-blocking
    scanner.stop()

Identification priority:
  1. BLE advertisement name:  "LVS-<suffix>"  →  lookup suffix in BLE_NAME_TO_IDENTIFIER
  2. BLE service UUIDs advertised in scan response
  3. After connecting: DeviceType; command response (done by _LovenseBLEBase)
"""
from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any, Optional

from PyQt6.QtCore import QObject, pyqtSignal

log = logging.getLogger(__name__)


class DiscoveredDevice:
    """Metadata about a BLE device found during scanning."""
    __slots__ = ("address", "name", "rssi", "class_key", "device_name",
                 "uuids", "manufacturer_data")

    def __init__(
        self,
        address:           str,
        name:              str,
        rssi:              int,
        class_key:         str,
        device_name:       str,
        uuids:             list[str],
        manufacturer_data: dict,
    ) -> None:
        self.address           = address
        self.name              = name
        self.rssi              = rssi
        self.class_key         = class_key
        self.device_name       = device_name
        self.uuids             = uuids
        self.manufacturer_data = manufacturer_data

    def __repr__(self) -> str:
        return (f"<DiscoveredDevice name={self.name!r} addr={self.address!r} "
                f"class={self.class_key!r} rssi={self.rssi}>")


class BLEScanner(QObject):
    """
    Wraps bleak BleakScanner with Qt signal emission.

    Signals
    -------
    device_found(DiscoveredDevice)  — fired for each qualifying device
    device_updated(DiscoveredDevice)— fired when RSSI/name updates for known device
    scan_started()
    scan_finished()
    scan_error(str)                 — human-readable error message
    """

    device_found   = pyqtSignal(object)   # DiscoveredDevice
    device_updated = pyqtSignal(object)   # DiscoveredDevice
    scan_started   = pyqtSignal()
    scan_finished  = pyqtSignal()
    scan_error     = pyqtSignal(str)

    def __init__(
        self,
        device_classes: dict,             # class_key → DeviceBase subclass
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._device_classes = device_classes
        self._loop:    Optional[asyncio.AbstractEventLoop] = None
        self._thread:  Optional[threading.Thread]          = None
        self._running: bool = False
        self._found:   dict[str, DiscoveredDevice] = {}   # address → result

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self, timeout_s: float = 10.0) -> None:
        """Start scanning in a background thread. Non-blocking."""
        if self._running:
            return
        self._found.clear()
        self._running = True
        self._loop   = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run_scan,
            args=(timeout_s,),
            daemon=True,
            name="BLEScanner",
        )
        self._thread.start()

    def stop(self) -> None:
        """Request the scanner to stop early."""
        self._running = False
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def results(self) -> list[DiscoveredDevice]:
        return list(self._found.values())

    # ── Background loop ───────────────────────────────────────────────────────

    def _run_scan(self, timeout_s: float) -> None:
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._async_scan(timeout_s))
        except Exception as exc:
            log.error("BLE scan error: %s", exc)
            self.scan_error.emit(str(exc))
        finally:
            self._running = False
            self.scan_finished.emit()

    async def _async_scan(self, timeout_s: float) -> None:
        try:
            from bleak import BleakScanner  # type: ignore
        except ImportError:
            self.scan_error.emit(
                "bleak is not installed.  Run:  pip install bleak"
            )
            return

        self.scan_started.emit()
        log.info("BLE scan started (%.1fs timeout)", timeout_s)

        def _callback(device: Any, advertisement_data: Any) -> None:
            if not self._running:
                return
            self._handle_advertisement(device, advertisement_data)

        async with BleakScanner(detection_callback=_callback):
            await asyncio.sleep(timeout_s)

    def _handle_advertisement(self, device: Any, adv: Any) -> None:
        """Filter and classify each advertisement callback."""
        name = device.name or adv.local_name or ""
        addr = device.address or ""
        rssi = getattr(adv, "rssi", getattr(device, "rssi", 0)) or 0

        # Primary filter: must match Lovense name prefixes or advertise a known service
        from devices.lovense._base import BLE_NAME_PREFIXES, BLE_SERVICE_UUIDS

        name_match    = any(name.upper().startswith(p.upper()) for p in BLE_NAME_PREFIXES)
        adv_uuids     = [str(u).lower() for u in (adv.service_uuids or [])]
        service_match = any(u in adv_uuids for u in
                            [s.lower() for s in BLE_SERVICE_UUIDS[:2]])  # only static ones

        if not (name_match or service_match):
            return

        class_key, device_display_name = self._identify(name, adv_uuids)

        disc = DiscoveredDevice(
            address           = addr,
            name              = name,
            rssi              = rssi,
            class_key         = class_key,
            device_name       = device_display_name,
            uuids             = adv_uuids,
            manufacturer_data = dict(adv.manufacturer_data or {}),
        )

        if addr in self._found:
            # Update RSSI / name if changed
            existing = self._found[addr]
            if existing.rssi != rssi or existing.class_key != class_key:
                self._found[addr] = disc
                self.device_updated.emit(disc)
        else:
            self._found[addr] = disc
            log.info("Found Lovense device: %s @ %s (class=%s rssi=%d)",
                     name, addr, class_key, rssi)
            self.device_found.emit(disc)

    def _identify(self, name: str, adv_uuids: list[str]) -> tuple[str, str]:
        """
        Return (class_key, display_name) for a discovered device.

        Identification cascade:
          1. Parse 'LVS-<model><fw>' name → look up model in BLE_NAME_TO_IDENTIFIER
          2. Match service UUIDs against known profiles
          3. Fallback: return first BLE device class

        Returns ("", name) if no class can be identified.
        """
        from devices.lovense._base import BLE_NAME_TO_IDENTIFIER, BLE_SERVICE_UUIDS

        identifier: Optional[str] = None
        display     = name

        # Step 1 — name-based identification
        name_upper = name.upper()
        for prefix in ("LVS-", "LOVE-"):
            if name_upper.startswith(prefix):
                suffix = name[len(prefix):]         # e.g. "Z011" or "Edge36"
                # Strip trailing firmware digits
                model_part = suffix.rstrip("0123456789")
                if model_part.upper() in {k.upper(): k for k in BLE_NAME_TO_IDENTIFIER}:
                    # Case-insensitive lookup
                    lookup = {k.upper(): v for k, v in BLE_NAME_TO_IDENTIFIER.items()}
                    identifier = lookup.get(model_part.upper())
                break

        # Step 2 — service-UUID-based identification (Gen1 vs Gen2)
        # We can't distinguish individual device models from service UUIDs alone
        # so we skip this for class identification; just confirm it's Lovense.

        if identifier is None:
            # Unknown Lovense device — return empty class_key; caller will
            # let user pick manually from the tile grid.
            return ("", display)

        # Match identifier → device class
        for key, cls in self._device_classes.items():
            dev_id = getattr(cls, "DEVICE_IDENTIFIER", "")
            if isinstance(dev_id, str) and dev_id.upper() == identifier.upper():
                return (key, cls.DEVICE_NAME)

        return ("", display)
