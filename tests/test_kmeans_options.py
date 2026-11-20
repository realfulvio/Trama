"""Regression tests for Hartigan–Wong on full worksheet and Gap fitting paths."""
import unittest
from threading import Event
from unittest.mock import patch

import numpy as np
import pandas as pd

from analisi import advanced, kmeans_options as option, kmeans_reports
from analisi.analysis_chain import ChainCancelled
from analisi.field_error import FieldError
from analisi.workbench import analyse
from analisi.prism_recipes import restore_recipe
from tests.test_prism_recipes import source, var


class KmeansOptionsTests(unittest.TestCase):
    def setUp(self):
        self.frame = pd.DataFrame({"x": [0., 1., None, 2., 9., 10., 11., 19., 20., 21.]},
                                  index=range(100, 110))
        self.options = {"Variables": ["x"], "Clusters": 3, "Standardize": False, "Seed": 42,
                        option.ALGORITHM: option.HARTIGAN, option.INITIAL_ROWS: "1, 5, 8"}

    def test_initial_rows_refer_to_worksheet_positions_before_excluding_incomplete_rows(self):
        result = analyse(option.CLUSTERING, self.frame, self.options).tables
        self.assertEqual(result["Fit"].loc["Within-cluster SS", "Value"], 6)
        np.testing.assert_array_equal(result["Centers (fitting scale)"]["x"], [1, 10, 20])
        self.assertEqual(result["Assignments"].index.tolist(), [100, 101, 103, 104, 105, 106, 107, 108, 109])
        self.assertEqual(result["Fit"].loc[option.ALGORITHM, "Value"], option.HARTIGAN)

    def test_invalid_fit_settings_keep_the_field_identity(self):
        mappings = (
            (option.ALGORITHM, "other"), (option.MAX_ITERATIONS, float("nan")),
            (option.INITIALIZATION, "other"),
            (option.MAX_ITERATIONS, 1001), (option.INITIAL_ROWS, "1, 1, 8"),
            (option.INITIAL_ROWS, "1, 3, 8"), (option.INITIAL_ROWS, "1, 5, 11"),
        )
        for field, invalid in mappings:
            with self.subTest(field=field, value=invalid), self.assertRaises(FieldError) as failure:
                analyse(option.CLUSTERING, self.frame, {**self.options, field: invalid})
            self.assertEqual(failure.exception.field, field)

    def test_iteration_limit_on_the_worker_names_the_recoverable_field(self):
        options = {**self.options, option.INITIAL_ROWS: "1, 2, 4", option.MAX_ITERATIONS: 1}
        with self.assertRaises(FieldError) as failure:
            analyse(option.CLUSTERING, self.frame, options)
        self.assertEqual(failure.exception.field, option.MAX_ITERATIONS)

    def test_seeded_kmeans_plus_plus_invokes_one_fit_and_reports_the_selected_rows(self):
        from analisi import hartigan_wong

        options = {**self.options, option.INITIAL_ROWS: "", option.INITIALIZATION: option.KMEANS_PLUS_PLUS,
                   kmeans_reports.CENTROIDS: True}
        with patch.object(hartigan_wong, "fit_hartigan_wong", wraps=hartigan_wong.fit_hartigan_wong) as fit:
            result = analyse(option.CLUSTERING, self.frame, options).tables
        self.assertEqual(fit.call_count, 1)
        np.testing.assert_array_equal(fit.call_args.args[1], [0, 6, 5])
        np.testing.assert_array_equal(result["Initial centroids"]["Initial center"], [0., 19., 11.])
        self.assertEqual(result["Fit"].loc[option.INITIALIZATION, "Value"], option.KMEANS_PLUS_PLUS)
        explicit = analyse(option.CLUSTERING, self.frame, {**options, option.INITIAL_ROWS: "1, 5, 8"}).tables
        np.testing.assert_array_equal(explicit["Initial centroids"]["Initial center"], [0., 9., 19.])

    def test_plus_plus_can_select_distinct_rows_when_squared_distances_underflow(self):
        frame = pd.DataFrame({"x": [0., 1e-200, 1.]})
        options = {**self.options, option.INITIAL_ROWS: "", option.INITIALIZATION: option.KMEANS_PLUS_PLUS,
                   kmeans_reports.CENTROIDS: True}
        tables = analyse(option.CLUSTERING, frame, options).tables
        np.testing.assert_array_equal(np.sort(tables["Initial centroids"]["Initial center"]), frame["x"])

    @patch.dict("os.environ", {"TRAMA_PROCESSES": "1"})
    def test_seeded_kmeans_plus_plus_reaches_observed_and_reference_fits(self):
        options = {**self.options, "Criterion": "Gap", "Maximum k": 4, "Gap simulations": 5,
                   option.INITIALIZATION: option.KMEANS_PLUS_PLUS, kmeans_reports.CENTROIDS: True}
        with patch.object(advanced, "kmeans", wraps=advanced.kmeans) as fit:
            result = analyse(option.SELECTION, self.frame, options).tables
        self.assertEqual(fit.call_count, 24)
        self.assertTrue(all(call.kwargs["kmeans_plus_plus"] for call in fit.call_args_list))
        repeated = analyse(option.SELECTION, self.frame, {**options, "Minimum k": 3}).tables
        centers = result["Initial centroids"]
        pd.testing.assert_frame_equal(centers.query("k >= 3").reset_index(drop=True),
                                      repeated["Initial centroids"], check_exact=True)

    def test_centering_reports_the_fit_scale_and_preserves_raw_assignments(self):
        frame = pd.DataFrame({"x": [0., 2., None, 10., 12.], "Constant": [1.1] * 5})
        settings = {"Variables": ["x", "Constant"], "Clusters": 2, "Seed": 42,
                    option.ALGORITHM: option.HARTIGAN, option.INITIAL_ROWS: "1, 4",
                    kmeans_reports.SCALED: True, kmeans_reports.DISTANCES: True}
        legacy = analyse(option.CLUSTERING, frame, {**settings, "Standardize": False}).tables
        centered = analyse(option.CLUSTERING, frame, {**settings, option.SCALE: option.CENTERED}).tables
        pd.testing.assert_frame_equal(legacy["Assignments"], centered["Assignments"])
        observed = centered["Centered observations"]
        np.testing.assert_array_equal(observed.to_numpy(), [[-6., 0.], [-4., 0.], [4., 0.], [6., 0.]])
        np.testing.assert_array_equal(centered["Centers (fitting scale)"].to_numpy(), [[-5., 0.], [5., 0.]])
        np.testing.assert_array_equal(centered["Assigned distances"]["Distance (k=2)"], [1.] * 4)
        self.assertEqual(centered["Fit"].loc["Within-cluster SS", "Value"], 4.)
        with self.assertRaises(FieldError) as failure:
            analyse(option.CLUSTERING, frame, {**settings, option.SCALE: "unknown"})
        self.assertEqual(failure.exception.field, option.SCALE)

    @patch.dict("os.environ", {"TRAMA_PROCESSES": "1"})
    def test_centered_scan_uses_the_centered_values_for_gap_and_metrics(self):
        frame = self.frame.dropna()
        reference = frame - frame.mean()
        settings = {"max_k": 4, "criterion": "gap", "gap_replicates": 5, "algorithm": "hartigan-wong",
                    "retain_fits": True, "retain_initial": True}
        expected = advanced.kmeans_scan(reference, ["x"], **settings)
        result = advanced.kmeans_scan(frame, ["x"], column_scale="center", **settings)
        pd.testing.assert_frame_equal(result.fitting_data, reference, check_exact=True)
        pd.testing.assert_frame_equal(result.metrics, expected.metrics, check_exact=True)
        np.testing.assert_array_equal(result.report_fits[3].initial_centers, expected.report_fits[3].initial_centers)

    # The patched kmeans counts calls in this process: keep the scan in one process.
    @patch.dict("os.environ", {"TRAMA_PROCESSES": "1"})
    def test_gap_reference_uses_the_same_algorithm_and_limit_as_observed_fits(self):
        options = {**self.options, "Criterion": "Gap", "Maximum k": 4, "Gap simulations": 5,
                   option.MAX_ITERATIONS: 23}
        with patch.object(advanced, "kmeans", wraps=advanced.kmeans) as fit:
            result = analyse(option.SELECTION, self.frame, options).tables
        self.assertEqual(fit.call_count, 24)
        for call in fit.call_args_list:
            self.assertEqual(call.kwargs["algorithm"], "hartigan-wong")
            self.assertEqual(call.kwargs["max_iterations"], 23)
            self.assertNotIn("initial_rows", call.kwargs)
        self.assertTrue(np.isfinite(result["Model metrics"]["Gap"]).all())
        self.assertEqual(result["Selection"].loc[option.ALGORITHM, "Value"], option.HARTIGAN)

    def test_saved_cluster_scan_recovers_algorithm_limits_and_mode(self):
        content = {
            "data": {"variables": [var("signal")]},
            "calc": {"algorithm": "HARTIGAN_WONG", "transform": "STANDARDIZE",
                     "distance": {"type": "EUCLIDIAN", "value": 2.},
                     "clusterMetrics": True, "clusterCount": {"min": 1, "max": 4},
                     "maxIterCount": 10, "randomSeed": {"type": "AUTO", "value": 53273}},
        }
        sheet, parameters, frames = source("K_MEANS_CLUSTERING", "0.0.0", content, self.frame,
                                            {"signal": ["x"]})
        uid, method, options = restore_recipe(sheet, parameters, frames)
        self.assertEqual((uid, method), ("source", option.SELECTION))
        self.assertEqual(options["Variables"], ["x"])
        self.assertEqual((options["Seed"], options["Minimum k"], options["Maximum k"]), (53273, 1, 4))
        self.assertEqual(options[option.MAX_ITERATIONS], 10)
        self.assertEqual(options[option.ALGORITHM], option.HARTIGAN)
        self.assertNotIn(option.INITIALIZATION, options)
        self.assertEqual(options[option.SCALE], option.STANDARDIZED)
        self.assertEqual(options["Criterion"], "Consensus (17 indices)")
        self.assertEqual(options["Krzanowski–Lai scaling"], "Unscaled WSS")
        self.assertEqual(options[option.GAP_REFERENCE], option.GAP_PRINCIPAL_AXES)
        self.assertEqual(options["Gap simulations"], 100)
        tables = analyse(method, self.frame, options).tables
        self.assertEqual(tables["Selection"].loc["Suggested k", "Value"], 3)
        content["calc"]["algorithm"] = "MACQUEEN"
        content["calc"]["maxIterCount"] = 50
        uid, method, restored = restore_recipe(sheet, parameters, frames)
        self.assertEqual((uid, method), ("source", option.SELECTION))
        self.assertEqual(restored[option.ALGORITHM], option.MACQUEEN)
        self.assertEqual(restored[option.MACQUEEN_ITERATIONS], 50)
        self.assertNotIn(option.MAX_ITERATIONS, restored)
        self.assertIn("saved MacQueen settings", restored["Prism import notes"])
        selection = analyse(method, self.frame, restored).tables["Selection"]
        self.assertEqual(selection.loc[option.ALGORITHM, "Value"], option.MACQUEEN)
        content["report"] = {"transformedData": True}
        for saved, expected, table in (("CENTER", option.CENTERED, "Centered observations"),
                                       ("NONE", option.UNSCALED, None)):
            with self.subTest(saved=saved):
                content["calc"]["transform"] = saved
                _, method, restored = restore_recipe(sheet, parameters, frames)
                self.assertEqual(restored[option.SCALE], expected)
                tables = analyse(method, self.frame, restored).tables
                self.assertNotIn("Standardized observations", tables)
                if table:
                    self.assertIn(table, tables)
                else:
                    self.assertNotIn("Centered observations", tables)
        content["calc"]["distance"]["type"] = "MANHATTAN"
        self.assertIsNone(restore_recipe(sheet, parameters, frames))

    def test_forgy_lloyd_uses_the_requested_number_of_batch_updates(self):
        frame = pd.DataFrame({"x": [0., 2., 3., 4., 10.]})
        settings = {"Variables": ["x"], "Clusters": 2, "Seed": 42, option.SCALE: option.UNSCALED,
                    option.ALGORITHM: option.FORGY_LLOYD, option.LLOYD_ITERATIONS: 1,
                    option.INITIAL_ROWS: "1, 2", kmeans_reports.CENTROIDS: True}
        first = analyse(option.CLUSTERING, frame, settings).tables
        second = analyse(option.CLUSTERING, frame, {**settings, option.LLOYD_ITERATIONS: 2}).tables
        self.assertEqual(first["Assignments"]["Cluster"].tolist(), [1, 2, 2, 2, 2])
        self.assertEqual(second["Assignments"]["Cluster"].tolist(), [1, 1, 2, 2, 2])
        np.testing.assert_allclose(first["Centers (fitting scale)"]["x"], [0, 4.75])
        np.testing.assert_allclose(second["Centers (fitting scale)"]["x"], [1, 17 / 3])
        self.assertEqual(first["Fit"].loc[option.LLOYD_ITERATIONS, "Value"], 1)

    def test_saved_forgy_lloyd_opens_as_an_editable_scan(self):
        content = {"data": {"variables": [var("signal")]},
                   "calc": {"algorithm": "LLOYD_FORGY", "transform": "CENTER",
                            "distance": {"type": "EUCLIDIAN", "value": 2.},
                            "clusterMetrics": True, "clusterCount": {"min": 2, "max": 4},
                            "maxIterCount": 12, "randomSeed": {"type": "AUTO", "value": 42}},
                   "report": {"initialCentroids": True}}
        sheet, parameters, frames = source("K_MEANS_CLUSTERING", "0.0.0", content, self.frame,
                                            {"signal": ["x"]})
        recovered = restore_recipe(sheet, parameters, frames)
        self.assertIsNotNone(recovered)
        uid, method, settings = recovered
        self.assertEqual((uid, method), ("source", option.SELECTION))
        self.assertEqual(settings[option.ALGORITHM], option.FORGY_LLOYD)
        self.assertEqual(settings[option.LLOYD_ITERATIONS], 12)
        self.assertEqual(settings[option.SCALE], option.CENTERED)
        self.assertTrue(settings[kmeans_reports.CENTROIDS])
        first = analyse(method, self.frame, settings).tables
        second = analyse(method, self.frame, {**settings, "Minimum k": 3}).tables
        centers = first["Initial centroids"]
        self.assertEqual(first["Selection"].loc[option.LLOYD_ITERATIONS, "Value"], 12)
        start_two = centers.loc[centers["k"] == 2, "Initial center"]
        start_three = centers.loc[centers["k"] == 3, "Initial center"]
        np.testing.assert_array_equal(start_two, start_three.iloc[:2])
        np.testing.assert_allclose(start_three + self.frame["x"].mean(), [0, 19, 11])
        pd.testing.assert_frame_equal(centers[centers["k"] == 3].reset_index(drop=True),
                                      second["Initial centroids"].query("k == 3").reset_index(drop=True))

    def test_selected_gap_geometry_is_recorded_and_validated(self):
        options = {**self.options, "Criterion": "Gap", "Maximum k": 4, "Gap simulations": 5,
                   option.GAP_REFERENCE: option.GAP_PRINCIPAL_AXES}
        result = analyse(option.SELECTION, self.frame, options)
        self.assertEqual(result.tables["Selection"].loc[option.GAP_REFERENCE, "Value"], option.GAP_PRINCIPAL_AXES)
        self.assertEqual(result.tables["Selection"].loc["Gap simulations", "Value"], 5)
        with self.assertRaises(FieldError) as caught:
            analyse(option.SELECTION, self.frame, {**options, option.GAP_REFERENCE: "unknown"})
        self.assertEqual(caught.exception.field, option.GAP_REFERENCE)

    @patch.dict("os.environ", {"TRAMA_PROCESSES": "1"})
    def test_cancelling_gap_stops_before_the_next_fit(self):
        cancel = Event()
        fits = []
        original = advanced.kmeans

        def fit(*args, **kwargs):
            fits.append(args[2])
            result = original(*args, **kwargs)
            if len(fits) == 3:  # two observed fits and one reference fit
                cancel.set()
            return result

        options = {**self.options, "Criterion": "Gap", "Maximum k": 2, "Gap simulations": 5}
        with patch.object(advanced, "kmeans", side_effect=fit), self.assertRaises(ChainCancelled):
            analyse(option.SELECTION, self.frame, options, cancel=cancel)
        self.assertEqual(fits, [1, 2, 1])
