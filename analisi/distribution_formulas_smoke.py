"""Desktop smoke check for probability, density and quantile formulas in the worksheet.

``tramastat.py --smoke`` calls :func:`check_distribution_formulas` with its own helpers.
Alone: ``TRAMASTAT_SMOKE_ONLY=distribution-formulas python tramastat.py --smoke DIR``.

Synthetic data only. The calculated column is typed into the real prompts of Calculated column, used in
a native XY graph, recalculated after an edit and an exclusion, exported to CSV, saved and reopened. A compatible
ZIP project written into the smoke folder is imported with its formula still active and editable.
"""
import json
from math import erfc, sqrt
from statistics import NormalDist
from tkinter import simpledialog
from unittest.mock import patch
from zipfile import ZipFile

import numpy as np
import pandas as pd

from . import i18n
from .data import Dataset, load_tables, save_project
from .graph_language_smoke import drive_mapped_dialog
from .worksheet_formula_dialog import WorksheetFormulaDialog

TITLE = "Distribution scores"
UPPER, ROW_TAIL = "Upper tail", "Row tail"
UPPER_FORMULA = 'NORMDIST(Score, 0, 1, "right")'
SCORES = [-1.5, -0.5, 0.0, 0.8, 1.6, 2.4]
TAILS = ["right", "left", "two", " One", "RIGHT", "sideways"]


def upper(z):
    return 0.5 * erfc(z / sqrt(2))


def row_tail(z, tail):
    key = tail.strip().casefold()
    if key == "left":
        return NormalDist().cdf(z)
    if key == "right":
        return upper(z)
    if key == "one":
        return upper(abs(z))
    if key == "two":
        return 2 * upper(abs(z))
    return np.nan


def drive_formula_editor(root, expression, errors, *, expected_error=None, before_accept=None):
    """Fill the actual worksheet formula editor and verify the submitted result."""
    def ready(dialog):
        try:
            dialog.expression.delete(0, "end")
            dialog.expression.insert(0, expression)
            if before_accept is not None:
                dialog.update()
                before_accept(dialog)
            dialog.ok()
            if expected_error is None:
                assert dialog.result is not None, dialog.problem.cget("text")
            else:
                assert dialog.result is None and expected_error in dialog.problem.cget("text")
                dialog.cancel()
        except Exception as error:
            errors.append(f"Formula editor: {error!r}")
            if dialog.winfo_exists():
                dialog.cancel()

    drive_mapped_dialog(root, WorksheetFormulaDialog, ready, errors)


def answer_prompts(root, tools, name, expression, *, shot=None, expected_error=None):
    """Enter a column name and then use the real formula editor."""
    def ready(dialog):
        try:
            dialog.entry.delete(0, "end")
            dialog.entry.insert(0, name)
            capture = (lambda formula: tools.capture(formula, shot)) if shot else None
            drive_formula_editor(root, expression, tools.errors, expected_error=expected_error, before_accept=capture)
            dialog.ok()
        except Exception as error:
            tools.errors.append(f"Calculated column name: {error!r}")
            if dialog.winfo_exists():
                dialog.cancel()

    drive_mapped_dialog(root, simpledialog.Dialog, ready, tools.errors)


def check_distribution_formulas(root, app, directory, tools):
    """Run the scenario in the language and theme the application started with."""
    screen = root.winfo_screenwidth(), root.winfo_screenheight()
    large = screen[0] >= 1600 and screen[1] >= 1000
    root.geometry(("1600x1000" if large else "1024x768") + "+0+0")
    root.update()
    suffix = f"-{i18n.active_language()}" + ("-1600" if large else "")
    report = {"screen": list(screen), "window": [root.winfo_width(), root.winfo_height()],
              "language": i18n.active_language()}
    _check(root, app, directory, tools, suffix, report)
    (directory / f"distribution-formulas{suffix}.json").write_text(json.dumps(report, indent=2) + "\n",
                                                                    encoding="utf-8")


