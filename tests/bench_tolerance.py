"""Time Tolerance intervals on synthetic data. Not a unit test.

    python tests/bench_tolerance.py --runs 5

It prints one JSON document: hardware and library versions, then for each case the median, minimum and maximum
of the wall-clock time in milliseconds (after one warm-up pass), the peak Python allocation of one run (tracemalloc,
MB) and the growth of the resident memory. The load case of the specification is 50,000 measures, 8 variables and
4 groups; the budget case is the largest the dialog accepts (100,000 values, 24 variables, 8 groups).
"""
import argparse
import io
import json
import os
import platform
import resource
import statistics
import sys
import time
import tracemalloc
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def rss_mb():
    with open("/proc/self/statm") as handle:
        return int(handle.read().split()[1]) * resource.getpagesize() / 1048576


def hardware():
    model = ""
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as handle:
            model = next((line.split(":", 1)[1].strip() for line in handle if line.startswith("model name")), "")
    except OSError:
        pass
    import matplotlib
    import scipy
    return {"python": platform.python_version(), "numpy": np.__version__, "scipy": scipy.__version__,
            "pandas": pd.__version__, "matplotlib": matplotlib.__version__, "system": platform.platform(),
            "cpu": model, "cores": os.cpu_count()}


def synthetic(rows, variables, groups, seed=93):
    rng = np.random.default_rng(seed)
    frame = pd.DataFrame({f"V{i + 1}": rng.normal(10 + i, 1 + i / 4, rows) for i in range(variables)})
    if groups:
        frame["Group"] = [f"G{i % groups + 1}" for i in range(rows)]
    return frame


def measure(function, runs):
    function()                                              # warm-up: imports, SciPy caches
    times = []
    for _ in range(runs):
        start = time.perf_counter()
        function()
        times.append((time.perf_counter() - start) * 1000)
    before = rss_mb()
    tracemalloc.start()
    function()
    peak = tracemalloc.get_traced_memory()[1] / 1048576
    tracemalloc.stop()
    return {"median_ms": round(statistics.median(times), 1), "min_ms": round(min(times), 1),
            "max_ms": round(max(times), 1), "python_peak_mb": round(peak, 1),
            "rss_growth_mb": round(rss_mb() - before, 1), "runs": runs}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=5)
    runs = parser.parse_args().runs
    from analisi.tolerance_intervals import tolerance_intervals

    load = synthetic(50_000, 8, 4)
    names = [f"V{i + 1}" for i in range(8)]
    base = {"Variables": names, "Group": "Group"}
    cases = {
        "load: Normal two-sided (Howe), 8 variables x 4 groups": (load, base),
        "load: Normal one-sided (exact noncentral t)": (load, {**base, "Sides": "Upper"}),
        "load: Distribution-free two-sided": (load, {**base, "Distribution": "Distribution-free"}),
        "load: Distribution-free lower": (load, {**base, "Distribution": "Distribution-free", "Sides": "Lower"}),
        "load: Normal two-sided, no group": (load, {"Variables": names}),
        "load: Normal two-sided with figure": (load, {**base, "Show graph": True}),
        "load: Distribution-free with figure": (load, {**base, "Distribution": "Distribution-free",
                                                       "Show graph": True}),
    }
    budget = synthetic(100_000, 24, 8)
    cases["budget: 100,000 values, 24 variables, 8 groups, Normal"] = (
        budget, {"Variables": [f"V{i + 1}" for i in range(24)], "Group": "Group"})
    cases["budget: same, Distribution-free"] = (
        budget, {"Variables": [f"V{i + 1}" for i in range(24)], "Group": "Group", "Distribution": "Distribution-free"})
    report = {"hardware": hardware(), "cases": {}}
    for name, (frame, options) in cases.items():
        report["cases"][name] = measure(lambda frame=frame, options=options: tolerance_intervals(frame, options), runs)
    # Rendering the figure to SVG is separate from building it.
    figure = tolerance_intervals(load, {**base, "Show graph": True}).figure

    def export():
        figure.savefig(io.StringIO(), format="svg")
    report["cases"]["load: figure exported to SVG"] = measure(export, max(2, runs // 2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
