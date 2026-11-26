"""Time and memory of linked coefficients on 10 series × 5,000 rows (synthetic data).

    python tests/bench_coefficient_links.py [--repeat 3]

Y = B_g + A*X + C*X^2 + noise with C = 2*A + 1, A = 1.5 shared, B_g local. It runs the global fit with the link
(A shared, B local, C linked) and the same fit with C free, then Fit custom equation per series (Group column)
with and without the link. Memory is the peak of ``tracemalloc`` during one run (Python allocations, NumPy
included). Prints one line per case and the platform.
"""
import argparse
import platform
import sys
import time
import tracemalloc
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analisi.workbench import analyse  # noqa: E402

SERIES, ROWS = 10, 5_000


def data(seed=117):
    rng = np.random.default_rng(seed)
    x = np.tile(np.linspace(-2, 2, ROWS), SERIES)
    group = np.repeat([f"S{i:02d}" for i in range(SERIES)], ROWS)
    offsets = np.repeat(np.linspace(-3, 3, SERIES), ROWS)
    y = offsets + 1.5 * x + 4.0 * x * x + rng.normal(0, 0.25, x.size)
    return pd.DataFrame({"serie": group, "x": x, "y": y})


def recipes(linked):
    link = {"link": {"source": "A", "factor": 2.0, "offset": 1.0}} if linked else {}
    parameters = [{"name": "A", "start": 1.0, "lower": None, "upper": None, "fixed": False, "shared": True},
                  {"name": "B", "start": 1.0, "lower": None, "upper": None, "fixed": False, "shared": False},
                  {"name": "C", "start": 3.0, "lower": None, "upper": None, "fixed": False, "shared": True, **link}]
    common = {"X": "x", "Y": "y", "Group": "serie", "Equation": "B + A*X + C*X^2"}
    single = [{k: v for k, v in record.items() if k != "shared"} for record in parameters]
    return (("Global fit custom equation", {**common, "Parameters": parameters, "Series constraints": []}),
            ("Fit custom equation", {**common, "Parameters": single}))


def run(method, frame, options, repeat):
    times = []
    for _ in range(repeat):
        start = time.perf_counter()
        result = analyse(method, frame, options)
        times.append(time.perf_counter() - start)
    tracemalloc.start()
    analyse(method, frame, options)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return min(times), peak, result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repeat", type=int, default=3)
    args = parser.parse_args(argv)
    frame = data()
    print(f"Platform: {platform.platform()} · Python {platform.python_version()} · NumPy {np.__version__} · "
          f"{SERIES} series × {ROWS:,} rows")
    for linked in (True, False):
        for method, options in recipes(linked):
            seconds, peak, result = run(method, frame, options, args.repeat)
            key = "Global fit" if method.startswith("Global") else "Fit: S00"
            summary = result.tables[key]["Value"]
            free = summary.get("Free parameters")
            print(f"{method:28s} {'linked' if linked else 'C free':7s} best of {args.repeat}: {seconds:7.3f} s · "
                  f"peak {peak / 2**20:7.1f} MiB · free parameters {free}")


if __name__ == "__main__":
    main()
