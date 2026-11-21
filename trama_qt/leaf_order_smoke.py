"""Optimal leaf ordering on the real Qt window: ``python -m trama_qt.leaf_order_smoke FOLDER [--dark]``.

The conventions of ``python -m trama_qt --smoke`` (``trama_qt/smoke.py``): the real screen, preferences in a
temporary folder, synthetic data only, English then Italian. In each language it opens the synthetic table
``tests/data/leaf_order/profili-sintetici.csv`` (7 samples × 5 variables), presses Analyze, has the size limit
refused on the field, changes ``Leaf ordering`` from the keyboard and runs the clustering on rows and columns. It
records the dialog and the result pages, checks that the heat map cells follow the report, draws a linked
Hierarchy graph (turned horizontal without another fit), puts the Default and Optimal figures side by side in a
two-panel layout, exports, saves and reopens the project, edits and excludes a cell (automatic recalculation)
and cancels the ordering of a large table.

Writes into FOLDER:

- ``<lang>-dialog.png``, ``-dialog-limit``, ``-dialog-keyboard``, ``-page-graph``, ``-page-row-order``,
  ``-page-column-order``, ``-page-costs``, ``-page-linked``, ``-layout`` (PNG as drawn at this scale);
- in the first language only: ``leaf-order.png/.svg/.pdf``, ``layout.png/.svg/.pdf``, ``row-leaf-order.csv``,
  ``column-leaf-order.csv`` and ``foglie.alab``;
- ``report.txt`` (screen, scale, theme, timings, checks, problems) and ``status.txt`` (PASS or FAIL).

Exit code 0 on PASS, 1 on FAIL. On Linux an emulated screen is ``QT_QPA_PLATFORM="offscreen:configfile=..."``
(see ``docs/qt-migration.md``).
"""
import os
from pathlib import Path
import re
import sys
import tempfile
from threading import Event
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

from analisi import hierarchical_workbench as hw  # noqa: E402
from analisi import leaf_order  # noqa: E402
from analisi.hierarchical_style import describe_hierarchical_artists  # noqa: E402

from .smoke import LANGUAGES, Smoke  # noqa: E402

FIXTURE = Path(__file__).resolve().parent.parent / "tests" / "data" / "leaf_order" / "profili-sintetici.csv"
METHOD = "Hierarchical clustering"
LINKED = "Hierarchy graph"
TITLE = "Profili sintetici"
BIG = "Tabella grande"
OVER = "Tabella oltre il limite"
VARIABLES = ["Cold", "Warm", "Salt", "Oxygen", "Light"]
RECIPE = {"Variables": VARIABLES, "Observation labels": "Label", "Direction": "Rows and columns",
          "Scale columns": "None", "Scale rows": "None", "Linkage": "average", "Distance": "cityblock",
          "Graph output": "Heat map", "Leaf ordering": "Optimal"}
COSTS = {"Row": (559.0, 520.0), "Column": (519.0, 492.0)}  # original and final cost, measured on the fixture
LEAVES = 1200  # large enough that the ordering is still running half a second after it started


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


