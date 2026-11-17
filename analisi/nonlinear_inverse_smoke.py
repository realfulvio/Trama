"""Desktop smoke check for nonlinear inverse intervals.

``tramastat.py --smoke`` calls :func:`check_nonlinear_inverse`.
Alone: ``TRAMASTAT_SMOKE_ONLY=nonlinear-inverse python tramastat.py --smoke DIR``.

The standards are a fixed noisy one-phase decay. Queries are two copies of one in-range
response (k = 1 and k = 4) and one response outside the curve. Screenshots go to ``DIR``.
"""
import sys
import traceback
from unittest.mock import patch

from matplotlib.colors import to_hex
import numpy as np
import pandas as pd
from tkinter import ttk

from . import i18n
from . import nonlinear_calibration as cal
from .data import Dataset, save_project

METHOD = "Interpolate a standard curve"
SHEET = "Decay standards"
X = [0.0, 0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0, 8.0]
Y = [12.000147618402899, 10.223156995280835, 8.670303917712928, 7.381245340289391,
     6.438729146951609, 4.892944532522445, 4.026182412258246, 3.0680053623606685,
     2.3485572575575024]
FRAME = pd.DataFrame({
    "X": X,
    "Y": Y,
    "Unknown": [6.5, 6.5, 40.0, None, None, None, None, None, None],
    "k": [1, 4, 1, None, None, None, None, None, None],
    "Bad k": [1.5, 1, 1, None, None, None, None, None, None],
})
INTERVAL_COLOR = "#9a3412"


