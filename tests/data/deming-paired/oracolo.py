"""Independent small-fixture oracle using SVD in whitened coordinates."""

import json
from pathlib import Path

import numpy as np
from scipy.stats import t


def fit(rows, y, ratio):
    data = rows[:, [0, y]]
    center = data.mean(axis=0)
    scale = np.sqrt(ratio)
    _, _, directions = np.linalg.svd((data - center) * [scale, 1.0], full_matrices=False)
    slope = scale * directions[0, 1] / directions[0, 0]
    return np.array([slope, center[1] - slope * center[0]])


def contrast(rows, ratio, confidence):
    first, second = fit(rows, 1, ratio), fit(rows, 2, ratio)
    estimate = second - first
    n = len(rows)
    replicates = []
    for i in range(n):
        sample = np.delete(rows, i, axis=0)
        replicates.append(fit(sample, 2, ratio) - fit(sample, 1, ratio))
    draws = np.array(replicates)
    se = np.sqrt((n - 1) / n * np.sum((draws - draws.mean(axis=0)) ** 2, axis=0))
    critical = t.ppf((1 + confidence) / 2, n - 1)
    return {
        "n": n, "df": n - 1, "variance_ratio": ratio, "confidence": confidence,
        "coefficient_order": ["slope", "intercept"],
        "first": first.tolist(), "second": second.tolist(), "second_minus_first": estimate.tolist(),
        "se": se.tolist(), "p_two_sided": (2*t.sf(abs(estimate/se), n - 1)).tolist(),
        "lower": (estimate - critical*se).tolist(), "upper": (estimate + critical*se).tolist(),
    }


def main():
    path = Path(__file__).with_name("deming-appaiato.alab")
    table = json.loads(path.read_text(encoding="utf-8"))["tables"][0]
    excluded = {tuple(cell) for cell in table["excluded"]}
    rows = np.array([row[1:] for i, row in enumerate(table["rows"])
                     if None not in row[1:] and not any((i, j) in excluded for j in (1, 2, 3))], dtype=float)
    print(json.dumps(contrast(rows, ratio=1.0, confidence=.95), indent=2))


if __name__ == "__main__":
    main()
