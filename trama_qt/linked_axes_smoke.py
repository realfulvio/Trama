"""Linked secondary axes on the real Qt window:
``python -m trama_qt.linked_axes_smoke FOLDER [--dark] [--size WIDTHxHEIGHT]``.

The conventions of ``python -m trama_qt --smoke`` (``trama_qt/smoke.py``): the real window, preferences in a
temporary folder, synthetic data only, English then Italian. ``--size`` emulates a screen of that size at 100%
(``QT_QPA_PLATFORM=offscreen`` with a screen file, see ``docs/qt-migration.md``); without it the real screen is used.
In each language it opens a synthetic table (temperature, time, dose), calculates XY series and then:

- ``top-axis``: Graph → Format graph… → Axes → Secondary axes… adds a top X axis in °F (multiplier 1.8, offset 32)
  and applies it;
- ``right-axis``: the Inspector adds a right Y axis in minutes, previews it on the live graph and applies it;
- ``offset-constraint``: on a logarithmic X axis the editor fixes the offset at 0 and explains why;
- ``incompatible-graph``: a graph with an independent right Y axis refuses the linked right axis, with the reason
  beside the disabled controls, and keeps the top axis available;

and checks along the way that the secondary axes are children of the graph's own Axes with their stable ids, that
the limits follow zoom, pan and inversion, that formatting twenty times never leaves more than two secondary axes,
that nothing but the style changed (data, series, title), that the project saves and reopens with them, that the SVG
export carries ``trama-linked-x`` and ``trama-linked-y`` and no raster, that a single click does not repeat the
calculation, and that no dialog clips its text at this size.

Writes into FOLDER: ``<lang>-<name>.png`` (the window or dialog as drawn), ``report.txt`` (screen, scale, theme,
timings, checks, problems), ``status.txt`` (PASS or FAIL), ``linked.alab`` and ``linked.svg`` in the first language.
Exit code 0 on PASS, 1 on FAIL. Windows and system DPI scaling are not covered by this offscreen run.
"""
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
from PySide6.QtWidgets import QDialog  # noqa: E402

from analisi.linked_axes import GID_PREFIX, linked_axes_reasons, linked_children  # noqa: E402

from .smoke import LANGUAGES, Smoke  # noqa: E402

TITLE = "groups"  # Smoke.calculate works on this table
TOP = {"x": {"multiplier": 1.8, "offset": 32.0, "label": "Temperature (°F)"}}
RIGHT = {"y": {"multiplier": 1 / 60, "offset": 0.0, "label": "Time (min)"}}
LOG = {"x": {"multiplier": 0.001, "offset": 0.0, "label": "Dose (µM → mM)"}}


def fixture():
    """Synthetic: temperature in °C, a time in seconds, and a log-spaced dose with a saturating response."""
    celsius = np.arange(0, 41, 4.0)
    seconds = 120 + 3.2 * celsius - 0.025 * celsius ** 2
    dose = np.logspace(0, 3, 11)
    return pd.DataFrame({"Celsius": celsius, "Seconds": seconds, "Dose": dose,
                         "Response": 100 * dose / (30 + dose)})


