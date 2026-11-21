"""The saved graph follows the identified Kaplan–Meier result across edits."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from zipfile import ZipFile

import numpy as np

from analisi import stats
from analisi.survival_plot import SURVIVAL_GRAPH, SURVIVAL_SUMMARY
from tests.test_prism_fit_graph import refresh
from tests.test_prism_recipes import var
from trama_qt.project import Project


def write_project(path, graph_id):
    method = "SURVIVAL"
    content = {
        "variableDesign": {"x": var("t"), "responseList": [var("e", 1)], "factorList": [var("g", 2)]},
        "data": {"eventCode": 1, "censorCode": 0, "treatUndefinedValuesAs": "MISSING"},
        "calc": {"tabulate": "EVENT", "logrankTestMethod": "RECOMMENDED", "logrankTest": True},
        "graph": {"showNumberAtRiskTable": True},
    }
    with ZipFile(path, "w") as archive:
        def write(name, value):
            archive.writestr(name, json.dumps(value))

        write("document.json", {"sheets": {"data": ["source"], "analyses": ["km"], "graphs": ["plot"]}})
        write("data/sheets/source/sheet.json", {"title": "Subjects", "table": {
            "uid": "raw", "format": "multivariable", "dataFormat": "y_single", "dataSets": ["t", "e", "g"]}})
        write("analyses/km/sheet.json", {"analysisClass": method, "title": "Survival",
              "inputSheets": [{"uid": "source"}], "isAllDataAnalyzed": True,
              "resultSheets": [{"uid": "curves"}]})
        write("analyses/km/parameters.json", {"analysisClass": method, "version": "0.0.2", "content": content})
        write("analyses/km/result_sheets/curves.json", {
            "name": "Survival proportions", "dataSheet": "probabilities", "graphId": 4})
        write("data/sheets/probabilities/sheet.json", {"table": {
            "uid": "xy", "format": "xy", "dataFormat": "y_single",
            "xDataSet": "time", "dataSets": ["a", "b"]}})
        for key, title in {"t": "Time", "e": "Event", "g": "Group", "time": "Time", "a": "A", "b": "B"}.items():
            write(f"data/sets/{key}.json", {"title": title})
        archive.writestr("data/tables/raw/data.csv", "1,1,A\n4,0,A\n2,1,B\n3,1,B\n")
        archive.writestr("data/tables/xy/data.csv", "1,0.5,\n2,,0.5\n3,,0\n4,0.5,\n")
        write("graphs/plot/sheet.json", {"uid": "plot", "fenID": graph_id,
              "title": "Follow-up $", "inputDataSets": ["b", "a"]})


class ImportedSurvivalFigureTests(unittest.TestCase):
    def test_graph_uses_its_parent_once_and_keeps_saved_series_order(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "survival.prismt"
            write_project(path, 4)
            project = Project()
            project.load(path)
            parent, graph = project.runs
            self.assertTrue(graph.options[SURVIVAL_GRAPH])
            self.assertEqual(graph.source.table, SURVIVAL_SUMMARY)
            self.assertEqual(graph.source.analysis_id, parent.uid)
            with patch.object(stats, "survival", wraps=stats.survival) as count:
                self.assertEqual(refresh(project, [graph]), [])
                self.assertEqual(count.call_count, 1)
            axes, risk = graph.result.figure.axes
            self.assertEqual(axes.get_title(), "Follow-up $")
            self.assertFalse(axes.title.get_parse_math())
            self.assertEqual(axes.get_legend_handles_labels()[1], ["B", "A"])
            self.assertEqual(risk.tables[0][1, 0].get_text().get_text(), "B")
            np.testing.assert_array_equal(axes.lines[2].get_xdata(), [0., 1., 4.])

            fields = {name: value for name, value in parent.options.items() if name != SURVIVAL_GRAPH}
            candidate = project.candidate(parent.title, parent.method, fields, index=0)
            self.assertTrue(candidate.options[SURVIVAL_GRAPH])
            saved = Path(folder) / "survival.alab"
            project.save(saved)
            reopened = Project()
            reopened.load(saved)
            parent, graph = reopened.runs
            self.assertEqual(graph.source.analysis_id, parent.uid)
            self.assertEqual(refresh(reopened, [graph]), [])
            self.assertEqual(refresh(reopened, reopened.paste(parent.title, 0, 0, [["1.5"]])), [])
            np.testing.assert_array_equal(graph.result.figure.axes[0].lines[2].get_xdata(), [0., 1.5, 4.])

    def test_unmatched_graph_keeps_archive_coordinates(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "survival.prismt"
            write_project(path, 5)
            project = Project()
            project.load(path)
            parent, graph = project.runs
            self.assertNotIn(SURVIVAL_GRAPH, parent.options)
            self.assertIsNone(graph.source)
            self.assertIn("Prism graph · Follow-up $", project.tables)
