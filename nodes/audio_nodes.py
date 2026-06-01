"""Audio playback nodes."""
from __future__ import annotations

import array
import hashlib
import logging
import os
import queue
import shutil
import threading
import time
from pathlib import Path
from typing import Any

os.environ.setdefault("QT_FFMPEG_DEBUG", "0")

from PyQt6.QtCore import QEventLoop, QRectF, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QAction, QBrush, QColor, QDesktopServices, QPainter
from PyQt6.QtMultimedia import QAudioDecoder, QAudioFormat, QAudioOutput, QMediaDevices, QMediaPlayer
from PyQt6.QtWidgets import QFileDialog, QMenu

from core.localization import tr
from core.node_base import NodeBase
from core.types import PinDescriptor, PinDirection, PinType

log = logging.getLogger(__name__)


_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_AUDIO_DIR = _PROJECT_ROOT / "assets" / "audio" / "sfx"
_AUDIO_EXTENSIONS = {
    ".aac", ".aiff", ".flac", ".m4a", ".mp3", ".ogg", ".opus", ".wav", ".wma",
}

_AUDIO_STREAM_DIR = _PROJECT_ROOT / "assets" / "audio" / "streams"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _unique_copy_path(directory: Path, filename: str) -> Path:
    candidate = directory / filename
    if not candidate.exists():
        return candidate
    stem = candidate.stem or "sfx"
    suffix = candidate.suffix
    idx = 2
    while True:
        candidate = directory / f"{stem} {idx}{suffix}"
        if not candidate.exists():
            return candidate
        idx += 1


def _device_id_to_str(device: Any) -> str:
    try:
        return bytes(device.id()).hex()
    except Exception:
        return ""


def _output_devices() -> list[Any]:
    try:
        return list(QMediaDevices.audioOutputs())
    except Exception:
        return []


def _clamp_int(value: Any, default: int, min_value: int, max_value: int) -> int:
    try:
        coerced = int(value)
    except (TypeError, ValueError):
        coerced = default
    return max(min_value, min(max_value, coerced))


def _audio_metrics(samples: list[float]) -> tuple[float, float, float]:
    if not samples:
        return 0.0, 0.0, 0.0
    rms = (sum(sample * sample for sample in samples) / len(samples)) ** 0.5
    peak = max(abs(sample) for sample in samples)
    return samples[-1], rms, peak


def _decode_audio_file(path: Path) -> tuple[list[float], int]:
    decoder = QAudioDecoder()
    fmt = QAudioFormat()
    fmt.setChannelCount(1)
    fmt.setSampleFormat(QAudioFormat.SampleFormat.Float)
    decoder.setAudioFormat(fmt)

    samples: list[float] = []
    sample_rate = 0
    loop = QEventLoop()

    def read_buffer() -> None:
        nonlocal sample_rate
        buffer = decoder.read()
        if not buffer.isValid():
            return
        audio_format = buffer.format()
        sample_rate = int(audio_format.sampleRate() or sample_rate or 44100)
        samples.extend(_buffer_to_mono_float_samples(buffer))

    decoder.bufferReady.connect(read_buffer)
    decoder.finished.connect(loop.quit)
    decoder.isDecodingChanged.connect(lambda decoding: None if decoding else loop.quit())
    decoder.setSource(QUrl.fromLocalFile(str(path)))
    decoder.start()
    QTimer.singleShot(15000, loop.quit)
    loop.exec()

    if decoder.error() != QAudioDecoder.Error.NoError:
        raise RuntimeError(decoder.errorString() or "Audio decode failed.")
    if not samples:
        raise RuntimeError("Audio decode produced no samples.")
    return samples, sample_rate or 44100


def _buffer_to_mono_float_samples(buffer: Any) -> list[float]:
    fmt = buffer.format()
    channels = max(1, int(fmt.channelCount() or 1))
    sample_format = fmt.sampleFormat()
    raw = bytes(buffer.constData())

    if sample_format == QAudioFormat.SampleFormat.Float:
        values = array.array("f")
        values.frombytes(raw)
        scale = 1.0
    elif sample_format == QAudioFormat.SampleFormat.Int16:
        values = array.array("h")
        values.frombytes(raw)
        scale = 32768.0
    elif sample_format == QAudioFormat.SampleFormat.Int32:
        values = array.array("i")
        values.frombytes(raw)
        scale = 2147483648.0
    elif sample_format == QAudioFormat.SampleFormat.UInt8:
        values = array.array("B")
        values.frombytes(raw)
        return [((float(v) - 128.0) / 128.0) for v in values]
    else:
        return []

    floats = [max(-1.0, min(1.0, float(v) / scale)) for v in values]
    if channels == 1:
        return floats

    mono: list[float] = []
    frame_count = len(floats) // channels
    for frame_idx in range(frame_count):
        start = frame_idx * channels
        mono.append(sum(floats[start:start + channels]) / channels)
    return mono


