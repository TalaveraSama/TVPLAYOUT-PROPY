"""Controlador de continuidad: modelo de playlist + lógica de emisión (automático/manual, hora exacta,
autofill, tandas, loop, cue) sobre el reproductor local PyAV. La salida RTMP/SRT/NDI se engancha mediante callbacks."""
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


def trim_bounds(item_or_duration, mark_in=0.0, mark_out=0.0):
    """Normaliza marcas y devuelve (inicio, fin, duración efectiva).

    Las marcas son metadatos de la entrada de playlist: nunca se escribe ni
    se modifica el archivo original. ``mark_out=0`` significa hasta el final.
    """
    if isinstance(item_or_duration, dict):
        source = item_or_duration.get("source_duration") or item_or_duration.get("duration") or 0
        mark_in = item_or_duration.get("mark_in", mark_in)
        mark_out = item_or_duration.get("mark_out", mark_out)
    else:
        source = item_or_duration
    try:
        source = max(0.0, float(source or 0))
    except (TypeError, ValueError):
        source = 0.0
    try:
        start = max(0.0, float(mark_in or 0))
        end = max(0.0, float(mark_out or 0))
    except (TypeError, ValueError):
        start, end = 0.0, 0.0
    if source > 0:
        start = min(start, source)
        if end > 0:
            end = min(end, source)
    if end <= 0:
        end = source
    if end < start:
        end = start
    return start, end, max(0.0, end - start)


