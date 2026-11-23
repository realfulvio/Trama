"""The K-means report sheets must agree with the fitted partitions and preserve old recipes."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from zipfile import ZipFile

import numpy as np
import pandas as pd

from analisi import advanced, kmeans_options as k, kmeans_reports as reports
from analisi.analysis_chain import result_frame
from analisi.data import load_tables
from analisi.field_error import FieldError
from analisi.legacy_recipes import restore_recipe
from analisi.legacy_restore import LEGACY_TITLE, SAVED_XY
from analisi.workbench import analyse
from tests.test_legacy_recipes import source, var


class KmeansReportTests(unittest.TestCase):
    def setUp(self):
        self.frame = pd.DataFrame({"x": [0., 2., None, 10., 12.],
                                   "Batch": ["a", "b", "b", "a", "a"]}, index=[7, 9, 13, 18, 24])
        self.fit = {"Variables": ["x"], "Clusters": 2, "Standardize": False, "Seed": 42,
                    k.ALGORITHM: k.HARTIGAN, k.INITIAL_ROWS: "1, 4"}

    def test_single_fit_reports_hand_calculated_values_and_actual_initial_centers(self):
        options = {**self.fit, **dict.fromkeys(reports.COMMON, True)}
        result = analyse(k.CLUSTERING, self.frame, options)
        self.assertNotIn("Standardized observations", result.tables)
        np.testing.assert_array_equal(result.tables["Assigned distances"]["Distance (k=2)"], 1)
        np.testing.assert_array_equal(result.tables["Cluster details"]["Center"], [1, 11])
        np.testing.assert_array_equal(result.tables["Cluster details"]["N"], [2, 2])
        np.testing.assert_array_equal(result.tables["Cluster details"]["Within SS"], [2, 2])
        np.testing.assert_array_equal(result.tables["Initial centroids"]["Initial center"], [0, 10])
        anova = result.tables["Cluster ANOVA"].iloc[0]
        self.assertEqual([anova[field] for field in ("Between SS", "Within SS", "Total SS", "F")],
                         [100, 4, 104, 50])
        self.assertAlmostEqual(anova["Nominal p"], 1 - 5 / np.sqrt(26), places=14)
        self.assertIn("Descriptive", anova["Interpretation"])
        self.assertAlmostEqual(result.tables["Cluster variation"].loc[2, "Explained variation (%)"], 100 * 100 / 104)

    # The patched kmeans counts calls in this process: keep the scan in one process.
    @patch.dict("os.environ", {"TRAMA_PROCESSES": "1"})
    def test_opt_in_does_not_change_lloyd_fits_and_scan_reports_reuse_every_fit_once(self):
        options = {**self.fit, "Standardize": True, "Maximum k": 3, "Criterion": "Gap",
                   "Gap simulations": 5, k.ALGORITHM: k.LLOYD}
        old_result = analyse(k.SELECTION, self.frame, options)
        self.assertNotIn("Cluster details", old_result.tables)
        with patch.object(advanced, "kmeans", wraps=advanced.kmeans) as fit:
            result = analyse(k.SELECTION, self.frame, {**options, **dict.fromkeys(reports.SCAN, True)})
        self.assertEqual(fit.call_count, 3 + 5 * 3)
        self.assertEqual(sum(call.kwargs.get("retain_initial", False) for call in fit.call_args_list), 3)
        for name, old in old_result.tables.items():
            pd.testing.assert_frame_equal(result.tables[name], old)
        assignments = result.tables["Assignments by k"]
        self.assertEqual(assignments.index.tolist(), self.frame.index.tolist())
        self.assertEqual(assignments["Batch"].tolist(), self.frame["Batch"].tolist())
        self.assertTrue(assignments.loc[13, ["Cluster (k=1)", "Cluster (k=2)", "Cluster (k=3)"]].isna().all())
        self.assertEqual(result.tables["Cluster details"]["k"].value_counts().sort_index().tolist(), [1, 2, 3])
        self.assertEqual(result.tables["Initial centroids"]["k"].value_counts().sort_index().tolist(), [1, 2, 3])
        gap = result.tables["Gap statistics"]
        np.testing.assert_allclose(gap["Mean log WSS reference"] - gap["Log WSS observed"], gap["Gap"])
        fitting_data = result.tables["Standardized observations"]
        self.assertAlmostEqual(float(fitting_data.x.mean()), 0)
        self.assertAlmostEqual(float(fitting_data.x.std(ddof=1)), 1)
        distances = result.tables["Assigned distances"]
        self.assertEqual(distances.index.tolist(), [7, 9, 18, 24])
        for count in (1, 2, 3):
            self.assertAlmostEqual(float((distances[f"Distance (k={count})"]**2).sum()),
                                   result.tables["Model metrics"].loc[count, "WSS"])

    def test_invalid_boolean_is_report_specific_and_degenerate_flat_report_is_descriptive(self):
        with self.assertRaises(FieldError) as caught:
            analyse(k.CLUSTERING, self.frame, {**self.fit, reports.ANOVA: "true"})
        self.assertEqual(caught.exception.field, reports.ANOVA)
        options = {**self.fit, "Clusters": 1, k.ALGORITHM: k.LLOYD, reports.ANOVA: True}
        result = analyse(k.CLUSTERING, pd.DataFrame({"x": [4., 4., 4.]}), options)
        self.assertTrue(result.tables["Cluster ANOVA"]["Nominal p"].isna().all())
        self.assertTrue(result.tables["Cluster variation"]["Explained variation (%)"].isna().all())

    # The patched kmeans counts calls in this process: keep the scan in one process.
    @patch.dict("os.environ", {"TRAMA_PROCESSES": "1"})
    def test_diagnostic_panels_reuse_consensus_fits_metrics_and_gap_uncertainty(self):
        options = {**self.fit, "Maximum k": 3, "Criterion": "Consensus (17 indices)", "Gap simulations": 5,
                   "Show WSS plot": True, "Show silhouette plot": True, "Show Gap plot": True}
        with patch.object(advanced, "kmeans", wraps=advanced.kmeans) as fit:
            result = analyse(k.SELECTION, self.frame, options)
        self.assertEqual(fit.call_count, 3 + 5 * 3)
        self.assertEqual(len(result.figure.axes), 4)
        self.assertEqual(result.figure.axes[0].get_title(), "K-means consensus votes")
        metrics = result.tables["Cluster metrics"]
        for panel, column in zip(result.figure.axes[1:], ("WSS", "Silhouette", "Gap"), strict=True):
            np.testing.assert_array_equal(panel.lines[0].get_xdata(), metrics.index)
            np.testing.assert_allclose(panel.lines[0].get_ydata(), metrics[column], equal_nan=True)
        intervals = result.figure.axes[3].containers[0].lines[2][0].get_segments()
        for index, segment in zip(metrics.index, intervals, strict=True):
            value, error = metrics.loc[index, ["Gap", "Gap SE"]]
            np.testing.assert_allclose(segment[:, 1], [value - error, value + error])

    def test_gap_plot_adds_references_without_changing_the_silhouette_choice(self):
        options = {**self.fit, "Maximum k": 3, "Criterion": "Silhouette", "Gap simulations": 5}
        old = analyse(k.SELECTION, self.frame, options)
        result = analyse(k.SELECTION, self.frame, {**options, "Show silhouette plot": True, "Show Gap plot": True})
        pd.testing.assert_frame_equal(result.tables["Selection"], old.tables["Selection"])
        pd.testing.assert_frame_equal(result.tables["Model metrics"][old.tables["Model metrics"].columns],
                                      old.tables["Model metrics"])
        self.assertEqual(len(result.figure.axes), 2)
        self.assertIn("Gap", result.tables["Model metrics"])
        self.assertEqual(len(old.figure.axes), 1)

    def test_linked_metric_uses_only_the_current_scan_and_keeps_gap_intervals(self):
        options = {**self.fit, "Maximum k": 3, "Criterion": "Silhouette", "Gap simulations": 5}
        scan = analyse(k.SELECTION, self.frame, {**options, k.GAP_PLOT: True})
        linked = result_frame(scan, "Selection")
        metrics = scan.tables["Model metrics"]
        with patch("analisi.workbench.kmeans_scan", side_effect=AssertionError("Unexpected second fit")):
            for metric in ("WSS", "Silhouette", "Gap"):
                with self.subTest(metric=metric):
                    view = analyse(reports.MODEL_GRAPH, linked, {reports.METRIC: metric})
                    axes, = view.figure.axes
                    pd.testing.assert_series_equal(view.tables["Plot values"][metric], metrics[metric])
                    np.testing.assert_array_equal(axes.lines[0].get_xdata(), metrics.index)
                    self.assertTrue(all(tick == int(tick) for tick in axes.get_xticks()))
                    if metric == "Gap":
                        segments = axes.containers[0].lines[2][0].get_segments()
                        for k_value, segment in zip(metrics.index, segments, strict=True):
                            value, error = metrics.loc[k_value, ["Gap", "Gap SE"]]
                            np.testing.assert_allclose(segment, [[k_value, value - error], [k_value, value + error]])
        no_gap = result_frame(analyse(k.SELECTION, self.frame, options), "Selection")
        for frame in (self.frame, no_gap):
            with self.assertRaises(FieldError) as failure:
                analyse(reports.MODEL_GRAPH, frame, {reports.METRIC: "Gap"})
            self.assertEqual(failure.exception.field, reports.METRIC)

    @patch.dict("os.environ", {"TRAMA_PROCESSES": "1"})
    def test_model_selection_and_wss_use_integer_ticks_for_narrow_ranges(self):
        frame = pd.DataFrame({"x": [0., .2, .4, 2., 2.4, 3., 8., 8.5, 9.]})
        for minimum, maximum in ((2, 4), (3, 3)):
            with self.subTest(minimum=minimum, maximum=maximum):
                options = {"Variables": ["x"], "Standardize": False, "Seed": 42, "Criterion": "Silhouette",
                           "Minimum k": minimum, "Maximum k": maximum, "Show WSS plot": True}
                result = analyse(k.SELECTION, frame, options)
                self.assertEqual(len(result.figure.axes), 2)
                for axes in result.figure.axes:
                    ticks = axes.get_xticks()
                    self.assertIn(3, ticks)
                    np.testing.assert_array_equal(ticks, np.rint(ticks))

    def test_import_only_links_the_graph_matching_the_result_sheet_identity(self):
        parameters = {
            "data": {"variables": [var("signal")]},
            "calc": {"algorithm": "HARTIGAN_WONG", "transform": "STANDARDIZE",
                     "distance": {"type": "EUCLIDIAN"}, "clusterMetrics": True,
                     "clusterCount": {"min": 1, "max": 3}, "maxIterCount": 10, "randomSeed": {"value": 42}},
            "graph": {"elbowPlot": True},
        }
        sheet, recipe, _ = source("K_MEANS_CLUSTERING", "0.0.0", parameters, self.frame, {"signal": ["x"]})
        with TemporaryDirectory() as directory:
            path = Path(directory) / "metrics.prismt"
            with ZipFile(path, "w") as archive:
                def write(name, value):
                    archive.writestr(name, json.dumps(value))

                write("document.json", {"sheets": {"data": ["source"], "analyses": ["fit"],
                                                 "graphs": ["elbow", "unrelated"]}})
                write("data/sheets/source/sheet.json", {"title": "Signal", "table": {
                    "uid": "input", "format": "multivariable", "dataFormat": "y_single", "dataSets": ["signal"]}})
                write("analyses/fit/sheet.json", {**sheet, "title": "Clustering", "resultSheets": [{"uid": "view"}]})
                write("analyses/fit/parameters.json", recipe)
                write("analyses/fit/result_sheets/view.json", {"name": "Elbow plot", "dataSheet": "scores", "graphId": 2})
                write("data/sheets/scores/sheet.json", {"table": {
                    "uid": "scores", "format": "view", "dataFormat": "y_single", "xDataSet": "count",
                    "dataSets": ["wss"]}})
                for uid, title in (("signal", "x"), ("count", "Number of clusters"), ("wss", "WCSS")):
                    write(f"data/sets/{uid}.json", {"title": title})
                archive.writestr("data/tables/input/data.csv", "0\n2\n10\n12\n")
                archive.writestr("data/tables/scores/data.csv", "1,104\n2,4\n3,2\n")
                for uid, graph_id, title in (("elbow", 2, "Linked"), ("unrelated", 3, "Snapshot")):
                    write(f"graphs/{uid}/sheet.json", {"uid": uid, "fenID": graph_id, "title": title,
                                                      "inputDataSets": ["wss"]})
            tables = load_tables(path, restore_legacy=True)
        fitted = tables["Signal"]
        (method, options), (view_method, view_options) = fitted.attrs["legacy_recipes"]
        self.assertEqual((method, view_method), (k.SELECTION, reports.MODEL_GRAPH))
        self.assertEqual((view_options[reports.METRIC], view_options[LEGACY_TITLE]), ("WSS", "Linked"))
        link = fitted.attrs["legacy_analysis_sources"][1]
        self.assertEqual((link.analysis_id, link.table), (fitted.attrs["legacy_analysis_ids"][0], "Selection"))
        archived = tables["Imported result · Clustering · Elbow plot"]
        self.assertEqual(archived["WCSS"].tolist(), [104, 4, 2])
        self.assertNotIn("Imported graph · Linked", tables)
        self.assertEqual(tables["Imported graph · Snapshot"].attrs["legacy_recipes"][0][0], SAVED_XY)

    def test_archive_restores_flags_for_reports_on_editable_recipe(self):
        content = {"data": {"variables": [var("signal")]},
                   "calc": {"algorithm": "HARTIGAN_WONG", "transform": "STANDARDIZE",
                            "distance": {"type": "EUCLIDIAN"}, "clusterMetrics": True,
                            "clusterCount": {"min": 1, "max": 3}, "maxIterCount": 10,
                            "randomSeed": {"value": 42}},
                   "report": {"clusterDetails": True, "transformedData": True, "distances": True,
                              "initialCentroids": True, "anovaTable": False},
                   "graph": {"elbowPlot": True, "silhouettePlot": True, "gapPlot": True}}
        sheet, parameters, frames = source("K_MEANS_CLUSTERING", "0.0.0", content, self.frame,
                                            {"signal": ["x"]})
        _, method, options = restore_recipe(sheet, parameters, frames)
        self.assertEqual(method, k.SELECTION)
        self.assertTrue(all(options.get(flag) for flag in ("Show WSS plot", "Show silhouette plot", "Show Gap plot")))
        self.assertEqual(reports.requested(options, scan=True), set(reports.SCAN) - {reports.ANOVA})
        result = analyse(method, self.frame, options).tables
        self.assertNotIn("Cluster ANOVA", result)
        self.assertEqual(len(result["Assignments by k"]), len(self.frame))
        self.assertEqual(len(result["Assigned distances"]), len(self.frame) - 1)
