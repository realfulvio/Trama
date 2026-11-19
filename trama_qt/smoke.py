"""Desktop acceptance of the Qt window: ``python -m trama_qt --smoke FOLDER``.

Runs on the real screen (not offscreen) in English and Italian. It opens a small project, calculates a result,
graphs and a layout, opens every window command that shows a dialog, drives a Multifactor ANOVA through its real
editors (model terms, an error with focus, the fix, Type I order, Cancel, save, reopen and recalculation), and
writes into FOLDER:

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
        self.notes = []
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
            self.gallery(window)
            self.anova(window)
            from .global_fit_smoke import exercise as global_fit
            global_fit(self, window)
            from .projects_smoke import run as project_tabs
            project_tabs(self, window)
            from .report_smoke import run as analysis_report
            analysis_report(self, window)
            from .canvas_smoke import check_canvas
            self.notes += check_canvas(self)  # Last: it replaces the project with its own.
        except Exception:  # noqa: BLE001 - the report must say what broke, then the next language runs.
            self.problem("stopped:\n" + traceback.format_exc())
        finally:
            for session in window.sessions:
                session.project.dirty = False
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

    def anova(self, window):
        """Multifactor ANOVA through the real editors: model terms, an error with focus, the fix, Type I
        order, Run, a cancelled change, save, reopen and recalculation (synthetic 2×2 data, literal names)."""
        from copy import deepcopy
        from unittest import mock
        from analisi.anova_terms import MODEL_TERMS, SELECTED, TERM_SELECTION, label
        from analisi.anova_ss import KEY as SUMS_OF_SQUARES, TYPE_I
        from PySide6.QtCore import Qt
        from .analysis_dialog import AnalysisDialog
        a, b = "Treatment $", "Visit : phase"
        data = self.folder / "anova.csv"
        pd.DataFrame({"Response": [9, 11, 13, 15, 15, 17, 23, 25, 12, 22, 26],
                      a: ["Control"] * 4 + ["Drug"] * 4 + ["Control", "Drug", "Drug"],
                      b: ["Start", "Start", "End", "End"] * 2 + ["Start", "End", "End"]}).to_csv(data, index=False)
        window.open_path(data)
        self.wait()

        def choose(dialog, field, value):
            combo = dialog.controls[field][1]
            combo.setCurrentIndex(combo.findData(value))

        def new_model(dialog):
            factors = dialog.controls["Factors"][1]
            for row in range(factors.count()):
                item = factors.item(row)
                item.setCheckState(Qt.CheckState.Checked if item.text() in (a, b) else Qt.CheckState.Unchecked)
            dialog.tabs.setCurrentIndex(0)
            self.shot(dialog, "anova-variables")
            dialog.tabs.setCurrentIndex(1)
            choose(dialog, TERM_SELECTION, SELECTED)
            editor = dialog.controls[MODEL_TERMS][1]
            editor.boxes[(a, b)].setChecked(True)
            editor.boxes[(a,)].setChecked(False)
            editor.boxes[(b,)].setChecked(False)
            dialog.tabs.widget(1).ensureWidgetVisible(editor)
            self.shot(dialog, "anova-terms")
            dialog.tabs.setCurrentIndex(0)
            dialog.accept()  # the interaction alone breaks the hierarchy
            self.app.processEvents()
            if dialog.result is not None or not dialog.banner.isVisible():
                self.problem("anova: an interaction without its main effects was accepted")
            if dialog.tabs.currentIndex() != 1 or dialog.focusWidget() is not editor.add_button:
                self.problem(f"anova: the error did not focus Add required terms ({dialog.focusWidget()})")
            self.shot(dialog, "anova-error")
            editor.add_button.click()
            choose(dialog, SUMS_OF_SQUARES, TYPE_I)
            order = dialog.anova.order
            order.list.setCurrentRow(0)
            order.down.click()
            dialog.tabs.widget(1).ensureWidgetVisible(order)
            self.shot(dialog, "anova-type-one")
            squeezed = [box.text() for box in editor.boxes.values()
                        if box.isVisible() and box.height() < box.minimumSizeHint().height()]
            if squeezed:
                self.problem(f"anova: term check boxes drawn below their height: {squeezed}")
            dialog.accept()
            return dialog.result is not None

        def change_then_cancel(dialog):
            dialog.tabs.setCurrentIndex(1)
            dialog.anova.order.list.setCurrentRow(0)
            dialog.anova.order.down.click()
            dialog.controls[MODEL_TERMS][1].boxes[(a, b)].setChecked(False)
            self.shot(dialog, "anova-cancelled-change")
            dialog.reject()
            return False

        steps = [new_model]

        def drive(dialog):
            dialog.show()
            self.app.processEvents()
            if not steps:
                self.problem(f"anova: unexpected dialog: {dialog.banner.text()}")
                dialog.reject()
                return QDialog.DialogCode.Rejected
            accepted = steps.pop(0)(dialog)
            return QDialog.DialogCode.Accepted if accepted else QDialog.DialogCode.Rejected

        expected = [[b], [a], [b, a]]
        with mock.patch.object(AnalysisDialog, "exec", drive):
            window.analyze(method="Multifactor ANOVA")
            self.wait()
            run = window.project.runs[-1]
            if run.method != "Multifactor ANOVA" or run.result is None:
                raise RuntimeError("Multifactor ANOVA was not calculated")
            if run.options.get("Factors") != [b, a] or run.options.get(MODEL_TERMS) != expected:
                self.problem(f"anova: recipe {run.options.get('Factors')} {run.options.get(MODEL_TERMS)}")
            if list(run.result.tables["Model terms"].index) != [label(term) for term in expected]:
                self.problem("anova: Model terms sheet does not list the selected terms")
            self.shot(window, "anova-result")
            confirmed, result = deepcopy(run.options), run.result
            steps.append(change_then_cancel)
            window.change_parameters()
            self.wait()
            if run.options != confirmed or window.project.runs[-1].result is not result:
                self.problem("anova: Cancel changed the confirmed analysis")
        saved = self.folder / "anova.alab"
        window.project.save(saved)
        window.close_project()
        window.open_path(saved)
        self.wait()
        index = next(i for i, item in enumerate(window.project.runs) if item.method == "Multifactor ANOVA")
        window.open_sheet(("result", index))
        self.wait()
        reopened = window.project.runs[index]
        if reopened.options != confirmed or reopened.result is None:
            self.problem("anova: the reopened analysis differs or was not recalculated")
        self.shot(window, "anova-reopened")

    # -- the gallery -------------------------------------------------------------------------------
    def previews(self, gallery, timeout=40):
        """Wait until every visible card that can have a preview has one."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            for _ in range(8):
                self.app.processEvents()
                time.sleep(0.01)
            shown = [entry for entry in gallery.visible_entries() if entry.previewable]
            if (gallery.service.task is None and not gallery.service.queue and not gallery._scan_timer.isActive()
                    and all(gallery.service.cache.get(entry) is not None for entry in shown)):
                return
        self.problem("gallery: previews were not drawn in time")

    def expect(self, condition, text):
        if not condition:
            self.problem(f"gallery: {text}")

    def gallery(self, window):
        """View → Gallery on a project that was just opened (no result yet), then recalculated and broken."""
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QFileDialog
        from analisi.layout_geometry import AUTO_PAPER, WHITE
        from analisi.presentation import Layout
        from . import theme

        project = window.project
        project.layouts.clear()  # One numbered layout of two graphs, as a user names them: "Figure 1".
        runs = project.runs
        graphs = [index for index, run in enumerate(runs) if run.method in ("Column graph", "Box / violin plot")]
        project.put_layout(Layout("Figure 1", 2, [runs[index].reference for index in graphs], AUTO_PAPER, WHITE))
        path = self.folder / f"gallery-{self.language}.alab"
        project.save(path)
        window.close_project()
        window.open_path(path)  # Opened from the file: every sheet waits for its calculation.
        self.wait()
        window.project.dirty = False
        project = window.project
        xy = next(index for index, run in enumerate(project.runs) if run.method == "XY series")
        project.runs[xy].label = "Calibration $ A"
        window.open_sheet(("data", "groups"))
        self.shot(window, "gallery-origin")
        before = [run.result for run in project.runs]

        window.actions["gallery"].trigger()
        self.app.processEvents()
        page = window.gallery
        if page is None:
            self.problem("gallery: the Gallery action did not open the gallery")
            return
        self.expect(page.view.objectName() == "sheetGallery" and page.search.objectName() == "gallerySearch",
                    "object names of the list and the search box")
        self.expect(page.view.model().rowCount() == len([e for e in page.entries]), "every card is listed")
        self.expect(all(run.result is a for run, a in zip(project.runs, before)),
                    "opening the gallery calculated or replaced a result")
        self.previews(page)
        self.shot(window, "gallery-pending")  # Placeholders say that there is no result yet.
        QTest.keyClicks(page.search, "$")
        self.app.processEvents()
        self.expect(page.view.model().rowCount() == 1, f"search $ found {page.view.model().rowCount()} cards")
        self.shot(window, "gallery-search-dollar")
        page.view.setFocus()
        QTest.keyClick(page.view, Qt.Key.Key_Return)  # Another sheet, with Enter: calculated the ordinary way.
        self.wait()
        self.expect(window.gallery is None and window.selected == ("graph", xy), "Enter did not open the graph")
        self.expect(project.runs[xy].result is not None and all(
            run.result is None for index, run in enumerate(project.runs) if index != xy), "only the opened sheet "
                    "should be calculated")
        self.shot(window, "gallery-opened-graph")

        window.actions["gallery"].trigger()  # The "$" search is remembered: it is a state of the view.
        page = window.gallery
        self.expect(page is not None and page.search.text() == "$", "the search text is not remembered")
        self.previews(page)
        self.shot(window, "gallery-ready-card")
        entry = page.entries and next((e for e in page.entries if e.ref == ("graph", xy)), None)
        thumb = page.service.cache.get(entry) if entry is not None else None
        self.expect(thumb is not None and thumb.pixmap is not None, "the calculated graph has no preview")
        first = thumb
        page.search.clear()
        self.app.processEvents()
        self.expect(page.view.model().rowCount() == len(page.entries), "clearing the search lists every card")
        for row in range(page.view.model().rowCount()):  # The numbered layout opens as a layout.
            if page.view.model().entry(row).name == "Figure 1":
                page.view.setCurrentIndex(page.view.model().index(row))
        page.view.setFocus()
        QTest.keyClick(page.view, Qt.Key.Key_Return)
        self.wait()
        self.expect(window.selected is not None and window.selected[0] == "layout", "the layout did not open as a layout")
        self.shot(window, "gallery-opened-layout")

        window.open_sheet(("graph", xy))  # Recalculate: the preview must follow.
        self.wait()
        window.recalculate()
        self.wait()
        window.actions["gallery"].trigger()
        page = window.gallery
        self.previews(page)
        self.shot(window, "gallery-recalculated")
        entry = next((e for e in page.entries if e.ref == ("graph", xy)), None)
        again = page.service.cache.get(entry) if entry is not None else None
        self.expect(again is not None and again is not first, "the preview was not redrawn after the recalculation")
        page.closed.emit()  # Esc: back to the sheet it came from.
        self.expect(window.gallery is None and window.selected == ("graph", xy), "Back did not return to the graph")

        export = self.folder / f"gallery-export-{self.language}.png"  # Export from the page, as before.
        original = QFileDialog.getSaveFileName
        QFileDialog.getSaveFileName = staticmethod(lambda *args, **kwargs: (str(export), "PNG (*.png)"))
        try:
            window.export()
        finally:
            QFileDialog.getSaveFileName = original
        self.expect(export.is_file() and export.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n", "the figure was not exported")

        window.project.dirty = False  # A graph whose calculation fails the first time it is opened.
        window.close_project()
        window.open_path(path)
        self.wait()
        project = window.project
        box = next(index for index, run in enumerate(project.runs) if run.method == "Column graph")
        project.runs[box].options["Variables"] = ["Missing column"]  # Column graph 1/2 of the layout "Figure 1".
        window.actions["gallery"].trigger()
        page = window.gallery
        for row in range(page.view.model().rowCount()):
            if page.view.model().entry(row).ref == ("graph", box):
                page.view.setCurrentIndex(page.view.model().index(row))
        page.view.setFocus()
        QTest.keyClick(page.view, Qt.Key.Key_Return)  # The ordinary calculation fails: a message, not a dialog.
        self.wait()
        self.expect(project.runs[box].result is None and project.runs[box].calculation_error, "the failure was not kept")
        window.actions["gallery"].trigger()
        page = window.gallery
        self.previews(page)
        states = {e.ref: e.state for e in page.entries}
        self.expect(states.get(("graph", box)) == "error", f"a failed calculation is {states.get(('graph', box))}")
        self.expect(states.get(("layout", 0)) == "error", f"its layout is {states.get(('layout', 0))}")
        self.shot(window, "gallery-error")
        page.closed.emit()

        theme.apply(self.app, dark=True)  # The same page in the dark theme.
        window.actions["gallery"].trigger()
        page = window.gallery
        self.shot(window, "gallery-dark")
        theme.apply(self.app, dark=False)
        page.closed.emit()
        window.open_sheet(("graph", xy))  # One calculated graph, so that there is a preview to clean up.
        self.wait()
        window.actions["gallery"].trigger()
        page = window.gallery
        self.previews(page)

        service = page.service
        self.expect(len(service.cache) > 0, "no preview to clean up")
        window.close_gallery()  # Closing frees every preview and every result it held.
        self.expect(len(service.cache) == 0 and service.task is None and not service.queue,
                    "the preview cache was not emptied when the gallery closed")
        window.actions["gallery"].trigger()
        page = window.gallery
        self.previews(page)
        service = page.service
        window.project.dirty = False
        window.new_project()  # Another project: nothing of the old one stays.
        self.expect(window.gallery is None and len(service.cache) == 0,
                    "the previews of the old project survived a new project")

    def report(self):
        screen = self.app.primaryScreen()
        geometry = screen.availableGeometry() if screen else QRect()
        lines = [f"Trama Qt smoke · PySide6 {PYSIDE_VERSION} · platform {self.app.platformName()}",
                 f"Screen {screen.name() if screen else '?'}: available {geometry.width()}×{geometry.height()}, "
                 f"device pixel ratio {screen.devicePixelRatio() if screen else '?'}, "
                 f"logical DPI {screen.logicalDotsPerInch() if screen else '?'}",
                 f"Screenshots: {self.shots}", ""]
        lines += self.problems or ["No problems found."]
        if self.notes:
            lines += ["", "Pointer drawing (QTest events sent to the canvas widget; the operating system pointer and "
                      "the native Windows DPI are not exercised here):", *self.notes]
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
