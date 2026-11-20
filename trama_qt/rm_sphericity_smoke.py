"""Sphericity corrections of Repeated measures ANOVA on the real Qt window:
``python -m trama_qt.rm_sphericity_smoke FOLDER [--dark]``.

The conventions of ``python -m trama_qt --smoke`` (``trama_qt/smoke.py``): the real screen, preferences in a
temporary folder, synthetic data only, English then Italian. In each language it opens the synthetic table
``tests/data/rm_sphericity/second-dataset.csv`` (8 subjects, Time 4 levels × Dose 3 levels), presses Analyze, chooses
Huynh-Feldt from the keyboard and runs the analysis. It records the dialog and the result pages, checks every
epsilon, degree of freedom and p against the frozen output of R (``reference-r.json``), reads the same values back
from the exported CSV, switches the analysis to Lower bound from the dialog, has an incomplete design refused on
its field in the active language, edits a measurement (automatic recalculation) and saves, closes and reopens the
project.

Writes into FOLDER:

- ``<lang>-dialog.png``, ``-dialog-keyboard``, ``-dialog-error``, ``-page-anova``, ``-page-sphericity``,
  ``-page-lower-bound`` (PNG as drawn at this scale);
- in the first language only: ``anova.csv``, ``sphericity.csv``, ``sphericity-lower-bound.csv`` and ``misure.alab``;
- ``report.txt`` (screen, scale, theme, timings, checks, problems) and ``status.txt`` (PASS or FAIL).

Exit code 0 on PASS, 1 on FAIL. On Linux an emulated screen is ``QT_QPA_PLATFORM="offscreen:configfile=..."``
(see ``docs/qt-migration.md``).
"""
import csv
import json
import os
from pathlib import Path
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
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QDialog, QFileDialog  # noqa: E402

from analisi import rm_sphericity  # noqa: E402
from analisi.workbench import analyse  # noqa: E402

from .smoke import LANGUAGES, Smoke  # noqa: E402

DATA = Path(__file__).resolve().parent.parent / "tests" / "data" / "rm_sphericity"
FIXTURE = DATA / "second-dataset.csv"
METHOD = "Repeated measures ANOVA"
FIELD = "Sphericity correction"
TITLE = "Misure ripetute"
BROKEN = "Disegno incompleto"
RECIPE = {"Response": "Value", "Factors": ["Time", "Dose"], "Subject": "Subject", FIELD: "Huynh-Feldt"}
EFFECTS = {"Time": "Time", "Dose": "Dose", "Time:Dose": "Time:Dose"}  # term → key of reference-r.json
REFERENCE = json.loads((DATA / "reference-r.json").read_text(encoding="utf-8"))["effects"]
STARTS = {  # the field error of the incomplete design, per language
    "en": "Subject S01 has no measurement for Time = T1; Dose = D2",
    "it": "Soggetto: Il soggetto S01 non ha una misura per Time = T1; Dose = D2"}
NOTE_STARTS = {"en": "Huynh–Feldt estimates the epsilon", "it": "Huynh–Feldt stima l’epsilon"}


def fill(dialog, values):
    """Set the controls of the dialog the way a user would type, tick or choose."""
    for name, value in values.items():
        kind, control = dialog.controls[name]
        if isinstance(value, list):
            for row in range(control.count()):
                item = control.item(row)
                item.setCheckState(Qt.CheckState.Checked if item.text() in value else Qt.CheckState.Unchecked)
        else:
            control.setCurrentIndex(control.findData(value))


def close(a, b, rtol=1e-7):
    return bool(np.isclose(a, b, rtol=rtol, atol=0))