def _is_generic_audio_alias(name: str) -> bool:
    normalized = _normalize_audio_name(name)
    if normalized in {
        "microsoft sound mapper input",
        "microsoft sound mapper output",
        "microsoft sound mapper - input",
        "microsoft sound mapper - output",
        "primary sound capture driver",
        "primary sound driver",
    }:
        return True
    return normalized.startswith("microsoft sound mapper")


def _normalize_audio_name(name: Any) -> str:
    return " ".join(str(name or "").casefold().split())


def _import_pyaudio_module() -> Any:
    try:
        import pyaudiowpatch  # type: ignore
        return pyaudiowpatch
    except Exception:
        import pyaudio  # type: ignore
        return pyaudio


def _add_unique_audio_device(
    bucket: list[dict[str, Any]],
    *,
    kind: str,
    index: int | None,
    name: str,
    enabled: bool,
    capture_index: int | None = None,
) -> bool:
    name = str(name or "").strip()
    if not name or _is_generic_audio_alias(name):
        return False
    normalized = _normalize_audio_name(name)
    for idx, existing in enumerate(bucket):
        if existing.get("kind") != kind:
            continue
        existing_name = _normalize_audio_name(existing.get("name", ""))
        if normalized == existing_name:
            if enabled and not bool(existing.get("enabled")):
                bucket[idx] = {
                    "kind": kind,
                    "index": index,
                    "name": name,
                    "enabled": enabled,
                    "capture_index": capture_index,
                }
            return False
        if normalized.startswith(existing_name) or existing_name.startswith(normalized):
            if len(name) > len(str(existing.get("name", ""))):
                bucket[idx] = {
                    "kind": kind,
                    "index": index,
                    "name": name,
                    "enabled": enabled,
                    "capture_index": capture_index,
                }
            return False
    bucket.append({
        "kind": kind,
        "index": index,
        "name": name,
        "enabled": enabled,
        "capture_index": capture_index,
    })
    return True


def _is_loopback_device_info(info: dict[str, Any]) -> bool:
    normalized = _normalize_audio_name(info.get("name", ""))
    return bool(info.get("isLoopbackDevice")) or any(
        token in normalized for token in ("loopback", "stereo mix", "what u hear", "wave out")
    )


def _find_loopback_capture_index(audio: Any, output_info: dict[str, Any]) -> int | None:
    loopback_for_output = getattr(audio, "get_wasapi_loopback_analogue_by_dict", None)
    if callable(loopback_for_output):
        try:
            info = loopback_for_output(output_info)
            if info is not None:
                return int(info.get("index"))
        except Exception:
            pass

    output_name = _normalize_audio_name(output_info.get("name", ""))
    if not output_name:
        return None
    try:
        count = audio.get_device_count()
    except Exception:
        return None
    for index in range(count):
        try:
            info = audio.get_device_info_by_index(index)
        except Exception:
            continue
        if int(info.get("maxInputChannels") or 0) <= 0 or not _is_loopback_device_info(info):
            continue
        input_name = _normalize_audio_name(info.get("name", ""))
        if output_name in input_name or input_name.replace("loopback", "").strip() in output_name:
            return int(info.get("index", index))
    return None


def _pyaudio_audio_devices() -> list[dict[str, Any]]:
    try:
        pyaudio_module = _import_pyaudio_module()
    except Exception:
        return [
            {"kind": "group", "index": None, "name": "Microphones", "enabled": False, "capture_index": None},
            {"kind": "microphone", "index": None, "name": "Default microphone", "enabled": True, "capture_index": None},
        ]

    audio = pyaudio_module.PyAudio()
    entries: list[dict[str, Any]] = [
        {"kind": "group", "index": None, "name": "Microphones", "enabled": False, "capture_index": None},
        {"kind": "microphone", "index": None, "name": "Default microphone", "enabled": True, "capture_index": None},
    ]
    speaker_entries: list[dict[str, Any]] = []
    try:
        for index in range(audio.get_device_count()):
            try:
                info = audio.get_device_info_by_index(index)
            except Exception:
                continue
            name = str(info.get("name") or f"Device {index}").strip()
            if int(info.get("maxInputChannels") or 0) > 0 and not _is_loopback_device_info(info):
                _add_unique_audio_device(
                    entries,
                    kind="microphone",
                    index=int(info.get("index", index)),
                    name=name,
                    enabled=True,
                    capture_index=int(info.get("index", index)),
                )
            if int(info.get("maxOutputChannels") or 0) <= 0:
                continue
            _add_unique_audio_device(
                speaker_entries,
                kind="speaker",
                index=int(info.get("index", index)),
                name=name,
                enabled=_find_loopback_capture_index(audio, info) is not None,
            )
        if speaker_entries:
            entries.append({"kind": "group", "index": None, "name": "Speakers", "enabled": False, "capture_index": None})
            entries.extend(speaker_entries)
    finally:
        audio.terminate()
    return entries


