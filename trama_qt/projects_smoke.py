"""Smoke of the project tabs, run by ``python -m trama_qt --smoke FOLDER`` after the window commands.

Two real projects with the same sheet name, each with a graph and a layout, are built through the window, saved,
and worked in side by side: tabs switched with the mouse and with the keyboard, the right cell and sheet kept,
only the project that was saved written, a closed project opened again, a CSV imported into the active tab, a
project opened the way the command line does, a handled open error, and the cost of switching a 10 000 × 30 sheet.
Screenshots ``<lang>-projects-*.png`` and ``projects-switch.txt`` (times and memory) go to the smoke folder.
"""
from hashlib import sha256
from pathlib import Path
from statistics import median
import time
import tracemalloc
from unittest import mock

import numpy as np
import pandas as pd
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def settle(app):
    """Events, then the deletions the event loop of the real application would run on its own."""
    app.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def run(smoke, window):
    """Raises nothing for a deviation: each one becomes a problem in the smoke report."""
    folder = smoke.folder / f"projects-{smoke.language}"
    folder.mkdir(exist_ok=True)
    window.project.dirty = False
    while len(window.sessions) > 1:  # Start from one empty tab, whatever the earlier steps left.
        window.sessions[len(window.sessions) - 1].project.dirty = False
        window.switch_project(window.sessions[len(window.sessions) - 1])
        window.close_project()
    window.close_project()
    tabs = window.project_tabs

    def check(ok, text):
        if not ok:
            smoke.problem(f"projects: {text}")

    def build(name, offset):
        """One project: the data, an XY graph and a layout with it, saved as ``sessione-<name>.alab``."""
        data_folder = folder / name
        data_folder.mkdir(exist_ok=True)
        frame = pd.DataFrame({"Tempo": [1, 2, 3, 4, 5], "Risposta": [value + offset for value in (3, 7, 6, 11, 13)],
                              "Controllo": [value + offset for value in (2, 4, 7, 8, 9)]})
        csv = data_folder / "Misure.csv"
        frame.to_csv(csv, index=False)
        window.open_path(csv)
        smoke.wait()
        window.open_sheet(("data", "Misure"))
        index = _calculate(smoke, "XY series", {"X": "Tempo", "Y columns": ["Risposta"]})
        from analisi.layout_geometry import AUTO_PAPER, WHITE
        from analisi.presentation import Layout
        graph = window.project.runs[index]
        window.project.put_layout(Layout(f"Figura {name.upper()}", 1, [graph.reference], AUTO_PAPER, WHITE))
        path = data_folder / f"sessione-{name}.alab"
        window.project.save(path)
        window.refresh()
        return path, index

    path_a, graph_a = build("a", 0)
    window.new_project()
    path_b, graph_b = build("b", 100)
    check(len(window.sessions) == 2 and tabs.count() == 2, f"expected two tabs, found {tabs.count()}")
    check(window.project.tables["Misure"].raw.iloc[0, 1] == 103, "tab B does not hold B's data")
    window.open_sheet(("graph", graph_b))
    smoke.wait()
    smoke.shot(window, "projects-two-tabs")

    def click(position):
        QTest.mouseClick(tabs, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                         tabs.tabRect(position).center())
        smoke.app.processEvents()

    def key(code, modifiers):
        window.activateWindow()  # Shortcuts reach the active window only.
        smoke.app.processEvents()
        QTest.keyClick(window, code, modifiers)
        smoke.app.processEvents()

    def active():
        return window.sessions.index(window.sessions.active)

    # Mouse and keyboard switching keep each tab's sheet, cell and project.
    click(0)
    check(active() == 0, "mouse click did not switch to the first tab")
    window.open_sheet(("data", "Misure"))
    window.sheet.setCurrentIndex(window.sheet.model().index(3, 2))
    first = window.project
    key(Qt.Key.Key_Tab, Qt.KeyboardModifier.ControlModifier)
    check(active() == 1 and window.selected == ("graph", graph_b),
          f"Ctrl+Tab: expected B's graph, found tab {active()} on {window.selected}")
    key(Qt.Key.Key_Backtab, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
    cell = window.sheet.currentIndex() if window.sheet is not None else None
    check(window.project is first and window.selected == ("data", "Misure") and cell is not None
          and (cell.row(), cell.column()) == (3, 2), "Ctrl+Shift+Tab did not bring back A's sheet and cell")

    # An edit in each tab; saving A writes only A.
    before_b = digest(path_b)
    for position, value in ((0, "42"), (1, "142")):
        click(position)
        window.open_sheet(("data", "Misure"))
        model = window.sheet.model()
        model.setData(model.index(0, 1), value)
        smoke.app.processEvents()
        smoke.wait()
    smoke.shot(window, "projects-dirty")
    check(all(tabs.tabText(i).startswith("•") for i in range(2)), "dirty marker missing on a tab")
    click(0)
    check(window.save(), "saving A failed")
    check(digest(path_b) == before_b, "saving A changed B's file")
    check(not window.project.dirty and window.sessions[1].project.dirty, "dirty flags after saving A are wrong")
    check(not tabs.tabText(0).startswith("•") and tabs.tabText(1).startswith("•"), "dirty marker after saving A")

    # B closed without saving, then opened again: the file's data, in a tab of its own.
    click(1)
    with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
        window.actions["close_project"].trigger()
    check(tabs.count() == 1, "closing B left more than one tab")
    window.open_path(path_b)
    smoke.wait()
    check(tabs.count() == 2 and window.project.tables["Misure"].raw.iloc[0, 1] == 103,
          "reopened B does not show the file's data")
    window.open_path(path_a)  # Already open: shown, not duplicated.
    check(tabs.count() == 2 and window.project is window.sessions[0].project, "opening A again did not show its tab")

    # A CSV import goes to the active tab only.
    extra = folder / "aggiunta.csv"
    pd.DataFrame({"P": [1.0, 2.0], "Q": [3.0, 4.0]}).to_csv(extra, index=False)
    window.open_path(extra)
    smoke.wait()
    check("aggiunta" in window.project.tables and "aggiunta" not in window.sessions[1].project.tables,
          "CSV import went to the wrong tab")

    # The command line: the file argument opens in the empty tab of a fresh window.
    for session in window.sessions:
        session.project.dirty = False
    while len(window.sessions) > 1:
        window.close_project()
    window.close_project()
    from .app import _file_argument
    argument = _file_argument(["trama", str(path_b)])
    check(argument == str(path_b), "command line did not name the project")
    window.open_path(argument)
    smoke.wait()
    check(tabs.count() == 1 and window.project.path == path_b, "command-line project not opened in the first tab")

    # A file that cannot be opened: a message, no new tab, nothing lost.
    broken = folder / "rotto.alab"
    broken.write_text("{ non è un progetto", encoding="utf-8")
    shown = []

    def show_error(error):
        box = QMessageBox(QMessageBox.Icon.Warning, "Trama", str(error), parent=window)
        box.show()
        smoke.app.processEvents()
        smoke.shot(box, "projects-open-error")
        shown.append(str(error))
        box.close()
        box.deleteLater()

    original, window.error = window.error, show_error
    try:
        window.open_path(broken)
    finally:
        window.error = original
    check(len(shown) == 1 and tabs.count() == 1 and window.project.path == path_b,
          "an invalid file changed the tabs or showed no message")
    window.project.dirty = False
    switch_cost(smoke, window)


def _calculate(smoke, method, options):
    """A calculation on the current table, as the smoke does it; returns the run index."""
    from .analysis_dialog import AnalysisDialog
    window = smoke.window
    title = window.selected[1]
    frame = window.project.tables[title].frame(mask_excluded=True)
    dialog = AnalysisDialog(window, frame, current=(method, {}))
    for name, value in options.items():
        control = dialog.controls[name][1]
        if isinstance(value, list) and hasattr(control, "item"):
            for row in range(control.count()):
                item = control.item(row)
                item.setCheckState(Qt.CheckState.Checked if item.text() in value else Qt.CheckState.Unchecked)
    values = dialog.options()
    dialog.deleteLater()
    values.update(options)
    candidate = window.project.candidate(title, method, values)
    window.calculate_candidate(candidate, frame, None)
    smoke.wait()
    return len(window.project.runs) - 1


def switch_cost(smoke, window, rows=10_000, columns=30, switches=40):
    """Time and memory of switching between a 10 000 × 30 project and a small one. The tabs hold their projects;
    a switch rebuilds the sheet view only, so memory stays flat across switches and the dataset is the same
    object. Appended to ``projects-switch.txt``."""
    big_frame = pd.DataFrame(np.random.default_rng(1).normal(size=(rows, columns)),
                             columns=[f"V{index + 1}" for index in range(columns)])
    window.new_project()
    big = window.sessions.active
    window.project.add_tables({"Grande": big_frame})
    window.project.dirty = False
    window.show_sheet("data", "Grande")
    window.new_project()
    small = window.sessions.active
    window.project.add_tables({"Piccola": pd.DataFrame({"A": [1.0, 2.0], "B": [3.0, 4.0]})})
    window.project.dirty = False
    window.show_sheet("data", "Piccola")
    raw = big.project.tables["Grande"].raw
    for _ in range(3):  # Warm-up: fonts, styles, first view.
        window.switch_project(big)
        window.switch_project(small)
    times, peaks = [], []
    tracemalloc.start()
    baseline = tracemalloc.get_traced_memory()[0]
    for _ in range(switches):
        tracemalloc.reset_peak()
        started = time.perf_counter()
        window.switch_project(big)
        smoke.app.processEvents()
        times.append(time.perf_counter() - started)
        peaks.append(tracemalloc.get_traced_memory()[1])
        window.switch_project(small)
        settle(smoke.app)
    after = tracemalloc.get_traced_memory()[0]
    tracemalloc.stop()
    size = raw.memory_usage(deep=True).sum()
    same = big.project.tables["Grande"].raw is raw
    lines = [f"language {smoke.language}",
             f"sheet {rows} x {columns} ({size / 1e6:.1f} MB of data), {switches} switches to it and back",
             f"switch to the big sheet: median {median(times) * 1000:.0f} ms, "
             f"max {max(times) * 1000:.0f} ms, min {min(times) * 1000:.0f} ms",
             f"python memory after the switches: {(after - baseline) / 1e6:+.2f} MB against the start",
             f"peak during a switch: {(max(peaks) - baseline) / 1e6:.1f} MB above the start "
             f"(a copy of the data would be {size / 1e6:.1f} MB)",
             f"dataset is the same object after the switches: {same}"]
    path = smoke.folder / "projects-switch.txt"
    previous = path.read_text(encoding="utf-8") if path.exists() else ""
    path.write_text(previous + "\n".join(lines) + "\n\n", encoding="utf-8")
    if not same:
        smoke.problem("projects: a tab switch replaced the dataset")
    if after - baseline > 2e6:
        smoke.problem(f"projects: memory grew {(after - baseline) / 1e6:.1f} MB over {switches} tab switches")
    for session in (small, big):
        session.project.dirty = False
    window.close_project()
    window.close_project()
