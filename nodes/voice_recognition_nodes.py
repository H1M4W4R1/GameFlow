"""Voice recognition event nodes."""
from __future__ import annotations

import logging
import queue
import re
import threading
import weakref
from typing import Any

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QAction, QBrush, QColor, QPainter
from PyQt6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QFormLayout, QMenu, QSpinBox

from core.localization import tr
from core.node_base import NodeBase
from core.types import PinDescriptor, PinDirection, PinType

log = logging.getLogger(__name__)


def _normalize_text(value: Any) -> str:
    text = str(value or "").casefold()
    text = re.sub(r"[^\w\s]+", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def _phrase_matches(transcript: str, phrase: str) -> bool:
    wanted = _normalize_text(phrase)
    heard = _normalize_text(transcript)
    if not wanted or not heard:
        return False
    if " " in wanted:
        return wanted in heard
    return wanted in heard.split()


class _SharedVoiceRecognitionService:
    """Single process-wide microphone recognition loop shared by all nodes."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._nodes: weakref.WeakSet[Any] = weakref.WeakSet()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._startup_error: str | None = None
        self._status = "stopped"
        self._microphone_index: int | None = None
        self._sensitivity = 60

    @property
    def startup_error(self) -> str | None:
        return self._startup_error

    @property
    def is_listening(self) -> bool:
        return self._thread is not None and self._thread.is_alive() and self._status == "listening"

    @property
    def status(self) -> str:
        return self._status

    @property
    def microphone_index(self) -> int | None:
        return self._microphone_index

    @property
    def sensitivity(self) -> int:
        return self._sensitivity

    def subscribe(self, node: Any, microphone_index: int | None, sensitivity: int) -> None:
        with self._lock:
            self._nodes.add(node)
            if self._thread is None or not self._thread.is_alive():
                self._start_locked(microphone_index, sensitivity)
            elif microphone_index != self._microphone_index or sensitivity != self._sensitivity:
                self._restart_locked(microphone_index, sensitivity)
            node.node_changed.emit()

    def unsubscribe(self, node: Any) -> None:
        with self._lock:
            self._nodes.discard(node)
            if not self._nodes:
                self._stop_locked()

    def reconfigure_from(self, node: Any, microphone_index: int | None, sensitivity: int) -> None:
        with self._lock:
            if node not in self._nodes:
                return
            if microphone_index == self._microphone_index and sensitivity == self._sensitivity:
                return
            self._restart_locked(microphone_index, sensitivity)
            for subscriber in list(self._nodes):
                subscriber.node_changed.emit()

    def list_audio_devices(self) -> list[tuple[str, int | None, str, bool]]:
        entries: list[tuple[str, int | None, str, bool]] = []
        entries.append(("group", None, "Microphones", False))
        entries.append(("microphone", None, "Default microphone", True))

        try:
            import pyaudio  # type: ignore
        except Exception as exc:
            self._startup_error = f"Voice recognition unavailable: {exc}"
            return entries

        audio = pyaudio.PyAudio()
        try:
            input_seen: set[str] = set()
            output_seen: set[str] = set()
            speaker_entries: list[tuple[str, int | None, str, bool]] = []

            for index in range(audio.get_device_count()):
                try:
                    info = audio.get_device_info_by_index(index)
                except Exception:
                    continue
                name = str(info.get("name") or f"Device {index}").strip()
                if not name:
                    continue
                if self._is_generic_audio_alias(name):
                    continue
                normalized = _normalize_text(name)
                if int(info.get("maxInputChannels") or 0) > 0 and normalized not in input_seen:
                    if self._add_unique_audio_device(entries, "microphone", index, name, True):
                        input_seen.add(normalized)
                if int(info.get("maxOutputChannels") or 0) > 0 and normalized not in output_seen:
                    if self._add_unique_audio_device(speaker_entries, "speaker", index, name, True):
                        output_seen.add(normalized)

            if speaker_entries:
                entries.append(("group", None, "Speakers", False))
                entries.extend(speaker_entries)
        except Exception as exc:
            self._startup_error = f"Microphone list unavailable: {exc}"
        finally:
            audio.terminate()
        return entries

    def list_microphones(self) -> list[tuple[int | None, str]]:
        return [
            (device_index, name)
            for kind, device_index, name, enabled in self.list_audio_devices()
            if kind == "microphone" and enabled
        ]

    def _is_generic_audio_alias(self, name: str) -> bool:
        normalized = _normalize_text(name)
        return normalized in {
            "microsoft sound mapper input",
            "microsoft sound mapper output",
            "primary sound capture driver",
            "primary sound driver",
        }

    def _add_unique_audio_device(
        self,
        bucket: list[tuple[str, int | None, str, bool]],
        kind: str,
        device_index: int | None,
        name: str,
        enabled: bool,
    ) -> bool:
        normalized = _normalize_text(name)
        for idx, (existing_kind, _existing_index, existing_name, _existing_enabled) in enumerate(bucket):
            if existing_kind != kind:
                continue
            existing_normalized = _normalize_text(existing_name)
            if normalized == existing_normalized:
                return False
            if normalized.startswith(existing_normalized) or existing_normalized.startswith(normalized):
                if len(name) > len(existing_name):
                    bucket[idx] = (kind, device_index, name, enabled)
                return False
        bucket.append((kind, device_index, name, enabled))
        return True

    def _start_locked(self, microphone_index: int | None, sensitivity: int) -> None:
        self._microphone_index = microphone_index
        self._sensitivity = self._coerce_sensitivity(sensitivity)
        self._startup_error = None
        self._stop_event.clear()
        self._status = "starting"
        self._thread = threading.Thread(
            target=self._run_loop,
            name="SensoryFlow-VoiceRecognition",
            daemon=True,
        )
        self._thread.start()

    def _restart_locked(self, microphone_index: int | None, sensitivity: int) -> None:
        self._stop_locked()
        if self._nodes:
            self._start_locked(microphone_index, sensitivity)

    def _stop_locked(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        self._thread = None
        self._status = "stopped"

    def _run_loop(self) -> None:
        try:
            import speech_recognition as sr  # type: ignore
        except Exception as exc:
            self._startup_error = f"Voice recognition unavailable: {exc}"
            self._status = "error"
            self._notify_nodes_changed()
            return

        recognizer = sr.Recognizer()
        recognizer.dynamic_energy_threshold = False
        recognizer.energy_threshold = self._energy_threshold_for_sensitivity(self._sensitivity)

        try:
            microphone = sr.Microphone(device_index=self._microphone_index)
        except Exception as exc:
            self._startup_error = f"Microphone unavailable: {exc}"
            self._status = "error"
            self._notify_nodes_changed()
            return

        try:
            with microphone as source:
                self._status = "listening"
                self._notify_nodes_changed()
                try:
                    recognizer.adjust_for_ambient_noise(source, duration=0.3)
                    recognizer.energy_threshold = self._energy_threshold_for_sensitivity(self._sensitivity)
                except Exception as exc:
                    log.debug("Voice ambient-noise calibration failed: %s", exc)

                while not self._stop_event.is_set():
                    try:
                        audio = recognizer.listen(source, timeout=0.5, phrase_time_limit=5.0)
                    except sr.WaitTimeoutError:
                        continue
                    except Exception as exc:
                        self._startup_error = f"Voice listen failed: {exc}"
                        self._status = "error"
                        self._notify_nodes_changed()
                        return

                    transcript = self._recognize_audio(recognizer, audio, sr)
                    if transcript:
                        self._dispatch_transcript(transcript)
        finally:
            if self._status != "error":
                self._status = "stopped"
            self._notify_nodes_changed()

    def _recognize_audio(self, recognizer: Any, audio: Any, sr_module: Any) -> str:
        try:
            return str(recognizer.recognize_google(audio)).strip()
        except sr_module.UnknownValueError:
            return ""
        except sr_module.RequestError as exc:
            self._startup_error = f"Voice recognition request failed: {exc}"
            self._status = "error"
            self._notify_nodes_changed()
            return ""
        except Exception as exc:
            log.debug("Voice recognition failed: %s", exc)
            return ""

    def _dispatch_transcript(self, transcript: str) -> None:
        with self._lock:
            nodes = list(self._nodes)
        for node in nodes:
            if isinstance(node, VoiceRecognitionNode):
                node.enqueue_transcript(transcript)

    def _notify_nodes_changed(self) -> None:
        with self._lock:
            nodes = list(self._nodes)
        for node in nodes:
            try:
                node.node_changed.emit()
            except RuntimeError:
                pass

    def _coerce_sensitivity(self, value: Any) -> int:
        try:
            sensitivity = int(value)
        except (TypeError, ValueError):
            sensitivity = 60
        return max(0, min(100, sensitivity))

    def _energy_threshold_for_sensitivity(self, sensitivity: int) -> int:
        sensitivity = self._coerce_sensitivity(sensitivity)
        return int(4050 - (sensitivity * 40))


_SHARED_VOICE_SERVICE = _SharedVoiceRecognitionService()


class VoiceRecognitionNode(NodeBase):
    """Fire a tick whenever the configured word or phrase is heard."""

    NODE_NAME = "Voice Recognition"
    NODE_GROUP = "Flow/Events"
    NODE_TITLE_COLOR = "#184f56"
    MIN_WIDTH = 230.0
    VARIABLE_INPUTS = {
        "phrase": (str, ""),
    }

    PINS = [
        PinDescriptor(
            "exec_out",
            PinDirection.OUTPUT,
            PinType.TICK,
            tooltip="Fires when the configured word or phrase is recognized.",
        ),
        PinDescriptor("transcript", PinDirection.OUTPUT, PinType.STRING),
        PinDescriptor("matched_phrase", PinDirection.OUTPUT, PinType.STRING),
        PinDescriptor("phrase", PinDirection.INPUT, PinType.STRING, optional=True),
    ]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._transcripts: queue.Queue[str] = queue.Queue()
        self._microphone_index: int | None = None
        self._sensitivity = 60
        self._last_phrase = self._effective_phrase()

    def on_start(self) -> None:
        self._last_phrase = self._effective_phrase()
        self._clear_transcripts()
        _SHARED_VOICE_SERVICE.subscribe(
            self,
            self._microphone_index,
            self._sensitivity,
        )

    def on_stop(self) -> None:
        _SHARED_VOICE_SERVICE.unsubscribe(self)

    def execute(self, trigger_pin: str) -> None:
        pass

    def enqueue_transcript(self, transcript: str) -> None:
        self._transcripts.put(transcript)

    def on_tick_check(self) -> None:
        self._sync_phrase_change()
        while True:
            try:
                transcript = self._transcripts.get_nowait()
            except queue.Empty:
                return

            phrase = self._effective_phrase()
            if not _phrase_matches(transcript, phrase):
                continue
            self.set_output("transcript", transcript)
            self.set_output("matched_phrase", phrase)
            self.fire_tick("exec_out")
            self.node_changed.emit()

    def on_data_received(self, pin_name: str, value: Any) -> None:
        if pin_name == "phrase":
            self._sync_phrase_change()
            self.node_changed.emit()

    def on_var_input_changed(self, pin_name: str, value: Any) -> None:
        if pin_name == "phrase":
            self._sync_phrase_change()

    def _effective_phrase(self) -> str:
        return str(self.get_var_input("phrase") or "").strip()

    def _sync_phrase_change(self) -> None:
        phrase = self._effective_phrase()
        if phrase == self._last_phrase:
            return
        self._last_phrase = phrase
        self._clear_transcripts()

    def _clear_transcripts(self) -> None:
        while True:
            try:
                self._transcripts.get_nowait()
            except queue.Empty:
                return

    def get_voice_recognition_config(self) -> tuple[int | None, int]:
        return self._microphone_index, self._sensitivity

    def set_voice_recognition_config(self, microphone_index: int | None, sensitivity: int) -> None:
        self._microphone_index = microphone_index
        self._sensitivity = _SHARED_VOICE_SERVICE._coerce_sensitivity(sensitivity)
        _SHARED_VOICE_SERVICE.reconfigure_from(
            self,
            self._microphone_index,
            self._sensitivity,
        )
        self.node_changed.emit()

    def _get_context_menu(self, canvas: Any, menu: QMenu, field_hit: Any = None) -> None:
        voice_act = QAction(
            tr("ui.canvas.menu.voice_recognition", default="Voice recognition..."),
            menu,
        )
        voice_act.triggered.connect(lambda: self._open_voice_recognition_dialog(canvas))
        menu.addAction(voice_act)

    def _open_voice_recognition_dialog(self, canvas: Any) -> None:
        current_mic, sensitivity = self.get_voice_recognition_config()
        audio_devices = self.list_voice_audio_devices()

        dlg = QDialog(canvas)
        dlg.setWindowTitle(tr("ui.dialog.voice_recognition.title", default="Voice Recognition"))
        dlg.setModal(True)
        layout = QFormLayout(dlg)

        mic_editor = QComboBox(dlg)
        selected_index = 0
        for idx, (device_kind, mic_index, mic_name, enabled) in enumerate(audio_devices):
            if device_kind == "group":
                label = tr(
                    f"ui.dialog.voice_recognition.group.{str(mic_name).lower()}",
                    default=str(mic_name),
                )
            else:
                label = str(mic_name or tr("ui.dialog.voice_recognition.default_mic", default="Default microphone"))
            mic_editor.addItem(label, mic_index)
            item = mic_editor.model().item(idx)
            if item is not None and not enabled:
                item.setEnabled(False)
            if enabled and mic_index == current_mic:
                selected_index = idx
        mic_editor.setCurrentIndex(selected_index)

        sensitivity_editor = QSpinBox(dlg)
        sensitivity_editor.setRange(0, 100)
        sensitivity_editor.setValue(int(sensitivity))

        layout.addRow(tr("ui.dialog.voice_recognition.microphone", default="Microphone:"), mic_editor)
        layout.addRow(tr("ui.dialog.voice_recognition.sensitivity", default="Sensitivity:"), sensitivity_editor)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            dlg,
        )
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addRow(buttons)

        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.set_voice_recognition_config(mic_editor.currentData(), sensitivity_editor.value())
            canvas.update()

    def list_voice_microphones(self) -> list[tuple[int | None, str]]:
        return _SHARED_VOICE_SERVICE.list_microphones()

    def list_voice_audio_devices(self) -> list[tuple[str, int | None, str, bool]]:
        return _SHARED_VOICE_SERVICE.list_audio_devices()

    def paint_title_status(self, painter: QPainter, rect: QRectF) -> None:
        if _SHARED_VOICE_SERVICE.startup_error:
            color = QColor("#ffb300")
        elif _SHARED_VOICE_SERVICE.is_listening:
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
        mic = "default" if _SHARED_VOICE_SERVICE.microphone_index is None else str(_SHARED_VOICE_SERVICE.microphone_index)
        status = _SHARED_VOICE_SERVICE.status
        if _SHARED_VOICE_SERVICE.startup_error:
            status = f"error: {_SHARED_VOICE_SERVICE.startup_error}"
        return (
            f"<b>Voice recognition</b><br>"
            f"<small style='color:#aaa'>microphone: {mic} - "
            f"sensitivity: {_SHARED_VOICE_SERVICE.sensitivity} - {status}</small>"
        )

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        phrase = str(self.get_var_input("phrase") or "").strip() or "..."
        painter.setPen(QColor("#80cbc4"))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, phrase)

    def get_state(self) -> dict[str, Any]:
        state = super().get_state()
        state["__voice_recognition_config__"] = {
            "microphone_index": self._microphone_index,
            "sensitivity": self._sensitivity,
        }
        return state

    def set_state(self, state: dict[str, Any]) -> None:
        voice_config = state.pop("__voice_recognition_config__", None)
        if isinstance(voice_config, dict):
            mic = voice_config.get("microphone_index")
            try:
                self._microphone_index = None if mic in (None, "") else int(mic)
            except (TypeError, ValueError):
                self._microphone_index = None
            self._sensitivity = _SHARED_VOICE_SERVICE._coerce_sensitivity(
                voice_config.get("sensitivity", 60)
            )
        super().set_state(state)
