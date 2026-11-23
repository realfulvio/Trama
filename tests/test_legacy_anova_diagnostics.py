"""Recalculate the requested diagnostic outputs of an imported multifactor ANOVA."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from zipfile import ZipFile

import numpy as np

from analisi import anova_diagnostics as diag, workbench
from tests.test_legacy_recipes import var
from trama_qt.project import Project, run_view


def write_project(path, tests, graphs):
    a, b = {"varIdx": 0, "varID": var("a")}, {"varIdx": 1, "varID": var("b", 1)}
    content = {
        "model": {"response": {"variable": {"id": var("y", 2)}, "definition": ""},
                  "predictor": {"variables": [{"id": a["varID"], "effectType": "FIXED"},
                                              {"id": b["varID"], "effectType": "FIXED"}],
                                "definition": [[], [a], [b], [a, b]]}},
        "postTests": {"type": "NO_TESTS"},
        "residuals": {"diagnostics": tests, "graphs": graphs},
    }
    method = "MULTI_FACTOR_ANOVA"
    records = {
        "document.json": {"sheets": {"data": ["data"], "analyses": ["model"]}},
        "data/sheets/data/sheet.json": {"title": "Observations", "table": {
            "uid": "raw", "format": "multivariable", "dataFormat": "y_single", "dataSets": ["a", "b", "y"]}},
        "analyses/model/sheet.json": {"analysisClass": method, "title": "Treatment and time",
                                      "inputSheets": [{"uid": "data"}], "isAllDataAnalyzed": True},
        "analyses/model/parameters.json": {"analysisClass": method, "version": "0.0.0", "content": content},
        **{f"data/sets/{key}.json": {"title": label} for key, label in
           {"a": "Treatment", "b": "Time", "y": "Response"}.items()},
    }
    with ZipFile(path, "w") as archive:
        for name, value in records.items():
            archive.writestr(name, json.dumps(value))
        archive.writestr("data/tables/raw/data.csv",
                         "A,Early,1\nA,Early,3\nA,Early,5\nA,Late,7\nA,Late,8\nA,Late,9\n"
                         "B,Early,9\nB,Early,10\nB,Early,11\nB,Late,14\nB,Late,17\nB,Late,20\n")


def refresh(project, runs):
    job = project.plan_refresh(runs)
    return project.apply_refresh(job, project.run_refresh(job))


class ImportedANOVADiagnosticsTests(unittest.TestCase):
    def test_graphs_share_one_fit_and_refresh_after_reopen(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "diagnostics.prismt"
            write_project(path, {"normalityTests": True, "heteroscedasticityTests": True},
                          {"residualsPlot": True, "homoscedasticityPlot": True, "qqPlot": True})
            project = Project()
            project.load(path)
            parent, *plots = project.runs
            self.assertEqual(parent.method, "Multifactor ANOVA")
            self.assertEqual([plot.options[diag.GRAPH] for plot in plots], list(diag.GRAPHS[1:]))
            self.assertTrue(all(plot.source.analysis_id == parent.uid and plot.source.table == diag.SHEET
                                and run_view(plot.method) == "graph" for plot in plots))
            fit = workbench.engine._factorial_anova_components
            with patch.object(workbench.engine, "_factorial_anova_components", wraps=fit) as fit_count:
                self.assertEqual(refresh(project, plots), [])
                self.assertEqual(fit_count.call_count, 1)
            self.assertEqual(parent.result.tables[diag.ASSUMPTION_SHEET]["Test"].to_list(), list(diag.TESTS))
            expected = [-2., 0., 2., -1., 0., 1., -1., 0., 1., -3., 0., 3.]
            fitted = np.repeat([3., 8., 10., 17.], 3)
            for plot, residual in zip(plots[:2], (expected, np.abs(expected)), strict=True):
                points = plot.result.figure.axes[0].collections[0].get_offsets()
                np.testing.assert_allclose(points, np.column_stack((fitted, residual)), atol=1e-12)
            points = plots[2].result.figure.axes[0].collections[0].get_offsets()
            np.testing.assert_allclose(points[:, 1], np.sort(expected), atol=1e-12)
            saved = Path(folder) / "diagnostics.alab"
            project.save(saved)
            reopened = Project()
            reopened.load(saved)
            self.assertEqual(refresh(reopened, reopened.paste(parent.title, 0, 2, [["4"]])), [])
            residuals = reopened.runs[1].result.figure.axes[0].collections[0].get_offsets()
            np.testing.assert_allclose(residuals[:3, 1], [0., -1., 1.], atol=1e-12)

    def test_keeps_the_requested_test_family_and_graphs(self):
        cases = (({"normalityTests": True}, diag.NORMALITY_TESTS, diag.TESTS[1:]),
                 ({"heteroscedasticityTests": True}, diag.VARIANCE_TEST, diag.TESTS[:1]))
        for flags, kind, expected in cases:
            with self.subTest(kind=kind), TemporaryDirectory() as folder:
                path = Path(folder) / "diagnostics.prismt"
                write_project(path, flags, {"qqPlot": True})
                project = Project()
                project.load(path)
                parent, graph = project.runs
                self.assertEqual(parent.options[diag.TEST_SET], kind)
                self.assertEqual(graph.options[diag.GRAPH], diag.GRAPH_QQ)
                self.assertEqual(refresh(project, [graph]), [])
                self.assertEqual(parent.result.tables[diag.ASSUMPTION_SHEET]["Test"].to_list(), list(expected))
