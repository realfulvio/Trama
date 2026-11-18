"""Synthetic project and GUI smoke for an editable PCA imported from a saved result."""

import json
from unittest.mock import patch
from zipfile import ZipFile

import pandas as pd

from .data import Dataset, save_project

INPUT = {"a": ["Signal"], "b": ["Signal (2)"], "c": ["Baseline"], "group": ["Cohort"]}
SOURCE_NAME = "Prism result · Saved assignments · Measurements"
ANALYSIS_TITLE = "Saved PCA"


def sample():
    frame = pd.DataFrame({
        "Signal": [2., 10., 2., 10., 3., 11., 1., 9.],
        "Signal (2)": [1., 9., 2., 10., 4., 12., 1., 9.],
        "Baseline": [2., 2., 10., 10., 2., 2., 10., 10.],
        "Cohort": ["First", "First", "Second", "Second"] * 2,
    })
    content = {
        "data": {"variables": [{"col": {"uid": key, "idx": index, "title": "Original title"}} for index, key in enumerate(("a", "b", "c"))]},
        "calc": {
            "transform": "STANDARDIZE_DATA", "method": "PARALLEL_ANALYSIS",
            "parallelAnalysis": {"percentileLevel": 95., "simulationCount": 120,
                                 "randomSeed": 2718, "randomSeedType": "AUTO"},
            "regression": {"run": False},
        },
        "report": {"transformedData": True, "eigenvectors": False, "variablesContributionMatrix": True,
                   "variablesComponentsCorrelationMatrix": False, "casesContributionMatrix": False,
                   "variablesCorrelationMatrix": True},
        "graph": {"scorePlot": True, "loadingPlot": False, "biPlot": False, "screePlot": False,
                  "varianceProportionPlot": False, "variables": {
                      "labels": {"use": False},
                      "symbolColor": {"use": True, "variable": {"col": {"uid": "group", "idx": 3, "title": "Original title"}}},
                      "symbolSize": {"use": False},
                      "connectingLine": {"use": False},
                  }},
    }
    return frame, content


def write_project(path, *, cached_format="multivariable"):
    frame, content = sample()
    sheet = {"analysisClass": "PCA", "inputSheets": [{"uid": "source"}], "isAllDataAnalyzed": True}
    parameters = {"analysisClass": "PCA", "version": "0.0.0", "content": content}
    data_sheet = {"title": "Measurements", "table": {
        "uid": "values", "format": cached_format, "dataFormat": "y_single", "dataSets": list(INPUT),
    }}
    with ZipFile(path, "w") as archive:
        def write(name, value):
            archive.writestr(name, json.dumps(value))
        # The consumer appears before its input-producing analysis. A saved view still resolves.
        write("document.json", {"sheets": {"data": ["raw"], "analyses": ["pca", "producer"]}})
        write("data/sheets/raw/sheet.json", {"title": "Raw", "table": {
            "uid": "raw-values", "format": "column", "dataFormat": "y_single", "dataSets": ["raw-a"]}})
        write("data/sets/raw-a.json", {"title": "Unrelated"})
        archive.writestr("data/tables/raw-values/data.csv", "8\n9\n")
        write("analyses/pca/sheet.json", {**sheet, "title": ANALYSIS_TITLE, "resultSheets": []})
        write("analyses/pca/parameters.json", parameters)
        write("analyses/producer/sheet.json", {"title": "Saved assignments", "analysisClass": "UNSUPPORTED",
                                               "resultSheets": [{"uid": "table-view"}]})
        write("analyses/producer/result_sheets/table-view.json",
              {"name": "Measurements", "dataSheet": "source", "isVisible": True})
        write("data/sheets/source/sheet.json", data_sheet)
        for uid, (name,) in INPUT.items():
            write(f"data/sets/{uid}.json", {"title": name})
        archive.writestr("data/tables/values/data.csv", frame.to_csv(index=False, header=False))


def check_restored_pca(root, app, directory, capture, wait):
    from tkinter import filedialog

    out = directory / "pca-import"
    out.mkdir(exist_ok=True)
    project = out / "Imported PCA.alab"
    save_project(project, {"Workspace": Dataset(pd.DataFrame({"Value": [1, 2]}))})
    app.import_file(project)
    archive = out / "Synthetic PCA.prismt"
    write_project(archive)
    app.import_file(archive)
    wait()

    def open_graph():
        index = next(i for i, run in enumerate(app.runs) if run.name == ANALYSIS_TITLE)
        app.open_sheet(("graph", index))
        wait()
        run = app.runs[index]
        assert run.result is not None and run.method == "Principal component analysis"
        return index, run

    _, run = open_graph()
    selection = run.result.tables["PCA selection settings"].iloc[0]
    assert selection["Seed"] == 2718 and selection["Simulations"] == 120
    assert run.title == SOURCE_NAME
    assert "Transformed data" in run.result.tables and "Variable contributions" in run.result.tables
    axes = run.result.figure.axes[0]
    assert [label.get_text() for label in axes.get_legend().get_texts()] == ["First", "Second"]
    old_eigenvalue = run.result.tables["Explained variance"].iloc[0]["Eigenvalue"]

    app.show("data", SOURCE_NAME)
    app.edit_cell(0, 0, "3.25")
    wait()
    _, run = open_graph()
    new_eigenvalue = run.result.tables["Explained variance"].iloc[0]["Eigenvalue"]
    assert new_eigenvalue != old_eigenvalue
    assert app.save()
    app.import_file(project)
    wait()
    index, run = open_graph()
    assert run.result.tables["Explained variance"].iloc[0]["Eigenvalue"] == new_eigenvalue
    assert run.options["Color groups by"] == "Cohort"
    app.show("graph", index)
    for ext in ("png", "svg"):
        target = out / f"Imported PCA.{ext}"
        with patch.object(filedialog, "asksaveasfilename", return_value=str(target)):
            app.export()
        assert target.stat().st_size > 1000
    capture(root, "window-restored-pca.png")
