"""Replicate lack-of-fit test in the desktop window.

``python -m trama_qt.replicate_lack_of_fit_smoke FOLDER [--languages en,it] [--themes light,dark]
[--sizes 1024x768,1600x1000]`` opens ``tests/data/replicate-lack-of-fit/repliche.alab``.
The saved recipe is the additive model of repliche.csv with the test on. The sheet is
N=8, U=4, rank=3, residual SS=40, pure-error SS=8, lack-of-fit SS=32, F=16.
"""
from contextlib import contextmanager
import os
import platform
import sys
from pathlib import Path

import pandas as pd
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QWidget

from analisi.ols_diagnostics import LACK_OF_FIT_SHEET, REPLICATE_LACK_OF_FIT
from analisi.workbench import analyse

METHOD = "Multiple regression"
TITLE = "Repliche"
ROOT = Path(__file__).resolve().parents[1] / "tests" / "data" / "replicate-lack-of-fit"
SOURCE = ROOT / "repliche.alab"


@contextmanager
def _driven(smoke, steps):
    from unittest import mock
    from .analysis_dialog import AnalysisDialog
    app = QApplication.instance()
    queue = list(steps)

    def run(dialog):
        dialog.show()
        app.processEvents()
        if not queue:
            smoke.problem(f"lack of fit: unexpected dialog: {dialog.banner.text()}")
            dialog.reject()
            return QDialog.DialogCode.Rejected
        accepted = queue.pop(0)(dialog)
        return QDialog.DialogCode.Accepted if accepted and dialog.result else QDialog.DialogCode.Rejected

    with mock.patch.object(AnalysisDialog, "exec", run):
        yield
    if queue:
        smoke.problem("lack of fit: a dialog step did not run")


def _fit(window, size):
    from . import theme
    available = window.screen().availableGeometry() if window.screen() else None
    width, height = size
    if available is not None:
        width = min(width, available.width())
        height = min(height, available.height())
    QWidget.resize(window, width, height)
    theme.keep_on_screen(window)
    QApplication.instance().processEvents()
    return QWidget.size(window)


def _numbers(smoke, result, what):
    if result is None or LACK_OF_FIT_SHEET not in result.tables:
        smoke.problem(f"lack of fit: {what} has no sheet")
        return None
    sheet = result.tables[LACK_OF_FIT_SHEET]
    residual, lack = sheet.loc["Residual"], sheet.loc["Lack of fit"]
    expected = {"N": 8, "Distinct combinations": 4, "Rank": 3, "Replicate groups": 4}
    for name, value in expected.items():
        if int(residual[name]) != value:
            smoke.problem(f"lack of fit: {what} {name} is {residual[name]}, expected {value}")
    shown = [f"{float(value):.10g}" for value in sheet["SS"]]
    if shown != ["40", "8", "32"]:
        smoke.problem(f"lack of fit: {what} sums are {shown}")
    degrees = [int(value) for value in sheet["df"]]
    if degrees != [5, 4, 1]:
        smoke.problem(f"lack of fit: {what} degrees of freedom are {degrees}")
    if f"{float(lack['F']):.10g}" != "16":
        smoke.problem(f"lack of fit: {what} F is {lack['F']}")
    if not str(float(lack["p"])).startswith("0.016130"):
        smoke.problem(f"lack of fit: {what} p is {lack['p']}")
    return sheet


def _show_sheet(smoke, window, index, name, *, reference=True):
    from analisi.i18n import active_language
    tables = window.project.runs[index].result.tables
    window.result_tabs.setCurrentIndex(list(tables).index(LACK_OF_FIT_SHEET))
    QApplication.instance().processEvents()
    view = window.result_tabs.currentWidget()
    model = view.model()
    language = active_language()
    component = "Componente" if language == "it" else "Component"
    residual = "Residuo" if language == "it" else "Residual"
    if model.headerData(0, Qt.Orientation.Horizontal) != component:
        smoke.problem(f"lack of fit: the component header is {model.headerData(0, Qt.Orientation.Horizontal)!r}")
    if model.plain_text(0, 0) != residual:
        smoke.problem(f"lack of fit: the first component is {model.plain_text(0, 0)!r}")
    if reference:
        p_column = list(tables[LACK_OF_FIT_SHEET].columns).index("p") + 1
        if not model.plain_text(2, p_column).startswith("0.016130"):
            smoke.problem(f"lack of fit: the shown p is {model.plain_text(2, p_column)!r}")
    smoke.shot(window, name)


