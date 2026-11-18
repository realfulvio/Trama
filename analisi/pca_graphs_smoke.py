"""Desktop smoke check for PCA scores, loadings, biplot, scree and variance proportion.

``tramastat.py --smoke`` (or ``TRAMASTAT_SMOKE_ONLY=pca-graphs``) calls
:func:`check_pca_graphs`.
"""
from unittest.mock import patch

import numpy as np
import pandas as pd

from .data import Dataset, save_project
from .i18n import active_language, set_language
from . import pca_reports
from .pca_graphs import (
    BIPLOT, COLOR_GROUPS, GRAPH, HORIZONTAL, LABEL, LOADINGS, POINT_VIEWS,
    PROPORTION, SCORES, SCREE, SHOW_LABELS, VERTICAL,
)

VIEWS = (SCORES, LOADINGS, BIPLOT, SCREE, PROPORTION)
ONE_DIMENSION = {SCREE, PROPORTION}


def check_pca_graphs(root, app, directory, kit):
    from tkinter import filedialog, messagebox

    capture, drive, pick, select = kit.capture, kit.drive_dialog, kit.pick_method, kit.select_columns
    wait = kit.wait_for_calculation
    previous_geometry = root.geometry()
    language = active_language()
    root.geometry("1024x768+0+0")
    try:
        _check(root, app, directory, capture, drive, pick, select, wait, messagebox, filedialog)
    finally:
        set_language(language)
        root.geometry(previous_geometry)


def _state(dialog, view):
    dialog.controls[GRAPH][1].set(view)
    dialog.update_idletasks()
    inactive = view in ONE_DIMENSION
    horizontal = dialog.field_rows[HORIZONTAL][1]
    assert horizontal.grid_info(), view
    assert dialog.field_rows[VERTICAL][1].grid_info(), view
    assert dialog.field_rows[LABEL][1].grid_info(), view
    assert ("disabled" if inactive else "normal") in str(horizontal.cget("state")), view
    label_state = "disabled" if inactive else "readonly"
    assert label_state in str(dialog.field_rows[LABEL][1].cget("state")), view
    group_state = "readonly" if view in POINT_VIEWS else "disabled"
    assert group_state in str(dialog.field_rows[COLOR_GROUPS][1].cget("state")), view
    show_state = "disabled" if inactive else "normal"
    assert show_state in str(dialog.field_rows[SHOW_LABELS][1].cget("state")), view


def _expect(run, view, frame):
    tables = run.result.tables
    assert list(tables)[:3] == ["Explained variance", "Eigenvectors", "Scores"], view
    coordinates = tables["PC graph coordinates"]
    assert tables["Settings"].loc["Graph display", "Value"] == view
    if view == SCORES:
        assert list(coordinates.columns) == ["Source row", "Label", "Horizontal", "Vertical"]
        assert coordinates["Source row"].tolist() == [0, 1, 2, 3, 4, 5]
        assert "gruppo $C" in coordinates["Label"].tolist()
        np.testing.assert_allclose(tables["Explained variance"]["Eigenvalue"], [1.6, 0.4])
        assert "PC1" in run.result.figure.axes[0].get_xlabel()
        assert "%" in run.result.figure.axes[0].get_xlabel()
    elif view == LOADINGS:
        assert list(coordinates.columns) == ["Variable", "Horizontal", "Vertical"]
        assert coordinates["Variable"].tolist() == ["A", "B"]
    elif view == BIPLOT:
        assert list(coordinates.columns) == ["Kind", "Identity", "Label", "Horizontal", "Vertical"]
        rows = coordinates.loc[coordinates.Kind == "Row", ["Horizontal", "Vertical"]].to_numpy(dtype=float)
        variables = coordinates.loc[coordinates.Kind == "Variable", ["Horizontal", "Vertical"]].to_numpy(dtype=float)
        values = frame.dropna(subset=["A", "B"])[["A", "B"]].to_numpy(dtype=float)
        np.testing.assert_allclose(rows @ variables.T, values - values.mean(axis=0), atol=1e-8)
        texts = [text.get_text() for text in run.result.figure.axes[0].texts]
        assert any("gruppo" in text and "$" in text for text in texts), texts
        assert "Symmetric biplot" in tables["Settings"].loc["Biplot", "Value"]
    elif view == SCREE:
        assert list(coordinates.columns) == ["PC", "Eigenvalue", "Variance (%)", "Cumulative (%)"]
        assert run.result.figure.axes[0].get_ylabel() == "Eigenvalue"
    else:
        assert list(coordinates.columns) == ["PC", "Eigenvalue", "Variance (%)", "Cumulative (%)"]
        assert run.result.figure.axes[0].get_ylabel() == "Variance (%)"
        assert run.result.figure.axes[0].get_legend() is not None


