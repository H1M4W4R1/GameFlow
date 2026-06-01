"""Voice recognition event nodes."""
from __future__ import annotations

import logging
import json
import queue
import re
import threading
import time
import weakref
from pathlib import Path
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
        self._restart_requested = False
        self._startup_error: str | None = None
        self._status = "stopped"
        self._device_kind = "microphone"
        self._device_index: int | None = None
        self._device_name = ""
        self._sensitivity = 60
        self._backend = "vosk"
        self._vosk_model: Any | None = None

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
        return self._device_index

    @property
    def device_kind(self) -> str:
        return self._device_kind

    @property
    def device_name(self) -> str:
        return self._device_name

    @property
    def sensitivity(self) -> int:
        return self._sensitivity

    @property
    def backend(self) -> str:
        return self._backend

    def subscribe(
        self,
        node: Any,
        device_kind: str,
        device_index: int | None,
        device_name: str,
        sensitivity: int,
        backend: str,
    ) -> None:
        with self._lock:
            self._nodes.add(node)
            if self._thread is None or not self._thread.is_alive():
                self._start_locked(device_kind, device_index, device_name, sensitivity, backend)
            elif self._stop_event.is_set():
                self._restart_locked(device_kind, device_index, device_name, sensitivity, backend)
            elif (
                device_kind != self._device_kind
                or device_index != self._device_index
                or device_name != self._device_name
                or sensitivity != self._sensitivity
                or backend != self._backend
            ):
                self._restart_locked(device_kind, device_index, device_name, sensitivity, backend)
            node.node_changed.emit()

    def unsubscribe(self, node: Any) -> None:
        with self._lock:
            self._nodes.discard(node)
            if not self._nodes:
                self._stop_locked()

    def reconfigure_from(
        self,
        node: Any,
        device_kind: str,
        device_index: int | None,
        device_name: str,
        sensitivity: int,
        backend: str,
    ) -> None:
        with self._lock:
            if node not in self._nodes:
                return
            if (
                device_kind == self._device_kind
                and device_index == self._device_index
                and device_name == self._device_name
                and sensitivity == self._sensitivity
                and backend == self._backend
            ):
                return
            self._restart_locked(device_kind, device_index, device_name, sensitivity, backend)
            for subscriber in list(self._nodes):
                subscriber.node_changed.emit()

    def list_audio_devices(self) -> list[tuple[str, int | None, str, bool]]:
        try:
            from nodes.audio_nodes import _pyaudio_audio_devices
        except Exception as exc:
            self._startup_error = f"Voice recognition unavailable: {exc}"
            return [
                ("group", None, "Microphones", False),
                ("microphone", None, "Default microphone", True),
            ]

        try:
            return [
                (
                    str(device.get("kind") or ""),
                    device.get("index"),
                    str(device.get("name") or ""),
                    bool(device.get("enabled", True)),
                )
                for device in _pyaudio_audio_devices()
            ]
        except Exception as exc:
            self._startup_error = f"Microphone list unavailable: {exc}"
            return [
                ("group", None, "Microphones", False),
                ("microphone", None, "Default microphone", True),
            ]

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

    def _start_locked(
        self,
        device_kind: str,
        device_index: int | None,
        device_name: str,
        sensitivity: int,
        backend: str,
    ) -> None:
        self._device_kind = "speaker" if device_kind == "speaker" else "microphone"
        self._device_index = device_index
        self._device_name = str(device_name or "")
        self._sensitivity = self._coerce_sensitivity(sensitivity)
        self._backend = self._coerce_backend(backend)
        self._restart_requested = False
        self._startup_error = None
        self._stop_event = threading.Event()
        self._status = "starting"
        self._thread = threading.Thread(
            target=self._run_loop,
            args=(
                self._stop_event,
                self._device_kind,
                self._device_index,
                self._device_name,
                self._sensitivity,
                self._backend,
            ),
            name="GameFlow-VoiceRecognition",
            daemon=True,
        )
        self._thread.start()

    def _restart_locked(
        self,
        device_kind: str,
        device_index: int | None,
        device_name: str,
        sensitivity: int,
        backend: str,
    ) -> None:
        self._device_kind = "speaker" if device_kind == "speaker" else "microphone"
        self._device_index = device_index
        self._device_name = str(device_name or "")
        self._sensitivity = self._coerce_sensitivity(sensitivity)
        self._backend = self._coerce_backend(backend)
        self._startup_error = None
        if self._thread is None or not self._thread.is_alive():
            self._start_locked(device_kind, device_index, device_name, sensitivity, backend)
            return
        self._restart_requested = True
        self._status = "restarting"
        self._stop_event.set()

    def _stop_locked(self) -> None:
        self._restart_requested = False
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._status = "stopping"
            return
        self._thread = None
        self._status = "stopped"

    def _run_loop(
        self,
        stop_event: threading.Event,
        device_kind: str,
        device_index: int | None,
        device_name: str,
        sensitivity: int,
        backend: str,
    ) -> None:
        try:
            import speech_recognition as sr  # type: ignore
        except Exception as exc:
            self._startup_error = f"Voice recognition unavailable: {exc}"
            self._status = "error"
            self._notify_nodes_changed()
            self._finish_thread(threading.current_thread(), stop_event)
            return

        recognizer = sr.Recognizer()
        recognizer.dynamic_energy_threshold = False
        recognizer.pause_threshold = 0.8
        recognizer.phrase_threshold = 0.3
        recognizer.non_speaking_duration = 0.5
        recognizer.energy_threshold = self._energy_threshold_for_sensitivity(sensitivity)

        try:
            microphone = self._build_microphone(sr, device_kind, device_index)
        except Exception as exc:
            self._startup_error = f"Audio input unavailable: {exc}"
            self._status = "error"
            self._notify_nodes_changed()
            self._finish_thread(threading.current_thread(), stop_event)
            return

        try:
            with microphone as source:
                self._status = "listening"
                self._notify_nodes_changed()
                try:
                    recognizer.adjust_for_ambient_noise(source, duration=0.3)
                    recognizer.energy_threshold = self._energy_threshold_for_sensitivity(sensitivity)
                except Exception as exc:
                    log.debug("Voice ambient-noise calibration failed: %s", exc)

                while not stop_event.is_set():
                    try:
                        audio = recognizer.listen(source, timeout=0.5, phrase_time_limit=5.0)
                    except sr.WaitTimeoutError:
                        continue
                    except Exception as exc:
                        if stop_event.is_set():
                            break
                        self._startup_error = f"Voice listen failed: {exc}"
                        self._status = "error"
                        self._notify_nodes_changed()
                        return

                    if stop_event.is_set():
                        break
                    transcript = self._recognize_audio(recognizer, audio, sr, stop_event, backend)
                    if self._status == "error":
                        return
                    if transcript:
                        self._dispatch_transcript(transcript)
        finally:
            if self._status != "error":
                self._status = "stopped"
            self._notify_nodes_changed()
            self._finish_thread(threading.current_thread(), stop_event)

    def _finish_thread(self, thread: threading.Thread, stop_event: threading.Event) -> None:
        with self._lock:
            if self._thread is not thread:
                return
            if self._restart_requested and self._nodes:
                self._start_locked(
                    self._device_kind,
                    self._device_index,
                    self._device_name,
                    self._sensitivity,
                    self._backend,
                )
                return
            self._thread = None
            self._restart_requested = False
            self._status = "stopped"
        self._notify_nodes_changed()

    def _build_microphone(self, sr_module: Any, device_kind: str, device_index: int | None) -> Any:
        from nodes.audio_nodes import _import_pyaudio_module, _resolve_audio_capture_info

        pyaudio_module = _import_pyaudio_module()
        capture_index, device_info = _resolve_audio_capture_info(device_kind, device_index)
        sample_rate = None
        if device_info is not None:
            sample_rate = int(float(device_info.get("defaultSampleRate") or 0)) or None

        class _PatchedMicrophone(sr_module.Microphone):
            @staticmethod
            def get_pyaudio() -> Any:
                return pyaudio_module

        return _PatchedMicrophone(device_index=capture_index, sample_rate=sample_rate)

    def _recognize_audio(
        self,
        recognizer: Any,
        audio: Any,
        sr_module: Any,
        stop_event: threading.Event,
        backend: str,
    ) -> str:
        try:
            if self._coerce_backend(backend) == "google":
                transcript = str(recognizer.recognize_google(audio)).strip()
            else:
                transcript = self._recognize_vosk(audio, sr_module)
            return "" if stop_event.is_set() else transcript
        except sr_module.UnknownValueError:
            return ""
        except sr_module.RequestError as exc:
            if stop_event.is_set():
                return ""
            self._startup_error = f"Voice recognition request failed: {exc}"
            self._status = "error"
            self._notify_nodes_changed()
            return ""
        except sr_module.SetupError as exc:
            self._startup_error = f"Voice recognition setup failed: {exc}"
            self._status = "error"
            self._notify_nodes_changed()
            return ""
        except Exception as exc:
            log.debug("Voice recognition failed: %s", exc)
            return ""

    def _recognize_vosk(self, audio: Any, sr_module: Any) -> str:
        from vosk import KaldiRecognizer, SetLogLevel

        SetLogLevel(-1)
        model = self._get_vosk_model(sr_module)
        sample_rate = 16000
        rec = KaldiRecognizer(model, sample_rate)
        rec.AcceptWaveform(audio.get_raw_data(convert_rate=sample_rate, convert_width=2))
        result = json.loads(rec.FinalResult())
        return str(result.get("text") or "").strip()

    def _get_vosk_model(self, sr_module: Any) -> Any:
        if self._vosk_model is not None:
            return self._vosk_model

        from vosk import Model

        model_path = Path(sr_module.__file__).resolve().parent / "models" / "vosk"
        if not model_path.exists():
            raise sr_module.SetupError(
                f"Vosk model not found at {model_path}. "
                "Run: python -m speech_recognition.cli download vosk"
            )
        self._vosk_model = Model(str(model_path))
        return self._vosk_model

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

    def _coerce_backend(self, value: Any) -> str:
        backend = str(value or "").strip().casefold()
        return "google" if backend == "google" else "vosk"

    def _energy_threshold_for_sensitivity(self, sensitivity: int) -> int:
        sensitivity = self._coerce_sensitivity(sensitivity)
        return int(4050 - (sensitivity * 40))


