"""Reshape long and wide in the desktop smoke (``python -m trama_qt --smoke FOLDER``).

From a long table with literal names (spaces, "$", "|", accents), "001" keys and a blank measure, it drives the real
editor: an ambiguous key with the error on ID columns and the cursor there, the correction, the preview page, a
trip to Wide to long and back, Run on the Qt worker, the CSV export of the result, a live Column graph that reads
the reshaped table, an excluded cell recalculated through the chain, Cancel of the dialog and of a calculation
on the existing recipe, then save, reopen and recalculation. Screenshots are named ``<lang>-reshape-*.png``; the
project is kept as ``<lang>-reshape.alab`` and the export as ``<lang>-reshape-wide.csv``. Problems go to the report.
"""
from copy import deepcopy
from unittest import mock

import pandas as pd
from PySide6.QtWidgets import QApplication

METHOD = "Reshape long and wide"
TITLE = "reshape visits"
DATA = pd.DataFrame({"Sample $": ["001", "001", "001", "001", "002", "002", "002", "002"],
                     "Rep": [1, 1, 2, 2, 1, 1, 2, 2],
                     "Visit": ["A | Start", "Fine à"] * 4,
                     "Measure": [5, 6, 0, None, 8, 7, 9, 11]})
RECIPE = {"Direction": "Long to wide", "ID columns": ["Sample $", "Rep"], "Name column": "Visit",
          "Value column": "Measure"}
EXPECTED = [["001", 1, 5, 6], ["001", 2, 0, None], ["002", 1, 8, 7], ["002", 2, 9, 11]]


def _cells(table):
    return [[None if pd.isna(value) else value for value in row] for row in table.itertuples(index=False, name=None)]


def _check(smoke, run, expected, label):
    if run is None or run.result is None or run.calculation_error:
        smoke.problem(f"reshape {label}: not calculated ({getattr(run, 'calculation_error', None)})")
        return False
    table = run.result.tables["Reshaped data"]
    if list(table.columns) != ["Sample $", "Rep", "A | Start", "Fine à"] or _cells(table) != expected:
        smoke.problem(f"reshape {label}: unexpected table {list(table.columns)} {_cells(table)}")
        return False
    return True


