"""Controlador de continuidad: modelo de playlist + lógica de emisión (automático/manual, hora exacta,
autofill, tandas, loop, cue) sobre el reproductor mpv local. La salida RTMP se engancha mediante callbacks."""
import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path

from PySide6.QtCore import QObject, Signal, QTimer

from . import logger
from .prober import pick_audio, pick_subtitle

log = logger.get("playout")

ST_PENDING = ""
ST_READY = "READY"
ST_ONAIR = "ON AIR"
ST_AIRED = "EMITIDO"
ST_CUT = "CORTADO"
ST_ERROR = "ERROR"
ST_SKIPPED = "OMITIDO"
DONE_STATES = {ST_AIRED, ST_CUT, ST_ERROR, ST_SKIPPED}


def make_item(row_or_dict, **extra):
    """Normaliza una fila de la BD o un dict a un evento de playlist."""
    src = dict(row_or_dict) if not isinstance(row_or_dict, dict) else dict(row_or_dict)
    tracks = src.get("tracks") or []
    if isinstance(tracks, str):
        try:
            tracks = json.loads(tracks or "[]")
        except ValueError:
            tracks = []
    item = {
        "media_id": src.get("media_id") if "media_id" in src else src.get("id"),
        "path": src.get("path", ""),
        "title": src.get("title") or Path(src.get("path", "")).stem,
        "category": src.get("category") or "Otros",
        "duration": float(src.get("duration") or 0),
        "width": int(src.get("width") or 0),
        "height": int(src.get("height") or 0),
        "fps": float(src.get("fps") or 0),
        "video_codec": src.get("video_codec") or "",
        "audio_codec": src.get("audio_codec") or "",
        "tracks": tracks,
        "thumb": src.get("thumb") or "",
        "audio_lang": src.get("audio_lang") or "",
        "subtitle_lang": src.get("subtitle_lang") or "",
        "fixed_time": src.get("fixed_time") or "",
        "status": ST_PENDING,
        "aired_at": None,
        "late": False,
        "note": src.get("note") or "",
    }
    item.update(extra)
    return item


