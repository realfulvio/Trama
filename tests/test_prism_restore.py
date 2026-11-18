import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from zipfile import ZipFile

import numpy as np
import pandas as pd

from analisi.data import Dataset, load_project, load_tables, save_project
from analisi.prism_restore import PRISM_TITLE, SAVED_XY
from analisi.workbench import analyse


class PrismRestoreTests(unittest.TestCase):
    def test_zip_xy_graph_preserves_the_recorded_error_endpoints_through_alab(self):
        cases = (
            ("y_sd", "1,10,2\n", (8, 12)),
            ("y_sd_n", "1,10,2,5\n", (8, 12)),
            ("y_se", "1,10,2\n", (8, 12)),
            ("y_se_n", "1,10,2,5\n", (8, 12)),
            ("y_high_low", "1,10,,6\n", (6, 10)),
            ("y_plus_minus", "1,10,3,\n", (10, 13)),
        )
        with TemporaryDirectory() as folder:
            for mode, row, bounds in cases:
                with self.subTest(mode=mode):
                    source = Path(folder) / f"{mode}.pzt"
                    with ZipFile(source, "w") as archive:
                        def write(name, value):
                            archive.writestr(name, json.dumps(value))

                        write("document.json", {"sheets": {"data": ["raw"], "graphs": ["figure"]}})
                        write("data/sheets/raw/sheet.json", {"title": "Measurement", "table": {
                            "uid": "data", "format": "xy", "xDataSet": "x", "dataSets": ["y"], "dataFormat": mode,
                        }})
                        write("data/sets/x.json", {"title": "Time"})
                        write("data/sets/y.json", {"title": "Response"})
                        archive.writestr("data/tables/data/data.csv", row)
                        write("graphs/figure/sheet.json", {"title": "Uncertainty", "inputDataSets": ["y"]})
                    tables = load_tables(source, restore_prism=True)
                    project = Path(folder) / f"{mode}.alab"
                    save_project(project, {name: Dataset(frame) for name, frame in tables.items()})
                    restored = load_project(project)["Prism graph · Uncertainty"]
                    method, options = restored.analyses[0]
                    fig = analyse(method, restored.frame(), options).figure
                    bars, = fig.axes[0].containers
                    lower, upper = bars.lines[2][0].get_segments()[0][:, 1]
                    np.testing.assert_allclose([lower, upper], bounds)
                    if mode in {"y_high_low", "y_plus_minus"}:
                        missing = "Y plus" if mode == "y_high_low" else "Y minus"
                        self.assertTrue(pd.isna(restored.frame()[missing].iloc[0]))

    def test_generated_coordinates_and_saved_views_round_trip(self):
        with TemporaryDirectory() as directory:
            directory = Path(directory)
            source = directory / "source.prism"
            with ZipFile(source, "w") as archive:
                def write(path, payload):
                    archive.writestr(path, json.dumps(payload))

                write("document.json", {"sheets": {"data": ["raw"], "analyses": ["fit"], "graphs": ["chart"]}})
                write("data/sheets/raw/sheet.json", {"title": "Raw", "table": {
                    "uid": "raw-table", "format": "column", "dataFormat": "y_single", "dataSets": ["raw-y"]}})
                write("data/sets/raw-y.json", {"title": "Values"})
                archive.writestr("data/tables/raw-table/data.csv", "1\n2\n")
                write("analyses/fit/sheet.json", {"title": "Original fit", "analysisClass": "UNKNOWN",
                                                 "resultSheets": [{"uid": "curve"}]})
                write("analyses/fit/result_sheets/curve.json", {"name": "Curve", "dataSheet": "curve-sheet"})
                write("data/sheets/curve-sheet/sheet.json", {"table": {
                    "uid": "curve-table", "format": "view", "dataFormat": "y_single", "xDataSetFormat": "series",
                    "xDataSet": "curve-x", "dataSets": ["curve-y"]}})
                write("data/sets/curve-x.json", {"title": "Dose", "replicates": [
                    {"@class": "SeriesReplicate", "startValue": .2, "interval": .4}]})
                write("data/sets/curve-y.json", {"title": "Treatment"})
                write("data/tables/curve-table/content.json", {"numberOfColumns": 1, "numberOfRows": 2})
                archive.writestr("data/tables/curve-table/data.csv", "1\n2\n")
                write("graphs/chart/sheet.json", {"title": "Original graph", "inputDataSets": ["curve-y"]})
            self.assertEqual(list(load_tables(source)), ["Raw"])
            tables = load_tables(source, restore_prism=True)
            self.assertIn("Prism result · Original fit · Curve", tables)
            self.assertIn("Recalculation unavailable", tables["Raw"].attrs["import_warnings"][0])
            project = directory / "roundtrip.alab"
            save_project(project, {name: Dataset(frame) for name, frame in tables.items()})
            restored = load_project(project)["Prism graph · Original graph"]
            method, settings = restored.analyses[0]
            self.assertEqual(method, SAVED_XY)
            self.assertEqual(settings[PRISM_TITLE], "Original graph")
            plot = analyse(method, restored.frame(), settings)
            axes = plot.figure.axes[0]
            self.assertEqual(axes.get_title(), "Original graph")
            self.assertEqual(axes.get_xlabel(), "Dose")
            self.assertAlmostEqual(axes.lines[0].get_xdata()[1], .6)
            self.assertEqual(list(axes.lines[0].get_ydata()), [1, 2])
