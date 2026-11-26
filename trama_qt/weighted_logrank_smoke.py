"""Weighted log-rank comparisons on the real Qt window:
``python -m trama_qt.weighted_logrank_smoke FOLDER``.

English then Italian, light and dark, 1024×768 and a wide window. Synthetic cohort only.
"""
import math
import os
from pathlib import Path
import platform
import sys
import tempfile
import time
import traceback
from unittest import mock

os.environ.setdefault("MPLBACKEND", "QtAgg")

import pandas as pd  # noqa: E402
from PySide6 import __version__ as PYSIDE_VERSION  # noqa: E402
from PySide6.QtCore import QItemSelection, QItemSelectionModel, QRect, Qt, qVersion  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QCheckBox, QDialog, QFileDialog, QLabel  # noqa: E402

from analisi.survival_input import PAIRWISE_CORRECTION, PAIRWISE_SCOPE  # noqa: E402
from analisi.weighted_logrank import (DETAIL, DETAIL_SHEET, GLOBAL, LATE, RHO, STEP_PREFIX, TARONE,  # noqa: E402
                                      WEIGHTING, WEIGHT_AXES)

from .smoke import LANGUAGES, Smoke  # noqa: E402

DATA = Path(__file__).resolve().parent.parent / "tests" / "data" / "weighted-logrank"
KM = "Kaplan–Meier survival"
TARONE_CHI2 = 1.350941601454316
TARONE_P = 0.5089167658137421


def cohort():
    frame = pd.read_csv(DATA / "coorti.csv")
    frame["altro"] = frame["evento"]
    return frame


def fill(dialog, values):
    for name, value in values.items():
        _kind, control = dialog.controls[name]
        if isinstance(value, list):
            for row in range(control.count()):
                item = control.item(row)
                item.setCheckState(Qt.CheckState.Checked if item.text() in value else Qt.CheckState.Unchecked)
        elif isinstance(control, QCheckBox):
            control.setChecked(bool(value))
        elif hasattr(control, "findData"):
            control.setCurrentIndex(control.findData(value))
        else:
            control.setText(str(value))


def close(value, expected):
    return math.isclose(float(value), expected, rel_tol=1e-9, abs_tol=1e-9)


