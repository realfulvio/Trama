"""One BLAS thread in every Trama process: the digits of a result do not depend on where it was calculated.

Each case runs in a fresh interpreter, because the thread count of OpenBLAS is fixed when NumPy loads and the
test runner has loaded NumPy long before.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
THREAD_VARIABLES = ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS",
                    "NUMEXPR_NUM_THREADS")
REPORT = ("import json, os, sys\n"
          "from analisi import blas_threads\n"
          "print(json.dumps({'variables': {name: os.environ.get(name) for name in blas_threads.VARIABLES},\n"
          "                  'before_numpy': blas_threads.BEFORE_NUMPY}))\n")
# The same analyses of the same 100 000 rows, once in this process and once in calculation workers: what the
# window does when Run is pressed in a dialog and when a linked analysis is recalculated after an edit.
TWO_PATHS = """
import json, time
from analisi import parallel  # the engine first, as in the program: NumPy must load after it
from analisi.parallel_analyses import analysis_task
import numpy as np, pandas as pd

rng = np.random.default_rng(3)
frame = pd.DataFrame(rng.normal(size=(100_000, 2)), columns=["A", "B"])
frame["B"] += .3 * frame["A"]
jobs = [("Correlation", frame, {"X": "A", "Y": "B", "Method": "Pearson"}),
        ("Linear regression", frame, {"X": "A", "Y": "B"})] * 4
here = [analysis_task(job) for job in jobs]
parallel.warm_up()
deadline = time.monotonic() + 120
while not (parallel._pool is not None and parallel._pool.warm) and time.monotonic() < deadline:
    time.sleep(.05)
there = parallel.run_tasks(analysis_task, jobs, outcomes=True)
parallel.shutdown()
remote = [index for index, outcome in enumerate(there) if outcome.remote]
different = [index for index in remote
             if any(not here[index].tables[name].equals(there[index].value.tables[name]) for name in here[index].tables)]
print(json.dumps({"remote": len(remote), "different": len(different)}))
"""


def fresh_interpreter(code, **environment):
    """Run ``code`` from the source folder with none of the thread settings of this process."""
    inherited = {name: value for name, value in os.environ.items()
                 if name not in THREAD_VARIABLES + ("TRAMA_BLAS_THREADS", "TRAMA_PROCESSES")}
    done = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=600,
                          env={**inherited, "MPLBACKEND": "Agg", "QT_QPA_PLATFORM": "offscreen", **environment})
    if done.returncode:
        raise AssertionError(done.stderr[-2000:])
    return json.loads(done.stdout.strip().splitlines()[-1])


class BlasThreadTests(unittest.TestCase):
    def test_importing_the_engine_asks_for_one_thread_before_numpy_loads(self):
        found = fresh_interpreter(REPORT)
        self.assertEqual(set(found["variables"]), set(THREAD_VARIABLES))
        self.assertEqual(set(found["variables"].values()), {"1"})
        self.assertTrue(found["before_numpy"])

    def test_a_setting_inherited_from_the_computer_does_not_bring_the_threads_back(self):
        found = fresh_interpreter(REPORT, OPENBLAS_NUM_THREADS="8", OMP_NUM_THREADS="8")
        self.assertEqual(set(found["variables"].values()), {"1"})

    def test_the_qt_window_reaches_the_engine_before_numpy(self):
        found = fresh_interpreter("import trama_qt.theme\n" + REPORT)
        self.assertTrue(found["before_numpy"])

    def test_benchmarks_can_ask_for_more_threads(self):
        found = fresh_interpreter(REPORT, TRAMA_BLAS_THREADS="4")
        self.assertEqual(set(found["variables"].values()), {"4"})
        for wrong in ("0", "many", "-2", ""):
            with self.subTest(value=wrong):
                self.assertEqual(set(fresh_interpreter(REPORT, TRAMA_BLAS_THREADS=wrong)["variables"].values()), {"1"})

    def test_a_dialog_and_a_linked_refresh_give_the_same_digits(self):
        found = fresh_interpreter(TWO_PATHS, TRAMA_PROCESSES="2")
        self.assertGreater(found["remote"], 0, "no analysis reached a calculation worker")
        self.assertEqual(found["different"], 0)


if __name__ == "__main__":
    unittest.main()