class LinkedAxesSmoke(Smoke):
    def __init__(self, folder, dark=False, size=None):
        super().__init__(folder)
        self.dark, self.size = dark, size

    def note(self, text):
        self.notes.append(f"[{self.language}] {text}")

    def expect(self, condition, text):
        if not condition:
            self.problem(text)
        return bool(condition)

    # -- helpers -----------------------------------------------------------------------------------------
    def calculate(self, method, options):
        """``Smoke.calculate`` for options some of which (``Series side``) have no control in the analysis dialog."""
        from .analysis_dialog import AnalysisDialog
        window = self.window
        frame = window.project.tables[TITLE].frame(mask_excluded=True)
        dialog = AnalysisDialog(window, frame, current=(method, {}))
        for name, value in options.items():
            if name not in dialog.controls:
                continue
            control = dialog.controls[name][1]
            if isinstance(value, list) and hasattr(control, "item"):
                for row in range(control.count()):
                    item = control.item(row)
                    item.setCheckState(Qt.CheckState.Checked if item.text() in value else Qt.CheckState.Unchecked)
        values = dialog.options()
        dialog.deleteLater()
        values.update(options)
        window.calculate_candidate(window.project.candidate(TITLE, method, values), frame, None)
        self.wait()
        run = window.project.runs[-1]
        if run.result is None or run.calculation_error:
            raise RuntimeError(f"{method} was not calculated: {run.calculation_error}")
        return window.project.runs.index(run)

    def editor(self, record, name=None):
        """The editor dialog runs ``record`` as typed text, is recorded, and answers Apply."""
        from .linked_axes import LinkedAxesDialog

        def exec_(dialog):
            dialog.show()
            self.app.processEvents()
            for dimension in ("x", "y"):
                dialog.boxes[dimension].setChecked(dimension in record)
                for field, value in (record.get(dimension) or {}).items():
                    edit = dialog.fields[(dimension, field)]
                    if edit.isEnabled():
                        edit.setText(str(value).replace(".", ",") if self.language == "it" and field != "label"
                                     else str(value))
            self.app.processEvents()
            if name:
                self.seen[name] = dialog
                self.shot(dialog, name)
            dialog.accept()
            return QDialog.DialogCode.Accepted if dialog.result is not None else QDialog.DialogCode.Rejected

        return mock.patch.object(LinkedAxesDialog, "exec", exec_)

    def open_graph(self, index):
        window = self.window
        window.open_sheet(("graph", index))
        self.wait()
        self.app.processEvents()
        return window.project.runs[index]

    def format_graph(self, script):
        """Graph → Format graph… with the dialog driven by ``script`` instead of by clicks."""
        from .graph_format import GraphFormatDialog

        def exec_(dialog):
            dialog.show()
            self.app.processEvents()
            script(dialog)
            return QDialog.DialogCode.Accepted if dialog.result is not None else QDialog.DialogCode.Rejected

        with mock.patch.object(GraphFormatDialog, "exec", exec_):
            self.window.format_graph()
        self.app.processEvents()

    def reveal(self, widget):
        """Scroll the page that holds ``widget`` until it shows, as a user would to reach it."""
        from PySide6.QtWidgets import QScrollArea
        area = widget.parentWidget()
        while area is not None and not isinstance(area, QScrollArea):
            area = area.parentWidget()
        if area is not None:
            area.ensureWidgetVisible(widget, 0, 60)
        self.app.processEvents()

    def draw(self, figure):
        figure.canvas.draw()
        self.app.processEvents()

    def children(self, run):
        return linked_children(run.result.figure.axes[0])

    def labels_inside(self, run, name):
        """The tick labels and the axis names of both secondary axes lie inside the figure."""
        figure = run.result.figure
        self.draw(figure)
        renderer = figure.canvas.get_renderer()
        page = figure.bbox
        for dimension, child in self.children(run).items():
            box = child.get_tightbbox(renderer)
            inside = (box.x0 >= page.x0 - 1 and box.x1 <= page.x1 + 1 and box.y0 >= page.y0 - 1
                      and box.y1 <= page.y1 + 1)
            self.expect(inside, f"{name}: the {dimension.upper()} secondary axis leaves the figure "
                                f"({box.x0:.0f}, {box.y0:.0f}, {box.x1:.0f}, {box.y1:.0f}) of {page.width:.0f}×{page.height:.0f}")

    def follows(self, run, name):
        """Limits of the secondary axes follow zoom, pan and inversion of the primary axes."""
        figure = run.result.figure
        axes = figure.axes[0]
        original = axes.get_xlim(), axes.get_ylim()
        for label, limits in (("zoom", (3.0, 9.0)), ("pan", (-2.0, 4.0)), ("inversion", (9.0, 3.0))):
            axes.set_xlim(*limits)
            self.draw(figure)
            for dimension, child in self.children(run).items():
                item = run.style["linked_axes"][dimension]
                primary = getattr(axes, f"get_{dimension}lim")()
                got = getattr(child, f"get_{dimension}lim")()
                want = [item["multiplier"] * value + item["offset"] for value in primary]
                if not np.allclose(got, want, rtol=1e-9, atol=1e-9):
                    self.problem(f"{name}: after {label} the {dimension.upper()} secondary limits are {got}, "
                                 f"expected {want}")
        axes.set_xlim(*original[0])
        axes.set_ylim(*original[1])
        self.draw(figure)

    def reformat_twenty_times(self, run, name):
        figure = run.result.figure
        start = time.perf_counter()
        for index in range(20):
            style = dict(run.style)
            record = json.loads(json.dumps(style["linked_axes"]))
            first = next(iter(record))
            record[first]["label"] = f"{record[first]['label']} ({index})"[:60]
            style["linked_axes"] = record
            self.window.project.apply_format(run, style)
        elapsed = time.perf_counter() - start
        count = len(figure.axes[0].child_axes)
        self.expect(count <= 2, f"{name}: {count} secondary axes after 20 reformats")
        self.expect(len(figure.axes) == 1, f"{name}: {len(figure.axes)} axes in the figure after 20 reformats")
        self.note(f"{name}: 20 reformats → {count} secondary axes, {elapsed / 20 * 1000:.0f} ms each")

    # -- the scenarios -----------------------------------------------------------------------------------
    def top_axis(self):
        window = self.window
        index = self.calculate("XY series", {"X": "Celsius", "Y columns": ["Seconds"]})
        run = self.open_graph(index)
        self.shot(window, "graph-before")
        before = [(line.get_xdata().copy(), line.get_ydata().copy()) for line in run.result.figure.axes[0].lines]
        title, calls = run.result.figure.axes[0].get_title(), []

        def script(dialog):
            dialog.tabs.setCurrentIndex(1)
            self.app.processEvents()
            self.reveal(dialog.linked_note)
            self.shot(dialog, "format-axes")
            self.expect(dialog.linked_button.isEnabled(), "the Secondary axes button is disabled on an XY graph")
            with self.editor(TOP, "editor-top"):
                dialog.edit_linked()
            self.expect(dialog.linked_axes == TOP, f"the dialog holds {dialog.linked_axes}")
            dialog.accept()
            self.expect(dialog.result is not None, f"Format graph refused: {dialog.banner.text()!r}")

        start = time.perf_counter()
        with mock.patch("analisi.workbench._analyse", side_effect=lambda *a, **k: calls.append(1)):
            self.format_graph(script)
        self.note(f"top axis applied from Format graph in {time.perf_counter() - start:.2f} s")
        self.expect(not calls, "applying the style repeated the calculation")
        run = window.project.runs[index]
        self.expect(sorted(self.children(run)) == ["x"], f"secondary axes: {sorted(self.children(run))}")
        self.expect(run.style.get("linked_axes") == TOP, f"saved style: {run.style.get('linked_axes')}")
        figure = run.result.figure
        self.expect(figure.axes[0].get_title() == title, "the title changed")
        self.expect(all(np.array_equal(line.get_xdata(), x) and np.array_equal(line.get_ydata(), y)
                        for line, (x, y) in zip(figure.axes[0].lines, before)), "the plotted data changed")
        self.expect(figure.axes[0].get_xlim()[0] <= 0, "the primary limits changed unexpectedly")
        window.open_sheet(("graph", index))
        self.app.processEvents()
        self.shot(window, "top-axis")
        self.labels_inside(run, "top-axis")
        self.follows(run, "top-axis")
        self.reformat_twenty_times(run, "top-axis")
        return index

    def right_axis(self, index):
        window = self.window
        run = self.open_graph(index)
        window.toggle_inspector()
        inspector = window.inspector
        if not self.expect(inspector is not None, "the Inspector did not open"):
            return
        self.expect(inspector.linked_button.isEnabled(), "the Inspector button is disabled")
        before = len(self.children(run))
        with self.editor({**TOP, **RIGHT}, "editor-both"):
            inspector.edit_linked()
        self.app.processEvents()
        self.reveal(inspector.linked_note)
        self.expect(sorted(self.children(run)) == ["x", "y"], f"previewed axes: {sorted(self.children(run))}")
        self.expect(before == 1, f"the graph had {before} secondary axes before")
        self.expect("linked_axes" not in (run.style or {}) or "y" not in run.style["linked_axes"],
                    "the preview was confirmed before Apply")
        self.shot(window, "right-axis")
        self.labels_inside(run, "right-axis")
        self.expect(inspector.apply(), f"Apply refused: {inspector.status.text() if hasattr(inspector, 'status') else ''}")
        self.expect(run.style["linked_axes"].get("y") == RIGHT["y"], f"saved style: {run.style['linked_axes']}")
        self.follows(run, "right-axis")
        window.toggle_inspector()  # closes the panel; the confirmed style stays
        self.app.processEvents()
        self.expect(sorted(self.children(run)) == ["x", "y"], "closing the Inspector changed the axes")

    def offset_constraint(self):
        window = self.window
        index = self.calculate("XY series", {"X": "Dose", "Y columns": ["Response"]})
        run = self.open_graph(index)
        shown = {}

        def script(dialog):
            dialog.tabs.setCurrentIndex(1)
            dialog.scales["x"].set("log")
            self.app.processEvents()
            from .linked_axes import LinkedAxesDialog

            def exec_(editor):
                editor.show()
                editor.boxes["x"].setChecked(True)
                editor.fields[("x", "multiplier")].setText("0.001")
                editor.fields[("x", "label")].setText(LOG["x"]["label"])
                self.app.processEvents()
                offset = editor.fields[("x", "offset")]
                shown.update(enabled=offset.isEnabled(), text=offset.text(), note=editor.notes["x"].text(),
                             visible=editor.notes["x"].isVisible())
                self.shot(editor, "offset-constraint")
                editor.accept()
                return QDialog.DialogCode.Accepted if editor.result is not None else QDialog.DialogCode.Rejected

            with mock.patch.object(LinkedAxesDialog, "exec", exec_):
                dialog.edit_linked()
            dialog.accept()
            self.expect(dialog.result is not None, f"Format graph refused: {dialog.banner.text()!r}")

        self.format_graph(script)
        self.expect(shown.get("enabled") is False, "the offset field stays editable on a logarithmic axis")
        self.expect(shown.get("text") in ("0", "0,0"), f"the offset field shows {shown.get('text')!r}")
        self.expect(shown.get("visible") and bool(shown.get("note")), "the logarithmic note is not visible")
        run = window.project.runs[index]
        self.expect(sorted(self.children(run)) == ["x"], f"secondary axes: {sorted(self.children(run))}")
        child = self.children(run).get("x")
        if child is not None:
            self.draw(run.result.figure)
            self.expect(child.xaxis.get_scale() == "functionlog", f"scale of the secondary axis: {child.xaxis.get_scale()}")
        window.open_sheet(("graph", index))
        self.app.processEvents()
        self.shot(window, "offset-constraint-graph")
        self.note(f"logarithmic X: offset field disabled at {shown.get('text')!r}; note: {shown.get('note')}")

    def incompatible_graph(self):
        window = self.window
        index = self.calculate("XY series", {"X": "Celsius", "Y columns": ["Seconds", "Response"],
                                             "Series side": {"Seconds": "Left", "Response": "Right"}})
        run = self.open_graph(index)
        self.expect(len(run.result.figure.axes) == 2, f"expected two Y axes, got {len(run.result.figure.axes)}")
        seen = {}

        def script(dialog):
            dialog.tabs.setCurrentIndex(1)
            self.app.processEvents()
            self.reveal(dialog.linked_note)
            seen["note"] = dialog.linked_note.text()
            self.shot(dialog, "incompatible-graph")
            from .linked_axes import LinkedAxesDialog

            def exec_(editor):
                editor.show()
                self.app.processEvents()
                seen["y_enabled"] = editor.boxes["y"].isEnabled()
                seen["x_enabled"] = editor.boxes["x"].isEnabled()
                seen["y_note"] = editor.notes["y"].text()
                self.shot(editor, "incompatible-editor")
                editor.reject()
                return QDialog.DialogCode.Rejected

            with mock.patch.object(LinkedAxesDialog, "exec", exec_):
                dialog.edit_linked()
            dialog.reject()

        self.format_graph(script)
        self.expect(bool(seen.get("note")), "no explanation beside the Secondary axes button")
        self.expect(seen.get("y_enabled") is False, "the right Y axis can be switched on beside an independent right axis")
        self.expect(seen.get("x_enabled") is True, "the top X axis is not available on this graph")
        self.expect(bool(seen.get("y_note")), "no reason in the editor for the right Y axis")
        self.note(f"independent right Y axis: {seen.get('y_note')}")
        # A saved record that cannot show keeps its style and says so, instead of failing.
        style = {**(run.style or {}), "linked_axes": {**TOP, **RIGHT}}
        window.project.apply_format(run, style)
        reasons = linked_axes_reasons(run.result.figure)
        self.expect(set(reasons) == {"y"}, f"reasons: {reasons}")
        self.expect(sorted(self.children(run)) == ["x"], f"secondary axes: {sorted(self.children(run))}")
        self.expect(bool(run.result.style_warning), "no note when a saved axis cannot be drawn")
        self.expect(run.style["linked_axes"] == {**TOP, **RIGHT}, "the record was not kept")
        window.open_sheet(("graph", index))
        self.app.processEvents()
        self.shot(window, "incompatible-note")
        self.note(f"saved right axis on that graph: {run.result.style_warning}")

    def exports_and_project(self, index):
        window = self.window
        from .window import export_graph
        run = window.project.runs[index]
        first = self.language == LANGUAGES[0]
        svg = self.folder / ("linked.svg" if first else f"{self.language}-linked.svg")
        export_graph(run.result.figure, svg)
        text = svg.read_text(encoding="utf-8")
        for gid in (GID_PREFIX + "x", GID_PREFIX + "y"):
            self.expect(f'id="{gid}"' in text, f"{svg.name} has no {gid}")
        self.expect("<image" not in text, f"{svg.name} contains a raster")
        self.note(f"SVG export: {svg.stat().st_size // 1024} KiB, secondary axes carry their ids, no raster")
        count = len(window.project.runs)
        path = self.folder / ("linked.alab" if first else f"{self.language}-linked.alab")
        window.project.save(path)
        self.expect(window.close_project(), "the project did not close")
        window.open_path(path)
        self.wait()
        self.expect(len(window.project.runs) == count, "the reopened project lost analyses")
        reopened = self.open_graph(index)
        self.expect(sorted(self.children(reopened)) == ["x", "y"],
                    f"after reopening: {sorted(self.children(reopened))}")
        self.shot(window, "reopened")
        self.note("saved, closed and reopened: both secondary axes are drawn again")

    # -- the run -----------------------------------------------------------------------------------------
    def run_language(self, language):
        from analisi.i18n import set_language
        from . import theme
        from .window import MainWindow
        self.language = language
        set_language(language)
        theme.install_qt_translations(self.app, language)
        self.window = window = MainWindow()
        self.seen = {}
        window.error = lambda error: self.problem(f"error shown: {error}")
        available = self.screen_rect(window)
        window.resize(available.width() if self.size else min(1280, available.width()),
                      available.height() if self.size else min(800, available.height()))
        window.show()
        theme.keep_on_screen(window)
        self.app.processEvents()
        try:
            data = self.folder / f"{TITLE}.csv"
            fixture().to_csv(data, index=False)
            window.open_path(data)
            self.wait()
            self.expect(window.selected == ("data", TITLE), f"table not opened: {window.selected}")
            index = self.top_axis()
            self.right_axis(index)
            self.offset_constraint()
            self.incompatible_graph()
            self.exports_and_project(index)
        except Exception:  # noqa: BLE001 - the report must say what broke, then the next language runs.
            self.problem("stopped:\n" + traceback.format_exc())
        finally:
            window.project.dirty = False
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def report(self):
        screen = self.app.primaryScreen()
        geometry = screen.availableGeometry() if screen else QRect()
        lines = [f"Trama Qt · Linked secondary axes smoke · PySide6 {PYSIDE_VERSION} · platform "
                 f"{self.app.platformName()} · theme {'dark' if self.dark else 'light'}",
                 f"Screen {screen.name() if screen else '?'}: available {geometry.width()}×{geometry.height()}, "
                 f"device pixel ratio {screen.devicePixelRatio() if screen else '?'}, "
                 f"logical DPI {screen.logicalDotsPerInch() if screen else '?'}",
                 f"Screenshots: {self.shots}", "Windows and system DPI scaling: not covered by this run.", ""]
        lines += self.notes + [""]
        lines += self.problems or ["No problems found."]
        (self.folder / "report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        status = "FAIL" if self.problems else "PASS"
        (self.folder / "status.txt").write_text(status + "\n", encoding="utf-8")
        return status


def run(folder, languages=LANGUAGES, dark=False, size=None):
    """Run the acceptance in each language; returns "PASS" or "FAIL" (also written to ``status.txt``)."""
    from analisi.i18n import active_language, set_language
    from . import theme
    smoke = LinkedAxesSmoke(folder, dark, size)
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
    size = None
    if "--size" in argv:
        position = argv.index("--size")
        try:
            width, height = (int(part) for part in argv[position + 1].lower().split("x"))
        except (IndexError, ValueError):
            print("Usage: python -m trama_qt.linked_axes_smoke FOLDER [--dark] [--size WIDTHxHEIGHT]")
            return 2
        size = (width, height)
        del argv[position:position + 2]
    folders = [argument for argument in argv if not argument.startswith("--")]
    if len(folders) != 1:
        print("Usage: python -m trama_qt.linked_axes_smoke FOLDER [--dark] [--size WIDTHxHEIGHT]")
        return 2
    dark = "--dark" in argv
    with tempfile.TemporaryDirectory() as config:
        if size is not None:  # an emulated screen at 100% (96 dpi), not the machine's own
            screen = Path(config) / "screen.json"
            screen.write_text(json.dumps({"screens": [{"name": "smoke", "x": 0, "y": 0, "width": size[0],
                                                       "height": size[1], "logicalDpi": 96, "logicalBaseDpi": 96,
                                                       "dpr": 1.0}]}), encoding="utf-8")
            os.environ["QT_QPA_PLATFORM"] = f"offscreen:configfile={screen}"
        with mock.patch.dict(os.environ, {"APPDATA": config, "XDG_CONFIG_HOME": config}):
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
            status = run(folders[0], dark=dark, size=size)
    print(f"Linked axes smoke: {status} ({folders[0]})")
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
