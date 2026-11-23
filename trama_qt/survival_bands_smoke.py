"""Kaplan–Meier simultaneous bands on the real Qt window:
``python -m trama_qt.survival_bands_smoke FOLDER [--dark]``.

Conventions of ``python -m trama_qt --smoke`` (``trama_qt/smoke.py``): the real screen, preferences in a temporary
folder, synthetic data only, English then Italian. In each language it opens a synthetic worksheet
(``tests/data/survival_bands/fixture.csv`` plus a second status column; a file name with spaces and symbols), finds
the analysis in the catalog, picks the **Hall–Wellner simultaneous band** in the dialog (its caption is checked in the
active language and the open list is recorded), runs at 95%, and compares the sheet *Simultaneous confidence bands*
with the independent oracle of the package. The fixture holds an event and a censor at the same time, a last event
with S = 0, a group that is all censored, a group of seven subjects next to groups of 8, 3 and 2. Then it changes
the level to 90 and to 99, the curve to cumulative events in percent (the band must be [1 − upper, 1 − lower] × 100),
adds a second response, edits a cell, excludes a row and undoes (automatic recalculation each time against the
oracle), presses Cancel in the dialog, and saves and reopens the project in a new window.

Writes into FOLDER: ``<lang>-*.png`` (as drawn at this scale); in the first language also ``bands.png/.svg/.pdf``,
``bands-sheet.csv`` and ``bande-simultanee.alab``; ``report.txt`` and ``status.txt``. Exit code 0 on PASS, 1 on FAIL.
"""
import importlib.util
import os
from pathlib import Path
import platform
import sys
import tempfile
import time
import traceback
from unittest import mock

os.environ.setdefault("MPLBACKEND", "QtAgg")  # before pyplot can be imported anywhere

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from PySide6 import __version__ as PYSIDE_VERSION  # noqa: E402
from PySide6.QtCore import QRect, Qt, qVersion  # noqa: E402
from PySide6.QtWidgets import QCheckBox, QDialog, QFileDialog  # noqa: E402

from analisi.survival_bands import SHEET, SIMULTANEOUS  # noqa: E402

from .smoke import LANGUAGES, Smoke  # noqa: E402

DATA = Path(__file__).resolve().parent.parent / "tests" / "data" / "survival_bands"
KM = "Kaplan–Meier survival"
CAPTION = {"en": "Hall–Wellner simultaneous band", "it": "Banda simultanea Hall–Wellner (conservativa)"}
WORKSHEET = "Sopravvivenza città $ {A}.csv"
_spec = importlib.util.spec_from_file_location("survival_bands_oracle", DATA / "verify.py")
oracle = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(oracle)


def worksheet():
    frame = pd.read_csv(DATA / "fixture.csv")
    frame["Relapse"] = 1 - frame["Event"]
    return frame


def oracle_rows(frame):
    return [{key: str(value) for key, value in row.items()} for row in frame.to_dict("records")]


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


