"""analisi.parallel: same values, order and errors as the serial loop, with any number of processes."""
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

from analisi import parallel
from analisi.field_error import FieldError


ROOT = Path(__file__).resolve().parents[1]


class Stop(Exception):
    """An engine's own cancellation error."""


def square(value):
    return value * value


def fail_at(value):
    if value in (5, 9):
        raise ValueError(f"item {value}")
    return value


def field_error(value):
    if value == 3:
        raise FieldError("Gap simulations", "Use 5 to 100 reference datasets.")
    return value


def unpicklable_result(value):
    return (lambda: value) if parallel.in_worker() else value


class Unpicklable(Exception):
    def __init__(self, handle):
        super().__init__("cannot travel")
        self.handle = handle


def unpicklable_error(value):
    raise Unpicklable(threading.Lock())


def environment(_):
    import sys as worker_sys
    return {"processes": parallel.process_count(), "in_worker": parallel.in_worker(), "pid": os.getpid(),
            "blas": os.environ.get("OPENBLAS_NUM_THREADS"), "backend": os.environ.get("MPLBACKEND"),
            "tk": "tkinter" in worker_sys.modules}


def language(_):
    from analisi.i18n import active_language, tr
    return parallel.in_worker(), active_language(), tr("processes.command")


def nested(value):
    return parallel.run_tasks(square, range(value)), parallel.process_count()


def crash_in_worker(value):
    if parallel.in_worker():
        os._exit(3)
    return value + 100


def slow_until_cancelled(value, cancel):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if cancel is not None and cancel.is_set():
            raise Stop(f"stopped {value}")
        time.sleep(0.01)
    return value


class Processes:
    """Run a block with TRAMA_PROCESSES set, then restore the variable."""

    def __init__(self, count):
        self.count = str(count)

    def __enter__(self):
        self.previous = os.environ.get(parallel.ENVIRONMENT)
        os.environ[parallel.ENVIRONMENT] = self.count

    def __exit__(self, *error):
        if self.previous is None:
            os.environ.pop(parallel.ENVIRONMENT, None)
        else:
            os.environ[parallel.ENVIRONMENT] = self.previous


class SettingTests(unittest.TestCase):
    def test_parse_setting(self):
        for value, expected in [("auto", "auto"), (None, "auto"), ("", "auto"), ("4", 4), (4, 4), (1, 1),
                                (0, "auto"), (65, "auto"), (True, "auto"), ("x", "auto"), (2.5, "auto")]:
            self.assertEqual(parallel.parse_setting(value), expected, value)

    def test_auto_leaves_one_processor_and_caps_memory(self):
        self.assertEqual(parallel.auto_processes(1), 1)
        self.assertEqual(parallel.auto_processes(2), 1)
        self.assertEqual(parallel.auto_processes(4), 3)
        self.assertEqual(parallel.auto_processes(32), parallel.MAX_AUTO)

    def test_save_keeps_the_other_preferences(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "preferences.json"
            path.write_text(json.dumps({"language": "it", "theme": "modern"}), encoding="utf-8")
            parallel.save_setting(path, 6)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")),
                             {"language": "it", "theme": "modern", "processes": 6})
            self.assertEqual(parallel.load_setting(path), 6)
            parallel.save_setting(path, "auto")
            self.assertEqual(parallel.load_setting(path), "auto")
            self.assertEqual(parallel.load_setting(Path(folder) / "missing.json"), "auto")

    def test_environment_overrides_the_preference(self):
        with Processes(1):
            self.assertEqual(parallel.process_count(), 1)
        with Processes(5):
            self.assertEqual(parallel.process_count(), 5)

    def test_freeze_support_is_the_first_thing_the_executable_does(self):
        source = (ROOT / "trama_qt" / "__main__.py").read_text(encoding="utf-8")
        self.assertLess(source.index("multiprocessing.freeze_support()"), source.index("from trama_qt.app import main"))


