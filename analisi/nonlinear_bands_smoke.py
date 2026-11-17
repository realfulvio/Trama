"""Desktop smoke check for the Nonlinear regression bands (0.61).

``tramastat.py --smoke`` calls :func:`check_nonlinear_bands` with its own helpers.
Alone: ``TRAMASTAT_SMOKE_ONLY=nonlinear-bands python tramastat.py --smoke DIR``.

Synthetic data only. The expected band comes from the closed-form OLS line computed here with numpy,
independent of the optimizer the application uses. Screenshots and exports go to ``DIR/nonlinear-bands``.
"""
from unittest.mock import patch
from xml.etree import ElementTree as ET

import numpy as np
from matplotlib.colors import to_rgb
import pandas as pd
from scipy import stats

from . import i18n
from . import nonlinear_bands as nb
from .data import Dataset, save_project
from .figure_export_dialog import SESSION, FigureExportDialog
from .presentation import apply_style
from .workbench import analyse

METHOD = "Nonlinear regression"
SHEET, OLD = "Band data", "Legacy fit"
LEVEL, BAND, DRAWING = nb.LEVEL, nb.BAND, nb.DRAWING
X = [float(v) for v in range(-2, 6)]
Y = [1.2, 2.7, 4.4, 5.3, 6.6, 7.9, 10.3, 11.4]
DECAY_X = [float(v) for v in np.arange(0, 6.5, .5)]
NOISE = [.3, -.25, .2, -.3, .15, .25, -.2, .1, -.05, .2, -.15, .1, -.2]
FRAME = pd.DataFrame({
    "X": X, "Y": Y, "SD": [.5 + .1 * i for i in range(8)],
})
DECAY = pd.DataFrame({
    "T": DECAY_X * 3,
    "Signal": [*(2 + 8 * np.exp(-.7 * np.array(DECAY_X)) + NOISE),
               *(1 + 6 * np.exp(-.4 * np.array(DECAY_X)) - np.array(NOISE)),
               *(3 + 5 * np.exp(-.9 * np.array(DECAY_X)))],        # exact: no residual variance
    "Group": ["A"] * 13 + ["B"] * 13 + ["C"] * 13,
})
BASE = {"X": "X", "Y columns": ["Y"], "Grouping variables": [], "Model": "Straight line", "Weighting": "Unweighted"}


