"""Synthetic linked grouped ANOVA and its desktop acceptance."""
import json
from math import isclose
from zipfile import ZipFile

import pandas as pd

from .data import Dataset, save_project
from .grouped_anova import METHOD


def archived_chain(path, *, valid=True, graph=None):
    """Build a synthetic result dependency with the child listed before its producer."""
    with ZipFile(path, "w") as project:
        def write(name, value):
            project.writestr(name, json.dumps(value))

        def sheet(uid, name, table, columns, kind, **shape):
            write(f"data/sheets/{uid}/sheet.json", {"title": name, "table": {
                "uid": table, "format": kind, "dataFormat": "y_single", "dataSets": columns, **shape,
            }})

        document = {"data": ["raw"], "analyses": ["test", "extract"]}
        if graph is not None:
            document["graphs"] = ["graph"]
            write("graphs/graph/sheet.json", {
                "uid": "graph", "title": "Extracted observations", "fenID": 3,
                "inputDataSets": ["b", "a"], **graph,
            })
        write("document.json", {"sheets": document})
        for uid, title in (("r", "Temperature"), ("c", "Treatment"), ("y", "Signal"),
                           ("row", "Temperature"), ("a", "Pump"), ("b", "Other")):
            write(f"data/sets/{uid}.json", {"title": title})
        sheet("raw", "Signals", "raw-values", ["r", "c", "y"], "multivariable")
        sheet("wide", "Grouped", "grouped-values", ["b", "a"], "grouped",
              dataFormat="y_replicates", replicatesCount=2, rowTitlesDataSet="row")
        project.writestr("data/tables/raw-values/data.csv",
                         "Warm,Pump,8\nWarm,Pump,10\nWarm,Other,4\nWarm,Other,6\n"
                         "Cold,Pump,4\nCold,Pump,6\nCold,Other,3\nCold,Other,4\n")
        project.writestr("data/tables/grouped-values/data.csv", "Cold,3,4,4,6\nWarm,4,6,8,10\n")

        def analysis(uid, kind, input_sheet, params, **metadata):
            write(f"analyses/{uid}/sheet.json", {
                "title": uid, "analysisClass": kind, "isAllDataAnalyzed": True,
                "inputSheets": [{"uid": input_sheet}], **metadata,
            })
            write(f"analyses/{uid}/parameters.json", {
                "analysisClass": kind, "version": "0.0.1", "content": params,
            })

        selected = [{"uid": "b"}, {"uid": "a"}] if valid else [{"uid": "b"}]
        analysis("test", "TWO_WAY_ANOVA", "wide", {
            "experimentalDesign": "ORDINARY_ANOVA", "postTests": {"type": "NO_TESTS"},
            "options": {"includeInteractionTerm": True},
            "factorNames": {"rowFactor": "Temperature", "colFactor": "Treatment"},
            "report": {"effectSizes": False}, "residuals": {"graphs": {"qqPlot": False}},
        }, inputDataSets=selected)
        analysis("extract", "EXTRACT_REARRANGE", "raw", {
            "resultTableFormat": "GROUPED", "includeVarNamePrefix": False, "reportCompleteRowsOnly": False,
            "rowTitles": {"type": "NO", "variable": None}, "dataArrangement": {
                "responseVariable": {"col": {"uid": "y"}},
                "rowFactorVariable": {"col": {"uid": "r"}},
                "columnFactorVariable": {"col": {"uid": "c"}},
            },
        }, resultSheets=[{"uid": "table"}])
        write("analyses/extract/result_sheets/table.json",
              {"dataSheet": "wide", "name": "Results", "isVisible": True, "graphId": 3})


def check_linked_grouped_anova(root, app, directory, capture, wait):
    out = directory / "linked-grouped-anova"
    out.mkdir(exist_ok=True)
    fixture = out / "Synthetic grouped.prismt"
    project = out / "Synthetic grouped.alab"
    archived_chain(fixture)
    save_project(project, {"Workspace": Dataset(pd.DataFrame({"Value": [1]}))})
    app.import_file(project)
    app.import_file(fixture)
    wait()

    def open_result():
        slot = next(i for i, run in enumerate(app.runs) if run.method == METHOD)
        app.open_sheet(("result", slot))
        wait()
        run = app.runs[slot]
        assert run.result is not None
        table = run.result.tables["ANOVA (type III)"]
        assert table.loc["Residual", "df"] == 4
        return run, float(table.loc["Temperature", "F"])

    run, initial = open_result()
    assert isclose(initial, 15.125 / 1.625, abs_tol=1e-10)
    assert run.title == "Signals" and run.source and run.source.table == "Rearranged data"
    app.source_analysis()
    producer = app.runs[app.selected[1]]
    assert producer.uid == run.source.analysis_id
    assert producer.result.tables[run.source.table].shape == (2, 5)

    app.show("data", "Signals")
    app.edit_cell(0, 2, "12")
    wait()
    _, edited = open_result()
    assert isclose(edited, 28.125 / 1.625, abs_tol=1e-10)
    assert app.save()
    app.import_file(project)
    wait()
    reopened, saved = open_result()
    assert reopened.source == run.source and isclose(saved, edited, abs_tol=1e-12)
    app.show("data", "Imported result · extract · Results")
    assert app.get_dataset().frame().iloc[1]["Pump [1]"] == 8
    open_result()
    capture(root, "window-linked-grouped-anova.png")
    (out / "results.json").write_text(json.dumps({
        "status": "PASS", "initial_F": initial, "updated_F": edited, "reopened_F": saved,
        "snapshot_unchanged": True,
    }, indent=2), encoding="utf-8")
