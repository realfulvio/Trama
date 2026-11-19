"""K-means stability on the real Qt window: ``python -m trama_qt.kmeans_stability_smoke FOLDER [--dark]``.

The conventions of ``python -m trama_qt --smoke`` (``trama_qt/smoke.py``): the real screen, preferences in a
temporary folder, synthetic data only, English then Italian. In each language it opens the synthetic project
``tests/data/kmeans_stability/stabilita-kmeans.alab``, presses Analyze and, in the same dialog, corrects an invalid
range of k, shows the Hartigan–Wong iteration limit, has a budget refused before any worker starts and then runs
with the co-assignment matrix. It records the dialog and the result pages, puts the figure in a layout, exports,
saves the project, edits and excludes a cell (automatic recalculation) and cancels a heavy change of options.

Writes into FOLDER:

- ``<lang>-dialog.png``, ``-dialog-k-range``, ``-dialog-hartigan``, ``-dialog-budget``, ``-page-graph``,
  ``-page-summary``, ``-page-assignment``, ``-page-coassignment``, ``-layout`` (PNG as drawn at this scale);
- in the first language only: ``stability.png/.svg/.pdf``, ``layout.png/.svg/.pdf``, ``assignment-stability.csv``,
  ``co-assignment.csv`` and ``stabilita-kmeans.alab``;
- ``report.txt`` (screen, scale, theme, timings, checks, problems) and ``status.txt`` (PASS or FAIL).

Exit code 0 on PASS, 1 on FAIL. On Linux an emulated screen is ``QT_QPA_PLATFORM="offscreen:configfile=..."``
(see ``docs/qt-migration.md``).
"""
import os
from pathlib import Path
import re
import sys
import tempfile
import time
import traceback
from unittest import mock

os.environ.setdefault("MPLBACKEND", "QtAgg")  # before pyplot can be imported anywhere

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from PySide6 import __version__ as PYSIDE_VERSION  # noqa: E402
from PySide6.QtCore import QRect, Qt  # noqa: E402
from PySide6.QtWidgets import QDialog, QFileDialog  # noqa: E402

from analisi import kmeans_stability as ks  # noqa: E402

from .smoke import LANGUAGES, Smoke  # noqa: E402

FIXTURE = Path(__file__).resolve().parent.parent / "tests" / "data" / "kmeans_stability" / "stabilita-kmeans.alab"
TITLE = "Tre gruppi $ sintetici"
RUN = {"Minimum k": 2, "Maximum k": 4, "Resamples": 30, "Seed": 7, "Sample fraction (%)": "82,5", "Report k": 3,
       "Show co-assignment matrix": True}
HEAVY = {"Resamples": 1500, "Seed runs": 0, "Show co-assignment matrix": False}
LIMIT = "Hartigan–Wong iteration limit"


def fill(dialog, values):
    """Set the controls of the dialog the way a user would type, tick or choose."""
    for name, value in values.items():
        kind, control = dialog.controls[name]
        if isinstance(value, bool):
            control.setChecked(value)
        elif isinstance(value, list):
            for row in range(control.count()):
                item = control.item(row)
                item.setCheckState(Qt.CheckState.Checked if item.text() in value else Qt.CheckState.Unchecked)
        elif hasattr(control, "findData"):
            control.setCurrentIndex(control.findData(value))
        else:
            control.setText(str(value))


