"""Paired Deming comparison in the desktop window.

``python -m trama_qt.deming_paired_smoke FOLDER [--languages en,it] [--themes light,dark]`` opens
``tests/data/deming-paired/deming-appaiato.alab`` on the real screen. The saved recipe has the comparison
off. The dialog must say that each row is the same unit, refuse the option with one series, then compare
``Trattamento $`` with ``Controllo``. Save, reopen, edit one cell and recalculate.
"""
from contextlib import contextmanager
import json
import math
from pathlib import Path
import os
import platform
import sys

import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog

from analisi.deming import PAIRED, PAIRED_SHEET

METHOD = "Deming regression"
TITLE = "Misure appaiate"
FIRST, SECOND = "Controllo", "Trattamento $"
ROOT = Path(__file__).resolve().parents[1] / "tests" / "data" / "deming-paired"
ORACLE = json.loads((ROOT / "oracolo.json").read_text(encoding="utf-8"))
SOURCE = ROOT / "deming-appaiato.alab"


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
            smoke.problem(f"deming paired: unexpected dialog: {dialog.banner.text()}")
            dialog.reject()
            return QDialog.DialogCode.Rejected
        accepted = queue.pop(0)(dialog)
        return QDialog.DialogCode.Accepted if accepted and dialog.result else QDialog.DialogCode.Rejected

    with mock.patch.object(AnalysisDialog, "exec", run):
        yield
    if queue:
        smoke.problem("deming paired: a dialog step did not run")


def _show_comparison(smoke, window, index):
    window.open_sheet(("result", index))
    smoke.wait()
    run = window.project.runs[index]
    if window.result_tabs is not None and run.result is not None and PAIRED_SHEET in run.result.tables:
        window.result_tabs.setCurrentIndex(list(run.result.tables).index(PAIRED_SHEET))
        QApplication.instance().processEvents()


def _tick(dialog, names):
    box = dialog.controls["Y series"][1]
    for row in range(box.count()):
        item = box.item(row)
        item.setCheckState(Qt.CheckState.Checked if item.text() in names else Qt.CheckState.Unchecked)


def _close(smoke, sheet, what):
    if sheet is None or len(sheet) != 2:
        smoke.problem(f"deming paired: {what} has no comparison sheet")
        return
    pairs = (("Difference", "second_minus_first"), ("SE", "se"), ("Individual p", "p_two_sided"),
             ("CI low", "lower"), ("CI high", "upper"))
    for column, key in pairs:
        for index, expected in enumerate(ORACLE[key]):
            got = float(sheet[column].iloc[index])
            if not math.isclose(got, float(expected), rel_tol=0, abs_tol=1e-10):
                smoke.problem(f"deming paired: {what} {column} row {index} is {got}, expected {expected}")
    if list(sheet["First N"]) != [10, 10] or list(sheet["Second N"]) != [8, 8] or list(sheet["Paired N"]) != [8, 8]:
        smoke.problem(f"deming paired: {what} counts "
                      f"{list(sheet['First N'])} {list(sheet['Second N'])} {list(sheet['Paired N'])}")
    if list(sheet["Second series"]) != [SECOND, SECOND]:
        smoke.problem(f"deming paired: {what} series name {list(sheet['Second series'])}")
    if "X = 0" not in str(sheet["Status"].iloc[1]):
        smoke.problem(f"deming paired: {what} does not flag the intercept at X = 0")


