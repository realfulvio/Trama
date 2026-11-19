"""Desktop acceptance of the Qt window: ``python -m trama_qt --smoke FOLDER``.

Runs on the real screen (not offscreen) in English and Italian. It opens a small project, calculates a result,
graphs and a layout, opens every window command that shows a dialog, and writes into FOLDER:

- ``<lang>-<name>.png``: the main window on each sheet and every dialog, as drawn at the current scale;
- ``report.txt``: screen, scale and Qt version, then every problem found;
- ``status.txt``: ``PASS`` or ``FAIL``.

A dialog fails when it does not fit the available screen or when a button, check box or label is narrower than
its text needs (clipped at this scale). Exit code 0 on PASS, 1 on FAIL.
"""
from contextlib import contextmanager
from pathlib import Path
import time
import traceback

import pandas as pd
from PySide6 import __version__ as PYSIDE_VERSION
from PySide6.QtCore import QRect
from PySide6.QtWidgets import QAbstractButton, QApplication, QDialog, QLabel, QMessageBox, QWidget

LANGUAGES = ("en", "it")


class Smoke:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.app = QApplication.instance()
        self.problems, self.shots, self.language = [], 0, "en"
        self.window = None

    # -- checks ---------------------------------------------------------------------------------------
    def problem(self, text):
        self.problems.append(f"[{self.language}] {text}")

    def screen_rect(self, widget):
        screen = widget.screen() or self.app.primaryScreen()
        return screen.availableGeometry()

    def check(self, widget, name):
        """Fits the screen; no visible button, check box or one-line label is clipped."""
        frame = widget.frameGeometry()
        available = self.screen_rect(widget)
        if frame.width() > available.width() or frame.height() > available.height():
            self.problem(f"{name}: {frame.width()}×{frame.height()} does not fit the screen "
                         f"{available.width()}×{available.height()}")
        for child in widget.findChildren(QWidget):
            if not child.isVisibleTo(widget) or QWidget.width(child) <= 0:
                continue
            if isinstance(child, QAbstractButton) and child.text():
                needed = child.minimumSizeHint().width()
            elif isinstance(child, QLabel) and child.text() and not child.wordWrap() and child.pixmap().isNull():
                needed = child.minimumSizeHint().width()
            else:
                continue
            if QWidget.width(child) + 1 < needed:
                text = child.text().replace("\n", " ")[:60]
                self.problem(f"{name}: '{text}' is {QWidget.width(child)} px wide, its text needs {needed} px")

    def shot(self, widget, name):
        self.app.processEvents()
        self.check(widget, name)
        path = self.folder / f"{self.language}-{name}.png"
        if not widget.grab().save(str(path)):
            self.problem(f"{name}: screenshot not written")
        self.shots += 1

    def dialog(self, dialog, name):
        """Show a dialog the smoke built itself, record it and close it."""
        dialog.show()
        self.app.processEvents()
        self.shot(dialog, name)
        dialog.reject()
        dialog.deleteLater()

    @contextmanager
    def dialogs(self, prefix):
        """Every dialog a command opens is shown, recorded and cancelled instead of waiting for a click."""
        original = QDialog.exec
        seen = []

        def capture(dialog):
            if isinstance(dialog, QMessageBox):
                self.problem(f"{prefix}: message shown: {dialog.text()}")
                return QMessageBox.StandardButton.Ok
            name = f"{prefix}-{type(dialog).__name__}"
            seen.append(name)
            dialog.show()
            self.app.processEvents()
            self.shot(dialog, name)
            dialog.reject()
            return QDialog.DialogCode.Rejected

        QDialog.exec = capture
        try:
            yield seen
        finally:
            QDialog.exec = original
        if not seen:
            self.problem(f"{prefix}: no dialog opened")

    # -- project -----------------------------------------------------------------------------------
    def wait(self, timeout=120):
        end = time.monotonic() + timeout
        while self.window.job is not None and time.monotonic() < end:
            self.app.processEvents()
            time.sleep(0.02)
        self.app.processEvents()
        if self.window.job is not None:
            raise RuntimeError("calculation still running")

    def calculate(self, method, options):
        from .analysis_dialog import AnalysisDialog
        window = self.window
        title = "groups"
        frame = window.project.tables[title].frame(mask_excluded=True)
        dialog = AnalysisDialog(window, frame, current=(method, {}))
        for name, value in options.items():
            control = dialog.controls[name][1]
            if isinstance(value, list) and hasattr(control, "item"):
                from PySide6.QtCore import Qt
                for row in range(control.count()):
                    item = control.item(row)
                    item.setCheckState(Qt.CheckState.Checked if item.text() in value else Qt.CheckState.Unchecked)
        values = dialog.options()
        dialog.deleteLater()
        values.update(options)
        candidate = window.project.candidate(title, method, values)
        window.calculate_candidate(candidate, frame, None)
        self.wait()
        run = window.project.runs[-1]
        if run.result is None or run.calculation_error:
            raise RuntimeError(f"{method} was not calculated: {run.calculation_error}")
        return window.project.runs.index(run)

    def build(self):
        from analisi.layout_geometry import AUTO_PAPER, WHITE
        from analisi.presentation import Layout
        window = self.window
        data = self.folder / "groups.csv"
        pd.DataFrame({"Control": [4.1, 5.0, 4.7, 5.3, 4.9, 5.1], "Treated": [5.9, 6.3, 6.1, 5.7, 6.6, 6.2]}).to_csv(
            data, index=False)
        window.open_path(data)
        self.wait()
        refs = {"result": self.calculate("Transform", {"Variables": ["Control", "Treated"],
                                                       "Operation": "Absolute value"}),
                "paired": self.calculate("Paired t-test (columns)", {"First": "Control", "Second": "Treated"}),
                "column": self.calculate("Column graph", {"Variables": ["Control", "Treated"]}),
                "box": self.calculate("Box / violin plot", {"Variables": ["Control", "Treated"]}),
                "xy": self.calculate("XY series", {"X": "Control", "Y columns": ["Treated"]})}
        runs = window.project.runs
        layout = Layout("Figure 1", 2, [runs[refs["column"]].reference, runs[refs["box"]].reference],
                        AUTO_PAPER, WHITE)
        refs["layout"] = window.project.put_layout(layout)
        window.refresh()
        return refs

    # -- the run -----------------------------------------------------------------------------------
    def run_language(self, language):
        from analisi.i18n import set_language
        from . import theme
        from .window import MainWindow
        self.language = language
        set_language(language)
        theme.install_qt_translations(self.app, language)
        self.window = window = MainWindow()
        window.error = lambda error: self.problem(f"error shown: {error}")
        available = self.screen_rect(window)
        window.resize(min(1280, available.width()), min(800, available.height()))
        window.show()
        theme.keep_on_screen(window)
        self.app.processEvents()
        try:
            self.shot(window, "home")
            refs = self.build()
            window.project.dirty = False
            pages = [("data", ("data", "groups")), ("result", ("result", refs["result"])),
                     ("graph-column", ("graph", refs["column"])), ("graph-xy", ("graph", refs["xy"])),
                     ("layout", ("layout", refs["layout"]))]
            for name, ref in pages:
                window.open_sheet(ref)
                self.wait()
                self.shot(window, f"page-{name}")
            for tab in range(window.ribbon_tabs.count()):
                window.ribbon_tabs.setCurrentIndex(tab)
                self.shot(window, f"ribbon-{tab + 1}")
            window.ribbon_tabs.setCurrentIndex(0)

            window.open_sheet(("data", "groups"))
            text = self.folder / "import.txt"
            text.write_text("ID;Dose;Response\n1;0,5;10,2\n2;1,0;11,8\n", encoding="utf-8")
            for name, command in (("analyze", window.analyze), ("layout", window.new_layout),
                                  ("info", window.new_info), ("family", window.duplicate_family),
                                  ("pdf", window.export_pdf_bundle), ("formula", window.edit_formula),
                                  ("text-import", lambda: window.open_path(text, import_data=True))):
                with self.dialogs(name):
                    command()
            window.open_sheet(("result", refs["result"]))
            with self.dialogs("change-input"):
                window.change_input_result()
            window.open_sheet(("graph", refs["column"]))
            self.wait()
            for name, command in (("format", window.format_graph), ("annotations", window.edit_annotations),
                                  ("shapes", window.edit_shapes), ("pairwise", window.pairwise_comparisons),
                                  ("export-options", window.export_with_options)):
                with self.dialogs(name):
                    command()
            window.toggle_inspector()
            self.shot(window, "inspector")
            window.dispose_inspector()
            self.editors(window, refs)
        except Exception:  # noqa: BLE001 - the report must say what broke, then the next language runs.
            self.problem("stopped:\n" + traceback.format_exc())
        finally:
            window.project.dirty = False
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def editors(self, window, refs):
        """The sub-dialogs that Format Graph and the drawing lists open, built directly."""
        from .annotations import AnnotationEditor
        from .axis_breaks import AxisBreaksDialog
        from .axis_guides import AxisBandsDialog, AxisGuidesDialog, BandEditor, GuideEditor
        from .legend import LegendEditor
        from .shapes import ShapeEditor
        figure = window.project.runs[refs["column"]].result.figure
        axes = figure.axes[0]
        xy = window.project.runs[refs["xy"]].result.figure.axes[0]
        for name, dialog in (("guides", lambda: AxisGuidesDialog(window, axes, [])),
                             ("bands", lambda: AxisBandsDialog(window, axes, [])),
                             ("guide-editor", lambda: GuideEditor(window, axes)),
                             ("band-editor", lambda: BandEditor(window, axes)),
                             ("breaks", lambda: AxisBreaksDialog(window, xy, {})),
                             ("legend", lambda: LegendEditor(window, figure, {})),
                             ("annotation-editor", lambda: AnnotationEditor(window, axes)),
                             ("shape-editor", lambda: ShapeEditor(window, axes))):
            try:
                self.dialog(dialog(), name)
            except Exception as error:  # noqa: BLE001
                self.problem(f"{name}: {type(error).__name__}: {error}")

    def report(self):
        screen = self.app.primaryScreen()
        geometry = screen.availableGeometry() if screen else QRect()
        lines = [f"Trama Qt smoke · PySide6 {PYSIDE_VERSION} · platform {self.app.platformName()}",
                 f"Screen {screen.name() if screen else '?'}: available {geometry.width()}×{geometry.height()}, "
                 f"device pixel ratio {screen.devicePixelRatio() if screen else '?'}, "
                 f"logical DPI {screen.logicalDotsPerInch() if screen else '?'}",
                 f"Screenshots: {self.shots}", ""]
        lines += self.problems or ["No problems found."]
        (self.folder / "report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        status = "FAIL" if self.problems else "PASS"
        (self.folder / "status.txt").write_text(status + "\n", encoding="utf-8")
        return status


def run(folder, languages=LANGUAGES):
    """Run the acceptance in each language; returns "PASS" or "FAIL" (also written to ``status.txt``)."""
    from analisi.i18n import active_language, set_language
    smoke = Smoke(folder)
    previous = active_language()
    try:
        for language in languages:
            smoke.run_language(language)
    finally:
        set_language(previous)
        from . import theme
        theme.install_qt_translations(smoke.app, previous)
    return smoke.report()