class StabilitySmoke(Smoke):
    def __init__(self, folder, dark=False):
        super().__init__(folder)
        self.dark = dark
        self.notes = []

    def note(self, text):
        self.notes.append(f"[{self.language}] {text}")

    def expect(self, condition, text):
        if not condition:
            self.problem(text)
        return bool(condition)

    def ask(self, command, script):
        """Run a window command; the analysis dialog it opens runs ``script`` instead of waiting for clicks."""
        from .analysis_dialog import AnalysisDialog
        seen = []

        def exec_(dialog):
            seen.append(dialog)
            dialog.show()
            self.app.processEvents()
            accepted = script(dialog)
            return QDialog.DialogCode.Accepted if accepted and dialog.result else QDialog.DialogCode.Rejected

        with mock.patch.object(AnalysisDialog, "exec", exec_):
            command()
        self.expect(seen, "the analysis dialog did not open")

    def save_as(self, command, path):
        with mock.patch.object(QFileDialog, "getSaveFileName", return_value=(str(path), "")):
            command()
        self.expect(path.exists() and path.stat().st_size > 0, f"{path.name} was not written")

    # -- the dialog --------------------------------------------------------------------------------------
    def first_dialog(self, dialog):
        window = self.window
        if dialog.method != ks.METHOD:  # search the catalog the way a user would
            from .labels import method_label
            dialog.query.setText(method_label(ks.METHOD))
            items = [dialog.methods.topLevelItem(group).child(row)
                     for group in range(dialog.methods.topLevelItemCount())
                     for row in range(dialog.methods.topLevelItem(group).childCount())]
            dialog._picked(next(item for item in items if item.data(0, Qt.ItemDataRole.UserRole) == ks.METHOD))
        self.shot(dialog, "dialog")

        fill(dialog, {"Minimum k": 4, "Maximum k": 3})
        dialog.accept()
        self.expect(dialog.result is None and dialog.banner.isVisible(), "an invalid range of k was accepted")
        self.expect(self.app.focusWidget() is dialog.controls["Maximum k"][1], "Maximum k is not focused")
        self.shot(dialog, "dialog-k-range")

        fill(dialog, {"Minimum k": 2, "Maximum k": 4, "K-means algorithm": "Hartigan–Wong"})
        _caption, limit, form = dialog.rows[LIMIT]
        self.expect(form.isRowVisible(limit), "the Hartigan–Wong iteration limit is hidden with Hartigan–Wong")
        dialog.focus_field(LIMIT)
        self.shot(dialog, "dialog-hartigan")
        fill(dialog, {"K-means algorithm": "Lloyd"})
        self.expect(not form.isRowVisible(limit), "the Hartigan–Wong iteration limit is shown with Lloyd")

        fill(dialog, {"Resamples": 2000})  # 3 values of k × 2001 fits is beyond the limit of 6000
        with mock.patch.object(ks.engine, "kmeans", side_effect=AssertionError("a K-means fit in the dialog")):
            dialog.accept()
        self.expect(dialog.result is None and window.job is None, "a budget beyond the limit reached the worker")
        self.expect(str(ks.MAX_FITS) in dialog.banner.text(), f"budget message: {dialog.banner.text()!r}")
        self.shot(dialog, "dialog-budget")
        self.note(f"budget refused in the dialog: {dialog.banner.text()}")

        fill(dialog, RUN)
        dialog.accept()
        self.expect(dialog.result is not None, f"the corrected dialog was refused: {dialog.banner.text()!r}")
        return True

    # -- the run -----------------------------------------------------------------------------------------
    def run_language(self, language):
        from analisi.i18n import set_language
        from analisi.layout_geometry import AUTO_PAPER, WHITE
        from analisi.presentation import Layout
        from . import theme
        from .window import MainWindow
        self.language = language
        set_language(language)
        theme.install_qt_translations(self.app, language)
        first = language == LANGUAGES[0]
        self.window = window = MainWindow()
        window.error = lambda error: self.problem(f"error shown: {error}")
        available = self.screen_rect(window)
        window.resize(min(1280, available.width()), min(800, available.height()))
        window.show()
        theme.keep_on_screen(window)
        self.app.processEvents()
        try:
            project = self.folder / f"{language}-input.alab"
            project.write_bytes(FIXTURE.read_bytes())
            window.open_path(project)
            self.wait()
            self.expect(window.selected == ("data", TITLE), f"fixture not opened: {window.selected}")

            started = time.perf_counter()
            self.ask(window.actions["analyze"].trigger, self.first_dialog)
            self.wait()
            self.note(f"first calculation (20 rows, k 2–4, 30 resamples): {time.perf_counter() - started:.2f} s")
            run = window.project.runs[-1]
            index = window.project.runs.index(run)
            self.expect(run.calculation_error is None and run.result is not None,
                        f"not calculated: {run.calculation_error}")
            self.expect(run.options["Sample fraction (%)"] == 82.5, "the decimal comma was not read as 82.5")
            self.expect(LIMIT not in run.options, "Lloyd stored the Hartigan–Wong iteration limit")
            self.expect(window.selected == ("graph", index), "the figure did not open first")
            self.shot(window, "page-graph")
            self.check_tables(run)

            window.open_sheet(("result", index))
            for name, shot in (("Stability summary", "page-summary"), ("Assignment stability", "page-assignment"),
                               ("Co-assignment", "page-coassignment")):
                window.result_tabs.setCurrentIndex(list(run.result.tables).index(name))
                self.shot(window, shot)
                if first and name != "Stability summary":
                    self.save_as(window.export, self.folder / f"{name.lower().replace(' ', '-')}.csv")

            window.open_sheet(("graph", index))
            if first:
                for suffix in ("png", "svg", "pdf"):
                    self.save_as(window.export, self.folder / f"stability.{suffix}")
                self.check_svg(self.folder / "stability.svg")
            key = window.project.put_layout(Layout("Stability", 1, [run.reference], AUTO_PAPER, WHITE))
            window.refresh()
            window.open_sheet(("layout", key))
            self.wait()
            self.shot(window, "layout")
            if first:
                for suffix in ("png", "svg", "pdf"):
                    self.save_as(window.export, self.folder / f"layout.{suffix}")
                window.project.save(self.folder / "stabilita-kmeans.alab")

            self.recalculate(run)
            self.cancel(index)
        except Exception:  # noqa: BLE001 - the report must say what broke, then the next language runs.
            self.problem("stopped:\n" + traceback.format_exc())
        finally:
            window.project.dirty = False
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def check_tables(self, run):
        tables = run.result.tables
        rows = [row for row in range(1, 21) if row not in {6, 15}]
        assignments = tables["Assignment stability"]
        self.expect(list(assignments.index) == rows, "Assignment stability lost the worksheet order")
        matrix = tables["Co-assignment"].to_numpy(dtype=float)
        self.expect(matrix.shape == (18, 18), f"co-assignment shape {matrix.shape}")
        self.expect(np.array_equal(matrix, matrix.T), "co-assignment is not symmetric")
        self.expect(np.all(np.diag(matrix) == 1.0), "co-assignment diagonal is not 1")
        self.expect(np.all((matrix >= 0) & (matrix <= 1)), "co-assignment outside 0–1")
        self.expect(list(tables["Co-assignment"].index) == rows, "co-assignment rows are not in worksheet order")
        summary = tables["Stability summary"]
        self.note("Stability summary, median ARI by k: "
                  + ", ".join(f"k={k}: {value:.4f}" for k, value in summary["Median ARI"].items()))

    def check_svg(self, path):
        text = path.read_text(encoding="utf-8")
        size = re.search(r'<svg[^>]*width="([^"]+)"[^>]*height="([^"]+)"', text)
        paths, texts, images = text.count("<path"), text.count("<text"), text.count("<image")
        self.expect(paths > 0, "the SVG has no vector paths")
        self.note(f"stability.svg: page {size.group(1)} × {size.group(2)}, {paths} paths, {texts} text elements "
                  f"(text drawn as glyph paths when 0), {images} raster images (the co-assignment heat map)"
                  if size else "stability.svg: no page size")

    def recalculate(self, run):
        window = self.window
        window.open_sheet(("data", TITLE))
        window.edit_cell(TITLE, 5, 0, "-100")  # completes row 6
        self.wait()
        run = window.project.runs[0]
        rows = list(run.result.tables["Assignment stability"].index)
        self.expect(run.calculation_error is None and 6 in rows and len(rows) == 19,
                    f"no recalculation after an edit: {run.calculation_error}")
        window.open_sheet(("data", TITLE))
        window.sheet.setCurrentIndex(window.sheet.model().index(0, 1))
        window.toggle_exclusion()
        self.wait()
        rows = list(window.project.runs[0].result.tables["Assignment stability"].index)
        self.expect(1 not in rows and 6 in rows, "an excluded value did not remove its row")
        self.note(f"after an edit and an exclusion: {len(rows)} rows")

    def cancel(self, index):
        window = self.window
        run = window.project.runs[index]
        options, result = dict(run.options), run.result
        window.open_sheet(("graph", index))
        self.wait()

        def heavy(dialog):
            fill(dialog, HEAVY)
            dialog.accept()
            return True

        self.ask(window.change_parameters, heavy)
        if not self.expect(window.job is not None, "the heavy change did not start"):
            return
        end = time.monotonic() + .5
        while time.monotonic() < end:
            self.app.processEvents()
            time.sleep(.01)
        done, total = window.job.control.progress()
        started = time.perf_counter()
        window.cancel_calculation()
        self.wait()
        latency = time.perf_counter() - started
        run = window.project.runs[index]
        self.expect(run.options == options and run.result is result, "cancelling changed the recipe or result")
        self.note(f"cancel after {done} of {total} fits: latency {latency:.3f} s, recipe and result kept")

    def report(self):
        screen = self.app.primaryScreen()
        geometry = screen.availableGeometry() if screen else QRect()
        lines = [f"Trama Qt · K-means stability smoke · PySide6 {PYSIDE_VERSION} · platform "
                 f"{self.app.platformName()} · theme {'dark' if self.dark else 'light'}",
                 f"Screen {screen.name() if screen else '?'}: available {geometry.width()}×{geometry.height()}, "
                 f"device pixel ratio {screen.devicePixelRatio() if screen else '?'}, "
                 f"logical DPI {screen.logicalDotsPerInch() if screen else '?'}",
                 f"Screenshots: {self.shots}", ""]
        lines += self.notes + [""]
        lines += self.problems or ["No problems found."]
        (self.folder / "report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        status = "FAIL" if self.problems else "PASS"
        (self.folder / "status.txt").write_text(status + "\n", encoding="utf-8")
        return status


def run(folder, languages=LANGUAGES, dark=False):
    """Run the acceptance in each language; returns "PASS" or "FAIL" (also written to ``status.txt``)."""
    from analisi.i18n import active_language, set_language
    from . import theme
    smoke = StabilitySmoke(folder, dark)
    previous = active_language()
    try:
        for language in languages:
            smoke.run_language(language)
    finally:
        set_language(previous)
        theme.install_qt_translations(smoke.app, previous)
    return smoke.report()


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    folders = [argument for argument in argv if not argument.startswith("--")]
    if len(folders) != 1:
        print("Usage: python -m trama_qt.kmeans_stability_smoke FOLDER [--dark]")
        return 2
    dark = "--dark" in argv
    with tempfile.TemporaryDirectory() as config, \
            mock.patch.dict(os.environ, {"APPDATA": config, "XDG_CONFIG_HOME": config}):
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtWidgets import QApplication
        QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
        app = QApplication.instance() or QApplication([sys.argv[0]])
        app.setApplicationName("Trama")
        import matplotlib
        matplotlib.use("QtAgg")
        from . import theme
        theme.load_fonts()
        theme.apply(app, dark=dark)
        status = run(folders[0], dark=dark)
    print(f"K-means stability smoke: {status} ({folders[0]})")
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