class SphericitySmoke(Smoke):
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
            dialog.activateWindow()
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

    def pick(self, dialog, method):
        """Choose a method in the catalog the way a user would: search, then click."""
        if dialog.method == method:
            return
        from .labels import method_label
        dialog.query.setText(method_label(method))
        items = [dialog.methods.topLevelItem(group).child(row)
                 for group in range(dialog.methods.topLevelItemCount())
                 for row in range(dialog.methods.topLevelItem(group).childCount())]
        found = [item for item in items if item.data(0, Qt.ItemDataRole.UserRole) == method]
        if self.expect(found, f"{method} is not in the catalog of this table"):
            dialog._picked(found[0])

    def options_page(self, dialog):
        dialog.tabs.setCurrentIndex(dialog.tabs.count() - 1)  # Sphericity correction is on the Options page
        self.app.processEvents()

    # -- the dialog --------------------------------------------------------------------------------------
    def first_dialog(self, dialog):
        self.pick(dialog, METHOD)
        self.shot(dialog, "dialog")
        fill(dialog, {**RECIPE, FIELD: "None"})
        self.options_page(dialog)
        combo = dialog.controls[FIELD][1]
        self.expect(combo.currentData() == "None", f"{FIELD} starts as {combo.currentData()!r}")
        self.note(f"choices: {[combo.itemText(i) for i in range(combo.count())]}; dialog {dialog.width()}×"
                  f"{dialog.height()} px")
        dialog.focus_field(FIELD)
        for expected in ("Geisser–Greenhouse", "Huynh-Feldt"):  # the keyboard alone moves the choice
            QTest.keyClick(combo, Qt.Key.Key_Down)
            self.expect(combo.currentData() == expected, f"the Down key left {combo.currentData()!r}, not {expected!r}")
        self.expect(dialog.sphericity.note.text().startswith(NOTE_STARTS[self.language]),
                    f"note: {dialog.sphericity.note.text()[:60]!r}")
        self.expect(dialog.sphericity.note.isVisible(), "the note is not visible")
        self.shot(dialog, "dialog-keyboard")
        dialog.accept()
        self.expect(dialog.result is not None, f"the dialog was refused: {dialog.banner.text()!r}")
        return True

    def recipe_dialog(self, values, method=METHOD):
        def script(dialog):
            self.pick(dialog, method)
            fill(dialog, values)
            dialog.accept()
            return True
        return script

    # -- the run -----------------------------------------------------------------------------------------
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
        window.resize(min(1280, available.width()), min(800, available.height()))
        window.show()
        theme.keep_on_screen(window)
        self.app.processEvents()
        try:
            data = self.folder / f"{TITLE}.csv"
            data.write_bytes(FIXTURE.read_bytes())
            window.open_path(data)
            self.wait()
            self.expect(window.selected == ("data", TITLE), f"table not opened: {window.selected}")

            started = time.perf_counter()
            self.ask(window.actions["analyze"].trigger, self.first_dialog)
            self.wait()
            self.note(f"first calculation (96 rows, 8 subjects, 4 × 3): {time.perf_counter() - started:.2f} s")
            index = len(window.project.runs) - 1
            run = window.project.runs[index]
            self.expect(run.calculation_error is None and run.result is not None,
                        f"not calculated: {run.calculation_error}")
            self.expect(run.options[FIELD] == "Huynh-Feldt", f"the recipe holds {run.options.get(FIELD)!r}")
            self.expect(window.selected[0] in {"result", "graph"}, f"the result did not open: {window.selected}")
            self.check_run(run, "Huynh-Feldt")
            self.pages(run, index, first, "page-sphericity", "sphericity")

            self.lower_bound(index, first)
            self.incomplete_design()
            self.edit_cell(index)
            self.save_and_reopen(index, first)
        except Exception:  # noqa: BLE001 - the report must say what broke, then the next language runs.
            self.problem("stopped:\n" + traceback.format_exc())
        finally:
            window.project.dirty = False
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def pages(self, run, index, first, shot, name):
        window = self.window
        window.open_sheet(("result", index))
        names = list(run.result.tables)
        window.result_tabs.setCurrentIndex(names.index("ANOVA"))
        self.shot(window, "page-anova" if shot == "page-sphericity" else shot + "-anova")
        window.result_tabs.setCurrentIndex(names.index("Sphericity"))
        self.shot(window, shot)
        if first:
            self.save_as(window.export, self.folder / f"{name}.csv")
            window.result_tabs.setCurrentIndex(names.index("ANOVA"))
            if name == "sphericity":
                self.save_as(window.export, self.folder / "anova.csv")
            window.result_tabs.setCurrentIndex(names.index("Sphericity"))
        self.check_csv(run, name)

    def check_run(self, run, correction):
        """Epsilons, degrees of freedom and p of every effect against the frozen output of R."""
        sheet = run.result.tables["Sphericity"].set_index("Term")
        anova = run.result.tables["ANOVA"]
        self.expect(list(run.result.tables["Sphericity"]) == rm_sphericity.ESTIMATED_COLUMNS,
                    f"Sphericity columns: {list(run.result.tables['Sphericity'])}")
        problems = 0
        for term, key in EFFECTS.items():
            ref, row = REFERENCE[key], sheet.loc[term]
            epsilon = min(1.0, ref["hf"]) if correction == "Huynh-Feldt" else 1 / ref["numdf"]
            p = ref["hf_p"] if correction == "Huynh-Feldt" else ref["lb_p"]
            df1 = ref["numdf"] * epsilon if correction == "Huynh-Feldt" else 1.0
            df2 = ref["dendf"] * epsilon if correction == "Huynh-Feldt" else ref["dendf"] / ref["numdf"]
            values = {"GG ε": (row["GG ε"], ref["gg"]), "Applied epsilon": (row["Applied epsilon"], epsilon),
                      "F": (row["F"], ref["F"]), "F df1": (row["F df1"], df1), "F df2": (row["F df2"], df2),
                      "p": (row["p"], p), "Uncorrected p": (row["Uncorrected p"], ref["p"])}
            for column, (got, want) in values.items():
                if not close(got, want):
                    problems += 1
                    self.problem(f"{term} {column}: {got!r}, R gives {want!r}")
            self.expect(close(anova.loc[term, "p"], p), f"the ANOVA sheet p of {term} differs from the Sphericity sheet")
            self.note(f"{term}: GG ε {row['GG ε']:.6f}, applied ε {row['Applied epsilon']:.6f}, "
                      f"df {row['F df1']:.4f}/{row['F df2']:.4f}, F {row['F']:.4f}, p {row['p']:.6f} "
                      f"(R: {p:.6f}); note: {row['Note'] or '—'}")
        if correction == "Huynh-Feldt":
            self.expect("limited to 1" in sheet.loc["Dose", "Note"], "the limit to 1 of Dose is not explained")
        self.note(f"{correction}: 3 effects × 7 values against R 4.3.3, {problems} differences")

    def check_csv(self, run, name):
        """The CSV of the Sphericity sheet carries the same epsilon, degrees of freedom and p."""
        path = self.folder / f"{name}.csv"
        if not path.exists():
            return
        with open(path, encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        sheet = run.result.tables["Sphericity"]
        self.expect([row["Term"] for row in rows] == list(sheet["Term"]), f"{path.name}: terms {rows and rows[0]}")
        for row, (_, values) in zip(rows, sheet.iterrows(), strict=False):
            for column in ("Applied epsilon", "F df1", "F df2", "p"):
                self.expect(close(float(row[column]), values[column], 1e-9),
                            f"{path.name}: {row['Term']} {column} {row[column]} instead of {values[column]!r}")
        self.note(f"{path.name}: {len(rows)} rows, epsilon, df and p equal to the sheet")

    # -- the same analysis with another correction ---------------------------------------------------------
    def lower_bound(self, index, first):
        window = self.window
        window.open_sheet(("result", index))

        def script(dialog):
            fill(dialog, {FIELD: "Lower bound"})
            dialog.accept()
            return True

        self.ask(window.change_parameters, script)
        self.wait()
        run = window.project.runs[index]
        self.expect(run.options[FIELD] == "Lower bound", f"the recipe holds {run.options.get(FIELD)!r}")
        self.expect(run.calculation_error is None and run.result is not None,
                    f"not recalculated: {run.calculation_error}")
        if run.result is not None:
            self.check_run(run, "Lower bound")
            window.result_tabs.setCurrentIndex(list(run.result.tables).index("Sphericity"))
            self.shot(window, "page-lower-bound")
            if first:
                self.save_as(window.export, self.folder / "sphericity-lower-bound.csv")
                self.check_csv(run, "sphericity-lower-bound")
        # Back to Huynh-Feldt for the rest of the run.
        self.ask(window.change_parameters, lambda dialog: fill(dialog, {FIELD: "Huynh-Feldt"}) or dialog.accept() or True)
        self.wait()

    def incomplete_design(self):
        """A table with a missing measurement is refused on the Subject field, before any worker."""
        window = self.window
        frame = pd.read_csv(FIXTURE).drop(index=1)
        path = self.folder / f"{BROKEN}.csv"
        frame.to_csv(path, index=False)
        window.open_path(path)
        self.wait()
        window.open_sheet(("data", BROKEN))

        def refuse(dialog):
            self.pick(dialog, METHOD)
            fill(dialog, RECIPE)
            with mock.patch.object(rm_sphericity, "effect_epsilon", side_effect=AssertionError("fit in the dialog")):
                dialog.accept()
            self.app.processEvents()
            self.expect(dialog.result is None and dialog.banner.isVisible(), "an incomplete design was accepted")
            self.expect(dialog.banner.text().startswith(STARTS[self.language]), f"message: {dialog.banner.text()!r}")
            self.expect(self.app.focusWidget() is dialog.controls["Subject"][1], "Subject is not focused")
            self.expect(window.job is None, "a worker started for an incomplete design")
            self.shot(dialog, "dialog-error")
            self.note(f"incomplete design refused on the field: {dialog.banner.text()}")
            fill(dialog, {FIELD: "None"})  # without correction the engine keeps its plain value errors
            dialog.accept()
            self.expect(dialog.result is not None, f"None was refused: {dialog.banner.text()!r}")
            return False

        self.ask(window.actions["analyze"].trigger, refuse)

    # -- recalculation, projects ---------------------------------------------------------------------------
    def edit_cell(self, index):
        window = self.window
        window.open_sheet(("data", TITLE))
        column = list(pd.read_csv(FIXTURE).columns).index("Value")
        window.edit_cell(TITLE, 5, column, "75")
        self.wait()
        edited = pd.read_csv(FIXTURE)
        edited.loc[5, "Value"] = 75
        fresh = analyse(METHOD, edited, RECIPE).tables
        run = window.project.runs[index]
        same = run.result is not None and all(
            name in run.result.tables and run.result.tables[name].equals(fresh[name]) for name in fresh)
        self.expect(same, "the sheets were not recalculated after an edit")
        if run.result is not None:
            self.note("after editing one measurement: Time p "
                      f"{run.result.tables['Sphericity'].set_index('Term').loc['Time', 'p']:.6f} "
                      f"(before {REFERENCE['Time']['hf_p']:.6f})")

    def save_and_reopen(self, index, first):
        window = self.window
        before = {name: frame.copy() for name, frame in window.project.runs[index].result.tables.items()}
        count = len(window.project.runs)
        path = self.folder / ("misure.alab" if first else f"{self.language}-reopened.alab")
        window.project.save(path)
        self.expect(window.close_project(), "the project did not close")
        window.open_path(path)
        self.wait()
        self.expect(len(window.project.runs) == count, "the reopened project lost analyses")
        window.open_sheet(("result", index))
        self.wait()
        run = window.project.runs[index]
        self.expect(run.options == RECIPE, f"the reopened recipe is {run.options}")
        for name, frame in before.items():
            same = run.result is not None and name in run.result.tables and run.result.tables[name].equals(frame)
            self.expect(same, f"{name} changed after saving and reopening")
        self.note("saved, closed and reopened: recipe and sheets identical")

    def report(self):
        screen = self.app.primaryScreen()
        geometry = screen.availableGeometry() if screen else QRect()
        lines = [f"Trama Qt · Sphericity smoke · PySide6 {PYSIDE_VERSION} · platform "
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
    smoke = SphericitySmoke(folder, dark)
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
        print("Usage: python -m trama_qt.rm_sphericity_smoke FOLDER [--dark]")
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
    print(f"Sphericity smoke: {status} ({folders[0]})")
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
