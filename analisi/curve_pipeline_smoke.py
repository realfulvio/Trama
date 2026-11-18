"""Desktop smoke check for the Curve pipeline (0.93).

``tramastat.py --smoke`` calls :func:`check_curve_pipeline` with its own helpers.
Alone: ``TRAMASTAT_SMOKE_ONLY=curve-pipeline python tramastat.py --smoke DIR``.

It works in the language and theme of the isolated preferences it runs under, so the same file serves the English and
the Italian, the standard and the Modern run. Every number is synthetic. The expected values are written down by hand
or computed with plain Python and numpy on the sorted points, never with the engine under test.
"""
import json
import resource
import time
import traceback
import tracemalloc
from unittest.mock import patch

import numpy as np
import pandas as pd

from . import curve_pipeline as cp
from . import i18n
from .data import Dataset, save_project
from .field_error import FieldError
from .graph_language_smoke import drive_mapped_dialog
from .workbench import analyse

METHOD, PIPELINE = cp.CURVE_METHOD, cp.PIPELINE
LEGACY, UNIFORM, IRREGULAR, GAPS = "Legacy recipe", "Uniform grid", "Irregular grid", "Gaps"
SHIFTED, BLOCKS, MIXED, INVALID, LARGE = "Shifted grid", "Blocks", "Mixed columns", "Invalid Y", "Fifty thousand"
LEGACY_OPTIONS = {"X": "X", "Y": "Y", "Method": "LOWESS", "LOWESS fraction": .6}
SG = cp.SAVITZKY_GOLAY
WINDOW_5 = np.array([-3., 12, 17, 12, -3]) / 35  # Savitzky–Golay, 5 points, degree 2: the specification's weights
LARGE_ROWS = 50_000

CLEAN = [3., 6, 11, 18, 27, 38, 51, 66, 83]
IMPULSE = [3., 6, 11, 32, 27, 38, 51, 66, 83]
UNIFORM_FRAME = pd.DataFrame({"X": np.arange(9.), "Clean": CLEAN, "Impulse": IMPULSE})
IRREGULAR_FRAME = pd.DataFrame({"X": [3., 0, 10, 1, 6], "Y": [18., 3, 123, 6, 51]})
GAPS_FRAME = pd.DataFrame({"X": np.array([0, 1, 2, 3, 5, 6], dtype="int64"), "Y": [2., 4, np.nan, 8, 12, 14]})
# A shifted and rescaled grid: seconds from 1000, readings in thousandths. Y = 1000 (2 u² + 3 u + 1), u = X - 1000.
_U = .5 * np.arange(10)
SHIFTED_FRAME = pd.DataFrame({"Time (s)": 1000 + _U, "Signal (mV)": 1000 * (2 * _U ** 2 + 3 * _U + 1)})
# Rising then falling, a gap, a two-point block, a gap, a lone point and, at the bottom of the sheet, the smallest X.
BLOCKS_FRAME = pd.DataFrame({
    "X": [0., 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, -1],
    "Y": [0., 1, 4, 9, 16, 9, 4, 1, np.nan, 5, 7, np.nan, 3, 1]})
# Text, an integer count, dates, an unsorted time column and a reading with a blank, as in a real worksheet.
MIXED_FRAME = pd.DataFrame({
    "Sample": [f"S{i}" for i in range(1, 9)],
    "Elapsed (s)": [4., 0, 2, 6, 1, 5, 3, 7],
    "Reading": [16., 0, 4, 36, 1, np.nan, 9, 49],
    "Count": np.arange(8, dtype="int64"),
    "Note": ["", "first", "", "", "", "blank reading", "", "last"]})
INVALID_FRAME = pd.DataFrame({"X": [0., 1, 2, 3, 4], "Y": ["1", "2", "n/a", "4", "5"]})

