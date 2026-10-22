"""User-authored Script and Formula nodes with inferred, persistent ports."""
from __future__ import annotations

import copy
import html
import math
import threading
from typing import Any

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QPainter
from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QPlainTextEdit,
    QScrollArea, QVBoxLayout, QWidget,
)

from core.command_history import Command
from core.expression_engine import ExpressionError, Interpreter, Program, parse_program
from core.localization import tr
from core.node_base import NodeBase
from core.node_preview import VALUE_HEIGHT, paint_value
from core.types import PinDescriptor, PinDirection, PinType
from ui.script_highlighter import PythonHighlighter


class _SourceEditCmd(Command):
    """Restore code, inferred pins, constants and removed wires in one undo step."""

    def __init__(self, node, before, after, changed) -> None:
        self.node, self.before, self.after, self.changed = node, before, after, changed
        self.description = f"Edit {node.NODE_NAME}"

    def _apply(self, snapshot) -> None:
        state, wires = snapshot
        self.node.set_state(copy.deepcopy(state))
        runtime = self.node._runtime
        if runtime is not None:
            wanted = {wire.wire_id for wire in wires}
            for wire in list(runtime.wires.values()):
                if (wire.src_node == self.node.node_id or wire.dst_node == self.node.node_id) and wire.wire_id not in wanted:
                    runtime.remove_wire(wire.wire_id)
            for wire in wires:
                if wire.wire_id not in runtime.wires:
                    runtime.add_wire(wire)
        self.changed()

    def undo(self) -> None:
        self._apply(self.before)

    def redo(self) -> None:
        self._apply(self.after)