def _resolve_audio_capture_info(device_kind: str, device_index: int | None) -> tuple[int | None, dict[str, Any] | None]:
    pyaudio_module = _import_pyaudio_module()
    audio = pyaudio_module.PyAudio()
    try:
        if device_kind == "speaker":
            if device_index is None:
                raise RuntimeError("No speaker selected.")
            output_info = audio.get_device_info_by_index(device_index)
            capture_index = _find_loopback_capture_index(audio, output_info)
            if capture_index is None:
                raise RuntimeError(
                    tr(
                        "node.audio_input_stream.loopback_unavailable",
                        default="Speaker loopback is unavailable. Install pyaudiowpatch or enable a system loopback input such as Stereo Mix.",
                    )
                )
            info = audio.get_device_info_by_index(capture_index)
            return capture_index, info
        if device_index is None:
            info = audio.get_default_input_device_info()
            return None, info
        info = audio.get_device_info_by_index(device_index)
        return device_index, info
    finally:
        audio.terminate()


class PlaySfxNode(NodeBase):
    """Play a configured local SFX file whenever execution reaches the node."""

    play_requested = pyqtSignal()

    NODE_NAME = "Play SFX"
    NODE_GROUP = "Audio"
    NODE_TITLE_COLOR = "#5b3f17"
    MIN_WIDTH = 220.0
    MIN_HEIGHT = 88.0

    PINS = [
        PinDescriptor("exec_in", PinDirection.INPUT, PinType.TICK),
        PinDescriptor("exec_out", PinDirection.OUTPUT, PinType.TICK),
    ]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._audio_hash = ""
        self._display_name = ""
        self._device_id = ""
        self._last_error = ""
        self._cached_path: Path | None = None
        self._playbacks: list[tuple[QMediaPlayer, QAudioOutput]] = []
        self.play_requested.connect(self._play_on_ui_thread)

    def execute(self, trigger_pin: str) -> None:
        if trigger_pin == "exec_in":
            self.play_requested.emit()
            self.fire_tick("exec_out")

    def _get_context_menu(self, canvas: Any, menu: QMenu, field_hit: Any = None) -> None:
        select_act = QAction(tr("ui.canvas.menu.select_sfx", default="Select SFX file..."), menu)
        select_act.triggered.connect(lambda: self._select_sfx_file(canvas))
        menu.addAction(select_act)

        device_menu = QMenu(tr("ui.canvas.menu.audio_output_device", default="Output audio device"), menu)
        default_act = QAction(tr("ui.canvas.menu.default_audio_device", default="Default output device"), device_menu)
        default_act.setCheckable(True)
        default_act.setChecked(not self._device_id)
        default_act.triggered.connect(lambda: self._set_output_device(""))
        device_menu.addAction(default_act)

        devices = _output_devices()
        if devices:
            device_menu.addSeparator()
            for device in devices:
                name = str(device.description() or "Audio device")
                device_id = _device_id_to_str(device)
                act = QAction(name, device_menu)
                act.setCheckable(True)
                act.setChecked(bool(device_id) and device_id == self._device_id)
                act.triggered.connect(lambda _checked=False, did=device_id: self._set_output_device(did))
                device_menu.addAction(act)
        menu.addMenu(device_menu)

        open_act = QAction(tr("ui.canvas.menu.open_audio_directory", default="Open Audio Directory"), menu)
        open_act.triggered.connect(self._open_audio_directory)
        menu.addAction(open_act)

    def _select_sfx_file(self, canvas: Any) -> None:
        path_str, _ = QFileDialog.getOpenFileName(
            canvas,
            tr("ui.dialog.sfx_file.title", default="Select SFX File"),
            "",
            tr(
                "ui.dialog.sfx_file.filter",
                default="Audio files (*.wav *.mp3 *.ogg *.flac *.m4a *.aac *.aiff *.opus *.wma);;All files (*.*)",
            ),
        )
        if path_str:
            self._copy_selected_file(Path(path_str))
            canvas.update()

    def _copy_selected_file(self, source: Path) -> None:
        try:
            if not source.is_file():
                raise FileNotFoundError(str(source))
            _AUDIO_DIR.mkdir(parents=True, exist_ok=True)
            audio_hash = _sha256_file(source)
            target = self._find_by_hash(audio_hash)
            if target is None:
                target = _unique_copy_path(_AUDIO_DIR, source.name)
                shutil.copy2(source, target)
            self._audio_hash = audio_hash
            self._display_name = target.name
            self._cached_path = target
            self._last_error = ""
        except Exception as exc:
            self._last_error = str(exc)
            log.error("SFX copy failed: %s", exc)
        self.node_changed.emit()

    def _set_output_device(self, device_id: str) -> None:
        self._device_id = str(device_id or "")
        self.node_changed.emit()

    def _open_audio_directory(self) -> None:
        _AUDIO_DIR.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(_AUDIO_DIR)))

    def _play_on_ui_thread(self) -> None:
        path = self._resolve_audio_file()
        if path is None:
            self.node_changed.emit()
            return
        try:
            audio_output = QAudioOutput(self)
            device = self._selected_audio_device()
            if device is not None:
                audio_output.setDevice(device)
            audio_output.setVolume(1.0)
            player = QMediaPlayer(self)
            player.setAudioOutput(audio_output)
            player.setSource(QUrl.fromLocalFile(str(path)))
            player.mediaStatusChanged.connect(lambda status, p=player: self._cleanup_player(p, status))
            player.errorOccurred.connect(lambda _err, text="", p=player: self._player_error(p, text))
            self._playbacks.append((player, audio_output))
            self._last_error = ""
            player.play()
        except Exception as exc:
            self._last_error = str(exc)
            log.error("SFX playback failed: %s", exc)
        self.node_changed.emit()

    def _resolve_audio_file(self) -> Path | None:
        if not self._audio_hash:
            self._last_error = "No SFX file selected."
            return None
        if self._cached_path and self._cached_path.exists():
            try:
                if _sha256_file(self._cached_path) == self._audio_hash:
                    self._display_name = self._cached_path.name
                    self._last_error = ""
                    return self._cached_path
            except OSError:
                pass
        path = self._find_by_hash(self._audio_hash)
        if path is None:
            self._cached_path = None
            self._last_error = "SFX file is missing from the audio directory."
            return None
        self._cached_path = path
        self._display_name = path.name
        self._last_error = ""
        return path

    def _find_by_hash(self, audio_hash: str) -> Path | None:
        if not audio_hash or not _AUDIO_DIR.exists():
            return None
        for path in _AUDIO_DIR.iterdir():
            if not path.is_file() or path.suffix.lower() not in _AUDIO_EXTENSIONS:
                continue
            try:
                if _sha256_file(path) == audio_hash:
                    return path
            except OSError:
                continue
        return None

    def _peek_audio_file(self) -> Path | None:
        if self._cached_path and self._cached_path.exists():
            return self._cached_path
        if not self._audio_hash:
            return None
        path = self._find_by_hash(self._audio_hash)
        if path is not None:
            self._cached_path = path
            self._display_name = path.name
        return path

    def _selected_audio_device(self) -> Any | None:
        if not self._device_id:
            return None
        for device in _output_devices():
            if _device_id_to_str(device) == self._device_id:
                return device
        return None

    def _cleanup_player(self, player: QMediaPlayer, status: QMediaPlayer.MediaStatus) -> None:
        if status != QMediaPlayer.MediaStatus.EndOfMedia:
            return
        playback = self._find_playback(player)
        if playback is not None:
            self._playbacks.remove(playback)
        player.deleteLater()
        if playback is not None:
            playback[1].deleteLater()

    def _player_error(self, player: QMediaPlayer, text: str) -> None:
        self._last_error = text or "Audio playback failed."
        playback = self._find_playback(player)
        if playback is not None:
            self._playbacks.remove(playback)
        player.deleteLater()
        if playback is not None:
            playback[1].deleteLater()
        self.node_changed.emit()

    def _find_playback(self, player: QMediaPlayer) -> tuple[QMediaPlayer, QAudioOutput] | None:
        for playback in self._playbacks:
            if playback[0] is player:
                return playback
        return None

    def paint_title_status(self, painter: QPainter, rect: QRectF) -> None:
        if self._last_error:
            color = QColor("#ef5350")
        elif self._audio_hash:
            color = QColor("#4caf50") if self._peek_audio_file() else QColor("#ffb300")
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
        if self._last_error:
            return f"<b>Play SFX</b><br><small style='color:#ffb300'>{self._last_error}</small>"
        device_name = "default"
        device = self._selected_audio_device()
        if device is not None:
            device_name = str(device.description() or device_name)
        return f"<b>Play SFX</b><br><small style='color:#aaa'>output: {device_name}</small>"

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        path = self._peek_audio_file()
        if path is not None:
            label = path.name
            color = QColor("#ffd180")
        elif self._audio_hash:
            label = self._display_name or tr("node.play_sfx.missing_file", default="Missing file")
            color = QColor("#ff8a80")
        else:
            label = tr("node.play_sfx.no_file", default="No file selected")
            color = QColor("#8d6e63")
        if len(label) > 28:
            label = label[:25] + "..."
        painter.setPen(color)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)

    def get_state(self) -> dict[str, Any]:
        state = super().get_state()
        state["__sfx_config__"] = {
            "audio_hash": self._audio_hash,
            "display_name": self._display_name,
            "device_id": self._device_id,
        }
        return state

    def set_state(self, state: dict[str, Any]) -> None:
        config = state.pop("__sfx_config__", None)
        if isinstance(config, dict):
            self._audio_hash = str(config.get("audio_hash") or "")
            self._display_name = str(config.get("display_name") or "")
            self._device_id = str(config.get("device_id") or "")
            self._cached_path = None
        super().set_state(state)


