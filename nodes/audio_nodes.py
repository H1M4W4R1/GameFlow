"""Audio playback nodes."""
from __future__ import annotations

import hashlib
import logging
import os
import shutil
from pathlib import Path
from typing import Any

os.environ.setdefault("QT_FFMPEG_DEBUG", "0")

from PyQt6.QtCore import QRectF, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QAction, QBrush, QColor, QDesktopServices, QPainter
from PyQt6.QtMultimedia import QAudioOutput, QMediaDevices, QMediaPlayer
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
