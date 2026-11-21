"""Join worksheets by key in the desktop smoke (``python -m trama_qt --smoke FOLDER``).

On the synthetic sheets of the 0.96 acceptance ("Misure $" on the left, "Anagrafica | visite" on the right) it
drives the real dialog: two key pairs, Full and One-to-many, the calculation on the Qt worker, an error with the
cursor on Join cardinality and its correction in the same dialog, a cancelled change, an edit of the right
sheet that recalculates the join, a missing right sheet and its relinking, save, reopen and recalculation, in
the light and the dark theme. Screenshots are named ``<lang>-join-*.png``; problems go to the smoke report.
"""
import pandas as pd
from PySide6.QtWidgets import QApplication

from analisi import worksheet_join as wj

LEFT, RIGHT = "Misure $", "Anagrafica | visite"
LEFT_DATA = pd.DataFrame({"Sample": pd.Series([1, 1, "1", None, 2], dtype=object),
                          "Visit": ["A", "B", "A", "A", "C"], "Signal": [10, 20, 30, 40, 50],
                          "Signal [right]": ["L1", "L2", "L3", "L4", "L5"]})
RIGHT_DATA = pd.DataFrame({"ID": pd.Series([1, 1.0, "1", None, 3], dtype=object),
                           "Time": ["A", "A", "A", "A", "D"], "Signal": [100, 101, 102, 200, 300],
                           "Batch $": ["A1", "A2", "A3", "A4", "A5"]})
FULL_ROWS = [[1, "A", 10, "L1", 100, "A1"], [1, "A", 10, "L1", 101, "A2"], [1, "B", 20, "L2", None, None],
             ["1", "A", 30, "L3", 102, "A3"], [None, "A", 40, "L4", None, None], [2, "C", 50, "L5", None, None],
             [None, "A", None, None, 200, "A4"], [3, "D", None, None, 300, "A5"]]
RECIPE = {wj.RIGHT_SHEET: RIGHT, wj.LEFT_KEYS: ["Sample", "Visit"], wj.RIGHT_KEYS: ["ID", "Time"],
          wj.JOIN_TYPE: "Full", wj.CARDINALITY: "One-to-many"}


def _rows(table):
    return [[None if pd.isna(value) else value for value in row] for row in table.itertuples(index=False, name=None)]


def _choose(box, value):
    box.setCurrentIndex(max(0, box.findData(value)))


def _fill(dialog, recipe):
    editor = dialog.join
    _choose(editor.sheet, recipe[wj.RIGHT_SHEET])
    while len(editor.pairs.pairs) < len(recipe[wj.LEFT_KEYS]):
        editor.pairs.add_button.click()
    for (_, left_box, right_box, _), left, right in zip(editor.pairs.pairs, recipe[wj.LEFT_KEYS],
                                                         recipe[wj.RIGHT_KEYS]):
        _choose(left_box, left)
        _choose(right_box, right)
    _choose(editor.kind, recipe[wj.JOIN_TYPE])
    _choose(editor.rule, recipe[wj.CARDINALITY])


def _settle(smoke):
    """An edit starts its recalculation from the event loop: let it start, then wait for it."""
    smoke.app.processEvents()
    smoke.wait()


def _tabs(smoke, dialog, prefix):
    for index in range(dialog.tabs.count()):
        dialog.tabs.setCurrentIndex(index)
        smoke.shot(dialog, f"{prefix}-{index + 1}")


def _dialog(window, recipe=None, **extra):
    from .analysis_dialog import AnalysisDialog
    project = window.project
    frame = project.tables[LEFT].frame(mask_excluded=True)
    dialog = AnalysisDialog(window, frame, current=(wj.METHOD, recipe or {}), only=wj.METHOD,
                            join_sources=project.join_sources(LEFT), join_left=LEFT, **extra)
    dialog.show()
    dialog.activateWindow()
    QApplication.instance().processEvents()
    return dialog


def _calculate(smoke, window, options, index=None):
    candidate = window.project.candidate(LEFT, wj.METHOD, options, index=index)
    original, failures = window._ask, []
    window._ask = lambda *args, error=None, error_field=None, **kwargs: failures.append((error, error_field))
    try:
        window.calculate_candidate(candidate, window.project.tables[LEFT].frame(mask_excluded=True), index)
        smoke.wait()
    finally:
        window._ask = original
    return failures