def exercise(smoke, window):
    from analisi.analysis_chain import ResultSource, result_frame
    from .analysis_dialog import AnalysisDialog
    app = QApplication.instance()
    path = smoke.folder / f"{TITLE}.csv"
    DATA.to_csv(path, index=False)
    window.open_path(path)
    smoke.wait()
    project = window.project
    frame = project.tables[TITLE].frame(mask_excluded=True)

    # A new analysis: one ID column only is ambiguous; the error stays on ID columns with the recipe intact.
    dialog = AnalysisDialog(window, frame, current=(METHOD, {}), only=METHOD)
    dialog.show()
    dialog.activateWindow()
    app.processEvents()
    editor = dialog.reshape
    editor.ids.set_values(["Sample $"])
    editor.name.setCurrentIndex(editor.name.findData("Visit"))
    editor.value.setCurrentIndex(editor.value.findData("Measure"))
    dialog.accept()
    app.processEvents()
    if dialog.result is not None or not dialog.banner.isVisible():
        smoke.problem("reshape: an ambiguous key was accepted")
    elif not editor.ids.list.hasFocus():
        smoke.problem("reshape: the error does not put the cursor on ID columns")
    smoke.shot(dialog, "reshape-error")
    editor.ids.set_values(["Sample $", "Rep"])
    editor.refresh_preview()
    dialog.tabs.setCurrentWidget(editor.preview_page)
    smoke.shot(dialog, "reshape-preview")
    if (editor.table.rowCount(), editor.table.columnCount()) != (4, 4):
        smoke.problem(f"reshape: preview is {editor.table.rowCount()}×{editor.table.columnCount()}, expected 4×4")
    dialog.tabs.setCurrentIndex(0)
    editor.direction.setCurrentIndex(editor.direction.findData("Wide to long"))
    editor.refresh_preview()
    smoke.shot(dialog, "reshape-wide-to-long")
    editor.direction.setCurrentIndex(editor.direction.findData("Long to wide"))
    editor.refresh_preview()
    smoke.shot(dialog, "reshape-dialog")
    dialog.accept()
    app.processEvents()
    if dialog.result != (METHOD, RECIPE):
        smoke.problem(f"reshape: dialog gave {dialog.result}, banner {dialog.banner.text()}")
        dialog.reject()
        return
    method, options = dialog.result
    dialog.deleteLater()
    window.calculate_candidate(project.candidate(TITLE, method, options), frame, None)
    smoke.wait()
    index = len(project.runs) - 1
    run = project.runs[index]
    if not _check(smoke, run, EXPECTED, "run"):
        return
    window.open_sheet(("result", index))
    smoke.wait()
    smoke.shot(window, "reshape-result")

    # Export the reshaped table to CSV, as File → Export does on the open result.
    target = smoke.folder / f"{smoke.language}-reshape-wide.csv"
    with mock.patch("trama_qt.window.QFileDialog.getSaveFileName", return_value=(str(target), "")):
        window.result_tabs.setCurrentIndex(0)
        window.export()
    try:
        written = pd.read_csv(target, encoding="utf-8-sig", index_col=0, dtype={"Sample $": str})
        if written["Sample $"].tolist() != ["001", "001", "002", "002"] or list(written.columns)[2:] != [
                "A | Start", "Fine à"]:
            smoke.problem(f"reshape: exported CSV differs: {list(written.columns)}")
    except (OSError, ValueError, KeyError) as error:
        smoke.problem(f"reshape: export failed: {error}")

    # A live Column graph on the reshaped table.
    source = ResultSource(run.uid, "Reshaped data")
    graph = project.candidate(TITLE, "Column graph", {"Variables": ["A | Start", "Fine à"]}, source=source)
    window.calculate_candidate(graph, result_frame(run.result, "Reshaped data"), None)
    smoke.wait()
    graph_index = len(project.runs) - 1
    if project.runs[graph_index].result is None or project.runs[graph_index].source != source:
        smoke.problem("reshape: the linked graph was not calculated")
        return
    window.open_sheet(("graph", graph_index))
    smoke.wait()
    smoke.shot(window, "reshape-graph")

    # Exclude a measure: the reshaped cell turns blank, its map row stays, the graph follows.
    measure = list(project.tables[TITLE].raw.columns).index("Measure")
    before = project.runs[graph_index].result
    affected = project.toggle_exclusion(TITLE, [(4, measure)])
    window.refresh_runs(affected)
    smoke.wait()
    excluded = deepcopy(EXPECTED)
    excluded[2][2] = None
    _check(smoke, project.runs[index], excluded, "after exclusion")
    if len(project.runs[index].result.tables["Source map"]) != 8:
        smoke.problem("reshape: the excluded measure lost its map row")
    if project.runs[graph_index].result is before or project.runs[graph_index].calculation_error:
        smoke.problem("reshape: the linked graph was not recalculated after the exclusion")

    # Cancel the dialog, then cancel a calculation of a changed recipe: the confirmed recipe stays.
    confirmed = deepcopy(project.runs[index].options)
    current = project.tables[TITLE].frame(mask_excluded=True)
    dialog = AnalysisDialog(window, current, current=(METHOD, confirmed), only=METHOD)
    dialog.show()
    app.processEvents()
    dialog.reshape.direction.setCurrentIndex(dialog.reshape.direction.findData("Wide to long"))
    dialog.reject()
    dialog.deleteLater()
    changed = project.candidate(TITLE, METHOD, {**confirmed, "ID columns": ["Rep", "Sample $"]}, index=index)
    window.calculate_candidate(changed, current, index)
    window.cancel_calculation()
    smoke.wait()
    if project.runs[index].options != confirmed:
        smoke.problem("reshape: Cancel changed the recipe")

    # Save, reopen, recalculate the reshape and the linked graph.
    saved = smoke.folder / f"{smoke.language}-reshape.alab"
    project.save(saved)
    project.dirty = False
    if not window.close_project():
        smoke.problem("reshape: the saved project did not close")
        return
    window.open_path(saved)
    smoke.wait()
    project = window.project
    runs = project.runs
    reopened = next((i for i, item in enumerate(runs) if item.method == METHOD), None)
    if reopened is None or runs[reopened].options != confirmed:
        smoke.problem("reshape: the reopened recipe differs")
        return
    window.open_sheet(("result", reopened))
    smoke.wait()
    _check(smoke, runs[reopened], excluded, "after reopening")
    linked = next((i for i, item in enumerate(runs) if item.source is not None), None)
    if linked is None or runs[linked].source.analysis_id != runs[reopened].uid:
        smoke.problem("reshape: the link to the graph was not reopened")
        return
    window.open_sheet(("graph", linked))
    smoke.wait()
    if runs[linked].result is None or runs[linked].calculation_error:
        smoke.problem(f"reshape: the linked graph was not recalculated after reopening: {runs[linked].calculation_error}")
    smoke.shot(window, "reshape-reopened")
    project.dirty = False
