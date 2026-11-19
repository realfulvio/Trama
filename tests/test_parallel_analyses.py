"""Level 1: whole analyses computed by worker processes give the results of the serial batch."""
from copy import deepcopy
import io
import os
import time
import unittest

import numpy as np
import pandas as pd

from analisi import parallel
from analisi.field_error import FieldError
from analisi.i18n import set_language
from analisi.parallel_analyses import LOCAL_METHODS, analysis_task, precompute
from analisi.workbench import METHODS, analyse


def recipe(method, **options):
    """The dialog defaults of ``method`` with ``options`` on top."""
    found = {}
    for key, value in METHODS[method].items():
        if isinstance(value, tuple) and value:
            found[key] = value[0]
        elif isinstance(value, (bool, int, float)):
            found[key] = value
    return {**found, **options}


X = np.repeat(np.linspace(-9, -4, 8), 3)
Y = 5 + 95 / (1 + 10 ** ((-6.5 - X) * 1.1)) + np.sin(np.arange(len(X))) * 3
DOSE = pd.DataFrame({"X": X, "Y": Y, "Y2": Y[::-1].copy(), "Group": np.tile(["A", "B", "C"], 8)})
NONLINEAR = recipe("Nonlinear regression", **{"X": "X", "Y columns": ["Y", "Y2"], "Grouping variables": [],
                  "Model": "Logistic (4 parameters)", "Parameter intervals": "Profile likelihood"})
ANOVA = recipe("One-way ANOVA", Response="Y", Group="Group")
JOBS = [
    ("nonlinear", "Nonlinear regression", DOSE, NONLINEAR),
    ("anova", "One-way ANOVA", DOSE, ANOVA),
    ("correlation", "Correlation", DOSE, recipe("Correlation", X="X", Y="Y")),
    ("kmeans", "K-means model selection", DOSE, recipe("K-means model selection", Variables=["X", "Y"],
                                                         Criterion="Gap", **{"Maximum k": 4})),
    ("broken", "Nonlinear regression", DOSE, {**NONLINEAR, "Model": "No such model"}),
]
SUCCEEDING = {"nonlinear", "anova", "correlation", "kmeans"}


def png(figure):
    with io.BytesIO() as buffer:
        figure.savefig(buffer, format="png", dpi=40)
        return buffer.getvalue()


def serial(method, frame, options):
    try:
        return analyse(method, frame, deepcopy(options)), None
    except Exception as error:
        return None, error


class PrecomputeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.previous = os.environ.get(parallel.ENVIRONMENT)
        os.environ[parallel.ENVIRONMENT] = "3"

    @classmethod
    def tearDownClass(cls):
        parallel.shutdown()
        if cls.previous is None:
            os.environ.pop(parallel.ENVIRONMENT, None)
        else:
            os.environ[parallel.ENVIRONMENT] = cls.previous

    def test_results_match_the_serial_batch(self):
        options = [deepcopy(item[3]) for item in JOBS]
        found = precompute([(key, method, frame, option) for (key, method, frame, _), option in zip(JOBS, options)])
        self.assertEqual(set(found), {key for key, *_ in JOBS})
        self.assertEqual({key for key, outcome in found.items() if outcome.error is None}, SUCCEEDING)
        self.assertTrue(any(outcome.remote for outcome in found.values()))
        for (key, method, frame, original), option in zip(JOBS, options):
            with self.subTest(analysis=key):
                self.assertEqual(option, original, "options changed in place")
                expected, error = serial(method, frame, original)
                outcome = found[key]
                if error is not None:
                    self.assertIsNotNone(outcome.error)
                    self.assertIs(type(outcome.error), type(error))
                    self.assertEqual(str(outcome.error), str(error))
                    if isinstance(error, FieldError):
                        self.assertEqual(outcome.error.field, error.field)
                    continue
                self.assertIsNone(outcome.error)
                result = outcome.value
                self.assertEqual(list(result.tables), list(expected.tables))
                for name, table in expected.tables.items():
                    pd.testing.assert_frame_equal(result.tables[name], table, check_exact=True)
                self.assertEqual(result.figure is None, expected.figure is None)
                if expected.figure is not None:
                    self.assertEqual(png(result.figure), png(expected.figure))

    def test_workers_word_the_results_in_the_language_of_this_process(self):
        """Compare two variances titles its figure with ``tr``: a worker must use the language chosen here."""
        from analisi.variance_ratio import GRAPH, GRAPH_VARIANCE, LEVEL, METHOD
        frame = pd.DataFrame({"A": DOSE["Y"].to_numpy()[:12], "B": DOSE["Y2"].to_numpy()[:12] * 1.7})
        options = {"First": "A", "Second": "B", LEVEL: 95.0, "Distribution": "Normal", GRAPH: GRAPH_VARIANCE}
        english = analyse(METHOD, frame, deepcopy(options)).figure.axes[0].get_title()
        parallel.warm_up()
        deadline = time.monotonic() + 60
        while not parallel._pool.warm and time.monotonic() < deadline:
            time.sleep(0.05)
        set_language("it")
        try:
            found = precompute([(index, METHOD, frame, deepcopy(options)) for index in range(6)])
            expected = analyse(METHOD, frame, deepcopy(options))
        finally:
            set_language("en")
        italian = expected.figure.axes[0].get_title()
        # Constrained layout can shift a spine by a pixel between successive
        # renders. Render both figures once at the target DPI before comparing.
        png(expected.figure)
        expected_png = png(expected.figure)
        self.assertNotEqual(italian, english)
        self.assertTrue(any(outcome.remote for outcome in found.values()), "no analysis reached a worker")
        for outcome in found.values():
            self.assertIsNone(outcome.error)
            self.assertEqual(outcome.value.figure.axes[0].get_title(), italian)
            png(outcome.value.figure)
            self.assertEqual(png(outcome.value.figure), expected_png)
            for name, table in expected.tables.items():
                pd.testing.assert_frame_equal(outcome.value.tables[name], table, check_exact=True)

    def test_local_methods_and_small_batches_stay_in_this_process(self):
        self.assertEqual(precompute([("one", *JOBS[1][1:])]), {})
        jobs = [(method, method, DOSE, {}) for method in sorted(LOCAL_METHODS)]
        self.assertEqual(precompute(jobs), {})
        os.environ[parallel.ENVIRONMENT] = "1"
        try:
            self.assertEqual(precompute([(key, method, frame, options) for key, method, frame, options in JOBS]), {})
        finally:
            os.environ[parallel.ENVIRONMENT] = "3"

    def test_the_task_is_the_serial_call(self):
        result = analysis_task(("One-way ANOVA", DOSE, ANOVA))
        expected = analyse("One-way ANOVA", DOSE, ANOVA)
        self.assertEqual(list(result.tables), list(expected.tables))


if __name__ == "__main__":
    unittest.main()
