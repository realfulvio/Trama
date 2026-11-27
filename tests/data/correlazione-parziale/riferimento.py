"""Numerical reference for the synthetic dataset, independent of Trama."""
import argparse
import csv
import json
from itertools import combinations
from math import sqrt
from pathlib import Path

import numpy as np
from scipy import stats

DIRECTORY = Path(__file__).resolve().parent
TARGETS = ("X", "Y", "W")


def example(method, controls):
    fields = (*TARGETS, *controls)
    with (DIRECTORY / "campione.csv").open(newline="", encoding="utf-8") as file:
        rows = [row for row in csv.DictReader(file)
                if row["ID"] != "escludere" and all(row[name] for name in fields)]
    values = np.asarray([[float(row[name]) for name in fields] for row in rows])
    matrix = stats.rankdata(values, axis=0) if method == "Spearman" else values
    n = len(matrix)
    df = n - len(controls) - 2
    pairs = []
    for i, j in combinations(range(len(TARGETS)), 2):
        control_indices = range(len(TARGETS), len(fields))
        pair_and_controls = matrix[:, [i, j, *control_indices]]
        precision = np.linalg.inv(np.corrcoef(pair_and_controls, rowvar=False))
        r = float(-precision[0, 1] / sqrt(precision[0, 0] * precision[1, 1]))
        t = r * sqrt(df / (1 - r**2))
        p = float(2 * stats.t.sf(abs(t), df))
        interval = None
        if method == "Pearson":
            delta = stats.norm.ppf(0.975) / sqrt(n - len(controls) - 3)
            interval = np.tanh(np.arctanh(r) + np.array([-delta, delta])).tolist()
        pairs.append({"variabili": [TARGETS[i], TARGETS[j]], "r": r, "p": p, "IC95": interval})
    ordered = sorted(pairs, key=lambda pair: pair["p"])
    previous = 0.0
    for index, pair in enumerate(ordered):
        previous = min(1.0, max(previous, pair["p"] * (len(pairs) - index)))
        pair["p_holm"] = previous
    return {"metodo": method, "controlli": list(controls), "N": n, "gdl": df, "coppie": pairs}


def assert_close(actual, expected):
    if isinstance(expected, float):
        np.testing.assert_allclose(actual, expected, rtol=1e-10, atol=1e-12)
    elif isinstance(expected, dict):
        assert actual.keys() == expected.keys()
        for key in expected:
            assert_close(actual[key], expected[key])
    elif isinstance(expected, list):
        for result, target in zip(actual, expected, strict=True):
            assert_close(result, target)
    else:
        assert actual == expected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    cases = [example(method, controls) for method in ("Pearson", "Spearman")
             for controls in (("Z1",), ("Z1", "Z2"))]
    np.testing.assert_allclose(cases[1]["coppie"][0]["r"], -1 / sqrt(5), atol=1e-12)
    if args.check:
        expected = json.loads((DIRECTORY / "atteso.json").read_text(encoding="utf-8"))
        assert_close(cases, expected)
        print("PASS — 4 configurazioni di correlazione parziale")
    else:
        print(json.dumps(cases, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