class SerialEquivalenceTests(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        parallel.shutdown()

    def test_same_values_and_order(self):
        for count in (1, 2, 4):
            with self.subTest(processes=count), Processes(count):
                self.assertEqual(parallel.run_tasks(square, range(40)), [value * value for value in range(40)])

    def test_first_error_in_item_order(self):
        for count in (1, 4):
            with self.subTest(processes=count), Processes(count):
                with self.assertRaisesRegex(ValueError, "item 5"):
                    parallel.run_tasks(fail_at, range(12))

    def test_outcomes_keep_every_error(self):
        with Processes(4):
            found = parallel.run_tasks(fail_at, range(12), outcomes=True)
        self.assertEqual([outcome.value for outcome in found if outcome.error is None],
                         [value for value in range(12) if value not in (5, 9)])
        self.assertEqual([str(outcome.error) for outcome in found if outcome.error is not None],
                         ["item 5", "item 9"])

    def test_field_error_keeps_its_field(self):
        with Processes(4):
            found = parallel.run_tasks(field_error, range(6), outcomes=True)
        error = found[3].error
        self.assertIsInstance(error, FieldError)
        self.assertEqual((error.field, str(error)), ("Gap simulations", "Use 5 to 100 reference datasets."))

    def test_results_and_errors_that_cannot_travel_are_computed_here(self):
        with Processes(4):
            self.assertEqual(parallel.run_tasks(unpicklable_result, range(6)), list(range(6)))
            with self.assertRaises(Unpicklable):
                parallel.run_tasks(unpicklable_error, range(3))

    def test_arguments_that_cannot_travel_are_computed_here(self):
        lock = threading.Lock()
        with Processes(4):
            found = parallel.run_tasks(type, [lock, 1, 2])
        self.assertEqual(found, [type(lock), int, int])

    def test_workers_are_lean_and_never_nest(self):
        with Processes(3):
            parallel.warm_up()
            found = parallel.run_tasks(environment, range(12))
            nested_found = parallel.run_tasks(nested, [5, 6, 7])
        remote = [item for item in found if item["in_worker"]]
        self.assertTrue(remote, "no item reached a worker")
        for item in remote:
            self.assertEqual((item["processes"], item["blas"], item["backend"], item["tk"]), (1, "1", "Agg", False))
        self.assertEqual([values for values, _ in nested_found],
                         [[value * value for value in range(n)] for n in (5, 6, 7)])

    def test_workers_use_the_language_of_this_process(self):
        from analisi.i18n import active_language, set_language
        previous = active_language()
        try:
            with Processes(3):
                parallel.warm_up()
                for code, command in (("it", "Calcolo multicore…"), ("en", "Multicore calculation…")):
                    set_language(code)
                    found = parallel.run_tasks(language, range(12))
                    self.assertTrue(any(remote for remote, *_ in found), "no item reached a worker")
                    self.assertEqual({(code_found, text) for _, code_found, text in found}, {(code, command)})
        finally:
            set_language(previous)

    def test_a_crashed_worker_falls_back_to_this_process(self):
        with Processes(3):
            parallel.warm_up()
            self.assertEqual(parallel.run_tasks(crash_in_worker, range(6)), [value + 100 for value in range(6)])
            self.assertEqual(parallel.run_tasks(square, range(8)), [value * value for value in range(8)])

    def test_cancellation_reaches_running_and_queued_items(self):
        cancel = threading.Event()
        with Processes(3):
            parallel.warm_up()
            timer = threading.Timer(0.5, cancel.set)
            timer.start()
            started = time.monotonic()
            with self.assertRaisesRegex(Stop, "stopped 0"):
                parallel.run_tasks(slow_until_cancelled, range(10), cancel=cancel, with_cancel=True)
            self.assertLess(time.monotonic() - started, 10)
            timer.join()

    def test_progress_counts_every_item(self):
        seen = []
        with Processes(3):
            parallel.run_tasks(square, range(9), progress=lambda done, total: seen.append((done, total)))
        self.assertEqual(seen[-1], (9, 9))
        self.assertEqual([done for done, _ in seen], list(range(1, 10)))

    def test_no_pool_means_serial(self):
        with Processes(4), mock.patch.object(parallel, "_get_pool", return_value=None):
            self.assertEqual(parallel.run_tasks(square, range(5)), [0, 1, 4, 9, 16])


if __name__ == "__main__":
    unittest.main()
