"""Time Restricted mean survival time on 50,000 complete rows in two cohorts with high-cardinality times.

Not a unit test. Run it once per source tree, in the same environment:

    python tests/bench_rmst.py --tree . --runs 7

It prints one JSON line: the median, minimum and maximum time of the dialog check (``check_options``), of the
whole analysis without and with the figure (in seconds, after one warm-up), the traced peak of the Python
allocations of one analysis in MB (tracemalloc) and the resident memory before and after, in MB.
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


def rss_mb():
    with open("/proc/self/statm") as handle:
        return int(handle.read().split()[1]) * resource.getpagesize() / 1048576


def frame(rows, seed=2026):
    rng = np.random.default_rng(seed)
    half = rows // 2
    times = np.r_[rng.exponential(30.0, half), rng.exponential(42.0, rows - half)]
    censor = rng.uniform(0, 90, rows)
    return pd.DataFrame({"Time": np.round(np.minimum(times, censor), 6), "Event": (times <= censor).astype(int),
                         "Group": np.repeat(["Control", "Treated"], [half, rows - half])})


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
    from analisi.rmst import check_options
    from analisi.workbench import analyse

    data = frame(args.rows)
    horizon = float(data.groupby("Group")["Time"].max().min())
    options = {"Time": "Time", "Status": "Event", "Group": "Group", "Reference group": "Control",
               "Horizon": horizon}
    before = rss_mb()
    report = {"rows": args.rows, "distinct times": int(data["Time"].nunique()), "horizon": horizon,
              "check_options s": timed(lambda: check_options(data, options), args.runs),
              "analysis without graph s": timed(lambda: analyse("Restricted mean survival time", data,
                                                                {**options, "Show graph": False}), args.runs),
              "analysis with graph s": timed(lambda: analyse("Restricted mean survival time", data, options),
                                             args.runs)}
    tracemalloc.start()
    result = analyse("Restricted mean survival time", data, {**options, "Show graph": False})
    report["traced peak MB"] = round(tracemalloc.get_traced_memory()[1] / 1048576, 2)
    tracemalloc.stop()
    report["integration steps"] = len(result.tables["Integration steps"])
    report["RSS MB"] = {"before": round(before, 1), "after": round(rss_mb(), 1)}
    report["environment"] = {"python": platform.python_version(), "numpy": np.__version__,
                             "pandas": pd.__version__, "machine": platform.machine(),
                             "processor": platform.processor() or platform.uname().machine}
    print(json.dumps(report))


if __name__ == "__main__":
    main()