class _SourceNode(NodeBase):
    MIN_WIDTH = 280.0
    CONTEXT_ONLY_FIELDS = True
    SOURCE_FIELD = ""
    IS_FORMULA = False

    def __init__(self, *args, **kwargs) -> None:
        self._source_lock = threading.RLock()
        self._evaluating = False
        self._program: Program | None = None
        self._inputs: tuple[str, ...] = ()
        self._outputs: tuple[str, ...] = ()
        self._event_inputs: tuple[str, ...] = ()
        self._event_outputs: tuple[str, ...] = ()
        self._error = ""
        self._faulted = False
        self._source_revision = 0
        self.PINS = []
        self.VARIABLE_INPUTS = {}
        super().__init__(*args, **kwargs)
        self.NODE_TOOLTIP = tr(f"node.{self.SOURCE_FIELD}.tooltip", default=self.NODE_TOOLTIP)
        self._rebuild()

    @property
    def last_error(self) -> str:
        return self._error

    @staticmethod
    def _input_pin(name: str) -> str:
        return f"input:{name}"

    @staticmethod
    def _output_pin(name: str) -> str:
        return f"output:{name}"

    @staticmethod
    def _event_input_pin(name: str) -> str:
        return f"event_in:{name}"

    @staticmethod
    def _event_output_pin(name: str) -> str:
        return f"event_out:{name}"

    def _set_error(self, message: str) -> None:
        if message != self._error:
            self._error = message
            self.node_changed.emit()
            if message:
                self.log_message.emit(f"{self.NODE_NAME}: {message}")

    def _rebuild(self, fallback: dict | None = None) -> None:
        """Parse without running code; invalid edits retain the last port layout."""
        self._program = None
        self._faulted = False
        self._source_revision += 1
        try:
            program = parse_program(str(self.get_field(self.SOURCE_FIELD)), formula=self.IS_FORMULA)
        except Exception as exc:
            self._set_error(f"{type(exc).__name__}: {exc}")
            if fallback is not None:
                def names(key):
                    return tuple(dict.fromkeys(str(name) for name in fallback.get(key, [])
                                               if isinstance(name, str) and name.strip() and len(name) <= 80))[:2000]
                self._inputs, self._outputs = names("inputs"), names("outputs")
                self._event_inputs, self._event_outputs = names("event_inputs"), names("event_outputs")
        else:
            self._program = program
            self._inputs, self._outputs = program.inputs, program.outputs
            self._event_inputs, self._event_outputs = program.event_inputs, program.event_outputs
            self._set_error("")

        pins: list[PinDescriptor] = []
        if not self.IS_FORMULA:
            pins += [PinDescriptor(self._event_input_pin(name), PinDirection.INPUT, PinType.TICK,
                                   label=name) for name in self._event_inputs]
            pins += [PinDescriptor(self._event_output_pin(name), PinDirection.OUTPUT, PinType.TICK,
                                   label=name) for name in self._event_outputs]
        pins += [PinDescriptor(self._input_pin(name), PinDirection.INPUT,
                               PinType.FLOAT if self.IS_FORMULA else PinType.ANY,
                               default=0.0 if self.IS_FORMULA else None, label=name)
                 for name in self._inputs]
        pins += ([PinDescriptor("result", PinDirection.OUTPUT, PinType.FLOAT)] if self.IS_FORMULA else
                 [PinDescriptor(self._output_pin(name), PinDirection.OUTPUT, PinType.ANY, label=name)
                  for name in self._outputs])
        self.PINS = pins
        self.VARIABLE_INPUTS = ({self._input_pin(name): (float, 0.0) for name in self._inputs}
                                if self.IS_FORMULA else {})
        self._var_inputs = {name: self._var_inputs.get(name, default)
                            for name, (_, default) in self.VARIABLE_INPUTS.items()}
        valid = {(pin.direction, pin.name) for pin in pins}
        valid_names = {pin.name for pin in pins}
        self._data = {name: value for name, value in self._data.items() if name in valid_names}
        if self._runtime is not None:
            for wire in list(self._runtime.wires.values()):
                if ((wire.src_node == self.node_id and (PinDirection.OUTPUT, wire.src_pin) not in valid)
                        or (wire.dst_node == self.node_id and (PinDirection.INPUT, wire.dst_pin) not in valid)):
                    self._runtime.remove_wire(wire.wire_id)
        self.node_changed.emit()

    def set_field(self, name: str, raw_value: str) -> None:
        with self._source_lock:
            super().set_field(name, raw_value)
        if name == self.SOURCE_FIELD and self.IS_FORMULA:
            self._compute()

    def on_field_changed(self, name: str, value: Any) -> None:
        if name == self.SOURCE_FIELD:
            self._rebuild()

    def get_state(self) -> dict[str, Any]:
        with self._source_lock:
            state = super().get_state()
            state["__source_ports__"] = {
                "inputs": list(self._inputs), "outputs": list(self._outputs),
                "event_inputs": list(self._event_inputs), "event_outputs": list(self._event_outputs),
            }
            return state

    def set_state(self, state: dict[str, Any]) -> None:
        with self._source_lock:
            state = copy.deepcopy(state)
            fallback = state.pop("__source_ports__", {})
            fields = state.setdefault("__fields__", {})
            fields[self.SOURCE_FIELD] = str(fields.get(self.SOURCE_FIELD,
                                                      self.EDITABLE_FIELDS[self.SOURCE_FIELD][1]))
            self._fields[self.SOURCE_FIELD] = fields[self.SOURCE_FIELD]
            self._rebuild(fallback)
            super().set_state(state)
            self.node_changed.emit()
        if self.IS_FORMULA:
            self._compute()

    def _snapshot(self):
        wires = [] if self._runtime is None else [
            wire for wire in self._runtime.wires.values()
            if wire.src_node == self.node_id or wire.dst_node == self.node_id
        ]
        return copy.deepcopy(self.get_state()), wires

    def edit_source(self, canvas) -> None:
        dialog = QDialog(canvas)
        dialog.setWindowTitle(tr(f"node.{self.SOURCE_FIELD}.edit"))
        dialog.resize(700, 520 if not self.IS_FORMULA else 460)
        layout = QVBoxLayout(dialog)
        hint = QLabel(tr(f"node.{self.SOURCE_FIELD}.help"), dialog)
        hint.setWordWrap(True)
        hint.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(hint)
        editor = QPlainTextEdit(dialog)
        editor.setFont(QFont("Courier New", 10))
        editor.setStyleSheet("QPlainTextEdit { background: #0d1117; color: #d6deeb; selection-background-color: #334b70; }")
        editor.setPlainText(str(self.get_field(self.SOURCE_FIELD)))
        editor.setTabStopDistance(editor.fontMetrics().horizontalAdvance(" ") * 4)
        if not self.IS_FORMULA:
            editor.highlighter = PythonHighlighter(editor.document())
        layout.addWidget(editor)
        preview = QLabel(dialog)
        preview.setWordWrap(True)
        preview.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(preview)
        constant_editors: dict[str, QLineEdit] = {}
        constant_text: dict[str, str] = {
            name: str(self._var_inputs.get(self._input_pin(name), 0.0)) for name in self._inputs
        }
        constant_names: tuple[str, ...] | None = None
        if self.IS_FORMULA:
            constants_hint = QLabel(tr("node.formula.constants_help"), dialog)
            constants_hint.setWordWrap(True)
            layout.addWidget(constants_hint)
            constants_area = QScrollArea(dialog)
            constants_area.setWidgetResizable(True)
            constants_area.setMinimumHeight(100)
            layout.addWidget(constants_area)

        def sync_constants(names: tuple[str, ...]) -> None:
            nonlocal constant_names
            if not self.IS_FORMULA or names == constant_names:
                return
            constant_text.update({name: field.text() for name, field in constant_editors.items()})
            constant_editors.clear()
            old = constants_area.takeWidget()
            if old is not None:
                old.deleteLater()
            body = QWidget(constants_area)
            form = QFormLayout(body)
            for name in names:
                field = QLineEdit(constant_text.get(name, "0"), body)
                constant_editors[name] = field
                form.addRow(QLabel(name, body), field)
            constants_area.setWidget(body)
            constant_names = names

        def validate():
            try:
                program = parse_program(editor.toPlainText(), formula=self.IS_FORMULA)
                outputs = ("result",) if self.IS_FORMULA else program.outputs
                preview.setText(tr("node.source.ports").format(
                    inputs=", ".join(program.inputs) or "—", outputs=", ".join(outputs) or "—"))
                if not self.IS_FORMULA:
                    preview.setText(preview.text() + "\n" + tr("node.source.events").format(
                        inputs=", ".join(program.event_inputs) or "—",
                        outputs=", ".join(program.event_outputs) or "—"))
                sync_constants(program.inputs)
                preview.setStyleSheet("color: #66bb6a")
            except Exception as exc:
                preview.setText(str(exc))
                preview.setStyleSheet("color: #ef5350")

        editor.textChanged.connect(validate)
        validate()
        if self.IS_FORMULA and constant_names is None:
            sync_constants(self._inputs)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, dialog)
        constants: dict[str, float] = {}

        def accept() -> None:
            constants.clear()
            for name, field in constant_editors.items():
                try:
                    value = float(field.text())
                    if not math.isfinite(value):
                        raise ValueError()
                except ValueError:
                    preview.setText(tr("node.formula.invalid_constant").format(name=name))
                    preview.setStyleSheet("color: #ef5350")
                    field.setFocus()
                    field.selectAll()
                    return
                constants[name] = value
            dialog.accept()

        buttons.accepted.connect(accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            source = editor.toPlainText()
            source_changed = source != self.get_field(self.SOURCE_FIELD)
            constants_changed = any(value != self._var_inputs.get(self._input_pin(name), 0.0)
                                    for name, value in constants.items())
            if source_changed or constants_changed:
                before = self._snapshot()
                with self._source_lock:
                    if source_changed:
                        self._fields[self.SOURCE_FIELD] = source
                        self._rebuild()
                    for name, value in constants.items():
                        pin = self._input_pin(name)
                        if pin in self.VARIABLE_INPUTS:
                            self._var_inputs[pin] = value
                if self.IS_FORMULA:
                    self._compute()
                def changed():
                    canvas.configuration_changed.emit()
                    canvas.update()
                canvas._history.push(_SourceEditCmd(self, before, self._snapshot(), changed))
                changed()

    def _show_error(self, canvas) -> None:
        dialog = QDialog(canvas)
        dialog.setWindowTitle(tr("node.source.error_title"))
        dialog.resize(640, 260)
        layout = QVBoxLayout(dialog)
        details = QPlainTextEdit(dialog)
        details.setReadOnly(True)
        details.setPlainText(self._error)
        layout.addWidget(details)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, dialog)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()

    def _get_context_menu(self, canvas, menu, field_hit=None) -> None:
        edit = menu.addAction(tr(f"node.{self.SOURCE_FIELD}.edit"))
        edit.triggered.connect(lambda: self.edit_source(canvas))
        error = menu.addAction(tr("node.source.view_error"))
        error.setEnabled(bool(self._error))
        error.triggered.connect(lambda: self._show_error(canvas))
        if not self.IS_FORMULA:
            retry = menu.addAction(tr("node.script.retry"))
            retry.setEnabled(self._faulted and self._program is not None)
            retry.triggered.connect(self._retry)

    def paint_title_status(self, painter: QPainter, rect: QRectF) -> None:
        if self._error:
            painter.setPen(QColor("#ff5252"))
            painter.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
            painter.drawText(QRectF(rect.right() - 14, rect.top(), 10, rect.height()),
                             Qt.AlignmentFlag.AlignCenter, "!")

    def title_status_tooltip(self) -> str:
        return html.escape(self._error)


