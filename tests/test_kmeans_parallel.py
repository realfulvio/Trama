"""K-means scans on several processes: the numbers and the failures of the serial scan."""
import os
import unittest
from unittest import mock

import numpy as np
import pandas as pd

from analisi import advanced, parallel
from analisi.advanced import kmeans_scan


RNG = np.random.default_rng(11)
FRAME = pd.DataFrame(np.vstack([RNG.normal(center, 1, size=(40, 3)) for center in (0, 4, 8)]),
                     columns=["a", "b", "c"])


def scan(processes, **options):
    previous = os.environ.get(parallel.ENVIRONMENT)
    os.environ[parallel.ENVIRONMENT] = str(processes)
    try:
        return kmeans_scan(FRAME, ["a", "b", "c"], standardize=True, seed=7, retain_fits=True, **options)
    finally:
        if previous is None:
            os.environ.pop(parallel.ENVIRONMENT, None)
        else:
            os.environ[parallel.ENVIRONMENT] = previous


def legacy_gap(metrics, values, columns, seed, replicates, *, allow_failed_references=False, fit_options):
    """The 0.93 loop, kept here as the reference for the order of failures."""
    metrics["Gap"] = np.nan
    metrics["Gap SE"] = np.nan
    eligible = metrics.index[(metrics.index < len(values)) & (metrics["WSS"] > 0)]
    if eligible.empty:
        return
    low, high = values.min(axis=0), values.max(axis=0)
    rng = np.random.default_rng(seed)
    reference_wss = np.full((replicates, len(eligible)), np.nan)
    failed = set()
    for replica in range(replicates):
        reference = pd.DataFrame(rng.uniform(low, high, size=values.shape), columns=columns)
        for index, count in enumerate(eligible):
            if index in failed:
                continue
            try:
                inertia = advanced.kmeans(reference, columns, count, seed=seed, **fit_options).inertia
            except ValueError:
                if not allow_failed_references:
                    raise
                failed.add(index)
                continue
            if allow_failed_references and (not np.isfinite(inertia) or inertia <= 0):
                failed.add(index)
            else:
                reference_wss[replica, index] = inertia
    valid = (reference_wss > 0).all(axis=0)
    counts = eligible[valid]
    log_reference = np.log(reference_wss[:, valid])
    metrics.loc[counts, "Gap"] = log_reference.mean(axis=0) - np.log(metrics.loc[counts, "WSS"])
    metrics.loc[counts, "Gap SE"] = log_reference.std(axis=0) * np.sqrt(1 + 1 / replicates)


class ParallelScanTests(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        parallel.shutdown()

    def assertSameScan(self, serial, found):
        pd.testing.assert_frame_equal(found.metrics, serial.metrics, check_exact=True)
        self.assertEqual(found.recommended_k, serial.recommended_k)
        self.assertEqual(sorted(found.report_fits), sorted(serial.report_fits))
        for k, fit in serial.report_fits.items():
            pd.testing.assert_series_equal(found.report_fits[k].labels, fit.labels, check_exact=True)
            self.assertEqual(found.report_fits[k].inertia, fit.inertia)

    def test_every_criterion_and_algorithm_is_identical(self):
        for algorithm in ("lloyd", "hartigan-wong", "macqueen"):
            for criterion in ("silhouette", "gap", "consensus"):
                with self.subTest(algorithm=algorithm, criterion=criterion):
                    options = dict(max_k=6, criterion=criterion, gap_replicates=6, algorithm=algorithm,
                                   max_iterations=100 if algorithm == "macqueen" else 10)
                    self.assertSameScan(scan(1, **options), scan(3, **options))

    def test_reference_failures_follow_the_serial_order(self):
        """A tolerated failure is skipped in later replicates; a fatal one is the first in replicate order."""
        real = advanced.kmeans

        def flaky(frame, columns, count, *args, **kwargs):
            # Depends only on the reference set and k, never on the call order.
            first = float(frame.to_numpy()[0, 0])
            if count == 4 and first > 0 or count == 3 and first < -0.5:
                raise ValueError(f"reference fit k={count} failed ({first:.3f})")
            return real(frame, columns, count, *args, **kwargs)

        values = ((FRAME - FRAME.mean()) / FRAME.std()).to_numpy()
        for allow in (True, False):
            with self.subTest(allow_failed_references=allow):
                metrics = pd.DataFrame({"WSS": [5.0, 4.0, 3.0, 2.0, 1.0]}, index=pd.Index([1, 2, 3, 4, 5], name="k"))
                expected, found = metrics.copy(), metrics.copy()
                options = {"algorithm": "lloyd", "max_iterations": 10}
                outcome = {}
                for label, target, function in (("legacy", expected, legacy_gap),
                                                ("new", found, advanced._gap_scores)):
                    with mock.patch.object(advanced, "kmeans", flaky), \
                            mock.patch.dict(os.environ, {parallel.ENVIRONMENT: "1"}):
                        try:
                            function(target, values, ["a", "b", "c"], 7, 6, allow_failed_references=allow,
                                     fit_options=options)
                            outcome[label] = None
                        except ValueError as error:
                            outcome[label] = str(error)
                self.assertEqual(outcome["new"], outcome["legacy"])
                self.assertEqual(outcome["legacy"] is None, allow)
                if allow:
                    pd.testing.assert_frame_equal(found, expected, check_exact=True)


if __name__ == "__main__":
    unittest.main()
