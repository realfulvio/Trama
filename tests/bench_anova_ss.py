"""Time the three sums of squares of the Multifactor ANOVA near the supported size of the design.

Not a unit test. Run it once per source tree, in the same environment:

    python tests/bench_anova_ss.py --tree . --runs 3

It prints one JSON line per case with the rows, the model coefficients, the number of terms, and the median,
minimum and maximum seconds of ``analyse`` for each type, plus the peak resident memory in MB. The data are
synthetic with a fixed seed. The limits of the analysis are eight factors, interactions to order 3, 2 to 128
levels per factor, and ``coefficients × rows ≤ 4,000,000`` with fewer coefficients than rows.
"""
import argparse
from itertools import combinations, product
import json
from math import prod
from pathlib import Path
import resource
import statistics
import sys
import time

import numpy as np
import pandas as pd

TYPES = ("Type III", "Type I", "Type II")


def coefficients(levels, order):
    degrees = [level - 1 for level in levels]
    return 1 + sum(prod(choice) for size in range(1, order + 1) for choice in combinations(degrees, size))


def frame(levels, rows, seed):
    rng = np.random.default_rng(seed)
    names = [f"F{index + 1}" for index in range(len(levels))]
    cells = list(product(*(range(level) for level in levels)))
    chosen = np.concatenate([np.arange(len(cells)), rng.integers(0, len(cells), rows - len(cells))])
    codes = np.array(cells)[chosen[:rows]]
    data = pd.DataFrame({name: [f"L{code}" for code in codes[:, index]] for index, name in enumerate(names)})
    effect = sum(codes[:, index] * (0.3 + 0.1 * index) for index in range(len(levels)))
    data["Y"] = 10 + effect + rng.normal(0, 2, rows) + (codes[:, 0] == codes[:, 1]) * 1.5
    return data, names


CASES = {
    # 10 × 10 × 10 cells, order 3: 1000 coefficients, 3990 rows (3.99 million cells of the design matrix).
    "three-factors-10-levels": ((10, 10, 10), 3, 3990),
    # Eight factors with three levels, order 3: 92 terms, 577 coefficients, 6900 rows.
    "eight-factors-3-levels": ((3,) * 8, 3, 6900),
    # One factor with 100 levels beside two small ones, order 2.
    "wide-factor": ((100, 4, 3), 2, 3000),
}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tree", type=Path, default=Path("."), help="Trama checkout to measure")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--cases", nargs="*", default=list(CASES), choices=list(CASES))
    args = parser.parse_args(argv)
    sys.path.insert(0, str(args.tree.resolve()))
    from analisi.workbench import analyse

    for name in args.cases:
        levels, order, rows = CASES[name]
        data, factors = frame(levels, rows, seed=92)
        count = coefficients(levels, order)
        assert count * rows <= 4_000_000 and count < rows, (count, rows)
        terms = sum(1 for size in range(1, order + 1) for _ in combinations(range(len(levels)), size))
        record = {"case": name, "rows": rows, "levels": list(levels), "order": order,
                  "coefficients": count, "terms": terms, "cells": count * rows, "seconds": {}}
        reference = None
        for kind in TYPES:
            options = {"Response": "Y", "Factors": factors, "Interaction order": order}
            if kind != "Type III":
                options["Sums of squares"] = kind
            times = []
            for _ in range(args.runs):
                started = time.perf_counter()
                result = analyse("Multifactor ANOVA", data, options)
                times.append(time.perf_counter() - started)
            record["seconds"][kind] = {"median": round(statistics.median(times), 3),
                                       "min": round(min(times), 3), "max": round(max(times), 3)}
            table = result.tables[next(iter(result.tables))]
            if reference is None:
                reference = table
            # The residual row is the same in every type.
            assert abs(table.loc["Residual", "SS"] - reference.loc["Residual", "SS"]) <= 1e-9 * reference.loc["Residual", "SS"]
        record["peak_rss_mb"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)
        print(json.dumps(record), flush=True)


if __name__ == "__main__":
    main()