class AudioFileStreamNode(NodeBase):
    """Stream decoded audio file samples as realtime mono float chunks."""

    NODE_NAME = "Audio File Stream"
    NODE_GROUP = "Audio"
    NODE_TITLE_COLOR = "#274f63"
    MIN_WIDTH = 240.0
    MIN_HEIGHT = 110.0

    PINS = [
        PinDescriptor("reset", PinDirection.INPUT, PinType.TICK),
        PinDescriptor("gain", PinDirection.INPUT, PinType.FLOAT, optional=True),
        PinDescriptor("chunk_size", PinDirection.INPUT, PinType.INT, optional=True),
        PinDescriptor("samples_tick", PinDirection.OUTPUT, PinType.TICK),
        PinDescriptor("samples", PinDirection.OUTPUT, PinType.ANY),
        PinDescriptor("sample", PinDirection.OUTPUT, PinType.FLOAT),
        PinDescriptor("rms", PinDirection.OUTPUT, PinType.FLOAT),
        PinDescriptor("peak", PinDirection.OUTPUT, PinType.FLOAT),
        PinDescriptor("position_s", PinDirection.OUTPUT, PinType.FLOAT),
        PinDescriptor("sample_rate", PinDirection.OUTPUT, PinType.INT),
    ]
    VARIABLE_INPUTS = {
        "gain": (float, 1.0),
        "chunk_size": (int, 512),
    }
    EDITABLE_FIELDS = {
        "loop": (bool, False),
    }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._audio_hash = ""
        self._display_name = ""
        self._cached_path: Path | None = None
        self._samples: list[float] = []
        self._sample_rate = 44100
        self._stream_pos = 0
        self._started_at = 0.0
        self._last_error = ""
        self._eof = False
        self._chunk_size = _clamp_int(self.get_var_input("chunk_size"), 512, 1, 8192)

    def on_start(self) -> None:
        self._stream_pos = 0
        self._started_at = time.monotonic()
        self._eof = False
        self._chunk_size = self._effective_chunk_size()
        self._load_selected_file()
        self.set_output("sample_rate", int(self._sample_rate))

    def on_stop(self) -> None:
        self._samples = []

    def execute(self, trigger_pin: str) -> None:
        if trigger_pin == "reset":
            self._stream_pos = 0
            self._started_at = time.monotonic()
            self._eof = False
            self.node_changed.emit()

    def on_data_received(self, pin_name: str, value: Any) -> None:
        if pin_name == "chunk_size":
            self._sync_chunk_size(value)

    def on_var_input_changed(self, pin_name: str, value: Any) -> None:
        if pin_name == "chunk_size":
            self._sync_chunk_size()

    def on_tick_check(self) -> None:
        if not self._samples or self._eof:
            return
        chunk_size = self._sync_chunk_size()
        target_pos = int((time.monotonic() - self._started_at) * self._sample_rate)
        if target_pos - self._stream_pos < chunk_size:
            return

        loop_enabled = bool(self.get_field("loop"))
        chunk: list[float] = []
        while len(chunk) < chunk_size:
            if self._stream_pos >= len(self._samples):
                if not loop_enabled:
                    self._eof = True
                    break
                self._stream_pos = 0
                self._started_at = time.monotonic()
            needed = chunk_size - len(chunk)
            end = min(len(self._samples), self._stream_pos + needed)
            chunk.extend(self._samples[self._stream_pos:end])
            self._stream_pos = end

        if not chunk:
            return
        gain = float(self.get_var_input("gain") or 1.0)
        if gain != 1.0:
            chunk = [max(-1.0, min(1.0, sample * gain)) for sample in chunk]
        self._publish_chunk(chunk)

    def _publish_chunk(self, chunk: list[float]) -> None:
        sample, rms, peak = _audio_metrics(chunk)
        self.set_output("samples", chunk)
        self.set_output("sample", sample)
        self.set_output("rms", rms)
        self.set_output("peak", peak)
        self.set_output("position_s", self._stream_pos / max(1, self._sample_rate))
        self.set_output("sample_rate", int(self._sample_rate))
        self.fire_tick("samples_tick")
        self.node_changed.emit()

    def _effective_chunk_size(self, value: Any = None) -> int:
        if value is None:
            value = self.get_var_input("chunk_size")
        return _clamp_int(value, 512, 1, 8192)

    def _sync_chunk_size(self, value: Any = None) -> int:
        chunk_size = self._effective_chunk_size(value)
        if chunk_size != self._chunk_size:
            self._chunk_size = chunk_size
            self._started_at = time.monotonic() - (self._stream_pos / max(1, self._sample_rate))
            self.node_changed.emit()
        return self._chunk_size

    def _get_context_menu(self, canvas: Any, menu: QMenu, field_hit: Any = None) -> None:
        select_act = QAction(tr("ui.canvas.menu.select_audio_stream_file", default="Select audio stream file..."), menu)
        select_act.triggered.connect(lambda: self._select_audio_file(canvas))
        menu.addAction(select_act)

        open_act = QAction(tr("ui.canvas.menu.open_audio_stream_directory", default="Open Audio Stream Directory"), menu)
        open_act.triggered.connect(self._open_audio_stream_directory)
        menu.addAction(open_act)

    def _select_audio_file(self, canvas: Any) -> None:
        path_str, _ = QFileDialog.getOpenFileName(
            canvas,
            tr("ui.dialog.audio_stream_file.title", default="Select Audio Stream File"),
            "",
            tr(
                "ui.dialog.audio_stream_file.filter",
                default="Audio files (*.wav *.mp3 *.ogg *.flac *.m4a *.aac *.aiff *.opus *.wma);;All files (*.*)",
            ),
        )
        if path_str:
            self._copy_selected_file(Path(path_str))
            canvas.update()

    def _copy_selected_file(self, source: Path) -> None:
        try:
            if not source.is_file():
                raise FileNotFoundError(str(source))
            _AUDIO_STREAM_DIR.mkdir(parents=True, exist_ok=True)
            audio_hash = _sha256_file(source)
            target = self._find_by_hash(audio_hash)
            if target is None:
                target = _unique_copy_path(_AUDIO_STREAM_DIR, source.name)
                shutil.copy2(source, target)
            self._audio_hash = audio_hash
            self._display_name = target.name
            self._cached_path = target
            self._last_error = ""
        except Exception as exc:
            self._last_error = str(exc)
            log.error("Audio stream file copy failed: %s", exc)
        self.node_changed.emit()

    def _open_audio_stream_directory(self) -> None:
        _AUDIO_STREAM_DIR.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(_AUDIO_STREAM_DIR)))

    def _load_selected_file(self) -> None:
        path = self._resolve_audio_file()
        if path is None:
            return
        try:
            self._samples, self._sample_rate = _decode_audio_file(path)
            self._last_error = ""
        except Exception as exc:
            self._samples = []
            self._last_error = str(exc)
            log.error("Audio stream decode failed: %s", exc)
        self.node_changed.emit()

    def _resolve_audio_file(self) -> Path | None:
        if not self._audio_hash:
            self._last_error = "No audio file selected."
            return None
        if self._cached_path and self._cached_path.exists():
            try:
                if _sha256_file(self._cached_path) == self._audio_hash:
                    return self._cached_path
            except OSError:
                pass
        path = self._find_by_hash(self._audio_hash)
        if path is None:
            self._cached_path = None
            self._last_error = "Audio file is missing from the stream directory."
            return None
        self._cached_path = path
        self._display_name = path.name
        return path

    def _find_by_hash(self, audio_hash: str) -> Path | None:
        if not audio_hash or not _AUDIO_STREAM_DIR.exists():
            return None
        for path in _AUDIO_STREAM_DIR.iterdir():
            if not path.is_file() or path.suffix.lower() not in _AUDIO_EXTENSIONS:
                continue
            try:
                if _sha256_file(path) == audio_hash:
                    return path
            except OSError:
                continue
        return None

    def _peek_audio_file(self) -> Path | None:
        if self._cached_path and self._cached_path.exists():
            return self._cached_path
        if not self._audio_hash:
            return None
        path = self._find_by_hash(self._audio_hash)
        if path is not None:
            self._cached_path = path
            self._display_name = path.name
        return path

    def paint_title_status(self, painter: QPainter, rect: QRectF) -> None:
        if self._last_error:
            color = QColor("#ef5350")
        elif self._audio_hash:
            color = QColor("#4caf50") if self._peek_audio_file() else QColor("#ffb300")
        else:
            color = QColor("#616161")
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(color))
        painter.drawEllipse(QRectF(rect.right() - 14, rect.top() + 7, 10, 10))

    def title_status_tooltip(self) -> str:
        if self._last_error:
            return f"<b>Audio file stream</b><br><small style='color:#ffb300'>{self._last_error}</small>"
        return f"<b>Audio file stream</b><br><small style='color:#aaa'>{self._sample_rate} Hz</small>"

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        path = self._peek_audio_file()
        if path is None:
            label = tr("node.audio_file_stream.no_file", default="No file selected")
            color = QColor("#78909c")
        elif self._last_error:
            label = tr("node.audio_file_stream.error", default="Decode error")
            color = QColor("#ff8a80")
        else:
            label = path.name
            color = QColor("#80deea")
        if len(label) > 30:
            label = label[:27] + "..."
        painter.setPen(color)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)

    def get_state(self) -> dict[str, Any]:
        state = super().get_state()
        state["__audio_stream_config__"] = {
            "audio_hash": self._audio_hash,
            "display_name": self._display_name,
        }
        return state

    def set_state(self, state: dict[str, Any]) -> None:
        config = state.pop("__audio_stream_config__", None)
        if isinstance(config, dict):
            self._audio_hash = str(config.get("audio_hash") or "")
            self._display_name = str(config.get("display_name") or "")
            self._cached_path = None
        super().set_state(state)