def exercise(smoke, window):
    from analisi.i18n import active_language
    from analisi.workbench import analyse
    app = QApplication.instance()
    language = active_language()
    window.open_path(SOURCE)
    smoke.wait()
    if not window.actions["analyze"].isEnabled():
        smoke.problem("deming paired: Analyze is disabled on the open project")
    index = next((i for i, item in enumerate(window.project.runs) if item.method == METHOD), None)
    if index is None:
        smoke.problem("deming paired: the sample project has no Deming regression")
        return
    window.open_sheet(("result", index))
    smoke.wait()
    legacy = window.project.runs[index]
    if legacy.result is None or PAIRED_SHEET in legacy.result.tables:
        smoke.problem("deming paired: the saved recipe already has a comparison sheet")
    else:
        counts = dict(zip(legacy.result.tables["Deming regression"]["Series"],
                          legacy.result.tables["Deming regression"]["N"]))
        if counts != {FIRST: 10, SECOND: 8}:
            smoke.problem(f"deming paired: saved series counts {counts}")

    def refuse(dialog):
        dialog.tabs.setCurrentIndex(1)
        note = dialog.deming_paired_note
        dialog.tabs.widget(1).ensureWidgetVisible(note)
        app.processEvents()
        expected = "stessa unità" if language == "it" else "same unit"
        if expected not in note.text():
            smoke.problem(f"deming paired: the note does not say the rows are paired ({note.text()!r})")
        smoke.shot(dialog, "deming-paired-note")
        _tick(dialog, [FIRST])
        dialog.controls[PAIRED][1].setChecked(True)
        dialog.accept()
        if dialog.result is not None:
            smoke.problem("deming paired: one series was accepted")
        sentence = "esattamente due serie Y" if language == "it" else "exactly two Y series"
        if sentence not in dialog.banner.text():
            smoke.problem(f"deming paired: the one-series error was {dialog.banner.text()!r}")
        smoke.shot(dialog, "deming-paired-error")
        _tick(dialog, [FIRST, SECOND])
        dialog.banner.hide()
        dialog.accept()
        return dialog.result is not None

    with _driven(smoke, [refuse]):
        window.change_parameters()
        smoke.wait()
    run = window.project.runs[index]
    if run.calculation_error or run.result is None or PAIRED_SHEET not in run.result.tables:
        smoke.problem(f"deming paired: calculation failed: {run.calculation_error}")
        return
    if not run.options.get(PAIRED):
        smoke.problem("deming paired: the recipe did not record the option")
    sheet = run.result.tables[PAIRED_SHEET]
    _close(smoke, sheet, "first run")
    _show_comparison(smoke, window, index)
    smoke.shot(window, "deming-paired-result")

    saved = smoke.folder / f"deming-paired-{language}.alab"
    window.project.save(saved)
    window.close_project()
    window.open_path(saved)
    smoke.wait()
    if index >= len(window.project.runs):
        smoke.problem("deming paired: the reopened project has no analysis")
        return
    window.open_sheet(("result", index))
    smoke.wait()
    reopened = window.project.runs[index]
    if not reopened.options.get(PAIRED) or reopened.result is None or PAIRED_SHEET not in reopened.result.tables:
        smoke.problem("deming paired: the reopened project lost the comparison")
        return
    _close(smoke, reopened.result.tables[PAIRED_SHEET], "reopened")
    _show_comparison(smoke, window, index)
    smoke.shot(window, "deming-paired-reopened")

    window.open_sheet(("data", TITLE))
    model = window.sheet.model()
    original = model.index(0, 2).data()
    if not model.setData(model.index(0, 2), "3.4"):
        smoke.problem("deming paired: the cell edit was refused")
    app.processEvents()
    smoke.wait()
    after = window.project.runs[index]
    if after.calculation_error or after.result is None or PAIRED_SHEET not in after.result.tables:
        smoke.problem(f"deming paired: recalculation failed: {after.calculation_error}")
    else:
        fresh = analyse(METHOD, window.project.tables[TITLE].frame(mask_excluded=True), after.options)
        try:
            pd.testing.assert_frame_equal(after.result.tables[PAIRED_SHEET], fresh.tables[PAIRED_SHEET])
        except AssertionError as error:
            smoke.problem(f"deming paired: the edited sheet differs from the engine: {error}")
        if after.result.tables[PAIRED_SHEET]["Difference"].iloc[0] == sheet["Difference"].iloc[0]:
            smoke.problem("deming paired: editing Controllo left the slope difference unchanged")
    _show_comparison(smoke, window, index)
    smoke.shot(window, "deming-paired-recalculated")
    if original is None:
        smoke.problem("deming paired: the edited cell had no original value")
    for session in window.sessions:
        session.project.dirty = False


def main(argv=None):
    """Only this step: ``python -m trama_qt.deming_paired_smoke FOLDER [--languages en,it] [--themes light,dark]``."""
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
    smoke.notes.append(f"OS {platform.system()} {platform.release()} — {platform.platform()}")
    smoke.notes.append(f"QT_SCALE_FACTOR {os.environ.get('QT_SCALE_FACTOR', 'unset')}")
    for mode in themes:
        theme.set_mode(mode, app, remember=False)
        for language in languages:
            smoke.language = f"{language}-{mode}"
            set_language(language)
            theme.install_qt_translations(app, language)
            window = smoke.window = MainWindow()
            window.error = lambda error: smoke.problem(f"error shown: {error}")
            available = smoke.screen_rect(window)
            window.resize(min(1680, available.width()), min(900, available.height()))
            window.show()
            theme.keep_on_screen(window)
            app.processEvents()
            try:
                exercise(smoke, window)
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
    print(f"Deming paired smoke: {status} ({folder})")
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
