"""A linked nonlinear graph uses fitted coordinates and leaves mismatched graphs archived."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from zipfile import ZipFile

import numpy as np
import pandas as pd

from analisi.prism_fit_graph import FIT_GRAPH, FIT_GRAPH_POINTS, FIT_GRAPH_SPEC, FIT_INTERVAL_BAND, LOG_DOSE_MODEL
from analisi.workbench import analyse
from tests.test_prism_recipes import var
from trama_qt.project import Project


def fixture(path, *, graph_id=4, shifted_grid=False):
    observed_x = np.asarray([.1, .4, 1, 3, 10, 30])
    observed_y = 100 / (1 + observed_x / 3) + np.asarray([2, -1, 0, -.5, .2, 1.])
    grid = np.linspace(observed_x.min(), observed_x.max(), 12)
    if shifted_grid:
        grid[1] += .2
    content = {
        "variableDesign": {"x": var("x"), "responseList": [var("y", 1)], "factorList": []},
        "data": {"handleReplicatesAs": "INDIVIDUAL",
                 "range": {edge: {"enabled": False} for edge in ("minX", "maxX")}},
        "model": {
            "equation": {"definition": "Y=100 / (1+(IC50/X)^HillSlope)", "parameters": ["IC50", "HillSlope"]},
            "constraints": {"IC50": {"type": "GREATER", "value": 0.}},
            "initialValues": {"IC50": [{"isAuto": True, "value": 3.}],
                              "HillSlope": [{"isAuto": True, "value": -1.}]},
        },
        "method": {"fittingMethod": "LS", "outliers": {"method": "DO_NOT_HANDLE"},
                   "weighting": {"type": "NO_WEIGHTING"}},
        "interpolation": {"enabled": False}, "modelComparison": {"type": "NO_COMPARISON"},
        "graph": {"curve": {"minX": {"isAuto": True}, "maxX": {"isAuto": True}, "pointCount": len(grid)},
                  "curveBands": {"type": "NONE"}},
    }
    with ZipFile(path, "w") as archive:
        def write(name, value):
            archive.writestr(name, json.dumps(value))

        write("document.json", {"sheets": {"data": ["source"], "analyses": ["fit"], "graphs": ["plot"]}})
        write("data/sheets/source/sheet.json", {"title": "Experiment", "table": {
            "uid": "input", "format": "multivariable", "dataFormat": "y_single", "dataSets": ["x", "y"]}})
        method = "NONLINEAR_REGRESSION"
        write("analyses/fit/sheet.json", {"analysisClass": method, "title": "Archived fit",
              "inputSheets": [{"uid": "source"}], "isAllDataAnalyzed": True,
              "resultSheets": [{"uid": "curve-view"}, {"uid": "xy-view"}]})
        write("analyses/fit/parameters.json", {"analysisClass": method, "version": "0.0.0", "content": content})
        points = np.column_stack((observed_x, observed_y))
        curve = np.column_stack((grid, 100 / (1 + grid / 3)))
        for prefix, name, table in (("xy", "XY data", points), ("curve", "Curve", curve)):
            write(f"analyses/fit/result_sheets/{prefix}-view.json", {
                "name": name, "dataSheet": prefix, "graphId": 4})
            write(f"data/sheets/{prefix}/sheet.json", {"table": {
                "uid": prefix, "format": "xy", "dataFormat": "y_single",
                "xDataSet": f"{prefix}-x", "dataSets": [f"{prefix}-y"]}})
            for axis, title in (("x", "Concentration"), ("y", "Signal")):
                write(f"data/sets/{prefix}-{axis}.json", {"title": title})
            archive.writestr(f"data/tables/{prefix}/data.csv", "".join(f"{x},{y}\n" for x, y in table))
        write("data/sets/x.json", {"title": "Concentration"})
        write("data/sets/y.json", {"title": "Signal"})
        archive.writestr("data/tables/input/data.csv", "".join(f"{x},{y}\n" for x, y in points))
        write("graphs/plot/sheet.json", {"uid": "plot", "fenID": graph_id,
              "title": "Original plot", "inputDataSets": ["xy-y", "curve-y"]})


def refresh(project, runs):
    job = project.plan_refresh(runs)
    return project.apply_refresh(job, project.run_refresh(job))


class ImportedFitFigureTests(unittest.TestCase):
    def test_imported_parameter_band_reads_the_current_confidence_limits(self):
        x = np.arange(-8., 0.)
        y = 10 + 90 / (1 + 10 ** (-4.2 - x)) + np.array([-.2, .5, 1, -.4, -.1, 0, .3, -.2])
        frame = pd.DataFrame({"X": x, "Y": y})
        options = {
            "X": "X", "Y columns": ["Y"], "Model": LOG_DOSE_MODEL, "Parameter confidence level (%)": 90.,
            FIT_INTERVAL_BAND: {"title": "Imported dose response", "color": "#d4d4d4",
                                "limits": [[-9., 0.], [0., 120.]]},
        }
        project = Project()
        project.add_tables({"Dose": frame})
        run = project.candidate("Dose", "Nonlinear regression", options)
        project.add_result(run, analyse(run.method, frame, run.options))
        revised = {key: value for key, value in options.items() if key != FIT_INTERVAL_BAND}
        candidate = project.candidate("Dose", run.method, revised, index=0)
        self.assertEqual(candidate.options[FIT_INTERVAL_BAND], options[FIT_INTERVAL_BAND])
        for offset in (0., 5.):
            edited = frame.copy()
            edited.loc[3, "Y"] += offset
            result = analyse(candidate.method, edited, candidate.options)
            parameters = next(table for title, table in result.tables.items() if title.startswith("Parameters:"))
            expected = parameters.loc["Log EC50", ["CI 90% low", "CI 90% high"]]
            axes, = result.figure.axes
            patch, = axes.patches
            self.assertEqual(patch.get_gid(), "linked-parameter-interval")
            np.testing.assert_allclose([patch.get_x(), patch.get_x() + patch.get_width()], expected, rtol=0, atol=1e-14)
            self.assertEqual(axes.get_xlim(), (-9., 0.))
            self.assertEqual(axes.get_ylim(), (0., 120.))
        combined = analyse(candidate.method, frame.assign(Z=y + 5), {**candidate.options, "Y columns": ["Y", "Z"]})
        self.assertFalse(any(artist.get_gid() == "linked-parameter-interval"
                             for axes in combined.figure.axes for artist in axes.patches))

    def test_graph_uses_one_fit_and_follows_changes_across_roundtrip(self):
        from analisi import stats

        with TemporaryDirectory() as folder:
            path = Path(folder) / "fit.prismt"
            fixture(path)
            project = Project()
            project.load(path)
            fit, graph = project.runs
            self.assertTrue(graph.options[FIT_GRAPH])
            self.assertEqual(graph.source.table, FIT_GRAPH_POINTS)
            self.assertEqual(graph.source.analysis_id, fit.uid)
            self.assertEqual(fit.options[FIT_GRAPH_SPEC]["samples"], 12)
            self.assertNotIn("Prism graph · Original plot", project.tables)
            with patch.object(stats, "nonlinear", wraps=stats.nonlinear) as count:
                self.assertEqual(refresh(project, [graph]), [])
                self.assertEqual(count.call_count, 1)
            original = graph.result.tables["Saved XY coordinates"]
            lines = original.query('Geometry == "line"')
            np.testing.assert_array_equal(lines["X"], np.linspace(.1, 30, 12))
            self.assertEqual(len(original), 18)
            self.assertEqual(graph.result.figure.axes[0].get_ylabel(), "Signal")
            options = {name: value for name, value in fit.options.items() if name != FIT_GRAPH_SPEC}
            edited = project.candidate(fit.title, fit.method, options, index=0)
            self.assertEqual(edited.options[FIT_GRAPH_SPEC], fit.options[FIT_GRAPH_SPEC])
            name = Path(folder) / "fit.alab"
            project.save(name)
            reopened = Project()
            reopened.load(name)
            fit, graph = reopened.runs
            self.assertEqual(graph.source.analysis_id, fit.uid)
            self.assertEqual(refresh(reopened, [graph]), [])
            np.testing.assert_array_equal(graph.result.tables["Saved XY coordinates"]["Y"], original["Y"])
            self.assertEqual(refresh(reopened, reopened.paste(fit.title, 5, 0, [["50"]])), [])
            after = graph.result.tables["Saved XY coordinates"].query('Geometry == "line"')
            np.testing.assert_array_equal(after["X"], np.linspace(.1, 50, 12))
            self.assertNotEqual(after["Y"].tolist(), lines["Y"].tolist())

    def test_unmatched_id_or_custom_grid_keeps_the_archived_graph(self):
        for settings in ({"graph_id": 5}, {"shifted_grid": True}):
            with self.subTest(settings=settings), TemporaryDirectory() as folder:
                path = Path(folder) / "fit.prismt"
                fixture(path, **settings)
                project = Project()
                project.load(path)
                fit, graph = project.runs
                self.assertNotIn(FIT_GRAPH_SPEC, fit.options)
                self.assertIsNone(graph.source)
                self.assertIn("Prism graph · Original plot", project.tables)
