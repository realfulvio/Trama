"""Passing–Bablok regression in the desktop window.

``python -m trama_qt.passing_bablok_smoke FOLDER [--languages en,it] [--themes light,dark]
[--sizes 1024x768,1600x1000]`` opens ``tests/data/passing-bablok/passing-bablok.alab`` on the real
screen. The saved recipe uses Riferimento as X and Metodo as Y, with the identity line on.
The four complete pairs are the rank-shift sample (slope 2.25, intercept −1.875). U5 is empty
and U6 is excluded. Save, reopen, edit one Y cell and recalculate.
"""
from contextlib import contextmanager
import math
from pathlib import Path
import os
import platform
import sys

import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QWidget

from analisi.passing_bablok import IDENTITY, LEVEL, METHOD, NOTES, SHEET

TITLE = "Metodi"
ROOT = Path(__file__).resolve().parents[1] / "tests" / "data" / "passing-bablok"
SOURCE = ROOT / "passing-bablok.alab"
SLOPE, INTERCEPT = 2.25, -1.875


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
            smoke.problem(f"passing–bablok: unexpected dialog: {dialog.banner.text()}")
            dialog.reject()
            return QDialog.DialogCode.Rejected
        accepted = queue.pop(0)(dialog)
        return QDialog.DialogCode.Accepted if accepted and dialog.result else QDialog.DialogCode.Rejected

    with mock.patch.object(AnalysisDialog, "exec", run):
        yield
    if queue:
        smoke.problem("passing–bablok: a dialog step did not run")


def _close(smoke, result, what):
    if result is None or SHEET not in result.tables:
        smoke.problem(f"passing–bablok: {what} has no result")
        return
    sheet = result.tables[SHEET].set_index("Parameter")
    for name, expected in (("Slope", SLOPE), ("Intercept", INTERCEPT)):
        got = float(sheet.loc[name, "Estimate"])
        if not math.isclose(got, expected, rel_tol=0, abs_tol=1e-9):
            smoke.problem(f"passing–bablok: {what} {name} is {got}, expected {expected}")
        if math.isfinite(float(sheet.loc[name, "CI low"])):
            smoke.problem(f"passing–bablok: {what} {name} has a limit on four pairs")
    notes = " ".join(result.tables[NOTES]["Note"])
    if "missing or excluded: 2" not in notes:
        smoke.problem(f"passing–bablok: {what} does not count the two left-out rows")
    if "not estimable" not in notes:
        smoke.problem(f"passing–bablok: {what} does not say the limits are unavailable")
    lines = result.figure.axes[0].get_lines()
    if len(lines) != 2 or lines[1].get_label() != "Identity":
        smoke.problem(f"passing–bablok: {what} identity line is {[line.get_label() for line in lines]}")


def _show(smoke, window, index, kind, name):
    window.open_sheet((kind, index))
    smoke.wait()
    if kind == "result" and window.result_tabs is not None:
        tables = window.project.runs[index].result.tables
        window.result_tabs.setCurrentIndex(list(tables).index(SHEET))
        QApplication.instance().processEvents()
    smoke.shot(window, name)


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


