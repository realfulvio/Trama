"""Bland–Altman for repeated pairs: the subject bootstrap gives the same numbers with 1 and 4 real processes."""
import os
import threading
import time
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from analisi import bland_altman_repeated as bar, parallel


def study(subjects=120, pairs=4, seed=3):
    rng = np.random.default_rng(seed)
    rows = []
    for subject in range(subjects):
        offset = rng.normal(0, 1.5)
        for occasion in range(1 + subject % pairs):
            second = rng.normal(50, 10)
            rows.append({"Subject": f"S{subject:03}", "Occasion": occasion + 1,
                         "First": second + 2 + offset + rng.normal(0, 1), "Second": second})
    return pd.DataFrame(rows)


RECIPE = {"Subject": "Subject", "Occasion": "Occasion", "First": "First", "Second": "Second", "Mode": "Difference",
          "Coverage": 95, "Confidence intervals": "Subject bootstrap", "Bootstrap replicates": 4001, "Seed": 2024}


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
        for mode in ("Difference", "Log ratio"):
            with self.subTest(mode=mode):
                recipe = {**RECIPE, "Mode": mode}
                if mode == "Log ratio":
                    frame = frame.assign(First=frame["First"].abs() + 1, Second=frame["Second"].abs() + 1)
                with patch.dict(os.environ, {parallel.ENVIRONMENT: "1"}):
                    expected = bar.analyse(frame, recipe).tables
                with patch.object(parallel, "run_tasks", wraps=parallel.run_tasks) as executed:
                    actual = bar.analyse(frame, recipe).tables
                executed.assert_called_once()
                self.assertGreater(len(executed.call_args.args[1]), 1)
                for name in expected:
                    pd.testing.assert_frame_equal(actual[name], expected[name], check_exact=True)

    def test_cancel_while_the_workers_run(self):
        frame = study(subjects=400, pairs=8)
        recipe = {**RECIPE, "Bootstrap replicates": 20000}
        cancel = threading.Event()
        timer = threading.Timer(.05, cancel.set)
        timer.start()
        started = time.monotonic()
        with self.assertRaises(bar.BlandAltmanRepeatedCancelled):
            bar.analyse(frame, recipe, cancel=cancel)
        self.assertLess(time.monotonic() - started, 5)
        timer.cancel()


if __name__ == "__main__":
    unittest.main()
