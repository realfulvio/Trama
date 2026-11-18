"""Synthetic archive and desktop check for editable categorical scatter imports."""
import json
from unittest.mock import patch
from zipfile import ZipFile

import pandas as pd

from .data import Dataset, save_project


PLOT = "Prism graph · Grouped scatter"
COLORS = {"Run $A": "#33996680", "_Run B": "#8b3366c0"}


def _title(text):
    return {"text": {"string": text}}


def _axis(label, orientation, low, high, start, step, reversed=False):
    return {"orientation": orientation, "title": _title(label), "segments": [{
        "@class": "LinearAxisSegment", "lowerLimit": low, "upperLimit": high,
        "startTicksValue": start, "interval": step, "isReversed": reversed,
    }]}


def archive_fixture(path, *, change=None):
    details = {
        "@class": "MVGraph", "dataSheet": "scatter-input",
        "xVariables": ["scatter-x"], "yVariables": ["scatter-y"],
        "gdoTypes": {"defaults": ["symbols"]}, "gdoTypesExt": {"defaults": ["symbols"]},
        "gdoSettings": {"symbols": {
            "@class": "BubblesFigure::Settings", "colorVariable": "scatter-cohort",
            "colormap": {"@class": "CategoricalColormap", "colors": {
                "1": COLORS["_Run B"], "0": COLORS["Run $A"]}},
            "isColorLegendEnabled": True,
            "sizeEvaluator": {"@class": "SymbolSizeEvaluator", "symbolSize": 5},
            "rowSymbolSettings": {"common": {
                "symbolShape": "circleFill", "symbolBorderColor": "#12151aff", "symbolBorderThickness": .4,
            }},
        }},
        "axisX": _axis("Dose $", "horizontal", -1, 7, 0, 2),
        "axisY": _axis("Signal", "vertical", 0, 10, 0, 2.5, reversed=True),
        "legends": [{"@class": "CategoricalSymbolsLegend", "title": _title("Cohort"), "children": [
            {"@class": "SymbolLegend", "title": _title(group), "symbolShape": "circleFill", "symbolFillColor": color}
            for group, color in COLORS.items()
        ]}],
    }
    if change:
        details.update(change)
    with ZipFile(path, "w") as archive:
        records = {
            "document.json": {"sheets": {"data": ["original"], "analyses": ["calculation"], "graphs": ["scatter"]}},
            "data/sheets/original/sheet.json": {"title": "Original", "table": {
                "uid": "raw-grid", "format": "column", "dataFormat": "y_single", "dataSets": ["raw-values"],
            }},
            "data/sets/raw-values.json": {"title": "Input"},
            "analyses/calculation/sheet.json": {"title": "Cached calculation", "analysisClass": "UNKNOWN",
                                                "resultSheets": [{"uid": "cache"}]},
            "analyses/calculation/result_sheets/cache.json": {"name": "Coordinates", "dataSheet": "scatter-input",
                                                              "isVisible": True},
            "data/sheets/scatter-input/sheet.json": {"table": {
                "uid": "scatter-grid", "format": "multivariable", "dataFormat": "y_single",
                "dataSets": ["scatter-x", "scatter-y", "scatter-cohort"],
            }},
            "data/sets/scatter-x.json": {"title": "Source X", "currentType": "numeric"},
            "data/sets/scatter-y.json": {"title": "Source Y", "currentType": "numeric"},
            "data/sets/scatter-cohort.json": {"title": "Cohort", "currentType": "categorical"},
            "graphs/scatter/sheet.json": {"uid": "scatter", "title": "Grouped scatter", "graph": details},
        }
        for name, document in records.items():
            archive.writestr(name, json.dumps(document))
        archive.writestr("data/tables/raw-grid/data.csv", "1\n2\n")
        archive.writestr("data/tables/scatter-grid/data.csv", "2,5,_Run B\n3,6,Run $A\n5,2,Run $A\n,6,_Run B\n")


def check_saved_scatter(root, app, directory, capture, wait):
    from tkinter import filedialog

    out = directory / "categorical-scatter-import"
    out.mkdir(exist_ok=True)
    path = out / "Editable scatter.alab"
    save_project(path, {"Workspace": Dataset(pd.DataFrame({"Value": [1, 2]}))})
    app.import_file(path)
    archive = out / "Grouped sample.prismt"
    archive_fixture(archive)
    app.import_file(archive)
    wait()

    def graph():
        index = next(i for i, run in enumerate(app.runs) if run.title == PLOT)
        app.open_sheet(("graph", index))
        wait()
        return index, app.runs[index].result.figure.axes[0]

    _, axes = graph()
    assert axes.get_xlabel() == "Dose $" and axes.get_ylim() == (10, 0)
    assert axes.collections[0].get_offsets().tolist() == [[3., 6.], [5., 2.]]
    app.show("data", PLOT)
    app.edit_cell(1, 0, "4.25")
    wait()
    _, axes = graph()
    assert axes.collections[0].get_offsets().tolist() == [[4.25, 6.], [5., 2.]]
    app.toggle_inspector()
    app.inspector.vars["title"].set("Edited scatter")
    app.inspector._update("title")
    assert app.inspector.has_draft and app.inspector.apply()
    app.toggle_inspector()

    assert app.save()
    app.import_file(path)
    wait()
    index, reopened = graph()
    assert reopened.get_title() == "Edited scatter"
    assert reopened.get_ylim() == (10, 0)
    assert reopened.collections[0].get_offsets().tolist() == [[4.25, 6.], [5., 2.]]
    assert [text.get_text() for text in reopened.get_legend().get_texts()] == list(COLORS)
    for ext in ("svg", "png"):
        target = out / f"Checked scatter.{ext}"
        app.show("graph", index)
        with patch.object(filedialog, "asksaveasfilename", return_value=str(target)):
            app.export()
        assert target.stat().st_size > 1000
    capture(root, "window-restored-categorical-scatter.png")
