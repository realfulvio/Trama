"""Refresh linked artwork for the visible layout, using that project's worker."""
from dataclasses import dataclass
import os
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from .layout_transfer import linked_run, prepare_preview, read_source
from .project import CalculationControl, PROJECT_SUFFIXES
from .strings import qt


@dataclass(frozen=True)
class LinkedGraphView:
    stamp: object = None
    figure: object = None
    error: str = ""


def _file_stamp(path):
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns


def _local_file(path):
    if not path.is_absolute() or path.suffix.lower() not in PROJECT_SUFFIXES:
        return False
    if os.name == "nt":
        from ctypes import windll

        # A saved project can name an SMB location. Contact it only after it has been selected or refreshed.
        return not path.drive.startswith(chr(92) * 2) and windll.kernel32.GetDriveTypeW(str(path.anchor)) != 4
    return not str(path).startswith("//")


def _refresh(requests, control):
    result, sources = {}, {}
    for link, snapshot, stamp, old, permitted, force in requests:
        if control.cancel.is_set():
            return {}
        path = Path(link.path)
        try:
            if stamp is None:
                if not permitted and not _local_file(path):
                    result[link] = LinkedGraphView(("manual",), old.figure, qt("qt.layout_link_manual"))
                    continue
                stamp = ("file", *_file_stamp(path))
            if not force and stamp == old.stamp:
                continue
            key = path, stamp
            if key not in sources:
                sources[key], _ = read_source(path, snapshot)
            source = sources[key]
            figure = prepare_preview(source, linked_run(source, link), control)
            if snapshot is None and _file_stamp(path) != stamp[1:]:
                continue
            result[link] = LinkedGraphView(stamp, figure)
        except FileNotFoundError:
            result[link] = LinkedGraphView(("missing",), old.figure, qt("qt.layout_link_missing"))
        except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
            result[link] = LinkedGraphView(stamp, old.figure, str(error)[:160])
    return result


class LiveLayoutGraphs:
    def __init__(self, window):
        self.window = window
        self.timer = QTimer(window, interval=1250)
        self.timer.timeout.connect(self.tick)
        self.timer.start()
        self.pending = None
        self.permitted = set()
        self.force = None
        self.paint = None

    def allow(self, link):
        self.permitted.add(link.path)

    def request(self):
        self.force = (self.window.project, self.window.selected)
        self.tick()

    def tick(self):
        window = self.window
        if (window.job is not None or not window.isVisible() or QApplication.activeModalWidget() is not None):
            return
        completed = self.pending is not None
        if completed:
            future, project = self.pending
            if not future.done():
                return
            self.pending = None
            self.timer.setInterval(1250)
            try:
                changed = project.set_linked_graph_views(future.result())
            except Exception:
                changed = False
            if changed:
                self.paint = project

        ref = window.selected
        if not ref or ref[0] != "layout" or window.gallery is not None:
            return
        project, index = window.project, ref[1]
        layout = project.layouts[index]
        if not layout.graph_links:
            return
        if self.paint is project:
            controller = window._active_layout_selection()
            if (controller is not None and controller.pending is not None) or window.table_move.active:
                return
            selection = tuple(controller.selected) if controller is not None else ()
            window.show_sheet(*ref)
            current = window._active_layout_selection()
            if current is not None and selection:
                current.select(selection)
            self.paint = None
        force = self.force == (project, ref)
        if self.force is not None:
            self.force = None
        if completed and not force:
            return

        sources = {}
        for session in window.sessions:
            if session.project is not project:
                for path in session.paths():
                    sources[os.path.normcase(os.path.abspath(path))] = session.project
        requests, snapshots = [], {}
        for link in dict(layout.graph_links).values():
            old = project.linked_graph_views.get(link, LinkedGraphView())
            source = sources.get(os.path.normcase(link.path))
            if force:
                self.allow(link)
            if source is None:
                requests.append((link, None, None, old, link.path in self.permitted, force))
                continue
            stamp = "open", id(source), source.revision
            if not force and old.stamp == stamp:
                continue
            if source not in snapshots:
                snapshots[source] = source.snapshot()
            requests.append((link, snapshots[source], stamp, old, True, force))
        if requests:
            self.pending = (window.worker.submit(_refresh, requests, CalculationControl()), project)
            self.timer.setInterval(100)
