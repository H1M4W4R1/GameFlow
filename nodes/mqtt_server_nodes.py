"""Built-in MQTT server nodes."""
from __future__ import annotations

import abc
import asyncio
import json
import logging
import queue
import threading
import weakref
from dataclasses import dataclass, field
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


@dataclass(eq=False)
class _MqttClient:
    writer: asyncio.StreamWriter
    subscriptions: set[str] = field(default_factory=set)


def _encode_remaining_length(value: int) -> bytes:
    encoded = bytearray()
    while True:
        digit = value % 128
        value //= 128
        if value > 0:
            digit |= 0x80
        encoded.append(digit)
        if value == 0:
            return bytes(encoded)


def _encode_utf8(value: str) -> bytes:
    data = value.encode("utf-8")
    return len(data).to_bytes(2, "big") + data


def _read_utf8(buffer: bytes, offset: int) -> tuple[str, int]:
    if offset + 2 > len(buffer):
        raise ValueError("missing MQTT string length")
    length = int.from_bytes(buffer[offset:offset + 2], "big")
    offset += 2
    if offset + length > len(buffer):
        raise ValueError("truncated MQTT string")
    return buffer[offset:offset + length].decode("utf-8", errors="replace"), offset + length


def _topic_matches(topic_filter: str, topic: str) -> bool:
    """Return True when an MQTT topic filter matches a concrete topic."""
    topic_filter = (topic_filter or "#").strip() or "#"
    if topic_filter == "#":
        return True

    filter_levels = topic_filter.split("/")
    topic_levels = topic.split("/")
    for index, level in enumerate(filter_levels):
        if level == "#":
            return index == len(filter_levels) - 1
        if index >= len(topic_levels):
            return False
        if level != "+" and level != topic_levels[index]:
            return False
    return len(topic_levels) == len(filter_levels)


def _coerce_payload(value: Any) -> bytes:
    if value is None:
        return b""
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    if isinstance(value, str):
        return value.encode("utf-8")
    try:
        return json.dumps(value, ensure_ascii=False).encode("utf-8")
    except (TypeError, ValueError):
        return str(value).encode("utf-8")


def _message_dict(topic: str, payload: bytes, qos: int = 0, retain: bool = False) -> dict[str, Any]:
    text = payload.decode("utf-8", errors="replace")
    return {
        "topic": topic,
        "payload": payload,
        "text": text,
        "qos": qos,
        "retain": retain,
    }


