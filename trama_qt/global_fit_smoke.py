"""Global fit custom equation in the desktop smoke (``python -m trama_qt --smoke FOLDER``).

From a new table it drives the real editors: Local/Shared coefficients, a per-series fixed value, an error with
the cursor on its cell, the correction, Cancel, the calculation on the Qt worker, save, reopen and
recalculation. Screenshots are named ``<lang>-global-*.png``; problems go to the smoke report.
"""
from copy import deepcopy
import math

import pandas as pd
from PySide6.QtWidgets import QApplication

METHOD = "Global fit custom equation"
DATA = pd.DataFrame({"X": [0, 1, 2, 3, 0, 1, 2, 3],
                     "Y": [1.25, 2.75, 4.75, 7.25, 3.75, 6.25, 8.25, 9.75],
                     "Series": ["Control $"] * 4 + ["Batch B"] * 4,
                     "SD": [0.5] * 4 + [1.0] * 4})


def _estimates(result):
    rows = {}
    for row in result.tables["Parameters"].to_dict("records"):
        group = None if pd.isna(row["Group"]) else row["Group"]
        rows[(group, row["Parameter"])] = (row["Scope"], row["Estimate"])
    return rows, result.tables["Global fit"]["Value"]


def _expect(smoke, result, df, fixed):
    rows, summary = _estimates(result)
    expected = {("Control $", "A"): 1.0, ("Batch B", "A"): 4.0, (None, "B"): 2.0}
    for key, value in expected.items():
        if key not in rows or not math.isclose(rows[key][1], value, rel_tol=1e-6, abs_tol=1e-7):
            smoke.problem(f"global fit: {key} is {rows.get(key)}, expected {value}")
    if rows.get(("Control $", "A"), ("",))[0] != ("Fixed" if fixed else "Local"):
        smoke.problem(f"global fit: Control $ A scope is {rows.get(('Control $', 'A'))}")
    if summary["DF residual"] != df or not math.isclose(summary["Residual SS"], .5, rel_tol=1e-6):
        smoke.problem(f"global fit: df {summary['DF residual']}, RSS {summary['Residual SS']}")


def _tabs(smoke, dialog, prefix):
    for index in range(dialog.tabs.count()):
        dialog.tabs.setCurrentIndex(index)
        smoke.shot(dialog, f"{prefix}-{index + 1}")


def exercise(smoke, window):
    from .analysis_dialog import AnalysisDialog
    app = QApplication.instance()
    path = smoke.folder / "global-fit.csv"
    DATA.to_csv(path, index=False)
    window.open_path(path)
    smoke.wait()
    title = "global-fit"
    frame = window.project.tables[title].frame(mask_excluded=True)

    # A new analysis: the example A + B*X, A local and B shared, then a fixed value for one series.
    dialog = AnalysisDialog(window, frame, current=(METHOD, {}), only=METHOD)
    dialog.show()
    dialog.activateWindow()
    app.processEvents()
    coefficients = dialog.controls["Parameters"][1]
    series = dialog.controls["Series constraints"][1]
    _tabs(smoke, dialog, "global-new")
    series.set_override("Control $", "A", "fixed", "1")
    coefficients.set_cell(1, coefficients.LOWER, "3")
    coefficients.set_cell(1, coefficients.UPPER, "1")
    dialog.accept()
    app.processEvents()
    if dialog.result is not None or not dialog.banner.isVisible():
        smoke.problem("global fit: reversed limits were accepted")
    elif (coefficients.table.currentRow(), coefficients.table.currentColumn()) != (1, coefficients.LOWER):
        smoke.problem("global fit: the reversed limit is not focused")
    smoke.shot(dialog, "global-error")
    coefficients.set_cell(1, coefficients.LOWER, "0")
    coefficients.set_cell(1, coefficients.UPPER, "4")
    dialog.focus_field("Series constraints")
    smoke.shot(dialog, "global-series")
    dialog.accept()
    app.processEvents()
    if dialog.result is None:
        smoke.problem(f"global fit: not accepted: {dialog.banner.text()}")
        dialog.reject()
        return
    method, options = dialog.result
    dialog.deleteLater()
    candidate = window.project.candidate(title, method, options)
    window.calculate_candidate(candidate, frame, None)
    smoke.wait()
    index = len(window.project.runs) - 1
    run = window.project.runs[index]
    if run.result is None or run.calculation_error:
        smoke.problem(f"global fit: not calculated: {run.calculation_error}")
        return
    _expect(smoke, run.result, 6, True)
    smoke.shot(window, "global-result")
    window.open_sheet(("graph", index))
    smoke.wait()
    smoke.shot(window, "global-graph")

    # Cancel leaves the recipe as it was; a reopened dialog shows the confirmed values.
    confirmed = deepcopy(run.options)
    dialog = AnalysisDialog(window, frame, current=(METHOD, run.options), only=METHOD)
    dialog.show()
    app.processEvents()
    dialog.controls["Parameters"][1].set_scope(0, "Shared")
    dialog.reject()
    dialog.deleteLater()
    if window.project.runs[index].options != confirmed:
        smoke.problem("global fit: Cancel changed the recipe")

    # Save, reopen, recalculate.
    saved = smoke.folder / f"{smoke.language}-global-fit.alab"
    window.project.save(saved)
    window.open_path(saved)
    smoke.wait()
    reopened = next((i for i, item in enumerate(window.project.runs) if item.method == METHOD), None)
    if reopened is None or window.project.runs[reopened].options != confirmed:
        smoke.problem("global fit: the reopened recipe differs")
        return
    window.open_sheet(("result", reopened))
    smoke.wait()
    result = window.project.runs[reopened].result
    if result is None:
        smoke.problem("global fit: not recalculated after reopening")
        return
    _expect(smoke, result, 6, True)
    dialog = AnalysisDialog(window, frame, current=(METHOD, window.project.runs[reopened].options), only=METHOD)
    dialog.show()
    app.processEvents()
    _tabs(smoke, dialog, "global-reopened")
    dialog.reject()
    dialog.deleteLater()
    window.project.dirty = False
