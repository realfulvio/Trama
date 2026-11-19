"""Validate binary logistic model on the real Qt window: ``python -m trama_qt.logistic_validation_smoke FOLDER [--dark]``.

Same conventions as ``python -m trama_qt --smoke`` (``trama_qt/smoke.py``): the real screen, preferences in a temporary
folder, synthetic data only, English then Italian. In each language it:

1. imports a synthetic CSV (column names with spaces and symbols, empty cells) through the real text import dialog;
2. opens Analyze, finds the method, gets a field error for Threshold and one for a malformed fold column (both
   before any fit: the fold fit is patched to fail), recovers in the same dialog and runs (decimal comma read);
3. records the figure and the Validation, Predictions and Calibration pages and checks the incomplete rows;
4. (first language) exports Predictions as CSV and the figure as PNG/SVG/PDF, then recomputes Brier score, log loss
   and ROC AUC from the exported CSV;
5. analyses the Predictions sheet as a linked input (logistic recalibration of Observed on Logit);
6. changes the parameters and presses Cancel (recipe kept), then switches the graph view to All panels;
7. edits one worksheet cell (automatic recalculation of the validation and of the linked analysis);
8. saves the project, reopens it in a new tab and recalculates: every sheet is identical;
9. imports 20,000 rows, validates 10 folds with the interface pumping events (time to the answer), then starts a
   20-fold change and cancels it (latency; recipe and result kept).

Writes ``<lang>-*.png``, in the first language ``predictions.csv``, ``validation.png/.svg/.pdf`` and
``validazione-logistica.alab``, then ``report.txt`` and ``status.txt`` (PASS or FAIL). Exit code 0 on PASS.
On Linux an emulated screen is ``QT_QPA_PLATFORM="offscreen:configfile=..."`` (see ``docs/qt-migration.md``).
"""
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
from PySide6.QtWidgets import QDialog, QFileDialog  # noqa: E402

from analisi import logistic_validation as lv  # noqa: E402

from .smoke import LANGUAGES, Smoke  # noqa: E402

RESPONSE, DOSE, AGE, CENTRE, FOLD, BROKEN = ("Esito (0/1)", "Dose mg/kg", "Età (anni) #", "Centro €", "Fold ✓",
                                              "Fold rotto")
TABLE = "studio logistico $ sintetico"
LARGE = "grande 20000"
RUN = {"Response": RESPONSE, "Predictors": [DOSE, AGE, CENTRE], "Categorical predictors": [CENTRE],
       "Folds": 5, "Seed": 2026, "Validation fold": "", "Threshold": "0,4", "Calibration bins": 8}


