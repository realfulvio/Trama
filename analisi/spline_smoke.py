"""Desktop smoke check for Fit spline/LOWESS (0.54).

``tramastat.py --smoke`` calls :func:`check_spline_fit` with its own helpers.
Alone: ``TRAMASTAT_SMOKE_ONLY=spline python tramastat.py --smoke DIR``.
"""
from unittest.mock import patch

import numpy as np
import pandas as pd

from . import spline_fit as sf
from .data import Dataset, save_project
from .workbench import analyse

METHOD = sf.SPLINE_FIT
LEGACY_METHOD = "Smooth / differentiate / integrate"
DUPLICATES, NATURAL, LOWESS_DATA, LEGACY = "Spline duplicates", "Spline natural", "Spline LOWESS", "Legacy smoothing"
DUPLICATE_FRAME = pd.DataFrame({
    "X": [2, 0, 1, 1, 2.5, 3, 4, 5, 6], "Y": [3, 0, 1, 3, 3, 3, 0, 4, None],
    "Query X": [0, 5, 1.5, 1.5, -1, 5.1, 2.25, None, 2.75], "Query Y": [1, 3, 1, 4.5, 0, 2, 2.5, None, 3],
    "Row title": ["At two", "At zero", "Replicate A", "Replicate B", "Inside plateau", "At three", "At four",
                  "Rising endpoint", "Missing standard"]})
NATURAL_FRAME = pd.DataFrame({
    "X": [2., 0, 4, 1, 3], "Y": [0., 4, 4, 1, 1], "Query X": [0, 4, 1.5, 2.5, 4.1], "Query Y": [0, 1, 4, 5, 1],
    "Row title": ["Tangent", "Left", "Right", "First inner", "Second inner"]})
LOWESS_FRAME = pd.DataFrame({
    "X": [6., 0, 1, 13, 2, 3, 12, 4, 5, 11, 7, 8, 9, 10],
    "Y": [12.65, 1.06, 1.65, 10.02, 2.43, 3.02, 9.43, 3.89, 4.56, 8.65, 5.93, 6.52, 7.39, 8.06],
    "Query X": [0, 13, 6, 6.5, 4.25, -1, 14] + [None] * 7,
    "Row title": [f"Sample {i}" for i in range(1, 15)]})
LEGACY_OPTIONS = {"X": "X", "Y": "Y", "Method": "LOWESS", "LOWESS fraction": .6}