def exercise(smoke, window):
    from . import theme
    window.new_project()
    project = window.project
    project.add_tables({LEFT: LEFT_DATA, RIGHT: RIGHT_DATA})
    window.show_sheet("data", LEFT)
    smoke.shot(window, "join-left")

    # The dialog: Variables (right sheet and the key pairs side by side) and Options (type, cardinality).
    dialog = _dialog(window)
    _fill(dialog, RECIPE)
    _tabs(smoke, dialog, "join-dialog")
    dialog.accept()
    if dialog.result is None or dialog.result[1] != RECIPE:
        smoke.problem(f"join: the dialog gave {dialog.result}")
    dialog.deleteLater()
    if _calculate(smoke, window, RECIPE):
        smoke.problem("join: the first calculation failed")
        return
    index = len(project.runs) - 1
    run = project.runs[index]
    if _rows(run.result.tables[wj.JOINED]) != FULL_ROWS:
        smoke.problem(f"join: Joined data is {_rows(run.result.tables[wj.JOINED])}")
    window.open_sheet(("result", index))
    for tab, name in enumerate(("joined", "provenance", "diagnostics")):
        window.result_tabs.setCurrentIndex(tab)
        smoke.shot(window, f"join-{name}")

    # One-to-one is refused (the right sheet repeats 1, A); the dialog reopens on Join cardinality.
    failures = _calculate(smoke, window, {**RECIPE, wj.CARDINALITY: "One-to-one"}, index)
    if len(failures) != 1 or failures[0][1] != wj.CARDINALITY:
        smoke.problem(f"join: One-to-one gave {failures}")
    else:
        error, field = failures[0]
        dialog = _dialog(window, {**RECIPE, wj.CARDINALITY: "One-to-one"}, error=error, error_field=field)
        if dialog.tabs.currentIndex() != 1 or dialog.focusWidget() is not dialog.join.rule:
            smoke.problem("join: the error did not put the cursor on Join cardinality")
        smoke.shot(dialog, "join-error")
        _choose(dialog.join.rule, "One-to-many")
        dialog.accept()
        dialog.deleteLater()

    # A cancelled change keeps the recipe.
    dialog = _dialog(window, run.options)
    _fill(dialog, {**RECIPE, wj.JOIN_TYPE: "Inner"})
    dialog.reject()
    dialog.deleteLater()
    if project.runs[index].options != RECIPE:
        smoke.problem("join: Cancel changed the recipe")

    # An edit of the right sheet recalculates the join.
    window.show_sheet("data", RIGHT)
    model = window.sheet.model()
    model.setData(model.index(0, 2), "999")
    _settle(smoke)
    if _rows(project.runs[index].result.tables[wj.JOINED])[0][4] != 999:
        smoke.problem("join: the edit of the right sheet did not reach the join")
    window.undo()
    _settle(smoke)

    # A missing right sheet: an error that names it, then the dialog to link another one.
    project.runs[index].options = {**RECIPE, wj.RIGHT_SHEET: "Gone $ sheet"}
    project.tables[LEFT].analyses[project.runs[index].slot] = (wj.METHOD, project.runs[index].options)
    window.refresh_runs([project.runs[index]])
    smoke.wait()
    if "Gone $ sheet" not in str(project.runs[index].calculation_error):
        smoke.problem(f"join: missing sheet gave {project.runs[index].calculation_error}")
    window.open_sheet(("result", index))
    smoke.shot(window, "join-missing")
    dialog = _dialog(window, project.runs[index].options, error=project.runs[index].calculation_error,
                     error_field=wj.RIGHT_SHEET)
    smoke.shot(dialog, "join-relink")
    dialog.reject()
    dialog.deleteLater()
    if _calculate(smoke, window, RECIPE, index) or project.runs[index].calculation_error:
        smoke.problem("join: relinking failed")

    # Dark theme, then save, reopen and recalculate.
    theme.apply(smoke.app, dark=True)
    dialog = _dialog(window, RECIPE)
    smoke.shot(dialog, "join-dialog-dark")
    dialog.reject()
    dialog.deleteLater()
    window.open_sheet(("result", index))
    window.result_tabs.setCurrentIndex(1)
    smoke.shot(window, "join-provenance-dark")
    theme.apply(smoke.app, dark=False)
    path = smoke.folder / f"{smoke.language}-join.alab"
    project.save(path)
    window.close_project()
    window.open_path(path)
    smoke.app.processEvents()
    reopened = window.project
    run = next((other for other in reopened.runs if other.method == wj.METHOD), None)
    if run is None or run.options != RECIPE:
        smoke.problem("join: the recipe did not survive save and reopen")
        return
    window.open_sheet(("result", reopened.runs.index(run)))
    smoke.wait()
    if run.result is None or _rows(run.result.tables[wj.JOINED]) != FULL_ROWS:
        smoke.problem("join: the reopened join was not recalculated")
    smoke.shot(window, "join-reopened")
    reopened.dirty = False