def exercise(smoke, window, sizes):
    from analisi.i18n import active_language
    from .shortcuts_dialog import ShortcutsDialog
    app = QApplication.instance()
    language = active_language()
    shortcut = window.actions["help_shortcuts"].shortcut().toString()
    if shortcut != "F1":
        smoke.problem(f"lack of fit: the shortcuts action is {shortcut!r}, expected F1")
    window.open_path(SOURCE)
    smoke.wait()
    index = next((i for i, item in enumerate(window.project.runs) if item.method == METHOD), None)
    if index is None:
        smoke.problem("lack of fit: the sample project has no multiple regression")
        return
    if window.project.runs[index].options.get(REPLICATE_LACK_OF_FIT) is not True:
        smoke.problem(f"lack of fit: the saved recipe is {window.project.runs[index].options}")
    window.open_sheet(("result", index))
    smoke.wait()
    run = window.project.runs[index]
    if run.calculation_error or run.result is None:
        smoke.problem(f"lack of fit: calculation failed: {run.calculation_error}")
        return
    _numbers(smoke, run.result, "opened")

    shortcuts_opened = []

    def capture_shortcuts():
        dialog = app.activeModalWidget()
        if isinstance(dialog, ShortcutsDialog):
            shortcuts_opened.append(dialog.windowTitle())
            smoke.shot(dialog, "lack-of-fit-shortcuts")
            dialog.reject()

    window.activateWindow()
    window.setFocus()
    app.processEvents()
    QTimer.singleShot(120, capture_shortcuts)
    QTest.keyClick(window, Qt.Key.Key_F1)
    QTest.qWait(160)
    if not any(shortcuts_opened):
        smoke.problem("lack of fit: F1 did not open the shortcuts dialog")

    def confirm(dialog):
        box = dialog.controls[REPLICATE_LACK_OF_FIT][1]
        if not box.isChecked():
            smoke.problem("lack of fit: Change parameters lost the check")
        if not dialog.tabs.isTabVisible(dialog.tabs.indexOf(dialog._lof_scroll)):
            smoke.problem("lack of fit: Diagnostics and predictions is hidden for the linear fit")
        caption = dialog.rows[REPLICATE_LACK_OF_FIT][0].text()
        expected = "Test di mancato adattamento sulle repliche" if language == "it" else REPLICATE_LACK_OF_FIT
        if caption != expected:
            smoke.problem(f"lack of fit: the checkbox caption is {caption!r}")
        dialog.tabs.setCurrentWidget(dialog._lof_scroll)
        dialog._lof_scroll.setFocus()
        app.processEvents()
        reached = False
        for _ in range(15):
            QTest.keyClick(dialog.focusWidget() or dialog, Qt.Key.Key_Tab)
            app.processEvents()
            if dialog.focusWidget() is box:
                reached = True
                break
        if not reached:
            smoke.problem("lack of fit: Tab did not reach the checkbox")
        smoke.shot(dialog, "lack-of-fit-dialog")
        if not dialog.run_button.isDefault():
            smoke.problem("lack of fit: Enter has no default confirm button")
        QTest.keyClick(dialog.run_button, Qt.Key.Key_Return)
        app.processEvents()
        return dialog.result is not None

    with _driven(smoke, [confirm]):
        window.change_parameters()
        smoke.wait()
    if window.project.runs[index].options.get(REPLICATE_LACK_OF_FIT) is not True:
        smoke.problem("lack of fit: confirming the dialog cleared the check")

    for width, height in sizes:
        actual = _fit(window, (width, height))
        smoke.notes.append(f"{language} window requested {width}×{height}, drawn {actual.width()}×{actual.height()}")
        window.open_sheet(("result", index))
        smoke.wait()
        _show_sheet(smoke, window, index, f"lack-of-fit-result-{width}x{height}")

    saved = smoke.folder / f"lack-of-fit-{language}.alab"
    window.project.save(saved)
    window.project.dirty = False
    window.close_project()
    window.open_path(saved)
    smoke.wait()
    if index >= len(window.project.runs) or window.project.runs[index].options.get(REPLICATE_LACK_OF_FIT) is not True:
        smoke.problem("lack of fit: the reopened project lost the check")
        return
    window.open_sheet(("result", index))
    smoke.wait()
    reopened_sheet = _numbers(smoke, window.project.runs[index].result, "reopened")
    opened_ss = None if reopened_sheet is None else float(reopened_sheet.loc["Residual", "SS"])

    window.open_sheet(("data", TITLE))
    if not window.edit_cell(TITLE, 0, 2, "5"):
        smoke.problem("lack of fit: the cell edit was refused")
    smoke.wait()
    edited = window.project.runs[index]
    if edited.calculation_error or edited.result is None:
        smoke.problem(f"lack of fit: recalculation failed: {edited.calculation_error}")
    else:
        fresh = analyse(METHOD, window.project.tables[TITLE].frame(mask_excluded=True), edited.options)
        try:
            pd.testing.assert_frame_equal(edited.result.tables[LACK_OF_FIT_SHEET], fresh.tables[LACK_OF_FIT_SHEET])
        except AssertionError as error:
            smoke.problem(f"lack of fit: the edited sheet differs from the engine: {error}")
        edited_ss = float(edited.result.tables[LACK_OF_FIT_SHEET].loc["Residual", "SS"])
        if opened_ss is not None and abs(edited_ss - opened_ss) < 1e-8:
            smoke.problem("lack of fit: editing Y left the residual sum of squares unchanged")
    window.sheet.setCurrentIndex(window.sheet.model().index(7, 2))
    window.toggle_exclusion()
    smoke.wait()
    excluded = window.project.runs[index]
    if excluded.calculation_error or excluded.result is None:
        smoke.problem(f"lack of fit: exclusion failed: {excluded.calculation_error}")
    elif int(excluded.result.tables[LACK_OF_FIT_SHEET].loc["Residual", "N"]) != 7:
        smoke.problem("lack of fit: excluding one measurement left N unchanged")
    else:
        fresh = analyse(METHOD, window.project.tables[TITLE].frame(mask_excluded=True), excluded.options)
        try:
            pd.testing.assert_frame_equal(excluded.result.tables[LACK_OF_FIT_SHEET], fresh.tables[LACK_OF_FIT_SHEET])
        except AssertionError as error:
            smoke.problem(f"lack of fit: the excluded sheet differs from the engine: {error}")
    window.open_sheet(("result", index))
    smoke.wait()
    _show_sheet(smoke, window, index, "lack-of-fit-edited", reference=False)
    for session in window.sessions:
        session.project.dirty = False


