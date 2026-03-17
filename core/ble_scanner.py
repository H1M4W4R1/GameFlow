"""
BLEScanner — generic BLE advertisement scanner, device-class-aware.

Collects advertisements from ALL nearby BLE devices and classifies them
against the full registry of known device classes.

Each DeviceBase subclass may declare:
    BLE_NAME_PREFIXES : tuple[str, ...]  — advertisement name prefixes
    BLE_SERVICE_UUID  : str              — primary GATT service UUID
    DEVICE_IDENTIFIER : str              — short id within a device family

Classification cascade (most-specific first):
  1. Exact BLE_NAME_PREFIXES match  → maps directly to that device class
  2. Advertised GATT service UUID   → maps to the class with that BLE_SERVICE_UUID
  3. Family-level name matching     → Lovense LVS- prefix parsing
  4. Unknown                        → class_key = ""

Signals
-------
device_found(DiscoveredDevice)   — new device seen
device_updated(DiscoveredDevice) — RSSI/name updated for known device
scan_started()
scan_finished()
scan_error(str)
"""
from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any, Optional

from PyQt6.QtCore import QObject, pyqtSignal

from core.localization import tr

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
    Generic BLE scanner — classifies devices from all registered device classes,
    not just Lovense.

    Parameters
    ----------
    device_classes : dict[class_key, DeviceBase subclass]
        Full registry of known device classes.  Used to build prefix/UUID
        lookup tables at scan start.
    """

    device_found   = pyqtSignal(object)   # DiscoveredDevice
    device_updated = pyqtSignal(object)   # DiscoveredDevice
    scan_started   = pyqtSignal()
    scan_finished  = pyqtSignal()
    scan_error     = pyqtSignal(str)

    def __init__(
        self,
        device_classes: dict,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._device_classes = device_classes
        self._loop:    Optional[asyncio.AbstractEventLoop] = None
        self._thread:  Optional[threading.Thread]          = None
        self._running: bool = False
        self._found:   dict[str, DiscoveredDevice] = {}

        # Built once per scan from device_classes
        self._prefix_map:  dict[str, str] = {}   # name_prefix_upper → class_key
        self._prefix_list: list[tuple[str, str]] = []  # sorted descending by length
        self._service_map: dict[str, str] = {}   # service_uuid_lower → class_key

    # ── Public API ─────────────────────────────────────────────────────────────

    def start(self, timeout_s: float = 10.0) -> None:
        """Start scanning in a background thread. Non-blocking."""
        if self._running:
            return
        self._found.clear()
        self._build_lookup_tables()
        self._running = True
        self._loop    = asyncio.new_event_loop()
        self._thread  = threading.Thread(
            target=self._run_scan,
            args=(timeout_s,),
            daemon=True,
            name="BLEScanner",
        )
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def results(self) -> list[DiscoveredDevice]:
        return list(self._found.values())

    # ── Lookup tables ───────────────────────────────────────────────────────────

    def _build_lookup_tables(self) -> None:
        """
        Build prefix → class_key and service_uuid → class_key maps from
        the full device registry.  Runs once per scan so new devices added
        at runtime are picked up.
        """
        self._prefix_map.clear()
        self._service_map.clear()

        for key, cls in self._device_classes.items():
            # Name prefix(es)
            prefixes = getattr(cls, "BLE_NAME_PREFIXES", ())
            for pfx in prefixes:
                self._prefix_map[pfx.upper()] = key

            # Primary GATT service UUID
            svc = getattr(cls, "BLE_SERVICE_UUID", None)
            if svc:
                self._service_map[svc.lower()] = key

        # Sort longest-first so "LVS-Z" beats "LVS-" when both match
        self._prefix_list = sorted(
            self._prefix_map.items(), key=lambda kv: -len(kv[0])
        )
        log.debug("BLEScanner lookup: %d prefixes, %d service UUIDs",
                  len(self._prefix_map), len(self._service_map))

    # ── Background loop ─────────────────────────────────────────────────────────

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
            self.scan_error.emit(tr("core.ble.no_bleak"))
            return

        self.scan_started.emit()
        log.info("BLE scan started (%.1fs timeout)", timeout_s)

        def _callback(device: Any, adv: Any) -> None:
            if not self._running:
                return
            self._handle_advertisement(device, adv)

        async with BleakScanner(detection_callback=_callback):
            await asyncio.sleep(timeout_s)

    def _handle_advertisement(self, device: Any, adv: Any) -> None:
        """
        Classify a BLE advertisement against all known device classes.

        Step 1 — name prefix match:
            Check device.name against every BLE_NAME_PREFIXES entry in every
            registered device class.  This is the most reliable signal on all
            platforms (Windows/Linux/macOS all include the name).

        Step 2 — GATT service UUID match:
            Some devices advertise their service UUID.  Cross-reference against
            every class's BLE_SERVICE_UUID.  Less reliable (many platforms
            require a bonded scan to receive service UUIDs).

        Step 3 — Unknown:
            Emit class_key="" so the UI can still show the device and let the
            user pick a class manually.
        """
        name = (device.name or "").strip() or (getattr(adv, "local_name", None) or "").strip()
        addr = device.address or ""
        rssi = int(getattr(adv, "rssi", None) or getattr(device, "rssi", None) or -100)
        adv_uuids = [str(u).lower() for u in (getattr(adv, "service_uuids", None) or [])]

        # ── Step 1: name prefix ────────────────────────────────────────────────
        class_key    = ""
        display_name = name or addr

        name_upper = name.upper()
        for prefix, key in self._prefix_list:  # longest-first for specificity
            if name_upper.startswith(prefix):
                class_key = key
                cls = self._device_classes.get(key)
                display_name = cls.DEVICE_NAME if cls else name
                break

        # ── Step 2: GATT service UUID ──────────────────────────────────────────
        if not class_key:
            for svc_uuid in adv_uuids:
                if svc_uuid in self._service_map:
                    class_key = self._service_map[svc_uuid]
                    cls = self._device_classes.get(class_key)
                    display_name = cls.DEVICE_NAME if cls else name
                    break

        # ── Only emit if we matched a known device ─────────────────────────────
        if not class_key:
            return

        disc = DiscoveredDevice(
            address           = addr,
            name              = name or addr,
            rssi              = rssi,
            class_key         = class_key,
            device_name       = display_name,
            uuids             = adv_uuids,
            manufacturer_data = dict(getattr(adv, "manufacturer_data", None) or {}),
        )

        if addr in self._found:
            existing = self._found[addr]
            if existing.rssi != rssi or existing.class_key != class_key:
                self._found[addr] = disc
                self.device_updated.emit(disc)
        else:
            self._found[addr] = disc
            log.info("Found device: %r  %s  class=%s  rssi=%d dBm",
                     name, addr, class_key, rssi)
            self.device_found.emit(disc)