class BandsSmoke(Smoke):
    def __init__(self, folder, dark=False):
        super().__init__(folder)
        self.dark = dark
        self.saved = None
        self.reference = None
        self.csv = None

    def note(self, text):
        self.notes.append(f"[{self.language}] {text}")

    def expect(self, condition, text):
        if not condition:
            self.problem(text)
        return bool(condition)

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

    def compare(self, sheet, frame, level, label):
        try:
            oracle.compare(sheet, oracle.oracle(oracle_rows(frame), level))
        except AssertionError as error:
            self.problem(f"{label}: the sheet differs from the oracle at {level}%: {error!r}")
            return False
        return True

    # -- dialog ----------------------------------------------------------------------------------------
    def first_dialog(self, dialog):
        from .labels import method_label
        dialog.query.setText(method_label(KM))
        items = [dialog.methods.topLevelItem(group).child(row)
                 for group in range(dialog.methods.topLevelItemCount())
                 for row in range(dialog.methods.topLevelItem(group).childCount())]
        dialog._picked(next(item for item in items if item.data(0, Qt.ItemDataRole.UserRole) == KM))
        fill(dialog, {"Time": "Time", "Event columns": ["Event"], "Grouping variables": ["Group"]})
        _kind, combo = dialog.controls["Uncertainty"]
        captions = [combo.itemText(index) for index in range(combo.count())]
        self.expect(captions[-1] == CAPTION[self.language], f"the last caption is {captions[-1]!r}")
        self.expect(combo.currentData() == "None", "the default of Uncertainty changed")
        self.note(f"Uncertainty choices: {captions}")
        self.show_field(dialog, "Uncertainty")
        self.shot(dialog, "dialog-default")
        combo.showPopup()
        self.app.processEvents()
        popup = combo.view().window()
        self.expect(combo.view().sizeHintForColumn(0) <= combo.view().viewport().width() + 2,
                    "the longest caption is cut in the open list")
        self.shot(popup, "dialog-list")
        combo.hidePopup()
        self.app.processEvents()
        fill(dialog, {"Uncertainty": SIMULTANEOUS, "Confidence level (%)": "95"})
        self.expect(combo.currentText() == CAPTION[self.language], "the choice did not show its caption")
        self.shot(dialog, "dialog-band")
        dialog.accept()
        self.expect(dialog.result is not None, f"the dialog was refused: {dialog.banner.text()!r}")
        return True

    @staticmethod
    def show_field(dialog, name):
        """Bring the page that holds the field to the front, with the field in view."""
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
        self.csv = self.folder / WORKSHEET
        worksheet().to_csv(self.csv, index=False)
        try:
            window.open_path(self.csv)
            self.wait()
            title = window.selected[1]
            started = time.perf_counter()
            self.ask(window.actions["analyze"].trigger, self.first_dialog)
            self.wait()
            run = window.project.runs[-1]
            index = window.project.runs.index(run)
            self.note(f"first calculation: {time.perf_counter() - started:.2f} s")
            self.expect(run.calculation_error is None and run.result is not None,
                        f"not calculated: {run.calculation_error}")
            self.expect(window.selected == ("graph", index), "the figure did not open first")
            self.expect(run.options["Uncertainty"] == SIMULTANEOUS, f"recipe {run.options}")
            self.shot(window, "page-graph")
            tables = run.result.tables
            self.expect(list(tables)[-1] == SHEET, f"sheets {list(tables)}")
            self.compare(tables[SHEET], worksheet(), 95, "95%")
            sheet = tables[SHEET]
            self.note("sheet: {} rows, {} available, {} unavailable ({})".format(
                len(sheet), int((sheet["Status"] == "Available").sum()), int((sheet["Status"] == "Unavailable").sum()),
                sorted(set(sheet.loc[sheet["Status"] == "Unavailable", "Group"]))))
            self.verify_drawing(run, 95, "survival fractions")
            window.open_sheet(("result", index))
            for number, name in enumerate(tables):
                window.result_tabs.setCurrentIndex(number)
                if name in ("Survival summary", SHEET):
                    self.shot(window, "page-" + name.lower().replace(" ", "-")[:24])
            if first:
                window.result_tabs.setCurrentIndex(list(tables).index(SHEET))
                self.save_as(window.export, self.folder / "bands-sheet.csv")
            window.open_sheet(("graph", index))
            if first:
                for suffix in ("png", "svg", "pdf"):
                    self.save_as(window.export, self.folder / f"bands.{suffix}")
                svg = (self.folder / "bands.svg").read_text(encoding="utf-8")
                self.expect("<path" in svg and "<image" not in svg, "the SVG is not fully vector")
                self.expect(svg.count("kaplan-meier-simultaneous-band-0-") >= 1, "the SVG does not carry the bands")
                self.saved = self.folder / "bande-simultanee.alab"
                window.project.save(self.saved)
                self.reference = {name: frame.copy() for name, frame in tables.items()}

            self.dismiss(index)
            for level in (90, 99):
                run = self.change(index, {"Confidence level (%)": str(level)})
                self.expect(run.calculation_error is None, f"{level}%: {run.calculation_error}")
                self.compare(run.result.tables[SHEET], worksheet(), level, f"{level}%")
                self.verify_drawing(run, level, f"{level}%")
                self.shot(window, f"page-level-{level}")
            run = self.change(index, {"Curve": "Cumulative events", "Display units": "Percent"})
            self.expect(run.calculation_error is None, f"cumulative: {run.calculation_error}")
            self.compare(run.result.tables[SHEET], worksheet(), 99, "cumulative percent")
            self.verify_drawing(run, 99, "cumulative percent")
            self.shot(window, "page-cumulative-percent")
            run = self.change(index, {"Curve": "Survival", "Display units": "Fraction", "Confidence level (%)": "95"})
            self.responses(index)
            self.recalculate(title, index)
            self.reopen()
        except Exception:  # noqa: BLE001 - the report must say what broke, then the next language runs.
            self.problem("stopped:\n" + traceback.format_exc())
        finally:
            window.project.dirty = False
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def verify_drawing(self, run, level, label):
        """The drawn band equals the sheet: limits at every available step, cumulative and percent included."""
        figure = run.result.figure
        axes = figure.axes[0]
        cumulative = axes.get_ylabel().startswith("Cumulative")
        factor = 100 if axes.get_ylabel().endswith("(%)") else 1
        sheet = run.result.tables[SHEET]
        bands = [artist for artist in axes.collections
                 if str(artist.get_gid()).startswith("kaplan-meier-simultaneous-band-") and "key" not in artist.get_gid()]
        groups = sheet.groupby("Group", sort=False)
        available = [group for _, group in groups if (group["Status"] == "Available").any()]
        self.expect(len(bands) >= len(available), f"{label}: {len(bands)} band artists for {len(available)} curves")
        vertices = np.vstack([artist.get_paths()[0].vertices for artist in bands])
        for _, group in groups:
            usable = group[group["Status"] == "Available"]
            low, high = usable["Simultaneous CI lower"].to_numpy(), usable["Simultaneous CI upper"].to_numpy()
            if cumulative:
                low, high = 1 - high, 1 - low
            for value in np.r_[low, high] * factor:
                if not np.isclose(vertices[:, 1], value, rtol=0, atol=1e-9).any():
                    self.problem(f"{label}: limit {value} of {group['Group'].iloc[0]} is not drawn")
                    break
        texts = [text.get_text() for text in axes.get_legend().get_texts()] if axes.get_legend() else []
        wanted = f"{level}% simultaneous band"
        self.expect(any(text.startswith(wanted) for text in texts), f"{label}: the legend lacks {wanted!r}: {texts}")

    def responses(self, index):
        run = self.change(index, {"Event columns": ["Event", "Relapse"]})
        self.expect(run.calculation_error is None, f"two responses: {run.calculation_error}")
        sheet = run.result.tables[SHEET]
        self.expect(list(sheet.columns)[0] == "Response variable"
                    and set(sheet["Response variable"]) == {"Event", "Relapse"}, "two responses: no Response variable")
        self.expect(len(run.result.figure.axes) >= 2, "two responses: the figure has one panel")
        self.shot(self.window, "page-two-responses")
        self.window.open_sheet(("result", index))
        self.window.result_tabs.setCurrentIndex(list(run.result.tables).index(SHEET))
        self.shot(self.window, "page-two-responses-sheet")
        self.note(f"two responses: {len(sheet)} rows")
        self.change(index, {"Event columns": ["Event"]})

    def dismiss(self, index):
        """Change parameters, edit the fields, then Cancel: the confirmed recipe and result stay as they were."""
        window = self.window
        run = window.project.runs[index]
        options, result = dict(run.options), run.result

        def script(dialog):
            fill(dialog, {"Uncertainty": "None", "Confidence level (%)": "80"})
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
        window.edit_cell(title, 16, 1, "1")  # the censored subject of "Censored" becomes an event
        self.wait()
        edited = worksheet()
        edited.loc[16, "Event"] = 1
        sheet = window.project.runs[index].result.tables[SHEET]
        self.compare(sheet, edited, 95, "after the edit")
        self.expect((sheet[sheet["Group"] == "Censored"]["Status"] == "Available").any(),
                    "the edited group still has no band")
        self.shot(window, "page-after-edit")
        window.open_sheet(("data", title))
        window.sheet.setCurrentIndex(window.sheet.model().index(0, 1))
        window.toggle_exclusion()
        self.wait()
        self.compare(window.project.runs[index].result.tables[SHEET], edited.drop(index=0), 95, "after the exclusion")
        window.open_sheet(("graph", index))
        self.shot(window, "page-after-exclusion")
        window.undo()
        self.wait()
        self.compare(window.project.runs[index].result.tables[SHEET], edited, 95, "after undo")
        window.undo()
        self.wait()
        self.compare(window.project.runs[index].result.tables[SHEET], worksheet(), 95, "after the second undo")
        self.note("edit, exclusion and two undos recalculated against the oracle")

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
            self.expect(reopened.options.get("Uncertainty") == SIMULTANEOUS, f"reopened recipe {reopened.options}")
            for name, frame in self.reference.items():
                try:
                    pd.testing.assert_frame_equal(reopened.result.tables[name], frame, obj=name)
                except AssertionError as error:
                    self.problem(f"reopened {name} differs: {error}")
            self.shot(other, "reopened")
            self.note("saved project reopened with identical sheets and the canonical recipe")
        finally:
            other.project.dirty = False
            other.close()
            other.deleteLater()
            self.app.processEvents()

    def report(self):
        screen = self.app.primaryScreen()
        geometry = screen.availableGeometry() if screen else QRect()
        platform_name = self.app.platformName()
        nature = ("virtual display (Xvfb or offscreen): the DPI is a fixed software value, not a physical panel"
                  if os.environ.get("DISPLAY") and platform_name in ("xcb", "offscreen") and
                  not os.environ.get("TRAMA_PHYSICAL_DISPLAY") else "physical display")
        lines = [f"Trama Qt · Kaplan–Meier simultaneous bands smoke · Python {platform.python_version()} · "
                 f"PySide6 {PYSIDE_VERSION} · Qt {qVersion()} · platform {platform_name} · "
                 f"theme {'dark' if self.dark else 'light'}",
                 f"Screen {screen.name() if screen else '?'}: available {geometry.width()}×{geometry.height()}, "
                 f"device pixel ratio {screen.devicePixelRatio() if screen else '?'}, "
                 f"logical DPI {screen.logicalDotsPerInch() if screen else '?'}",
                 f"Nature of the DPI: {nature}. Windows native: NOT TESTED.",
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
    smoke = BandsSmoke(folder, dark)
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
        print("Usage: python -m trama_qt.survival_bands_smoke FOLDER [--dark]")
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
    print(f"Kaplan–Meier simultaneous bands smoke: {status} ({folders[0]})")
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