class WeightedSmoke(Smoke):
    def __init__(self, folder):
        super().__init__(folder)
        self.saved = None
        self.reference = None

    def note(self, text):
        self.notes.append(f"[{self.language}] {text}")

    def expect(self, condition, text):
        if not condition:
            self.problem(text)
        return bool(condition)

    def shot(self, widget, name):
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
        for canvas in widget.findChildren(FigureCanvasQTAgg):
            if canvas.isVisible():
                canvas.draw()
        end = time.monotonic() + .25
        while time.monotonic() < end:
            self.app.processEvents()
            time.sleep(.01)
        super().shot(widget, name)

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

    @staticmethod
    def show_field(dialog, name):
        _caption, widget, form = dialog.rows[name]
        for position in range(dialog.tabs.count()):
            scroll = dialog.tabs.widget(position)
            if scroll.widget().layout() is form:
                dialog.tabs.setCurrentIndex(position)
                scroll.ensureWidgetVisible(widget)
                break

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

    def survival_columns(self, run):
        kept = {}
        for name, frame in run.result.tables.items():
            if name in (GLOBAL, "Weighted pairwise", DETAIL_SHEET, "Weighted pairwise FDR", "Pairwise log-rank"):
                continue
            if "Survival" in getattr(frame, "columns", ()):
                kept[name] = frame["Survival"].to_numpy(dtype=float).copy()
            if "At risk" in getattr(frame, "columns", ()) and "Weight" not in frame.columns:
                kept[name + " at risk"] = frame["At risk"].to_numpy(dtype=float).copy()
        return kept

    def run_language(self, language):
        from analisi.i18n import set_language
        from . import theme
        from .window import MainWindow
        self.language = language
        set_language(language)
        theme.install_qt_translations(self.app, language)
        theme.set_mode("light", remember=False)
        first = language == LANGUAGES[0]
        self.window = window = MainWindow()
        window.error = lambda error: self.problem(f"error shown: {error}")
        available = self.screen_rect(window)
        window.resize(min(1600, available.width()), min(1000, available.height()))
        window.show()
        theme.keep_on_screen(window)
        self.app.processEvents()
        path = self.folder / "coorti.csv"
        cohort().to_csv(path, index=False)
        try:
            window.open_path(path)
            self.wait()
            title = window.selected[1]
            self.ask(window.actions["analyze"].trigger, self.first_dialog)
            self.wait()
            run = window.project.runs[-1]
            index = window.project.runs.index(run)
            self.expect(run.calculation_error is None and run.result is not None, f"not calculated: {run.calculation_error}")
            self.expect(run.options.get(WEIGHTING) == TARONE and RHO not in run.options and run.options.get(DETAIL) is True,
                        f"recipe {run.options}")
            sheet = run.result.tables[GLOBAL]
            self.expect(close(sheet.at["χ²", "Value"], TARONE_CHI2) and close(sheet.at["p", "Value"], TARONE_P),
                        f"Tarone–Ware χ²={sheet.at['χ²', 'Value']} p={sheet.at['p', 'Value']}")
            self.expect(int(sheet.at["df", "Value"]) == 2, f"df {sheet.at['df', 'Value']}")
            baseline = self.survival_columns(run)
            self.expect_weight_panel(run, 1)
            self.shot(window, "graph")
            window.open_sheet(("result", index))
            self.wait()
            window.result_tabs.setCurrentIndex(list(run.result.tables).index(DETAIL_SHEET))
            self.shot(window, "weight-detail")
            self.resize_and_themes(window)
            self.shortcuts(window)
            run = self.change(index, {WEIGHTING: LATE, DETAIL: True})
            self.expect(run.calculation_error is None, f"late weight: {run.calculation_error}")
            detail = run.result.tables[DETAIL_SHEET]
            self.expect(detail.iloc[0]["Comparison"] == "All groups" and close(detail.iloc[0]["Weight"], 0.0),
                        f"first late weight is {detail.iloc[0]['Weight']}")
            later = self.survival_columns(run)
            self.expect(baseline.keys() == later.keys(), "the Kaplan–Meier sheets changed with the weight")
            for name in baseline:
                self.expect(len(baseline[name]) == len(later[name]) and all(
                    math.isclose(left, right, rel_tol=0, abs_tol=0) for left, right in zip(baseline[name], later[name])),
                    f"Kaplan–Meier column {name} changed when the weight changed")
            self.dismiss(index)
            self.second_response(index)
            self.edit_and_exclude(title, index)
            if first:
                window.open_sheet(("result", index))
                self.wait()
                window.result_tabs.setCurrentIndex(list(window.project.runs[index].result.tables).index(DETAIL_SHEET))
                self.save_as(window.export, self.folder / "weight-detail.csv")
                window.open_sheet(("graph", index))
                self.save_as(window.export, self.folder / "weight-graph.png")
                self.saved = self.folder / "sopravvivenza-pesata-smoke.alab"
                window.project.save(self.saved)
                self.reference = window.project.runs[index].result.tables[GLOBAL].copy()
            self.reopen()
        except Exception:
            self.problem("stopped:\n" + traceback.format_exc())
        finally:
            window.project.dirty = False
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def first_dialog(self, dialog):
        from .labels import method_label
        dialog.query.setText(method_label(KM))
        items = [dialog.methods.topLevelItem(group).child(row)
                 for group in range(dialog.methods.topLevelItemCount())
                 for row in range(dialog.methods.topLevelItem(group).childCount())]
        dialog._picked(next(item for item in items if item.data(0, Qt.ItemDataRole.UserRole) == KM))
        fill(dialog, {"Time": "tempo", "Event columns": ["evento"], "Grouping variables": ["gruppo"]})
        self.show_field(dialog, WEIGHTING)
        banner = next(label for label in dialog.findChildren(QLabel) if label.objectName() == "infoBanner")
        if self.language == "it":
            self.expect("curve di Kaplan–Meier" in banner.text(), "the Italian help does not mention the curves")
            captions = [dialog.controls[WEIGHTING][1].itemText(i) for i in range(dialog.controls[WEIGHTING][1].count())]
            self.expect(any("precoce" in text for text in captions), f"Italian choices {captions}")
        else:
            self.expect("Kaplan–Meier curves" in banner.text() and "early weight" in banner.text(), banner.text())
        weighting = dialog.controls[WEIGHTING][1]
        self.expect(weighting.currentData() == "None" and RHO in dialog.hidden and DETAIL in dialog.hidden,
                    "the selector does not start at None with the exponents hidden")
        weighting.setFocus()
        QTest.keyClick(weighting, Qt.Key.Key_Tab)
        self.app.processEvents()
        self.expect(dialog.focusWidget() is not weighting, "Tab did not leave the selector")
        fill(dialog, {WEIGHTING: TARONE, DETAIL: True, PAIRWISE_CORRECTION: "Holm", PAIRWISE_SCOPE: "All pairs"})
        self.expect(RHO in dialog.hidden and DETAIL not in dialog.hidden, "Tarone–Ware showed the exponents")
        self.shot(dialog, "dialog")
        QTest.keyClick(dialog, Qt.Key.Key_Return)
        self.app.processEvents()
        self.expect(dialog.result is not None, f"Enter did not run the analysis: {dialog.banner.text()!r}")
        return True

    def expect_weight_panel(self, run, count):
        figure = run.result.figure
        lines = [line for ax in figure.axes for line in ax.lines
                 if str(line.get_gid() or "").startswith(STEP_PREFIX)]
        named = [ax for ax in figure.axes if ax.get_gid() == WEIGHT_AXES or "Tarone" in ax.get_ylabel()
                 or "Fleming" in ax.get_ylabel() or "Gehan" in ax.get_ylabel() or "Log-rank" in ax.get_ylabel()
                 or "pesato" in ax.get_ylabel().casefold() or "tardivo" in ax.get_ylabel().casefold()]
        self.expect(len(lines) == count, f"{len(lines)} weight steps, expected {count}")
        self.expect(bool(named), f"no axis names the method: {[ax.get_ylabel() for ax in figure.axes]}")

    def resize_and_themes(self, window):
        from . import theme
        window.resize(1024, 768)
        theme.keep_on_screen(window)
        self.app.processEvents()
        self.shot(window, "1024x768")
        available = self.screen_rect(window)
        window.resize(min(1600, available.width()), min(1000, available.height()))
        theme.keep_on_screen(window)
        self.app.processEvents()
        self.shot(window, "wide")
        theme.set_mode("dark", remember=False)
        self.app.processEvents()
        self.shot(window, "dark")
        theme.set_mode("light", remember=False)
        self.app.processEvents()
        self.shot(window, "light")

    def shortcuts(self, window):
        from .shortcuts_dialog import ShortcutsDialog
        dialog = ShortcutsDialog(window)
        dialog.show()
        self.app.processEvents()
        self.shot(dialog, "shortcuts")
        self.expect(dialog.isVisible() and dialog.tree.topLevelItemCount() > 0, "F1 did not list the shortcuts")
        QTest.keyClick(dialog, Qt.Key.Key_Escape)
        self.app.processEvents()
        self.expect(not dialog.isVisible(), "Escape did not close the shortcut list")
        dialog.deleteLater()

    def dismiss(self, index):
        window = self.window
        run = window.project.runs[index]
        options, result = dict(run.options), run.result

        def script(dialog):
            fill(dialog, {WEIGHTING: TARONE})
            QTest.keyClick(dialog, Qt.Key.Key_Escape)
            self.app.processEvents()
            return False

        window.open_sheet(("graph", index))
        self.ask(window.change_parameters, script)
        self.wait()
        run = window.project.runs[index]
        self.expect(run.options == options and run.result is result, "Escape changed the confirmed recipe")
        self.note("Escape left the late-weight recipe unchanged")

    def second_response(self, index):
        run = self.change(index, {"Event columns": ["evento", "altro"]})
        self.expect(run.calculation_error is None, f"two responses: {run.calculation_error}")
        self.expect_weight_panel(run, 2)
        labels = [line.get_label() for ax in run.result.figure.axes for line in ax.lines
                  if str(line.get_gid() or "").startswith(STEP_PREFIX)]
        self.expect(any("evento" in label for label in labels) and any("altro" in label for label in labels),
                    f"the weight curves do not name the responses: {labels}")
        self.shot(self.window, "two-responses")
        self.change(index, {"Event columns": ["evento"]})

    def edit_and_exclude(self, title, index):
        window = self.window
        before = float(window.project.runs[index].result.tables[GLOBAL].at["χ²", "Value"])
        window.open_sheet(("data", title))
        self.wait()
        window.edit_cell(title, 0, 3, "0")
        self.wait()
        edited = float(window.project.runs[index].result.tables[GLOBAL].at["χ²", "Value"])
        self.expect(not close(edited, before), "editing an event did not recalculate the test")
        window.undo()
        self.wait()
        restored = float(window.project.runs[index].result.tables[GLOBAL].at["χ²", "Value"])
        self.expect(close(restored, before), f"undo left χ² at {restored}")
        window.open_sheet(("data", title))
        model = window.sheet.model()
        window.sheet.selectionModel().select(QItemSelection(model.index(12, 1), model.index(17, 1)),
                                              QItemSelectionModel.SelectionFlag.ClearAndSelect)
        window.toggle_exclusion()
        self.wait()
        reduced = window.project.runs[index].result.tables[GLOBAL]
        self.expect(int(reduced.at["df", "Value"]) == 1, f"excluding group C left df {reduced.at['df', 'Value']}")
        window.undo()
        self.wait()
        self.expect(int(window.project.runs[index].result.tables[GLOBAL].at["df", "Value"]) == 2,
                    "undo did not restore the three-group test")
        self.note("edit, undo, exclusion of group C and undo recalculated")

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
            if not self.expect(reopened.result is not None, f"reopened run has no result: {reopened.calculation_error}"):
                return
            self.expect(reopened.options.get(WEIGHTING) == LATE, f"reopened recipe {reopened.options}")
            sheet = reopened.result.tables[GLOBAL]
            self.expect(close(sheet.at["χ²", "Value"], self.reference.at["χ²", "Value"])
                        and close(sheet.at["p", "Value"], self.reference.at["p", "Value"]),
                        "the reopened test differs from the saved one")
            self.shot(other, "reopened")
            self.note("the project reopened with the same weighted test")
        finally:
            other.project.dirty = False
            other.close()
            other.deleteLater()
            self.app.processEvents()

    def report(self):
        screen = self.app.primaryScreen()
        geometry = screen.availableGeometry() if screen else QRect()
        platform_name = self.app.platformName()
        lines = [f"Trama Qt · weighted log-rank smoke · Python {platform.python_version()} · "
                 f"PySide6 {PYSIDE_VERSION} · Qt {qVersion()} · platform {platform_name}",
                 f"Screen {screen.name() if screen else '?'}: available {geometry.width()}×{geometry.height()}, "
                 f"device pixel ratio {screen.devicePixelRatio() if screen else '?'}, "
                 f"logical DPI {screen.logicalDotsPerInch() if screen else '?'}",
                 f"QT_SCALE_FACTOR: {os.environ.get('QT_SCALE_FACTOR', 'unset')}",
                 f"Screenshots: {self.shots}", ""]
        lines += self.notes + [""]
        lines += self.problems or ["No problems found."]
        (self.folder / "report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        status = "FAIL" if self.problems else "PASS"
        (self.folder / "status.txt").write_text(status + "\n", encoding="utf-8")
        return status


def run(folder, languages=LANGUAGES):
    from analisi.i18n import active_language, set_language
    from . import theme
    smoke = WeightedSmoke(folder)
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
        print("Usage: python -m trama_qt.weighted_logrank_smoke FOLDER")
        return 2
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
        theme.apply(app)
        status = run(folders[0])
    print(f"Weighted log-rank smoke: {status} ({folders[0]})")
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