def synthetic(n=160, seed=96):
    """A small study: two numeric predictors, a categorical one, fold codes and a few empty cells."""
    rng = np.random.default_rng(seed)
    dose = np.round(rng.normal(2, .8, n), 3)
    age = np.round(rng.normal(55, 9, n), 1)
    centre = rng.choice(["Nord", "Sud", "Est"], n)
    z = -2.2 + 1.1 * dose + .015 * (age - 55) + .6 * (centre == "Sud")
    outcome = (rng.random(n) < 1 / (1 + np.exp(-z))).astype(int)
    frame = pd.DataFrame({RESPONSE: outcome, DOSE: dose, AGE: age, CENTRE: centre,
                          FOLD: np.tile([1, 2, 3, 4, 5], n // 5), BROKEN: np.tile([1, 2, 3, 4, 5], n // 5)})
    frame = frame.astype({RESPONSE: object, DOSE: object, CENTRE: object})
    frame.loc[[4, 39], DOSE] = None
    frame.loc[69, CENTRE] = None
    frame.loc[99, RESPONSE] = None
    frame.loc[120, BROKEN] = 7
    return frame


def large(n=20_000, seed=7):
    rng = np.random.default_rng(seed)
    frame = pd.DataFrame({f"x{i}": np.round(rng.normal(size=n), 4) for i in range(1, 9)})
    frame["Gruppo"] = rng.choice(list("ABCD"), n)
    z = frame[[f"x{i}" for i in range(1, 9)]].to_numpy() @ np.linspace(-1, 1, 8) + .5 * (frame["Gruppo"] == "B")
    frame.insert(0, "Esito", (rng.random(n) < 1 / (1 + np.exp(-z))).astype(int))
    return frame


def fill(dialog, values):
    """Set the controls the way a user types, ticks or chooses."""
    for name, value in values.items():
        _kind, control = dialog.controls[name]
        if isinstance(value, bool):
            control.setChecked(value)
        elif isinstance(value, list):
            for row in range(control.count()):
                item = control.item(row)
                item.setCheckState(Qt.CheckState.Checked if item.text() in value else Qt.CheckState.Unchecked)
        elif hasattr(control, "findData"):
            position = control.findData(value)
            if position < 0:
                raise AssertionError(f"{name}: no choice {value!r}")
            control.setCurrentIndex(position)
        else:
            control.setText(str(value))


def pick(dialog, method):
    """Find a method in the catalog the way a user would: by its caption in the active language."""
    from .labels import method_label
    if dialog.method == method:
        return
    dialog.query.setText(method_label(method))
    items = [dialog.methods.topLevelItem(group).child(row)
             for group in range(dialog.methods.topLevelItemCount())
             for row in range(dialog.methods.topLevelItem(group).childCount())]
    dialog._picked(next(item for item in items if item.data(0, Qt.ItemDataRole.UserRole) == method))


class ValidationSmoke(Smoke):
    def __init__(self, folder, dark=False):
        super().__init__(folder)
        self.dark = dark

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

    def import_csv(self, path, shot=None):
        from .text_import import TextImportDialog

        def exec_(dialog):
            dialog.show()
            self.app.processEvents()
            if shot:
                self.shot(dialog, shot)
            dialog.accept()
            return QDialog.DialogCode.Accepted

        with mock.patch.object(TextImportDialog, "exec", exec_):
            self.window.open_path(path, import_data=True)
        self.app.processEvents()

    def save_as(self, command, path):
        with mock.patch.object(QFileDialog, "getSaveFileName", return_value=(str(path), "")):
            command()
        self.expect(path.exists() and path.stat().st_size > 0, f"{path.name} was not written")

    def run_index(self, method, title=None):
        runs = self.window.project.runs
        return max(i for i, run in enumerate(runs) if run.method == method and (title is None or run.title == title))

    # -- 2. the dialog -------------------------------------------------------------------------------------
    def first_dialog(self, dialog):
        window = self.window
        pick(dialog, lv.METHOD)
        fill(dialog, {**RUN, "Threshold": "0,5"})
        self.shot(dialog, "dialog")

        fill(dialog, {"Threshold": "1,5"})
        dialog.accept()
        self.expect(dialog.result is None and dialog.banner.isVisible(), "Threshold 1.5 was accepted")
        self.expect(self.app.focusWidget() is dialog.controls["Threshold"][1], "Threshold is not focused")
        self.shot(dialog, "dialog-error-threshold")
        self.note(f"Threshold error: {dialog.banner.text()}")

        fill(dialog, {"Threshold": "0,4", "Validation fold": BROKEN})
        with mock.patch.object(lv, "binomial_fit", side_effect=AssertionError("a fit in the dialog")), \
                mock.patch.object(lv, "separation_direction", side_effect=AssertionError("an LP in the dialog")):
            dialog.accept()
        self.expect(dialog.result is None and window.job is None, "a malformed fold column reached the worker")
        self.expect(self.app.focusWidget() is dialog.controls["Validation fold"][1], "Validation fold not focused")
        self.expect("121" in dialog.banner.text() and "7" in dialog.banner.text(),
                    f"fold message: {dialog.banner.text()!r}")
        self.shot(dialog, "dialog-error-fold")
        self.note(f"fold column error: {dialog.banner.text()}")

        fill(dialog, {"Validation fold": ""})
        dialog.accept()
        self.expect(dialog.result is not None, f"the corrected dialog was refused: {dialog.banner.text()!r}")
        return True

    # -- the run -------------------------------------------------------------------------------------------
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
        work = Path(tempfile.mkdtemp(prefix="trama-logval-"))
        try:
            source = work / f"{TABLE}.csv"
            synthetic().to_csv(source, index=False)
            self.import_csv(source, "import")
            self.expect(window.selected == ("data", TABLE), f"CSV not imported: {window.selected}")

            started = time.perf_counter()
            self.ask(window.actions["analyze"].trigger, self.first_dialog)
            self.wait()
            index = self.run_index(lv.METHOD)
            run = window.project.runs[index]
            self.note(f"first calculation (160 rows, 5 folds): {time.perf_counter() - started:.2f} s")
            self.expect(run.calculation_error is None and run.result is not None, f"not calculated: "
                                                                                  f"{run.calculation_error}")
            self.expect(run.options["Threshold"] == .4 and run.options["Validation fold"] is None,
                        f"recipe not canonical: {run.options}")
            self.expect(window.selected == ("graph", index), "the figure did not open first")
            self.shot(window, "page-graph")
            self.check_tables(run)
            window.open_sheet(("result", index))
            for name, shot in ((lv.VALIDATION, "page-validation"), (lv.PREDICTIONS, "page-predictions"),
                               (lv.CALIBRATION, "page-calibration"), (lv.FOLD_SHEET, "page-folds")):
                window.result_tabs.setCurrentIndex(list(run.result.tables).index(name))
                self.shot(window, shot)
                if first and name == lv.PREDICTIONS:
                    self.save_as(window.export, self.folder / "predictions.csv")
                    self.check_export(run, self.folder / "predictions.csv")
            if first:
                window.open_sheet(("graph", index))
                for suffix in ("png", "svg", "pdf"):
                    self.save_as(window.export, self.folder / f"validation.{suffix}")
            self.linked(index)
            self.change_and_cancel(index)
            self.edit(index)
            self.reopen(index, self.folder / "validazione-logistica.alab" if first else work / "progetto.alab")
            self.benchmark(work)
        except Exception:  # noqa: BLE001 - the report says what broke, then the next language runs.
            self.problem("stopped:\n" + traceback.format_exc())
        finally:
            for session in list(getattr(window.sessions, "sessions", [])):
                getattr(session, "project", window.project).dirty = False
            window.project.dirty = False
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def check_tables(self, run):
        tables = run.result.tables
        rows = tables[lv.PREDICTIONS]
        incomplete = rows.loc[rows["Status"] == lv.INCOMPLETE, "Source row"].tolist()
        self.expect(incomplete == [5, 40, 70, 100], f"incomplete rows {incomplete}")
        self.expect(len(rows) == 160 and rows["Source row"].tolist() == list(range(1, 161)), "Predictions order")
        summary = tables[lv.VALIDATION].iloc[0]
        self.expect(summary["N"] == 156 and len(tables[lv.CALIBRATION]) == 8, "Validation N or bins")
        self.note(f"Validation: Brier {summary['Brier score']:.4f}, log loss {summary['Log loss']:.4f}, "
                  f"AUC {summary['ROC AUC']:.4f}, AP {summary['Average precision']:.4f}, "
                  f"TN/FP/FN/TP {summary['TN']}/{summary['FP']}/{summary['FN']}/{summary['TP']} at p ≥ 0.4")

    def check_export(self, run, path):
        exported = pd.read_csv(path)
        used = exported[exported["Status"] == lv.PREDICTED]
        y, p, z = used["Observed"].to_numpy(), used["Probability"].to_numpy(), used["Logit"].to_numpy()
        summary = run.result.tables[lv.VALIDATION].iloc[0]
        brier = np.mean((p - y) ** 2)
        loss = np.mean(np.logaddexp(0, z) - y * z)
        positive, negative = z[y == 1], z[y == 0]
        auc = np.mean((positive[:, None] > negative[None, :]) + .5 * (positive[:, None] == negative[None, :]))
        ok = all(abs(a - b) < 1e-9 for a, b in ((brier, summary["Brier score"]), (loss, summary["Log loss"]),
                                                (auc, summary["ROC AUC"])))
        self.expect(ok, f"metrics from the exported CSV differ: {brier}, {loss}, {auc}")
        self.note(f"metrics recomputed from predictions.csv ({len(used)} rows): equal to 1e-9")

    # -- 5. linked analysis --------------------------------------------------------------------------------
    def linked(self, index):
        window = self.window
        run = window.project.runs[index]
        window.open_sheet(("result", index))
        window.result_tabs.setCurrentIndex(list(run.result.tables).index(lv.PREDICTIONS))

        def recalibrate(dialog):
            pick(dialog, "Multiple regression")
            fill(dialog, {"Response": "Observed", "Predictors": ["Logit"], "Categorical predictors": [],
                          "Family": "Logistic"})
            dialog.accept()
            return True

        self.ask(window.analyze_result_table, recalibrate)
        self.wait()
        linked = window.project.runs[self.run_index("Multiple regression")]
        self.expect(linked.source is not None and linked.source.table == lv.PREDICTIONS,
                    f"the linked analysis does not read Predictions: {linked.source}")
        self.expect(linked.calculation_error is None and linked.result is not None,
                    f"linked analysis failed: {linked.calculation_error}")
        if linked.result is not None:
            slope = linked.result.tables["Coefficients"].loc["Logit", "Estimate"]
            self.note(f"linked recalibration on Predictions: slope of Logit {slope:.4f} (N "
                      f"{int(linked.result.tables['Model'].loc['N', 'Value'])})")
            self.shot(window, "page-linked")

    # -- 6. change, cancel the dialog, then All panels -------------------------------------------------------
    def change_and_cancel(self, index):
        window = self.window
        run = window.project.runs[index]
        options, result = dict(run.options), run.result
        window.open_sheet(("graph", index))

        def cancelled(dialog):
            fill(dialog, {"Folds": 3, "Seed": 1})
            return False

        self.ask(window.change_parameters, cancelled)
        self.wait()
        run = window.project.runs[index]
        self.expect(run.options == options and run.result is result, "Cancel in the dialog changed the recipe")

        def panels(dialog):
            fill(dialog, {"Graph view": lv.ALL_VIEWS})
            dialog.accept()
            return True

        self.ask(window.change_parameters, panels)
        self.wait()
        run = window.project.runs[index]
        self.expect(len(run.result.figure.axes) == 3, "All panels did not draw three panels")
        self.shot(window, "page-graph-all")

    # -- 7. edit a cell ------------------------------------------------------------------------------------
    def edit(self, index):
        window = self.window
        before = window.project.runs[index].result.tables
        position = 10
        fold = int(before[lv.PREDICTIONS]["Fold"].iloc[position])
        column = list(window.project.tables[TABLE].frame().columns).index(DOSE)
        window.open_sheet(("data", TABLE))
        window.edit_cell(TABLE, position, column, "9")
        self.wait()
        after = window.project.runs[index].result.tables
        self.expect(after[lv.PREDICTIONS]["Logit"].iloc[position] != before[lv.PREDICTIONS]["Logit"].iloc[position],
                    "the edited row was not predicted again")
        own = after[lv.COEFFICIENTS].query("Fold == @fold")["Estimate"].to_numpy()
        self.expect(np.array_equal(own, before[lv.COEFFICIENTS].query("Fold == @fold")["Estimate"].to_numpy()),
                    "the fit that predicts the edited row changed")
        linked = window.project.runs[self.run_index("Multiple regression")]
        self.expect(linked.calculation_error is None and linked.result is not None, "linked analysis not updated")
        self.note(f"edited row 11 (fold {fold}): its own fold fit unchanged, the other folds refitted, "
                  f"linked analysis recalculated")

    # -- 8. save, reopen, recalculate ---------------------------------------------------------------------
    def reopen(self, index, path):
        window = self.window
        before = {name: table.copy() for name, table in window.project.runs[index].result.tables.items()}
        window.project.save(path)
        window.open_path(path)
        self.wait()
        self.app.processEvents()
        position = self.run_index(lv.METHOD)
        window.open_sheet(("result", position))
        window.recalculate()
        self.wait()
        run = window.project.runs[position]
        self.expect(run.result is not None and run.calculation_error is None, "not recalculated after reopening")
        if run.result is not None:
            same = all(before[name].equals(run.result.tables[name]) for name in before)
            self.expect(same, "the reopened project gives other sheets")
            self.note(f"{path.name}: reopened in a new tab and recalculated, {len(before)} sheets identical")
        self.shot(window, "page-reopened")

    # -- 9. benchmark and cancel ---------------------------------------------------------------------------
    def benchmark(self, work):
        window = self.window
        source = work / f"{LARGE}.csv"
        large().to_csv(source, index=False)
        started = time.perf_counter()
        self.import_csv(source)
        imported = time.perf_counter() - started
        options = {"Response": "Esito", "Predictors": [*[f"x{i}" for i in range(1, 9)], "Gruppo"],
                   "Categorical predictors": ["Gruppo"], "Folds": 10, "Seed": 1, "Validation fold": "",
                   "Threshold": "0.5", "Calibration bins": 10}
        timing = {}

        def big(dialog):
            pick(dialog, lv.METHOD)
            fill(dialog, options)
            timing["accepted"] = time.perf_counter()
            dialog.accept()
            return True

        self.ask(window.actions["analyze"].trigger, big)
        ticks = 0
        while window.job is not None:
            self.app.processEvents()
            ticks += 1
            time.sleep(.01)
        answered = time.perf_counter() - timing["accepted"]
        index = self.run_index(lv.METHOD, LARGE)
        run = window.project.runs[index]
        self.expect(run.result is not None, f"20,000 rows not validated: {run.calculation_error}")
        self.note(f"20,000 rows × 10 folds: import {imported:.2f} s, Run → result {answered:.2f} s with the window "
                  f"processing events ({ticks} event-loop turns)")
        options_before, result_before = dict(run.options), run.result
        window.open_sheet(("graph", index))

        def heavy(dialog):
            fill(dialog, {"Folds": 20})
            dialog.accept()
            return True

        self.ask(window.change_parameters, heavy)
        if not self.expect(window.job is not None, "the 20-fold change did not start"):
            return
        end = time.monotonic() + .4
        while time.monotonic() < end:
            self.app.processEvents()
            time.sleep(.01)
        started = time.perf_counter()
        window.cancel_calculation()
        self.wait()
        latency = time.perf_counter() - started
        run = window.project.runs[index]
        self.expect(run.options == options_before and run.result is result_before,
                    "cancelling changed the recipe or the result")
        self.note(f"cancel during the 20-fold change: {latency:.3f} s until the window was idle; recipe and result kept")

    def report(self):
        screen = self.app.primaryScreen()
        geometry = screen.availableGeometry() if screen else QRect()
        lines = [f"Trama Qt · Validate binary logistic model smoke · PySide6 {PYSIDE_VERSION} · platform "
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
    smoke = ValidationSmoke(folder, dark)
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
        print("Usage: python -m trama_qt.logistic_validation_smoke FOLDER [--dark]")
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
    print(f"Logistic validation smoke: {status} ({folders[0]})")
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
