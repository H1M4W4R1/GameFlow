"""Built-in WebSocket server nodes."""
from __future__ import annotations

import abc
import asyncio
import json
import logging
import queue
import threading
import weakref
from typing import Any

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QAction, QBrush, QColor, QPainter
from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QLineEdit, QMenu, QSpinBox, QVBoxLayout,
)

from core.localization import tr
from core.node_base import NodeBase
from core.types import PinDescriptor, PinDirection, PinType

log = logging.getLogger(__name__)


class _SharedWebSocketServer:
    """Single process-wide WebSocket listener used by all WebSocket nodes."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._subscribers: weakref.WeakSet[Any] = weakref.WeakSet()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._server: Any = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._startup_error: str | None = None
        self._host = "127.0.0.1"
        self._port = 8765
        self._is_serving = False
        self._clients: set[Any] = set()

    @property
    def host(self) -> str:
        return self._host

    @property
    def port(self) -> int:
        return self._port

    @property
    def is_serving(self) -> bool:
        return self._is_serving

    @property
    def startup_error(self) -> str | None:
        return self._startup_error

    def subscribe(self, node: Any, host: str, port: int) -> None:
        with self._lock:
            self._subscribers.add(node)
            if not self._is_serving:
                self._start_locked(host, port)
            elif host != self._host or port != self._port:
                node.log_message.emit(
                    f"WebSocket server already running at ws://{self._host}:{self._port}"
                )
            node.node_changed.emit()

    def unsubscribe(self, node: Any) -> None:
        with self._lock:
            self._subscribers.discard(node)
            if not self._subscribers:
                self._stop_locked()

    def reconfigure_from(self, node: Any, host: str, port: int) -> None:
        with self._lock:
            if node not in self._subscribers:
                return
            if host == self._host and port == self._port:
                return
            self._stop_locked()
            if self._subscribers:
                self._start_locked(host, port)
                for subscriber in list(self._subscribers):
                    subscriber.node_changed.emit()

    def send_json(self, data: Any) -> None:
        try:
            message = json.dumps(data, ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            log.warning("Ignoring non-serializable WebSocket JSON data: %s", exc)
            return

        loop = self._loop
        if loop and loop.is_running():
            loop.call_soon_threadsafe(
                lambda: asyncio.create_task(self._send_to_clients(message))
            )

    def _start_locked(self, host: str, port: int) -> None:
        if self._thread and self._thread.is_alive():
            return

        self._host = host
        self._port = port
        self._startup_error = None
        self._ready.clear()
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="SensoryFlow-WebSocketServer",
            daemon=True,
        )
        self._thread.start()
        self._ready.wait(timeout=3.0)
        if self._startup_error:
            log.error(self._startup_error)

    def _stop_locked(self) -> None:
        loop = self._loop
        if loop and loop.is_running():
            loop.call_soon_threadsafe(loop.stop)
        if self._thread:
            self._thread.join(timeout=2.0)
        self._thread = None
        self._loop = None
        self._server = None
        self._clients.clear()
        self._is_serving = False

    def _run_loop(self) -> None:
        loop = self._loop
        if loop is None:
            return

        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._async_start_server())
            self._ready.set()
            loop.run_forever()
        except Exception as exc:
            self._startup_error = f"WebSocket server failed: {exc}"
            self._ready.set()
        finally:
            try:
                loop.run_until_complete(self._async_stop_server())
                pending = [task for task in asyncio.all_tasks(loop) if not task.done()]
                for task in pending:
                    task.cancel()
                if pending:
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            finally:
                loop.close()

    async def _async_start_server(self) -> None:
        import websockets  # type: ignore

        self._server = await websockets.serve(self._handle_client, self._host, self._port)
        self._is_serving = True

    async def _async_stop_server(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
        clients = list(self._clients)
        for websocket in clients:
            await websocket.close()
        self._clients.clear()
        self._is_serving = False

    async def _handle_client(self, websocket: Any) -> None:
        self._clients.add(websocket)
        try:
            async for message in websocket:
                try:
                    data = json.loads(message)
                except (TypeError, ValueError) as exc:
                    log.warning("Ignoring invalid WebSocket JSON message: %s", exc)
                    continue

                with self._lock:
                    subscribers = list(self._subscribers)
                for node in subscribers:
                    if isinstance(node, WebSocketNodeBase):
                        node.enqueue_message(data)
        finally:
            self._clients.discard(websocket)

    async def _send_to_clients(self, message: str) -> None:
        dead: list[Any] = []
        for websocket in list(self._clients):
            try:
                await websocket.send(message)
            except Exception as exc:
                log.debug("WebSocket client send failed: %s", exc)
                dead.append(websocket)
        for websocket in dead:
            self._clients.discard(websocket)


_SHARED_SERVER = _SharedWebSocketServer()


class WebSocketNodeBase(NodeBase):
    """Base for nodes driven by JSON received on the shared WebSocket server."""

    __abstractmethods__ = frozenset({"should_execute_for_message"})
    NODE_GROUP = "Servers/WebSocket"
    MIN_WIDTH = 210.0
    MIN_HEIGHT = 60.0
    TICK_OUTPUT_PIN = ""
    DATA_OUTPUT_PIN = "data"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._messages: queue.Queue[Any] = queue.Queue()
        self._ws_host = "127.0.0.1"
        self._ws_port = 8765

    def on_start(self) -> None:
        _SHARED_SERVER.subscribe(self, self._configured_host(), self._configured_port())

    def on_stop(self) -> None:
        _SHARED_SERVER.unsubscribe(self)

    def enqueue_message(self, data: Any) -> None:
        self._messages.put(data)

    def on_tick_check(self) -> None:
        while True:
            try:
                data = self._messages.get_nowait()
            except queue.Empty:
                return
            if not self.should_execute_for_message(data):
                continue
            self.on_websocket_message(data)

    def execute(self, trigger_pin: str) -> None:
        pass

    @abc.abstractmethod
    def should_execute_for_message(self, data: Any) -> bool:
        """Return True when this JSON message should execute the node."""

    def on_websocket_message(self, data: Any) -> None:
        if self.DATA_OUTPUT_PIN:
            self.set_output(self.DATA_OUTPUT_PIN, data)
        if self.TICK_OUTPUT_PIN:
            self.fire_tick(self.TICK_OUTPUT_PIN)
        self.node_changed.emit()

    def on_output_wire_connected(self, pin_name: str) -> None:
        if pin_name == self.DATA_OUTPUT_PIN and self.DATA_OUTPUT_PIN in self._data:
            self.set_output(self.DATA_OUTPUT_PIN, self._data[self.DATA_OUTPUT_PIN])

    def get_websocket_config(self) -> tuple[str, int]:
        return self._configured_host(), self._configured_port()

    def set_websocket_config(self, host: str, port: int) -> None:
        self._ws_host = str(host).strip() or "127.0.0.1"
        self._ws_port = self._coerce_port(port)
        _SHARED_SERVER.reconfigure_from(self, self._ws_host, self._ws_port)
        self.node_changed.emit()

    def _get_context_menu(self, canvas: Any, menu: QMenu, field_hit: Any = None) -> None:
        ws_act = QAction(
            tr("ui.canvas.menu.websocket_server", default="WebSocket server..."),
            menu,
        )
        ws_act.triggered.connect(lambda: self._open_websocket_config_dialog(canvas))
        menu.addAction(ws_act)

    def _open_websocket_config_dialog(self, canvas: Any) -> None:
        host, port = self.get_websocket_config()
        dlg = QDialog(canvas)
        dlg.setWindowTitle(tr("ui.dialog.websocket_server.title", default="WebSocket Server"))
        dlg.setModal(True)

        layout = QVBoxLayout(dlg)
        form = QFormLayout()
        host_editor = QLineEdit(dlg)
        host_editor.setText(str(host))
        port_editor = QSpinBox(dlg)
        port_editor.setRange(1, 65535)
        port_editor.setValue(int(port))
        form.addRow(tr("ui.dialog.websocket_server.host", default="Host:"), host_editor)
        form.addRow(tr("ui.dialog.websocket_server.port", default="Port:"), port_editor)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            dlg,
        )
        layout.addWidget(buttons)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)

        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.set_websocket_config(host_editor.text(), port_editor.value())
            canvas.update()

    def paint_title_status(self, painter: QPainter, rect: QRectF) -> None:
        if _SHARED_SERVER.startup_error:
            color = QColor("#ffb300")
        elif _SHARED_SERVER.is_serving:
            color = QColor("#4caf50")
        else:
            color = QColor("#616161")

        dot_r = 5.0
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(color))
        painter.drawEllipse(
            QRectF(
                rect.right() - dot_r * 2 - 4,
                rect.top() + (rect.height() - dot_r * 2) / 2,
                dot_r * 2,
                dot_r * 2,
            )
        )

    def title_status_tooltip(self) -> str:
        url = f"ws://{_SHARED_SERVER.host}:{_SHARED_SERVER.port}"
        if _SHARED_SERVER.startup_error:
            status = "error"
        elif _SHARED_SERVER.is_serving:
            status = "listening"
        else:
            status = "stopped"
        return f"<b>{url}</b><br><small style='color:#aaa'>{status}</small>"

    def get_state(self) -> dict[str, Any]:
        state = super().get_state()
        state["__websocket_config__"] = {
            "host": self._configured_host(),
            "port": self._configured_port(),
        }
        return state

    def set_state(self, state: dict[str, Any]) -> None:
        state.pop("__message_count__", None)
        ws_config = state.pop("__websocket_config__", None)
        legacy_fields = state.get("__fields__")
        if isinstance(ws_config, dict):
            self._ws_host = str(ws_config.get("host") or "127.0.0.1").strip() or "127.0.0.1"
            self._ws_port = self._coerce_port(ws_config.get("port", 8765))
        elif isinstance(legacy_fields, dict):
            self._ws_host = str(legacy_fields.get("host") or "127.0.0.1").strip() or "127.0.0.1"
            self._ws_port = self._coerce_port(legacy_fields.get("port", 8765))
        super().set_state(state)

    def _configured_host(self) -> str:
        return str(self._ws_host or "127.0.0.1").strip() or "127.0.0.1"

    def _configured_port(self) -> int:
        return self._coerce_port(self._ws_port)

    def _coerce_port(self, value: Any) -> int:
        try:
            port = int(value)
        except (TypeError, ValueError):
            port = 8765
        return max(1, min(65535, port))


class WebSocketMessageNode(WebSocketNodeBase):
    """Emit every JSON message received on the shared WebSocket server."""

    __abstractmethods__ = frozenset()
    NODE_NAME = "On WebSocket Message"
    NODE_TITLE_COLOR = "#124a5f"
    TICK_OUTPUT_PIN = "on_message"

    PINS = [
        PinDescriptor(
            "on_message",
            PinDirection.OUTPUT,
            PinType.TICK,
            tooltip="Fires every time the server receives a valid JSON message.",
        ),
        PinDescriptor(
            "data",
            PinDirection.OUTPUT,
            PinType.ANY,
            tooltip="Parsed JSON data from the latest received message.",
        ),
    ]

    def should_execute_for_message(self, data: Any) -> bool:
        return True


class WebSocketEventNode(WebSocketNodeBase):
    """Emit only WebSocket messages whose JSON event field matches this node."""

    __abstractmethods__ = frozenset()
    NODE_NAME = "On WebSocket Event"
    NODE_TITLE_COLOR = "#16423a"
    TICK_OUTPUT_PIN = "on_event"

    PINS = [
        PinDescriptor(
            "on_event",
            PinDirection.OUTPUT,
            PinType.TICK,
            tooltip="Fires when a WebSocket JSON message has a matching event field.",
        ),
        PinDescriptor(
            "data",
            PinDirection.OUTPUT,
            PinType.ANY,
            tooltip="Parsed JSON data from the matching WebSocket message.",
        ),
    ]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._event_name = ""

    def should_execute_for_message(self, data: Any) -> bool:
        if not isinstance(data, dict):
            return False
        return str(data.get("event", "")) == self._event_name

    def get_event_name(self) -> str:
        return self._event_name

    def set_event_name(self, event_name: str) -> None:
        self._event_name = str(event_name).strip()
        self.node_changed.emit()

    def _get_context_menu(self, canvas: Any, menu: QMenu, field_hit: Any = None) -> None:
        super()._get_context_menu(canvas, menu, field_hit)
        event_act = QAction(
            tr("ui.canvas.menu.edit_event_name", default="Edit event name..."),
            menu,
        )
        event_act.triggered.connect(lambda: self._open_event_name_dialog(canvas))
        menu.addAction(event_act)

    def _open_event_name_dialog(self, canvas: Any) -> None:
        dlg = QDialog(canvas)
        dlg.setWindowTitle(tr("ui.dialog.event_name.title", default="Edit Event Name"))
        dlg.setModal(True)

        layout = QVBoxLayout(dlg)
        editor = QLineEdit(dlg)
        editor.setText(str(self.get_event_name()))
        editor.selectAll()
        layout.addWidget(editor)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            dlg,
        )
        layout.addWidget(buttons)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)

        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.set_event_name(editor.text())
            canvas.update()

    def title_status_tooltip(self) -> str:
        base = super().title_status_tooltip()
        event_name = self._event_name or "(empty)"
        return base.replace("</small>", f" · event: {event_name}</small>")

    def get_state(self) -> dict[str, Any]:
        state = super().get_state()
        state["__event_name__"] = self._event_name
        return state

    def set_state(self, state: dict[str, Any]) -> None:
        self._event_name = str(state.pop("__event_name__", ""))
        super().set_state(state)


class WebSocketSendJsonNode(WebSocketNodeBase):
    """Send JSON data to all clients connected to the shared WebSocket server."""

    __abstractmethods__ = frozenset()
    NODE_NAME = "WebSocket Send JSON"
    NODE_TITLE_COLOR = "#5b3f24"
    MIN_WIDTH = 220.0
    VARIABLE_INPUTS = {"data": (str, "{}")}

    PINS = [
        PinDescriptor(
            "exec_in",
            PinDirection.INPUT,
            PinType.TICK,
            tooltip="Send the JSON data when this tick fires.",
        ),
        PinDescriptor(
            "exec_out",
            PinDirection.OUTPUT,
            PinType.TICK,
            tooltip="Fires after the send request is queued.",
        ),
        PinDescriptor(
            "data",
            PinDirection.INPUT,
            PinType.ANY,
            default={},
            tooltip="JSON-serializable data to send to connected WebSocket clients.",
        ),
    ]

    def execute(self, trigger_pin: str) -> None:
        try:
            data = self._coerce_json_data(self.get_var_input("data"))
        except ValueError as exc:
            self.log_message.emit(f"WebSocket Send JSON ignored invalid JSON: {exc}")
            self.fire_tick("exec_out")
            return

        _SHARED_SERVER.send_json(data)
        self.fire_tick("exec_out")

    def should_execute_for_message(self, data: Any) -> bool:
        return False

    def _coerce_json_data(self, value: Any) -> Any:
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return {}
            return json.loads(text)
        return value