class ScriptNode(_SourceNode):
    """Run bounded Python event handlers through inferred data/event ports."""
    NODE_NAME = "Script Node"
    NODE_GROUP = "Utility"
    SOURCE_FIELD = "script"
    EDITABLE_FIELDS = {"script": (str, 'def on_tick():\n    value = read("value")\n    write("result", value)\n    emit("done")')}
    NODE_TOOLTIP = "Python event handlers: read/write data and emit/on_name events. Right-click to edit or inspect errors."

    def on_start(self) -> None:
        with self._source_lock:
            self._rebuild()

    def _retry(self) -> None:
        with self._source_lock:
            self._faulted = False
            if self._program is not None:
                self._set_error("")

    def execute(self, trigger_pin: str) -> None:
        with self._source_lock:
            if self._program is None or self._faulted or self._evaluating:
                return
            if not trigger_pin.startswith("event_in:"):
                return
            event = trigger_pin.removeprefix("event_in:")
            if event not in self._program.event_inputs:
                return
            self._evaluating = True
            revision = self._source_revision
            interpreter = Interpreter({}, lambda name: self.get_input(self._input_pin(name)))
            try:
                outputs = interpreter.run(self._program, event=event)
            except Exception as exc:
                self._faulted = True
                self._set_error(str(exc))
                self._evaluating = False
                return
            self._set_error("")
            # No data or named event is published until the whole handler succeeds.
            staged = {self._output_pin(name): value for name, value in outputs.items()}
            events = tuple(interpreter.events)
            self._data.update(staged)
        # Never hold a node lock while invoking another node through a wire.
        try:
            for name, value in staged.items():
                if revision != self._source_revision:
                    return
                self.set_output(name, value)
            for name in events:
                if revision != self._source_revision:
                    return
                self.fire_tick(self._event_output_pin(name))
        finally:
            with self._source_lock:
                self._evaluating = False


