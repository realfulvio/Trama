"""Bland–Altman for repeated pairs on the real Qt window:
``python -m trama_qt.bland_altman_repeated_smoke FOLDER [--dark]``.

Conventions of ``python -m trama_qt --smoke`` (``trama_qt/smoke.py``): the real screen, preferences in a temporary
folder, synthetic data only, English then Italian. In each language it opens ``tests/data/bland_altman_repeated/
glicemia ripetuta.csv`` (column names with spaces and symbols, one incomplete pair, one subject with a single pair),
finds the analysis in the catalog, has a wrong Occasion refused in the dialog before any worker starts, runs with the
subject bootstrap, records the dialog and every result page, switches to the subject diagnostics and to Log ratio,
edits a cell, excludes a cell and undoes (automatic recalculation), cancels a change and checks that the last
confirmed result comes back, then saves the project and reopens it in a new window.

Writes into FOLDER: ``<lang>-*.png`` (as drawn at this scale); in the first language also ``agreement.png/.svg/.pdf``,
``agreement-table.csv``, ``pairs.csv`` and ``bland-altman-ripetute.alab``; ``report.txt`` and ``status.txt``.
Exit code 0 on PASS, 1 on FAIL.
"""
import os
from pathlib import Path
import sys
import tempfile
import time
import traceback
from unittest import mock

os.environ.setdefault("MPLBACKEND", "QtAgg")  # before pyplot can be imported anywhere

import pandas as pd  # noqa: E402
from PySide6 import __version__ as PYSIDE_VERSION  # noqa: E402
from PySide6.QtCore import QRect, Qt  # noqa: E402
from PySide6.QtWidgets import QDialog, QFileDialog  # noqa: E402

from analisi import bland_altman_repeated as bar  # noqa: E402

from .smoke import LANGUAGES, Smoke  # noqa: E402

DATA = Path(__file__).resolve().parent.parent / "tests" / "data" / "bland_altman_repeated"
CSV = DATA / "glicemia ripetuta.csv"
COLUMNS = {"Subject": "Paziente #", "Occasion": "Visita |", "First": "Metodo A (mg/dl)",
           "Second": "Metodo B (mg/dl)"}
RUN = {"Confidence intervals": "Subject bootstrap", "Bootstrap replicates": 999, "Seed": 2026, "Coverage": "95"}


def fill(dialog, values):
    for name, value in values.items():
        _kind, control = dialog.controls[name]
        if hasattr(control, "findData"):
            control.setCurrentIndex(control.findData(value))
        else:
            control.setText(str(value))


