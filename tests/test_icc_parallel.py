"""Intraclass correlation: the subject bootstrap gives the same numbers with 1 and 4 real processes."""
import os
import threading
import time
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from analisi import icc, parallel


def study(subjects=900, raters=4, seed=3):
    rng = np.random.default_rng(seed)
    level = rng.normal(0, 3, size=(subjects, 1))
    return pd.DataFrame(level + rng.normal(0, 1, size=(subjects, raters)) + np.arange(raters) * .3,
                        columns=[f"R{i}" for i in range(raters)])


RECIPE = {"Raters": ["R0", "R1", "R2", "R3"], "Bootstrap CI": True, "Bootstrap replicates": 1500, "Seed": 2024}


class ParallelBootstrap(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.addClassCleanup(parallel.shutdown)
        environment = patch.dict(os.environ, {parallel.ENVIRONMENT: "4"})
        environment.start()
        cls.addClassCleanup(environment.stop)
        parallel.warm_up()
        end = time.monotonic() + 60
        while not parallel._pool.warm and time.monotonic() < end:
            time.sleep(.02)
        if not parallel._pool.warm:
            raise RuntimeError("The process pool did not start.")

    def test_one_and_four_processes_agree_exactly(self):
        frame = study()
        for definition, unit in (("Absolute agreement", "Single measure"), ("Consistency", "Mean of raters")):
            with self.subTest(definition=definition, unit=unit):
                recipe = {**RECIPE, "Definition": definition, "Unit": unit}
                with patch.dict(os.environ, {parallel.ENVIRONMENT: "1"}):
                    expected = icc.analyse(frame, recipe).tables
                with patch.object(parallel, "run_tasks", wraps=parallel.run_tasks) as executed:
                    actual = icc.analyse(frame, recipe).tables
                executed.assert_called_once()
                self.assertGreater(len(executed.call_args.args[1]), 1)
                for name in expected:
                    pd.testing.assert_frame_equal(actual[name], expected[name], check_exact=True)

    def test_cancel_while_the_workers_run(self):
        frame = study(subjects=1000)
        recipe = {**RECIPE, "Bootstrap replicates": 5000}
        cancel = threading.Event()
        timer = threading.Timer(.05, cancel.set)
        timer.start()
        started = time.monotonic()
        with self.assertRaises(icc.IccCancelled):
            icc.analyse(frame, recipe, cancel=cancel)
        self.assertLess(time.monotonic() - started, 5)
        timer.cancel()


if __name__ == "__main__":
    unittest.main()