class FormulaNode(_SourceNode):
    """Evaluate a math expression; inferred parameters accept wires or constants."""
    NODE_NAME = "Formula Node"
    NODE_GROUP = "Math/Arithmetic"
    SOURCE_FIELD = "formula"
    IS_FORMULA = True
    EDITABLE_FIELDS = {"formula": (str, "a * x + b")}
    NODE_TOOLTIP = "Formula preview with automatic parameter inputs and one result output. Right-click to edit."
    MIN_HEIGHT = 60.0 + VALUE_HEIGHT

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._compute()

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        formula = " ".join(str(self.get_field(self.SOURCE_FIELD)).split())
        paint_value(painter, rect, formula or "—", "#ef5350" if self._error else "#aeb9cc")

    def on_start(self) -> None:
        self._compute()

    def on_output_wire_connected(self, pin_name: str) -> None:
        self._compute()

    def on_data_received(self, pin_name: str, value: Any) -> None:
        self._compute()

    def on_var_input_changed(self, pin_name: str, value: Any) -> None:
        self._compute()

    def execute(self, trigger_pin: str) -> None:
        self._compute()

    def _compute(self) -> None:
        with self._source_lock:
            if self._program is None or self._evaluating:
                return
            self._evaluating = True
            revision = self._source_revision
            try:
                parameters = {name: float(self.get_var_input(self._input_pin(name))) for name in self._inputs}
                result = float(Interpreter(parameters).run(self._program))
                if not math.isfinite(result):
                    raise ExpressionError("Formula result must be finite")
            except Exception as exc:
                self._set_error(str(exc))
                self._evaluating = False
                return
            self._set_error("")
        try:
            if revision == self._source_revision:
                self.set_output("result", result)
        finally:
            with self._source_lock:
                self._evaluating = False
