# Detailed correlation — 0.72

**Data Exploration and Summary** keeps the existing **Correlation** sheet. **Detailed results** is off unless the recipe says so. Two analyses sit beside it: **Correlate against control** and **Compare independent correlations**. The correlation matrix is unchanged.

Intervals are always two-sided at the chosen confidence level, including when the test itself is one-sided. Trama states that in the dialog and in Settings. These are Trama's calculations. They are not a claim of identity with another statistics product.

## Correlation

| Field | Meaning |
|---|---|
| X, Y | Two different numeric columns. A row is used only when both cells are present. Text or an infinity stops on that column. |
| Method | Pearson, Spearman or Kendall. |
| Detailed results | Off by default. Off, or anything other than yes, keeps the three-row sheet (N, coefficient, p) and ignores the fields below. |
| Alternative | Two-sided, Positive (ρ > 0) or Negative (ρ < 0). Default Two-sided. |
| Confidence level (%) | Finite, strictly between 0 and 100. Default 95. |
| Spearman p values | Automatic, Exact or Approximate. Shown for every detailed correlation and enabled only for Spearman. |

Pearson uses a coefficient that does not change when both columns are rescaled by a positive constant. The p value under ρ = 0 is the beta equivalent of the usual t statistic on n − 2 degrees of freedom. R² is reported only for Pearson. The interval is Fisher z, SE = 1/√(n − 3), for n ≥ 4. At n = 3 the limits are blank and the reason says why. A coefficient of exactly ±1 with n ≥ 4 gives a degenerate interval at that value. A column with any representable variation is not treated as constant.

Spearman ranks with average ranks for ties, then applies Pearson to the ranks. **Exact** uses the observed ranks, ties included, and the permutation distribution of the Y order. The two-sided tail is the absolute centered score at least as large as the one observed; a one-sided tail includes the observed score. Tied asymmetric distributions are not folded by doubling the smaller tail. The **Extended (17 pairs)** budget supports up to 17 complete pairs with work and storage checks. **Standard (9 pairs)** retains the original nine-pair policy. Existing recipes without a budget keep Standard; new dialogs default to Extended. **Automatic** uses approximation with a reason when a limit is exceeded, while **Exact** rejects rather than silently substituting. See [extended exact testing](spearman-exact-extended.md) for resource and cancellation details. The approximation is t = ρ √((n − 2) / (1 − ρ²)) on n − 2 degrees of freedom; a perfect coefficient gives p of 0 or 1 according to the tail. The Spearman interval is Bonett–Wright for n ≥ 11: artanh(ρ) ± z √((1 + ρ²/2) / (n − 3)), then tanh. Below 11 the limits are blank. Spearman has no R².

Kendall is tau-b with the asymptotic p value and the selected alternative. There is no tau interval: the limits are blank and the reason says so. The Spearman control is ignored.

The result keeps N, coefficient and p in the first three rows, then the limits, R², the p method, the interval method and the reason. **Pairs** lists Source row, X and Y for the complete pairs, in sheet order. Source row is the sheet index, including a string, a duplicate or a gap. **Ranks** is added only for Spearman. The scatter uses the original values, not the ranks, and draws no regression line.

## Correlate against control

X is the shared column. Variables is one to 24 distinct responses, none equal to X. Pearson or Spearman, the same alternative, level and Spearman option, pairwise or listwise deletion, a p adjustment (none, Holm or Benjamini–Hochberg) and Show intervals.

Pairwise keeps, for each response, the rows where X and that response are both present. Listwise keeps the rows where X and every chosen response are present. A constant response, or one with fewer than three complete pairs, stays in the table as Unavailable with a reason. The others are still calculated. If none can be calculated, the error is on Variables. An explicit Exact request past the budget is an error on the Spearman option, not a silent approximation.

Only finite p values are adjusted, and only as many as are finite. Intervals are not adjusted. They stay pointwise: adjusting the p values does not make them simultaneous. Settings and the figure legend say so.

The table has one row per response, in the chosen order: variable, N, coefficient, p, adjusted p, limits, R², p method, interval method, status and reason. The figure draws the available coefficients on −1…1, with a zero line and the worksheet names as literal text (`$x$` is not mathematics). Sample size and method are in the legend. A missing interval is not drawn. Show intervals off hides the bars and leaves the points and the table.

## Compare independent correlations

The sheet is long: X, Y and Group. Exactly two non-missing groups are used, in the order they first appear. Each row belongs to one group. Text and numbers are preserved, so `1` and `"1"` are different groups, and a boolean is not the number 1. Missing group cells are omitted and counted. Group cannot be X or Y. Each group needs at least four complete pairs and variation in both columns.

The two Pearson coefficients and their own Fisher intervals are computed as above. The comparison is unavailable when either coefficient is exactly ±1: the estimates and their intervals stay, and no finite z is invented by clipping. Otherwise z₁ = artanh(r₁), z₂ = artanh(r₂), SE = √(1/(n₁−3) + 1/(n₂−3)) and Z = (z₁ − z₂) / SE. Two-sided p is 2·P(Z ≥ |Z|). Positive tests ρ₁ > ρ₂ and Negative tests ρ₁ < ρ₂. Difference = r₁ − r₂ is descriptive. The inferential interval is the Fisher z difference. It is not transformed back to r and it is not labelled as an interval for the difference of the coefficients.

The groups are assumed experimentally independent. The dialog says so. Trama does not check the study design, and it does not compare more than one pair of groups, dependent correlations, or Spearman.

The figure shows the two coefficients and, unless Show intervals is off, their pointwise intervals, on −1…1.

## Not included

Bootstrap intervals, partial correlation, a test of dependence between the two correlations, causal language, every pair of groups, and any change to the correlation-matrix engine.