# Hand-written results (X, Value, Block, First source row, Last source row).
FIRST_BLOCKS = [[-.5, -1, 1, 13, 0], [.5, 1, 1, 0, 1], [1.5, 3, 1, 1, 2], [2.5, 5, 1, 2, 3], [3.5, 7, 1, 3, 4],
                [4.5, -7, 1, 4, 5], [5.5, -5, 1, 5, 6], [6.5, -3, 1, 6, 7], [9.5, 2, 2, 9, 10]]
SECOND_BLOCKS = [[0., 2, 1, 13, 1], [1., 2, 1, 0, 2], [2., 2, 1, 1, 3], [3., 2, 1, 2, 4], [4., -14, 1, 3, 5],
                 [5., 2, 1, 4, 6], [6., 2, 1, 5, 7]]
FIRST_GAPS = [[.5, 2, 1, 0, 1], [4, 2, 2, 3, 4], [5.5, 2, 2, 4, 5]]
SECOND_IRREGULAR = [[1.25, 2, 1, 1, 0], [3.25, 2, 1, 3, 4], [6.25, 2, 1, 0, 2]]
FIRST_THEN_SMOOTH_CLEAN = [[2.5, 7, 1, 0, 5], [3.5, 9, 1, 1, 6], [4.5, 11, 1, 2, 7], [5.5, 13, 1, 3, 8]]
RUN_FIELDS = {"X": "X", "Y": "Y"}


def rows_of(table):
    return table.to_numpy(dtype=float)


