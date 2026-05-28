"""
DevicePanel — left sidebar with device status, battery, and a redesigned
manufacturer-grouped tile-based Add Device dialog.

Layout of the Add Device dialog:
  ┌─────────────────────────────────────────────┐
  │  [Lovense ▼]  [Generic ▼]  [Custom ▼]       │  ← manufacturer tabs
  ├─────────────────────────────────────────────┤
  │  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐       │
  │  │  [L] │ │  [H] │ │  [D] │ │  [E] │  ...  │  ← device tiles
  │  │ Lush │ │ Hush │ │ Domi │ │ Edge │       │
  │  └──────┘ └──────┘ └──────┘ └──────┘       │
  ├─────────────────────────────────────────────┤
  │  BLE Address: [________________]            │
  │                          [Connect] [Cancel] │
  └─────────────────────────────────────────────┘
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QSize, QPoint, QMimeData, pyqtSignal, QRectF
from PyQt6.QtGui  import (
    QColor, QPainter, QBrush, QPen, QFont, QPixmap,
    QIcon, QImage, QDrag,
)
from PyQt6.QtSvgWidgets import QSvgWidget
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QScrollArea, QFrame, QDialog, QLineEdit, QSizePolicy, QGridLayout, QTabWidget,
    QComboBox,
)

from core.device_base import DeviceBase
from core.device_registry import DeviceRegistry
from core.localization import tr, get_current_language, load_language, save_language_pref
from core.types import DeviceStatus, ConnectionDescriptor, PortKind

log = logging.getLogger(__name__)

# Maps language code → (flag emoji, native name)
_LANG_INFO: dict[str, tuple[str, str]] = {
    "EN": ("🇬🇧", "English"),
    "DE": ("🇩🇪", "Deutsch"),
    "FR": ("🇫🇷", "Français"),
    "ES": ("🇪🇸", "Español"),
    "IT": ("🇮🇹", "Italiano"),
    "PT": ("🇵🇹", "Português"),
    "RU": ("🇷🇺", "Русский"),
    "ZH": ("🇨🇳", "中文"),
    "JA": ("🇯🇵", "日本語"),
    "KO": ("🇰🇷", "한국어"),
    "PL": ("🇵🇱", "Polski"),
    "NL": ("🇳🇱", "Nederlands"),
    "SV": ("🇸🇪", "Svenska"),
    "UK": ("🇺🇦", "Українська"),
}

STATUS_COLORS = {
    DeviceStatus.CONNECTED:    "#4caf50",
    DeviceStatus.UNKNOWN:      "#ffb300",
    DeviceStatus.DISCONNECTED: "#616161",
}

_PROJECT_ROOT = Path(__file__).parent.parent
_UNKNOWN_ICON = str(_PROJECT_ROOT / "assets" / "icons" / "unknown.svg")

_DLG_STYLE = """
QDialog, QWidget       { background: #1a0a0f; color: #ffd0de; }
QLabel                 { color: #ffd0de; font-size: 9pt; background: transparent; }
QLineEdit              { background: #220d14; color: #ffd0de; border: 1px solid #45072f;
                         border-radius: 4px; padding: 4px 8px; font-size: 9pt; }
QLineEdit:focus        { border: 1px solid #c90084; }
QTabWidget::pane       { border: 1px solid #45072f; background: #1a0a0f; }
QTabBar::tab           { background: #2d1020; color: #c8889a; padding: 6px 14px;
                         border: 1px solid #45072f; border-bottom: none;
                         border-radius: 4px 4px 0 0; font-size: 9pt; }
QTabBar::tab:selected  { background: #45072f; color: #ffd0de; }
QTabBar::tab:hover     { background: #3d1525; }
QPushButton            { background: #c90084; color: white; border: none;
                         border-radius: 4px; padding: 6px 16px; font-size: 9pt; }
QPushButton:hover      { background: #f95979; }
QPushButton:disabled   { background: #2d1020; color: #5a3040; }
QPushButton#cancel     { background: #45072f; }
QPushButton#cancel:hover { background: #6b3050; }
QScrollBar:vertical    { background: #1a0a0f; width: 6px; }
QScrollBar::handle:vertical { background: #45072f; border-radius: 3px; min-height: 20px; }
"""


# ── Status dot ────────────────────────────────────────────────────────────────

class StatusDot(QWidget):
    def __init__(self, status: DeviceStatus = DeviceStatus.DISCONNECTED) -> None:
        super().__init__()
        self._color = QColor(STATUS_COLORS[status])
        self.setFixedSize(12, 12)

    def set_status(self, status: DeviceStatus) -> None:
        self._color = QColor(STATUS_COLORS[status])
        self.update()

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(self._color.darker(150), 1))
        p.setBrush(QBrush(self._color))
        p.drawEllipse(1, 1, 10, 10)


# ── Battery bar ───────────────────────────────────────────────────────────────

class BatteryWidget(QWidget):
    """Compact battery level display — shows percentage and colour-coded bar."""
    def __init__(self) -> None:
        super().__init__()
        self._level = -1
        self.setFixedSize(36, 14)
        self.setToolTip(tr("ui.panel.devices.battery_unknown"))

    def set_level(self, level: int) -> None:
        self._level = level
        tip = tr("ui.panel.devices.battery").format(level=level) if level >= 0 else tr("ui.panel.devices.battery_unknown_short")
        self.setToolTip(tip)
        self.update()

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        # Outer shell
        p.setPen(QPen(QColor("#45072f"), 1))
        p.setBrush(QColor("#1a0a0f"))
        p.drawRoundedRect(0, 2, w - 4, h - 4, 2, 2)
        # Nub
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#45072f"))
        p.drawRect(w - 4, h // 2 - 2, 3, 4)

        if self._level < 0:
            p.setPen(QColor("#5a3040"))
            p.setFont(QFont("Segoe UI", 6))
            p.drawText(1, 0, w - 5, h, Qt.AlignmentFlag.AlignCenter, "—")
            return

        pct   = self._level / 100.0
        bar_w = max(2, int((w - 6) * pct))
        if self._level <= 20:
            color = QColor("#ef5350")
        elif self._level <= 50:
            color = QColor("#ffb74d")
        else:
            color = QColor("#4caf50")

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        p.drawRoundedRect(2, 4, bar_w, h - 8, 1, 1)

        p.setPen(QColor(255, 255, 255, 160))
        p.setFont(QFont("Segoe UI", 6, QFont.Weight.Bold))
        p.drawText(1, 0, w - 5, h, Qt.AlignmentFlag.AlignCenter,
                   f"{self._level}%")


# ── Device row ────────────────────────────────────────────────────────────────

class DeviceRow(QFrame):
    clicked          = pyqtSignal(str)
    rename_requested = pyqtSignal(str, str)   # device_id, new_alias

    def __init__(self, device_id: str, device_name: str, address: str,
                 icon_path: Optional[str] = None) -> None:
        super().__init__()
        self.device_id    = device_id
        self._rename_editor: Optional[QLineEdit] = None
        self.setObjectName("DeviceRow")
        self.setStyleSheet("""
            QFrame#DeviceRow            { background:#220d14; border:1px solid #45072f;
                                          border-radius:6px; margin:2px 4px; }
            QFrame#DeviceRow:hover      { border:1px solid #c90084; background:#2d1020; }
        """)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(52)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 8, 4)
        layout.setSpacing(6)

        # Icon
        icon_w = _make_icon_widget(icon_path, 36)
        layout.addWidget(icon_w)

        # Status dot
        self._dot = StatusDot()
        layout.addWidget(self._dot)

        # Name + address
        info = QVBoxLayout()
        info.setSpacing(1)
        self._name_lbl = QLabel(device_name)
        self._name_lbl.setStyleSheet(
            "color:#ffd0de;font-weight:bold;font-size:9pt;background:transparent;")
        self._addr_lbl = QLabel(address)
        self._addr_lbl.setStyleSheet(
            "color:#7a4060;font-size:7pt;background:transparent;")
        info.addWidget(self._name_lbl)
        info.addWidget(self._addr_lbl)
        layout.addLayout(info)
        layout.addStretch()

        # Battery
        self._battery = BatteryWidget()
        layout.addWidget(self._battery)

    def set_status(self, status: DeviceStatus) -> None:
        self._dot.set_status(status)

    def set_battery(self, level: int) -> None:
        self._battery.set_level(level)

    def set_alias(self, alias: str) -> None:
        self._name_lbl.setText(alias)

    def set_highlighted(self, active: bool) -> None:
        """Highlight this row when a node linked to this device is selected."""
        if active:
            self.setStyleSheet("""
                QFrame#DeviceRow { background:#2d0f1a; border:1px solid #f95979;
                                   border-radius:6px; margin:2px 4px; }
            """)
        else:
            self.setStyleSheet("""
                QFrame#DeviceRow { background:#220d14; border:1px solid #45072f;
                                   border-radius:6px; margin:2px 4px; }
                QFrame#DeviceRow:hover { border:1px solid #c90084; background:#2d1020; }
            """)

    def mousePressEvent(self, event) -> None:
        self._drag_start = event.position().toPoint()
        self._did_drag   = False

    def mouseMoveEvent(self, event) -> None:
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        if (event.position().toPoint() - self._drag_start).manhattanLength() < 8:
            return
        self._did_drag = True
        mime = QMimeData()
        mime.setText(f"device:{self.device_id}")
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction)

    def mouseReleaseEvent(self, event) -> None:
        if not self._did_drag and self._rename_editor is None:
            # Delay single-click so a double-click can cancel it.
            # Guard: skip if rename editor is active — the double-click sequence
            # fires a second mouseReleaseEvent that would otherwise restart the
            # timer and open the detail dialog on top of the inline editor.
            from PyQt6.QtWidgets import QApplication
            from PyQt6.QtCore import QTimer
            if not hasattr(self, "_click_timer"):
                self._click_timer = QTimer(self)
                self._click_timer.setSingleShot(True)
                self._click_timer.timeout.connect(lambda: self.clicked.emit(self.device_id))
            self._click_timer.start(QApplication.doubleClickInterval())

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            if hasattr(self, "_click_timer"):
                self._click_timer.stop()
            self._start_inline_rename()

    def _start_inline_rename(self) -> None:
        """Replace the name label with an inline QLineEdit for renaming."""
        if self._rename_editor is not None:
            return
        current = self._name_lbl.text()
        self._name_lbl.setVisible(False)

        editor = QLineEdit(current, self)
        editor.setStyleSheet(
            "background:#2d1020; color:#ffd0de; border:1px solid #f95979;"
            "border-radius:3px; padding:0 3px; font-size:9pt; font-weight:bold;"
        )
        # Match the geometry of the name label
        geom = self._name_lbl.geometry()
        editor.setGeometry(geom)
        editor.show()
        editor.setFocus()
        editor.selectAll()
        self._rename_editor = editor

        _committed = [False]

        def _commit() -> None:
            if _committed[0]:
                return
            _committed[0] = True
            text = editor.text().strip()
            if text:
                self._name_lbl.setText(text)
                self.rename_requested.emit(self.device_id, text)
            self._name_lbl.setVisible(True)
            editor.deleteLater()
            self._rename_editor = None

        def _cancel() -> None:
            if _committed[0]:
                return
            _committed[0] = True
            self._name_lbl.setVisible(True)
            editor.deleteLater()
            self._rename_editor = None

        editor.returnPressed.connect(_commit)
        editor.editingFinished.connect(_commit)
        editor.installEventFilter(self)
        self._rename_cancel = _cancel

    def eventFilter(self, obj, event) -> bool:
        from PyQt6.QtCore import QEvent
        if self._rename_editor is not None and obj is self._rename_editor:
            if (event.type() == QEvent.Type.KeyPress
                    and event.key() == Qt.Key.Key_Escape):
                self._rename_cancel()
                return True
        return super().eventFilter(obj, event)


# ── Device panel ──────────────────────────────────────────────────────────────

class DevicePanel(QWidget):
    add_device_requested    = pyqtSignal(str, object)   # class_key, descriptor
    remove_device_requested = pyqtSignal(str)
    rename_device_requested = pyqtSignal(str, str)       # device_id, new_alias
    language_changed        = pyqtSignal(str)            # lang_code

    def __init__(self, registry: DeviceRegistry,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._registry = registry
        self._rows:    dict[str, DeviceRow] = {}
        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self) -> None:
        self.setFixedWidth(230)
        self.setStyleSheet("background:#1a0a0f;")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header
        header = QFrame()
        header.setStyleSheet("background:#45072f;border-bottom:1px solid #c90084;")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(10, 8, 8, 8)
        title = QLabel(tr("ui.panel.devices.title"))
        title.setStyleSheet(
            "color:#ffd0de;font-weight:bold;font-size:10pt;letter-spacing:2px;")
        hl.addWidget(title)
        hl.addStretch()
        add_btn = QPushButton("+")
        add_btn.setFixedSize(24, 24)
        add_btn.setToolTip(tr("ui.panel.devices.add_tooltip"))
        add_btn.setStyleSheet("""
            QPushButton { background:transparent; color:#c8889a; border:none;
                          font-size:16pt; font-weight:bold; padding:0; margin:0; }
            QPushButton:hover { color:#f95979; }
        """)
        add_btn.clicked.connect(self._on_add_clicked)
        hl.addWidget(add_btn)
        root.addWidget(header)

        # BLE status banner (hidden by default, shown if no adapter)
        self._ble_banner = QLabel(tr("ui.panel.devices.no_ble"))
        self._ble_banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._ble_banner.setWordWrap(True)
        self._ble_banner.setStyleSheet(
            "color:#ffb300;font-size:8pt;padding:6px 8px;"
            "background:#2d1a00;border-bottom:1px solid #6b4500;")
        self._ble_banner.setVisible(False)
        root.addWidget(self._ble_banner)
        # Check BLE adapter availability
        self._check_ble_adapter()

        # Scroll list
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setStyleSheet("background:transparent;")
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list_w = QWidget()
        self._list_w.setStyleSheet("background:transparent;")
        self._list_lay = QVBoxLayout(self._list_w)
        self._list_lay.setContentsMargins(0, 6, 0, 6)
        self._list_lay.setSpacing(2)
        self._list_lay.addStretch()
        self._empty_lbl = QLabel(tr("ui.panel.devices.empty"))
        self._empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_lbl.setStyleSheet("color:#6b3050;font-size:9pt;padding:20px;")
        self._list_lay.insertWidget(0, self._empty_lbl)
        self._scroll.setWidget(self._list_w)
        root.addWidget(self._scroll)

        # Language selector footer
        root.addWidget(self._make_lang_footer())

    def _make_lang_footer(self) -> QFrame:
        """Full-width language combobox at the bottom of the panel."""
        footer = QFrame()
        footer.setStyleSheet(
            "QFrame { background:#150809; border-top:1px solid #2d1020; }"
        )
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(8, 6, 8, 6)

        self._lang_combo = QComboBox()
        self._lang_combo.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self._lang_combo.setIconSize(QSize(20, 14))
        self._lang_combo.setStyleSheet("""
            QComboBox {
                background: #220d14;
                color: #c8889a;
                border: 1px solid #45072f;
                border-radius: 4px;
                padding: 3px 8px;
                font-size: 9pt;
            }
            QComboBox:hover { border: 1px solid #c90084; color: #ffd0de; }
            QComboBox::drop-down { border: none; width: 18px; }
            QComboBox::down-arrow {
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 5px solid #c8889a;
                width: 0; height: 0;
            }
            QComboBox QAbstractItemView {
                background: #220d14;
                color: #ffd0de;
                selection-background-color: #45072f;
                border: 1px solid #c90084;
                outline: none;
            }
        """)

        # Populate with available locale files
        _icons_dir = Path(__file__).parent.parent / "assets" / "icons" / "lang"
        locales_dir = Path(__file__).parent.parent / "locales"
        available = sorted(p.stem.upper() for p in locales_dir.glob("*.csv"))
        current = get_current_language().upper()
        for code in available:
            _, name = _LANG_INFO.get(code, ("🌐", code))
            svg_path = _icons_dir / f"{code}.svg"
            icon = QIcon(str(svg_path)) if svg_path.exists() else QIcon()
            self._lang_combo.addItem(icon, name, userData=code)

        # Select current language
        for i in range(self._lang_combo.count()):
            if self._lang_combo.itemData(i) == current:
                self._lang_combo.setCurrentIndex(i)
                break

        self._lang_combo.currentIndexChanged.connect(self._on_lang_changed)

        fl.addWidget(self._lang_combo)
        return footer

    def _on_lang_changed(self, index: int) -> None:
        code = self._lang_combo.itemData(index)
        if not code or code == get_current_language():
            return
        load_language(code)
        save_language_pref(code)
        self.language_changed.emit(code)

    def _check_ble_adapter(self) -> None:
        """Check for a BLE adapter in a background thread; show banner if absent."""
        import threading
        def _check() -> None:
            try:
                import asyncio
                from bleak import BleakScanner  # type: ignore
                loop = asyncio.new_event_loop()
                adapters = loop.run_until_complete(_async_get_adapters())
                loop.close()
                if not adapters:
                    self._ble_banner.setText(tr("ui.panel.devices.no_ble_detail"))
                    self._ble_banner.setVisible(True)
            except ImportError:
                self._ble_banner.setText(tr("ui.panel.devices.no_bleak"))
                self._ble_banner.setVisible(True)
            except Exception:
                pass  # adapter may still work; don't show banner on generic errors

        async def _async_get_adapters():
            try:
                from bleak import BleakScanner  # type: ignore
                # Quick 0.1s scan just to check adapter presence
                found = []
                scanner = BleakScanner()
                await scanner.start()
                import asyncio as _a; await _a.sleep(0.1)
                await scanner.stop()
                return [True]   # adapter present if no exception
            except Exception:
                return []

        t = threading.Thread(target=_check, daemon=True, name="BLEAdapterCheck")
        t.start()

    def _connect_signals(self) -> None:
        self._registry.device_added.connect(self._on_added)
        self._registry.device_removed.connect(self._on_removed)
        self._registry.device_status.connect(self._on_status)

    def _on_added(self, device_id: str) -> None:
        dev = self._registry.get_device(device_id)
        if not dev:
            return
        from core.device_node_base import get_device_alias
        alias = get_device_alias(dev)
        row = DeviceRow(device_id, alias,
                        dev.descriptor.address, dev.ICON_PATH)
        row.clicked.connect(self._on_row_clicked)
        row.rename_requested.connect(self._on_rename_requested)
        dev.battery_changed.connect(
            lambda lvl, did=device_id: self._on_battery(did, lvl)
        )
        self._rows[device_id] = row
        self._list_lay.insertWidget(self._list_lay.count() - 1, row)
        self._empty_lbl.setVisible(False)

    def _on_removed(self, device_id: str) -> None:
        row = self._rows.pop(device_id, None)
        if row:
            self._list_lay.removeWidget(row)
            row.deleteLater()
        self._empty_lbl.setVisible(len(self._rows) == 0)

    def _on_status(self, device_id: str, status: DeviceStatus) -> None:
        row = self._rows.get(device_id)
        if row:
            row.set_status(status)

    def _on_battery(self, device_id: str, level: int) -> None:
        row = self._rows.get(device_id)
        if row:
            row.set_battery(level)

    def highlight_device(self, device_id: Optional[str]) -> None:
        """Highlight the specific device row; clear all others."""
        for did, row in self._rows.items():
            row.set_highlighted(device_id is not None and did == device_id)

    def _on_rename_requested(self, device_id: str, new_alias: str) -> None:
        self.rename_device_requested.emit(device_id, new_alias)

    def _on_row_clicked(self, device_id: str) -> None:
        dev = self._registry.get_device(device_id)
        if not dev:
            return
        from core.device_node_base import get_device_alias
        current_alias = get_device_alias(dev)
        dlg = DeviceDetailDialog(device_id, dev.DEVICE_NAME,
                                  dev.descriptor.address, dev.status, dev.battery_level,
                                  dev.ICON_PATH, current_alias,
                                  getattr(dev, "DEVICE_URL", ""), self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            if dlg.should_remove():
                self.remove_device_requested.emit(device_id)
            new_alias = dlg.new_alias()
            if new_alias and new_alias != current_alias:
                self.rename_device_requested.emit(device_id, new_alias)
                row = self._rows.get(device_id)
                if row:
                    row.set_alias(new_alias)

    def _on_add_clicked(self) -> None:
        dlg = AddDeviceDialog(self._registry.device_classes, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            result = dlg.result_data()
            if result:
                class_key, descriptor = result
                self.add_device_requested.emit(class_key, descriptor)


# ── Add Device dialog — manufacturer tiles ────────────────────────────────────

class _DeviceTile(QFrame):
    """Clickable tile showing device icon + name."""
    selected = pyqtSignal(str)   # class_key

    _STYLE_NORMAL = """
        QFrame { background:#220d14; border:2px solid #45072f;
                 border-radius:8px; }
        QFrame:hover { border:2px solid #c90084; background:#2d1020; }
    """
    _STYLE_ACTIVE = """
        QFrame { background:#45072f; border:2px solid #f95979;
                 border-radius:8px; }
    """

    def __init__(self, class_key: str, device_cls, parent=None) -> None:
        super().__init__(parent)
        self._key      = class_key
        self._selected = False
        self.setFixedSize(120, 132)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(self._STYLE_NORMAL)

        # Set tooltip to description if available
        prefix = getattr(device_cls, "DEVICE_TR_PREFIX", None)
        display_name = tr(f"device.{prefix}.name", default=device_cls.DEVICE_NAME) if prefix else device_cls.DEVICE_NAME
        display_desc = tr(f"device.{prefix}.description", default=getattr(device_cls, "DEVICE_DESCRIPTION", "")) if prefix else getattr(device_cls, "DEVICE_DESCRIPTION", "")
        if display_desc:
            self.setToolTip(display_desc)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 8, 6, 6)
        lay.setSpacing(4)
        lay.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        icon_w = _make_icon_widget(device_cls.ICON_PATH, 66)
        lay.addWidget(icon_w, alignment=Qt.AlignmentFlag.AlignHCenter)

        name = QLabel(display_name)
        name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name.setWordWrap(True)
        name.setStyleSheet("color:#ffd0de;font-size:9pt;background:transparent;")
        lay.addWidget(name)

    def set_active(self, active: bool) -> None:
        self._selected = active
        self.setStyleSheet(self._STYLE_ACTIVE if active else self._STYLE_NORMAL)

    def mousePressEvent(self, _) -> None:
        self.selected.emit(self._key)


class AddDeviceDialog(QDialog):
    """
    Two-step device selection dialog.

    Step 1 — manufacturer tile grid: pick the device model.
    Step 2 — depends on the selected device's CONNECTION_KINDS:
              BLE  → launch BLEScanDialog (auto-scan, no address typing)
              COM  → (future) COM config dialog; currently skipped
              Other→ simple address entry fallback

    The dialog does NOT show a protocol selector; the protocol is inferred
    from the device class and handled transparently.
    """

    def __init__(self, device_classes: dict, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("ui.dialog.add_device.title"))
        self.setStyleSheet(_DLG_STYLE)
        self.setMinimumSize(560, 480)
        self._device_classes = {k: v for k, v in device_classes.items()
                                 if not v.__name__.startswith("_")}
        self._selected_key: Optional[str] = None
        self._tiles:         dict[str, _DeviceTile] = {}
        self._result:        Optional[tuple[str, ConnectionDescriptor]] = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        # Manufacturer tabs
        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)

        manufacturers: dict[str, list[tuple[str, type]]] = {}
        for key, cls in self._device_classes.items():
            mfr = getattr(cls, "MANUFACTURER", "Generic")
            if mfr.lower() in ("unknown", "generic"):
                continue   # hide abstraction/placeholder devices
            manufacturers.setdefault(mfr, []).append((key, cls))

        for mfr in sorted(manufacturers.keys()):
            tab = _ManufacturerTab(manufacturers[mfr])
            tab.tile_selected.connect(self._on_tile_selected)
            self._tabs.addTab(tab, mfr)
            for key, _ in manufacturers[mfr]:
                self._tiles[key] = tab.tile(key)

        root.addWidget(self._tabs)

        # Info bar
        self._info_bar = QLabel(tr("ui.panel.devices.select_continue"))
        self._info_bar.setStyleSheet(
            "color:#9a5070;font-size:8pt;padding:4px;"
            "background:#220d14;border:1px solid #45072f;border-radius:4px;")
        root.addWidget(self._info_bar)

        # Hint label (shown below info bar)
        self._hint_lbl = QLabel("")
        self._hint_lbl.setStyleSheet("color:#6b3050;font-size:8pt;")
        self._hint_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self._hint_lbl)

        # Buttons
        btn_row = QHBoxLayout()
        self._website_btn = QPushButton(tr("ui.button.website"))
        self._website_btn.setObjectName("cancel")
        self._website_btn.setEnabled(False)
        self._website_btn.setToolTip(tr("ui.panel.devices.website_tooltip"))
        self._website_btn.clicked.connect(self._on_website)
        btn_row.addWidget(self._website_btn)
        btn_row.addStretch()
        cancel = QPushButton(tr("ui.button.cancel"))
        cancel.setObjectName("cancel")
        cancel.clicked.connect(self.reject)
        self._next_btn = QPushButton(tr("ui.button.search_connect"))
        self._next_btn.setEnabled(False)
        self._next_btn.clicked.connect(self._on_next)
        btn_row.addWidget(cancel)
        btn_row.addWidget(self._next_btn)
        root.addLayout(btn_row)

    def _on_tile_selected(self, class_key: str) -> None:
        old_tile = self._tiles.get(self._selected_key)
        if old_tile:
            old_tile.set_active(False)
        self._selected_key = class_key
        self._tiles[class_key].set_active(True)

        cls  = self._device_classes[class_key]
        prefix = getattr(cls, "DEVICE_TR_PREFIX", None)
        display_name = tr(f"device.{prefix}.name", default=cls.DEVICE_NAME) if prefix else cls.DEVICE_NAME
        display_desc = tr(f"device.{prefix}.description", default=getattr(cls, "DEVICE_DESCRIPTION", "")) if prefix else getattr(cls, "DEVICE_DESCRIPTION", "")
        self._info_bar.setText(
            f"<b>{display_name}</b>  —  {display_desc}" if display_desc
            else f"<b>{display_name}</b>"
        )

        kinds = getattr(cls, "CONNECTION_KINDS", [])
        from core.types import PortKind as _PK
        if _PK.BLE in kinds:
            self._hint_lbl.setText(tr("ui.panel.devices.turn_on_ble"))
            self._next_btn.setText(tr("ui.button.search_connect"))
        else:
            self._hint_lbl.setText("")
            self._next_btn.setText(tr("ui.button.connect"))

        self._next_btn.setEnabled(True)
        url = getattr(cls, "DEVICE_URL", "")
        self._website_btn.setEnabled(bool(url))

    def _on_website(self) -> None:
        if not self._selected_key:
            return
        cls = self._device_classes[self._selected_key]
        url = getattr(cls, "DEVICE_URL", "")
        if url:
            from PyQt6.QtGui import QDesktopServices
            from PyQt6.QtCore import QUrl
            QDesktopServices.openUrl(QUrl(url))

    def _on_next(self) -> None:
        if not self._selected_key:
            return
        cls   = self._device_classes[self._selected_key]
        kinds = getattr(cls, "CONNECTION_KINDS", [])
        from core.types import PortKind as _PK

        if _PK.BLE in kinds:
            self._launch_ble_scan()
        else:
            kind = kinds[0] if kinds else _PK.BLE
            dlg = _AddressDialog(cls, kind, self)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                self._result = (
                    self._selected_key,
                    ConnectionDescriptor(kind=kind, address=dlg.address()),
                )
                self.accept()

    def _launch_ble_scan(self) -> None:
        """Open the BLE scan dialog, passing the preselected tile class_key."""
        from ui.ble_scan_dialog import BLEScanDialog
        scan_dlg = BLEScanDialog(
            device_classes  = self._device_classes,
            preselected_key = self._selected_key or "",
            parent          = self,
        )
        if scan_dlg.exec() == QDialog.DialogCode.Accepted:
            result = scan_dlg.result_data()
            if result:
                self._result = result
                self.accept()

    def result_data(self) -> Optional[tuple[str, ConnectionDescriptor]]:
        return self._result


class _AddressDialog(QDialog):
    """Small connection-address dialog for non-BLE devices."""

    def __init__(self, device_cls: type, kind: PortKind, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("ui.dialog.device_address.title"))
        self.setStyleSheet(_DLG_STYLE)
        self.setMinimumWidth(420)
        self._address = ""

        prefix = getattr(device_cls, "DEVICE_TR_PREFIX", None)
        display_name = (
            tr(f"device.{prefix}.name", default=device_cls.DEVICE_NAME)
            if prefix else device_cls.DEVICE_NAME
        )

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        label = QLabel(tr("ui.dialog.device_address.message").format(name=display_name))
        label.setWordWrap(True)
        lay.addWidget(label)

        lay.addWidget(QLabel(tr("ui.dialog.device_address.address_label")))
        self._address_edit = QLineEdit(self)
        self._address_edit.setPlaceholderText(self._placeholder_for(kind))
        default_address = getattr(device_cls, "DEFAULT_ADDRESS", "")
        self._address_edit.setText(default_address)
        lay.addWidget(self._address_edit)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel = QPushButton(tr("ui.button.cancel"))
        cancel.setObjectName("cancel")
        cancel.clicked.connect(self.reject)
        connect = QPushButton(tr("ui.button.connect_plain"))
        connect.clicked.connect(self._accept_if_valid)
        btn_row.addWidget(cancel)
        btn_row.addWidget(connect)
        lay.addLayout(btn_row)

    def _placeholder_for(self, kind: PortKind) -> str:
        if kind == PortKind.WEBSOCKET:
            return "ws://<device-ip>:<websocket_port>"
        if kind == PortKind.TCP:
            return "192.168.1.42:1234"
        if kind == PortKind.REST:
            return "http://192.168.1.42"
        if kind == PortKind.SERIAL:
            return "COM3"
        return ""

    def _accept_if_valid(self) -> None:
        address = self._address_edit.text().strip()
        if not address:
            self._address_edit.setFocus()
            return
        self._address = address
        self.accept()

    def address(self) -> str:
        return self._address


class _ReflowContainer(QWidget):
    """Container that reflows its QGridLayout when the width changes."""

    _TILE_W   = 120
    _SPACING  = 8
    _MARGINS  = 16  # 8px left + 8px right

    def __init__(self, tile_items: list[tuple[str, "_DeviceTile"]], parent=None) -> None:
        super().__init__(parent)
        self._tile_items  = tile_items
        self._current_cols = 0

        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(8, 8, 8, 8)
        self._grid.setSpacing(self._SPACING)
        self._grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)

        self._place_tiles(4)  # reasonable initial layout

    def _place_tiles(self, cols: int) -> None:
        if cols == self._current_cols:
            return
        self._current_cols = cols
        for _, tile in self._tile_items:
            self._grid.removeWidget(tile)
        for idx, (_, tile) in enumerate(self._tile_items):
            self._grid.addWidget(tile, idx // cols, idx % cols)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        avail = self.width() - self._MARGINS
        cols  = max(1, avail // (self._TILE_W + self._SPACING))
        self._place_tiles(cols)


class _ManufacturerTab(QWidget):
    """Scrollable grid of device tiles for one manufacturer."""
    tile_selected = pyqtSignal(str)

    def __init__(self, items: list[tuple[str, type]], parent=None) -> None:
        super().__init__(parent)
        self._tiles: dict[str, _DeviceTile] = {}

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background:transparent;")

        tile_items: list[tuple[str, _DeviceTile]] = []
        for key, cls in items:
            t = _DeviceTile(key, cls)
            t.selected.connect(self.tile_selected)
            self._tiles[key] = t
            tile_items.append((key, t))

        container = _ReflowContainer(tile_items)
        container.setStyleSheet("background:transparent;")
        scroll.setWidget(container)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(scroll)

    def tile(self, key: str) -> _DeviceTile:
        return self._tiles[key]


# ── Device detail dialog ──────────────────────────────────────────────────────

class DeviceDetailDialog(QDialog):
    def __init__(self, device_id: str, name: str, address: str,
                 status: DeviceStatus, battery: int,
                 icon_path: Optional[str], current_alias: str = "",
                 device_url: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("ui.dialog.device_detail.title").format(name=name))
        self.setStyleSheet(_DLG_STYLE)
        self.setMinimumWidth(320)
        self._remove      = False
        self._new_alias   = ""
        self._device_url  = device_url

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        # Header: icon + name + status
        hrow = QHBoxLayout()
        icon_w = _make_icon_widget(icon_path, 52)
        hrow.addWidget(icon_w)
        vinfo = QVBoxLayout()
        vinfo.setSpacing(2)
        n_lbl = QLabel(f"<b>{name}</b>")
        n_lbl.setStyleSheet("font-size:12pt;")
        vinfo.addWidget(n_lbl)
        s_lbl = QLabel(tr("ui.panel.devices.status_label").format(status=status.value))
        s_lbl.setStyleSheet(f"color:{STATUS_COLORS[status]};")
        vinfo.addWidget(s_lbl)
        hrow.addLayout(vinfo)
        lay.addLayout(hrow)

        # Battery
        bat_row = QHBoxLayout()
        bat_row.addWidget(QLabel(tr("ui.panel.devices.battery_label")))
        bat_w = BatteryWidget()
        bat_w.set_level(battery)
        bat_w.setFixedSize(60, 18)
        bat_row.addWidget(bat_w)
        bat_row.addStretch()
        lay.addLayout(bat_row)

        lay.addWidget(QLabel(tr("ui.panel.devices.address_label").format(address=address)))
        lay.addWidget(QLabel(tr("ui.panel.devices.id_label").format(id=device_id[:16])))

        # Rename field
        lay.addWidget(QLabel(tr("ui.panel.devices.alias_label")))
        self._alias_edit = QLineEdit(current_alias or name)
        self._alias_edit.setPlaceholderText(tr("ui.panel.devices.alias_placeholder"))
        lay.addWidget(self._alias_edit)

        btn_row = QHBoxLayout()
        remove_btn = QPushButton(tr("ui.button.remove"))
        remove_btn.clicked.connect(self._on_remove)
        save_btn = QPushButton(tr("ui.button.save"))
        save_btn.clicked.connect(self._on_save)
        close_btn = QPushButton(tr("ui.button.close"))
        close_btn.setObjectName("cancel")
        close_btn.clicked.connect(self.reject)
        btn_row.addWidget(remove_btn)
        btn_row.addStretch()
        if device_url:
            website_btn = QPushButton(tr("ui.button.website"))
            website_btn.setObjectName("cancel")
            website_btn.setToolTip(tr("ui.panel.devices.website_tooltip"))
            website_btn.clicked.connect(self._on_website)
            btn_row.addWidget(website_btn)
        btn_row.addWidget(save_btn)
        btn_row.addWidget(close_btn)
        lay.addLayout(btn_row)

    def _on_website(self) -> None:
        if self._device_url:
            from PyQt6.QtGui import QDesktopServices
            from PyQt6.QtCore import QUrl
            QDesktopServices.openUrl(QUrl(self._device_url))

    def _on_remove(self) -> None:
        self._remove = True
        self.accept()

    def _on_save(self) -> None:
        self._new_alias = self._alias_edit.text().strip()
        self.accept()

    def should_remove(self) -> bool:
        return self._remove

    def new_alias(self) -> str:
        return self._new_alias


# ── Icon helper ───────────────────────────────────────────────────────────────

def _make_icon_widget(icon_path: Optional[str], size: int) -> QWidget:
    """
    Return a QSvgWidget for SVG icons, or a text-placeholder widget
    (question mark) if the icon is missing or not SVG.
    """
    resolved = None
    if icon_path:
        p = Path(icon_path)
        if not p.is_absolute():
            p = _PROJECT_ROOT / p
        if p.exists() and p.suffix.lower() == ".svg":
            resolved = str(p)

    if resolved is None:
        resolved = _UNKNOWN_ICON

    try:
        from PyQt6.QtSvgWidgets import QSvgWidget as _SVG
        w = _SVG()
        w.load(resolved)
        w.setFixedSize(size, size)
        return w
    except Exception:
        pass

    # Fallback: plain label with question mark
    lbl = QLabel("?")
    lbl.setFixedSize(size, size)
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lbl.setStyleSheet(
        f"color:#6b3050;font-size:{int(size*0.5)}pt;font-weight:bold;"
        "background:#220d14;border:1px solid #45072f;border-radius:4px;"
    )
    return lbl