def _check(root, app, directory, tools, suffix, report):  # noqa: C901 - one linear scenario, step by step
    errors = tools.errors
    source = pd.DataFrame({"Score": SCORES, "Tail": TAILS,
                           "Subject": [f"S{index + 1}" for index in range(len(SCORES))]})
    path = directory / f"distribution-formulas{suffix}.alab"
    save_project(path, {TITLE: Dataset(source)})
    app.import_file(path)
    root.update()

    # 1. A right-tail calculated column typed into the real prompts.
    answer_prompts(root, tools, UPPER, UPPER_FORMULA, shot=f"window-distribution-formula-prompt{suffix}.png")
    app.add_formula()
    root.update()
    assert not errors, errors
    data = app.tables[TITLE]
    assert data.formulas == {UPPER: UPPER_FORMULA}, data.formulas
    np.testing.assert_allclose(data.frame()[UPPER], [upper(z) for z in SCORES], rtol=1e-14)
    answer_prompts(root, tools, ROW_TAIL, "ZDIST(Score, Tail)")
    app.add_formula()
    assert not errors, errors
    row = data.frame()[ROW_TAIL].to_numpy()
    np.testing.assert_allclose(row[:5], [row_tail(z, t) for z, t in zip(SCORES[:5], TAILS[:5])], rtol=1e-14)
    assert np.isnan(row[5]), row
    tools.capture(root, f"window-distribution-worksheet{suffix}.png")

    # 2. The calculated column in a native XY graph.
    def choose(dialog):
        tools.pick_method(dialog, "XY series")
        dialog.controls["X"][1].set("Score")
        tools.select_columns(dialog, "Y columns", [UPPER])

    tools.drive_dialog(tools.AnalysisDialog, choose)
    app.choose_analysis()
    tools.wait_for_calculation()
    run = next(run for run in app.runs if run.title == TITLE)
    graph = run.result.figure

    def plotted():
        lines = [line for axes in run.result.figure.axes for line in axes.get_lines() if len(line.get_xdata())]
        x, y = np.asarray(lines[0].get_xdata(), dtype=float), np.asarray(lines[0].get_ydata(), dtype=float)
        order = np.argsort(x)
        return x[order], y[order]

    x, y = plotted()
    np.testing.assert_allclose(x, sorted(SCORES))
    np.testing.assert_allclose(y, [upper(z) for z in sorted(SCORES)], rtol=1e-12)
    app.open_sheet(("graph", app.runs.index(run)))
    root.update()
    tools.capture(root, f"window-distribution-graph{suffix}.png")

    # 3. Editing a source value recalculates the column and the graph.
    app.open_sheet(("data", TITLE))
    root.update()
    app.edit_cell(0, 0, "3")
    tools.wait_for_calculation()
    edited = [3.0] + SCORES[1:]
    np.testing.assert_allclose(app.tables[TITLE].frame()[UPPER], [upper(z) for z in edited], rtol=1e-14)
    assert run.result is not None and run.result.figure is not graph, "the graph was not recalculated"
    x, y = plotted()
    np.testing.assert_allclose(x, sorted(edited))
    np.testing.assert_allclose(y, [upper(z) for z in sorted(edited)], rtol=1e-12)
    app.open_sheet(("graph", app.runs.index(run)))
    root.update()
    tools.capture(root, f"window-distribution-graph-edited{suffix}.png")

    # 4. A wrong argument count, then an unknown literal tail, then the correction.
    app.open_sheet(("data", TITLE))
    root.update()
    before = dict(data.formulas)
    for wrong, message in (('NORMDIST(Score, 0, 1, "right", 2)', "NORMDIST takes 1 to 4 arguments"),
                           ('ZDIST(Score, "upper")', 'the tail must be "left", "right", "one" or "two"')):
        answer_prompts(root, tools, UPPER, wrong, expected_error=message)
        app.add_formula()
        root.update()
        assert not errors, errors
        assert data.formulas == before, data.formulas
    answer_prompts(root, tools, UPPER, 'NORMDIST(Score, 0, 1, " Right ")',
                   shot=f"window-distribution-formula-corrected{suffix}.png")
    app.add_formula()
    tools.wait_for_calculation()
    assert not errors, errors
    assert data.formulas[UPPER] == 'NORMDIST(Score, 0, 1, " Right ")'
    np.testing.assert_allclose(data.frame()[UPPER], [upper(z) for z in edited], rtol=1e-14)

    # 5. Excluding a source cell blanks only that row, in the worksheet and in the graph.
    app.open_sheet(("data", TITLE))
    root.update()
    app.current_grid.active_cell = (2, 0)
    app.toggle_exclusion()
    tools.wait_for_calculation()
    masked = data.frame(mask_excluded=True)[UPPER].to_numpy()
    assert np.isnan(masked[2]) and np.isnan(data.frame()[UPPER][2]), masked
    np.testing.assert_allclose(np.delete(masked, 2), [upper(z) for z in np.delete(edited, 2)], rtol=1e-14)
    x, y = plotted()
    kept = sorted(np.delete(edited, 2))
    np.testing.assert_allclose(x[np.isfinite(y)], kept)
    tools.capture(root, f"window-distribution-excluded{suffix}.png")
    app.open_sheet(("graph", app.runs.index(run)))
    root.update()
    tools.capture(root, f"window-distribution-graph-excluded{suffix}.png")

    # 6. CSV export of the worksheet.
    app.open_sheet(("data", TITLE))
    root.update()
    target = directory / f"distribution-formulas{suffix}.csv"
    with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
        app.export()
    exported = load_tables(target)[target.stem]
    np.testing.assert_allclose(exported[UPPER].to_numpy(dtype=float), masked, rtol=1e-12)

    # 7. Save and reopen the project: formulas, exclusion and values come back, still live.
    assert app.save()
    app.import_file(path)
    tools.wait_for_calculation()
    reopened = app.tables[TITLE]
    assert reopened.formulas == data.formulas, reopened.formulas
    assert (2, 0) in reopened.excluded
    pd.testing.assert_frame_equal(reopened.frame(mask_excluded=True), data.frame(mask_excluded=True),
                                  check_dtype=False)
    app.open_sheet(("data", TITLE))
    root.update()
    app.edit_cell(1, 0, "0")
    tools.wait_for_calculation()
    assert reopened.frame()[UPPER][1] == 0.5
    tools.capture(root, f"window-distribution-reopened{suffix}.png")

    # 8. A compatible ZIP project with an active formula stays live and editable.
    archive = directory / f"distribution-import{suffix}.prism"
    with ZipFile(archive, "w") as zipped:
        zipped.writestr("document.json", json.dumps({"sheets": {"data": ["synthetic"]}}))
        zipped.writestr("data/sheets/synthetic/sheet.json", json.dumps({"title": "Imported scores", "table": {
            "uid": "values", "format": "multivariable", "dataFormat": "y_single", "dataSets": ["a", "b"]}}))
        zipped.writestr("data/sets/a.json", json.dumps({"title": "Measured score"}))
        zipped.writestr("data/sets/b.json", json.dumps({"title": "Upper probability", "valuesStorageData": {
            "@class": "TransformDataSource", "transform": 'NORMDIST(A, 0, 1, "right")'}}))
        zipped.writestr("data/tables/values/data.csv", "0,999\n1,999\n2,999\n")
    app.import_file(archive)
    root.update()
    imported_title = next(name for name in app.tables if name.startswith("Imported scores"))
    imported = app.tables[imported_title]
    assert list(imported.raw) == ["Measured score"] and "Upper probability" in imported.formulas, imported.formulas
    np.testing.assert_allclose(imported.frame()["Upper probability"], [0.5, upper(1), upper(2)], rtol=1e-14)
    app.open_sheet(("data", imported_title))
    root.update()
    tools.capture(root, f"window-distribution-imported{suffix}.png")
    recipe = imported.formulas["Upper probability"]
    answer_prompts(root, tools, "Upper probability", recipe.replace('"right"', '"two"'),
                   shot=f"window-distribution-imported-edit{suffix}.png")
    app.add_formula()
    root.update()
    assert not errors, errors
    assert '"two"' in imported.formulas["Upper probability"]
    app.edit_cell(2, 0, "-2")
    root.update()
    np.testing.assert_allclose(imported.frame()["Upper probability"], [1.0, 2 * upper(1), 2 * upper(2)],
                               rtol=1e-14)
    tools.capture(root, f"window-distribution-imported-edited{suffix}.png")
    report.update({"formulas": data.formulas, "imported_formula": imported.formulas["Upper probability"],
                   "graph_points": int(np.isfinite(plotted()[1]).sum()), "status": "PASS"})
