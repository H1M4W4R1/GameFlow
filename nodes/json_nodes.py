"""JSON utility nodes."""
from __future__ import annotations

import json
import re
from typing import Any

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QAction, QBrush, QColor, QFont, QFontMetrics, QPainter, QPen
from PyQt6.QtWidgets import QMenu

from core.localization import tr
from core.node_base import NodeBase
from core.types import PinDescriptor, PinDirection, PinType


_JSON_FONT = QFont("Courier New", 8)
_LINE_H = 14
_MAX_DEBUG_W = 540.0
_MAX_DEBUG_H = 380.0
_SCROLLBAR = 10.0


def _add_json_fields_context_menu(node: NodeBase, canvas: Any, menu: QMenu, field_hit: Any) -> None:
    if not (field_hit and field_hit.node_id == node.node_id and field_hit.is_dynamic):
        return
    idx = field_hit.dynamic_index
    fields_menu = QMenu(tr("ui.canvas.menu.json_fields", default="JSON fields"), menu)
    fields_menu.setStyleSheet(menu.styleSheet())

    up_act = QAction(tr("ui.canvas.menu.move_field_up", default="Move field up"), fields_menu)
    up_act.setEnabled(idx > 0)
    up_act.triggered.connect(lambda: canvas._move_dynamic_field(node.node_id, idx, -1))
    fields_menu.addAction(up_act)

    down_act = QAction(tr("ui.canvas.menu.move_field_down", default="Move field down"), fields_menu)
    field_count = len([spec for spec in node.get_dynamic_field_specs() if str(spec[1]).strip()])
    down_act.setEnabled(0 <= idx < field_count - 1)
    down_act.triggered.connect(lambda: canvas._move_dynamic_field(node.node_id, idx, 1))
    fields_menu.addAction(down_act)

    menu.addMenu(fields_menu)


class JsonExtractNode(NodeBase):
    """Parse JSON text and expose user-defined object fields as outputs."""
    NODE_NAME = "JSON Extract"
    NODE_GROUP = "Conversion"
    MIN_WIDTH = 270.0
    MIN_HEIGHT = 60.0

    def __init__(self, *args, **kwargs) -> None:
        self._field_paths: list[str] = [""]
        self.PINS = self._build_pins()
        super().__init__(*args, **kwargs)

    def get_dynamic_field_specs(self) -> list[tuple[int, str, str | None]]:
        pin_names = self._output_pin_names()
        specs: list[tuple[int, str, str | None]] = []
        output_i = 0
        for i, path in enumerate(self._field_paths):
            pin_name = None
            if path.strip():
                pin_name = pin_names[output_i]
                output_i += 1
            specs.append((i, path, pin_name))
        return specs

    def get_dynamic_field_value(self, index: int) -> str:
        if 0 <= index < len(self._field_paths):
            return self._field_paths[index]
        return ""

    def set_dynamic_field_value(self, index: int, raw_value: str) -> None:
        while index >= len(self._field_paths):
            self._field_paths.append("")
        self._field_paths[index] = str(raw_value).strip()
        self._normalize_fields()
        self.PINS = self._build_pins()
        self._compute()
        self.node_changed.emit()

    def move_dynamic_field(self, index: int, delta: int) -> None:
        fields = [f for f in self._field_paths if f.strip()]
        target = index + delta
        if not (0 <= index < len(fields) and 0 <= target < len(fields)):
            return
        fields[index], fields[target] = fields[target], fields[index]
        self._field_paths = fields + [""]
        self.PINS = self._build_pins()
        self._compute()
        self.node_changed.emit()

    def _get_context_menu(self, canvas: Any, menu: QMenu, field_hit: Any = None) -> None:
        _add_json_fields_context_menu(self, canvas, menu, field_hit)

    def get_dynamic_output_pin_names(self) -> list[str]:
        return self._output_pin_names()

    def on_start(self) -> None:
        self._compute()

    def on_data_received(self, pin_name: str, value: Any) -> None:
        self._compute()

    def execute(self, trigger_pin: str) -> None:
        self._compute()

    def get_state(self) -> dict[str, Any]:
        state = super().get_state()
        state["__json_fields__"] = [f for f in self._field_paths if f.strip()]
        return state

    def set_state(self, state: dict[str, Any]) -> None:
        fields = state.pop("__json_fields__", [])
        self._field_paths = [str(f).strip() for f in fields if str(f).strip()]
        self._normalize_fields()
        self.PINS = self._build_pins()
        super().set_state(state)
        self._compute()

    def _build_pins(self) -> list[PinDescriptor]:
        pins = [
            PinDescriptor(
                "json_text",
                PinDirection.INPUT,
                PinType.STRING,
                default="{}",
                tooltip="JSON object text to parse.",
            ),
        ]
        for path, pin_name in zip(self._active_fields(), self._output_pin_names()):
            pins.append(
                PinDescriptor(
                    pin_name,
                    PinDirection.OUTPUT,
                    PinType.ANY,
                    tooltip=f"Value at JSON field '{path}'.",
                )
            )
        return pins

    def _compute(self) -> None:
        raw = self.get_input("json_text")
        try:
            parsed = json.loads(raw if isinstance(raw, str) else str(raw or ""))
        except (TypeError, ValueError):
            parsed = None

        for path, pin_name in zip(self._active_fields(), self._output_pin_names()):
            self.set_output(pin_name, self._extract_path(parsed, path))

    def _normalize_fields(self) -> None:
        self._field_paths = [f.strip() for f in self._field_paths if f.strip()]
        self._field_paths.append("")

    def _active_fields(self) -> list[str]:
        return [f for f in self._field_paths if f.strip()]

    def _output_pin_names(self) -> list[str]:
        used: dict[str, int] = {}
        names: list[str] = []
        for path in self._active_fields():
            base = re.sub(r"[^a-zA-Z0-9_]+", "_", path).strip("_").lower() or "field"
            count = used.get(base, 0)
            used[base] = count + 1
            names.append(base if count == 0 else f"{base}_{count + 1}")
        return names

    def _extract_path(self, parsed: Any, path: str) -> Any:
        cur = parsed
        for part in path.split("."):
            part = part.strip()
            if not part:
                continue
            if isinstance(cur, dict):
                cur = cur.get(part)
            elif isinstance(cur, list):
                try:
                    cur = cur[int(part)]
                except (ValueError, IndexError):
                    return None
            else:
                return None
        return cur


