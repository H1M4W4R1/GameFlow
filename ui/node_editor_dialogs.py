"""Dialog and popup classes for NodeEditorCanvas."""

from PyQt6.QtCore import Qt, QEvent, QObject, QPointF, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QFrame, QLineEdit, QListWidget, QListWidgetItem,
    QVBoxLayout, QWidget,
)

from core.localization import tr


def _parse_hex_to_qcolor(s: str) -> QColor:
    """Parse #RRGGBB or #RRGGBBAA into QColor."""
    s = (s or "").strip()
    if not s.startswith("#") or len(s) < 7:
        return QColor(255, 255, 255)
    s = s[1:]
    try:
        r = int(s[0:2], 16)
        g = int(s[2:4], 16)
        b = int(s[4:6], 16)
        return QColor(r, g, b)
    except ValueError:
        return QColor(255, 255, 255)


def _format_value(val, typ: type, dim: bool) -> tuple[str, QColor]:
    """Return (display_string, QColor) for a field value."""
    if typ is bool:
        v     = bool(val)
        label = "true" if v else "false"
        if dim:
            return label, QColor("#4a5040" if v else "#504040")
        return label, QColor("#4caf50" if v else "#ef5350")
    elif typ is float:
        label = f"{float(val):.4g}" if val is not None else "0"
        return label, QColor("#3a7080" if dim else "#4fc3f7")
    elif typ is int:
        label = str(int(val)) if val is not None else "0"
        return label, QColor("#607040" if dim else "#aed581")
    else:
        label = str(val) if val is not None else ""
        if len(label) > 18:
            label = label[:15] + "…"
        return label, QColor("#604080" if dim else "#ce93d8")


_MENU_STYLE = """
QMenu {
    background-color: #220d14; color: #ffd0de;
    border: 1px solid #45072f; border-radius: 4px;
    padding: 4px; font-family: 'Segoe UI'; font-size: 9pt;
}
QMenu::item:selected { background-color: #c90084; border-radius: 3px; }
QMenu::item          { padding: 4px 20px 4px 12px; }
QMenu::separator     { background: #45072f; height: 1px; margin: 4px 8px; }
"""

_SEARCH_POPUP_STYLE = """
QFrame {
    background: #220d14; border: 1px solid #45072f; border-radius: 6px;
}
QLineEdit {
    background: #2a0e1a; color: #ffd0de;
    border: 1px solid #45072f; border-radius: 3px;
    padding: 5px 8px; font-family: 'Segoe UI'; font-size: 10pt;
}
QLineEdit:focus { border-color: #c90084; }
QListWidget {
    background: #220d14; color: #ffd0de;
    border: none; outline: none;
    font-family: 'Segoe UI'; font-size: 9pt;
}
QListWidget::item { padding: 4px 10px; border-radius: 3px; }
QListWidget::item:selected { background: #c90084; color: #fff; }
QListWidget::item:hover { background: #3a0d22; }
QScrollBar:vertical { width: 6px; background: #1a0510; border: none; }
QScrollBar::handle:vertical { background: #45072f; border-radius: 3px; min-height: 20px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""


class _NodeSearchPopup(QFrame):
    """Floating search popup for quick node addition via the right-click menu."""

    node_selected = pyqtSignal(str, QPointF)  # (node_key, scene_pos)

    def __init__(
        self,
        flat_nodes: list[tuple[str, str]],
        scene_pos: QPointF,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self._flat_nodes = flat_nodes
        self._scene_pos = scene_pos

        self.setStyleSheet(_SEARCH_POPUP_STYLE)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        self._search = QLineEdit()
        self._search.setPlaceholderText(tr("ui.canvas.menu.search_nodes"))
        layout.addWidget(self._search)

        self._list = QListWidget()
        self._list.setFixedHeight(260)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.itemActivated.connect(self._confirm_selection)
        layout.addWidget(self._list)

        self._search.textChanged.connect(self._filter)
        self._search.installEventFilter(self)
        self._list.installEventFilter(self)

        self.setFixedWidth(320)
        self._populate(flat_nodes)

    # ── population / filtering ─────────────────────────────────────────────

    def _populate(self, nodes: list[tuple[str, str]]) -> None:
        self._list.clear()
        for label, key in nodes:
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, key)
            self._list.addItem(item)
        if self._list.count():
            self._list.setCurrentRow(0)

    def _filter(self, text: str) -> None:
        q = text.strip().lower()
        filtered = [
            (lbl, key) for lbl, key in self._flat_nodes
            if not q or q in lbl.lower()
        ]
        self._populate(filtered)

    # ── selection ──────────────────────────────────────────────────────────

    def _confirm_selection(self, item: QListWidgetItem | None = None) -> None:
        if item is None:
            item = self._list.currentItem()
        if item:
            key = item.data(Qt.ItemDataRole.UserRole)
            if key:
                self.node_selected.emit(key, self._scene_pos)
        self.close()

    # ── keyboard routing ───────────────────────────────────────────────────

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if obj is self._search:
                if key == Qt.Key.Key_Down:
                    self._list.setFocus()
                    if self._list.count():
                        self._list.setCurrentRow(0)
                    return True
                if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    self._confirm_selection()
                    return True
                if key == Qt.Key.Key_Escape:
                    self.close()
                    return True
            elif obj is self._list:
                if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    self._confirm_selection()
                    return True
                if key == Qt.Key.Key_Escape:
                    self.close()
                    return True
                # Any printable key while list is focused → redirect to search bar
                if key not in (
                    Qt.Key.Key_Up, Qt.Key.Key_Down,
                    Qt.Key.Key_PageUp, Qt.Key.Key_PageDown,
                    Qt.Key.Key_Home, Qt.Key.Key_End,
                ):
                    self._search.setFocus()
                    self._search.event(event)
                    return True
        return super().eventFilter(obj, event)

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        self._search.setFocus()
