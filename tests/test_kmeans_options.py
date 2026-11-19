"""Regression tests for Hartigan–Wong on full worksheet and Gap fitting paths."""
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from analisi import advanced, kmeans_options as option
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
        self.assertEqual(options["Criterion"], "Consensus (17 indices)")
        self.assertEqual(options["Krzanowski–Lai scaling"], "Unscaled WSS")
        tables = analyse(method, self.frame, options).tables
        self.assertEqual(tables["Selection"].loc["Suggested k", "Value"], 3)
        content["calc"]["distance"]["type"] = "MANHATTAN"
        self.assertIsNone(restore_recipe(sheet, parameters, frames))