def check_nonlinear_inverse(root, app, directory, tools):
    """``tools`` carries AnalysisDialog, LayoutDialog, GraphFormatDialog, capture, drive_dialog,
    pick_method, wait_for_calculation, messagebox, filedialog and errors."""
    previous_geometry = root.geometry()
    language = i18n.active_language()
    root.geometry("1024x768+0+0")
    root.update_idletasks()
    try:
        _check(root, app, directory, tools)
    except Exception:
        (directory / "nonlinear-inverse-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        raise
    finally:
        i18n.set_language(language)
        root.geometry(previous_geometry)


def _button(dialog, text):
    pending = [dialog]
    while pending:
        widget = pending.pop()
        if isinstance(widget, ttk.Button) and widget.cget("text") == i18n.ui(text):
            return widget
        pending.extend(widget.winfo_children())
    raise AssertionError(text)


def _reachable(dialog, text):
    button = _button(dialog, text)
    dialog.update_idletasks()
    assert button.winfo_ismapped() and button.winfo_viewable(), text
    right = button.winfo_rootx() + button.winfo_width()
    bottom = button.winfo_rooty() + button.winfo_height()
    assert button.winfo_rootx() >= -1 and button.winfo_rooty() >= -1, text
    assert right <= dialog.winfo_screenwidth() + 1, text
    assert bottom <= dialog.winfo_screenheight() + 1, text
    return button


def _placed(dialog, name):
    return bool(dialog.field_rows[name][1].winfo_manager())


def _interval_lines(figure):
    return [line for line in figure.axes[0].lines if to_hex(line.get_color()).lower() == INTERVAL_COLOR]


def _bounds(table, row):
    return float(table.at[row, "X lower"]), float(table.at[row, "X upper"])


def _check(root, app, directory, tools):
    wait, errors = tools.wait_for_calculation, tools.errors
    messagebox, filedialog = tools.messagebox, tools.filedialog
    sizes = ["1024x768"]
    dpi = root.winfo_fpixels("1i")
    (directory / "nonlinear-inverse-environment.txt").write_text(
        "\n".join([
            f"python={sys.version.split()[0]}",
            f"tk={root.tk.call('info', 'patchlevel')}",
            f"screen={root.winfo_screenwidth()}x{root.winfo_screenheight()}",
            f"dpi={dpi:.2f}",
            "geometry=1024x768",
        ]) + "\n",
        encoding="utf-8")

    def fields(dialog, values):
        for name, value in values:
            dialog.controls[name][1].set(value)
            dialog.update_idletasks()

    def rejected(dialog, field, shot=None):
        with patch.object(messagebox, "showerror") as report:
            assert dialog.validate() is False, field
        assert dialog.winfo_exists()
        assert field in report.call_args.args[1], report.call_args
        assert dialog.fields.select() == str(dialog.field_rows[field][1].master), field
        if shot:
            tools.capture(dialog, shot)

    def configure(dialog, *, uncertainty, count):
        tools.pick_method(dialog, METHOD)
        fields(dialog, (
            ("X", "X"), ("Y", "Y"), ("Unknown responses", "Unknown"),
            (cal.DIRECTION, "X from Y"), ("Curve", "Nonlinear"),
        ))
        assert dialog.controls["Model"][1].get() == "One-phase decay"
        for model in cal.INVERSE_INTERVAL_MODELS:
            fields(dialog, (("Model", model), (cal.UNCERTAINTY, "Prediction")))
            assert _placed(dialog, cal.UNCERTAINTY) and _placed(dialog, cal.LEVEL) and _placed(dialog, cal.COUNT)
            assert dialog.inverse_note.winfo_manager(), model
        fields(dialog, (("Model", "One-phase association"),))
        assert not _placed(dialog, cal.UNCERTAINTY) and not _placed(dialog, cal.LEVEL)
        assert not _placed(dialog, cal.COUNT) and not dialog.inverse_note.winfo_manager()
        fields(dialog, (
            ("Model", "One-phase decay"), (cal.UNCERTAINTY, "None"),
        ))
        assert _placed(dialog, cal.UNCERTAINTY) and not dialog.inverse_note.winfo_manager()
        assert not _placed(dialog, cal.LEVEL) and not _placed(dialog, cal.COUNT)
        fields(dialog, ((cal.DIRECTION, "Y from X"),))
        assert not dialog.inverse_note.winfo_manager()
        fields(dialog, ((cal.DIRECTION, "X from Y"), (cal.UNCERTAINTY, uncertainty), (cal.LEVEL, "95")))
        if count:
            fields(dialog, ((cal.COUNT, count),))
        assert dialog.inverse_note.cget("text") == cal.INTERVAL_NOTE
        assert dialog.field_rows["Model"][0].cget("text") == "Model"
        dialog.fields.select(dialog.field_rows[cal.LEVEL][1].master)
        dialog.update_idletasks()
        _reachable(dialog, "Run Analysis")
        _reachable(dialog, "Cancel")
        assert dialog.inverse_note.winfo_viewable()
        note_bottom = dialog.inverse_note.winfo_rooty() + dialog.inverse_note.winfo_height()
        assert note_bottom <= dialog.winfo_screenheight() + 1
        dialog.fields.select(dialog.field_rows[cal.COUNT][1].master)
        dialog.update_idletasks()
        if count:
            assert dialog.field_rows[cal.COUNT][1].winfo_viewable()

    path = directory / "nonlinear-inverse.alab"
    save_project(path, {SHEET: Dataset(FRAME.copy())})
    app.import_file(path)
    app.show("data", SHEET)

    def prediction(dialog):
        configure(dialog, uncertainty="Prediction", count="k")
        dialog.controls[cal.LEVEL][1].set("150")
        rejected(dialog, cal.LEVEL, "window-nonlinear-inverse-level-error.png")
        dialog.controls[cal.LEVEL][1].set("95")
        dialog.controls[cal.COUNT][1].set("Bad k")
        rejected(dialog, cal.COUNT, "window-nonlinear-inverse-count-error.png")
        dialog.controls[cal.COUNT][1].set("k")
        tools.capture(dialog, "window-nonlinear-inverse-dialog.png")

    tools.drive_dialog(tools.AnalysisDialog, prediction)
    app.choose_analysis()
    assert not errors, errors
    wait()
    prediction_index = len(app.runs) - 1
    prediction_run = app.runs[prediction_index]
    assert prediction_run.options["Curve"] == "Nonlinear"
    assert prediction_run.options["Model"] == "One-phase decay"
    assert prediction_run.options[cal.DIRECTION] == "X from Y"
    assert prediction_run.options[cal.UNCERTAINTY] == "Prediction"
    assert prediction_run.options[cal.LEVEL] == 95.0
    assert prediction_run.options[cal.COUNT] == "k"
    table = prediction_run.result.tables[cal.INTERPOLATED]
    assert list(table.columns[-5:]) == ["X lower", "X upper", cal.INTERVAL_STATUS, "Reason", cal.REPLICATES]
    assert table[cal.INTERVAL_STATUS].tolist() == [cal.COMPLETE, cal.COMPLETE, ""]
    assert table["Reason"].tolist() == ["", "", cal.OUTSIDE_REASON]
    assert table[cal.REPLICATES].tolist() == [1, 4, 1]
    assert table["Status"].tolist() == [cal.IN_RANGE, cal.IN_RANGE, cal.OUT_OF_RANGE]
    assert np.isnan(table.at[2, "X lower"]) and np.isnan(table.at[2, "X upper"])
    left, right = _bounds(table, 0)
    narrow_left, narrow_right = _bounds(table, 1)
    point = float(table.at[0, "Interpolated X"])
    assert left <= point <= right
    assert left <= narrow_left <= narrow_right <= right
    assert (right - left) > (narrow_right - narrow_left) > 0
    note = prediction_run.result.tables["Fit diagnostics"].at["Interval note", "Value"]
    assert note == cal.INTERVAL_NOTE
    assert cal.COMPONENTS not in prediction_run.result.tables
    axis = prediction_run.result.figure.axes[0]
    labels = [text.get_text() for text in axis.get_legend().get_texts()]
    assert labels.count("95% prediction interval") == 1, labels
    artists = _interval_lines(prediction_run.result.figure)
    assert len(artists) == 2, len(artists)
    assert all(len(line.get_xdata()) == 2 for line in artists)
    assert {round(float(line.get_ydata()[0]), 6) for line in artists} == {6.5}
    assert all(float(line.get_ydata()[0]) == float(line.get_ydata()[1]) for line in artists)
    app.show("graph", prediction_index)
    tools.capture(root, "window-nonlinear-inverse-graph.png")
    app.show("result", prediction_index)
    app.result_tabs.select(0)
    tools.capture(root, "window-nonlinear-inverse-result.png")

    def mean(dialog):
        configure(dialog, uncertainty="Mean response", count=None)
        assert not _placed(dialog, cal.COUNT)
        assert dialog.inverse_note.winfo_manager()

    tools.drive_dialog(tools.AnalysisDialog, mean)
    app.show("data", SHEET)
    app.choose_analysis()
    assert not errors, errors
    wait()
    mean_index = len(app.runs) - 1
    mean_table = app.runs[mean_index].result.tables[cal.INTERPOLATED]
    assert cal.REPLICATES not in mean_table.columns
    assert app.runs[mean_index].options[cal.UNCERTAINTY] == "Mean response"
    assert cal.COUNT not in app.runs[mean_index].options
    mean_left, mean_right = _bounds(mean_table, 0)
    scale = max(1.0, abs(left), abs(right))
    tolerance = 1e-6 * scale
    assert narrow_left - tolerance <= mean_left <= mean_right <= narrow_right + tolerance
    assert (narrow_right - narrow_left) > (mean_right - mean_left) > 0
    mean_labels = [text.get_text() for text in app.runs[mean_index].result.figure.axes[0].get_legend().get_texts()]
    assert mean_labels.count("95% mean response interval") == 1, mean_labels

    columns = list(app.tables[SHEET].raw.columns)
    original_lower = float(app.runs[prediction_index].result.tables[cal.INTERPOLATED].at[0, "X lower"])
    app.show("data", SHEET)
    app.edit_cell(0, columns.index("Y"), f"{Y[0] + 0.8:.6f}")
    wait()
    moved = float(app.runs[prediction_index].result.tables[cal.INTERPOLATED].at[0, "X lower"])
    assert abs(moved - original_lower) > 1e-4
    app.show("data", SHEET)
    assert app.worksheet_history.can_apply()
    app.apply_worksheet_history()
    wait()
    restored = float(app.runs[prediction_index].result.tables[cal.INTERPOLATED].at[0, "X lower"])
    assert abs(restored - original_lower) < 1e-8
    assert float(app.tables[SHEET].raw.iat[0, columns.index("Y")]) == Y[0]

    app.show("data", SHEET)
    app.current_grid.active_cell = (2, columns.index("Unknown"))
    app.toggle_exclusion()
    wait()
    excluded = app.runs[prediction_index].result.tables[cal.INTERPOLATED]
    assert excluded["Source row"].tolist() == [0, 1]
    app.show("data", SHEET)
    app.apply_worksheet_history()
    wait()
    assert app.runs[prediction_index].result.tables[cal.INTERPOLATED]["Source row"].tolist() == [0, 1, 2]

    before = app.runs[prediction_index].result.tables[cal.INTERPOLATED].copy()
    app.recalculate(prediction_index)
    wait()
    pd.testing.assert_frame_equal(app.runs[prediction_index].result.tables[cal.INTERPOLATED], before)

    raw = app.tables[SHEET].raw
    k_column = columns.index("k")
    raw.iat[0, k_column] = 1.5

    def recover(dialog):
        assert dialog.winfo_exists()
        assert cal.COUNT in dialog.error and "k" in dialog.error, dialog.error
        assert dialog.fields.select() == str(dialog.field_rows[cal.COUNT][1].master)
        assert dialog.controls[cal.UNCERTAINTY][1].get() == "Prediction"
        assert dialog.controls[cal.COUNT][1].get() == "k"
        assert dialog.controls["Model"][1].get() == "One-phase decay"
        _reachable(dialog, "Run Analysis")
        _reachable(dialog, "Cancel")
        tools.capture(dialog, "window-nonlinear-inverse-recovery.png")
        dialog.ok = dialog.cancel

    try:
        tools.drive_dialog(tools.AnalysisDialog, recover)
        app.recalculate(prediction_index)
        wait()
        assert not errors, errors
        pd.testing.assert_frame_equal(app.runs[prediction_index].result.tables[cal.INTERPOLATED], before)
    finally:
        raw.iat[0, k_column] = 1
    app.recalculate(prediction_index)
    wait()
    pd.testing.assert_frame_equal(app.runs[prediction_index].result.tables[cal.INTERPOLATED], before)

    app.show("graph", prediction_index)
    root.update()
    figure = app.runs[prediction_index].result.figure
    interval_line = _interval_lines(figure)[0]
    assert to_hex(interval_line.get_color()).lower() == INTERVAL_COLOR
    app.toggle_inspector()
    root.update()
    inspector = app.inspector
    assert inspector is not None
    window_bottom = root.winfo_rooty() + root.winfo_height()
    for button in (inspector.apply_button, inspector.cancel_button):
        assert button.winfo_ismapped() and button.winfo_viewable()
        assert button.winfo_rooty() + button.winfo_height() <= window_bottom + 1
    interval_key = next(item["key"] for item in inspector.elements
                        if getattr(item["item"], "artist", None) is interval_line)
    assert inspector.select_group(interval_key)
    inspector.vars["element:color"].set("#1d4ed8")
    inspector._now("element:color")
    assert to_hex(interval_line.get_color()).lower() == "#1d4ed8"
    inspector.cancel_button.invoke()
    root.update()
    assert app.inspector is None
    assert to_hex(interval_line.get_color()).lower() == INTERVAL_COLOR

    app.toggle_inspector()
    root.update()
    inspector = app.inspector
    assert inspector.select_group(interval_key)
    inspector.vars["element:color"].set("#1d4ed8")
    inspector._now("element:color")
    assert inspector.apply()
    inspector.cancel_button.invoke()
    root.update()
    assert to_hex(interval_line.get_color()).lower() == "#1d4ed8"
    assert any(to_hex(line.get_color()).lower() == INTERVAL_COLOR for line in figure.axes[0].lines)
    assert app.runs[prediction_index].options[cal.UNCERTAINTY] == "Prediction"

    def retitle(dialog):
        dialog.inputs["title"].set("Inverse intervals")
        tools.capture(dialog, "window-nonlinear-inverse-format.png")

    app.show("graph", prediction_index)
    tools.drive_dialog(tools.GraphFormatDialog, retitle)
    app.format_graph()
    assert not errors, errors
    assert app.runs[prediction_index].result.figure.axes[0].get_title() == "Inverse intervals"
    assert app.runs[prediction_index].options["Model"] == "One-phase decay"

    recipe = {index: dict(app.runs[index].options) for index in (prediction_index, mean_index)}
    tables = {index: {name: frame.copy() for name, frame in app.runs[index].result.tables.items()}
              for index in (prediction_index, mean_index)}
    i18n.set_language("it")

    def italian(dialog):
        assert dialog.field_rows[cal.UNCERTAINTY][0].cget("text") == "Incertezza"
        assert dialog.field_rows[cal.LEVEL][0].cget("text") == "Livello di confidenza (%)"
        assert dialog.field_rows[cal.COUNT][0].cget("text") == "Colonna del numero di repliche"
        assert dialog.field_rows["Model"][0].cget("text") == "Modello"
        assert dialog.inverse_note.cget("text").startswith("Approssimazione")
        assert dialog.controls[cal.UNCERTAINTY][1].get() == "Prediction"
        assert dialog.controls["Model"][1].get() == "One-phase decay"
        assert dialog.controls["Curve"][1].get() == "Nonlinear"
        tools.capture(dialog, "window-nonlinear-inverse-dialog-it.png")

    app.show("result", prediction_index)
    tools.drive_dialog(tools.AnalysisDialog, italian)
    app.edit_analysis()
    assert not errors, errors
    wait()
    i18n.set_language("en")
    assert app.runs[prediction_index].options == recipe[prediction_index]

    app.path = path
    assert app.save()
    saved = path.read_text(encoding="utf-8")
    assert "Prediction" in saved and "One-phase decay" in saved
    assert "Incertezza" not in saved and "Approssimazione" not in saved
    app.import_file(path)
    assert app.runs[prediction_index].result is None
    app.open_sheet(("graph", prediction_index))
    wait()
    reopened = app.runs[prediction_index]
    assert reopened.options == recipe[prediction_index]
    assert reopened.result.figure.axes[0].get_title() == "Inverse intervals"
    reopened_colors = {to_hex(line.get_color()).lower() for line in reopened.result.figure.axes[0].lines}
    assert "#1d4ed8" in reopened_colors and INTERVAL_COLOR in reopened_colors
    for index in (prediction_index, mean_index):
        app.open_sheet(("result", index))
        wait()
        assert app.runs[index].options == recipe[index]
        assert list(app.runs[index].result.tables) == list(tables[index])
        for name, frame in tables[index].items():
            pd.testing.assert_frame_equal(app.runs[index].result.tables[name], frame)

    app.show("result", prediction_index)
    app.result_tabs.select(0)
    csv_path = directory / "nonlinear-inverse.csv"
    with patch.object(filedialog, "asksaveasfilename", return_value=str(csv_path)):
        app.export()
    exported = csv_path.read_text(encoding="utf-8-sig")
    assert "X lower" in exported and "Interval status" in exported and "Replicate count" in exported
    assert cal.OUTSIDE_REASON in exported
    before_tables = set(app.tables)
    app.use_result_as_data()
    added = set(app.tables) - before_tables
    assert len(added) == 1, added
    copied = app.tables[added.pop()].raw
    assert {"X lower", "X upper", "Interval status", "Reason", "Replicate count"} <= set(copied.columns)

    app.show("graph", prediction_index)
    for suffix in ("png", "svg", "pdf"):
        target = directory / f"nonlinear-inverse.{suffix}"
        with patch.object(filedialog, "asksaveasfilename", return_value=str(target)):
            app.export()
        assert target.stat().st_size > 1000, suffix
    assert b"<svg" in (directory / "nonlinear-inverse.svg").read_bytes()
    assert "9a3412" in (directory / "nonlinear-inverse.svg").read_text(encoding="utf-8").lower()
    assert (directory / "nonlinear-inverse.pdf").read_bytes().startswith(b"%PDF")

    def compose(dialog):
        dialog.name.set("Inverse intervals")
        dialog.columns.set("1")
        dialog.list.selection_clear(0, "end")
        for number, item in enumerate(dialog.runs):
            if item is app.runs[prediction_index]:
                dialog.list.selection_set(number)
        dialog.add_selected()

    tools.drive_dialog(tools.LayoutDialog, compose)
    app.new_layout()
    assert not errors, errors
    root.update()
    layout_index = next(i for i, item in enumerate(app.layouts) if item.name == "Inverse intervals")
    app.show("layout", layout_index)
    root.update()
    tools.capture(root, "window-nonlinear-inverse-layout.png")
    layout_pdf = directory / "nonlinear-inverse-layout.pdf"
    with patch.object(filedialog, "asksaveasfilename", return_value=str(layout_pdf)):
        app.export()
    assert layout_pdf.read_bytes().startswith(b"%PDF")
    layout_png = directory / "nonlinear-inverse-layout.png"
    with patch.object(filedialog, "asksaveasfilename", return_value=str(layout_png)):
        app.export()
    assert layout_png.stat().st_size > 1000

    def clear_uncertainty(dialog):
        dialog.controls[cal.UNCERTAINTY][1].set("None")
        dialog.update_idletasks()
        assert not dialog.inverse_note.winfo_manager()
        assert not _placed(dialog, cal.LEVEL) and not _placed(dialog, cal.COUNT)

    app.show("result", prediction_index)
    tools.drive_dialog(tools.AnalysisDialog, clear_uncertainty)
    app.edit_analysis()
    assert not errors, errors
    wait()
    plain = app.runs[prediction_index]
    assert "X lower" not in plain.result.tables[cal.INTERPOLATED].columns
    plain_labels = [text.get_text() for text in plain.result.figure.axes[0].get_legend().get_texts()]
    assert plain_labels == ["Standards", "One-phase decay", "Estimates"], plain_labels
    assert "Interval note" not in plain.result.tables["Fit diagnostics"].index

    if root.winfo_screenwidth() >= 1600 and root.winfo_screenheight() >= 1000:
        root.geometry("1600x1000+0+0")
        root.update()
        sizes.append("1600x1000")

        def wide(dialog):
            configure(dialog, uncertainty="Prediction", count="k")
            tools.capture(dialog, "window-nonlinear-inverse-dialog-1600.png")
            dialog.ok = dialog.cancel

        app.show("data", SHEET)
        tools.drive_dialog(tools.AnalysisDialog, wide)
        app.choose_analysis()
        assert not errors, errors
        tools.capture(root, "window-nonlinear-inverse-1600.png")
    report = directory / "nonlinear-inverse-environment.txt"
    report.write_text(report.read_text(encoding="utf-8") + f"checked={','.join(sizes)}\n", encoding="utf-8")
    assert not errors, errors
