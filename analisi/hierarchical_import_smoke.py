"""Exercise editable clustering imports with synthetic project content only."""
from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

import numpy as np
import pandas as pd

from .graph_dialog import GraphFormatDialog
from .i18n import active_language, set_language


def _project(path):
    def variable(uid):
        return {"col": {"uid": uid, "idx": 0, "title": "Saved title"}}
    parameters = {
        "analysisClass": "HIERARCHICAL_CLUSTERING", "version": "0.0.0", "content": {
            "data": {"inputType": "ROWS_COLUMNS", "variables": [variable(c) for c in "ABC"],
                     "label": {"type": "VARIABLE", "variable": variable("label")}},
            "calc": {"columnTransform": "NONE", "rowTransform": "CENTER", "linkage": "COMPLETE",
                     "distance": {"type": "EUCLIDIAN", "value": 2.}},
            "defineClusters": {"rows": {"method": "NONE", "clusterCount": 2},
                               "columns": {"method": "NUMBER_OF_CLUSTERS", "clusterCount": 2}},
            "report": {"standardizedData": True, "distanceMatrix": True, "outputFullMatrix": False},
            "graph": {"plots": ["HEATMAP"]},
        },
    }
    with ZipFile(path, "w") as archive:
        def write(name, obj):
            archive.writestr(name, json.dumps(obj))
        write("document.json", {"sheets": {"data": ["source"], "analyses": ["tree"]}})
        write("data/sheets/source/sheet.json", {"title": "Marker expression", "table": {
            "uid": "matrix", "format": "multivariable", "dataFormat": "y_single",
            "dataSets": ["label", "A", "B", "C"]}})
        for uid, title in (("label", "Sample"), ("A", "Marker A"), ("B", "Marker B"), ("C", "Marker C")):
            write(f"data/sets/{uid}.json", {"title": title})
        archive.writestr("data/tables/matrix/data.csv", "Aster,1,3,2\nBirch,4,6,5\nCedar,9,4,5\nDahlia,2,5,8\n")
        write("analyses/tree/sheet.json", {"title": "Imported clustering", "analysisClass": "HIERARCHICAL_CLUSTERING",
              "isAllDataAnalyzed": True, "inputSheets": [{"uid": "source"}], "resultSheets": [{"uid": "cached"}]})
        write("analyses/tree/parameters.json", parameters)
        write("analyses/tree/result_sheets/cached.json", {"name": "Saved result", "dataSheet": "cached-sheet",
                                                        "isVisible": True})
        write("data/sheets/cached-sheet/sheet.json", {"table": {
            "uid": "cached-table", "format": "view", "dataFormat": "y_single", "dataSets": ["cached-y"]}})
        write("data/sets/cached-y.json", {"title": "Archived"})
        archive.writestr("data/tables/cached-table/data.csv", "101\n202\n")


def check_hierarchical_import(root, app, directory, kit):
    out = Path(directory)/"hierarchical-import"
    out.mkdir(exist_ok=True)
    language = active_language()

    def capture(window, name):
        kit.capture(window, name)
        path = Path(directory)/name
        if path.is_file():
            path.replace(out/name)

    def finish():
        kit.wait_for_calculation()
        assert not kit.errors, kit.errors
        assert all(not run.calculation_error for run in app.runs), [run.calculation_error for run in app.runs]

    def table():
        return app.runs[index].result.tables["Scaled data"]

    try:
        set_language("en")
        incoming = out/"synthetic-clustering.prism"
        _project(incoming)
        app.import_file(incoming)
        index = next(i for i, run in enumerate(app.runs) if run.method == "Hierarchical clustering")
        title = "Marker expression"
        archived_name = next(name for name in app.tables if name.startswith("Prism result"))
        archived = app.tables[archived_name].raw.copy(deep=True)
        app.open_sheet(("graph", index))
        finish()
        initial = table().copy(deep=True)
        np.testing.assert_allclose(initial, [[-1, 1, 0], [-1, 1, 0], [3, -2, -1], [-3, 0, 3]])
        assert len(app.runs[index].result.figure.axes) == 4
        assert "Row Assignments" not in app.runs[index].result.tables
        capture(root, "window-imported-clustering-en.png")

        def edit(dialog):
            assert dialog.controls["Direction"][1].get() == "Rows and columns"
            assert dialog.controls["Scale rows"][1].get() == "Center"
            assert dialog.controls["Row cut"][1].get() == "No cut"
            dialog.controls["Column clusters"][1].set("3")
            dialog.focus_field("Column clusters")
            capture(dialog, "window-imported-clustering-options-en.png")
        kit.drive_dialog(kit.AnalysisDialog, edit)
        app.edit_analysis()
        finish()
        assert app.runs[index].result.tables["Column Assignments"]["Cluster"].nunique() == 3

        app.show("graph", index)
        def format_graph(dialog):
            dialog.inputs["title"].set("Marker expression · Live clusters")
        kit.drive_dialog(GraphFormatDialog, format_graph)
        app.format_graph()
        style = deepcopy(app.runs[index].style)
        app.show("data", title)
        app.edit_cell(0, 1, "7")
        finish()
        assert not initial.equals(table())
        np.testing.assert_allclose(table().iloc[0].to_numpy(), [3, -1, -2])
        assert app.runs[index].style == style

        app.show("data", title)
        app.current_grid.select((1, 2))
        app.toggle_exclusion()
        finish()
        assert table().index.tolist() == [0, 2, 3]
        app.show("result", index)
        position = list(app.runs[index].result.tables).index("Scaled data")
        app.result_tabs.select(position)
        with patch.object(kit.filedialog, "asksaveasfilename", return_value=str(out/"scaled.csv")):
            app.export()
        assert "Marker A" in (out/"scaled.csv").read_text(encoding="utf-8")

        for suffix in ("svg", "png", "pdf"):
            app.show("graph", index)
            path = out/f"live-clustering.{suffix}"
            with patch.object(kit.filedialog, "asksaveasfilename", return_value=str(path)):
                app.export()
            assert path.stat().st_size > 1000
        app.path = out/"roundtrip.alab"
        assert app.save()
        changed = table().copy(deep=True)
        options = deepcopy(app.runs[index].options)
        app.import_file(app.path)
        app.open_sheet(("graph", index))
        finish()
        pd.testing.assert_frame_equal(table(), changed)
        assert app.runs[index].options == options and app.runs[index].style == style
        pd.testing.assert_frame_equal(app.tables[archived_name].raw, archived)

        set_language("it")
        app.show("graph", index)
        capture(root, "window-imported-clustering-it.png")
        def inspect_it(dialog):
            dialog.focus_field("Scale rows")
            capture(dialog, "window-imported-clustering-options-it.png")
        kit.drive_dialog(kit.AnalysisDialog, inspect_it)
        app.edit_analysis()
        finish()
        assert app.runs[index].options == options
        (out/"report.json").write_text(json.dumps({
            "directions": "Rows and columns", "row_centering": True, "column_clusters": 3,
            "edited_data": True, "excluded_row": 1, "roundtrip": True, "saved_snapshot_unchanged": True,
            "style_preserved": True, "screen": [root.winfo_screenwidth(), root.winfo_screenheight()],
        }, indent=2), encoding="utf-8")
    finally:
        set_language(language)
