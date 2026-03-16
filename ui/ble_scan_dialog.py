"""
BLEScanDialog — BLE advertisement scanner for Lovense (and future BLE) devices.

Flow:
  1. Dialog opens with device type pre-selected from the tile picker.
  2. A bleak BleakScanner runs in a background thread, filtering advertisements
     by the known Lovense name prefixes (LVS-*, LOVE-*) and service UUIDs.
  3. Each discovered device appears as a row (name, MAC, RSSI signal bar).
  4. The user can:
       • Click a discovered device row → it is highlighted, "Connect" activates.
       • Click "Scan Again" to restart the scan.
       • Press Escape / click Cancel to abort.
  5. On Connect the dialog resolves the most specific device class key it can
     from the advertisement name, falls back to the pre-selected tile key.

BLE identifier → device class matching:
  "LVS-Z011"   → strip "LVS-", alpha="Z"   → DEVICE_IDENTIFIER "Z" → Hush
  "LVS-Edge36" → strip "LVS-", alpha="Edge" → name lookup "Edge" → P → Edge
  "LOVE-P011"  → strip "LOVE-", alpha="P"   → DEVICE_IDENTIFIER "P" → Edge
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from PyQt6.QtCore   import Qt, QTimer, pyqtSignal, QObject
from PyQt6.QtGui    import QColor, QPainter, QBrush, QPen, QFont
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QWidget, QProgressBar,
)

from core.types import ConnectionDescriptor, PortKind
from core.ble_scanner import BLEScanner, DiscoveredDevice

log = logging.getLogger(__name__)

SCAN_WINDOW_S = 10.0   # bleak scan duration


# ── Data record ───────────────────────────────────────────────────────────────

@dataclass
class BLECandidate:
    address:       str
    name:          str
    rssi:          int           = -100
    service_uuids: list[str]     = field(default_factory=list)
    matched_key:   Optional[str] = None


# ── Thread → Qt signal bridge ────────────────────────────────────────────────

class _Bridge(QObject):
    device_found  = pyqtSignal(object)   # BLECandidate
    scan_finished = pyqtSignal()
    scan_error    = pyqtSignal(str)


# ── RSSI bar ──────────────────────────────────────────────────────────────────

class _RSSIBar(QWidget):
    def __init__(self, rssi: int = -100) -> None:
        super().__init__()
        self._rssi = rssi
        self.setFixedSize(34, 16)

    def set_rssi(self, rssi: int) -> None:
        self._rssi = rssi
        self.update()

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pct    = (max(-100, min(0, self._rssi)) + 100) / 100.0
        bars   = max(1, round(pct * 4))
        cols   = ["#ef5350", "#ffb74d", "#ffb74d", "#4caf50"]
        bw, gap = 6, 2
        for i in range(4):
            bh  = 4 + i * 3
            col = cols[i] if i < bars else "#2d1020"
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(QColor(col)))
            p.drawRoundedRect(i * (bw + gap), 14 - bh, bw, bh, 1, 1)


# ── Candidate row ─────────────────────────────────────────────────────────────

class _CandidateRow(QFrame):
    selected = pyqtSignal(str)   # address

    _S_NORMAL = ("QFrame{background:#220d14;border:1px solid #45072f;"
                 "border-radius:6px;margin:1px 4px;}"
                 "QFrame:hover{border:1px solid #c90084;background:#2d1020;}")
    _S_ACTIVE = ("QFrame{background:#45072f;border:2px solid #f95979;"
                 "border-radius:6px;margin:1px 4px;}")

    def __init__(self, c: BLECandidate) -> None:
        super().__init__()
        self._address = c.address
        self.setStyleSheet(self._S_NORMAL)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(48)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 4, 10, 4)
        lay.setSpacing(8)

        info = QVBoxLayout()
        info.setSpacing(1)
        self._name_lbl = QLabel(c.name or "Unknown")
        self._name_lbl.setStyleSheet(
            "color:#ffd0de;font-weight:bold;font-size:9pt;background:transparent;")
        self._addr_lbl = QLabel(c.address)
        self._addr_lbl.setStyleSheet(
            "color:#7a4060;font-size:7pt;background:transparent;")
        info.addWidget(self._name_lbl)
        info.addWidget(self._addr_lbl)
        lay.addLayout(info, stretch=1)

        self._rssi_bar = _RSSIBar(c.rssi)
        lay.addWidget(self._rssi_bar)
        self._rssi_lbl = QLabel(f"{c.rssi} dBm")
        self._rssi_lbl.setStyleSheet(
            "color:#6b3050;font-size:7pt;background:transparent;min-width:52px;")
        lay.addWidget(self._rssi_lbl)

    def update_rssi(self, rssi: int) -> None:
        self._rssi_bar.set_rssi(rssi)
        self._rssi_lbl.setText(f"{rssi} dBm")

    def set_active(self, v: bool) -> None:
        self.setStyleSheet(self._S_ACTIVE if v else self._S_NORMAL)

    def mousePressEvent(self, _) -> None:
        self.selected.emit(self._address)


# ── Dialog ────────────────────────────────────────────────────────────────────

_DLG_STYLE = """
QDialog,QWidget     { background:#1a0a0f; color:#ffd0de; }
QLabel              { color:#ffd0de; font-size:9pt; background:transparent; }
QProgressBar        { background:#220d14; border:1px solid #45072f;
                      border-radius:3px; }
QProgressBar::chunk { background:#c90084; border-radius:3px; }
QPushButton         { background:#c90084; color:white; border:none;
                      border-radius:4px; padding:6px 16px; font-size:9pt; }
QPushButton:hover   { background:#f95979; }
QPushButton:disabled{ background:#2d1020; color:#5a3040; }
QPushButton#cancel  { background:#45072f; }
QPushButton#cancel:hover { background:#6b3050; }
QScrollBar:vertical { background:#1a0a0f; width:6px; }
QScrollBar::handle:vertical { background:#45072f; border-radius:3px; min-height:20px; }
"""


class BLEScanDialog(QDialog):
    """
    Scans BLE advertisements for Lovense devices and returns a
    (class_key, ConnectionDescriptor) pair on accept.

    Parameters
    ----------
    device_classes  : all registered device classes (for identifier resolution)
    preselected_key : class key from tile picker — fallback if scan can't identify
    """

    AUTO_CONNECT_SINGLE: bool = False   # if True, auto-connects when exactly 1 found

    def __init__(
        self,
        device_classes:  dict,
        preselected_key: str,
        parent           = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Searching for Devices…")
        self.setStyleSheet(_DLG_STYLE)
        self.setMinimumSize(460, 400)

        self._device_classes  = device_classes
        self._preselected_key = preselected_key
        self._candidates:     dict[str, BLECandidate]  = {}
        self._rows:           dict[str, _CandidateRow] = {}
        self._selected_addr:  Optional[str]            = None
        self._result:         Optional[tuple[str, ConnectionDescriptor]] = None
        self._bridge          = _Bridge()
        self._scanner         = None   # BLEScanner instance
        self._scanning        = False

        # Build DEVICE_IDENTIFIER → class_key lookup
        self._ident_to_key: dict[str, str] = {}
        for key, cls in device_classes.items():
            ident = getattr(cls, "DEVICE_IDENTIFIER", "")
            if ident:
                self._ident_to_key[ident.upper()] = key

        self._setup_ui()
        self._bridge.device_found.connect(self._on_device_found)
        self._bridge.scan_finished.connect(self._on_scan_finished)
        self._bridge.scan_error.connect(self._on_scan_error)

        QTimer.singleShot(120, self._start_scan)

    # ── UI ────────────────────────────────────────────────────────────────────

    def _scan_status_text(self) -> str:
        if self._preselected_key and self._preselected_key in self._device_classes:
            cls = self._device_classes[self._preselected_key]
            return f"Searching for {cls.DEVICE_NAME}…"
        return "Scanning for nearby BLE devices…"

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        # Header row
        hrow = QHBoxLayout()
        self._status_lbl = QLabel(self._scan_status_text())
        self._status_lbl.setStyleSheet("font-size:10pt;font-weight:bold;")
        hrow.addWidget(self._status_lbl, stretch=1)
        self._scan_btn = QPushButton("Scan Again")
        self._scan_btn.setEnabled(False)
        self._scan_btn.clicked.connect(self._start_scan)
        hrow.addWidget(self._scan_btn)
        root.addLayout(hrow)

        # Progress bar — indeterminate while scanning
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setFixedHeight(5)
        self._progress.setTextVisible(False)
        root.addWidget(self._progress)

        # Hint text
        self._hint_lbl = QLabel(
            "Make sure your device is turned on and not connected to another app.")
        self._hint_lbl.setStyleSheet("color:#6b3050;font-size:8pt;")
        self._hint_lbl.setWordWrap(True)
        root.addWidget(self._hint_lbl)

        # Divider label
        found_lbl = QLabel("FOUND DEVICES")
        found_lbl.setStyleSheet(
            "color:#45072f;font-size:7pt;letter-spacing:2px;padding-top:4px;")
        root.addWidget(found_lbl)

        # Results scroll list
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setStyleSheet("background:transparent;")
        self._list_w = QWidget()
        self._list_w.setStyleSheet("background:transparent;")
        self._list_lay = QVBoxLayout(self._list_w)
        self._list_lay.setContentsMargins(0, 0, 0, 0)
        self._list_lay.setSpacing(3)
        self._list_lay.addStretch()
        self._empty_lbl = QLabel("No devices found yet…")
        self._empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_lbl.setStyleSheet(
            "color:#4a2030;font-size:9pt;padding:24px;")
        self._list_lay.insertWidget(0, self._empty_lbl)
        self._scroll.setWidget(self._list_w)
        root.addWidget(self._scroll, stretch=1)

        # Bottom buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel = QPushButton("Cancel")
        cancel.setObjectName("cancel")
        cancel.clicked.connect(self.reject)
        self._connect_btn = QPushButton("Connect")
        self._connect_btn.setEnabled(False)
        self._connect_btn.clicked.connect(self._on_connect)
        btn_row.addWidget(cancel)
        btn_row.addWidget(self._connect_btn)
        root.addLayout(btn_row)

    def _scan_status_text(self) -> str:
        """Status message based on preselected device type."""
        if self._preselected_key and self._preselected_key in self._device_classes:
            cls = self._device_classes[self._preselected_key]
            name = getattr(cls, "DEVICE_NAME", "device")
            return f"Scanning for {name}…"
        return "Scanning for nearby BLE devices…"

    # ── Scan logic (background thread) ────────────────────────────────────────

    def _start_scan(self) -> None:
        if self._scanning:
            return
        self._scanning = True
        self._scan_btn.setEnabled(False)
        self._connect_btn.setEnabled(False)
        self._status_lbl.setText(self._scan_status_text())
        self._progress.setRange(0, 0)
        self._hint_lbl.setText(
            "Make sure your device is turned on and not connected to another app.")

        # Use the generic BLEScanner from core — it knows about ALL device classes
        # (Lovense, Coyote, H1M4W4R1, …) via BLE_NAME_PREFIXES / BLE_SERVICE_UUID.
        self._scanner = BLEScanner(self._device_classes)
        self._scanner.device_found.connect(self._on_ble_found)
        self._scanner.device_updated.connect(self._on_ble_updated)
        self._scanner.scan_finished.connect(self._on_scan_finished)
        self._scanner.scan_error.connect(self._on_scan_error)
        self._scanner.start(timeout_s=SCAN_WINDOW_S)

    def _on_ble_found(self, disc) -> None:
        """Convert DiscoveredDevice → BLECandidate and route to existing slot."""
        # If user preselected a specific tile, use that as the matched key
        # as long as the class_key from the scan is either the preselected one
        # or empty (unknown).
        matched = disc.class_key or self._preselected_key or ""
        if self._preselected_key and disc.class_key and disc.class_key != self._preselected_key:
            # Scanner found it belongs to a different device type — trust the scanner
            matched = disc.class_key

        c = BLECandidate(
            address       = disc.address,
            name          = disc.name,
            rssi          = disc.rssi,
            service_uuids = disc.uuids,
            matched_key   = matched,
        )
        self._bridge.device_found.emit(c)

    def _on_ble_updated(self, disc) -> None:
        """Update RSSI for an already-shown device."""
        row = self._rows.get(disc.address)
        if row:
            row.update_rssi(disc.rssi)
            if disc.address in self._candidates:
                self._candidates[disc.address].rssi = disc.rssi

    # ── Qt slot handlers ──────────────────────────────────────────────────────

    def _on_device_found(self, c: BLECandidate) -> None:
        if c.address in self._candidates:
            # Update RSSI on existing row
            self._candidates[c.address].rssi = c.rssi
            row = self._rows.get(c.address)
            if row:
                row.update_rssi(c.rssi)
            return

        self._candidates[c.address] = c
        self._empty_lbl.setVisible(False)

        row = _CandidateRow(c)
        row.selected.connect(self._on_row_selected)
        self._rows[c.address] = row
        self._list_lay.insertWidget(self._list_lay.count() - 1, row)

        # Identify what device type was detected and update title
        if c.matched_key and c.matched_key in self._device_classes:
            cls = self._device_classes[c.matched_key]
            self._status_lbl.setText(
                f"Found: {cls.DEVICE_NAME} — select and click Connect")
        else:
            self._status_lbl.setText(
                f"Found {len(self._candidates)} device(s) — select one")

        # Auto-connect if enabled and exactly one device
        if self.AUTO_CONNECT_SINGLE and len(self._candidates) == 1:
            self._on_row_selected(c.address)
            self._on_connect()

    def _on_scan_finished(self) -> None:
        self._scanning = False
        self._progress.setRange(0, 1)
        self._progress.setValue(1)
        self._scan_btn.setEnabled(True)
        count = len(self._candidates)
        if count == 0:
            self._status_lbl.setText("No devices found.")
            self._hint_lbl.setText(
                "Ensure the device is on, in range, and not paired to another app. "
                "Click Scan Again to retry.")
        else:
            self._hint_lbl.setText("")

    def _on_scan_error(self, msg: str) -> None:
        self._scanning = False
        self._progress.setRange(0, 1)
        self._progress.setValue(0)
        self._scan_btn.setEnabled(True)
        self._status_lbl.setText("Scan failed")
        self._hint_lbl.setText(f"Error: {msg}")
        log.error("BLE scan error: %s", msg)

    def _on_row_selected(self, address: str) -> None:
        old = self._rows.get(self._selected_addr or "")
        if old:
            old.set_active(False)
        self._selected_addr = address
        self._rows[address].set_active(True)
        self._connect_btn.setEnabled(True)

        # Show which device type we matched
        c   = self._candidates[address]
        key = c.matched_key or self._preselected_key
        if key in self._device_classes:
            cls = self._device_classes[key]
            self._status_lbl.setText(
                f"Selected: {cls.DEVICE_NAME}  ({c.address})")

    def _on_connect(self) -> None:
        if not self._selected_addr:
            return
        c         = self._candidates[self._selected_addr]
        class_key = c.matched_key or self._preselected_key
        self._result = (
            class_key,
            ConnectionDescriptor(
                kind    = PortKind.BLE,
                address = self._selected_addr,
                extra   = {"ble_name": c.name},
            ),
        )
        self.accept()

    def result_data(self) -> Optional[tuple[str, ConnectionDescriptor]]:
        return self._result

    def closeEvent(self, event) -> None:
        self._scanning = False
        if self._scanner:
            self._scanner.stop()
        super().closeEvent(event)
