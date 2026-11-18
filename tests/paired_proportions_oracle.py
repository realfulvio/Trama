"""Independent oracle for the Paired proportions analysis; it imports no Trama module.

The McNemar tails are summed from exact binomial coefficients (``math.comb``), the exact p value is compared with
statsmodels, and the conditional odds-ratio interval is the Clopper–Pearson interval of b out of b + c written as
q / (1 − q), straight from SciPy's beta quantiles. The frozen values of the synthetic fixtures live in
``tests/data/paired_proportions/expected.json``.
"""
from math import comb

import numpy as np
from scipy.stats import beta, chi2
from statsmodels.stats.contingency_tables import mcnemar

EXACT, MID_P, CHI = "Exact", "Mid-p", "Chi-square with continuity correction"
FIELDS = ["N pairs", "Before positive fraction", "After positive fraction", "Difference (after − before)",
          "Discordant pairs", "Chi-square", "p", "Matched odds ratio", "OR CI lower", "OR CI upper"]


def reference(counts, level, method):
    """Report values for the counts (a, b, c, d); None stands for a value that is not estimable or not used."""
    a, b, c, d = counts
    n, discordant = sum(counts), b + c
    statistic = odds = lower = upper = None
    p = 1.0
    if discordant:
        small = min(b, c)
        tail = sum(comb(discordant, j) for j in range(small + 1))
        doubled = 2 * tail / 2 ** discordant
        if method == EXACT:
            p = min(1.0, doubled)
            table = np.array([[a, b], [c, d]])
            assert abs(p - float(mcnemar(table, exact=True).pvalue)) < 1e-12
        elif method == MID_P:
            p = min(1.0, doubled - comb(discordant, small) / 2 ** discordant)
        else:
            statistic = max(0, abs(b - c) - 1) ** 2 / discordant
            p = float(chi2.sf(statistic, 1))
        edge = (1 - level / 100) / 2
        odds = b / c if c else float("inf")
        low_b = float(beta.ppf(edge, b, c + 1)) if b else 0.0
        high_b = float(beta.isf(edge, b + 1, c)) if c else 1.0
        lower = low_b / (1 - low_b)
        upper = high_b / (1 - high_b) if c else float("inf")
    return dict(zip(FIELDS, [n, (c + d) / n, (b + d) / n, (b - c) / n, discordant, statistic, p, odds, lower, upper]))
