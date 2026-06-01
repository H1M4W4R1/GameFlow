"""Debug log console window."""
from __future__ import annotations

import html
import logging
import re
from pathlib import Path

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLineEdit,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from core.localization import tr


LOG_DIR = Path.home() / ".gameflow" / "logs"
_LOG_LINE_RE = re.compile(r"^(?P<time>\S+\s+\S+)\s+\[(?P<level>[A-Z]+)\]\s+(?P<body>.*)$")
_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
_LEVEL_LABELS = {"WARNING": "WARN", "CRITICAL": "CRIT"}
_LEVEL_COLORS = {
    "DEBUG": "#7dd3fc",
    "INFO": "#a7f3d0",
    "WARNING": "#fde047",
    "ERROR": "#fb7185",
    "CRITICAL": "#f97316",
}


def configure_file_logging() -> Path:
    """Create the current log file and keep only the three newest logs."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / "gameflow.log"
    if log_path.exists():
        stamp = log_path.stat().st_mtime
        rotated = LOG_DIR / f"gameflow.{int(stamp)}.log"
        counter = 1
        while rotated.exists():
            rotated = LOG_DIR / f"gameflow.{int(stamp)}.{counter}.log"
            counter += 1
        log_path.rename(rotated)

    _trim_old_logs()
    return log_path


def _trim_old_logs() -> None:
    logs = sorted(LOG_DIR.glob("gameflow*.log"), key=lambda path: path.stat().st_mtime)
    for path in logs[:-2]:
        try:
            path.unlink()
        except OSError:
            logging.getLogger(__name__).warning("Could not delete old log file: %s", path)


class DebugConsole(QWidget):
    """A small live log viewer with level flags and quick text search."""

    def __init__(self, log_path: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._log_path = log_path
        self._last_text = ""
        self._level_buttons: dict[str, QToolButton] = {}

        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setWindowTitle(tr("ui.debug_console.title"))
        self.resize(980, 560)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.setStyleSheet(_STYLE)

        self._build_ui()

        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._reload_if_needed)
        self._timer.start()
        self._reload_if_needed(force=True)

    def show_and_raise(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        self._text = QTextEdit()
        self._text.setReadOnly(True)
        self._text.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self._text.setObjectName("LogText")
        layout.addWidget(self._text, stretch=1)

        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 0, 0, 0)
        bottom.setSpacing(6)

        for level in _LEVELS:
            button = QToolButton()
            button.setText(_LEVEL_LABELS.get(level, level))
            button.setCheckable(True)
            button.setChecked(True)
            button.setProperty("level", level)
            button.setToolTip(tr("ui.debug_console.level_tooltip").format(level=level))
            button.setStyleSheet(_button_style(level))
            button.toggled.connect(lambda _checked: self._render())
            self._level_buttons[level] = button
            bottom.addWidget(button)

        self._search = QLineEdit()
        self._search.setPlaceholderText(tr("ui.debug_console.search_placeholder"))
        self._search.textChanged.connect(lambda _text: self._render())
        bottom.addWidget(self._search, stretch=1)

        layout.addLayout(bottom)

    def _reload_if_needed(self, force: bool = False) -> None:
        try:
            text = self._log_path.read_text(encoding="utf-8")
        except OSError:
            text = ""
        if force or text != self._last_text:
            self._last_text = text
            self._render()

    def _render(self) -> None:
        active_levels = {
            level
            for level, button in self._level_buttons.items()
            if button.isChecked()
        }
        query = self._search.text().casefold().strip()

        lines = []
        for level, entry in self._iter_entries():
            if level not in active_levels:
                continue
            if query and query not in entry.casefold():
                continue
            lines.append(self._format_entry(entry, level))

        at_bottom = self._text.verticalScrollBar().value() >= self._text.verticalScrollBar().maximum() - 4
        self._text.setHtml("<br>".join(lines))
        if at_bottom:
            self._text.moveCursor(QTextCursor.MoveOperation.End)

    def _iter_entries(self) -> list[tuple[str, str]]:
        entries: list[tuple[str, list[str]]] = []
        current_level = "INFO"
        current_lines: list[str] = []

        for line in self._last_text.splitlines():
            match = _LOG_LINE_RE.match(line)
            if match:
                if current_lines:
                    entries.append((current_level, current_lines))
                current_level = match.group("level")
                current_lines = [line]
                continue
            current_lines.append(line)

        if current_lines:
            entries.append((current_level, current_lines))
        return [(level, "\n".join(lines)) for level, lines in entries]

    def _format_entry(self, entry: str, level: str) -> str:
        return "<br>".join(
            self._format_line(line, level, _LOG_LINE_RE.match(line))
            for line in entry.splitlines()
        )

    def _format_line(self, line: str, level: str, match: re.Match[str] | None) -> str:
        color = _LEVEL_COLORS.get(level, "#c9d1d9")
        if not match:
            return f"<span style='color:{color};'>{html.escape(line)}</span>"

        timestamp = html.escape(match.group("time"))
        body = html.escape(match.group("body"))
        label = html.escape(_LEVEL_LABELS.get(level, level))
        return (
            "<span style='color:#7d8590;'>"
            f"{timestamp}</span> "
            f"<span style='color:{color};font-weight:700;'>[{label}]</span> "
            f"<span style='color:#c9d1d9;'>{body}</span>"
        )


def _button_style(level: str) -> str:
    color = _LEVEL_COLORS[level]
    return (
        "QToolButton {"
        f" color:{color};"
        " background:#0d1117;"
        f" border:1px solid {color};"
        " border-radius:4px;"
        " padding:4px 8px;"
        " font-weight:700;"
        "}"
        "QToolButton:checked {"
        f" background:{color};"
        " color:#0d1117;"
        "}"
    )


_STYLE = """
DebugConsole {
    background: #161b22;
}
QTextEdit#LogText {
    background: #0d1117;
    border: 1px solid #30363d;
    color: #c9d1d9;
    font-family: Consolas, "Cascadia Mono", monospace;
    font-size: 9pt;
}
QLineEdit {
    background: #0d1117;
    border: 1px solid #30363d;
    border-radius: 4px;
    color: #f4f0ff;
    padding: 5px 8px;
}
QLineEdit:focus {
    border-color: #8b5cf6;
}
"""