def check_curve_pipeline(root, app, directory, tools):
    """``tools`` carries the smoke helpers: AnalysisDialog, capture, drive_dialog, pick_method,
    wait_for_calculation, messagebox, filedialog and the smoke's errors list."""
    wait = tools.wait_for_calculation
    out = directory / "curve-pipeline"
    out.mkdir(exist_ok=True)
    path = directory / "curve-pipeline.alab"
    report = {"language": i18n.active_language()}

    datasets = {title: Dataset(frame.copy()) for title, frame in {
        LEGACY: UNIFORM_FRAME[["X", "Clean"]].rename(columns={"Clean": "Y"}), UNIFORM: UNIFORM_FRAME,
        IRREGULAR: IRREGULAR_FRAME, GAPS: GAPS_FRAME, SHIFTED: SHIFTED_FRAME, BLOCKS: BLOCKS_FRAME,
        MIXED: MIXED_FRAME, INVALID: INVALID_FRAME}.items()}
    datasets[LEGACY].analyses.append((METHOD, dict(LEGACY_OPTIONS)))
    save_project(path, datasets)
    app.import_file(path)

    def placed(dialog, name):
        return bool(dialog.field_rows[name][1].winfo_manager())

    def shown(dialog):
        return {name for name in dialog.controls if placed(dialog, name)}

    def fields(dialog, values):
        for name, value in values:
            dialog.controls[name][1].set(value)
            dialog.update()

    def names(field, message):
        text = message.lower()
        return field.lower() in text or i18n.ui(field).lower() in text

    def rejected(dialog, field, shot=None):
        """The dialog stays open on the page of the wrong field, shows it and gives it the keyboard focus."""
        with patch.object(tools.messagebox, "showerror") as banner:
            assert dialog.validate() is False, field
        assert dialog.winfo_exists()
        message = banner.call_args.args[1]
        assert names(field, message), (field, message)
        control = dialog.field_rows[field][1]
        assert dialog.fields.select() == str(control.master), field
        assert control.winfo_viewable(), field
        assert dialog.initial_focus is control, (field, dialog.initial_focus)
        if shot:
            tools.capture(dialog, shot)
        return message

    def latest():
        return len(app.runs) - 1

    def new_run(title, values, *, inspect=None):
        """A Curve pipeline analysis of one worksheet, driven through the real dialog."""
        app.show("data", title)

        def drive(dialog):
            tools.pick_method(dialog, METHOD)
            assert dialog.controls["Method"][1].get() == "LOWESS"
            fields(dialog, (("Method", PIPELINE), *values))
            if inspect:
                inspect(dialog)

        tools.drive_dialog(tools.AnalysisDialog, drive)
        app.choose_analysis()
        wait()
        return latest()

    def refuse(title, values, field, shot=None):
        """A dialog that cannot be accepted: the message and the focus are checked, then the dialog is cancelled."""
        app.show("data", title)
        seen = {}

        def enter(dialog):
            try:
                dialog.update()
                tools.pick_method(dialog, METHOD)
                fields(dialog, (("Method", PIPELINE), *values))
                seen["message"] = rejected(dialog, field, shot)
            except Exception:
                seen["error"] = traceback.format_exc()
            finally:
                dialog.cancel()

        drive_mapped_dialog(root, tools.AnalysisDialog, enter, tools.errors)
        count = len(app.runs)
        app.choose_analysis()
        assert "error" not in seen, seen.get("error")
        assert len(app.runs) == count, "a rejected dialog must not add a run"
        return seen["message"]

    def sheets(position):
        return app.runs[position].result.tables

    def curve(position):
        return sheets(position)[cp.CURVE]

    def setting(position, name):
        table = sheets(position)[cp.SETTINGS]
        return table.loc[table["Setting"] == name, "Value"].iloc[0]

    def expect(position, rows, label=""):
        table = curve(position)
        assert list(table.columns) == cp.COLUMNS, list(table.columns)
        got = rows_of(table)
        assert got.shape == (len(rows), 5), (label, got)
        np.testing.assert_allclose(got, np.array(rows, dtype=float), rtol=1e-12, atol=1e-12, err_msg=label)

    def export(position, sheet, name):
        app.show("result", position)
        app.result_tabs.select(list(sheets(position)).index(sheet))
        target = directory / name
        with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
            app.export()
        return pd.read_csv(target, index_col=0)  # the exporter writes the sheet index as the first column

    def draw(position, suffix):
        app.show("graph", position)
        target = directory / f"curve-pipeline-{position}.{suffix}"
        with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
            app.export()
        return target.read_bytes()

    def edit_analysis(position, action):
        app.show("result", position)
        tools.drive_dialog(tools.AnalysisDialog, action)
        app.edit_analysis()
        wait()

    # --- an older recipe keeps its sheet, its numbers and its controls ---------------------------------------------
    legacy = next(position for position, run in enumerate(app.runs) if run.method == METHOD)
    app.open_sheet(("result", legacy))
    wait()
    assert app.runs[legacy].options == LEGACY_OPTIONS, app.runs[legacy].options
    old = analyse(METHOD, datasets[LEGACY].frame(mask_excluded=True), LEGACY_OPTIONS)
    assert list(sheets(legacy)) == ["Curve"], list(sheets(legacy))
    pd.testing.assert_frame_equal(sheets(legacy)["Curve"], old.tables["Curve"])

    def switch(dialog):
        older = {"X", "Y", "Method", "LOWESS fraction"}
        assert dialog.controls["Method"][1].get() == "LOWESS" and shown(dialog) == older, shown(dialog)
        assert dialog.controls["LOWESS fraction"][1].get() == "0.6"
        fields(dialog, (("Method", PIPELINE),))
        assert shown(dialog) == {"X", "Y", "Method", cp.OPERATION, cp.SMOOTHING}, shown(dialog)
        fields(dialog, ((cp.OPERATION, cp.FIRST), (cp.SMOOTHING, SG)))
        assert shown(dialog) == {"X", "Y", "Method", cp.OPERATION, cp.SMOOTHING, cp.HALF_WINDOW, cp.DEGREE}
        dialog.fields.select(dialog.field_rows[cp.OPERATION][1].master)
        tools.capture(dialog, "window-curve-pipeline-options.png")
        # Going back brings the older controls back as they were; the pipeline keeps what was chosen.
        fields(dialog, (("Method", "Differentiate"),))
        assert shown(dialog) == older and dialog.controls["LOWESS fraction"][1].get() == "0.6"
        fields(dialog, (("Method", PIPELINE),))
        assert (dialog.controls[cp.OPERATION][1].get(), dialog.controls[cp.SMOOTHING][1].get()) == (cp.FIRST, SG)

    edit_analysis(legacy, switch)
    assert app.runs[legacy].options == {**RUN_FIELDS, "Method": PIPELINE, cp.OPERATION: cp.FIRST, cp.SMOOTHING: SG,
                                        cp.HALF_WINDOW: 2, cp.DEGREE: 2}, app.runs[legacy].options
    expect(legacy, FIRST_THEN_SMOOTH_CLEAN, "first difference then Savitzky–Golay on the clean parabola")
    assert list(sheets(legacy)) == [cp.CURVE, cp.SETTINGS]

    # --- degree 5 with half-window 2, then the uneven grid with and without smoothing -------------------------------
    def irregular(dialog):
        fields(dialog, (("X", "X"), ("Y", "Y"), (cp.SMOOTHING, SG), (cp.DEGREE, "5")))
        rejected(dialog, cp.DEGREE, "window-curve-pipeline-degree-error.png")
        fields(dialog, ((cp.DEGREE, "2"),))
        rejected(dialog, cp.SMOOTHING)  # X = 0, 1, 3, 6, 10 is not an even grid
        fields(dialog, ((cp.SMOOTHING, "None"), (cp.OPERATION, cp.SECOND)))

    second = new_run(IRREGULAR, (), inspect=irregular)
    expect(second, SECOND_IRREGULAR, "second difference of x² + 2x + 3 on an uneven, unsorted grid")
    assert cp.HALF_WINDOW not in app.runs[second].options and cp.BASELINE not in app.runs[second].options
    assert setting(second, "Smoothing") == "None"

    # --- Clean and Impulse, alone and in sequence, through the exported CSV -----------------------------------------
    plain = {}
    for column in ("Clean", "Impulse"):
        position = new_run(UNIFORM, (("X", "X"), ("Y", column), (cp.SMOOTHING, SG)))
        plain[column] = export(position, cp.CURVE, f"curve-pipeline-{column.lower()}-smoothed.csv")
        assert plain[column]["X"].tolist() == [2., 3, 4, 5, 6]
    np.testing.assert_allclose(plain["Clean"]["Value"], CLEAN[2:7], rtol=1e-12)  # a parabola passes unchanged
    np.testing.assert_allclose(plain["Impulse"]["Value"], np.convolve(IMPULSE, WINDOW_5[::-1], "valid"), rtol=1e-12)
    np.testing.assert_allclose(plain["Impulse"]["Value"][:2], [15.8, 24.8], rtol=1e-12)
    assert not np.allclose(plain["Impulse"]["Value"], plain["Clean"]["Value"])
    sequence = {}
    for column in ("Clean", "Impulse"):
        position = new_run(UNIFORM, (("X", "X"), ("Y", column), (cp.OPERATION, cp.FIRST), (cp.SMOOTHING, SG)))
        sequence[column] = export(position, cp.CURVE, f"curve-pipeline-{column.lower()}-first-smoothed.csv")
        if column == "Clean":
            clean_sequence = position
    np.testing.assert_allclose(sequence["Clean"][["X", "Value"]].to_numpy(), [[2.5, 7], [3.5, 9], [4.5, 11], [5.5, 13]])
    steps = np.diff(IMPULSE)
    np.testing.assert_allclose(sequence["Impulse"]["Value"], np.convolve(steps, WINDOW_5[::-1], "valid"), rtol=1e-12)
    assert sequence["Impulse"]["Value"].tolist() != sequence["Clean"]["Value"].tolist()
    np.testing.assert_allclose(sequence["Impulse"]["Value"].iloc[[0, -1]], [9., 14.2], rtol=1e-12)  # 315/35 and 497/35
    smoothed_graph = new_run(UNIFORM, (("X", "X"), ("Y", "Impulse"), (cp.SMOOTHING, SG)))
    labels = [text.get_text() for text in app.runs[smoothed_graph].result.figure.axes[0].get_legend().get_texts()]
    assert labels == [f"{cp.IDENTITY} + {SG}", "Original data"], labels
    app.show("result", clean_sequence)
    app.result_tabs.select(0)
    root.update()
    tools.capture(root, "window-curve-pipeline-results.png")

    # --- a shifted and rescaled grid: the values and the units of the rate and of the area ---------------------------
    x, y = SHIFTED_FRAME["Time (s)"].to_numpy(), SHIFTED_FRAME["Signal (mV)"].to_numpy()
    shifted = (("X", "Time (s)"), ("Y", "Signal (mV)"))
    rate = new_run(SHIFTED, (*shifted, (cp.OPERATION, cp.FIRST)))
    np.testing.assert_allclose(curve(rate)["X"], 1000.25 + .5 * np.arange(9), rtol=0, atol=1e-9)
    np.testing.assert_allclose(curve(rate)["Value"], 4000 + 2000 * np.arange(9), rtol=1e-12)
    acceleration = new_run(SHIFTED, (*shifted, (cp.OPERATION, cp.SECOND)))
    np.testing.assert_allclose(curve(acceleration)["X"], 1000.5 + .5 * np.arange(8), rtol=0, atol=1e-9)
    np.testing.assert_allclose(curve(acceleration)["Value"], 4000., rtol=1e-12)
    area = new_run(SHIFTED, (*shifted, (cp.OPERATION, cp.CUMULATIVE), (cp.BASELINE, "500"), (cp.INITIAL, "10")))
    walked = [10.]
    for index in range(1, len(x)):
        walked.append(walked[-1] + (x[index] - x[index - 1]) * ((y[index] + y[index - 1]) / 2 - 500))
    np.testing.assert_allclose(curve(area)["Value"], walked, rtol=1e-12)
    assert curve(area)["First source row"].tolist() == [0] * 10 and curve(area)["Last source row"].tolist() == list(range(10))
    units = {rate: "Signal (mV) per Time (s)", acceleration: "Signal (mV) per Time (s) squared",
             area: "Signal (mV) × Time (s)"}
    for position, unit in units.items():
        assert setting(position, "Output unit") == unit, (position, setting(position, "Output unit"))
        assert "Signal (mV)" in app.runs[position].result.figure.axes[0].get_ylabel()
        assert app.runs[position].result.figure.axes[0].get_xlabel() == "Time (s)"
    assert (setting(area, "Baseline"), setting(area, "Initial integral")) == (500.0, 10.0)

    # --- blocks: a falling stretch, a gap, a short block, a lone point and a smaller X at the bottom ------------------
    blocks = (("X", "X"), ("Y", "Y"))
    first = new_run(BLOCKS, (*blocks, (cp.OPERATION, cp.FIRST)))
    expect(first, FIRST_BLOCKS, "first difference with a falling stretch and a bottom row")
    assert (curve(first)["Value"] < 0).tolist() == [True, False, False, False, False, True, True, True, False]
    assert [setting(first, name) for name in ("Blocks", "Blocks without output", "Output points")] == [3, 1, 9]
    assert (setting(first, "Valid points"), setting(first, "Gap rows (Y missing or excluded)")) == (12, 2)
    # The line is broken between blocks: no segment enters a gap.
    line = app.runs[first].result.figure.axes[0].lines[0]
    xs, ys = np.asarray(line.get_xdata(), dtype=float), np.asarray(line.get_ydata(), dtype=float)
    # Eight points of the first block, one break, then the second block: nothing is drawn from 6.5 to 9.5.
    assert np.flatnonzero(np.isnan(xs)).tolist() == np.flatnonzero(np.isnan(ys)).tolist() == [8], np.isnan(xs)
    assert (xs[7], xs[9]) == (6.5, 9.5)
    app.show("graph", first)
    tools.capture(root, "window-curve-pipeline-graph.png")
    second_blocks = new_run(BLOCKS, (*blocks, (cp.OPERATION, cp.SECOND)))
    expect(second_blocks, SECOND_BLOCKS, "second difference: the two short blocks give nothing")
    assert (setting(second_blocks, "Blocks"), setting(second_blocks, "Blocks without output")) == (3, 2)
    sorted_y = [1., 0, 1, 4, 9, 16, 9, 4, 1]
    sorted_rows = [13, 0, 1, 2, 3, 4, 5, 6, 7]
    moving = new_run(BLOCKS, (*blocks, (cp.SMOOTHING, SG), (cp.HALF_WINDOW, "1"), (cp.DEGREE, "1")))
    expect(moving, [[float(centre), sum(sorted_y[centre:centre + 3]) / 3, 1, sorted_rows[centre], sorted_rows[centre + 2]]
                    for centre in range(7)], "a three-point moving average of the long block")
    assert setting(moving, "Blocks without output") == 2
    # A block shorter than the window gives nothing, and nothing at all is an error on the half-window.
    refusal = refuse(BLOCKS, (*blocks, (cp.SMOOTHING, SG), (cp.HALF_WINDOW, "5"), (cp.DEGREE, "2")), cp.HALF_WINDOW)
    assert "11" in refusal, refusal
    # Text in Y is refused on Y, with the row.
    invalid = refuse(INVALID, (*blocks, (cp.OPERATION, cp.FIRST)), "Y", "window-curve-pipeline-text-error.png")
    assert "3" in invalid, invalid
    # Two rows with the same X are refused on X, even when one of them has no Y.
    duplicated = pd.DataFrame({"X": [0., 1, 1, 2], "Y": [1., 2, np.nan, 4]})
    try:
        analyse(METHOD, duplicated, {**RUN_FIELDS, "Method": PIPELINE})
    except FieldError as error:
        assert error.field == "X", error.field
    else:
        raise AssertionError("duplicate X with an empty Y must be refused")

    # --- mixed columns: positions, not index labels ------------------------------------------------------------------
    mixed_values = (("X", "Elapsed (s)"), ("Y", "Reading"), (cp.OPERATION, cp.FIRST))
    mixed = new_run(MIXED, mixed_values)
    # Sorted by time the worksheet rows are 1, 4, 2, 6, 0, 5 (blank reading), 3, 7 → blocks {1,4,2,6,0} and {3,7}.
    expect(mixed, [[.5, 1, 1, 1, 4], [1.5, 3, 1, 4, 2], [2.5, 5, 1, 2, 6], [3.5, 7, 1, 6, 0], [6.5, 13, 2, 3, 7]],
           "first difference of an unsorted sheet with text, count and blank cells")
    assert setting(mixed, "Source row numbering").startswith("Zero-based")
    odd_index = MIXED_FRAME.set_axis([f"row {name}" for name in "hgfedcba"])
    pd.testing.assert_frame_equal(analyse(METHOD, odd_index, {"X": "Elapsed (s)", "Y": "Reading", "Method": PIPELINE,
                                                              cp.OPERATION: cp.FIRST}).tables[cp.CURVE], curve(mixed))

    # --- exclusions and Undo --------------------------------------------------------------------------------------------
    gaps = new_run(GAPS, (("X", "X"), ("Y", "Y"), (cp.OPERATION, cp.FIRST)))
    expect(gaps, FIRST_GAPS, "first difference of the gaps fixture")
    columns = list(app.tables[GAPS].raw.columns)
    app.show("data", GAPS)
    app.current_grid.select((3, columns.index("Y")))
    app.toggle_exclusion()
    wait()
    expect(gaps, [FIRST_GAPS[0], [5.5, 2, 2, 4, 5]], "an excluded Y splits the curve there")
    assert setting(gaps, "Gap rows (Y missing or excluded)") == 2
    app.show("data", GAPS)
    app.apply_worksheet_history()
    wait()
    expect(gaps, FIRST_GAPS, "Undo brings the excluded Y back")
    app.show("data", GAPS)
    app.current_grid.select((4, columns.index("X")))
    app.toggle_exclusion()
    wait()
    expect(gaps, [[.5, 2, 1, 0, 1], [4.5, 2, 2, 3, 5]], "an excluded X leaves no coordinate behind")
    used = set(curve(gaps)["First source row"]) | set(curve(gaps)["Last source row"])
    assert 4 not in used and setting(gaps, "Rows skipped (X missing or excluded)") == 1, used
    app.show("data", GAPS)
    app.apply_worksheet_history()
    wait()
    expect(gaps, FIRST_GAPS, "Undo brings the excluded X back")
    app.show("data", GAPS)
    app.edit_cell(2, columns.index("Y"), "6")
    wait()
    expect(gaps, [[.5, 2, 1, 0, 1], [1.5, 2, 1, 1, 2], [2.5, 2, 1, 2, 3], [4, 2, 1, 3, 4], [5.5, 2, 1, 4, 5]],
           "filling the empty Y joins the two blocks")
    app.show("data", GAPS)
    app.apply_worksheet_history()
    wait()
    expect(gaps, FIRST_GAPS, "Undo empties it again")

    # --- exports, Use Result as Data --------------------------------------------------------------------------------------
    table = export(first, cp.CURVE, "curve-pipeline-blocks.csv")
    assert list(table.columns) == cp.COLUMNS and len(table) == 9
    np.testing.assert_allclose(table.to_numpy(float), rows_of(curve(first)), rtol=1e-12)
    assert list(export(first, cp.SETTINGS, "curve-pipeline-blocks-settings.csv").columns) == ["Setting", "Value"]
    for suffix, magic in (("svg", b"<svg"), ("png", b"\x89PNG"), ("pdf", b"%PDF")):
        payload = draw(first, suffix)
        assert payload.startswith(magic) or magic in payload[:400], suffix
        assert len(payload) > 1000, suffix
    before = set(app.tables)
    app.show("result", first)
    app.result_tabs.select(0)
    app.use_result_as_data()
    added = set(app.tables) - before
    assert len(added) == 1, added
    copied = app.tables[added.pop()].raw
    assert list(copied.columns) == cp.COLUMNS
    np.testing.assert_allclose(copied.to_numpy(float), rows_of(curve(first)), rtol=1e-12)

    # --- fifty thousand points: rows, time, memory and a responsive window ------------------------------------------------
    grid = np.arange(LARGE_ROWS) * .01
    signal = 3 * grid ** 2 - 2 * grid + 1 + np.sin(grid * 40)
    signal[np.arange(1000, LARGE_ROWS, 1000)] = np.nan
    large_frame = pd.DataFrame({"X": grid, "Y": signal})
    app._add_tables({LARGE: large_frame})
    options = {**RUN_FIELDS, "Method": PIPELINE, cp.OPERATION: cp.SECOND, cp.SMOOTHING: SG, cp.HALF_WINDOW: 10,
               cp.DEGREE: 3}
    tracemalloc.start()
    started = time.perf_counter()
    direct = analyse(METHOD, large_frame, options)
    direct_seconds = time.perf_counter() - started
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    assert len(direct.tables[cp.CURVE]) > 40_000
    assert peak < 120 * 2 ** 20, peak
    started = time.perf_counter()
    big = new_run(LARGE, (("X", "X"), ("Y", "Y"), (cp.OPERATION, cp.SECOND), (cp.SMOOTHING, SG),
                          (cp.HALF_WINDOW, "10"), (cp.DEGREE, "3")))
    through_dialog = time.perf_counter() - started
    pd.testing.assert_frame_equal(curve(big), direct.tables[cp.CURVE])
    assert (setting(big, "Valid points"), setting(big, "Blocks")) == (LARGE_ROWS - 49, 50)
    assert through_dialog < 15, through_dialog
    # An edit starts a recalculation in the worker. A second edit made while it runs is refused, not mixed into it.
    column = list(app.tables[LARGE].raw.columns).index("Y")
    app.show("data", LARGE)
    app.edit_cell(10, column, "100")
    assert app.pending is not None
    app.edit_cell(20, column, "-100")
    assert tools.errors == ["Wait for the current analysis to finish."], tools.errors
    del tools.errors[:]
    longest, ticks, started = 0., 0, time.perf_counter()
    previous = started
    while app.pending is not None:
        root.update()
        now = time.perf_counter()
        longest, previous, ticks = max(longest, now - previous), now, ticks + 1
        time.sleep(.01)
        assert now - started < 30, "the recalculation did not finish"
    recalculated = time.perf_counter() - started
    assert not tools.errors, tools.errors
    assert app.tables[LARGE].raw.iloc[20, column] == large_frame["Y"].iloc[20]  # the refused edit changed nothing
    expected = analyse(METHOD, app.tables[LARGE].frame(mask_excluded=True), options)
    pd.testing.assert_frame_equal(curve(big), expected.tables[cp.CURVE])
    assert longest < 2.0, longest
    app.show("data", LARGE)
    app.edit_cell(20, column, "-100")
    wait()
    expected = analyse(METHOD, app.tables[LARGE].frame(mask_excluded=True), options)
    pd.testing.assert_frame_equal(curve(big), expected.tables[cp.CURVE])
    assert curve(big)["Value"].abs().max() > 1000  # both edits are in the numbers now
    # The row limit is a sentence on X, before any conversion.
    try:
        analyse(METHOD, pd.DataFrame({"X": np.zeros(cp.MAX_ROWS + 1), "Y": np.zeros(cp.MAX_ROWS + 1)}),
                {**RUN_FIELDS, "Method": PIPELINE})
    except FieldError as error:
        assert error.field == "X" and "200,000" in str(error), str(error)
    else:
        raise AssertionError("the row limit must be enforced")
    report["large"] = {"rows": LARGE_ROWS, "output_points": int(len(curve(big))), "engine_seconds": round(direct_seconds, 3),
                       "dialog_seconds": round(through_dialog, 3), "recalculation_seconds": round(recalculated, 3),
                       "longest_gap_between_screen_updates_seconds": round(longest, 3), "screen_updates": ticks,
                       "peak_python_and_numpy_MiB": round(peak / 2 ** 20, 1),
                       "process_peak_rss_MiB": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)}

    # --- save, reopen and calculate again ---------------------------------------------------------------------------------------
    def recipes():
        found = {}
        for position, run in enumerate(app.runs):
            if run.method == METHOD and run.title != LARGE:
                found.setdefault(run.title, []).append(position)
        return found

    app.show("result", first)
    for position in [p for items in recipes().values() for p in items]:
        app.open_sheet(("result", position))
        wait()
    saved = {title: [(dict(app.runs[position].options),
                      {name: frame.copy() for name, frame in app.runs[position].result.tables.items()})
                     for position in positions]
             for title, positions in recipes().items()}
    assert sum(len(items) for items in saved.values()) >= 12
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
            for name, frame in tables.items():
                pd.testing.assert_frame_equal(app.runs[position].result.tables[name], frame)
    again = reopened[BLOCKS][0]
    app.show("result", again)
    app.result_tabs.select(0)
    root.update()
    tools.capture(root, "window-curve-pipeline-reopened.png")
    # The graph of a reopened recipe still has its broken line.
    app.show("graph", again)
    line = app.runs[again].result.figure.axes[0].lines[0]
    assert np.isnan(np.asarray(line.get_xdata(), dtype=float)).sum() == 1
    (out / "curve-pipeline-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (directory / "curve-pipeline-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