class PlayoutController(QObject):
    items_changed = Signal()            # estructura de la lista cambió → reconstruir grid
    item_changed = Signal(int)          # una fila cambió (estado/metadatos)
    onair_changed = Signal(int)         # índice al aire (-1 = nada)
    cue_changed = Signal(int)
    position = Signal(float, float)     # posición, duración del clip al aire
    message = Signal(str)
    playlist_end = Signal()

    def __init__(self, db, player, parent=None):
        super().__init__(parent)
        self.db = db
        self.player = player
        self.items = []
        self.onair = -1
        self.cue = -1
        self.mode = "auto"          # auto | manual
        self.loop = True
        self.exact_time = True
        self.autofill = False
        self.tandas = False
        self.autofill_category = "Todas"
        self.autofill_count = 10
        self.tandas_category = "Publicidad"
        self.tandas_count = 2
        self.audio_pref = "AUTO"
        self.sub_pref = "OFF"
        self.paused = False
        # v23.3: filler automático. Cuando se acaba la lista y no hay
        # loop ni autofill, se carga un clip de filler con loop infinito
        # para que el monitor nunca quede en negro. Configurable desde
        # Ajustes (filler_path). Si no hay filler, se muestra un slate
        # estático generado en runtime.
        self.filler_path = ""
        self.filler_enabled = True
        self.filler_active = False  # True mientras el filler está al aire
        self._filler_play_count = 0
        # v23.3.1: contador de fallos consecutivos al cargar filler/slate.
        # Si el clip de filler no existe y el slate lavfi tampoco carga
        # (build de mpv sin lavfi/fontconfig, ver _play_slate), mpv emite
        # end-file(error) apenas se manda el loadfile. Sin este límite,
        # _on_ended reintentaba filler→slate en cada end-file, generando
        # un loop infinito de loadfile/end-file que dejaba el programa
        # "pegado" al terminar la lista (tick tras tick sin nunca asentarse).
        self._filler_fail_count = 0
        self._pos = 0.0
        self._dur = 0.0
        self._started_at = 0.0
        self._log_id = None
        self._consecutive_errors = 0
        self._fixed_fired = set()
        self._dirty = False
        # Estado de transición del reproductor. `end-file` es el camino
        # normal, pero algunas builds de mpv sólo notifican idle-active al
        # llegar al EOF. Mientras se carga el siguiente archivo ignoramos
        # ese idle transitorio para no cerrar el clip nuevo por error.
        self._load_pending = False
        self.on_start_callbacks = []     # callable(index, item)
        self.on_items_replaced = []      # callable(items, index)

        player.ended.connect(self._on_ended)
        player.loaded.connect(self._on_loaded)
        player.position.connect(self._on_position)
        # Red de seguridad: si el build de mpv no entrega end-file, el
        # cambio a idle-active=True igualmente permite continuar la tanda.
        try:
            player.idle.connect(self._on_player_idle)
        except AttributeError:
            pass
        player.process_died.connect(self._on_player_died)

        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(500)
        self._tick_timer.timeout.connect(self._tick)
        self._tick_timer.start()
        self._save_timer = QTimer(self)
        self._save_timer.setInterval(1500)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self.save_current)

    # ----------------------------------------------------------- propiedades
    @property
    def current(self):
        return self.items[self.onair] if 0 <= self.onair < len(self.items) else None

    @property
    def is_on_air(self):
        return self.onair >= 0

    @property
    def elapsed(self):
        # v22.2.4: si mpv no está reportando time-pos por IPC (caso
        # documentado en v22.2.3 con build vieja de mpv), _pos queda en
        # 0 aunque el video SÍ avance visualmente. En ese caso estimamos
        # la posición con el reloj de pared: ahora - _started_at.
        if self._pos > 0:
            return self._pos
        if 0 <= self.onair < len(self.items) and self._started_at > 0 and not self.paused:
            return max(0.0, time.time() - self._started_at)
        return self._pos

    @property
    def duration(self):
        cur = self.current
        if self._dur > 0:
            return self._dur
        return cur["duration"] if cur else 0.0

    @property
    def remain(self):
        return max(0.0, self.duration - self._pos)

    def playlist_remaining(self):
        total = self.remain if self.is_on_air else 0.0
        start = self.onair + 1 if self.is_on_air else self._first_pending()
        if start is None:
            return total
        for it in self.items[start:]:
            if it["status"] not in DONE_STATES and it["status"] != ST_ONAIR:
                total += it["duration"] or 0
        return total

    def _first_pending(self, after=-1):
        for i in range(after + 1, len(self.items)):
            if self.items[i]["status"] in (ST_PENDING, ST_READY):
                return i
        return None

    def next_index(self):
        """Siguiente evento a emitir: cue si existe, si no el primer pendiente tras el aire."""
        if 0 <= self.cue < len(self.items) and self.items[self.cue]["status"] in (ST_PENDING, ST_READY):
            return self.cue
        return self._first_pending(self.onair)

    # -------------------------------------------------------------- edición
    def _mark_dirty(self):
        self._dirty = True
        self._save_timer.start()

    def set_items(self, items, notify=True):
        self.items = [dict(it) for it in items]
        self.onair = -1
        self.cue = -1
        self._fixed_fired.clear()
        if notify:
            self.items_changed.emit()
            self.onair_changed.emit(-1)
            self.cue_changed.emit(-1)
        self._mark_dirty()

    def replace_playlist(self, items, start=True, reason="scheduled"):
        """Reemplaza la playlist (p. ej. desde el programador) y opcionalmente empieza a emitir."""
        was_on_air = self.is_on_air
        self._finish_current(ST_CUT)          # cierra el as-run del evento actual
        self.set_items(items)
        if start and self.items:
            self.play_index(0, reason)
        elif was_on_air:
            self.stop()

    def insert_items(self, index, items):
        items = [dict(it) for it in items if it.get("path")]
        if not items:
            return 0
        if index is None or index < 0 or index > len(self.items):
            index = len(self.items)
        self.items[index:index] = items
        if self.onair >= index:
            self.onair += len(items)
        if self.cue >= index:
            self.cue += len(items)
        self._fixed_fired = {k for k in self._fixed_fired}
        self.items_changed.emit()
        self._mark_dirty()
        return len(items)

    def append_items(self, items):
        return self.insert_items(len(self.items), items)

    def remove_indices(self, indices):
        indices = sorted({i for i in indices if 0 <= i < len(self.items) and i != self.onair}, reverse=True)
        if not indices:
            return 0
        for i in indices:
            del self.items[i]
            if self.onair > i:
                self.onair -= 1
            if self.cue == i:
                self.cue = -1
            elif self.cue > i:
                self.cue -= 1
        self.items_changed.emit()
        self.cue_changed.emit(self.cue)
        self._mark_dirty()
        return len(indices)

    def move(self, index, delta):
        j = index + delta
        if not (0 <= index < len(self.items)) or not (0 <= j < len(self.items)):
            return index
        self.items[index], self.items[j] = self.items[j], self.items[index]
        for attr in ("onair", "cue"):
            v = getattr(self, attr)
            if v == index:
                setattr(self, attr, j)
            elif v == j:
                setattr(self, attr, index)
        self.items_changed.emit()
        self._mark_dirty()
        return j

    def duplicate(self, index):
        if not (0 <= index < len(self.items)):
            return
        copy = dict(self.items[index])
        copy["status"] = ST_PENDING
        copy["aired_at"] = None
        copy["fixed_time"] = ""
        self.insert_items(index + 1, [copy])

    def update_item(self, index, **fields):
        if not (0 <= index < len(self.items)):
            return
        self.items[index].update(fields)
        self.item_changed.emit(index)
        self._mark_dirty()

    def refresh_meta_from_db(self, path):
        row = self.db.media_by_path(path)
        if not row:
            return
        meta = make_item(row)
        for i, it in enumerate(self.items):
            if it["path"] == path:
                for k in ("duration", "width", "height", "fps", "video_codec", "audio_codec", "tracks", "thumb"):
                    it[k] = meta[k]
                self.item_changed.emit(i)

    def clear(self):
        if self.is_on_air:
            cur = self.items[self.onair]
            self.items = [cur]
            self.onair = 0
        else:
            self.items = []
            self.onair = -1
        self.cue = -1
        self._fixed_fired.clear()
        self.items_changed.emit()
        self.onair_changed.emit(self.onair)
        self.cue_changed.emit(-1)
        self._mark_dirty()

    def clear_aired(self):
        keep = []
        new_onair = -1
        new_cue = -1
        for i, it in enumerate(self.items):
            if it["status"] in DONE_STATES:
                continue
            if i == self.onair:
                new_onair = len(keep)
            if i == self.cue:
                new_cue = len(keep)
            keep.append(it)
        removed = len(self.items) - len(keep)
        self.items = keep
        self.onair, self.cue = new_onair, new_cue
        self.items_changed.emit()
        self.onair_changed.emit(self.onair)
        self.cue_changed.emit(self.cue)
        self._mark_dirty()
        return removed

    def reset_statuses(self):
        for i, it in enumerate(self.items):
            if i != self.onair:
                it["status"] = ST_PENDING
                it["aired_at"] = None
        self._fixed_fired.clear()
        self.items_changed.emit()
        self._mark_dirty()

    # ------------------------------------------------------------- guardado
    def save_current(self):
        if not self._dirty:
            return
        try:
            self.db.save_playlist("__current__", self.items)
            self._dirty = False
        except Exception as e:  # noqa: BLE001
            log.error("No se pudo guardar la playlist actual: %s", e)

    def restore_current(self):
        try:
            rows = self.db.load_playlist("__current__")
        except Exception as e:  # noqa: BLE001
            log.error("No se pudo restaurar la playlist: %s", e)
            return 0
        items = [make_item(r) for r in rows]
        self.items = items
        self.onair = -1
        self.cue = -1
        self.items_changed.emit()
        return len(items)

    def export_items(self):
        return [dict(it) for it in self.items]

    # -------------------------------------------------------------- control
    def set_cue(self, index):
        if index is not None and 0 <= index < len(self.items) and self.items[index]["status"] in (ST_PENDING, ST_READY):
            old = self.cue
            if old >= 0 and old < len(self.items) and self.items[old]["status"] == ST_READY:
                self.items[old]["status"] = ST_PENDING
                self.item_changed.emit(old)
            self.cue = index
            self.items[index]["status"] = ST_READY
            self.item_changed.emit(index)
        else:
            old = self.cue
            self.cue = -1
            if 0 <= old < len(self.items) and self.items[old]["status"] == ST_READY:
                self.items[old]["status"] = ST_PENDING
                self.item_changed.emit(old)
        self.cue_changed.emit(self.cue)

    def play_index(self, index, reason="manual"):
        if not (0 <= index < len(self.items)):
            return False
        item = self.items[index]
        if not item.get("path") or not os.path.isfile(item["path"]):
            item["status"] = ST_ERROR
            item["note"] = "archivo no encontrado"
            self.item_changed.emit(index)
            self.message.emit(f"ERROR • archivo no encontrado: {item['title']}")
            self._consecutive_errors += 1
            if reason != "manual" and self._consecutive_errors < len(self.items):
                nxt = self._first_pending(index)
                if nxt is not None:
                    return self.play_index(nxt, reason)
            return False
        # cierra el anterior (si terminó solo ya está marcado EMITIDO; si lo cortamos, CORTADO)
        self._finish_current(ST_CUT)
        aid = pick_audio(item.get("tracks"), item.get("audio_lang") or self.audio_pref)
        sid = pick_subtitle(item.get("tracks"), item.get("subtitle_lang") or self.sub_pref)
        self.paused = False
        # Se marca antes de enviar loadfile: mpv puede emitir idle-active
        # durante el reemplazo del archivo anterior. Ese idle no significa
        # que el nuevo clip terminó.
        self._load_pending = True
        ok = self.player.play(item["path"], audio_id=aid, sub_id=sid)
        if not ok:
            self._load_pending = False
            item["status"] = ST_ERROR
            item["note"] = "mpv no disponible"
            self.item_changed.emit(index)
            self.message.emit("No se pudo iniciar mpv. Revisa Ajustes del sistema.")
            return False
        if index == self.cue:
            self.cue = -1
            self.cue_changed.emit(-1)
        self.onair = index
        self.filler_active = False
        self._pos = 0.0
        self._dur = item["duration"] or 0.0
        self._started_at = time.time()
        item["status"] = ST_ONAIR
        item["aired_at"] = datetime.now()
        item["note"] = ""
        self._fixed_fired.add(id(item))
        self._log_id = self.db.air_log_start(item["title"], item["path"], item["category"], item["duration"], reason)
        self.item_changed.emit(index)
        self.onair_changed.emit(index)
        self.position.emit(0.0, self._dur)
        self.message.emit(f"ON AIR • {item['title']}")
        log.info("ON AIR [%s] %s (%s)", reason, item["title"], item["path"])
        for cb in list(self.on_start_callbacks):
            try:
                cb(index, item)
            except Exception as e:  # noqa: BLE001
                log.error("callback de inicio: %s", e)
        self._mark_dirty()
        return True

    def _finish_current(self, status):
        if 0 <= self.onair < len(self.items):
            it = self.items[self.onair]
            if it["status"] == ST_ONAIR:
                it["status"] = status
                self.item_changed.emit(self.onair)
        if self._log_id:
            self.db.air_log_end(self._log_id, status)
            self._log_id = None

    def play_next(self, reason="manual"):
        nxt = self.next_index()
        if nxt is None:
            nxt = self._end_of_playlist(reason)
            if nxt is None:
                return False
        return self.play_index(nxt, reason)

    def play(self, selected=None):
        """Botón PLAY: reanuda si está en pausa; si no, emite el seleccionado / cue / siguiente."""
        if self.is_on_air and self.paused:
            self.toggle_pause()
            return True
        if selected is not None and 0 <= selected < len(self.items) and selected != self.onair:
            return self.play_index(selected)
        if not self.is_on_air:
            return self.play_next()
        return False

    def stop(self):
        self._finish_current(ST_CUT)
        self.player.stop()
        prev = self.onair
        self.onair = -1
        self.filler_active = False
        self._load_pending = False
        self.paused = False
        self._pos = 0.0
        self._dur = 0.0
        self.onair_changed.emit(-1)
        self.position.emit(0.0, 0.0)
        if prev >= 0:
            self.message.emit("STOP")
        self._mark_dirty()

    def toggle_pause(self):
        if not self.is_on_air:
            return False
        self.paused = not self.paused
        self.player.set_pause(self.paused)
        self.message.emit("PAUSA (solo local)" if self.paused else "REANUDADO")
        return self.paused

    def seek_fraction(self, frac):
        if self.is_on_air and self.duration > 0:
            self.player.seek(frac * self.duration, absolute=True)

    # ---------------------------------------------------------- eventos mpv
    def _on_loaded(self):
        self._consecutive_errors = 0
        self._filler_fail_count = 0
        self._load_pending = False

    def _on_player_idle(self, is_idle):
        """Continúa la secuencia cuando mpv sólo informa idle-active.

        `end-file` sigue siendo la señal principal. Esta ruta cubre builds
        que, con ciertos contenedores o decodificadores, llegan a idle sin
        entregar el evento de fin por IPC. `_load_pending` evita tomar como
        EOF el idle que ocurre mientras se reemplaza el clip anterior.
        """
        if not is_idle or self._load_pending or self.paused:
            return
        # Confirmar en el siguiente ciclo evita que el idle-active del clip
        # saliente cierre el clip nuevo cuando ambos eventos llegan juntos.
        QTimer.singleShot(150, self._confirm_player_idle)

    def _confirm_player_idle(self):
        if self._load_pending or self.paused:
            return
        # MPVPlayer mantiene este estado y lo pone en False en file-loaded.
        # Si el fake/player no lo expone, la condición por defecto permite
        # usar igualmente la red de seguridad.
        if getattr(self.player, "_idle_active", True) is False:
            return
        if self.is_on_air:
            self._on_ended("eof")
        elif self.filler_active and self.onair == -2:
            self._on_ended("eof")

    def _on_position(self, pos, dur):
        # Descarta posición/duración que pudiera pertenecer al clip
        # saliente mientras esperamos file-loaded del nuevo. Sin este
        # guard, una respuesta IPC retrasada puede sobrescribir la
        # duración del siguiente evento y disparar el watchdog demasiado
        # pronto.
        if self._load_pending or not self.is_on_air:
            return
        # v23.3: si el filler está al aire (onair == -2), no actualizamos
        # _pos/_dur — el filler es loop infinito y no tiene duración
        # significativa para mostrar en la UI.
        if self.onair == -2:
            return
        self._pos = pos
        if dur and dur > 0:
            if abs(dur - self._dur) > 0.5:
                self._dur = dur
                cur = self.current
                if cur and (not cur["duration"] or abs(cur["duration"] - dur) > 1.0):
                    cur["duration"] = dur
                    self.item_changed.emit(self.onair)
            self._dur = dur
        self.position.emit(self._pos, self._dur)

    def _on_ended(self, reason):
        if reason not in ("eof", "error"):
            return
        # Al reemplazar un archivo mpv puede notificar un EOF residual antes
        # de file-loaded. No debe cerrar el clip que todavía se está
        # cargando; los errores sí se procesan para poder saltar al próximo.
        if self._load_pending and reason == "eof":
            return
        filler_ended = self.filler_active and self.onair == -2
        if not self.is_on_air and not filler_ended:
            return
        idx = self.onair
        # v23.3: si el clip que terminó era el filler, NO disparamos el
        # flujo de fin de playlist normal. Sólo recargamos el filler
        # (loop infinito) sin emitir FIN DE PLAYLIST.
        if idx == -2:  # convención: -2 = filler al aire (ver _play_filler)
            self._pos = 0.0
            self._filler_fail_count += 1
            if self._filler_fail_count > 3:
                # v23.3.1: ni el filler ni el slate lavfi cargan (mpv
                # emite end-file apenas mandamos loadfile). Reintentar
                # de nuevo solo repite el mismo ciclo end-file→retry sin
                # parar y "cuelga" el playout. Nos rendimos: dejamos el
                # monitor realmente detenido (onair=-1) y avisamos al
                # operador en vez de loopear para siempre.
                log.error(
                    "Filler/slate falló %d veces seguidas cargando; se detiene el reintento (monitor en negro).",
                    self._filler_fail_count,
                )
                self.message.emit("ERROR • no se pudo mostrar filler ni slate • monitor detenido")
                self.filler_active = False
                self._filler_fail_count = 0
                self.onair = -1
                self.onair_changed.emit(-1)
                return
            if not self._play_filler(reason):
                # si no se pudo cargar el filler otra vez, caemos al slate
                if not self._play_slate() and not self.filler_enabled:
                    self.filler_active = False
                    self.onair = -1
                    self.onair_changed.emit(-1)
            return
        item = self.items[idx]
        if reason == "error":
            item["status"] = ST_ERROR
            item["note"] = "no se pudo reproducir"
            self._consecutive_errors += 1
            self.db.air_log_end(self._log_id, ST_ERROR)
            self._log_id = None
            log.warning("mpv no pudo reproducir: %s", item["path"])
        else:
            item["status"] = ST_AIRED
            self._consecutive_errors = 0
            self.db.air_log_end(self._log_id, ST_AIRED)
            self._log_id = None
        self.item_changed.emit(idx)
        self.onair = -1
        self._pos = 0.0
        self.onair_changed.emit(-1)
        if reason == "error" and self._consecutive_errors >= max(3, len(self.items)):
            self.message.emit("Demasiados errores consecutivos • emisión detenida")
            return
        if self.tandas and reason == "eof" and item["category"] != self.tandas_category:
            nxt_idx = self._first_pending(idx)
            nxt_is_ad = nxt_idx is not None and self.items[nxt_idx]["category"] == self.tandas_category
            if not nxt_is_ad:
                self._insert_tanda(idx)
        if self.mode == "auto":
            nxt = self.next_index()
            if nxt is None:
                nxt = self._end_of_playlist("auto")
            if nxt is not None:
                self.play_index(nxt, "auto")
            else:
                # v23.3: no hay más clips. Antes emitíamos "FIN DE
                # PLAYLIST" y dejábamos el monitor en negro. Ahora
                # intentamos cargar el filler (clip de relleno con loop
                # infinito). Si no hay filler configurado, mostramos un
                # slate estático.
                self.filler_active = False
                if not self._play_filler("eof"):
                    self._play_slate()
                self.message.emit("FIN DE PLAYLIST • filler al aire")
                self.playlist_end.emit()
        else:
            nxt = self.next_index()
            if nxt is not None and self.cue < 0:
                self.set_cue(nxt)
            # v23.3: en modo manual, también cargamos filler al final
            # para que el operador pueda decidir si quiere algo
            # específico.
            if nxt is None and not self.is_on_air:
                self.filler_active = False
                if not self._play_filler("eof"):
                    self._play_slate()
            self.message.emit("MODO MANUAL • esperando PLAY")

    def _on_player_died(self):
        if self.is_on_air:
            idx = self.onair
            self.items[idx]["status"] = ST_ERROR
            self.items[idx]["note"] = "mpv se cerró"
            self.item_changed.emit(idx)
            self.db.air_log_end(self._log_id, ST_ERROR)
            self._log_id = None
            self.onair = -1
            self.onair_changed.emit(-1)
        elif self.filler_active and self.onair == -2:
            self.onair = -1
            self.filler_active = False
            self.onair_changed.emit(-1)
        self._load_pending = False
        self.message.emit("mpv se cerró inesperadamente • pulsa PLAY para reiniciarlo")

    # ------------------------------------------------------- automatización
    def _end_of_playlist(self, reason):
        """Devuelve el índice a emitir cuando ya no quedan pendientes (autofill / loop) o None."""
        if self.autofill:
            added = self.fill(self.autofill_category, self.autofill_count)
            if added:
                self.message.emit(f"AUTOFILL • {added} eventos añadidos ({self.autofill_category})")
                return self._first_pending(self.onair)
        if self.loop and self.items:
            for it in self.items:
                if it["status"] in DONE_STATES:
                    it["status"] = ST_PENDING
                    it["aired_at"] = None
            self._fixed_fired.clear()
            self.items_changed.emit()
            self.message.emit("LOOP • playlist reiniciada")
            return self._first_pending(-1)
        return None

    # v23.3: filler automático + slate fallback.
    def _play_filler(self, reason):
        """Carga el clip de filler (configurado en Ajustes) en loop
        infinito. Retorna True si se cargó, False si no hay filler o
        el archivo no existe. La convención es usar self.onair = -2
        mientras el filler está al aire, así _on_ended sabe que
        debe re-cargar el filler (no buscar el siguiente clip).
        """
        if not self.filler_enabled:
            return False
        if not self.filler_path or not os.path.isfile(self.filler_path):
            return False
        # cerramos el item actual (sea clip normal, otro filler, o nada)
        if 0 <= self.onair < len(self.items):
            self._finish_current(ST_CUT)
        if self._log_id:
            self.db.air_log_end(self._log_id, ST_AIRED)
            self._log_id = None
        # usamos el MPVPlayer directamente con loop-file=inf
        self.paused = False
        self._load_pending = True
        ok = False
        if hasattr(self.player, "play_loop"):
            ok = self.player.play_loop(self.filler_path)
        else:
            # fallback: play normal con loop-file
            ok = self.player.play(self.filler_path, loop=True)
        if not ok:
            self._load_pending = False
            return False
        self.onair = -2  # convención: filler al aire
        self.filler_active = True
        self._filler_play_count += 1
        self._pos = 0.0
        self._dur = 0.0
        self._started_at = time.time()
        self.onair_changed.emit(-2)
        self.position.emit(0.0, 0.0)
        log.info("FILLER al aire (%dx) • %s", self._filler_play_count, self.filler_path)
        return True

    def _play_slate(self):
        """v23.3: slate estático como fallback del filler. Usa la URL
        lavfi de mpv (`av://lavfi:color=...:drawtext=...`) para generar
        un patrón negro con texto "TVPlayout PRO — Próximamente" en vivo.
        No requiere archivos externos ni PIL — mpv lo genera en runtime.
        """
        if not self.filler_enabled:
            return False
        # Slate URL: color negro 1920x1080 con texto centrado.
        # drawtext usa fontfile por default; en Windows buscamos Arial.
        # Si no hay fuente, mpv cae al default.
        font_path = ""
        if os.name == "nt":
            arial = r"C:\Windows\Fonts\arial.ttf"
            if os.path.isfile(arial):
                font_path = f":fontfile='{arial}'"
        # Construimos la URL lavfi. Usamos comillas simples adentro
        # porque mpv/ffmpeg parsea con espacios.
        # v23.3.1: el segundo drawtext no llevaba font_path, así que en
        # builds de mpv sin fontconfig (portables, sin libfontconfig)
        # fallaba solo ese filtro y el loadfile completo se rechazaba
        # (end-file error), lo que alimentaba el loop de reintento de
        # arriba. Ambos drawtext deben usar el mismo fontfile.
        slate_url = (
            "av://lavfi:color=c=black:s=1920x1080:r=30,"
            f"drawtext{font_path}:text='TVPlayout PRO':"
            "fontsize=80:fontcolor=white:x=(w-tw)/2:y=(h-th)/2-100,"
            f"drawtext{font_path}:text='PROXIMAMENTE':"
            "fontsize=60:fontcolor=gray:x=(w-tw)/2:y=(h-th)/2,"
            "format=yuv420p"
        )
        if not hasattr(self.player, "play_loop"):
            log.error("MPVPlayer no tiene play_loop; slate no soportado")
            return False
        if 0 <= self.onair < len(self.items):
            self._finish_current(ST_CUT)
        if self._log_id:
            self.db.air_log_end(self._log_id, ST_AIRED)
            self._log_id = None
        self._load_pending = True
        ok = self.player.play_loop(slate_url)
        if not ok:
            self._load_pending = False
        if ok:
            self.onair = -2
            self.filler_active = True
            self._filler_play_count += 1
            self._pos = 0.0
            self._dur = 0.0
            self._started_at = time.time()
            self.onair_changed.emit(-2)
            self.position.emit(0.0, 0.0)
            log.info("SLATE al aire (lavfi)")
        return ok

    def fill(self, category, count, index=None):
        exclude = [it["path"] for it in self.items[-50:]]
        rows = self.db.random_media(category, count, exclude_paths=exclude)
        if not rows:
            rows = self.db.random_media(category, count)
        if not rows:
            return 0
        items = [make_item(r, note="autofill") for r in rows]
        return self.insert_items(len(self.items) if index is None else index, items)

    def _insert_tanda(self, after_index):
        rows = self.db.random_media(self.tandas_category, self.tandas_count)
        if not rows:
            return 0
        items = [make_item(r, note="tanda") for r in rows]
        n = self.insert_items(after_index + 1, items)
        if n:
            self.message.emit(f"TANDA • {n} anuncios insertados")
        return n

    def _tick(self):
        # v23.0: crossfade de audio. Cuando quedan crossfade_duration
        # segundos para terminar el clip al aire, aplicamos un fade-out
        # al audio de mpv para que la transición al próximo clip sea
        # suave. El fade-in del próximo clip se aplica en player.play()
        # vía el filter chain (afade=t=in:st=0). Si crossfade_enabled
        # es False, no se hace nada (corte directo).
        if (self.is_on_air and not self.paused and self.duration > 0
                and getattr(self.player, "crossfade_enabled", False)):
            try:
                d = float(getattr(self.player, "crossfade_duration", 0.0) or 0.0)
                if d > 0 and not getattr(self.player, "_fade_out_applied", False):
                    rem = self.duration - self.elapsed
                    # disparamos un poquito antes para que el fade esté
                    # completo cuando mpv emita end-file
                    if rem <= d + 0.05:
                        self.player.fade_out(d)
            except Exception:
                pass
        # v22.2.9: watchdog de fin de clip. Si mpv no emite end-file por
        # IPC (caso documentado en v22.2.3), el playout no detecta que
        # el clip terminó y queda colgado en el último frame con posición
        # estimada > duración. Este watchdog dispara _on_ended("eof")
        # cuando elapsed > duration + 2s de tolerancia.
        if self.is_on_air and not self.paused and self.duration > 0:
            try:
                pos = float(self.elapsed or 0.0)
                if pos > self.duration + 2.0:
                    log.warning(
                        "Watchdog fin de clip: %.2fs > duración %.2fs (%s)",
                        pos, self.duration, self.current["title"] if self.current else "?",
                    )
                    self.message.emit(f"FIN DE CLIP (watchdog) • {self.current['title'] if self.current else ''}")
                    self._on_ended("eof")
                    return
            except Exception:
                pass
        if not self.exact_time or not self.items:
            return
        now = datetime.now()
        for i, it in enumerate(self.items):
            ft = it.get("fixed_time")
            if not ft or it["status"] in DONE_STATES or it["status"] == ST_ONAIR or id(it) in self._fixed_fired:
                continue
            target = parse_fixed_time(ft, now)
            if target is None:
                continue
            delta = (now - target).total_seconds()
            if 0 <= delta <= 30:
                self._fixed_fired.add(id(it))
                self.message.emit(f"HORA EXACTA • {ft} • {it['title']}")
                log.info("Hora exacta %s → %s", ft, it["title"])
                self.play_index(i, "fixed")
                break

    # ------------------------------------------------------------- tiempos
    def compute_times(self):
        """Hora estimada de inicio de cada evento (datetime o None) y marca de retraso."""
        n = len(self.items)
        out = [None] * n
        now = datetime.now()
        if self.is_on_air:
            out[self.onair] = datetime.fromtimestamp(self._started_at) if self._started_at else now
            cursor = now + timedelta(seconds=self.remain) if self.duration else now
            start = self.onair + 1
        else:
            nxt = self.next_index()
            start = nxt if nxt is not None else n
            cursor = now
        for i in range(n):
            it = self.items[i]
            if i < start and i != self.onair:
                out[i] = it.get("aired_at")
                it["late"] = False
                continue
            if i == self.onair:
                continue
            if it["status"] in DONE_STATES:
                out[i] = it.get("aired_at")
                continue
            ft = it.get("fixed_time")
            it["late"] = False
            if ft:
                target = parse_fixed_time(ft, cursor)
                if target is not None:
                    if target < cursor:
                        it["late"] = True
                        t = target if self.exact_time else cursor
                    else:
                        t = target
                else:
                    t = cursor
            else:
                t = cursor
            out[i] = t
            cursor = t + timedelta(seconds=it["duration"] or 0)
        return out


def parse_fixed_time(text, ref):
    """'HH:MM' o 'HH:MM:SS' → datetime del día de `ref` (o del siguiente si ya pasó hace más de 12 h)."""
    text = (text or "").strip()
    if not text:
        return None
    parts = text.split(":")
    try:
        h = int(parts[0])
        m = int(parts[1]) if len(parts) > 1 else 0
        s = int(parts[2]) if len(parts) > 2 else 0
    except (ValueError, IndexError):
        return None
    if not (0 <= h < 24 and 0 <= m < 60 and 0 <= s < 60):
        return None
    target = ref.replace(hour=h, minute=m, second=s, microsecond=0)
    if (ref - target).total_seconds() > 12 * 3600:
        target += timedelta(days=1)
    return target
