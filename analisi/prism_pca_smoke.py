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


def write_project(path, *, cached_format="multivariable", clustered=False, reorder_rows=False):
    frame, content = sample()
    sheet = {"analysisClass": "PCA", "inputSheets": [{"uid": "source"}], "isAllDataAnalyzed": True}
    parameters = {"analysisClass": "PCA", "version": "0.0.0", "content": content}
    columns = {uid: name for uid, (name,) in INPUT.items()}
    raw = frame if clustered else pd.DataFrame({"Unrelated": [8, 9]})
    archived = frame
    if clustered:
        columns.update({"k1": "1 clusters", "k2": "2 clusters", "k3": "3 clusters"})
        archived = frame.assign(**{"1 clusters": "Cluster 1",
                                   "2 clusters": ["Cluster 1", "Cluster 2"] * 4,
                                   "3 clusters": ["Cluster 1", "Cluster 2", "Cluster 3", "Cluster 1"] * 2})
        content["graph"]["variables"]["symbolColor"]["variable"] = {"col": {"uid": "k2", "idx": 5}}
    if reorder_rows:
        archived = archived.iloc[::-1]
    data_sheet = {"title": "Measurements", "table": {
        "uid": "values", "format": cached_format, "dataFormat": "y_single", "dataSets": list(columns),
    }}
    with ZipFile(path, "w") as archive:
        def write(name, value):
            archive.writestr(name, json.dumps(value))
        # The consumer appears before its input-producing analysis. A saved view still resolves.
        write("document.json", {"sheets": {"data": ["raw"], "analyses": ["pca", "producer"]}})
        raw_ids = [f"raw-{index}" for index in range(len(raw.columns))]
        write("data/sheets/raw/sheet.json", {"title": "Raw", "table": {
            "uid": "raw-values", "format": "multivariable" if clustered else "column", "dataFormat": "y_single",
            "dataSets": raw_ids}})
        for uid, name in zip(raw_ids, raw.columns, strict=True):
            write(f"data/sets/{uid}.json", {"title": name})
        archive.writestr("data/tables/raw-values/data.csv", raw.to_csv(index=False, header=False))
        write("analyses/pca/sheet.json", {**sheet, "title": ANALYSIS_TITLE, "resultSheets": []})
        write("analyses/pca/parameters.json", parameters)
        producer = {"title": "Saved assignments", "analysisClass": "UNSUPPORTED",
                    "resultSheets": [{"uid": "table-view"}]}
        if clustered:
            producer.update(analysisClass="K_MEANS_CLUSTERING", inputSheets=[{"uid": "raw"}], isAllDataAnalyzed=True)
            write("analyses/producer/parameters.json", {
                "analysisClass": "K_MEANS_CLUSTERING", "version": "0.0.0", "content": {
                    "data": {"variables": [{"col": {"uid": uid}} for uid in raw_ids[:3]]},
                    "calc": {"algorithm": "HARTIGAN_WONG", "transform": "STANDARDIZE",
                             "distance": {"type": "EUCLIDIAN"}, "clusterMetrics": True,
                             "clusterCount": {"min": 1, "max": 3}, "maxIterCount": 10,
                             "randomSeed": {"value": 2718}},
                },
            })
        write("analyses/producer/sheet.json", producer)
        write("analyses/producer/result_sheets/table-view.json",
              {"name": "Clustered data" if clustered else "Measurements", "dataSheet": "source", "isVisible": True})
        write("data/sheets/source/sheet.json", data_sheet)
        for uid, name in columns.items():
            write(f"data/sets/{uid}.json", {"title": name})
        archive.writestr("data/tables/values/data.csv", archived.to_csv(index=False, header=False))


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

    project = out / "Linked PCA.alab"
    save_project(project, {"Workspace": Dataset(pd.DataFrame({"Value": [1, 2]}))})
    app.import_file(project)
    archive = out / "Linked PCA.prismt"
    write_project(archive, clustered=True)
    app.import_file(archive)
    wait()
    _, run = open_graph()
    assert run.title == "Raw" and run.source and run.source.table == "Assignments by k"
    assert run.options["Color groups by"] == "Cluster (k=2)"
    old_eigenvalue = run.result.tables["Explained variance"].iloc[0]["Eigenvalue"]
    app.source_analysis()
    parent = app.runs[app.selected[1]]
    assert parent.uid == run.source.analysis_id
    assert list(parent.result.tables)[app.result_tabs.index("current")] == "Assignments by k"
    app.show("data", "Raw")
    app.edit_cell(0, 0, "20")
    wait()
    new_eigenvalue = run.result.tables["Explained variance"].iloc[0]["Eigenvalue"]
    assert new_eigenvalue != old_eigenvalue
    assert app.save()
    app.import_file(project)
    wait()
    _, reopened = open_graph()
    assert reopened.source == run.source
    assert reopened.result.tables["Explained variance"].iloc[0]["Eigenvalue"] == new_eigenvalue
    capture(root, "window-linked-pca.png")
