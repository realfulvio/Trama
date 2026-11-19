"""Seeded arrays and cancellation when recomputed in real spawned workers."""
import os
import threading
import time
import unittest
from unittest.mock import patch

import pandas as pd

from analisi import independent_roc, mean_permutation, monte_carlo, parallel
from tests.test_independent_roc import COHORTS, bootstrap
from tests.test_monte_carlo import SOURCE, WELCH


class ParallelResamplingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.addClassCleanup(parallel.shutdown)
        environment = patch.dict(os.environ, {parallel.ENVIRONMENT: "2"})
        environment.start()
        cls.addClassCleanup(environment.stop)
        parallel.warm_up()
        end = time.monotonic() + 30
        while not parallel._pool.warm and time.monotonic() < end:
            time.sleep(.02)
        if not parallel._pool.warm:
            raise RuntimeError("The process pool did not start.")

    def check_result(self, function, frame, options):
        with patch.dict(os.environ, {parallel.ENVIRONMENT: "1"}):
            expected = function(frame, options).tables
        with patch.object(parallel, "run_tasks", wraps=parallel.run_tasks) as executed:
            actual = function(frame, options).tables
        executed.assert_called_once()
        self.assertEqual(list(actual), list(expected))
        for name in actual:
            pd.testing.assert_frame_equal(actual[name], expected[name], check_exact=True)

    def test_monte_carlo_results_and_progress(self):
        options = {**WELCH, "Replicates": 8501, "N A": 110, "N B": 110}
        self.check_result(monte_carlo.monte_carlo, SOURCE, options)
        cancel = threading.Event()
        calls = []

        def progress(done, total):
            calls.append((done, total))
            cancel.set()

        with self.assertRaises(monte_carlo.MonteCarloCancelled):
            monte_carlo.monte_carlo(SOURCE, options, progress=progress, cancel=cancel)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1], options["Replicates"])

    def test_roc_bootstrap_keeps_the_legacy_draw_order(self):
        options = bootstrap(**{"Bootstrap replicates": 6001, "Area": "Partial", "Maximum FPR": .4})
        frame = pd.concat([COHORTS] * 20, ignore_index=True)
        self.check_result(independent_roc.independent_roc, frame, options)

    def test_paired_permutations_keep_every_legacy_draw(self):
        size = 501
        frame = pd.DataFrame({"A": range(size), "B": [(row * 71) % 389 for row in range(size)]})
        self.check_result(mean_permutation.permutation_test, frame,
                          {"First": "A", "Second": "B", "Design": "Paired", "Method": "Monte Carlo",
                           "Resamples": 22003, "Seed": 16, "Keep draws": True, "Show graph": False})
