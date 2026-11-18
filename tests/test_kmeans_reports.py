"""The K-means report sheets must agree with the fitted partitions and preserve old recipes."""
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from analisi import advanced, kmeans_options as k, kmeans_reports as reports
from analisi.field_error import FieldError
from analisi.prism_recipes import restore_recipe
from analisi.workbench import analyse
from tests.test_prism_recipes import source, var


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