class BuildJsonNode(NodeBase):
    """Combine user-defined input fields into one JSON object string."""
    NODE_NAME = "Build JSON"
    NODE_GROUP = "Conversion"
    MIN_WIDTH = 270.0
    MIN_HEIGHT = 60.0

    def __init__(self, *args, **kwargs) -> None:
        self._field_names: list[str] = [""]
        self.PINS = self._build_pins()
        super().__init__(*args, **kwargs)

    def get_dynamic_field_specs(self) -> list[tuple[int, str, str | None, PinDirection]]:
        pin_names = self._input_pin_names()
        specs: list[tuple[int, str, str | None, PinDirection]] = []
        input_i = 0
        for i, name in enumerate(self._field_names):
            pin_name = None
            if name.strip():
                pin_name = pin_names[input_i]
                input_i += 1
            specs.append((i, name, pin_name, PinDirection.INPUT))
        return specs

    def get_dynamic_field_value(self, index: int) -> str:
        if 0 <= index < len(self._field_names):
            return self._field_names[index]
        return ""

    def set_dynamic_field_value(self, index: int, raw_value: str) -> None:
        while index >= len(self._field_names):
            self._field_names.append("")
        self._field_names[index] = str(raw_value).strip()
        self._normalize_fields()
        self.PINS = self._build_pins()
        self._compute()
        self.node_changed.emit()

    def move_dynamic_field(self, index: int, delta: int) -> None:
        fields = [f for f in self._field_names if f.strip()]
        target = index + delta
        if not (0 <= index < len(fields) and 0 <= target < len(fields)):
            return
        fields[index], fields[target] = fields[target], fields[index]
        self._field_names = fields + [""]
        self.PINS = self._build_pins()
        self._compute()
        self.node_changed.emit()

    def _get_context_menu(self, canvas: Any, menu: QMenu, field_hit: Any = None) -> None:
        _add_json_fields_context_menu(self, canvas, menu, field_hit)

    def get_dynamic_input_pin_names(self) -> list[str]:
        return self._input_pin_names()

    def on_start(self) -> None:
        self._compute()

    def on_data_received(self, pin_name: str, value: Any) -> None:
        self._compute()

    def execute(self, trigger_pin: str) -> None:
        self._compute()

    def get_state(self) -> dict[str, Any]:
        state = super().get_state()
        state["__json_fields__"] = [f for f in self._field_names if f.strip()]
        return state

    def set_state(self, state: dict[str, Any]) -> None:
        fields = state.pop("__json_fields__", [])
        self._field_names = [str(f).strip() for f in fields if str(f).strip()]
        self._normalize_fields()
        self.PINS = self._build_pins()
        super().set_state(state)
        self._compute()

    def _build_pins(self) -> list[PinDescriptor]:
        pins: list[PinDescriptor] = []
        for field_name, pin_name in zip(self._active_fields(), self._input_pin_names()):
            pins.append(
                PinDescriptor(
                    pin_name,
                    PinDirection.INPUT,
                    PinType.ANY,
                    tooltip=f"Value for JSON field '{field_name}'.",
                )
            )
        pins.append(
            PinDescriptor(
                "json_text",
                PinDirection.OUTPUT,
                PinType.STRING,
                tooltip="Built JSON object text.",
            )
        )
        return pins

    def _compute(self) -> None:
        obj: dict[str, Any] = {}
        for field_name, pin_name in zip(self._active_fields(), self._input_pin_names()):
            self._assign_path(obj, field_name, self.get_input(pin_name))
        self.set_output("json_text", json.dumps(obj, ensure_ascii=False))

    def _normalize_fields(self) -> None:
        self._field_names = [f.strip() for f in self._field_names if f.strip()]
        self._field_names.append("")

    def _active_fields(self) -> list[str]:
        return [f for f in self._field_names if f.strip()]

    def _input_pin_names(self) -> list[str]:
        used: dict[str, int] = {}
        names: list[str] = []
        for field_name in self._active_fields():
            base = re.sub(r"[^a-zA-Z0-9_]+", "_", field_name).strip("_").lower() or "field"
            count = used.get(base, 0)
            used[base] = count + 1
            names.append(base if count == 0 else f"{base}_{count + 1}")
        return names

    def _assign_path(self, obj: dict[str, Any], path: str, value: Any) -> None:
        parts = [part.strip() for part in path.split(".") if part.strip()]
        if not parts:
            return
        cur = obj
        for part in parts[:-1]:
            child = cur.get(part)
            if not isinstance(child, dict):
                child = {}
                cur[part] = child
            cur = child
        cur[parts[-1]] = value