class _SharedMqttServer:
    """Single process-wide MQTT broker used by all MQTT nodes."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._nodes: weakref.WeakSet[Any] = weakref.WeakSet()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._server: asyncio.AbstractServer | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._startup_error: str | None = None
        self._host = "127.0.0.1"
        self._port = 1883
        self._is_serving = False
        self._clients: set[_MqttClient] = set()

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

    def register(self, node: "MqttConfiguredNode", host: str, port: int) -> None:
        with self._lock:
            self._nodes.add(node)
            if not self._is_serving:
                self._start_locked(host, port)
            elif host != self._host or port != self._port:
                node.log_message.emit(
                    f"MQTT server already running at mqtt://{self._host}:{self._port}"
                )
            node.node_changed.emit()

    def unregister(self, node: "MqttConfiguredNode") -> None:
        with self._lock:
            self._nodes.discard(node)
            if not self._nodes:
                self._stop_locked()

    def reconfigure_from(self, node: "MqttConfiguredNode", host: str, port: int) -> None:
        with self._lock:
            if node not in self._nodes:
                return
            if host == self._host and port == self._port:
                return
            self._stop_locked()
            if self._nodes:
                self._start_locked(host, port)
                for subscriber in list(self._nodes):
                    subscriber.node_changed.emit()

    def publish(self, topic: str, payload: Any, retain: bool = False) -> None:
        topic = str(topic or "").strip()
        if not topic:
            return
        payload_bytes = _coerce_payload(payload)
        message = _message_dict(topic, payload_bytes, qos=0, retain=retain)
        self._dispatch_to_nodes(message)
        loop = self._loop
        if loop and loop.is_running():
            loop.call_soon_threadsafe(
                lambda: asyncio.create_task(self._publish_to_clients(topic, payload_bytes, retain))
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
            name="SensoryFlow-MqttServer",
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
            self._startup_error = f"MQTT server failed: {exc}"
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
        self._server = await asyncio.start_server(self._handle_client, self._host, self._port)
        self._is_serving = True

    async def _async_stop_server(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
        clients = list(self._clients)
        for client in clients:
            client.writer.close()
        for client in clients:
            await client.writer.wait_closed()
        self._is_serving = False

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        client = _MqttClient(writer)
        self._clients.add(client)
        try:
            while True:
                packet_type, flags, payload = await self._read_packet(reader)
                if packet_type == 1:
                    await self._handle_connect(writer)
                elif packet_type == 3:
                    await self._handle_publish(writer, flags, payload)
                elif packet_type == 8:
                    await self._handle_subscribe(client, payload)
                elif packet_type == 10:
                    await self._handle_unsubscribe(client, payload)
                elif packet_type == 12:
                    writer.write(bytes([0xD0, 0x00]))
                    await writer.drain()
                elif packet_type == 14:
                    break
                else:
                    log.debug("Ignoring unsupported MQTT packet type %s", packet_type)
        except (asyncio.IncompleteReadError, ConnectionError, ValueError) as exc:
            log.debug("MQTT client disconnected: %s", exc)
        finally:
            self._clients.discard(client)
            writer.close()
            await writer.wait_closed()

    async def _read_packet(self, reader: asyncio.StreamReader) -> tuple[int, int, bytes]:
        fixed_header = await reader.readexactly(1)
        first = fixed_header[0]
        multiplier = 1
        remaining_length = 0
        while True:
            digit = (await reader.readexactly(1))[0]
            remaining_length += (digit & 127) * multiplier
            if (digit & 128) == 0:
                break
            multiplier *= 128
            if multiplier > 128 * 128 * 128:
                raise ValueError("malformed MQTT remaining length")
        payload = await reader.readexactly(remaining_length) if remaining_length else b""
        return first >> 4, first & 0x0F, payload

    async def _handle_connect(self, writer: asyncio.StreamWriter) -> None:
        writer.write(bytes([0x20, 0x02, 0x00, 0x00]))
        await writer.drain()

    async def _handle_publish(
        self,
        writer: asyncio.StreamWriter,
        flags: int,
        packet: bytes,
    ) -> None:
        topic, offset = _read_utf8(packet, 0)
        qos = (flags >> 1) & 0x03
        packet_id = None
        if qos:
            if offset + 2 > len(packet):
                raise ValueError("missing MQTT packet id")
            packet_id = packet[offset:offset + 2]
            offset += 2
        payload = packet[offset:]
        message = _message_dict(topic, payload, qos=qos, retain=bool(flags & 0x01))
        self._dispatch_to_nodes(message)
        await self._publish_to_clients(topic, payload, retain=bool(flags & 0x01))
        if qos == 1 and packet_id is not None:
            writer.write(bytes([0x40, 0x02]) + packet_id)
            await writer.drain()

    async def _handle_subscribe(self, client: _MqttClient, packet: bytes) -> None:
        if len(packet) < 2:
            raise ValueError("truncated MQTT subscribe packet")
        packet_id = packet[:2]
        offset = 2
        return_codes = bytearray()
        while offset < len(packet):
            topic_filter, offset = _read_utf8(packet, offset)
            if offset >= len(packet):
                raise ValueError("missing MQTT requested QoS")
            offset += 1
            client.subscriptions.add(topic_filter)
            return_codes.append(0)
        client.writer.write(bytes([0x90]) + _encode_remaining_length(2 + len(return_codes)) + packet_id + return_codes)
        await client.writer.drain()

    async def _handle_unsubscribe(self, client: _MqttClient, packet: bytes) -> None:
        if len(packet) < 2:
            raise ValueError("truncated MQTT unsubscribe packet")
        packet_id = packet[:2]
        offset = 2
        while offset < len(packet):
            topic_filter, offset = _read_utf8(packet, offset)
            client.subscriptions.discard(topic_filter)
        client.writer.write(bytes([0xB0, 0x02]) + packet_id)
        await client.writer.drain()

    async def _publish_to_clients(self, topic: str, payload: bytes, retain: bool = False) -> None:
        packet = self._build_publish_packet(topic, payload, retain)
        dead: list[_MqttClient] = []
        for client in list(self._clients):
            if not any(_topic_matches(topic_filter, topic) for topic_filter in client.subscriptions):
                continue
            try:
                client.writer.write(packet)
                await client.writer.drain()
            except ConnectionError:
                dead.append(client)
        for client in dead:
            self._clients.discard(client)

    def _build_publish_packet(self, topic: str, payload: bytes, retain: bool) -> bytes:
        variable = _encode_utf8(topic)
        body = variable + payload
        first = 0x30 | (0x01 if retain else 0x00)
        return bytes([first]) + _encode_remaining_length(len(body)) + body

    def _dispatch_to_nodes(self, message: dict[str, Any]) -> None:
        with self._lock:
            nodes = list(self._nodes)
        for node in nodes:
            if isinstance(node, MqttNodeBase):
                node.enqueue_message(message)


_SHARED_MQTT_SERVER = _SharedMqttServer()


class MqttConfiguredNode(NodeBase):
    """Base for nodes that use the shared MQTT broker configuration."""

    __abstractmethods__ = frozenset({"execute"})
    NODE_GROUP = "Servers/MQTT"
    MIN_WIDTH = 220.0
    _MQTT_DEFAULT_HOST = "127.0.0.1"
    _MQTT_DEFAULT_PORT = 1883

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._mqtt_host = self._MQTT_DEFAULT_HOST
        self._mqtt_port = self._MQTT_DEFAULT_PORT

    def on_start(self) -> None:
        _SHARED_MQTT_SERVER.register(self, self._configured_host(), self._configured_port())

    def on_stop(self) -> None:
        _SHARED_MQTT_SERVER.unregister(self)

    def get_mqtt_config(self) -> tuple[str, int]:
        return self._configured_host(), self._configured_port()

    def set_mqtt_config(self, host: str, port: int) -> None:
        self._mqtt_host = str(host).strip() or self._MQTT_DEFAULT_HOST
        self._mqtt_port = self._coerce_port(port)
        _SHARED_MQTT_SERVER.reconfigure_from(self, self._mqtt_host, self._mqtt_port)
        self.node_changed.emit()

    def _get_context_menu(self, canvas: Any, menu: QMenu, field_hit: Any = None) -> None:
        mqtt_act = QAction(
            tr("ui.canvas.menu.mqtt_server", default="MQTT server..."),
            menu,
        )
        mqtt_act.triggered.connect(lambda: self._open_mqtt_config_dialog(canvas))
        menu.addAction(mqtt_act)

    def _open_mqtt_config_dialog(self, canvas: Any) -> None:
        host, port = self.get_mqtt_config()
        dlg = QDialog(canvas)
        dlg.setWindowTitle(tr("ui.dialog.mqtt_server.title", default="MQTT Server"))
        dlg.setModal(True)

        layout = QVBoxLayout(dlg)
        form = QFormLayout()
        host_editor = QLineEdit(dlg)
        host_editor.setText(str(host))
        port_editor = QSpinBox(dlg)
        port_editor.setRange(1, 65535)
        port_editor.setValue(int(port))
        form.addRow(tr("ui.dialog.mqtt_server.host", default="Host:"), host_editor)
        form.addRow(tr("ui.dialog.mqtt_server.port", default="Port:"), port_editor)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            dlg,
        )
        layout.addWidget(buttons)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)

        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.set_mqtt_config(host_editor.text(), port_editor.value())
            canvas.update()

    def paint_title_status(self, painter: QPainter, rect: QRectF) -> None:
        if _SHARED_MQTT_SERVER.startup_error:
            color = QColor("#ffb300")
        elif _SHARED_MQTT_SERVER.is_serving:
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
        url = f"mqtt://{_SHARED_MQTT_SERVER.host}:{_SHARED_MQTT_SERVER.port}"
        if _SHARED_MQTT_SERVER.startup_error:
            status = "error"
        elif _SHARED_MQTT_SERVER.is_serving:
            status = "listening"
        else:
            status = "stopped"
        return f"<b>{url}</b><br><small style='color:#aaa'>{status}</small>"

    def get_state(self) -> dict[str, Any]:
        state = super().get_state()
        state["__mqtt_config__"] = {
            "host": self._configured_host(),
            "port": self._configured_port(),
        }
        return state

    def set_state(self, state: dict[str, Any]) -> None:
        mqtt_config = state.pop("__mqtt_config__", None)
        if isinstance(mqtt_config, dict):
            self._mqtt_host = str(mqtt_config.get("host") or self._MQTT_DEFAULT_HOST).strip() or self._MQTT_DEFAULT_HOST
            self._mqtt_port = self._coerce_port(mqtt_config.get("port", self._MQTT_DEFAULT_PORT))
        super().set_state(state)

    def _configured_host(self) -> str:
        return str(self._mqtt_host or self._MQTT_DEFAULT_HOST).strip() or self._MQTT_DEFAULT_HOST

    def _configured_port(self) -> int:
        return self._coerce_port(self._mqtt_port)

    def _coerce_port(self, value: Any) -> int:
        try:
            port = int(value)
        except (TypeError, ValueError):
            port = self._MQTT_DEFAULT_PORT
        return max(1, min(65535, port))


class MqttNodeBase(MqttConfiguredNode):
    """Base for nodes driven by messages received on the shared MQTT broker."""

    __abstractmethods__ = frozenset({"should_execute_for_message"})
    TICK_OUTPUT_PIN = ""
    DATA_OUTPUT_PIN = "data"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._messages: queue.Queue[dict[str, Any]] = queue.Queue()

    def enqueue_message(self, message: dict[str, Any]) -> None:
        self._messages.put(message)

    def on_tick_check(self) -> None:
        while True:
            try:
                message = self._messages.get_nowait()
            except queue.Empty:
                return
            if not self.should_execute_for_message(message):
                continue
            self.on_mqtt_message(message)

    def execute(self, trigger_pin: str) -> None:
        pass

    @abc.abstractmethod
    def should_execute_for_message(self, message: dict[str, Any]) -> bool:
        """Return True when this MQTT message should execute the node."""

    def on_mqtt_message(self, message: dict[str, Any]) -> None:
        if self.DATA_OUTPUT_PIN:
            self.set_output(self.DATA_OUTPUT_PIN, message)
        self.set_output("topic", message.get("topic", ""))
        self.set_output("payload", message.get("payload", b""))
        self.set_output("text", message.get("text", ""))
        if self.TICK_OUTPUT_PIN:
            self.fire_tick(self.TICK_OUTPUT_PIN)
        self.node_changed.emit()

    def on_output_wire_connected(self, pin_name: str) -> None:
        if pin_name in self._data:
            self.set_output(pin_name, self._data[pin_name])


class MqttMessageNode(MqttNodeBase):
    """Emit every message received on the shared MQTT broker."""

    __abstractmethods__ = frozenset()
    NODE_NAME = "On MQTT Message"
    NODE_TITLE_COLOR = "#28465f"
    TICK_OUTPUT_PIN = "on_message"

    PINS = [
        PinDescriptor(
            "on_message",
            PinDirection.OUTPUT,
            PinType.TICK,
            tooltip="Fires every time the MQTT broker receives a message.",
        ),
        PinDescriptor("topic", PinDirection.OUTPUT, PinType.STRING),
        PinDescriptor("payload", PinDirection.OUTPUT, PinType.ANY),
        PinDescriptor("text", PinDirection.OUTPUT, PinType.STRING),
        PinDescriptor("data", PinDirection.OUTPUT, PinType.ANY),
    ]

    def should_execute_for_message(self, message: dict[str, Any]) -> bool:
        return True


class MqttTopicNode(MqttNodeBase):
    """Emit MQTT messages whose topic matches this node's topic filter."""

    __abstractmethods__ = frozenset()
    NODE_NAME = "On MQTT Topic"
    NODE_TITLE_COLOR = "#254f3f"
    TICK_OUTPUT_PIN = "on_message"
    EDITABLE_FIELDS = {"topic_filter": (str, "#")}

    PINS = [
        PinDescriptor(
            "on_message",
            PinDirection.OUTPUT,
            PinType.TICK,
            tooltip="Fires when an MQTT message matches the topic filter.",
        ),
        PinDescriptor("topic", PinDirection.OUTPUT, PinType.STRING),
        PinDescriptor("payload", PinDirection.OUTPUT, PinType.ANY),
        PinDescriptor("text", PinDirection.OUTPUT, PinType.STRING),
        PinDescriptor("data", PinDirection.OUTPUT, PinType.ANY),
    ]

    def should_execute_for_message(self, message: dict[str, Any]) -> bool:
        return _topic_matches(str(self.get_field("topic_filter") or "#"), str(message.get("topic", "")))

    def title_status_tooltip(self) -> str:
        base = super().title_status_tooltip()
        topic_filter = str(self.get_field("topic_filter") or "#")
        return base.replace("</small>", f" - topic: {topic_filter}</small>")


