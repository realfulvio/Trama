import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from zipfile import ZipFile

import numpy as np
import pandas as pd

from analisi.data import Dataset, load_project, load_tables, save_project
from analisi.legacy_restore import LEGACY_TITLE, SAVED_XY
from analisi.workbench import analyse


class LegacyRestoreTests(unittest.TestCase):
    def test_grouped_anova_plot_keeps_replicates_in_their_factor_cells(self):
        from analisi.anova_grouped_plot import METHOD, observations

        model = pd.DataFrame({
            "response": [3., 1., 5., 8., 7.],
            "factor0": ["Low", "High", "High", "Low", "High"],
            "factor1": ["B", "A", "A", "A", "B"],
            "factor2": ["Normal", "Extra", "Extra", "Normal", "Extra"],
        })
        table = observations(model, ["Light", "Treatment", "Water"], "Treatment")
        self.assertEqual(list(table["Row title"]), ["High, Extra", "Low, Normal"])
        self.assertEqual(table.attrs["worksheet_roles"]["y"], [["A [1]", "A [2]"], ["B [1]", "B [2]"]])
        np.testing.assert_array_equal(table.iloc[:, 1:].to_numpy(dtype=float), [[1., 5., 7., np.nan],
                                                                                [8., np.nan, 3., np.nan]])
        axes, = analyse(METHOD, table, {}).figure.axes
        self.assertEqual([tick.get_text() for tick in axes.get_xticklabels()], list(table["Row title"]))

    def test_anova_comparison_plot_uses_absolute_interval_endpoints(self):
        from analisi.anova_comparison_plot import METHOD

        frame = pd.DataFrame({
            "Comparison": ["A$ − B", "A$ − C"], "Family": ["All", "All"],
            "Difference": [-5., 3.], "CI low": [-8., 1.], "CI high": [-1., 8.],
        })
        result = analyse(METHOD, frame, {})
        pd.testing.assert_frame_equal(result.tables["Comparison intervals"], frame)
        axes, = result.figure.axes
        self.assertEqual([tick.get_text() for tick in axes.get_yticklabels()], ["A$ − B", "A$ − C"])
        bars, = axes.containers
        segments = bars.lines[2][0].get_segments()
        np.testing.assert_array_equal([segment[:, 0] for segment in segments], [[-8., -1.], [1., 8.]])

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
                    tables = load_tables(source, restore_legacy=True)
                    project = Path(folder) / f"{mode}.alab"
                    save_project(project, {name: Dataset(frame) for name, frame in tables.items()})
                    restored = load_project(project)["Imported graph · Uncertainty"]
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
            tables = load_tables(source, restore_legacy=True)
            self.assertIn("Imported result · Original fit · Curve", tables)
            self.assertIn("Recalculation unavailable", tables["Raw"].attrs["import_warnings"][0])
            project = directory / "roundtrip.alab"
            save_project(project, {name: Dataset(frame) for name, frame in tables.items()})
            restored = load_project(project)["Imported graph · Original graph"]
            method, settings = restored.analyses[0]
            self.assertEqual(method, SAVED_XY)
            self.assertEqual(settings[LEGACY_TITLE], "Original graph")
            plot = analyse(method, restored.frame(), settings)
            axes = plot.figure.axes[0]
            self.assertEqual(axes.get_title(), "Original graph")
            self.assertEqual(axes.get_xlabel(), "Dose")
            self.assertAlmostEqual(axes.lines[0].get_xdata()[1], .6)
            self.assertEqual(list(axes.lines[0].get_ydata()), [1, 2])