class AudioInputStreamNode(NodeBase):
    """Capture microphone or OS-exposed loopback samples as mono float chunks."""

    NODE_NAME = "Audio Input Stream"
    NODE_GROUP = "Audio"
    NODE_TITLE_COLOR = "#1d5760"
    MIN_WIDTH = 250.0
    MIN_HEIGHT = 110.0

    PINS = [
        PinDescriptor("gain", PinDirection.INPUT, PinType.FLOAT, optional=True),
        PinDescriptor("chunk_size", PinDirection.INPUT, PinType.INT, optional=True),
        PinDescriptor("samples_tick", PinDirection.OUTPUT, PinType.TICK),
        PinDescriptor("samples", PinDirection.OUTPUT, PinType.ANY),
        PinDescriptor("sample", PinDirection.OUTPUT, PinType.FLOAT),
        PinDescriptor("rms", PinDirection.OUTPUT, PinType.FLOAT),
        PinDescriptor("peak", PinDirection.OUTPUT, PinType.FLOAT),
        PinDescriptor("sample_rate", PinDirection.OUTPUT, PinType.INT),
    ]
    VARIABLE_INPUTS = {
        "gain": (float, 1.0),
        "chunk_size": (int, 512),
    }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._device_kind = "microphone"
        self._device_index: int | None = None
        self._device_name = ""
        self._sample_rate = 44100
        self._chunks: queue.Queue[list[float]] = queue.Queue(maxsize=12)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_error = ""
        self._status = "stopped"
        self._chunk_size = _clamp_int(self.get_var_input("chunk_size"), 512, 1, 8192)

    def on_start(self) -> None:
        self._chunk_size = self._effective_chunk_size()
        self._start_capture()

    def on_stop(self) -> None:
        self._stop_capture()

    def execute(self, trigger_pin: str) -> None:
        pass

    def on_data_received(self, pin_name: str, value: Any) -> None:
        if pin_name == "chunk_size":
            self._sync_chunk_size(value)

    def on_var_input_changed(self, pin_name: str, value: Any) -> None:
        if pin_name == "chunk_size":
            self._sync_chunk_size()

    def on_tick_check(self) -> None:
        processed = 0
        while processed < 4:
            try:
                chunk = self._chunks.get_nowait()
            except queue.Empty:
                return
            gain = float(self.get_var_input("gain") or 1.0)
            if gain != 1.0:
                chunk = [max(-1.0, min(1.0, sample * gain)) for sample in chunk]
            sample, rms, peak = _audio_metrics(chunk)
            self.set_output("samples", chunk)
            self.set_output("sample", sample)
            self.set_output("rms", rms)
            self.set_output("peak", peak)
            self.set_output("sample_rate", int(self._sample_rate))
            self.fire_tick("samples_tick")
            processed += 1
        self.node_changed.emit()

    def _start_capture(self) -> None:
        self._stop_capture()
        self._stop_event.clear()
        self._last_error = ""
        self._status = "starting"
        self._thread = threading.Thread(
            target=self._capture_loop,
            name="GameFlow-AudioInputStream",
            daemon=True,
        )
        self._thread.start()
        self.node_changed.emit()

    def _stop_capture(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=1.5)
        self._thread = None
        self._status = "stopped"

    def _capture_loop(self) -> None:
        try:
            pyaudio_module = _import_pyaudio_module()
        except Exception as exc:
            self._last_error = f"PyAudio unavailable: {exc}"
            self._status = "error"
            self.node_changed.emit()
            return

        audio = pyaudio_module.PyAudio()
        stream = None
        try:
            chunk_size = self._chunk_size
            capture_index, device_info = _resolve_audio_capture_info(self._device_kind, self._device_index)
            if device_info is None:
                raise RuntimeError("Audio device unavailable.")
            self._sample_rate = int(float(device_info.get("defaultSampleRate") or self._sample_rate))
            channels = max(1, min(2, int(device_info.get("maxInputChannels") or 1)))

            stream = audio.open(
                format=pyaudio_module.paFloat32,
                channels=channels,
                rate=self._sample_rate,
                input=True,
                input_device_index=capture_index,
                frames_per_buffer=chunk_size,
            )
            self._status = "capturing"
            self.node_changed.emit()
            while not self._stop_event.is_set():
                raw = stream.read(chunk_size, exception_on_overflow=False)
                values = array.array("f")
                values.frombytes(raw)
                floats = [float(v) for v in values]
                if channels > 1:
                    frame_count = len(floats) // channels
                    floats = [
                        sum(floats[i * channels:(i + 1) * channels]) / channels
                        for i in range(frame_count)
                    ]
                self._queue_chunk(floats)
        except Exception as exc:
            self._last_error = str(exc)
            self._status = "error"
            log.error("Audio input capture failed: %s", exc)
        finally:
            if stream is not None:
                try:
                    stream.stop_stream()
                    stream.close()
                except Exception:
                    pass
            audio.terminate()
            if self._status != "error":
                self._status = "stopped"
            self.node_changed.emit()

    def _effective_chunk_size(self, value: Any = None) -> int:
        if value is None:
            value = self.get_var_input("chunk_size")
        return _clamp_int(value, 512, 1, 8192)

    def _sync_chunk_size(self, value: Any = None) -> int:
        chunk_size = self._effective_chunk_size(value)
        if chunk_size != self._chunk_size:
            self._chunk_size = chunk_size
            self._clear_chunks()
            if self._thread is not None and self._thread.is_alive():
                self._start_capture()
            else:
                self.node_changed.emit()
        return self._chunk_size

    def _clear_chunks(self) -> None:
        while True:
            try:
                self._chunks.get_nowait()
            except queue.Empty:
                return

    def _queue_chunk(self, chunk: list[float]) -> None:
        try:
            self._chunks.put_nowait(chunk)
        except queue.Full:
            try:
                self._chunks.get_nowait()
            except queue.Empty:
                pass
            try:
                self._chunks.put_nowait(chunk)
            except queue.Full:
                pass

    def _get_context_menu(self, canvas: Any, menu: QMenu, field_hit: Any = None) -> None:
        device_menu = QMenu(tr("ui.canvas.menu.audio_input_device", default="Input audio device"), menu)
        default_act = QAction(tr("ui.canvas.menu.default_audio_input_device", default="Default input device"), device_menu)
        default_act.setCheckable(True)
        default_act.setChecked(self._device_kind == "microphone" and self._device_index is None)
        default_act.triggered.connect(lambda: self._set_input_device("microphone", None, ""))
        device_menu.addAction(default_act)

        devices = _pyaudio_audio_devices()
        if devices:
            device_menu.addSeparator()
            for device in devices:
                kind = str(device.get("kind") or "")
                if kind == "group":
                    label = tr(
                        f"ui.dialog.voice_recognition.group.{str(device.get('name', '')).lower()}",
                        default=str(device.get("name") or ""),
                    )
                    group_act = QAction(label, device_menu)
                    group_act.setEnabled(False)
                    device_menu.addAction(group_act)
                    continue
                label = str(device.get("name") or "Audio device")
                if kind == "speaker":
                    label = f"{label} ({tr('ui.canvas.menu.loopback_hint', default='loopback')})"
                act = QAction(label, device_menu)
                act.setCheckable(True)
                device_index = device.get("index")
                act.setChecked(self._device_kind == kind and self._device_index == device_index)
                act.setEnabled(bool(device.get("enabled", True)))
                act.triggered.connect(
                    lambda _checked=False, k=kind, idx=device_index, name=str(device.get("name") or ""): self._set_input_device(k, idx, name)
                )
                device_menu.addAction(act)
        menu.addMenu(device_menu)

    def _set_input_device(self, device_kind: str, device_index: int | None, name: str) -> None:
        self._device_kind = "speaker" if device_kind == "speaker" else "microphone"
        self._device_index = device_index if device_index is None else int(device_index)
        self._device_name = str(name or "")
        if self._thread is not None and self._thread.is_alive():
            self._start_capture()
        self.node_changed.emit()

    def paint_title_status(self, painter: QPainter, rect: QRectF) -> None:
        if self._last_error:
            color = QColor("#ef5350")
        elif self._status == "capturing":
            color = QColor("#4caf50")
        elif self._status == "starting":
            color = QColor("#ffb300")
        else:
            color = QColor("#616161")
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(color))
        painter.drawEllipse(QRectF(rect.right() - 14, rect.top() + 7, 10, 10))

    def title_status_tooltip(self) -> str:
        device = self._device_name or "default"
        if self._last_error:
            return f"<b>Audio input stream</b><br><small style='color:#ffb300'>{self._last_error}</small>"
        return f"<b>Audio input stream</b><br><small style='color:#aaa'>{self._device_kind}: {device} - {self._status}</small>"

    def paint_custom(self, painter: QPainter, rect: QRectF) -> None:
        label = self._device_name or tr("node.audio_input_stream.default_device", default="Default input device")
        if len(label) > 30:
            label = label[:27] + "..."
        painter.setPen(QColor("#80cbc4"))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)

    def get_state(self) -> dict[str, Any]:
        state = super().get_state()
        state["__audio_input_stream_config__"] = {
            "device_kind": self._device_kind,
            "device_index": self._device_index,
            "device_name": self._device_name,
        }
        return state

    def set_state(self, state: dict[str, Any]) -> None:
        config = state.pop("__audio_input_stream_config__", None)
        if isinstance(config, dict):
            self._device_kind = "speaker" if config.get("device_kind") == "speaker" else "microphone"
            idx = config.get("device_index")
            try:
                self._device_index = None if idx in (None, "") else int(idx)
            except (TypeError, ValueError):
                self._device_index = None
            self._device_name = str(config.get("device_name") or "")
        super().set_state(state)