def ols_band(x, y, level, kind, grid):
    """Closed-form straight-line band at ``grid``: (predicted, lower, upper)."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    design = np.column_stack([np.ones(len(x)), x])
    beta = np.linalg.lstsq(design, y, rcond=None)[0]
    residual = y - design @ beta
    s2 = float(residual @ residual) / (len(x) - 2)
    cov = np.linalg.inv(design.T @ design) * s2
    g = np.column_stack([np.ones(len(grid)), grid])
    variance = np.einsum("ij,jk,ik->i", g, cov, g)
    half = stats.t.ppf((1 + level / 100) / 2, len(x) - 2) * np.sqrt(variance + (s2 if kind == nb.BAND_PREDICTION else 0))
    return g @ beta, g @ beta - half, g @ beta + half


def check_nonlinear_bands(root, app, directory, tools):
    """Runs the check and leaves the remembered Export with options… settings as it found them."""
    remembered = dict(SESSION)
    try:
        _check_nonlinear_bands(root, app, directory, tools)
    finally:
        SESSION.clear()
        SESSION.update(remembered)


def _check_nonlinear_bands(root, app, directory, tools):
    """``tools`` carries the smoke helpers: AnalysisDialog, capture, drive_dialog, pick_method, select_columns,
    wait_for_calculation, messagebox, filedialog and the shared ``errors`` list."""
    wait, errors = tools.wait_for_calculation, tools.errors
    out = directory / "nonlinear-bands"
    out.mkdir(exist_ok=True)
    path = directory / "nonlinear-bands.alab"
    log = []

    old = Dataset(FRAME.copy())
    legacy_options = {"X": "X", "Y": "Y", "Model": "Straight line"}   # saved before Weighting and Band existed
    old.analyses.append((METHOD, dict(legacy_options)))
    save_project(path, {SHEET: Dataset(FRAME.copy()), OLD: old, "Decay data": Dataset(DECAY.copy())})
    app.import_file(path)

    def shot(window, name):
        tools.capture(window, name)
        if (directory / name).exists():
            (directory / name).replace(out / name)

    def placed(dialog, name):
        return bool(dialog.field_rows[name][1].winfo_manager())

    def rejected(dialog, field, shot_name=None):
        with patch.object(tools.messagebox, "showerror") as report:
            assert dialog.validate() is False, field
        assert dialog.winfo_exists()
        assert field in report.call_args.args[1], report.call_args
        assert dialog.fields.select() == str(dialog.field_rows[field][1].master), field
        if shot_name:
            shot(dialog, shot_name)

    def drive(action, *, accept):
        """Like tools.drive_dialog, but the dialog can also be cancelled."""
        def find(parent):
            for child in parent.winfo_children():
                if isinstance(child, tools.AnalysisDialog):
                    return child
                found = find(child)
                if found is not None:
                    return found

        def enter():
            dialog = find(root)
            if dialog is None:
                errors.append("AnalysisDialog did not open")
                return
            try:
                action(dialog)
                dialog.ok() if accept else dialog.cancel()
            except Exception as error:
                errors.append(str(error))
                dialog.cancel()

        root.after(200, enter)

    def band(index, label="All"):
        return app.runs[index].result.tables[f"Band: {label}"]

    def status(index):
        return app.runs[index].result.tables["Band status"]

    def edit(index, action, *, accept=True):
        app.show("result", index)
        drive(action, accept=accept)
        app.edit_analysis()
        wait() if accept else root.update()

    def same_band(index, x, y, level, kind):
        table = band(index)
        predicted, lower, upper = ols_band(x, y, level, kind, table["X"].to_numpy())
        assert len(table) == 300, len(table)
        for name, expected in (("Predicted", predicted), ("Lower", lower), ("Upper", upper)):
            assert np.allclose(table[name], expected, rtol=2e-6, atol=1e-8), (name, table[name].to_numpy()[:3], expected[:3])

    # 1. A recipe saved by 0.61.0 and earlier opens unchanged, with no Band sheet and no band artists.
    position = next(i for i, run in enumerate(app.runs) if run.title == OLD)
    app.open_sheet(("result", position))
    wait()
    assert app.runs[position].options == legacy_options, app.runs[position].options
    expected = analyse(METHOD, FRAME, legacy_options)
    assert list(app.runs[position].result.tables) == list(expected.tables)
    for name, table in expected.tables.items():
        pd.testing.assert_frame_equal(app.runs[position].result.tables[name], table)
    assert "Band status" not in app.runs[position].result.tables
    assert not app.runs[position].result.figure.axes[0].collections[1:], "no band artist without Band"

    def legacy_dialog(dialog):
        assert dialog.controls[BAND][1].get() == nb.BAND_NONE
        assert not placed(dialog, LEVEL) and not placed(dialog, DRAWING)

    app.show("result", position)
    drive(legacy_dialog, accept=False)
    app.edit_analysis()
    root.update()
    assert app.runs[position].options == legacy_options

    # 2. New analysis, mean band, Filled. A level of 100 keeps the dialog open on its field; 80 runs.
    app.show("data", SHEET)

    def new_fit(dialog):
        tools.pick_method(dialog, METHOD)
        dialog.controls["X"][1].set("X")
        tools.select_columns(dialog, "Y columns", {"Y"})
        dialog.controls["Model"][1].set("Straight line")
        assert dialog.controls[BAND][1].get() == nb.BAND_NONE
        assert tuple(dialog.field_rows[BAND][1].cget("values")) == nb.BANDS
        assert not placed(dialog, LEVEL) and not placed(dialog, DRAWING)
        dialog.controls[BAND][1].set(nb.BAND_MEAN)
        dialog.update()
        assert placed(dialog, LEVEL) and placed(dialog, DRAWING)
        dialog.controls[DRAWING][1].set(nb.FILLED)
        dialog.controls[LEVEL][1].set("95")
        dialog.fields.select(dialog.field_rows[LEVEL][1].master)
        dialog.update()
        # 1024×768: every band control is mapped inside the screen.
        for name in (BAND, LEVEL, DRAWING):
            widget = dialog.field_rows[name][1]
            assert widget.winfo_viewable(), name
            assert widget.winfo_rooty() + widget.winfo_height() <= max(768, root.winfo_screenheight()), name
        assert dialog.winfo_width() <= max(1024, root.winfo_screenwidth())
        shot(dialog, "window-bands-options.png")
        dialog.controls[LEVEL][1].set("100")
        rejected(dialog, LEVEL, "window-bands-level-error.png")
        dialog.controls[LEVEL][1].set("0")
        rejected(dialog, LEVEL)
        dialog.controls[LEVEL][1].set("80")

    tools.drive_dialog(tools.AnalysisDialog, new_fit)
    app.choose_analysis()
    wait()
    index = len(app.runs) - 1
    run = app.runs[index]
    assert run.options[BAND] == nb.BAND_MEAN and run.options[LEVEL] == 80.0 and run.options[DRAWING] == nb.FILLED
    same_band(index, X, Y, 80., nb.BAND_MEAN)
    assert status(index).iloc[0]["Status"] == "OK" and status(index).iloc[0][LEVEL] == 80
    fit = app.runs[index].result.tables["Parameters: All"]["Estimate"].to_numpy(float)
    assert np.allclose(fit, np.polyfit(X, Y, 1)[::-1], rtol=2e-6)
    axes = app.runs[index].result.figure.axes[0]
    assert sum(str(c.get_gid()).startswith(nb.GID) for c in axes.collections) == 1
    app.show("result", index)
    app.result_tabs.select(3)
    shot(root, "window-bands-sheet.png")
    app.show("graph", index)
    shot(root, "window-bands-mean-filled.png")

    # 3. Prediction with Lines: wider band, the center curve and the observations stay, one legend at most.
    before = band(index).copy()

    def prediction(dialog):
        assert dialog.controls[BAND][1].get() == nb.BAND_MEAN and dialog.controls[LEVEL][1].get() == "80.0"
        dialog.controls[BAND][1].set(nb.BAND_PREDICTION)
        dialog.controls[DRAWING][1].set(nb.LINES)

    edit(index, prediction)
    same_band(index, X, Y, 80., nb.BAND_PREDICTION)
    assert ((band(index).Upper - band(index).Lower) > (before.Upper - before.Lower)).all()
    figure = app.runs[index].result.figure
    axes = figure.axes[0]
    assert len(axes.lines) >= 3 and len(axes.collections) == 1
    assert axes.get_legend() is None
    app.show("graph", index)
    shot(root, "window-bands-prediction-lines.png")

    # 4. A cell edit, then its exclusion, rebuild fit and band from the current data only.
    columns = list(app.tables[SHEET].raw.columns)
    app.show("data", SHEET)
    app.edit_cell(7, columns.index("Y"), "14.9")
    wait()
    changed = [*Y[:7], 14.9]
    same_band(index, X, changed, 80., nb.BAND_PREDICTION)
    app.show("data", SHEET)
    app.current_grid.select((7, columns.index("Y")))
    app.toggle_exclusion()
    wait()
    same_band(index, X[:7], Y[:7], 80., nb.BAND_PREDICTION)
    assert app.runs[index].result.tables["Fit: All"].loc["N", "Value"] == 7
    app.show("result", index)
    app.result_tabs.select(3)
    shot(root, "window-bands-recalculated.png")
    app.show("data", SHEET)
    app.current_grid.select((7, columns.index("Y")))
    app.toggle_exclusion()      # include the cell again
    wait()
    app.edit_cell(7, columns.index("Y"), str(Y[7]))
    wait()
    same_band(index, X, Y, 80., nb.BAND_PREDICTION)

    # 5. SD column with a band is refused on Band; Unweighted applies; Cancel keeps the stored settings.
    def sd_refused(dialog):
        dialog.controls["Weighting"][1].set("Inverse variance (column)")
        dialog.controls["SD column"][1].set("SD")
        dialog.update()
        rejected(dialog, BAND, "window-bands-weighting-error.png")
        dialog.controls["Weighting"][1].set("Unweighted")
        dialog.controls[BAND][1].set(nb.BAND_NONE)       # changed, then cancelled below

    app.show("result", index)
    drive(sd_refused, accept=False)
    app.edit_analysis()
    root.update()
    assert app.runs[index].options[BAND] == nb.BAND_PREDICTION and app.runs[index].options["Weighting"] == "Unweighted"

    def weighted_prediction(dialog):
        dialog.controls["Weighting"][1].set("1/abs(Y)")
        dialog.update()
        rejected(dialog, BAND)
        dialog.controls[BAND][1].set(nb.BAND_MEAN)

    edit(index, weighted_prediction)
    assert app.runs[index].options["Weighting"] == "1/abs(Y)" and app.runs[index].options[BAND] == nb.BAND_MEAN
    assert "observed-Y" in status(index).iloc[0]["Inference"]
    edit(index, lambda dialog: (dialog.controls["Weighting"][1].set("Unweighted"),
                                dialog.controls[BAND][1].set(nb.BAND_PREDICTION)))
    same_band(index, X, Y, 80., nb.BAND_PREDICTION)

    # 6. One-phase decay with three groups: one band and one fit color per group; the exact group keeps its
    #    estimates and explains the missing band.
    app.show("data", "Decay data")

    def groups(dialog):
        tools.pick_method(dialog, METHOD)
        dialog.controls["X"][1].set("T")
        tools.select_columns(dialog, "Y columns", {"Signal"})
        tools.select_columns(dialog, "Grouping variables", {"Group"})
        dialog.controls["Model"][1].set("One-phase decay")
        dialog.controls[BAND][1].set(nb.BAND_MEAN)
        dialog.controls[DRAWING][1].set(nb.FILLED)

    tools.drive_dialog(tools.AnalysisDialog, groups)
    app.choose_analysis()
    wait()
    second = len(app.runs) - 1
    tables = app.runs[second].result.tables
    state = tables["Band status"]["Status"]
    assert list(state.index) == ["A", "B", "C"], list(state.index)
    assert state.tolist() == ["OK", "OK", "Not available"], state.to_dict()
    assert "perfect" in tables["Band status"].loc["C", "Reason"] and tables["Band status"].loc["A", "Reason"] == ""
    assert len(tables["Parameters: C"]) == 3
    axes = app.runs[second].result.figure.axes[0]
    bands = [c for c in axes.collections if str(c.get_gid()).startswith(nb.GID)]
    curves = [line for line in axes.lines if not str(line.get_gid()).startswith(nb.GID)]
    assert len(bands) == 2 and len(curves) == 3, (len(bands), len(curves))
    for item, curve in zip(bands, curves):
        assert np.allclose(item.get_facecolor()[0][:3], to_rgb(curve.get_color()))
    assert len(axes.get_legend().get_texts()) == 3
    app.show("graph", second)
    shot(root, "window-bands-groups.png")

    # 7. Format and layout: a style with a title and reference line survives, the band stays vector.
    style = {"title": "Decay with bands", "reference_lines": [{"axis": "y", "value": 4.0, "label": "limit"}]}
    figure = app.runs[second].result.figure
    apply_style(figure, style)
    app.runs[second].style = style
    app.tables["Decay data"].graph_styles[app.runs[second].slot] = style
    app.dirty = True
    count = (len(figure.axes[0].collections), len(figure.axes[0].lines))
    apply_style(figure, style)
    assert count == (len(figure.axes[0].collections), len(figure.axes[0].lines)), "no accumulation"
    assert figure.axes[0].get_title() == "Decay with bands"
    assert sum(str(c.get_gid()).startswith(nb.GID) for c in figure.axes[0].collections) == 2

    def compose(dialog):
        dialog.name.set("Band layout")
        dialog.columns.set("2")
        dialog.list.selection_clear(0, "end")
        for number, item in enumerate(dialog.runs):
            if app.runs.index(item) in {index, second}:
                dialog.list.selection_set(number)
        dialog.add_selected()

    tools.drive_dialog(tools.LayoutDialog, compose)
    app.new_layout()
    root.update()
    layout = next(i for i, item in enumerate(app.layouts) if item.name == "Band layout")
    app.show("layout", layout)
    root.update()
    shot(root, "window-bands-layout.png")

    def vector(dialog):
        dialog.format.set("SVG")
        dialog.width.set("160")
        dialog.svg_text.set("Text")

    svg_path = out / "bands-layout.svg"
    tools.drive_dialog(FigureExportDialog, vector)
    with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(svg_path)), \
            patch.object(app, "error") as failure:
        app.export_with_options()
    assert not failure.called and svg_path.exists()
    document = ET.parse(svg_path).getroot()
    assert not list(document.iter("{http://www.w3.org/2000/svg}image")), "bands must not be rasterized"
    assert "fill-opacity" in svg_path.read_text(encoding="utf-8")
    from .pdf_bundle_smoke import read_pdf

    pdf_path = out / "bands-layout.pdf"
    with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(pdf_path)):
        app.export()
    [(size, text, images)] = read_pdf(pdf_path)
    assert images == 0, images
    for suffix in ("png", "svg"):
        target = out / f"bands-graph.{suffix}"
        app.show("graph", second)
        with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
            app.export()
        assert target.stat().st_size > 1000, target

    # 8. Save, close, reopen: graph first, then the source sheet. Settings, coordinates and style survive.
    saved = band(index).copy()
    app.path = directory / "nonlinear-bands-saved.alab"
    assert app.save()
    app.import_file(app.path)
    graph = next(i for i, item in enumerate(app.runs) if item.title == SHEET and item.method == METHOD)
    app.open_sheet(("graph", graph))
    wait()
    assert app.runs[graph].options[BAND] == nb.BAND_PREDICTION and app.runs[graph].options[LEVEL] == 80.0
    pd.testing.assert_frame_equal(band(graph), saved)
    decay = next(i for i, item in enumerate(app.runs) if item.title == "Decay data" and item.method == METHOD)
    app.open_sheet(("graph", decay))
    wait()
    figure = app.runs[decay].result.figure
    assert figure.axes[0].get_title() == "Decay with bands"
    assert sum(str(c.get_gid()).startswith(nb.GID) for c in figure.axes[0].collections) == 2
    app.show("data", SHEET)

    # 9. Band as data: the sheet becomes a worksheet that keeps X and the limits, and exports as CSV.
    app.show("result", graph)
    app.result_tabs.select(3)
    known = set(app.tables)
    app.use_result_as_data()
    added = set(app.tables) - known
    assert len(added) == 1, added
    data = app.tables[added.pop()].raw
    assert {"X", "Lower", "Upper"} <= set(map(str, data.columns)) or "X" in set(data.iloc[:, 0].astype(str)), data.head()
    csv = out / "band.csv"
    app.show("result", graph)
    app.result_tabs.select(3)
    with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(csv)):
        app.export()
    header = csv.read_text(encoding="utf-8-sig").splitlines()[0]
    assert all(name in header for name in nb.COLUMNS), header

    # 10. Italian and English show the same canonical recipe.
    recipe = dict(app.runs[graph].options)

    def italian(dialog):
        assert dialog.controls[BAND][1].get() == nb.BAND_PREDICTION
        assert dialog.field_rows[BAND][0].cget("text") == "Banda"
        assert dialog.choice_bindings[BAND].display.get() == "Predizione (nuova osservazione)"
        assert dialog.choice_bindings[DRAWING].display.get() == "Linee"
        assert dialog.field_rows[LEVEL][0].cget("text") == "Livello di confidenza (%)"
        shot(dialog, "window-bands-dialog-it.png")

    i18n.set_language("it")
    try:
        app.show("result", graph)
        drive(italian, accept=True)
        app.edit_analysis()
        wait()
    finally:
        i18n.set_language("en")
    assert app.runs[graph].options[BAND] == recipe[BAND] and app.runs[graph].options[DRAWING] == recipe[DRAWING]
    assert dict(app.runs[graph].options) == recipe, (app.runs[graph].options, recipe)
    (out / "log.txt").write_text("\n".join(log) + "\n", encoding="utf-8")
    assert not errors, errors