def check_spline_fit(root, app, directory, tools):
    """``tools`` carries the smoke helpers: AnalysisDialog, capture, drive_dialog, pick_method,
    wait_for_calculation, messagebox and filedialog."""
    wait = tools.wait_for_calculation
    path = directory / "spline-lowess.alab"
    frames = {DUPLICATES: DUPLICATE_FRAME, NATURAL: NATURAL_FRAME, LOWESS_DATA: LOWESS_FRAME,
              LEGACY: LOWESS_FRAME[["X", "Y"]]}
    datasets = {title: Dataset(frame.copy()) for title, frame in frames.items()}
    datasets[LEGACY].analyses.append((LEGACY_METHOD, dict(LEGACY_OPTIONS)))
    save_project(path, datasets)
    app.import_file(path)

    # The Smooth / differentiate / integrate recipe keeps its sheet, columns and values.
    legacy = next(position for position, run in enumerate(app.runs) if run.method == LEGACY_METHOD)
    app.open_sheet(("result", legacy))
    wait()
    assert app.runs[legacy].options == LEGACY_OPTIONS, app.runs[legacy].options
    expected = analyse(LEGACY_METHOD, datasets[LEGACY].frame(mask_excluded=True), LEGACY_OPTIONS)
    assert list(app.runs[legacy].result.tables) == ["Curve"]
    pd.testing.assert_frame_equal(app.runs[legacy].result.tables["Curve"], expected.tables["Curve"])

    def placed(dialog, name):
        return bool(dialog.field_rows[name][1].winfo_manager())

    def rejected(dialog, field, shot=None):
        with patch.object(tools.messagebox, "showerror") as report:
            assert dialog.validate() is False, field
        assert dialog.winfo_exists()
        assert field in report.call_args.args[1], report.call_args
        assert dialog.fields.select() == str(dialog.field_rows[field][1].master), field
        if shot:
            tools.capture(dialog, shot)

    def fields(dialog, values):
        for name, value in values:
            dialog.controls[name][1].set(value)
            dialog.update()

    def latest():
        return len(app.runs) - 1

    # Reject on duplicates, then Average: a plateau and an isolated root for Y = 3.
    app.show("data", DUPLICATES)

    def duplicates(dialog):
        tools.pick_method(dialog, METHOD)
        assert dialog.controls[sf.METHOD][1].get() == sf.POINT
        assert dialog.controls[sf.DIRECTION][1].get() == sf.NO_QUERY
        assert not placed(dialog, sf.QUERY) and not placed(dialog, sf.KNOTS) and not placed(dialog, sf.FRACTION)
        fields(dialog, (("X", "X"), ("Y", "Y"), (sf.DIRECTION, sf.X_FROM_Y)))
        assert placed(dialog, sf.QUERY)
        rejected(dialog, sf.QUERY)
        fields(dialog, ((sf.QUERY, "Query Y"),))
        rejected(dialog, "X", "window-spline-duplicate-error.png")
        fields(dialog, ((sf.DUPLICATES, sf.AVERAGE), (sf.METHOD, sf.SMOOTH)))
        assert placed(dialog, sf.KNOTS) and not placed(dialog, sf.ITERATIONS)
        fields(dialog, ((sf.KNOTS, "9"),))
        rejected(dialog, sf.KNOTS)
        fields(dialog, ((sf.METHOD, sf.LOWESS),))
        assert placed(dialog, sf.FRACTION) and placed(dialog, sf.ITERATIONS) and not placed(dialog, sf.KNOTS)
        rejected(dialog, "X")  # LOWESS needs 12 distinct X
        fields(dialog, ((sf.METHOD, sf.POINT), (sf.SEGMENTS, "8")))
        dialog.fields.select(dialog.field_rows[sf.DIRECTION][1].master)
        tools.capture(dialog, "window-spline-options.png")

    tools.drive_dialog(tools.AnalysisDialog, duplicates)
    app.choose_analysis()
    wait()
    point = latest()
    run = app.runs[point]
    # Hidden method fields stay out of the recipe.
    assert sf.KNOTS not in run.options and sf.FRACTION not in run.options, run.options
    tables = run.result.tables
    assert list(tables) == [sf.SUPPORT, sf.COORDINATES, sf.VALUES, sf.SOLUTIONS, sf.PLATEAUS], list(tables)
    assert tables[sf.SUPPORT].loc[1, ["X", "Y", "N"]].tolist() == [1.0, 2.0, 2]
    values = tables[sf.VALUES]
    assert values["Row title"].iloc[0] == "At two"
    assert values.loc[values["Query"] == 3.0, "Status"].tolist() == [sf.AMBIGUOUS] * 2
    assert tables[sf.PLATEAUS][["X lower", "X upper"]].drop_duplicates().to_numpy().tolist() == [[2.0, 3.0]]
    assert 4.75 in tables[sf.SOLUTIONS]["X"].tolist()
    app.show("result", point)
    app.result_tabs.select(list(tables).index(sf.SOLUTIONS))
    root.update()
    tools.capture(root, "window-spline-inverse-solutions.png")
    app.result_tabs.select(list(tables).index(sf.PLATEAUS))
    root.update()
    tools.capture(root, "window-spline-inverse-plateaus.png")
    csv = directory / "spline-inverse-solutions.csv"
    app.result_tabs.select(list(tables).index(sf.SOLUTIONS))
    with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(csv)):
        app.export()
    assert "Solution" in csv.read_text(encoding="utf-8-sig")
    before = set(app.tables)
    app.show("result", point)
    app.result_tabs.select(list(tables).index(sf.SOLUTIONS))
    app.use_result_as_data()
    added = set(app.tables) - before
    assert len(added) == 1, added
    assert list(app.tables[added.pop()].raw.columns) == ["Source row", "Solution", "X"]

    # The same answers with 1000 drawn segments.
    app.show("result", point)
    tools.drive_dialog(tools.AnalysisDialog, lambda dialog: fields(dialog, ((sf.SEGMENTS, "1000"),)))
    app.edit_analysis()
    wait()
    fine = app.runs[point].result.tables
    assert len(fine[sf.COORDINATES]) == 1001
    for sheet in (sf.VALUES, sf.SOLUTIONS, sf.PLATEAUS):
        pd.testing.assert_frame_equal(fine[sheet], tables[sheet])

    # Cubic spline with residuals and Y from X, then the two roots of Y = 1.
    app.show("data", NATURAL)

    def natural(dialog):
        tools.pick_method(dialog, METHOD)
        fields(dialog, (("X", "X"), ("Y", "Y"), (sf.METHOD, sf.CUBIC), (sf.DIRECTION, sf.Y_FROM_X),
                        (sf.QUERY, "Query X"), (sf.SEGMENTS, "60")))
        dialog.controls[sf.RESIDUALS][1].set(True)
        dialog.update()

    tools.drive_dialog(tools.AnalysisDialog, natural)
    app.choose_analysis()
    wait()
    cubic = latest()
    result = app.runs[cubic].result
    assert list(result.tables) == [sf.SUPPORT, sf.COORDINATES, sf.RESIDUAL_SHEET, sf.VALUES], list(result.tables)
    assert result.tables[sf.VALUES]["Status"].tolist() == [sf.IN_RANGE] * 4 + [sf.OUTSIDE]
    np.testing.assert_allclose(result.tables[sf.RESIDUAL_SHEET]["Residual"].astype(float), 0, atol=1e-12)
    labels = [text.get_text() for text in result.figure.axes[0].get_legend().get_texts()]
    assert labels == ["Support points", "Cubic spline", "Y from X queries"], labels
    app.show("graph", cubic)
    tools.capture(root, "window-spline-cubic-graph.png")
    for suffix in ("png", "svg"):
        target = directory / f"spline-cubic.{suffix}"
        with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
            app.show("graph", cubic)
            app.export()
        assert target.stat().st_size > 1000, target
    assert b"<svg" in (directory / "spline-cubic.svg").read_bytes()
    before = set(app.tables)
    app.show("result", cubic)
    app.result_tabs.select(list(result.tables).index(sf.COORDINATES))
    app.use_result_as_data()
    added = set(app.tables) - before
    assert len(added) == 1 and len(app.tables[added.pop()].raw) == 61

    def inverse(dialog):
        fields(dialog, ((sf.DIRECTION, sf.X_FROM_Y), (sf.QUERY, "Query Y")))

    app.show("result", cubic)
    tools.drive_dialog(tools.AnalysisDialog, inverse)
    app.edit_analysis()
    wait()
    roots = app.runs[cubic].result.tables
    assert roots[sf.VALUES]["Status"].tolist() == [sf.IN_RANGE, sf.AMBIGUOUS, sf.AMBIGUOUS, sf.OUTSIDE,
                                                   sf.AMBIGUOUS], roots[sf.VALUES]["Status"].tolist()
    assert roots[sf.VALUES]["Value"].iloc[0] == 2.0
    first = roots[sf.SOLUTIONS].loc[roots[sf.SOLUTIONS]["Source row"] == 1, "X"].tolist()
    np.testing.assert_allclose(first, [1.0, 3.0], atol=1e-12)
    app.show("result", cubic)
    app.result_tabs.select(list(roots).index(sf.SOLUTIONS))
    root.update()
    tools.capture(root, "window-spline-cubic-roots.png")

    # LOWESS without, then with robust iterations; then an edit and an exclusion recalculate it.
    app.show("data", LOWESS_DATA)

    def smooth(dialog):
        tools.pick_method(dialog, METHOD)
        fields(dialog, (("X", "X"), ("Y", "Y"), (sf.METHOD, sf.LOWESS), (sf.FRACTION, "0.6"), (sf.ITERATIONS, "0"),
                        (sf.DIRECTION, sf.Y_FROM_X), (sf.QUERY, "Query X")))
        dialog.controls[sf.RESIDUALS][1].set(True)
        dialog.update()
        fields(dialog, ((sf.FRACTION, "0.15"),))
        rejected(dialog, sf.FRACTION, "window-spline-lowess-fraction-error.png")
        fields(dialog, ((sf.FRACTION, "0.6"), (sf.ITERATIONS, "4")))
        rejected(dialog, sf.ITERATIONS)
        fields(dialog, ((sf.ITERATIONS, "0"),))

    tools.drive_dialog(tools.AnalysisDialog, smooth)
    app.choose_analysis()
    wait()
    loess = latest()
    plain = app.runs[loess].result.tables
    assert len(plain[sf.COORDINATES]) == max(sf.DEFAULT_SEGMENTS, 4 * 14) + 1
    outlier = abs(float(plain[sf.RESIDUAL_SHEET]["Residual"].iloc[0]))
    app.show("result", loess)
    tools.drive_dialog(tools.AnalysisDialog, lambda dialog: fields(dialog, ((sf.ITERATIONS, "3"),)))
    app.edit_analysis()
    wait()
    robust = app.runs[loess].result.tables
    assert app.runs[loess].options[sf.ITERATIONS] == 3
    assert abs(float(robust[sf.RESIDUAL_SHEET]["Residual"].iloc[0])) > outlier + 1
    app.show("graph", loess)
    tools.capture(root, "window-spline-lowess-graph.png")
    columns = list(app.tables[LOWESS_DATA].raw.columns)
    app.show("data", LOWESS_DATA)
    app.edit_cell(0, columns.index("Y"), "6.2")
    wait()
    edited = app.runs[loess].result.tables
    assert edited[sf.SUPPORT].loc[edited[sf.SUPPORT]["X"] == 6, "Y"].tolist() == [6.2]
    app.show("data", LOWESS_DATA)
    app.current_grid.select((2, columns.index("Query X")))
    app.toggle_exclusion()
    wait()
    excluded = app.runs[loess].result.tables[sf.VALUES]
    assert 2 not in excluded["Source row"].tolist() and len(excluded) == 6, excluded

    # Save and reopen: every recipe keeps its options and tables.
    def recipes():
        found = {}
        for position, item in enumerate(app.runs):
            if item.method in (METHOD, LEGACY_METHOD):
                found.setdefault(item.title, []).append(position)
        return found

    for position in [p for items in recipes().values() for p in items]:
        app.open_sheet(("result", position))
        wait()
    saved = {title: [(dict(app.runs[position].options),
                      {name: table.copy() for name, table in app.runs[position].result.tables.items()})
                     for position in positions]
             for title, positions in recipes().items()}
    app.path = path
    assert app.save()
    app.import_file(path)
    reopened = recipes()
    assert {title: len(items) for title, items in reopened.items()} == {
        title: len(items) for title, items in saved.items()}, reopened
    for title, positions in reopened.items():
        for position, (options, tables) in zip(positions, saved[title], strict=True):
            app.open_sheet(("result", position))
            wait()
            assert app.runs[position].options == options, (title, app.runs[position].options, options)
            assert list(app.runs[position].result.tables) == list(tables)
            for name, table in tables.items():
                pd.testing.assert_frame_equal(app.runs[position].result.tables[name], table)
