# Equivalence test (TOST) — 0.71

Choose **Group Comparison → Equivalence test (TOST)** to show that a difference is small enough to count as practically irrelevant. A non-significant t-test does not do that: it only fails to show a difference. The ordinary **t-test**, **Paired t-test (columns)** and **Lognormal t-test** are unchanged and keep their recipes.

You declare an **equivalence zone** before looking at the data: a lower and an upper margin around zero. The analysis then runs two one-sided tests and reports whether the whole interval of the difference lies inside the zone.

## Choices

| Field | Meaning |
|---|---|
| Design | **One-sample** (Response against a Reference value), **Paired**, **Student** (pooled variance) or **Welch** (separate variances). Default One-sample. |
| Response, Reference | One-sample only. The difference is mean(Response) − Reference. Reference is any finite number; zero is valid. |
| First, Second | The other designs. The difference is always **First − Second**. They must be two different numeric columns. |
| Lower margin, Upper margin | Finite numbers with Lower margin < 0 < Upper margin, in the units of the difference. The two margins may be unequal. They start at 0 and 0 so the dialog refuses to run until you declare them: Trama does not choose margins and does not present any as universal. |
| Alpha | Finite number with 0 < Alpha < 0.5; default 0.05. The interval level is 100 × (1 − 2 × Alpha), so 90% for Alpha 0.05. |

Fields that do not belong to the design are hidden, are not validated and are not written to the recipe; a stale value of a hidden field in an older recipe is ignored. Recipes keep the English field names and values whatever language the interface shows.

## How it is computed

Let *d* be the difference, *se* its standard error and *ν* the degrees of freedom.

* **One-sample:** *d* = mean − Reference, *se* = s/√n, *ν* = n − 1.
* **Paired:** First − Second on the rows where both cells are present; then as One-sample on the differences with *ν* = pairs − 1. A cell without its partner is not a pair.
* **Student:** pooled variance, *se* = s_p·√(1/n₁ + 1/n₂), *ν* = n₁ + n₂ − 2. **Welch:** *se* = √(s₁²/n₁ + s₂²/n₂) with the Welch–Satterthwaite *ν*. Missing cells are removed from each column separately.
* Lower test: t = (*d* − Lower margin)/*se*, p = P(T ≥ t). Upper test: t = (*d* − Upper margin)/*se*, p = P(T ≤ t). p TOST is the larger of the two.
* Interval: *d* ± t(1 − Alpha, *ν*)·*se*.
* **Equivalent** only when both p values are below Alpha **and** the interval lies strictly inside (Lower margin, Upper margin). The two rules agree except at an exact tie (the interval ends on a margin), where requiring both keeps the result "Not demonstrated". The decision uses the unrounded numbers.

Otherwise the result is **Not demonstrated**: the data do not show equivalence at this zone and Alpha. The text never says "different" or "not equivalent".

## Results

* **Equivalence summary** (one row): design, labels, N first and N second (blank for One-sample, never an invented zero), Difference, SE, df, margins, Alpha, interval level and limits, both t and p values, p TOST, Conclusion and Status / Reason. One-sample labels the second quantity "Reference (value)".
* **Equivalence tests** (two rows): the lower and upper null hypotheses written out with the margin and the orientation, the statistic, df, p, Alpha and whether the null is rejected.
* **Data used**: the observations that entered the test with their original **Source row**. For Paired, First, Second and their difference on the complete pairs. Excluded cells and incomplete pairs are not rebuilt.
* **Settings**: design, orientation, margins, Alpha, the decision rule and the scope.

The figure shows the estimate and its interval (a diamond with caps), the two margins (dashed lines labelled with their value), the zero line (dotted) and the zone (a labelled shaded band). The axis names the orientation, First − Second (Sample − Reference for One-sample). The title repeats the table's conclusion; the figure decides nothing. The Inspector and Format Graph work as on other graphs.

## When inference is unavailable

A zero standard error, a difference or standard error outside the floating-point range, or a degenerate df gives **Inference unavailable** with the reason. Representable variation is retained even with a large common offset; no threshold proportional to the original measurements suppresses it. Counts and valid statistics stay in the table, p values and intervals are blank, and the tests table says "Not available". A non-finite or non-numeric cell in a column you chose, a missing column, First equal to Second, fewer than two values (or two complete pairs), or an invalid margin or Alpha stop the dialog on the field to correct.

For extreme units the figure uses a labelled power-of-two display multiplier to keep its coordinates renderable. Tables and legend values remain in the input units.

## Not included

Non-inferiority, equivalence of a ratio of lognormal means, summary mean/SD/N input, pairing by a Subject column in long format, repeated measures, bootstrap, Bayesian methods, multiple-comparison corrections, regulatory limits and clinical claims. Margins depend on the scientific question; Trama does not validate them.

## Reference

D. J. Schuirmann (1987), *A comparison of the two one-sided tests procedure and the power approach for assessing the equivalence of average bioavailability*, Journal of Pharmacokinetics and Biopharmaceutics 15, 657–680. https://doi.org/10.1007/BF01068419

