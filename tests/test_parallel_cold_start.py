"""A request never waits for calculation workers that are still starting.

Until the workers are ready the calling thread works through the items in order, exactly as the serial loop
does. A request that ends within ``COLD_START_SECONDS`` does not start them at all; a longer one starts them
and hands over what is left when the first is ready.
"""
import os
import threading
import time
import unittest
from unittest import mock

import pandas as pd

from analisi import parallel
from analisi.data import Dataset
from tests.test_parallel import Processes, Stop, fail_at, slow_until_cancelled, square


def slow_square(value):
    time.sleep(0.05)
    return value * value


def where(value):
    return value, parallel.in_worker(), os.getpid()


def work_through_worker_start(value):
    # Keep the first local item busy until the pool actually becomes ready.
    # A fixed-length workload may finish before a loaded machine starts a worker.
    if value == 0 and not parallel.in_worker():
        deadline = time.monotonic() + 120
        while not parallel._pool.warm:
            if time.monotonic() >= deadline:
                raise AssertionError("the calculation workers did not start during the first item")
            time.sleep(0.02)
    return square(value)


class ColdStartTests(unittest.TestCase):
    def setUp(self):
        parallel.shutdown()  # every test starts without workers
        self.addCleanup(parallel.shutdown)

    def test_a_short_first_request_is_answered_here_and_starts_no_worker(self):
        with Processes(4):
            found = parallel.run_tasks(where, range(6), outcomes=True)
            self.assertEqual([outcome.value[0] for outcome in found], list(range(6)))
            self.assertEqual({outcome.value[2] for outcome in found}, {os.getpid()})
            self.assertFalse(any(outcome.remote for outcome in found))
            self.assertFalse(parallel._pool.started)

    def test_a_long_first_request_starts_here_and_moves_to_the_workers(self):
        with Processes(3):
            found = parallel.run_tasks(work_through_worker_start, range(6), outcomes=True)
            self.assertEqual(found[0], parallel.Outcome(value=0))
            self.assertEqual([outcome.value for outcome in found], [value * value for value in range(6)])
            self.assertTrue(all(outcome.remote for outcome in found[1:]))

    def test_the_second_request_uses_the_workers_from_its_first_item(self):
        with Processes(3):
            self.assertEqual(parallel.run_tasks(work_through_worker_start, range(3)), [0, 1, 4])
            found = parallel.run_tasks(where, range(12), outcomes=True)
            self.assertTrue(all(outcome.remote for outcome in found))

    def test_first_error_in_item_order_without_workers(self):
        seen = []
        with Processes(4):
            with self.assertRaisesRegex(ValueError, "item 5"):
                parallel.run_tasks(fail_at, range(12), progress=lambda done, total: seen.append(done))
            self.assertEqual(seen, [1, 2, 3, 4, 5, 6])  # the loop stops at its first error
            self.assertFalse(parallel._pool.started)

    def test_outcomes_keep_every_error_without_workers(self):
        with Processes(4):
            found = parallel.run_tasks(fail_at, range(12), outcomes=True)
        self.assertEqual([str(outcome.error) for outcome in found if outcome.error is not None], ["item 5", "item 9"])
        self.assertEqual([outcome.value for outcome in found if outcome.error is None],
                         [value for value in range(12) if value not in (5, 9)])

    def test_progress_counts_every_item_without_workers(self):
        seen = []
        with Processes(3):
            parallel.run_tasks(square, range(9), progress=lambda done, total: seen.append((done, total)))
        self.assertEqual(seen, [(done, 9) for done in range(1, 10)])

    def test_cancelling_before_the_workers_start_raises_the_engine_error(self):
        cancel = threading.Event()
        with Processes(3):
            timer = threading.Timer(0.05, cancel.set)  # well before COLD_START_SECONDS
            timer.start()
            started = time.monotonic()
            with self.assertRaisesRegex(Stop, "stopped 0"):
                parallel.run_tasks(slow_until_cancelled, range(10), cancel=cancel, with_cancel=True)
            self.assertLess(time.monotonic() - started, 5)
            timer.join()
            self.assertFalse(parallel._pool.started)

    def test_workers_that_never_get_ready_leave_the_request_here(self):
        with Processes(3), mock.patch.object(parallel._Pool, "start", return_value=False):
            found = parallel.run_tasks(slow_square, range(12), outcomes=True)  # 0.6 s: longer than the delay
        self.assertEqual([outcome.value for outcome in found], [value * value for value in range(12)])
        self.assertFalse(any(outcome.remote for outcome in found))

    def test_warm_up_starts_the_workers_without_a_request(self):
        with Processes(3):
            self.assertTrue(parallel.warm_up())
            self.assertTrue(parallel._pool.started)
            deadline = time.monotonic() + 120
            while not parallel._pool.warm and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertEqual(parallel.warm_process_count(), 3)
            found = parallel.run_tasks(where, range(12), outcomes=True)
            self.assertTrue(all(outcome.remote for outcome in found))


class LinkedRefreshTests(unittest.TestCase):
    """What a person meets: the first recalculation of linked analyses after an edit, in a new session."""

    def test_a_small_refresh_does_not_start_the_workers(self):
        from trama_qt.project import Project, Run

        parallel.shutdown()
        self.addCleanup(parallel.shutdown)
        project = Project()
        project.tables["Experiment"] = Dataset(pd.DataFrame({"X": [1., 2., 3., 4., 5.], "Y": [2., 5., 6., 9., 9.],
                                                             "Z": [5., 3., 4., 1., 2.]}))
        project.runs = [Run("Correlation", "Experiment", {"X": a, "Y": b, "Method": method}, slot=slot)
                        for slot, (a, b, method) in enumerate([("X", "Y", "Pearson"), ("X", "Z", "Pearson"),
                                                               ("Y", "Z", "Pearson"), ("X", "Y", "Spearman")])]
        with Processes(1):
            expected = project.run_refresh(project.plan_refresh(project.runs))
        with Processes(4):
            current = project.run_refresh(project.plan_refresh(project.runs))
            self.assertFalse(parallel._pool is not None and parallel._pool.started)
        for run in project.runs:
            self.assertIsNone(current[run.uid].error)
            for name, table in expected[run.uid].result.tables.items():
                pd.testing.assert_frame_equal(current[run.uid].result.tables[name], table, check_exact=True)


if __name__ == "__main__":
    unittest.main()