def make_item(row_or_dict, **extra):
    """Normaliza una fila de la BD o un dict a un evento de playlist."""
    src = dict(row_or_dict) if not isinstance(row_or_dict, dict) else dict(row_or_dict)
    tracks = src.get("tracks") or []
    if isinstance(tracks, str):
        try:
            tracks = json.loads(tracks or "[]")
        except ValueError:
            tracks = []
    source_duration = float(src.get("source_duration") or src.get("duration") or 0)
    mark_in, mark_out, effective_duration = trim_bounds(
        source_duration, src.get("mark_in", 0), src.get("mark_out", 0)
    )
    item = {
        "media_id": src.get("media_id") if "media_id" in src else src.get("id"),
        "path": src.get("path", ""),
        "title": src.get("title") or Path(src.get("path", "")).stem,
        "category": src.get("category") or "Otros",
        "duration": effective_duration,
        "source_duration": source_duration,
        "mark_in": mark_in,
        "mark_out": mark_out if mark_out < source_duration or source_duration <= 0 else 0.0,
        "width": int(src.get("width") or 0),
        "height": int(src.get("height") or 0),
        "fps": float(src.get("fps") or 0),
        "video_codec": src.get("video_codec") or "",
        "audio_codec": src.get("audio_codec") or "",
        "tracks": tracks,
        "thumb": src.get("thumb") or "",
        "tmdb_poster": src.get("tmdb_poster") or "",
        "tmdb_backdrop": src.get("tmdb_backdrop") or "",
        "tmdb_title": src.get("tmdb_title") or "",
        "tmdb_year": src.get("tmdb_year") or "",
        "tmdb_overview": src.get("tmdb_overview") or "",
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
        # Tanda intermedia independiente de la tanda al final del evento.
        # Se dispara sólo en Películas/Música y el clip continúa desde el
        # offset exacto que reportó PyAV al entrar en la tanda.
        self.midroll_enabled = False
        self.midroll_category = "Publicidad"
        self.midroll_interval_minutes = 15
        self._midroll_next_at = 0.0
        self._midroll_resume = None
        # Identificadores de estación: son clips transitorios, no se agregan
        # como eventos permanentes a la playlist ni se aplican a publicidad,
        # filler o slate.
        self.identifiers_enabled = False
        self.identifier_in_path = ""
        self.identifier_out_path = ""
        self.identifier_categories = {"Películas", "Música"}
        self._identifier_transition = None
        self._position_base = 0.0
        self.audio_pref = "AUTO"
        self.sub_pref = "OFF"
        self.paused = False
        # v23.3: filler automático. Cuando se acaba la lista y no hay
        # loop ni autofill, se carga un clip de filler con loop infinito
        # para que el monitor nunca quede en negro. Configurable desde
        # Ajustes (filler_path). Si no hay filler, se muestra un slate
        # estático generado en runtime.
        self.filler_path = ""
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
        self.on_start_callbacks = []     # callable(index, item)
        self.on_items_replaced = []      # callable(items, index)

        player.ended.connect(self._on_ended)
        player.loaded.connect(self._on_loaded)
        player.position.connect(self._on_position)
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
        track_changed = any(k in fields for k in ("audio_lang", "subtitle_lang"))
        if any(k in fields for k in ("mark_in", "mark_out", "source_duration")):
            preview = dict(self.items[index])
            preview.update(fields)
            start, end, effective = trim_bounds(preview)
            source = float(preview.get("source_duration") or 0)
            fields.update({
                "source_duration": source,
                "mark_in": start,
                "mark_out": end if end < source else 0.0,
                "duration": effective,
            })
        self.items[index].update(fields)
        self.item_changed.emit(index)
        self._mark_dirty()
        if track_changed and index == self.onair:
            self.set_track_preferences(
                fields.get("audio_lang") or self.audio_pref,
                fields.get("subtitle_lang") or self.sub_pref,
            )

    def refresh_meta_from_db(self, path):
        row = self.db.media_by_path(path)
        if not row:
            return
        meta = make_item(row)
        for i, it in enumerate(self.items):
            if it["path"] == path:
                it["source_duration"] = meta.get("source_duration") or meta.get("duration") or 0
                start, end, effective = trim_bounds(it)
                it["mark_in"], it["mark_out"], it["duration"] = start, (end if end < it["source_duration"] else 0.0), effective
                for k in ("width", "height", "fps", "video_codec", "audio_codec", "tracks", "thumb",
                          "tmdb_poster", "tmdb_backdrop", "tmdb_title", "tmdb_year", "tmdb_overview"):
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
            # Los identificadores son transitorios: nunca deben reaparecer
            # como filas permanentes después de reiniciar la aplicación.
            persistent = [it for it in self.items if not it.get("_transient_identifier")]
            self.db.save_playlist("__current__", persistent)
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

    def _track_preferences_for_item(self, item):
        audio = item.get("_live_audio_preference")
        subtitle = item.get("_live_subtitle_preference")
        if audio is None:
            audio = item.get("audio_lang") or self.audio_pref
        if subtitle is None:
            subtitle = item.get("subtitle_lang") or self.sub_pref
        return audio, subtitle

    def set_track_preferences(self, audio_preference, subtitle_preference, restart_current=True):
        """Cambia idioma/pista durante el evento actual.

        PyAV no puede cambiar el stream de un ``DecodeJob`` ya abierto sin
        perder su demuxer. Se reinicia el mismo archivo en el offset actual;
        el callback normal obliga a RTMP/SRT a hacer el mismo salto. El corte
        breve es intencional y evita que audio, subtítulo y vídeo queden en
        posiciones distintas.
        """
        self.audio_pref = str(audio_preference or "AUTO / Español latino preferido")
        self.sub_pref = str(subtitle_preference or "OFF")
        if not restart_current or not self.is_on_air:
            return True
        item = self.current
        if not item or not item.get("path") or not os.path.isfile(item["path"]):
            return False
        try:
            offset = max(0.0, float(self._pos or 0.0))
        except (TypeError, ValueError):
            offset = 0.0
        trim_start, trim_end, effective_duration = trim_bounds(item)
        if effective_duration > 0:
            offset = min(offset, effective_duration)
        aid = pick_audio(item.get("tracks"), self.audio_pref)
        sid = pick_subtitle(item.get("tracks"), self.sub_pref)
        log.info("Cambio de pistas en vivo • audio_pref=%s audio_id=%s subtitle_pref=%s subtitle_id=%s offset=%.3f",
                 self.audio_pref, aid, self.sub_pref, sid, offset)
        item["_live_audio_preference"] = self.audio_pref
        item["_live_subtitle_preference"] = self.sub_pref
        item["_start_offset"] = offset
        try:
            ok = self.player.play(item["path"], audio_id=aid, sub_id=sid,
                                  start=trim_start + offset, end=trim_end)
        except TypeError:
            ok = self.player.play(item["path"], audio_id=aid, start=trim_start + offset)
        if not ok:
            self.message.emit("No se pudo cambiar idioma/subtítulos del evento actual")
            return False
        self._position_base = offset
        self._pos = offset
        self._dur = effective_duration or self._dur
        self._started_at = time.time()
        self.position.emit(self._pos, self._dur)
        self.message.emit(f"PISTAS EN VIVO • audio: {self.audio_pref} • subtítulos: {self.sub_pref}")
        for cb in list(self.on_start_callbacks):
            try:
                cb(self.onair, item)
            except Exception as exc:  # noqa: BLE001
                log.error("callback de cambio de pistas: %s", exc)
        self._mark_dirty()
        return True

    def _identifier_eligible(self, item):
        return bool(item and item.get("category") in self.identifier_categories)

    def _start_identifier(self, index, phase):
        """Inserta un identificador temporal justo antes/después del evento.

        El evento original no se duplica ni se convierte en publicidad: el
        identificador sólo vive durante la transición y se retira al terminar,
        para que loop/clear_aired no acumulen clips invisibles.
        """
        path = self.identifier_in_path if phase == "in" else self.identifier_out_path
        if not (self.identifiers_enabled and path and os.path.isfile(path)):
            return False
        if not (0 <= index < len(self.items)):
            return False
        original = self.items[index]
        bumper = make_item({
            "path": path,
            "title": "Identificador de entrada" if phase == "in" else "Identificador de salida",
            "category": "Identificador",
            "note": "identificador temporal",
        }, _transient_identifier=True)
        if phase == "in":
            self.insert_items(index, [bumper])
            bumper_index = index
            target_index = index + 1
        else:
            self.insert_items(index + 1, [bumper])
            bumper_index = index + 1
            target_index = None
        self._identifier_transition = {
            "phase": phase,
            "bumper_index": bumper_index,
            "target_index": target_index,
            "original_index": index,
            "original_item": original,
        }
        return self.play_index(bumper_index, f"identifier-{phase}", _internal=True)

    def _remove_identifier(self, index):
        if not (0 <= index < len(self.items)):
            return
        self.items.pop(index)
        if self.onair > index:
            self.onair -= 1
        if self.cue > index:
            self.cue -= 1
        self.items_changed.emit()
        self._mark_dirty()

    def _start_midroll(self):
        """Interrumpe el evento actual y conserva el offset de reproducción."""
        if not self.midroll_enabled or not self.is_on_air or self._midroll_resume:
            return False
        item = self.current
        if not self._identifier_eligible(item):
            return False
        rows = self.db.random_media(self.midroll_category, self.tandas_count)
        if not rows:
            self.message.emit(f"TANDA INTERMEDIA • no hay medios en {self.midroll_category}")
            self._midroll_next_at = self._pos + self._midroll_interval_seconds()
            return False
        original_index = self.onair
        resume_offset = max(0.0, float(self._pos or 0.0))
        ads = [make_item(r, note="tanda intermedia") for r in rows]
        count = self.insert_items(original_index + 1, ads)
        if not count:
            return False
        # Evita que _finish_current lo marque CORTADO: queda pendiente para
        # que, al terminar los anuncios, play_index lo reabra en el offset.
        item["status"] = ST_PENDING
        item["aired_at"] = None
        self.item_changed.emit(original_index)
        self._midroll_resume = {
            "original_index": original_index,
            "offset": resume_offset,
            "last_ad_index": original_index + count,
        }
        self._midroll_next_at = 0.0
        self.message.emit(f"TANDA INTERMEDIA • {count} anuncios • reanudación en {resume_offset:.1f}s")
        return self.play_index(original_index + 1, "midroll", _internal=True)

    def _midroll_interval_seconds(self):
        try:
            return max(1.0, float(self.midroll_interval_minutes) * 60.0)
        except (TypeError, ValueError):
            return 900.0

    def play_index(self, index, reason="manual", start_offset=0.0, _internal=False):
        if not (0 <= index < len(self.items)):
            return False
        item = self.items[index]
        # Un cambio manual/fijo cancela una reanudación pendiente; no debemos
        # devolver al operador a una película que ya decidió saltar.
        if self._midroll_resume and not _internal:
            self._midroll_resume = None
        if (not _internal and not self._identifier_transition and
                self._identifier_eligible(item) and self.identifiers_enabled and
                self.identifier_in_path and os.path.isfile(self.identifier_in_path)):
            return self._start_identifier(index, "in")
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
        audio_preference, subtitle_preference = self._track_preferences_for_item(item)
        aid = pick_audio(item.get("tracks"), audio_preference)
        sid = pick_subtitle(item.get("tracks"), subtitle_preference)
        trim_start, trim_end, effective_duration = trim_bounds(item)
        try:
            resume_offset = max(0.0, float(start_offset or 0.0))
        except (TypeError, ValueError):
            resume_offset = 0.0
        resume_offset = min(resume_offset, effective_duration) if effective_duration > 0 else resume_offset
        playback_start = trim_start + resume_offset
        playback_duration = max(0.0, effective_duration - resume_offset) if effective_duration > 0 else effective_duration
        item["mark_in"] = trim_start
        item["mark_out"] = trim_end if trim_end < (item.get("source_duration") or 0) else 0.0
        item["duration"] = effective_duration
        item["_start_offset"] = resume_offset
        self.paused = False
        try:
            # La llamada histórica era start=trim_start, end=trim_end; para
            # reanudación, playback_start conserva el mismo end absoluto.
            ok = self.player.play(item["path"], audio_id=aid, sub_id=sid,
                                  start=playback_start, end=trim_end)
        except TypeError:
            # Compatibilidad con reproductores alternativos que aún no
            # exponen el argumento end; el aire activo es PyAVPlayer.
            ok = self.player.play(item["path"], audio_id=aid, sub_id=sid, start=playback_start)
        if not ok:
            item["status"] = ST_ERROR
            item["note"] = "reproductor local no disponible"
            self.item_changed.emit(index)
            self.message.emit("No se pudo iniciar el reproductor local. Revisa PyAV/INSTALL.bat.")
            return False
        if index == self.cue:
            self.cue = -1
            self.cue_changed.emit(-1)
        self.onair = index
        # PyAV expone la posición relativa al nuevo punto de seek. El
        # controlador vuelve a sumar la base para que UI, scheduler y salidas
        # IP vean la línea de tiempo original de la película.
        self._position_base = resume_offset
        self._pos = resume_offset
        self._dur = (playback_duration + resume_offset) if playback_duration > 0 else (item["duration"] or 0.0)
        self._started_at = time.time()
        self._midroll_next_at = (self._pos + self._midroll_interval_seconds()
                                 if self._identifier_eligible(item) and self.midroll_enabled else 0.0)
        item["status"] = ST_ONAIR
        item["aired_at"] = datetime.now()
        item["note"] = ""
        self._fixed_fired.add(id(item))
        self._log_id = self.db.air_log_start(item["title"], item["path"], item["category"], item["duration"], reason)
        self.item_changed.emit(index)
        self.onair_changed.emit(index)
        self.position.emit(self._pos, self._dur)
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
        self.paused = False
        self._pos = 0.0
        self._dur = 0.0
        self._position_base = 0.0
        self._midroll_next_at = 0.0
        self._midroll_resume = None
        self._identifier_transition = None
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
            target = max(0.0, float(frac) * self.duration - self._position_base)
            self.player.seek(target, absolute=True)

    # ---------------------------------------------------------- eventos mpv
    def _on_loaded(self):
        self._consecutive_errors = 0
        self._filler_fail_count = 0

    def _on_position(self, pos, dur):
        if not self.is_on_air:
            return
        # v23.3: si el filler está al aire (onair == -2), no actualizamos
        # _pos/_dur — el filler es loop infinito y no tiene duración
        # significativa para mostrar en la UI.
        if self.onair == -2:
            return
        # PyAV informa tiempo relativo al punto de entrada. Para una
        # reanudación intermedia, conservar la línea de tiempo original.
        shown_pos = max(0.0, float(pos or 0.0)) + self._position_base
        shown_dur = (max(0.0, float(dur or 0.0)) + self._position_base
                     if dur and dur > 0 else self._dur)
        self._pos = shown_pos
        if shown_dur and shown_dur > 0:
            if abs(shown_dur - self._dur) > 0.5:
                self._dur = shown_dur
                cur = self.current
                if cur and (not cur["duration"] or abs(cur["duration"] - shown_dur) > 1.0):
                    cur["duration"] = shown_dur
                    self.item_changed.emit(self.onair)
            self._dur = shown_dur
        self.position.emit(self._pos, self._dur)
        if (self.midroll_enabled and self._midroll_next_at > 0 and
                self.current and self._identifier_eligible(self.current) and
                self._pos >= self._midroll_next_at):
            self._start_midroll()

    def _on_ended(self, reason):
        if reason not in ("eof", "error"):
            return
        if not self.is_on_air:
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
                self._play_slate()
            return
        item = self.items[idx]
        transition = (self._identifier_transition
                      if self._identifier_transition and self._identifier_transition.get("bumper_index") == idx
                      else None)
        # Un identificador de salida ya terminó, pero el evento original es
        # el que debe alimentar la lógica de tanda/playlist. Cierra el log
        # del identificador y evita marcar/loguear dos veces la película.
        if transition and transition.get("phase") == "out":
            bumper = item
            bumper["status"] = ST_ERROR if reason == "error" else ST_AIRED
            if reason == "error":
                bumper["note"] = "no se pudo reproducir"
            self.db.air_log_end(self._log_id, bumper["status"])
            self._log_id = None
            self.item_changed.emit(idx)
            item = transition["original_item"]
        elif reason == "error":
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
        if not (transition and transition.get("phase") == "out"):
            self.item_changed.emit(idx)
        self.onair = -1
        self._pos = 0.0
        self._position_base = 0.0
        self.onair_changed.emit(-1)
        if transition:
            phase = transition.get("phase")
            bumper_index = idx
            self._remove_identifier(bumper_index)
            self._identifier_transition = None
            if phase == "in":
                # Al retirar el bumper, el evento original retrocede una
                # posición. Se inicia sin volver a insertar otro identificador.
                target = max(0, int(transition.get("target_index") or idx + 1) - 1)
                if 0 <= target < len(self.items):
                    self.play_index(target, "identifier-in-finished", _internal=True)
                return
            # Para el identificador de salida, continuar debajo con el evento
            # original ya finalizado (tanda al final, siguiente, filler, etc.).
            idx = int(transition.get("original_index", idx))
            item = transition.get("original_item") or item
        if reason == "error" and self._consecutive_errors >= max(3, len(self.items)):
            self.message.emit("Demasiados errores consecutivos • emisión detenida")
            return
        if (not transition and reason == "eof" and self.identifiers_enabled and
                self._identifier_eligible(item) and self.identifier_out_path and
                os.path.isfile(self.identifier_out_path)):
            if self._start_identifier(idx, "out"):
                return
        if (self._midroll_resume and reason == "eof" and
                idx < self._midroll_resume.get("last_ad_index", idx)):
            next_ad = idx + 1
            if 0 <= next_ad < len(self.items) and self.items[next_ad]["status"] in (ST_PENDING, ST_READY):
                self.play_index(next_ad, "midroll-ad", _internal=True)
            return
        if (self._midroll_resume and reason == "eof" and
                idx == self._midroll_resume.get("last_ad_index")):
            resume = self._midroll_resume
            self._midroll_resume = None
            target = int(resume.get("original_index", -1))
            if 0 <= target < len(self.items):
                self.message.emit(f"REANUDAR • {self.items[target]['title']} desde {resume.get('offset', 0.0):.1f}s")
                self.play_index(target, "midroll-resume", start_offset=resume.get("offset", 0.0), _internal=True)
            return
        if (self.tandas and reason == "eof" and not self._midroll_resume and
                item["category"] != self.tandas_category):
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
            self.items[idx]["note"] = "reproductor local se cerró"
            self.item_changed.emit(idx)
            self.db.air_log_end(self._log_id, ST_ERROR)
            self._log_id = None
            self.onair = -1
            self.onair_changed.emit(-1)
        self.message.emit("El reproductor local se cerró inesperadamente • pulsa PLAY para reiniciarlo")

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
        if not self.filler_path or not os.path.isfile(self.filler_path):
            return False
        # cerramos el item actual (sea clip normal, otro filler, o nada)
        if 0 <= self.onair < len(self.items):
            self._finish_current(ST_CUT)
        if self._log_id:
            self.db.air_log_end(self._log_id, ST_AIRED)
            self._log_id = None
        # PyAV decodifica el clip en loop infinito
        self.paused = False
        ok = False
        if hasattr(self.player, "play_loop"):
            ok = self.player.play_loop(self.filler_path)
        else:
            # fallback compatible para reproductores alternativos
            ok = self.player.play(self.filler_path, loop=True)
        if not ok:
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
        """Activa el slate dibujado por el reproductor PyAV.

        El reproductor local no depende de filtros ni de una fuente
        instalada en Windows: pinta el texto directamente sobre
        VideoSurface y lo mantiene hasta que vuelve un clip real.
        """
        if not hasattr(self.player, "play_loop"):
            log.error("El reproductor local no soporta slate")
            return False
        if 0 <= self.onair < len(self.items):
            self._finish_current(ST_CUT)
        if self._log_id:
            self.db.air_log_end(self._log_id, ST_AIRED)
            self._log_id = None
        ok = self.player.play_loop("av://slate:native")
        if ok:
            self.onair = -2
            self.filler_active = True
            self._filler_play_count += 1
            self._pos = 0.0
            self._dur = 0.0
            self._started_at = time.time()
            self.onair_changed.emit(-2)
            self.position.emit(0.0, 0.0)
            log.info("SLATE nativo al aire")
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