class RepeatedAgreementSmoke(Smoke):
    def __init__(self, folder, dark=False):
        super().__init__(folder)
        self.dark = dark
        self.saved = None
        self.reference = None

    def note(self, text):
        self.notes.append(f"[{self.language}] {text}")

    def shot(self, widget, name):
        """Draw the figures first: an idle matplotlib canvas would be grabbed before its first paint."""
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
        for canvas in widget.findChildren(FigureCanvasQTAgg):
            if canvas.isVisible():
                canvas.draw()
        end = time.monotonic() + .25
        while time.monotonic() < end:
            self.app.processEvents()
            time.sleep(.01)
        super().shot(widget, name)

    def expect(self, condition, text):
        if not condition:
            self.problem(text)
        return bool(condition)

    def wait(self, window=None, timeout=120):
        window = window or self.window
        end = time.monotonic() + timeout
        while window.job is not None and time.monotonic() < end:
            self.app.processEvents()
            time.sleep(.02)
        self.app.processEvents()
        self.expect(window.job is None, "a calculation is still running")

    def ask(self, command, script):
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

    # -- dialog ----------------------------------------------------------------------------------------
    def first_dialog(self, dialog):
        from .labels import method_label
        dialog.query.setText(method_label(bar.METHOD))
        items = [dialog.methods.topLevelItem(group).child(row)
                 for group in range(dialog.methods.topLevelItemCount())
                 for row in range(dialog.methods.topLevelItem(group).childCount())]
        dialog._picked(next(item for item in items if item.data(0, Qt.ItemDataRole.UserRole) == bar.METHOD))
        fill(dialog, COLUMNS)
        self.shot(dialog, "dialog")
        _caption, seed, form = dialog.rows["Seed"]
        self.expect(not form.isRowVisible(seed), "Seed is shown without the bootstrap")

        fill(dialog, {"Occasion": COLUMNS["Subject"]})
        with mock.patch.object(bar, "bootstrap", side_effect=AssertionError("resampling in the dialog")):
            dialog.accept()
        self.expect(dialog.result is None and self.window.job is None, "a wrong Occasion reached the worker")
        self.expect(dialog.focusWidget() is dialog.controls["Occasion"][1], "Occasion is not focused")
        self.shot(dialog, "dialog-error")
        self.note(f"refused in the dialog: {dialog.banner.text()}")

        fill(dialog, {"Occasion": COLUMNS["Occasion"], **RUN})
        dialog.tabs.setCurrentIndex(dialog.tabs.count() - 1)
        self.expect(form.isRowVisible(seed), "Seed is hidden with the bootstrap")
        self.shot(dialog, "dialog-bootstrap")
        dialog.accept()
        self.expect(dialog.result is not None, f"the corrected dialog was refused: {dialog.banner.text()!r}")
        return True

    def change(self, index, values):
        def script(dialog):
            fill(dialog, values)
            dialog.accept()
            return True
        self.window.open_sheet(("graph", index))
        self.wait()
        self.ask(self.window.change_parameters, script)
        self.wait()
        return self.window.project.runs[index]

    # -- run ---------------------------------------------------------------------------------------------
    def run_language(self, language):
        from analisi.i18n import set_language
        from . import theme
        from .window import MainWindow
        self.language = language
        set_language(language)
        theme.install_qt_translations(self.app, language)
        first = language == LANGUAGES[0]
        self.window = window = MainWindow()
        window.error = lambda error: self.problem(f"error shown: {error}")
        available = self.screen_rect(window)
        window.resize(min(1600, available.width()), min(1000, available.height()))
        window.show()
        theme.keep_on_screen(window)
        self.app.processEvents()
        try:
            window.open_path(CSV)
            self.wait()
            title = window.selected[1]
            started = time.perf_counter()
            self.ask(window.actions["analyze"].trigger, self.first_dialog)
            self.wait()
            run = window.project.runs[-1]
            index = window.project.runs.index(run)
            self.note(f"first calculation (14 pairs, 6 subjects, 999 replicates): {time.perf_counter() - started:.2f} s")
            self.expect(run.calculation_error is None and run.result is not None,
                        f"not calculated: {run.calculation_error}")
            self.expect(window.selected == ("graph", index), "the figure did not open first")
            self.expect(run.options["Coverage"] == 95.0 and run.options["Seed"] == 2026, f"recipe {run.options}")
            self.shot(window, "page-graph")
            tables = run.result.tables
            self.expect(list(tables) == ["Agreement", "Subjects", "Pairs", "Excluded rows"], f"sheets {list(tables)}")
            row = tables["Agreement"].iloc[0]
            self.note("Agreement: bias {:.4f}, limits {:.4f} to {:.4f}, bias CI {:.4f}–{:.4f}, {} valid replicates"
                      .format(row["Bias"], row["Lower agreement limit"], row["Upper agreement limit"],
                              row["Bias CI low"], row["Bias CI high"], row["Bootstrap valid"]))
            window.open_sheet(("result", index))
            for name in tables:
                window.result_tabs.setCurrentIndex(list(tables).index(name))
                self.shot(window, "page-" + name.lower().replace(" ", "-"))
                if first and name in ("Agreement", "Pairs"):
                    self.save_as(window.export, self.folder / ("agreement-table.csv" if name == "Agreement"
                                                               else "pairs.csv"))
            window.open_sheet(("graph", index))
            if first:
                for suffix in ("png", "svg", "pdf"):
                    self.save_as(window.export, self.folder / f"agreement.{suffix}")
                svg = (self.folder / "agreement.svg").read_text(encoding="utf-8")
                self.expect("<path" in svg and "<image" not in svg, "the SVG is not fully vector")
                self.saved = self.folder / "bland-altman-ripetute.alab"
                window.project.save(self.saved)
                self.reference = {name: frame.copy() for name, frame in tables.items()}

            self.dismiss(index)
            run = self.change(index, {"Graph": "Subject diagnostics"})
            self.expect(run.calculation_error is None and "Within-subject" in run.result.figure.axes[0].get_title(),
                        "subject diagnostics did not draw")
            self.shot(window, "page-subjects")
            run = self.change(index, {"Graph": "Pairs", "Mode": "Log ratio"})
            self.expect(run.result.figure.axes[0].get_yscale() == "log", "Log ratio is not drawn on a ratio axis")
            self.shot(window, "page-graph-log")
            run = self.change(index, {"Mode": "Difference"})

            self.recalculate(title, index)
            self.cancel(index)
            self.reopen()
        except Exception:  # noqa: BLE001 - the report must say what broke, then the next language runs.
            self.problem("stopped:\n" + traceback.format_exc())
        finally:
            window.project.dirty = False
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def dismiss(self, index):
        """Change parameters, edit the fields, then Cancel: the confirmed recipe and result stay as they were."""
        window = self.window
        run = window.project.runs[index]
        options, result = dict(run.options), run.result

        def script(dialog):
            fill(dialog, {"Mode": "Log ratio", "Coverage": "80"})
            dialog.reject()
            return False

        window.open_sheet(("graph", index))
        self.ask(window.change_parameters, script)
        self.wait()
        run = window.project.runs[index]
        self.expect(window.job is None and run.options == options and run.result is result,
                    "Cancel in the dialog changed the recipe")
        self.note("Change parameters → Cancel kept the confirmed recipe")

    def recalculate(self, title, index):
        window = self.window
        window.open_sheet(("data", title))
        window.edit_cell(title, 4, 2, "123")
        self.wait()
        tables = window.project.runs[index].result.tables
        self.expect(tables["Agreement"].iloc[0]["Pairs"] == 15 and "Excluded rows" not in tables,
                    "completing row 5 did not add the pair")
        window.open_sheet(("data", title))
        window.sheet.setCurrentIndex(window.sheet.model().index(0, 2))
        window.toggle_exclusion()
        self.wait()
        tables = window.project.runs[index].result.tables
        self.expect(tables.get("Excluded rows") is not None
                    and tables["Excluded rows"]["Source row"].tolist() == [1], "an excluded cell was not listed")
        window.undo()
        self.wait()
        self.expect("Excluded rows" not in window.project.runs[index].result.tables, "undo did not restore row 1")
        self.note("edit, exclusion and undo recalculated the analysis")

    def cancel(self, index):
        window = self.window
        run = window.project.runs[index]
        options, result = dict(run.options), run.result
        started = []

        def slow(plan, cancel=None, **_):  # the synthetic study is too small to stay busy for a click
            started.append(time.perf_counter())
            while not cancel.is_set():
                time.sleep(.005)
            bar.check_cancel(cancel)

        def script(dialog):
            fill(dialog, {"Bootstrap replicates": 20000})
            dialog.accept()
            return True

        window.open_sheet(("graph", index))
        with mock.patch.object(bar, "bootstrap", side_effect=slow):
            self.ask(window.change_parameters, script)
            end = time.monotonic() + 10
            while not started and time.monotonic() < end:
                self.app.processEvents()
                time.sleep(.01)
            clicked = time.perf_counter()
            window.cancel_calculation()
            self.wait()
        run = window.project.runs[index]
        self.expect(run.options == options and run.result is result, "cancelling changed the recipe or the result")
        self.note(f"cancel: last confirmed result kept, latency {time.perf_counter() - clicked:.3f} s "
                  "(bootstrap held open by the smoke)")

    def reopen(self):
        from .window import MainWindow
        if self.saved is None:
            return
        other = MainWindow()
        other.error = lambda error: self.problem(f"error shown on reopen: {error}")
        other.show()
        try:
            other.open_path(self.saved)
            self.wait(other)
            other.open_sheet(("graph", 0))
            self.wait(other)
            reopened = other.project.runs[0]
            for name, frame in self.reference.items():
                try:
                    pd.testing.assert_frame_equal(reopened.result.tables[name], frame, obj=name)
                except AssertionError as error:
                    self.problem(f"reopened {name} differs: {error}")
            self.shot(other, "reopened")
            self.note("saved project reopened with identical sheets")
        finally:
            other.project.dirty = False
            other.close()
            other.deleteLater()
            self.app.processEvents()

    def report(self):
        screen = self.app.primaryScreen()
        geometry = screen.availableGeometry() if screen else QRect()
        lines = [f"Trama Qt · Bland–Altman for repeated pairs smoke · PySide6 {PYSIDE_VERSION} · platform "
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
    from analisi.i18n import active_language, set_language
    from . import theme
    smoke = RepeatedAgreementSmoke(folder, dark)
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
        print("Usage: python -m trama_qt.bland_altman_repeated_smoke FOLDER [--dark]")
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
    print(f"Bland–Altman for repeated pairs smoke: {status} ({folders[0]})")
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