def main(argv=None):
    """Only this step: ``python -m trama_qt.replicate_lack_of_fit_smoke FOLDER``."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print(main.__doc__)
        return 2

    def option(name, default):
        if name in argv:
            position = argv.index(name)
            value = argv[position + 1]
            del argv[position:position + 2]
            return value.split(",")
        return default

    languages = option("--languages", ["en", "it"])
    themes = option("--themes", ["light", "dark"])
    sizes = [tuple(int(part) for part in item.split("x")) for item in option("--sizes", ["1024x768", "1600x1000"])]
    folder = Path(argv[0])
    from analisi.i18n import set_language
    os.environ.setdefault("MPLBACKEND", "QtAgg")
    app = QApplication.instance() or QApplication([sys.argv[0]])
    from . import theme
    import matplotlib
    matplotlib.use("QtAgg")
    theme.load_fonts()
    from .smoke import Smoke
    from .window import MainWindow
    smoke = Smoke(folder)
    screen = app.primaryScreen()
    smoke.notes.append(f"OS {platform.system()} {platform.release()} — {platform.platform()}")
    smoke.notes.append(f"machine {platform.node()} — {platform.machine()}")
    smoke.notes.append(f"QT_SCALE_FACTOR {os.environ.get('QT_SCALE_FACTOR', 'unset')}")
    smoke.notes.append(f"QT_QPA_PLATFORM {os.environ.get('QT_QPA_PLATFORM', app.platformName())}")
    if screen is not None:
        smoke.notes.append(f"devicePixelRatio {screen.devicePixelRatio()} logical DPI {screen.logicalDotsPerInch()}")
    for mode in themes:
        theme.set_mode(mode, app, remember=False)
        for language in languages:
            smoke.language = f"{language}-{mode}"
            set_language(language)
            theme.install_qt_translations(app, language)
            window = smoke.window = MainWindow()
            window.error = lambda error: smoke.problem(f"error shown: {error}")
            window.show()
            theme.keep_on_screen(window)
            app.processEvents()
            try:
                exercise(smoke, window, sizes)
            except Exception:
                import traceback
                smoke.problem("stopped:\n" + traceback.format_exc())
            finally:
                for session in window.sessions:
                    session.project.dirty = False
                window.close()
                window.deleteLater()
                app.processEvents()
    status = smoke.report()
    print(f"Replicate lack-of-fit smoke: {status} ({folder})")
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