def exercise(smoke, window, sizes):
    from analisi.i18n import active_language
    from analisi.workbench import analyse
    app = QApplication.instance()
    language = active_language()
    window.open_path(SOURCE)
    smoke.wait()
    index = next((i for i, item in enumerate(window.project.runs) if item.method == METHOD), None)
    if index is None:
        smoke.problem("passing–bablok: the sample project has no Passing–Bablok regression")
        return
    window.open_sheet(("result", index))
    smoke.wait()
    run = window.project.runs[index]
    if run.calculation_error or run.result is None:
        smoke.problem(f"passing–bablok: calculation failed: {run.calculation_error}")
        return
    if run.options.get("X") != "Riferimento" or run.options.get("Y") != "Metodo" or not run.options.get(IDENTITY):
        smoke.problem(f"passing–bablok: the recipe is {run.options}")
    _close(smoke, run.result, "opened")
    for suffix in ("png", "svg", "pdf"):
        run.result.figure.savefig(smoke.folder / f"passing-bablok-{language}-figure.{suffix}")

    def look(dialog):
        tree = dialog.methods
        caption = None
        for folder in range(tree.topLevelItemCount()):
            parent = tree.topLevelItem(folder)
            for child in range(parent.childCount()):
                item = parent.child(child)
                if item.data(0, Qt.ItemDataRole.UserRole) == METHOD:
                    caption = item.text(0)
        expected = "Regressione di Passing–Bablok" if language == "it" else METHOD
        if caption != expected:
            smoke.problem(f"passing–bablok: the method caption is {caption!r}")
        if not dialog.controls[IDENTITY][1].isChecked():
            smoke.problem("passing–bablok: the identity line is off in the saved recipe")
        if dialog.controls["X"][1].currentData() != "Riferimento" or dialog.controls["Y"][1].currentData() != "Metodo":
            smoke.problem("passing–bablok: the dialog does not keep the saved columns")
        smoke.shot(dialog, "passing-bablok-dialog")
        dialog.reject()
        return False

    with _driven(smoke, [look]):
        window.change_parameters()
        smoke.wait()
    if window.project.runs[index].options.get(IDENTITY) is not True:
        smoke.problem("passing–bablok: cancelling the dialog changed the recipe")

    for width, height in sizes:
        actual = _fit(window, (width, height))
        smoke.notes.append(f"{language} window requested {width}×{height}, drawn {actual.width()}×{actual.height()}")
        _show(smoke, window, index, "result", f"passing-bablok-result-{width}x{height}")
        if window.result_tabs is not None:
            tables = window.project.runs[index].result.tables
            window.result_tabs.setCurrentIndex(list(tables).index(NOTES))
            app.processEvents()
            smoke.shot(window, f"passing-bablok-notes-{width}x{height}")
        _show(smoke, window, index, "graph", f"passing-bablok-graph-{width}x{height}")

    saved = smoke.folder / f"passing-bablok-{language}.alab"
    window.project.save(saved)
    window.close_project()
    window.open_path(saved)
    smoke.wait()
    if index >= len(window.project.runs) or window.project.runs[index].method != METHOD:
        smoke.problem("passing–bablok: the reopened project lost the analysis")
        return
    window.open_sheet(("result", index))
    smoke.wait()
    reopened = window.project.runs[index]
    if reopened.options.get(IDENTITY) is not True or reopened.options.get(LEVEL) != 95.0:
        smoke.problem(f"passing–bablok: the reopened recipe is {reopened.options}")
    _close(smoke, reopened.result, "reopened")

    window.open_sheet(("data", TITLE))
    model = window.sheet.model()
    if not model.setData(model.index(0, 2), "8"):
        smoke.problem("passing–bablok: the cell edit was refused")
    app.processEvents()
    smoke.wait()
    after = window.project.runs[index]
    if after.calculation_error or after.result is None:
        smoke.problem(f"passing–bablok: recalculation failed: {after.calculation_error}")
    else:
        fresh = analyse(METHOD, window.project.tables[TITLE].frame(mask_excluded=True), after.options)
        try:
            pd.testing.assert_frame_equal(after.result.tables[SHEET], fresh.tables[SHEET])
        except AssertionError as error:
            smoke.problem(f"passing–bablok: the edited sheet differs from the engine: {error}")
        edited = float(after.result.tables[SHEET].set_index("Parameter").loc["Slope", "Estimate"])
        if math.isclose(edited, SLOPE, rel_tol=0, abs_tol=1e-9):
            smoke.problem("passing–bablok: editing Metodo left the slope unchanged")
    _show(smoke, window, index, "result", "passing-bablok-recalculated")
    for session in window.sessions:
        session.project.dirty = False


def main(argv=None):
    """Only this step: ``python -m trama_qt.passing_bablok_smoke FOLDER``."""
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
    print(f"Passing–Bablok smoke: {status} ({folder})")
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
