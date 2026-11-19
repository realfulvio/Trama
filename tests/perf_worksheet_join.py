"""Time and peak memory of Join worksheets by key (not a unit test: ``python tests/perf_worksheet_join.py``).

1. 50,000 × 50,000 rows, one-to-one on a text and a number key, Full join (50,000 output rows).
2. 50,000 × 50,000 rows with repeated keys whose matches exceed the 100,000-row budget: the error comes before
   anything is expanded.
No time threshold: the numbers depend on the machine.
"""
import json
import sys
import time
import tracemalloc
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analisi import worksheet_join as wj  # noqa: E402
from analisi.field_error import FieldError  # noqa: E402

N = 50_000


def measure(name, left, right, options):
    tracemalloc.start()
    start = time.perf_counter()
    outcome = "ok"
    try:
        result = wj.join_worksheets(left, right, options)
        rows = len(result.tables[wj.JOINED])
    except FieldError as error:
        outcome, rows = f"FieldError on {error.field}: {error}", 0
    elapsed = time.perf_counter() - start
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {"case": name, "seconds": round(elapsed, 3), "peak_mb": round(peak / 2**20, 1), "rows": rows,
            "outcome": outcome}


def main():
    rng = np.random.default_rng(96)
    ids = rng.permutation(N)
    left = pd.DataFrame({"Sample": [f"S{i:05d} $" for i in range(N)], "Visit": np.arange(N) % 7,
                         "Signal": rng.normal(size=N)})
    right = pd.DataFrame({"ID": [f"S{i:05d} $" for i in ids], "Time": ids % 7, "Batch": rng.integers(0, 9, N),
                          "Signal": rng.normal(size=N)})
    one = {wj.RIGHT_SHEET: "Right", wj.LEFT_KEYS: ["Sample", "Visit"], wj.RIGHT_KEYS: ["ID", "Time"],
           wj.JOIN_TYPE: "Full", wj.CARDINALITY: "One-to-one"}
    results = [measure("50k x 50k one-to-one Full", left, right, one)]
    repeated_left = pd.DataFrame({"Key": np.arange(N) % 10, "Value": np.arange(N)})
    repeated_right = pd.DataFrame({"Key": np.arange(N) % 10, "Other": np.arange(N)})
    many = {wj.RIGHT_SHEET: "Right", wj.LEFT_KEYS: ["Key"], wj.RIGHT_KEYS: ["Key"], wj.JOIN_TYPE: "Inner",
            wj.CARDINALITY: "Many-to-many"}
    results.append(measure("50k x 50k repeated keys over budget (250,000,000 pairs)", repeated_left,
                           repeated_right, many))
    for item in results:
        print(json.dumps(item, ensure_ascii=False))


if __name__ == "__main__":
    main()