class JsonDebugNode(NodeBase):
    """Pretty-print JSON and show it in a bounded scrollable node."""
    NODE_NAME = "JSON Debug"
    NODE_GROUP = "Debug"
    PINS = [
        PinDescriptor(
            "json",
            PinDirection.INPUT,
            PinType.ANY,
            default="{}",
            tooltip="JSON text, dict, list, or any value to inspect.",
        ),
    ]
    MIN_WIDTH = 260.0
    MIN_HEIGHT = 120.0

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._pretty_text = "{}"
        self._scroll_x = 0
        self._scroll_y = 0
        self._drag_scroll: str | None = None

    def on_data_received(self, pin_name: str, value: Any) -> None:
        if pin_name == "json":
            self._pretty_text = self._format_json(value)
            self._fit_to_content()
            self._clamp_scroll()
            self.node_changed.emit()

    def execute(self, trigger_pin: str) -> None:
        pass

    def get_state(self) -> dict[str, Any]:
        state = super().get_state()
        state["_pretty_text"] = self._pretty_text
        state["_scroll_x"] = self._scroll_x
        state["_scroll_y"] = self._scroll_y
        return state

    def set_state(self, state: dict[str, Any]) -> None:
        super().set_state(state)
        self._pretty_text = str(state.get("_pretty_text", "{}"))
        self._scroll_x = int(state.get("_scroll_x", 0))
        self._scroll_y = int(state.get("_scroll_y", 0))
        self._fit_to_content()
        self._clamp_scroll()

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        painter.setFont(_JSON_FONT)
        fm = QFontMetrics(_JSON_FONT)
        char_w = max(1, fm.horizontalAdvance("M"))
        lines = self._pretty_text.splitlines() or [""]
        view = rect.adjusted(4, 4, -4, -4)
        content_cols = max((len(line) for line in lines), default=0)
        visible_cols = max(1, int((view.width() - _SCROLLBAR) / char_w))
        visible_lines = max(1, int((view.height() - _SCROLLBAR) / _LINE_H))
        need_h = content_cols > visible_cols
        need_v = len(lines) > visible_lines
        text_rect = view.adjusted(0, 0, -(_SCROLLBAR if need_v else 0), -(_SCROLLBAR if need_h else 0))
        visible_cols = max(1, int(text_rect.width() / char_w))
        visible_lines = max(1, int(text_rect.height() / _LINE_H))
        self._clamp_scroll(visible_cols, visible_lines)

        painter.setPen(QPen(QColor("#31424f"), 1))
        painter.setBrush(QBrush(QColor("#0b1117")))
        painter.drawRoundedRect(view, 4, 4)

        painter.save()
        painter.setClipRect(text_rect.adjusted(2, 2, -2, -2))
        painter.setPen(QColor("#c8e6c9"))
        start_line = self._scroll_y
        end_line = min(len(lines), start_line + visible_lines + 1)
        for visual_i, line_i in enumerate(range(start_line, end_line)):
            line = lines[line_i]
            if self._scroll_x:
                line = line[self._scroll_x:]
            painter.drawText(
                QRectF(text_rect.x() + 5, text_rect.y() + 4 + visual_i * _LINE_H,
                       text_rect.width() - 10, _LINE_H),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                line,
            )
        painter.restore()

        if need_v:
            self._paint_scrollbar(painter, self._vbar_rect(view), self._scroll_y, len(lines), visible_lines, vertical=True)
        if need_h:
            self._paint_scrollbar(painter, self._hbar_rect(view), self._scroll_x, content_cols, visible_cols, vertical=False)

    def on_ctrl_press(self, scene_pos: QPointF, ctrl_rect: QRectF, modifiers: Qt.KeyboardModifiers = Qt.KeyboardModifier.NoModifier) -> bool:
        view = ctrl_rect.adjusted(4, 4, -4, -4)
        if self._vbar_rect(view).contains(scene_pos):
            self._drag_scroll = "v"
            self._set_scroll_from_pos(scene_pos, view)
            return True
        if self._hbar_rect(view).contains(scene_pos):
            self._drag_scroll = "h"
            self._set_scroll_from_pos(scene_pos, view)
            return True
        return False

    def on_ctrl_drag(self, scene_pos: QPointF, ctrl_rect: QRectF) -> None:
        if self._drag_scroll:
            self._set_scroll_from_pos(scene_pos, ctrl_rect.adjusted(4, 4, -4, -4))
            self.node_changed.emit()

    def on_ctrl_release(self) -> None:
        self._drag_scroll = None

    def _format_json(self, value: Any) -> str:
        try:
            if isinstance(value, str):
                parsed = json.loads(value)
            else:
                parsed = value
            return json.dumps(parsed, indent=2, ensure_ascii=False)
        except (TypeError, ValueError):
            return str(value) if value is not None else ""

    def _fit_to_content(self) -> None:
        lines = self._pretty_text.splitlines() or [""]
        cols = max((len(line) for line in lines), default=2)
        desired_w = cols * 7.0 + 54.0
        desired_h = len(lines) * _LINE_H + 92.0
        self.MIN_WIDTH = max(260.0, min(_MAX_DEBUG_W, desired_w))
        self.MIN_HEIGHT = max(120.0, min(_MAX_DEBUG_H, desired_h))

    def _clamp_scroll(self, visible_cols: int | None = None, visible_lines: int | None = None) -> None:
        lines = self._pretty_text.splitlines() or [""]
        max_cols = max((len(line) for line in lines), default=0)
        if visible_cols is None:
            visible_cols = max(1, int((self.MIN_WIDTH - 30.0) / 7.0))
        if visible_lines is None:
            visible_lines = max(1, int((self.MIN_HEIGHT - 74.0) / _LINE_H))
        self._scroll_x = max(0, min(self._scroll_x, max(0, max_cols - visible_cols)))
        self._scroll_y = max(0, min(self._scroll_y, max(0, len(lines) - visible_lines)))

    def _vbar_rect(self, view: QRectF) -> QRectF:
        return QRectF(view.right() - _SCROLLBAR, view.y(), _SCROLLBAR, max(0.0, view.height() - _SCROLLBAR))

    def _hbar_rect(self, view: QRectF) -> QRectF:
        return QRectF(view.x(), view.bottom() - _SCROLLBAR, max(0.0, view.width() - _SCROLLBAR), _SCROLLBAR)

    def _paint_scrollbar(self, painter: QPainter, rect: QRectF, offset: int, total: int, visible: int, vertical: bool) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor("#182532")))
        painter.drawRoundedRect(rect, 3, 3)
        max_offset = max(1, total - visible)
        span = rect.height() if vertical else rect.width()
        thumb_span = max(16.0, span * min(1.0, visible / max(1, total)))
        thumb_pos = (span - thumb_span) * (offset / max_offset)
        thumb = QRectF(rect.x(), rect.y() + thumb_pos, rect.width(), thumb_span) if vertical else QRectF(rect.x() + thumb_pos, rect.y(), thumb_span, rect.height())
        painter.setBrush(QBrush(QColor("#4f6b7a")))
        painter.drawRoundedRect(thumb, 3, 3)

    def _set_scroll_from_pos(self, scene_pos: QPointF, view: QRectF) -> None:
        lines = self._pretty_text.splitlines() or [""]
        cols = max((len(line) for line in lines), default=0)
        visible_cols = max(1, int((view.width() - _SCROLLBAR) / 7.0))
        visible_lines = max(1, int((view.height() - _SCROLLBAR) / _LINE_H))
        if self._drag_scroll == "v":
            bar = self._vbar_rect(view)
            ratio = 0.0 if bar.height() <= 1 else (scene_pos.y() - bar.y()) / bar.height()
            self._scroll_y = int(round(max(0.0, min(1.0, ratio)) * max(0, len(lines) - visible_lines)))
        elif self._drag_scroll == "h":
            bar = self._hbar_rect(view)
            ratio = 0.0 if bar.width() <= 1 else (scene_pos.x() - bar.x()) / bar.width()
            self._scroll_x = int(round(max(0.0, min(1.0, ratio)) * max(0, cols - visible_cols)))
        self._clamp_scroll(visible_cols, visible_lines)
