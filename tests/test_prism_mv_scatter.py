import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from zipfile import ZipFile

from matplotlib.colors import to_rgba
import numpy as np

from analisi.data import Dataset, load_project, load_tables, save_project
from analisi.prism_mv_scatter import APPEARANCE
from analisi.prism_restore import SAVED_XY
from analisi.workbench import analyse

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


class SavedCategoricalScatterTests(unittest.TestCase):
    def test_view_uses_exact_ids_and_saves_editable_coordinates(self):
        with TemporaryDirectory() as folder:
            source = Path(folder) / "project.prismt"
            archive_fixture(source)
            self.assertEqual(list(load_tables(source)), ["Original"])
            tables = load_tables(source, restore_prism=True)
            self.assertNotIn("Graph unavailable", tables["Original"].attrs["import_warnings"][0])
            points = Dataset(tables[PLOT])
            path = Path(folder) / "roundtrip.alab"
            save_project(path, {PLOT: points})
            reopened = load_project(path)[PLOT]
            self.assertEqual(reopened.analyses, points.analyses)
            method, options = reopened.analyses[0]
            self.assertEqual(method, SAVED_XY)
            self.assertEqual(options[APPEARANCE]["palette"], COLORS)
            frame = reopened.frame()
            self.assertEqual(frame["Series"].tolist(), ["_Run B", "Run $A", "Run $A"])
            frame.loc[1, "X"] = 4.0
            figure = analyse(method, frame, options).figure
            ax, = figure.axes
            np.testing.assert_allclose(ax.collections[0].get_offsets(), [[4, 6], [5, 2]])
            np.testing.assert_allclose(ax.collections[1].get_offsets(), [[2, 5]])
            for artist, color in zip(ax.collections, COLORS.values(), strict=True):
                np.testing.assert_allclose(artist.get_facecolors()[0], to_rgba(color))
                np.testing.assert_allclose(artist.get_sizes(), [25])
                np.testing.assert_allclose(artist.get_linewidths(), [.4])
            self.assertEqual(ax.get_ylim(), (10, 0))
            self.assertEqual(ax.get_xlim(), (-1, 7))
            self.assertEqual(ax.get_xlabel(), "Dose $")
            np.testing.assert_allclose(ax.get_xticks(), [0, 2, 4, 6])
            np.testing.assert_allclose(ax.get_yticks(), [0, 2.5, 5, 7.5, 10])
            legend = ax.get_legend()
            self.assertEqual([item.get_text() for item in legend.get_texts()], list(COLORS))
            self.assertFalse(legend.get_texts()[0].get_parse_math())
            svg = Path(folder) / "saved.svg"
            figure.savefig(svg)
            self.assertIn("#339966", svg.read_text())

    def test_unsupported_graphs_keep_the_original_warning(self):
        for change in (
            {"dataSheet": "missing"},
            {"gdoTypesExt": {"defaults": ["symbols", "confidence ellipses"]}},
            {"xVariables": ["scatter-y"]},
            {"xVariables": ["not-a-dataset"]},
        ):
            with self.subTest(change=change), TemporaryDirectory() as folder:
                source = Path(folder) / "project.prismt"
                archive_fixture(source, change=change)
                views = load_tables(source, restore_prism=True)
                self.assertNotIn(PLOT, views)
                self.assertIn("Graph unavailable for Grouped scatter", views["Original"].attrs["import_warnings"][0])