class LeafOrderSmoke(Smoke):
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

    # -- the dialog --------------------------------------------------------------------------------------
    def first_dialog(self, dialog):
        self.pick(dialog, METHOD)
        self.shot(dialog, "dialog")
        combo = dialog.controls["Leaf ordering"][1]
        self.expect(combo.currentData() == "Default", f"Leaf ordering starts as {combo.currentData()!r}")

        fill(dialog, RECIPE)
        fill(dialog, {"Leaf ordering": "Default"})  # the keyboard alone moves the choice
        dialog.focus_field("Leaf ordering")
        QTest.keyClick(combo, Qt.Key.Key_Down)
        self.expect(combo.currentData() == "Optimal", f"the Down key left {combo.currentData()!r}")
        self.shot(dialog, "dialog-keyboard")
        dialog.accept()
        self.expect(dialog.result is not None, f"the corrected dialog was refused: {dialog.banner.text()!r}")
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
            data = self.folder / f"{TITLE}.csv"
            data.write_bytes(FIXTURE.read_bytes())
            window.open_path(data)
            self.wait()
            self.expect(window.selected == ("data", TITLE), f"table not opened: {window.selected}")

            started = time.perf_counter()
            self.ask(window.actions["analyze"].trigger, self.first_dialog)
            self.wait()
            self.note(f"first calculation (7 rows, 5 columns, both axes): {time.perf_counter() - started:.2f} s")
            index = len(window.project.runs) - 1
            run = window.project.runs[index]
            self.expect(run.calculation_error is None and run.result is not None,
                        f"not calculated: {run.calculation_error}")
            self.expect(run.options["Leaf ordering"] == "Optimal", "the recipe lost Leaf ordering")
            self.expect(window.selected == ("graph", index), "the figure did not open first")
            self.shot(window, "page-graph")
            self.check_run(run)
            self.pages(run, index, first)

            window.open_sheet(("graph", index))
            if first:
                for suffix in ("png", "svg", "pdf"):
                    self.save_as(window.export, self.folder / f"leaf-order.{suffix}")
                self.check_vector(self.folder / "leaf-order.svg", self.folder / "leaf-order.pdf")

            self.linked_graph(run, index)
            plain_index = self.plain_run(index)
            self.layout(first, run, window.project.runs[plain_index])
            if first:
                window.project.save(self.folder / "foglie.alab")

            self.edit_and_exclude(index, plain_index)
            self.save_and_reopen(index)
            self.limit()
            self.cancel()
        except Exception:  # noqa: BLE001 - the report must say what broke, then the next language runs.
            self.problem("stopped:\n" + traceback.format_exc())
        finally:
            window.project.dirty = False
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def pages(self, run, index, first):
        window = self.window
        window.open_sheet(("result", index))
        names = list(run.result.tables)
        for name, shot in (("Row leaf order", "page-row-order"), ("Column leaf order", "page-column-order"),
                           ("Leaf order costs", "page-costs")):
            window.result_tabs.setCurrentIndex(names.index(name))
            self.shot(window, shot)
            if first and name != "Leaf order costs":
                self.save_as(window.export, self.folder / f"{name.lower().replace(' ', '-')}.csv")

    def check_run(self, run):
        tables = run.result.tables
        for axis, (original, final) in COSTS.items():
            report = tables[f"{axis} leaf order"]
            self.expect(list(report.columns) == ["Position", "Label", "Input index", "Distance from previous"],
                        f"{axis} leaf order columns: {list(report.columns)}")
            self.expect(pd.isna(report["Distance from previous"].iloc[0]), f"{axis}: the first distance is not empty")
            total = float(report["Distance from previous"].iloc[1:].sum())
            self.expect(abs(total - final) < 1e-9, f"{axis}: the report adds up to {total}, not {final}")
            costs = tables["Leaf order costs"].set_index("Axis").loc[axis]
            self.expect((costs["Original cost"], costs["Final cost"]) == (original, final),
                        f"{axis} costs {costs['Original cost']} → {costs['Final cost']}, expected {original} → {final}")
            self.note(f"{axis}: cost {original:g} → {final:g}, order {report['Label'].tolist()}")
        self.expect_cells(run)

    def expect_cells(self, run):
        """The dendrograms, the captions and the heat map cells follow the report."""
        meta = describe_hierarchical_artists(run.result.figure)
        rows, cols = meta["row"]["leaf_order"], meta["column"]["leaf_order"]
        for axis, order in (("Row", rows), ("Column", cols)):
            report = run.result.tables[f"{axis} leaf order"]
            self.expect([i + 1 for i in order] == report["Input index"].tolist(), f"the {axis.lower()} dendrogram "
                        "does not follow the report")
        frame = self.window.project.tables[TITLE].frame(mask_excluded=True)
        scaled = frame[VARIABLES].dropna().to_numpy(float)
        cells = np.asarray(meta["heatmap"]["image"].get_array())
        self.expect(np.array_equal(cells, scaled[np.ix_(rows, cols)]), "the heat map cells do not follow the order")

    def check_vector(self, svg, pdf):
        text = svg.read_text(encoding="utf-8")
        size = re.search(r'<svg[^>]*width="([^"]+)"[^>]*height="([^"]+)"', text)
        paths, texts, images = text.count("<path"), text.count("<text"), text.count("<image")
        self.expect(paths > 10, "the SVG has no vector paths")
        self.expect(images == 2, f"the SVG has {images} raster images (heat map cells and colour bar expected)")
        header = pdf.read_bytes()[:5]
        self.expect(header == b"%PDF-", f"{pdf.name} is not a PDF")
        self.note(f"leaf-order.svg: page {size.group(1)} × {size.group(2)}, {paths} paths, {texts} text elements "
                  f"(text drawn as glyph paths when 0), {images} raster images (heat map cells and colour bar); "
                  f"leaf-order.pdf: {pdf.stat().st_size} bytes" if size else "leaf-order.svg: no page size")

    # -- a linked graph, a plain run for comparison, a layout ------------------------------------------------
    def linked_graph(self, run, index):
        window = self.window
        window.open_sheet(("result", index))
        window.result_tabs.setCurrentIndex(list(run.result.tables).index("Row Merges"))
        before = len(window.project.runs)
        with mock.patch.object(hw, "hierarchical", side_effect=AssertionError("a second clustering")):
            self.ask(window.actions["analyze_result"].trigger,
                     self.recipe_dialog({"Graph output": "Dendrogram", "Dendrogram orientation": "Horizontal"},
                                        LINKED))
            self.wait()
        if not self.expect(len(window.project.runs) == before + 1, "the linked Hierarchy graph was not added"):
            return None
        graph = window.project.runs[-1]
        self.expect(graph.calculation_error is None and graph.result is not None,
                    f"linked graph not calculated: {graph.calculation_error}")
        window.open_sheet(("graph", len(window.project.runs) - 1))
        self.shot(window, "page-linked")
        row = describe_hierarchical_artists(graph.result.figure).get("row")
        wanted = describe_hierarchical_artists(run.result.figure)["row"]["leaf_order"]
        self.expect(row is not None and row["leaf_order"] == wanted, "the linked graph does not follow the order")
        self.note("linked Hierarchy graph (horizontal) follows the row order without another clustering")
        return graph

    def plain_run(self, index):
        window = self.window
        window.open_sheet(("data", TITLE))
        self.ask(window.actions["analyze"].trigger, self.recipe_dialog({**RECIPE, "Leaf ordering": "Default"}))
        self.wait()
        plain_index = len(window.project.runs) - 1
        plain = window.project.runs[plain_index]
        self.expect(plain_index != index and plain.calculation_error is None and plain.result is not None,
                    "the Default run was not added")
        if plain.result is not None:
            self.expect("Row leaf order" not in plain.result.tables, "Default added a leaf order sheet")
        return plain_index

    def layout(self, first, run, plain):
        from analisi.layout_geometry import AUTO_PAPER, WHITE
        from analisi.presentation import Layout
        window = self.window
        key = window.project.put_layout(Layout("Before and after", 2, [plain.reference, run.reference],
                                               AUTO_PAPER, WHITE))
        window.refresh()
        window.open_sheet(("layout", key))
        self.wait()
        self.shot(window, "layout")
        if first:
            for suffix in ("png", "svg", "pdf"):
                self.save_as(window.export, self.folder / f"layout.{suffix}")
            text = (self.folder / "layout.svg").read_text(encoding="utf-8")
            self.expect(text.count("<path") > 20, "the layout SVG has too few vector paths")
            self.note(f"layout.svg: two panels, {text.count('<path')} paths, {text.count('<image')} raster images")

    # -- recalculation, projects, cancellation ---------------------------------------------------------------
    def edit_and_exclude(self, index, plain_index):
        window = self.window
        window.open_sheet(("data", TITLE))
        column = VARIABLES.index("Cold") + 1  # Label is the first column
        window.edit_cell(TITLE, 0, column, "-40")
        self.wait()
        run = window.project.runs[index]
        edited = pd.read_csv(FIXTURE)
        edited.loc[0, "Cold"] = -40
        from analisi.workbench import analyse
        fresh = analyse(METHOD, edited, RECIPE).tables
        for name in ("Row leaf order", "Column leaf order", "Leaf order costs"):
            same = run.result is not None and name in run.result.tables and \
                run.result.tables[name].equals(fresh[name])
            self.expect(same, f"{name} was not recalculated after an edit")
        self.expect_cells(run)
        self.expect("Row leaf order" not in window.project.runs[plain_index].result.tables,
                    "the Default run grew a leaf order sheet")
        window.open_sheet(("data", TITLE))
        window.sheet.setCurrentIndex(window.sheet.model().index(1, 2))
        window.toggle_exclusion()  # Sample 2, Warm
        self.wait()
        report = window.project.runs[index].result.tables["Row leaf order"]
        self.expect(len(report) == 6 and "Sample 2" not in report["Label"].tolist(),
                    f"an excluded value did not remove its row: {report['Label'].tolist()}")
        self.expect_cells(window.project.runs[index])
        self.note(f"after an edit and an exclusion: {len(report)} rows, order {report['Label'].tolist()}")

    def save_and_reopen(self, index):
        window = self.window
        before = {name: frame.copy() for name, frame in window.project.runs[index].result.tables.items()}
        count = len(window.project.runs)
        path = self.folder / f"{self.language}-reopened.alab"
        window.project.save(path)
        self.expect(window.close_project(), "the project did not close")
        window.open_path(path)
        self.wait()
        self.expect(len(window.project.runs) == count, "the reopened project lost analyses")
        window.open_sheet(("graph", index))
        self.wait()
        run = window.project.runs[index]
        self.expect(run.options["Leaf ordering"] == "Optimal", "the reopened recipe lost Leaf ordering")
        for name in ("Row leaf order", "Column leaf order", "Leaf order costs"):
            same = run.result is not None and name in run.result.tables and run.result.tables[name].equals(before[name])
            self.expect(same, f"{name} changed after saving and reopening")
        self.expect_cells(run)
        self.note("saved and reopened: recipe, sheets and cell order identical")

    def limit(self):
        """Beyond 2000 leaves the dialog refuses on the field, before any worker or matrix exists."""
        window = self.window
        wide = pd.DataFrame(np.random.default_rng(6).normal(size=(leaf_order.MAX_LEAVES + 100, 3)),
                            columns=["A", "B", "C"])
        path = self.folder / f"{OVER}.csv"
        wide.to_csv(path, index=False)
        window.open_path(path)
        self.wait()
        window.open_sheet(("data", OVER))
        starts = {"en": "Optimal leaf ordering is limited to 2000 leaves",
                  "it": "L’ordine ottimale delle foglie è limitato a 2000"}

        def refuse(dialog):
            self.pick(dialog, METHOD)
            fill(dialog, {"Variables": ["A", "B", "C"], "Direction": "Rows", "Leaf ordering": "Optimal"})
            with mock.patch.object(leaf_order, "optimal_order", side_effect=AssertionError("ordering in the dialog")):
                dialog.accept()
            self.app.processEvents()
            self.expect(dialog.result is None and dialog.banner.isVisible(), "a table beyond the limit was accepted")
            self.expect(dialog.banner.text().startswith(starts[self.language]),
                        f"limit message: {dialog.banner.text()!r}")
            self.expect(self.app.focusWidget() is dialog.controls["Leaf ordering"][1],
                        "Leaf ordering is not focused after the limit message")
            self.expect(window.job is None, "a worker started for a table beyond the limit")
            self.shot(dialog, "dialog-limit")
            self.note(f"{leaf_order.MAX_LEAVES + 100} rows refused on the field: {dialog.banner.text()}")
            fill(dialog, {"Leaf ordering": "Default"})  # the same table is fine with Default
            dialog.accept()
            self.expect(dialog.result is not None, f"Default was refused: {dialog.banner.text()!r}")
            return False

        self.ask(window.actions["analyze"].trigger, refuse)

    def cancel(self):
        window = self.window
        rng = np.random.default_rng(5)
        big = pd.DataFrame(rng.normal(size=(LEAVES, 8)), columns=[f"V{i}" for i in range(1, 9)])
        big.insert(0, "Label", [f"Obs {i}" for i in range(1, LEAVES + 1)])
        path = self.folder / f"{BIG}.csv"
        big.to_csv(path, index=False)
        window.open_path(path)
        self.wait()
        window.open_sheet(("data", BIG))
        previous = [run.result for run in window.project.runs]
        recipe = {"Variables": [f"V{i}" for i in range(1, 9)], "Observation labels": "Label", "Direction": "Rows",
                  "Scale columns": "Standardize", "Graph output": "Dendrogram", "Leaf ordering": "Optimal"}
        entered, release = Event(), Event()
        minimum = leaf_order._minplus

        def wait_for_click(left, right, cancel):
            entered.set()
            if not release.wait(10):
                raise TimeoutError("The smoke did not reach the cancellation button.")
            return minimum(left, right, cancel)

        with mock.patch.object(leaf_order, "_minplus", wait_for_click):
            try:
                self.ask(window.actions["analyze"].trigger, self.recipe_dialog(recipe))
                end = time.monotonic() + 8
                while not entered.is_set() and window.job is not None and time.monotonic() < end:
                    self.app.processEvents()
                    time.sleep(.005)
                if not self.expect(entered.is_set() and window.job is not None, "the ordering worker did not reach its first block"):
                    return
                button = window.cancel_button
                if not self.expect(button.isVisible() and button.isEnabled(), "the cancellation button is unavailable"):
                    return
                started = time.perf_counter()
                button.click()
                self.expect(window.job.control.cancel.is_set(), "the button did not cancel the job")
            finally:
                release.set()
                self.wait()
        latency = time.perf_counter() - started
        results = [run.result for run in window.project.runs]
        if self.expect(len(results) == len(previous) and all(a is b for a, b in zip(results, previous)),
                       "the cancelled calculation changed the project results"):
            self.note(f"cancel of the ordering of {LEAVES} leaves at its first block: latency {latency:.3f} s, "
                      "no analysis added, previous results kept")

    def report(self):
        screen = self.app.primaryScreen()
        geometry = screen.availableGeometry() if screen else QRect()
        lines = [f"Trama Qt · Leaf ordering smoke · PySide6 {PYSIDE_VERSION} · platform "
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
    smoke = LeafOrderSmoke(folder, dark)
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
        print("Usage: python -m trama_qt.leaf_order_smoke FOLDER [--dark]")
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
    print(f"Leaf ordering smoke: {status} ({folders[0]})")
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