class MqttSendNode(MqttConfiguredNode):
    """Publish a payload through the shared MQTT broker."""

    NODE_NAME = "MQTT Send"
    NODE_TITLE_COLOR = "#5b3f24"
    NODE_GROUP = "Servers/MQTT"
    MIN_WIDTH = 220.0
    VARIABLE_INPUTS = {
        "topic": (str, "sensoryflow/message"),
        "payload": (str, ""),
        "retain": (bool, False),
    }

    PINS = [
        PinDescriptor(
            "exec_in",
            PinDirection.INPUT,
            PinType.TICK,
            tooltip="Publish the payload when this tick fires.",
        ),
        PinDescriptor(
            "exec_out",
            PinDirection.OUTPUT,
            PinType.TICK,
            tooltip="Fires after the publish request is queued.",
        ),
        PinDescriptor("topic", PinDirection.INPUT, PinType.STRING),
        PinDescriptor("payload", PinDirection.INPUT, PinType.ANY),
        PinDescriptor("retain", PinDirection.INPUT, PinType.BOOL),
    ]

    def execute(self, trigger_pin: str) -> None:
        topic = str(self.get_var_input("topic") or "").strip()
        payload = self.get_var_input("payload")
        retain = bool(self.get_var_input("retain"))
        if topic:
            _SHARED_MQTT_SERVER.publish(topic, payload, retain)
        self.fire_tick("exec_out")