_SHARED_VOICE_SERVICE = _SharedVoiceRecognitionService()


class VoiceRecognitionNode(NodeBase):
    """Fire a tick whenever the configured word or phrase is heard."""

    NODE_NAME = "On Voice Detected"
    NODE_GROUP = "Audio"
    _TR_KEY = "voice_recognition"
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
        self._transcripts: queue.Queue[tuple[float, str]] = queue.Queue(maxsize=8)
        self._device_kind = "microphone"
        self._device_index: int | None = None
        self._device_name = ""
        self._sensitivity = 60
        self._backend = "vosk"
        self._last_phrase = self._effective_phrase()
        self._phrase_changed_at = time.monotonic()

    def on_start(self) -> None:
        self._last_phrase = self._effective_phrase()
        self._phrase_changed_at = time.monotonic()
        self._clear_transcripts()
        _SHARED_VOICE_SERVICE.subscribe(
            self,
            self._device_kind,
            self._device_index,
            self._device_name,
            self._sensitivity,
            self._backend,
        )

    def on_stop(self) -> None:
        _SHARED_VOICE_SERVICE.unsubscribe(self)

    def execute(self, trigger_pin: str) -> None:
        pass

    def enqueue_transcript(self, transcript: str) -> None:
        item = (time.monotonic(), transcript)
        try:
            self._transcripts.put_nowait(item)
        except queue.Full:
            try:
                self._transcripts.get_nowait()
            except queue.Empty:
                pass
            try:
                self._transcripts.put_nowait(item)
            except queue.Full:
                pass

    def on_tick_check(self) -> None:
        self._sync_phrase_change()
        phrase = self._effective_phrase()
        if not phrase:
            return
        while True:
            try:
                transcript_at, transcript = self._transcripts.get_nowait()
            except queue.Empty:
                return

            if transcript_at < self._phrase_changed_at:
                continue
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
        self._phrase_changed_at = time.monotonic()

    def _clear_transcripts(self) -> None:
        while True:
            try:
                self._transcripts.get_nowait()
            except queue.Empty:
                return

    def get_voice_recognition_config(self) -> tuple[str, int | None, str, int, str]:
        return self._device_kind, self._device_index, self._device_name, self._sensitivity, self._backend

    def set_voice_recognition_config(
        self,
        device_kind: str,
        device_index: int | None,
        device_name: str,
        sensitivity: int,
        backend: str,
    ) -> None:
        self._device_kind = "speaker" if device_kind == "speaker" else "microphone"
        self._device_index = device_index
        self._device_name = str(device_name or "")
        self._sensitivity = _SHARED_VOICE_SERVICE._coerce_sensitivity(sensitivity)
        self._backend = _SHARED_VOICE_SERVICE._coerce_backend(backend)
        _SHARED_VOICE_SERVICE.reconfigure_from(
            self,
            self._device_kind,
            self._device_index,
            self._device_name,
            self._sensitivity,
            self._backend,
        )
        self.node_changed.emit()

    def set_voice_recognition_backend(self, backend: str) -> None:
        self.set_voice_recognition_config(
            self._device_kind,
            self._device_index,
            self._device_name,
            self._sensitivity,
            backend,
        )

    def _get_context_menu(self, canvas: Any, menu: QMenu, field_hit: Any = None) -> None:
        voice_act = QAction(
            tr("ui.canvas.menu.voice_recognition", default="Voice recognition..."),
            menu,
        )
        voice_act.triggered.connect(lambda: self._open_voice_recognition_dialog(canvas))
        menu.addAction(voice_act)

        backend_menu = QMenu(
            tr("ui.canvas.menu.voice_recognition_backend", default="Recognition backend"),
            menu,
        )
        for backend, label_key, default_label in (
            ("vosk", "ui.dialog.voice_recognition.backend.vosk", "Vosk (local)"),
            ("google", "ui.dialog.voice_recognition.backend.google", "Google (online)"),
        ):
            act = QAction(tr(label_key, default=default_label), backend_menu)
            act.setCheckable(True)
            act.setChecked(self._backend == backend)
            act.triggered.connect(lambda _checked=False, value=backend: self.set_voice_recognition_backend(value))
            backend_menu.addAction(act)
        menu.addMenu(backend_menu)

    def _open_voice_recognition_dialog(self, canvas: Any) -> None:
        current_kind, current_index, _current_name, sensitivity, backend = self.get_voice_recognition_config()
        audio_devices = self.list_voice_audio_devices()

        dlg = QDialog(canvas)
        dlg.setWindowTitle(tr("ui.dialog.voice_recognition.title", default="Voice Recognition"))
        dlg.setModal(True)
        layout = QFormLayout(dlg)

        mic_editor = QComboBox(dlg)
        selected_index = 0
        for idx, (device_kind, device_index, device_name, enabled) in enumerate(audio_devices):
            if device_kind == "group":
                label = tr(
                    f"ui.dialog.voice_recognition.group.{str(device_name).lower()}",
                    default=str(device_name),
                )
            else:
                label = str(device_name or tr("ui.dialog.voice_recognition.default_mic", default="Default microphone"))
                if device_kind == "speaker":
                    label = f"{label} ({tr('ui.canvas.menu.loopback_hint', default='loopback')})"
            mic_editor.addItem(label, (device_kind, device_index, device_name))
            item = mic_editor.model().item(idx)
            if item is not None and not enabled:
                item.setEnabled(False)
            if enabled and device_kind == current_kind and device_index == current_index:
                selected_index = idx
        mic_editor.setCurrentIndex(selected_index)

        sensitivity_editor = QSpinBox(dlg)
        sensitivity_editor.setRange(0, 100)
        sensitivity_editor.setValue(int(sensitivity))

        backend_editor = QComboBox(dlg)
        backend_options = [
            ("vosk", tr("ui.dialog.voice_recognition.backend.vosk", default="Vosk (local)")),
            ("google", tr("ui.dialog.voice_recognition.backend.google", default="Google (online)")),
        ]
        selected_backend_index = 0
        for idx, (backend_value, backend_label) in enumerate(backend_options):
            backend_editor.addItem(backend_label, backend_value)
            if backend_value == backend:
                selected_backend_index = idx
        backend_editor.setCurrentIndex(selected_backend_index)

        layout.addRow(tr("ui.dialog.voice_recognition.microphone", default="Microphone:"), mic_editor)
        layout.addRow(tr("ui.dialog.voice_recognition.sensitivity", default="Sensitivity:"), sensitivity_editor)
        layout.addRow(tr("ui.dialog.voice_recognition.backend", default="Backend:"), backend_editor)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            dlg,
        )
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addRow(buttons)

        if dlg.exec() == QDialog.DialogCode.Accepted:
            device_kind, device_index, device_name = mic_editor.currentData()
            self.set_voice_recognition_config(
                device_kind,
                device_index,
                device_name,
                sensitivity_editor.value(),
                backend_editor.currentData(),
            )
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
        device_name = _SHARED_VOICE_SERVICE.device_name or "default"
        status = _SHARED_VOICE_SERVICE.status
        if _SHARED_VOICE_SERVICE.startup_error:
            status = f"error: {_SHARED_VOICE_SERVICE.startup_error}"
        return (
            f"<b>Voice recognition</b><br>"
            f"<small style='color:#aaa'>{_SHARED_VOICE_SERVICE.device_kind}: {device_name} - "
            f"backend: {_SHARED_VOICE_SERVICE.backend} - "
            f"sensitivity: {_SHARED_VOICE_SERVICE.sensitivity} - {status}</small>"
        )

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        phrase = str(self.get_var_input("phrase") or "").strip() or "..."
        painter.setPen(QColor("#80cbc4"))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, phrase)

    def get_state(self) -> dict[str, Any]:
        state = super().get_state()
        state["__voice_recognition_config__"] = {
            "device_kind": self._device_kind,
            "device_index": self._device_index,
            "device_name": self._device_name,
            "microphone_index": self._device_index,
            "sensitivity": self._sensitivity,
            "backend": self._backend,
        }
        return state

    def set_state(self, state: dict[str, Any]) -> None:
        voice_config = state.pop("__voice_recognition_config__", None)
        if isinstance(voice_config, dict):
            self._device_kind = "speaker" if voice_config.get("device_kind") == "speaker" else "microphone"
            mic = voice_config.get("device_index", voice_config.get("microphone_index"))
            try:
                self._device_index = None if mic in (None, "") else int(mic)
            except (TypeError, ValueError):
                self._device_index = None
            self._device_name = str(voice_config.get("device_name") or "")
            self._sensitivity = _SHARED_VOICE_SERVICE._coerce_sensitivity(
                voice_config.get("sensitivity", 60)
            )
            self._backend = _SHARED_VOICE_SERVICE._coerce_backend(
                voice_config.get("backend", "vosk")
            )
        super().set_state(state)
