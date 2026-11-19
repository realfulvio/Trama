"""Recovery copies of unsaved projects in the Qt window: when to take them, and how to bring them back.

The files are handled by ``recovery_store.py`` (no Qt). This module decides *when*: every open project with
confirmed changes gets a copy at most once per interval (30 seconds by default, 15/30/60/120 in the preferences),
and *how*: File → Recover projects… lists the copies left by a window that closed abnormally, and a notice at
start-up says how many there are.

Threads. The state of a project is captured on the GUI thread (``Project.snapshot``: frames copied, nothing
serialised) because the GUI thread is the only one that changes it. Serialising (the slow part), hashing and
writing happen on one background thread, in order, so a save, a discard or a reused tab enqueued after a write
always runs after it; each write also carries its generation, and the store refuses anything a save or a discard
already covered.

Life of a copy. One key per project (``Project.recovery_key``), one generation per copy. A normal save removes the
generations it covered; Close → Discard removes all copies of that tab; Close → Cancel keeps everything; closing
the window removes what the decisions covered. A recovered project keeps its key and generation, so if Trama stops
again before it is saved the copy is still listed (with the newer generation, if there was one).
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
import math
import os
from pathlib import Path
import tempfile
import threading
import time

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFrame,
                               QHBoxLayout, QLabel, QMessageBox, QPushButton, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout)

from analisi.i18n import active_language, config_path

from . import theme
from .recovery_store import (HEARTBEAT, INTERVALS, MAX_COPIES, MAX_SNAPSHOT_BYTES, MAX_TOTAL_BYTES, MiB, Leases,
                             RecoveryBusy, RecoveryDamaged, RecoveryLimitError, RecoveryStore, load_settings,
                             original_state, save_settings)

_TEXT = {
    "recover": ("Recover projects…", "Recupera progetti…"),
    "recover_tip": ("Reopen the recovery copies of projects that were not saved when Trama stopped.",
                    "Riapre le copie di recupero dei progetti non salvati quando Trama si è chiuso."),
    "settings": ("Recovery copies…", "Copie di recupero…"),
    "settings_tip": ("Keep recovery copies of projects with unsaved changes, and how often.",
                     "Tieni copie di recupero dei progetti con modifiche non salvate, e ogni quanto."),
    "settings_title": ("Recovery copies", "Copie di recupero"),
    "enabled": ("Keep recovery copies of projects with unsaved changes",
                "Tieni copie di recupero dei progetti con modifiche non salvate"),
    "every": ("Copy changes every", "Copia le modifiche ogni"),
    "seconds": ("{count} seconds", "{count} secondi"),
    "settings_note": ("Copies are kept in {folder}. Up to {copies} copies, {each} MiB each and {total} MiB in all; "
                      "when a limit is reached new copies stop and the existing ones stay, until you delete some "
                      "in File → Recover projects…. Undo history and drafts still open in a dialog are not copied.",
                      "Le copie stanno in {folder}. Al massimo {copies} copie, {each} MiB ciascuna e {total} MiB in "
                      "tutto; al limite le nuove copie si fermano e le esistenti restano, finché non ne elimini "
                      "qualcuna da File → Recupera progetti…. La cronologia Annulla e le bozze ancora aperte in un "
                      "dialogo non vengono copiate."),
    "settings_error": ("The preference could not be saved: {error}", "Impossibile salvare la preferenza: {error}"),
    "title": ("Recover projects", "Recupera progetti"),
    "intro": ("These projects had changes that were not saved when Trama stopped. A recovered copy opens as a "
              "new unsaved project; the original file stays as it is and can be opened in its own tab.",
              "Questi progetti avevano modifiche non salvate quando Trama si è chiuso. Una copia recuperata si apre "
              "come nuovo progetto da salvare; il file originale resta com'è e si può aprire nella sua scheda."),
    "column.project": ("Project", "Progetto"),
    "column.written": ("Last copy", "Ultima copia"),
    "column.source": ("Original file", "File originale"),
    "column.state": ("Original", "Originale"),
    "state.none": ("Never saved", "Mai salvato"),
    "state.unchanged": ("Unchanged", "Immutato"),
    "state.changed": ("Changed on disk", "Cambiato sul disco"),
    "state.missing": ("Missing", "Assente"),
    "state.unknown": ("Unknown", "Sconosciuto"),
    "no_source": ("—", "—"),
    "changed_warning": ("The original of {names} changed on disk after the copy was taken. Recovering opens the "
                        "copy beside it: save it with a new name and compare the two.",
                        "L'originale di {names} è cambiato sul disco dopo la copia. Recuperando, la copia si apre "
                        "accanto: salvala con un nuovo nome e confronta i due file."),
    "missing_warning": ("The original of {names} is no longer on disk; the copy is all that is left.",
                        "L'originale di {names} non è più sul disco; la copia è tutto ciò che resta."),
    "none": ("No recovery copies are waiting.", "Nessuna copia di recupero in attesa."),
    "other_window": ("{count} more copies belong to another Trama window that is still open.",
                     "Altre {count} copie appartengono a un'altra finestra di Trama ancora aperta."),
    "damaged": ("Copies that cannot be recovered ({count})", "Copie non recuperabili ({count})"),
    "damaged_row": ("{title}: {reason}", "{title}: {reason}"),
    "damaged_untitled": ("Unnamed copy", "Copia senza nome"),
    "damage.reference_unreadable": ("its index cannot be read", "il suo indice non si può leggere"),
    "damage.reference_invalid": ("its index is damaged", "il suo indice è rovinato"),
    "damage.payload_missing": ("the project file is missing", "manca il file del progetto"),
    "damage.payload_unreadable": ("the project file cannot be read", "il file del progetto non si può leggere"),
    "damage.payload_size": ("the project file is incomplete", "il file del progetto è incompleto"),
    "damage.payload_checksum": ("the project file was altered", "il file del progetto è stato alterato"),
    "usage": ("{copies} copies · {size} of {total} MiB · up to {limit} copies, {each} MiB each",
              "{copies} copie · {size} di {total} MiB · al massimo {limit} copie, {each} MiB ciascuna"),
    "recover_button": ("Recover", "Recupera"),
    "delete_button": ("Delete…", "Elimina…"),
    "delete_damaged": ("Delete unrecoverable…", "Elimina non recuperabili…"),
    "later": ("Later", "Più tardi"),
    "delete_title": ("Delete recovery copies", "Elimina copie di recupero"),
    "delete_question": ("Delete {count} recovery copies for good? Their unsaved changes cannot be recovered "
                        "afterwards. The original files are not touched.",
                        "Eliminare definitivamente {count} copie di recupero? Le loro modifiche non salvate non "
                        "si potranno più recuperare. I file originali non vengono toccati."),
    "recovered_title": ("{title} (recovered)", "{title} (recuperato)"),
    "recovered_file": ("{stem} (recovered).alab", "{stem} (recuperato).alab"),
    "recovered_status": ("Recovered {count} project(s). Save each with a new name to keep it.",
                         "Recuperati {count} progetti. Salvali con un nuovo nome per conservarli."),
    "no_room": ("Close a project to recover the other {count}: they stay available in File → Recover projects….",
                "Chiudi un progetto per recuperare le altre {count}: restano disponibili in File → Recupera "
                "progetti…."),
    "recover_failed": ("{title} could not be recovered: {error}", "Impossibile recuperare {title}: {error}"),
    "notice": ("Trama found {count} recovery copies of projects that were not saved.",
               "Trama ha trovato {count} copie di recupero di progetti non salvati."),
    "notice_one": ("Trama found a recovery copy of a project that was not saved.",
                   "Trama ha trovato una copia di recupero di un progetto non salvato."),
    "notice_open": ("Recover…", "Recupera…"),
    "status.off": ("Recovery copies off", "Copie di recupero disattivate"),
    "status.on": ("Recovery copies every {interval} s", "Copie di recupero ogni {interval} s"),
    "status.last": ("Last recovery copy {time}", "Ultima copia di recupero {time}"),
    "status.failed": ("Recovery copy failed · last {time}", "Copia di recupero non riuscita · ultima {time}"),
    "status.failed_never": ("Recovery copy failed", "Copia di recupero non riuscita"),
    "status.suspended": ("Recovery copies paused (limit) · last {time}",
                         "Copie di recupero sospese (limite) · ultima {time}"),
    "status.suspended_never": ("Recovery copies paused (limit)", "Copie di recupero sospese (limite)"),
    "status.failed_message": ("The recovery copy could not be written: {error}. The last good copy is kept.",
                              "Impossibile scrivere la copia di recupero: {error}. L'ultima copia valida resta."),
    "status.limit_message": ("Recovery copies are paused: {error} Free space in File → Recover projects….",
                             "Copie di recupero sospese: {error} Libera spazio da File → Recupera progetti…."),
    "limit.snapshot": ("this project is larger than {each} MiB.", "questo progetto supera {each} MiB."),
    "limit.copies": ("there are already {limit} copies.", "ci sono già {limit} copie."),
    "limit.total": ("the copies would exceed {total} MiB.", "le copie supererebbero {total} MiB."),
}


def r(key, **values):
    english, italian = _TEXT[key]
    text = italian if active_language() == "it" else english
    return text.format(**values) if values else text


def local_time(seconds, *, date=False):
    moment = datetime.fromtimestamp(seconds)
    return moment.strftime("%d/%m/%Y %H:%M:%S" if date else "%H:%M:%S")


def limit_text(error):
    reason = getattr(error, "reason", "total")
    return r(f"limit.{reason}", each=MAX_SNAPSHOT_BYTES // MiB, limit=MAX_COPIES, total=MAX_TOTAL_BYTES // MiB)


@dataclass
class _Tracked:
    project: object
    captured: int = -1  # The revision the last copy (or save) holds.
    since: float | None = None  # When the first change not yet copied was seen.
    writing: int = 0


class RecoveryController(QObject):
    """Recovery copies for one main window. Created by ``app.main`` for the real profile; tests create it with a
    temporary folder, an injected clock and a short interval."""

    written = Signal(object)  # From the background thread: the outcome of one write.
    scanned = Signal(object)  # From the background thread: the copies found at start-up.

    def __init__(self, root, *, settings_path=None, enabled=True, interval=30, clock=time.monotonic, wall=time.time,
                 owner=None, write_bytes=None, tick_ms=1000, heartbeat_ms=None):
        super().__init__()
        self.root = Path(root)
        self.settings_path = settings_path
        self.owner = owner or Leases.new_owner()
        self.leases = Leases(self.root)
        self.store = RecoveryStore(self.root, owner=self.owner, write_bytes=write_bytes, clock=wall)
        self.enabled, self.interval = bool(enabled), interval
        self.clock, self.wall = clock, wall
        self.queue = ThreadPoolExecutor(max_workers=1, thread_name_prefix="Trama-recovery")
        self.tracked = {}  # recovery_key -> _Tracked
        self.covered = {}  # recovery_key -> generation a save or a discard covered (math.inf: closed)
        self.covered_lock = threading.Lock()
        self.window = None
        self.last_written = None
        self.failure = None
        self.suspended = None
        self.reported = set()
        self.timings = []  # (generation, GUI capture ms, background ms, bytes) of the last copies, for measures.
        self.notice = None
        self.label = None
        self.closed = False
        self.written.connect(self._on_written)
        self.scanned.connect(self._on_scanned)
        self.timer = QTimer(self)
        self.timer.setInterval(tick_ms)
        self.timer.timeout.connect(self.tick)
        self.heartbeat = QTimer(self)
        self.heartbeat.setInterval(int(heartbeat_ms or HEARTBEAT * 1000))
        self.heartbeat.timeout.connect(self._renew)

    @classmethod
    def for_profile(cls):
        """The controller of the real profile: the folder ``recovery`` beside preferences.json."""
        path = config_path()
        enabled, interval = load_settings(path)
        return cls(path.parent / "recovery", settings_path=path, enabled=enabled, interval=interval)

    # -- window ------------------------------------------------------------------------------------------------
    def attach(self, window):
        self.window = window
        self.label = QLabel("")
        self.label.setObjectName("muted")
        self.label.setAccessibleName(r("settings_title"))
        window.statusBar().insertPermanentWidget(1, self.label)  # After the message, before the cell.
        self._renew()
        self.timer.start()
        self.heartbeat.start()
        self.update_label()
        self.queue.submit(self._startup_scan)

    def update_label(self):
        if self.label is None:
            return
        when = local_time(self.last_written) if self.last_written is not None else None
        if not self.enabled:
            text = r("status.off")
        elif self.suspended is not None:
            text = r("status.suspended", time=when) if when else r("status.suspended_never")
        elif self.failure is not None:
            text = r("status.failed", time=when) if when else r("status.failed_never")
        elif when is not None:
            text = r("status.last", time=when)
        else:
            text = r("status.on", interval=self.interval)
        self.label.setText(text)
        self.label.setToolTip(self.suspended or self.failure or str(self.root))

    def configure(self, enabled, interval):
        self.enabled, self.interval = bool(enabled), interval
        for tracked in self.tracked.values():
            tracked.since = None  # The new interval starts from the next change.
        self.update_label()

    # -- taking copies -----------------------------------------------------------------------------------------
    def _track(self, project):
        tracked = self.tracked.get(project.recovery_key)
        if tracked is None or tracked.project is not project:
            tracked = self.tracked[project.recovery_key] = _Tracked(project)
        return tracked

    def tick(self):
        """Called every second: copy each project whose oldest change not yet copied is one interval old. Projects
        in tabs that are not active are copied too."""
        if self.window is None or self.closed:
            return
        now = self.clock()
        keys, due = set(), []
        for session in self.window.sessions:
            project = session.project
            keys.add(project.recovery_key)
            tracked = self._track(project)
            if (not self.enabled or not project.dirty or project.revision == tracked.captured
                    or (not project.tables and not project.info_sheets)):
                tracked.since = None
                continue
            if tracked.since is None:
                tracked.since = now
            if now - tracked.since >= self.interval and not tracked.writing:
                due.append(project)
        # All states first, then the writes: a capture never competes with a serialisation already running.
        jobs = [self._prepare(project) for project in due]
        for job in jobs:
            self.queue.submit(self._write, *job)
        for key in [key for key in self.tracked if key not in keys]:
            del self.tracked[key]  # A tab that went away without the window telling (should not happen).

    def _prepare(self, project):
        """The detached state of ``project`` and its new generation, on the GUI thread."""
        start = time.perf_counter()
        tracked = self._track(project)
        snapshot = project.snapshot()
        project.recovery_generation += 1
        tracked.captured, tracked.since = project.revision, None
        tracked.writing += 1
        title = getattr(project, "recovery_base_title", None) or project.title
        gui_ms = (time.perf_counter() - start) * 1000
        return (project.recovery_key, project.recovery_generation, snapshot, title, project.recovery_source,
                project.source_stamp, gui_ms)

    def capture(self, project):
        """Take a copy of ``project`` now: detached state here, the rest on the background thread."""
        return self.queue.submit(self._write, *self._prepare(project))

    def _is_covered(self, key, generation):
        with self.covered_lock:
            return generation <= self.covered.get(key, 0)

    def _write(self, key, generation, snapshot, title, source, stamp, gui_ms):
        outcome = {"key": key, "generation": generation, "gui_ms": gui_ms}
        start = time.perf_counter()
        try:
            if self._is_covered(key, generation):
                outcome["kind"] = "skipped"
            else:
                data = snapshot.to_bytes()
                outcome["bytes"] = len(data)
                try:
                    record = self.store.write_snapshot(key, generation, data, title=title, source=source,
                                                       source_stamp=stamp)
                except RecoveryLimitError as error:
                    outcome.update(kind="limit", error=error)
                except ValueError as error:
                    outcome.update(kind="skipped" if self._is_covered(key, generation) else "failed", error=error)
                else:
                    outcome.update(kind="written", record=record)
        except Exception as error:  # Serialisation (e.g. a missing Info constant) or the disk (OSError).
            outcome.update(kind="failed", error=error)
        outcome["background_ms"] = (time.perf_counter() - start) * 1000
        if not self.closed:
            self.written.emit(outcome)
        return outcome

    def _on_written(self, outcome):
        if self.closed:
            return
        tracked = self.tracked.get(outcome["key"])
        if tracked is not None:
            tracked.writing = max(0, tracked.writing - 1)
        kind = outcome["kind"]
        if kind == "written":
            self.last_written = outcome["record"]["written"]
            self.failure = self.suspended = None
            self.timings = (self.timings + [(outcome["generation"], outcome["gui_ms"], outcome["background_ms"],
                                             outcome.get("bytes", 0))])[-20:]
        elif kind == "limit":
            if tracked is not None:
                tracked.captured = -1  # Try again at the next interval: the user may have freed space.
            message = r("status.limit_message", error=limit_text(outcome["error"]))
            self.suspended = message
            self._report(message)
        elif kind == "failed":
            if tracked is not None:
                tracked.captured = -1  # Try again at the next interval.
            message = r("status.failed_message", error=outcome["error"])
            self.failure = message
            self._report(message)
        self.update_label()

    def _report(self, message):
        """The status line says each distinct problem once; the permanent label keeps showing it, never a dialog."""
        if message in self.reported or self.window is None:
            return
        self.reported.add(message)
        self.window.status(message)

    def wait(self, timeout=10):
        """Block until the queued writes are done (tests and the drill)."""
        self.queue.submit(lambda: None).result(timeout)

    # -- the window's decisions ----------------------------------------------------------------------------------
    def _cover(self, key, generation):
        with self.covered_lock:
            self.covered[key] = max(self.covered.get(key, 0), generation)

    def saved(self, project):
        """A save went through: the copies it covers go, later changes will get new ones."""
        through = project.recovery_generation
        tracked = self._track(project)
        tracked.captured, tracked.since = project.revision, None
        self._cover(project.recovery_key, through)
        if through:
            self.queue.submit(self._safely, self.store.discard, project.recovery_key, through_generation=through)

    def forget(self, project):
        """The project left its tab (Discard, closed after a save, the window closed, a tab reused): all its
        copies go, and nothing queued may write them again."""
        key = project.recovery_key
        self._cover(key, math.inf)
        self.tracked.pop(key, None)
        self.queue.submit(self._safely, self.store.discard, key)

    @staticmethod
    def _safely(call, *args, **options):
        try:
            call(*args, **options)
        except (OSError, ValueError):
            pass  # A copy that cannot be deleted now is swept or offered later; it never blocks closing.

    def shutdown(self, projects=()):
        """The window closes normally: every project was saved or discarded."""
        for project in projects:
            self.forget(project)
        self.timer.stop()
        self.heartbeat.stop()
        self.closed = True
        self.queue.shutdown(wait=True)
        self.leases.release(self.owner)

    def _renew(self):
        try:
            self.leases.hold(self.owner)
        except OSError:
            pass  # The writes report the folder problem; the lease is retried at the next heartbeat.

    # -- copies to offer ---------------------------------------------------------------------------------------
    def offered(self):
        """``(snapshots, problems, others)``: copies left by windows that are gone (or taken by this window but not
        open in a tab), the damaged ones among them, and how many belong to another window still running."""
        open_keys = {session.project.recovery_key for session in self.window.sessions} if self.window else set()
        snapshots, problems = self.store.scan()
        mine, others = [], 0
        for record in snapshots:
            owner = record.get("owner")
            if record["session_key"] in open_keys:
                continue
            if owner == self.owner or not self.leases.alive(owner):
                mine.append(record)
            else:
                others += 1
        damaged = [problem for problem in problems if problem["session_key"] not in open_keys
                   and (problem.get("owner") in (None, self.owner) or not self.leases.alive(problem.get("owner")))]
        return mine, damaged, others

    def _startup_scan(self):
        try:
            self.leases.sweep()
            self.store.sweep(alive=self.leases.alive)
            found = self.offered()
        except OSError:
            return
        if not self.closed:
            self.scanned.emit(found)

    def _on_scanned(self, found):
        if self.closed or self.window is None:
            return  # The window closed before the scan came back.
        snapshots, problems, _others = found
        count = len(snapshots) + len(problems)
        if count and self.window is not None:
            self.show_notice(count)

    def show_notice(self, count):
        self.hide_notice()
        frame = QFrame()
        frame.setObjectName("recoveryNotice")
        row = QHBoxLayout(frame)
        row.setContentsMargins(12, 6, 12, 0)
        label = QLabel(r("notice", count=count) if count > 1 else r("notice_one"))
        label.setObjectName("notice")
        label.setWordWrap(True)
        row.addWidget(label, 1)
        recover = QPushButton(r("notice_open"))
        recover.setObjectName("primary")
        recover.clicked.connect(lambda: self.window.recover_projects())
        row.addWidget(recover)
        later = QPushButton(r("later"))
        later.clicked.connect(self.hide_notice)
        row.addWidget(later)
        self.notice = frame
        self.window.centralWidget().layout().insertWidget(2, frame)  # Under the tabs and the command bar.

    def hide_notice(self):
        if self.notice is not None:
            self.notice.hide()
            self.notice.deleteLater()
            self.notice = None

    # -- recovering --------------------------------------------------------------------------------------------
    def load(self, record, number):
        """Take the copy (``claim``) and read it into a new ``Project`` marked as changed and never saved."""
        from .project import Project
        key = record["session_key"]
        if record.get("owner") != self.owner:
            self.store.claim(key, expected_owner=record.get("owner"))
        data = self.store.read_snapshot(key)
        handle, name = tempfile.mkstemp(prefix=f".tmp-{self.owner}-open-", suffix=".alab", dir=self.root)
        try:
            with os.fdopen(handle, "wb") as stream:
                stream.write(data)
            project = Project(number)
            project.load(name)
        finally:
            try:
                os.unlink(name)
            except OSError:
                pass
        project.path = None
        project.recovery_key = key
        project.recovery_generation = record["generation"]
        project.recovered_from = record.get("source")
        project.recovery_base_title = record["title"]
        project.recovered_title = r("recovered_title", title=record["title"])
        source = record.get("source")
        stem = Path(source).stem if source else Path(record["title"]).stem
        folder = Path(source).parent if source else None
        project.save_suggestion = str(folder / r("recovered_file", stem=stem)) if folder else r(
            "recovered_file", stem=stem)
        project.source_stamp = record.get("source_stamp")
        project.dirty = True  # Protected until it is saved or discarded explicitly.
        tracked = self._track(project)
        tracked.captured = project.revision  # The copy on disk already holds this state.
        return project

    def recover(self, records):
        """Open ``records`` in tabs while there is room; the rest stay on disk, untouched. Returns how many opened."""
        window = self.window
        self.hide_notice()  # The user is dealing with the copies now.
        opened, errors = 0, []
        for position, record in enumerate(records):
            if not window.room_for_project():
                window.status(r("no_room", count=len(records) - position))
                break
            try:
                project = self.load(record, window.project_number + 1)
            except (OSError, ValueError, RecoveryBusy, RecoveryDamaged, KeyError) as error:
                errors.append(r("recover_failed", title=record["title"], error=error))
                continue
            if not window.place_project(project):
                break
            opened += 1
        else:
            if opened:
                window.status(r("recovered_status", count=opened))
        if errors:
            window.error("\n".join(errors))
        return opened

    def discard_keys(self, keys):
        for key in keys:
            self.store.discard(key)


class RecoveryDialog(QDialog):
    """File → Recover projects…: the copies, their originals, Recover, Delete (with a question) and Later."""

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.chosen = []
        self.setWindowTitle(r("title"))
        self.setObjectName("recoveryDialog")
        layout = QVBoxLayout(self)
        intro = QLabel(r("intro"))
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.list = QTreeWidget()
        self.list.setObjectName("recoveryList")
        self.list.setRootIsDecorated(False)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.setHeaderLabels([r("column.project"), r("column.written"), r("column.state"), r("column.source")])
        self.list.setTextElideMode(Qt.TextElideMode.ElideMiddle)  # Long paths keep their start and file name.
        self.list.setAccessibleName(r("title"))
        self.list.itemSelectionChanged.connect(self._selection_changed)
        self.list.itemDoubleClicked.connect(lambda *_: self.accept())
        layout.addWidget(self.list, 1)
        self.warning = QLabel("")
        self.warning.setObjectName("notice")
        self.warning.setWordWrap(True)
        layout.addWidget(self.warning)
        self.damaged = QLabel("")
        self.damaged.setObjectName("errorBanner")
        self.damaged.setWordWrap(True)
        layout.addWidget(self.damaged)
        self.usage = QLabel("")
        self.usage.setObjectName("muted")
        self.usage.setWordWrap(True)
        layout.addWidget(self.usage)
        buttons = QHBoxLayout()
        self.delete_button = QPushButton(r("delete_button"))
        self.delete_button.clicked.connect(self.delete_selected)
        buttons.addWidget(self.delete_button)
        self.delete_damaged_button = QPushButton(r("delete_damaged"))
        self.delete_damaged_button.clicked.connect(self.delete_damaged)
        buttons.addWidget(self.delete_damaged_button)
        buttons.addStretch(1)
        self.later_button = QPushButton(r("later"))
        self.later_button.clicked.connect(self.reject)
        buttons.addWidget(self.later_button)
        self.recover_button = QPushButton(r("recover_button"))
        self.recover_button.setObjectName("primary")
        self.recover_button.setDefault(True)
        self.recover_button.clicked.connect(self.accept)
        buttons.addWidget(self.recover_button)
        layout.addLayout(buttons)
        self.fill()
        theme.fit_dialog(self, 760, 440)

    def fill(self):
        self.records, self.problems, others = self.controller.offered()
        self.list.clear()
        for record in self.records:
            state = original_state(record.get("source"), record.get("source_stamp"))
            item = QTreeWidgetItem([record["title"], local_time(record["written"], date=True), r(f"state.{state}"),
                                    record.get("source") or r("no_source")])
            item.setData(0, Qt.ItemDataRole.UserRole, record["session_key"])
            item.setData(2, Qt.ItemDataRole.UserRole, state)
            item.setToolTip(0, record["title"])
            item.setToolTip(3, record.get("source") or "")
            self.list.addTopLevelItem(item)
        for column in range(3):
            self.list.resizeColumnToContents(column)
        if self.records:
            self.list.topLevelItem(0).setSelected(True)
            self.list.setCurrentItem(self.list.topLevelItem(0))
        if self.problems:
            rows = [r("damaged_row", title=problem.get("title") or r("damaged_untitled"),
                      reason=r(f"damage.{problem['code']}")) for problem in self.problems]
            self.damaged.setText(r("damaged", count=len(self.problems)) + "\n" + "\n".join(rows))
        self.damaged.setVisible(bool(self.problems))
        self.delete_damaged_button.setVisible(bool(self.problems))
        usage = self.controller.store.usage()
        size = f"{usage['bytes'] / MiB:.1f}"
        if active_language() == "it":
            size = size.replace(".", ",")
        lines = [r("usage", copies=usage["copies"], size=size, total=MAX_TOTAL_BYTES // MiB, limit=MAX_COPIES,
                   each=MAX_SNAPSHOT_BYTES // MiB)]
        if not self.records and not self.problems:
            lines.insert(0, r("none"))
        if others:
            lines.append(r("other_window", count=others))
        if self.controller.suspended:
            lines.append(self.controller.suspended)
        self.usage.setText("\n".join(lines))
        self._selection_changed()

    def selected_records(self):
        keys = [item.data(0, Qt.ItemDataRole.UserRole) for item in self.list.selectedItems()]
        return [record for record in self.records if record["session_key"] in keys]

    def _selection_changed(self):
        chosen = self.selected_records()
        changed = [record["title"] for record in chosen
                   if original_state(record.get("source"), record.get("source_stamp")) == "changed"]
        missing = [record["title"] for record in chosen
                   if original_state(record.get("source"), record.get("source_stamp")) == "missing"]
        text = []
        if changed:
            text.append(r("changed_warning", names=", ".join(changed)))
        if missing:
            text.append(r("missing_warning", names=", ".join(missing)))
        self.warning.setText("\n".join(text))
        self.warning.setVisible(bool(text))
        self.recover_button.setEnabled(bool(chosen))
        self.delete_button.setEnabled(bool(chosen))

    def _confirm_delete(self, count):
        answer = QMessageBox.question(self, r("delete_title"), r("delete_question", count=count),
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                      QMessageBox.StandardButton.No)
        return answer == QMessageBox.StandardButton.Yes

    def delete_selected(self):
        chosen = self.selected_records()
        if chosen and self._confirm_delete(len(chosen)):
            self.controller.discard_keys([record["session_key"] for record in chosen])
            self.fill()

    def delete_damaged(self):
        if self.problems and self._confirm_delete(len(self.problems)):
            self.controller.discard_keys([problem["session_key"] for problem in self.problems])
            self.fill()

    def accept(self):
        self.chosen = self.selected_records()
        if self.chosen:
            super().accept()


class RecoverySettingsDialog(QDialog):
    """The preference: on or off, and the interval (15, 30, 60 or 120 seconds)."""

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.setWindowTitle(r("settings_title"))
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)
        self.enabled = QCheckBox(r("enabled"))
        self.enabled.setChecked(controller.enabled)
        layout.addWidget(self.enabled)
        row = QHBoxLayout()
        caption = QLabel(r("every"))
        row.addWidget(caption)
        self.interval = QComboBox()
        self.interval.setAccessibleName(r("every"))
        for seconds in INTERVALS:
            self.interval.addItem(r("seconds", count=seconds), seconds)
        self.interval.setCurrentIndex(max(0, self.interval.findData(controller.interval)))
        caption.setBuddy(self.interval)
        row.addWidget(self.interval, 1)
        layout.addLayout(row)
        self.enabled.toggled.connect(self.interval.setEnabled)
        self.interval.setEnabled(controller.enabled)
        note = QLabel(r("settings_note", folder=controller.root, copies=MAX_COPIES, each=MAX_SNAPSHOT_BYTES // MiB,
                        total=MAX_TOTAL_BYTES // MiB))
        note.setWordWrap(True)
        note.setObjectName("muted")
        note.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self):
        enabled, interval = self.enabled.isChecked(), self.interval.currentData()
        if self.controller.settings_path is not None:
            try:
                save_settings(self.controller.settings_path, enabled, interval)
            except (OSError, ValueError) as error:
                QMessageBox.critical(self, self.windowTitle(), r("settings_error", error=error))
                return
        self.controller.configure(enabled, interval)
        super().accept()