def _check(root, app, directory, capture, drive, pick, select, wait, messagebox, filedialog):
    path = directory / "pca-graphs.alab"
    title = "Components"
    frame = pd.DataFrame({
        "A": [1.4142135623730951, -1.4142135623730951, 0.7071067811865476, -0.7071067811865476, 0.0, 0.0, np.nan],
        "B": [1.4142135623730951, -1.4142135623730951, -0.7071067811865476, 0.7071067811865476, 0.0, 0.0, 9.0],
        "Label": ["città A", "città B", "gruppo $C", "gruppo <D>", "centro", "centro", "incompleta"],
        "Cohort": ["Control", "Control", "Treated $", "Treated $", None, None, "Unused"],
    })
    save_project(path, {title: Dataset(frame)})
    app.import_file(path)

    def italian(dialog):
        pick(dialog, "Principal component analysis")
        assert dialog.field_rows[GRAPH][0].cget("text") == "Vista del grafico"
        assert dialog.field_rows[SHOW_LABELS][0].cget("text") == "Mostra etichette di riga"
        assert dialog.field_rows[COLOR_GROUPS][0].cget("text") == "Colora gruppi per"
        reports_tab = dialog.field_rows[pca_reports.INPUT][0].master
        assert dialog.fields.tab(reports_tab, "text") == "Risultati"
        assert dialog.field_rows[pca_reports.CASES][0].cget("text") == "Contributi delle osservazioni"
        tab = dialog.field_rows[GRAPH][0].master
        assert dialog.fields.tab(tab, "text") == "Grafico"
        dialog.ok = dialog.cancel

    set_language("it")
    drive(italian)
    app.choose_analysis()
    set_language("en")

    def configure(dialog):
        pick(dialog, "Principal component analysis")
        select(dialog, "Variables", {"A", "B"})
        dialog.controls["Standardize"][1].set(False)
        dialog.controls[LABEL][1].set("Label")
        dialog.controls[SHOW_LABELS][1].set(True)
        dialog.controls[GRAPH][1].set(BIPLOT)
        dialog.controls[HORIZONTAL][1].set("2")
        dialog.controls[VERTICAL][1].set("2")
        with patch.object(messagebox, "showerror") as shown:
            assert dialog.validate() is False
        assert dialog.winfo_exists()
        assert "Vertical PC" in shown.call_args.args[1], shown.call_args
        capture(dialog, "window-pca-equal-components.png")
        dialog.controls[HORIZONTAL][1].set("1")
        dialog.controls[VERTICAL][1].set("2")
        dialog.controls[GRAPH][1].set(SCREE)
        assert "disabled" in str(dialog.field_rows[HORIZONTAL][1].cget("state"))
        assert dialog.field_rows[LABEL][1].grid_info()
        dialog.controls[HORIZONTAL][1].set("nope")
        assert dialog.validate() is True
        assert HORIZONTAL not in dialog.result[1]
        dialog.result = None
        dialog.controls[HORIZONTAL][1].set("1")
        for view in VIEWS:
            _state(dialog, view)
        dialog.controls[GRAPH][1].set(SCORES)
        dialog.fields.select(dialog.field_rows[GRAPH][0].master)
        dialog.update_idletasks()
        assert dialog.winfo_reqwidth() <= 1024, dialog.winfo_reqwidth()
        assert dialog.winfo_reqheight() <= 768, dialog.winfo_reqheight()
        assert dialog.field_rows[GRAPH][0].cget("text") == "Graph display"
        capture(dialog, "window-pca-dialog.png")
        assert dialog.validate() is True
        dialog.result = None

    drive(configure)
    app.choose_analysis()
    wait()
    _expect(app.runs[0], SCORES, frame)

    def switch(view):
        def action(dialog):
            _state(dialog, view)
            if view not in ONE_DIMENSION:
                dialog.controls[HORIZONTAL][1].set("1")
                dialog.controls[VERTICAL][1].set("2")
                dialog.controls[LABEL][1].set("Label")
                dialog.controls[SHOW_LABELS][1].set(True)
            assert dialog.validate() is True
            dialog.result = None

        return action

    for view in (LOADINGS, SCREE, PROPORTION, BIPLOT):
        drive(switch(view))
        app.show("result", 0)
        app.edit_analysis()
        wait()
        _expect(app.runs[0], view, frame)

    ordinary = app.runs[0].result.tables

    def color_groups(dialog):
        _state(dialog, BIPLOT)
        dialog.controls[COLOR_GROUPS][1].set("Cohort")
        for option in pca_reports.OPTIONS:
            dialog.controls[option][1].set(True)
        dialog.fields.select(dialog.field_rows[pca_reports.INPUT][0].master)
        dialog.update_idletasks()
        assert dialog.winfo_reqheight() <= 768
        capture(dialog, "window-pca-reports.png")
        assert dialog.validate() is True
        dialog.result = None

    drive(color_groups)
    app.show("graph", 0)
    app.edit_analysis()
    wait()
    colored = app.runs[0].result
    for name in ("Explained variance", "Eigenvectors", "Scores"):
        pd.testing.assert_frame_equal(ordinary[name], colored.tables[name])
    pd.testing.assert_frame_equal(
        ordinary["PC graph coordinates"], colored.tables["PC graph coordinates"].drop(columns="Color group"),
    )
    legend = colored.figure.axes[0].get_legend()
    assert legend.get_title().get_text() == "Cohort"
    assert len(legend.get_texts()) == 3
    reports = (pca_reports.INPUT_SHEET, pca_reports.VARIABLES, pca_reports.CORRELATIONS,
               pca_reports.CASES, pca_reports.MATRIX_SHEET)
    assert list(colored.tables)[-len(reports):] == list(reports)
    np.testing.assert_allclose(
        colored.tables[pca_reports.CASES].loc[:, ["PC1", "PC2"]].sum(), [1., 1.],
    )

    for view in (SCREE, PROPORTION, BIPLOT):
        drive(switch(view))
        app.show("result", 0)
        app.edit_analysis()
        wait()
        result = app.runs[0].result
        assert result.tables["Settings"].loc["Graph display", "Value"] == view
        for report in reports:
            pd.testing.assert_frame_equal(result.tables[report], colored.tables[report])

    app.show("graph", 0)
    capture(root, "window-pca-biplot.png")
    svg_path, png_path = directory / "pca-biplot.svg", directory / "pca-biplot.png"
    for export_path in (svg_path, png_path):
        app.show("graph", 0)
        with patch.object(filedialog, "asksaveasfilename", return_value=str(export_path)):
            app.export()
    svg = svg_path.read_text(encoding="utf-8")
    assert "<svg" in svg and "gruppo" in svg and ("$" in svg or "&#36;" in svg)
    assert png_path.stat().st_size > 1000
    confirmed = app.runs[0].result.tables["PC graph coordinates"].copy()

    def abort(dialog):
        dialog.controls[GRAPH][1].set(SCORES)
        dialog.controls[VERTICAL][1].set(dialog.controls[HORIZONTAL][1].get())
        with patch.object(messagebox, "showerror") as shown:
            assert dialog.validate() is False
        assert dialog.winfo_exists()
        assert "Vertical PC" in shown.call_args.args[1], shown.call_args
        dialog.result = None
        dialog.ok = dialog.cancel

    drive(abort)
    app.show("graph", 0)
    app.edit_analysis()
    wait()
    pd.testing.assert_frame_equal(app.runs[0].result.tables["PC graph coordinates"], confirmed)
    assert app.runs[0].options[GRAPH] == BIPLOT

    before = app.runs[0].result.tables["Explained variance"]["Eigenvalue"].to_numpy().copy()
    app.show("data", title)
    app.edit_cell(0, 0, "3")
    wait()
    assert not np.allclose(app.runs[0].result.tables["Explained variance"]["Eigenvalue"], before)
    app.show("data", title)
    app.current_grid.select((1, 0))
    app.toggle_exclusion()
    wait()
    labels = app.runs[0].result.tables["PC graph coordinates"]
    kept = labels.loc[labels.Kind == "Row", "Label"].tolist()
    assert "città B" not in kept and "gruppo $C" in kept
    saved = labels.copy()
    assert app.save()
    app.import_file(app.path)
    app.open_sheet(("result", 0))
    wait()
    reopened = app.runs[0]
    assert reopened.options[LABEL] == "Label"
    assert reopened.options[COLOR_GROUPS] == "Cohort"
    assert all(reopened.options[option] is True for option in pca_reports.OPTIONS)
    assert list(reopened.result.tables)[-len(reports):] == list(reports)
    assert reopened.result.tables[pca_reports.INPUT_SHEET]["Source row"].tolist() == [0, 2, 3, 4, 5]
    assert reopened.result.figure.axes[0].get_legend().get_title().get_text() == "Cohort"
    pd.testing.assert_frame_equal(reopened.result.tables["PC graph coordinates"], saved)

    app.show("result", 0)
    app.result_tabs.select(list(reopened.result.tables).index("PC graph coordinates"))
    app.use_result_as_data()
    assert app.tables["PC graph coordinates"].raw["Kind"].tolist() == saved["Kind"].tolist()
    csv_path = directory / "pca-coordinates.csv"
    app.show("result", 0)
    app.result_tabs.select(list(app.runs[0].result.tables).index("PC graph coordinates"))
    with patch.object(filedialog, "asksaveasfilename", return_value=str(csv_path)):
        app.export()
    exported = pd.read_csv(csv_path)
    assert "gruppo $C" in exported["Label"].tolist()

    legacy_path = directory / "pca-legacy.alab"
    legacy = Dataset(frame.copy())
    legacy.analyses.append(("Principal component analysis", {"Variables": ["A", "B"], "Standardize": True}))
    save_project(legacy_path, {"Legacy": legacy})
    app.import_file(legacy_path)
    app.open_sheet(("result", 0))
    wait()
    old = app.runs[0]
    assert "Graph display" not in old.options
    assert list(old.result.tables) == ["Explained variance", "Eigenvectors", "Scores"]
    assert old.result.figure.axes[0].get_xlabel() == "PC1"
    assert old.result.figure.axes[0].get_ylabel() == "PC2"
    np.testing.assert_allclose(old.result.tables["Explained variance"]["Eigenvalue"], [1.6, 0.4])
