"""Reproductor local nativo basado en QtMultimedia.

No depende del IPC de mpv para el playout local. QMediaPlayer usa el backend
multimedia nativo del sistema (Media Foundation en Windows) y QVideoWidget
pinta directamente dentro de la interfaz Qt. FFmpeg sigue disponible para la
salida RTMP y mpv sólo se usa, si existe, para la previsualización externa.
"""
import os
import subprocess
import time

from PySide6.QtCore import QObject, QTimer, QUrl, Qt, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import QLabel

from . import logger

log = logger.get("native-player")
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class NativePlayer(QObject):
    """Backend de reproducción local para continuidad 24/7.

    La interfaz pública coincide con la que consume PlayoutController y la UI
    para que el cambio de motor no afecte la salida RTMP ni la playlist.
    """

    status = Signal(str)
    ended = Signal(str)               # eof | error | stop
    loaded = Signal()                 # media cargado
    position = Signal(float, float)   # posición y duración en segundos
    levels = Signal(float, float)     # no expuesto por QtMultimedia; queda en -90 dBFS
    idle = Signal(bool)
    process_died = Signal()

    def __init__(self, video_widget, mpv_path="", parent=None):
        super().__init__(parent)
        self.widget = video_widget
        self.mpv_path = mpv_path or ""
        self.proc = None               # compatibilidad con integraciones antiguas
        self.ipc_path = None
        self.hwdec = "auto-safe"      # compatibilidad; Qt elige el backend nativo
        self.audio_device = ""
        self.alang = "es-MX,es-419,spa,es"
        self.slang = ""
        self.volume = 100
        self.muted = False
        self.crossfade_enabled = True
        self.crossfade_duration = 0.5
        self._fade_out_applied = False
        self._current_path = ""
        self._time = 0.0
        self._duration = 0.0
        self._running = False
        self._generation = 0
        self._loaded_generation = -1
        self._end_generation = -1
        self._pending_start = 0.0
        self._pending_audio = None
        self._pending_sub = None
        self._pending_loop = False
        self._target_volume = 1.0
        self._fade_from = 1.0
        self._fade_to = 1.0
        self._fade_started = 0.0
        self._fade_length = 0.0
        self._last_diag_second = -1

        # QVideoWidget es un hijo del VideoSurface. Se oculta cuando no hay
        # señal para que VideoSurface pueda pintar el slate "SIN SEÑAL".
        self._video = QVideoWidget(video_widget)
        self._video.setObjectName("nativeVideoOutput")
        self._video.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
        self._video.hide()
        self._slate = QLabel(video_widget)
        self._slate.setObjectName("nativeSlate")
        self._slate.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._slate.setStyleSheet(
            "background:#000; color:#e5e5e5; font-size:28px; font-weight:600;"
        )
        self._slate.setText("TVPlayout PRO\nPROXIMAMENTE")
        self._slate.hide()
        self._resize_video()
        try:
            self.widget.resized.connect(self._resize_video)
        except AttributeError:
            pass

        self._audio = QAudioOutput(self)
        self._audio.setVolume(self.volume / 100.0)
        self._audio.setMuted(self.muted)
        self._player = QMediaPlayer(self)
        self._player.setAudioOutput(self._audio)
        self._player.setVideoOutput(self._video)
        self._player.positionChanged.connect(self._on_position_changed)
        self._player.durationChanged.connect(self._on_duration_changed)
        self._player.mediaStatusChanged.connect(self._on_media_status)
        self._player.errorOccurred.connect(self._on_error)
        self._player.playbackStateChanged.connect(self._on_playback_state)

        self._fade_timer = QTimer(self)
        self._fade_timer.setInterval(40)
        self._fade_timer.timeout.connect(self._tick_fade)
        log.info("QtMultimedia NativePlayer inicializado • QMediaPlayer=%s QAudioOutput volume=%.2f muted=%s QVideoWidget object=%s",
                 self._player, self._audio.volume(), self._audio.isMuted(), self._video.objectName())

    # ------------------------------------------------------------- estado
    @property
    def available(self):
        # El motor nativo viene con PySide6; no depende de mpv.exe.
        return True

    @property
    def running(self):
        return self._running

    @property
    def current_path(self):
        return self._current_path

    def _resize_video(self):
        if not hasattr(self, "_video"):
            return
        rect = self.widget.rect()
        self._video.setGeometry(rect)
        self._slate.setGeometry(rect)
        log.debug("video geometry surface=%dx%d video=%s visible=%s slate=%s visible=%s",
                  rect.width(), rect.height(), self._video.geometry(), self._video.isVisible(),
                  self._slate.geometry(), self._slate.isVisible())

    def start(self):
        return True

    def shutdown(self):
        log.info("shutdown NativePlayer gen=%d path=%s", self._generation, self._current_path)
        self._fade_timer.stop()
        self._generation += 1
        self._player.stop()
        self._running = False
        self._current_path = ""
        self._video.hide()
        self._slate.hide()

    # ------------------------------------------------------------ multimedia
    def _set_audio_target(self, volume=None):
        if volume is not None:
            self._target_volume = max(0.0, min(1.0, float(volume) / 100.0))
        self._audio.setMuted(self.muted)
        if not self._fade_timer.isActive():
            self._audio.setVolume(0.0 if self.muted else self._target_volume)

    def _start_fade(self, target, duration=None, initial=None):
        duration = self.crossfade_duration if duration is None else float(duration)
        duration = max(0.0, min(3.0, duration))
        self._fade_from = self._audio.volume() if initial is None else float(initial)
        self._fade_to = max(0.0, min(1.0, float(target)))
        self._fade_started = time.monotonic()
        self._fade_length = duration
        if duration <= 0:
            self._fade_timer.stop()
            self._audio.setVolume(self._fade_to)
            return
        self._fade_timer.start()

    def _tick_fade(self):
        if self._fade_length <= 0:
            self._fade_timer.stop()
            self._audio.setVolume(self._fade_to)
            return
        frac = (time.monotonic() - self._fade_started) / self._fade_length
        if frac >= 1.0:
            self._fade_timer.stop()
            self._audio.setVolume(self._fade_to)
            return
        self._audio.setVolume(self._fade_from + (self._fade_to - self._fade_from) * frac)

    def _apply_tracks(self):
        # QMediaPlayer expone pistas ya demultiplexadas. Las APIs pueden no
        # estar disponibles en algún backend; en ese caso usa la pista auto.
        try:
            if isinstance(self._pending_audio, int) and self._pending_audio >= 0:
                self._player.setActiveAudioTrack(self._pending_audio)
        except (AttributeError, RuntimeError):
            pass
        try:
            if self._pending_sub is None:
                self._player.setActiveSubtitleTrack(-1 if not self.slang else 0)
            elif self._pending_sub < 0:
                self._player.setActiveSubtitleTrack(-1)
            else:
                self._player.setActiveSubtitleTrack(int(self._pending_sub))
        except (AttributeError, RuntimeError):
            pass

    def play(self, path, audio_id=None, sub_id=None, start=0.0, loop=False):
        absolute_path = os.path.abspath(path) if path else ""
        exists = bool(absolute_path) and os.path.isfile(absolute_path)
        size = os.path.getsize(absolute_path) if exists else 0
        log.info("source inspect path=%s exists=%s size=%d bytes", absolute_path, exists, size)
        if not exists:
            self.status.emit("Reproductor nativo: archivo no encontrado")
            return False
        self.start()
        self._generation += 1
        self._loaded_generation = -1
        self._end_generation = -1
        self._time = 0.0
        self._duration = 0.0
        self._current_path = absolute_path
        self._running = True
        self._pending_start = max(0.0, float(start or 0.0))
        self._pending_audio = audio_id
        self._pending_sub = sub_id
        self._pending_loop = bool(loop)
        self._last_diag_second = -1
        log.info("play request gen=%d loop=%s audio=%s subtitle=%s path=%s",
                 self._generation, loop, audio_id, sub_id, path)
        self._fade_out_applied = False
        self._fade_timer.stop()
        self._slate.hide()
        self._video.show()
        self._resize_video()
        log.info("video output visible=%s size=%dx%d parent=%s",
                 self._video.isVisible(), self._video.width(), self._video.height(), self._video.parentWidget())
        self._player.stop()
        self._player.setLoops(QMediaPlayer.Loops.Infinite if loop else QMediaPlayer.Loops.Once)
        self._set_audio_target()
        source_url = QUrl.fromLocalFile(absolute_path)
        log.debug("setSource url=%s gen=%d", source_url.toString(), self._generation)
        self._player.setSource(source_url)
        log.debug("play() dispatched gen=%d playbackState=%s mediaStatus=%s",
                  self._generation, self._player.playbackState(), self._player.mediaStatus())
        self._player.play()
        self.status.emit("Nativo ▶ " + os.path.basename(absolute_path))
        return True

    def play_loop(self, path):
        # Las URLs lavfi de mpv no son portables entre backends Qt. Para el
        # slate se usa un overlay nativo estático, sin cargar un archivo ni
        # depender de FFmpeg/lavfi.
        if str(path).startswith("av://"):
            self.start()
            self._generation += 1
            self._loaded_generation = self._generation
            self._end_generation = -1
            self._current_path = str(path)
            self._running = True
            self._fade_timer.stop()
            self._video.hide()
            self._slate.show()
            self._resize_video()
            log.info("slate loop path=%s generation=%d video_visible=%s slate_visible=%s",
                     path, self._generation, self._video.isVisible(), self._slate.isVisible())
            self.status.emit("Nativo ▶ slate de continuidad")
            return True
        return self.play(path, loop=True)

    def stop(self):
        log.info("stop request gen=%d path=%s pos=%.3f", self._generation, self._current_path, self._time)
        self._generation += 1
        self._player.stop()
        self._fade_timer.stop()
        self._running = False
        self._current_path = ""
        self._video.hide()
        self._slate.hide()
        self.idle.emit(True)
        return True

    def _on_media_status(self, status):
        log.debug("mediaStatusChanged gen=%d status=%s path=%s", self._generation, status, self._current_path)
        if status in (QMediaPlayer.MediaStatus.LoadedMedia, QMediaPlayer.MediaStatus.BufferedMedia):
            if self._loaded_generation == self._generation:
                return
            self._loaded_generation = self._generation
            if self._pending_start > 0:
                self._player.setPosition(int(self._pending_start * 1000))
                self._time = self._pending_start
            self._apply_tracks()
            log.info("media loaded gen=%d duration=%.3fs path=%s", self._generation, self._duration, self._current_path)
            self.loaded.emit()
            self.position.emit(self._time, self._duration)
            self.idle.emit(False)
            if self.crossfade_enabled and self.crossfade_duration > 0 and not self.muted:
                self._start_fade(self._target_volume, self.crossfade_duration, initial=0.0)
        elif status == QMediaPlayer.MediaStatus.EndOfMedia:
            self._emit_end("eof")
        elif status == QMediaPlayer.MediaStatus.InvalidMedia:
            self._emit_end("error")

    def _emit_end(self, reason):
        if self._end_generation == self._generation:
            return
        self._end_generation = self._generation
        log.info("media ended gen=%d reason=%s path=%s", self._generation, reason, self._current_path)
        self._running = False
        self._current_path = ""
        self._video.hide()
        self._slate.hide()
        self.idle.emit(True)
        self.ended.emit(reason)

    def _on_error(self, error, error_string):
        if error == QMediaPlayer.Error.NoError:
            return
        log.error("QtMultimedia error=%s text=%s gen=%d path=%s", error, error_string, self._generation, self._current_path)
        self.status.emit("Reproductor nativo: " + (error_string or "error multimedia"))
        self._emit_end("error")

    def _on_playback_state(self, state):
        log.debug("playbackStateChanged gen=%d state=%s path=%s", self._generation, state, self._current_path)
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self._running = True
        elif state == QMediaPlayer.PlaybackState.StoppedState and self._current_path:
            # No marcar EOF aquí: StoppedState también ocurre al hacer
            # loadfile/stop para cargar el siguiente evento.
            self.idle.emit(True)

    def _on_position_changed(self, value):
        self._time = max(0.0, float(value) / 1000.0)
        second = int(self._time)
        if second != self._last_diag_second:
            self._last_diag_second = second
            log.debug("position gen=%d pos=%.3fs dur=%.3fs state=%s",
                      self._generation, self._time, self._duration, self._player.playbackState())
        self.position.emit(self._time, self._duration)

    def _on_duration_changed(self, value):
        self._duration = max(0.0, float(value) / 1000.0)
        log.debug("durationChanged gen=%d duration=%.3fs", self._generation, self._duration)
        self.position.emit(self._time, self._duration)

    # ------------------------------------------------------------- controles
    def set_pause(self, paused):
        log.info("pause=%s gen=%d pos=%.3f", paused, self._generation, self._time)
        if paused:
            self._player.pause()
        else:
            self._player.play()
        return True

    def set_mute(self, muted):
        log.info("mute=%s gen=%d", muted, self._generation)
        self.muted = bool(muted)
        self._audio.setMuted(self.muted)
        return True

    def set_volume(self, value):
        log.debug("volume=%s gen=%d", value, self._generation)
        self.volume = int(max(0, min(100, value)))
        self._target_volume = self.volume / 100.0
        if not self._fade_timer.isActive():
            self._audio.setVolume(self._target_volume)
        return True

    def seek(self, seconds, absolute=False):
        target = float(seconds) if absolute else self._time + float(seconds)
        target = max(0.0, target)
        log.info("seek request gen=%d target=%.3f absolute=%s", self._generation, target, absolute)
        self._player.setPosition(int(target * 1000))
        return True

    def set_property(self, name, value):
        if name == "video-aspect-override":
            if str(value) in ("16:9", "4:3"):
                self._video.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
            else:
                self._video.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
            return True
        return True

    def set_track_langs(self, alang, slang):
        self.alang, self.slang = alang, slang
        return True

    def set_crossfade(self, enabled=None, duration=None):
        if enabled is not None:
            self.crossfade_enabled = bool(enabled)
        if duration is not None:
            self.crossfade_duration = max(0.0, min(3.0, float(duration)))

    def fade_out(self, duration):
        if not self.crossfade_enabled or duration <= 0 or self._fade_out_applied:
            return False
        self._fade_out_applied = True
        self._start_fade(0.0, duration)
        return True

    def open_external_preview(self, path, title="PREVIEW"):
        # La previsualización no afecta el aire. Si el mpv auxiliar existe,
        # se mantiene esta función para no cambiar el flujo de trabajo.
        if not self.mpv_path or not os.path.isfile(self.mpv_path):
            self.status.emit("Preview: mpv.exe no encontrado")
            return False
        cmd = [self.mpv_path, f"--title={title} — {os.path.basename(path)}", "--force-window=yes",
               "--keep-open=yes", "--osc=yes", "--geometry=40%", "--no-terminal", path]
        try:
            subprocess.Popen(cmd, creationflags=CREATE_NO_WINDOW, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except Exception as exc:  # noqa: BLE001
            self.status.emit(f"Preview: {exc}")
            return False
