"""Time the Kaplan–Meier analysis on 50,000 rows in 8 groups, with and without the simultaneous band.

Not a unit test. Run it once per source tree, in the same environment:

    python tests/bench_survival_bands.py --tree . --runs 7

It prints one JSON line. Every figure is the median, minimum and maximum (seconds, after one warm-up) of the whole
``analyse`` call: without the band (``Uncertainty = None``, the default), with the pointwise band and with the
simultaneous band; then the band computation alone (``band_sheet`` on the already calculated curves), the traced
peak of the Python allocations of the simultaneous run in MB (tracemalloc) and the resident memory in MB.
"""
import argparse
import json
import platform
from pathlib import Path
import resource
import statistics
import sys
import time
import tracemalloc

import numpy as np
import pandas as pd

GROUPS = 8


def rss_mb():
    with open("/proc/self/statm") as handle:
        return int(handle.read().split()[1]) * resource.getpagesize() / 1048576


def frame(rows, seed=2026):
    rng = np.random.default_rng(seed)
    scales = rng.uniform(20, 60, GROUPS)
    group = rng.integers(0, GROUPS, rows)
    times = rng.exponential(scales[group])
    censor = rng.uniform(0, 90, rows)
    return pd.DataFrame({"Time": np.round(np.minimum(times, censor), 6), "Event": (times <= censor).astype(int),
                         "Group": np.array([f"Arm {number + 1}" for number in range(GROUPS)])[group]})


def timed(function, runs):
    function()
    samples = []
    for _ in range(runs):
        start = time.perf_counter()
        function()
        samples.append(time.perf_counter() - start)
    return {"median": round(statistics.median(samples), 4), "min": round(min(samples), 4),
            "max": round(max(samples), 4)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tree", type=Path, default=Path("."))
    parser.add_argument("--runs", type=int, default=7)
    parser.add_argument("--rows", type=int, default=50_000)
    args = parser.parse_args()
    sys.path.insert(0, str(args.tree.resolve()))
    import matplotlib
    matplotlib.use("Agg")
    from analisi import stats as engine
    from analisi.survival_bands import SIMULTANEOUS, band_sheet
    from analisi.workbench import analyse

    method = "Kaplan–Meier survival"
    data = frame(args.rows)
    options = {"Time": "Time", "Event": "Event", "Group": "Group", "Confidence level (%)": 95}
    curves, _ = engine.survival(data, "Time", "Event", "Group", strict=False)
    before = rss_mb()
    report = {"rows": args.rows, "groups": GROUPS, "distinct times": int(data["Time"].nunique()),
              "analysis without band s": timed(lambda: analyse(method, data, options), args.runs),
              "analysis with pointwise band s": timed(
                  lambda: analyse(method, data, {**options, "Uncertainty": "Pointwise confidence band"}), args.runs),
              "analysis with simultaneous band s": timed(
                  lambda: analyse(method, data, {**options, "Uncertainty": SIMULTANEOUS}), args.runs),
              "band computation alone s": timed(lambda: band_sheet(curves, 95), args.runs)}
    tracemalloc.start()
    result = analyse(method, data, {**options, "Uncertainty": SIMULTANEOUS})
    report["traced peak MB"] = round(tracemalloc.get_traced_memory()[1] / 1048576, 2)
    tracemalloc.stop()
    report["band rows"] = len(result.tables["Simultaneous confidence bands"])
    report["RSS MB"] = {"before": round(before, 1), "after": round(rss_mb(), 1)}
    report["environment"] = {"python": platform.python_version(), "numpy": np.__version__,
                             "pandas": pd.__version__, "machine": platform.machine(),
                             "processor": platform.processor() or platform.uname().machine}
    print(json.dumps(report))


if __name__ == "__main__":
    main()
