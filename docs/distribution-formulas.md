# Probability, density and quantile formulas

Calculated columns and **Select and Transform** accept functions for the normal, Student t, chi-square, F and binomial distributions. Arguments can be numbers, columns or expressions, and a constant is repeated on every row. Function names are not case-sensitive.

| Formula | Result |
| --- | --- |
| `NORMDIST(x [, mean [, sd [, tail]]])` | Probability of the normal distribution. Defaults: mean 0, SD 1, tail `"left"`. |
| `NORMINV(p [, mean [, sd [, tail]]])` | Normal quantile, with the same defaults. |
| `NORMPDF(x [, mean [, sd]])` | Normal density. |
| `ZDIST(z [, tail])`, `ZINV(p [, tail])`, `ZPDF(z)` | The same operations with mean 0 and SD 1. |
| `TDIST(t, df)`, `TINV(p, df)`, `TPDF(t, df)` | Upper tail of Student's t, two-sided critical value and density. |
| `CHIDIST(x, df)`, `CHIINV(p, df)`, `CHISQC(x, df)` | Upper tail, upper-tail quantile and cumulative probability of chi-square. |
| `FDIST(x, df1, df2)`, `FINV(p, df1, df2)`, `FPDF(x, df1, df2)` | Upper tail, upper-tail quantile and density of F. |
| `BINOMIAL(k, n, p)` | Probability of k or more successes in n trials, P(K ≥ k). |
| `ERF(x)`, `ERFC(x)`, `PROBIT(p)` | Error function, its complement and 5 plus the left standard normal quantile. |

## Tails

The optional tail is a text value: `"left"`, `"right"`, `"one"` or `"two"`. Spaces around it and letter case do not matter.

- `"left"` is the cumulative probability P(X ≤ x). `"right"` is the upper tail P(X > x).
- `"one"` is the smaller of the two tails beyond x, measured from the mean. `"two"` is twice that tail.
- For `NORMINV` and `ZINV`, a probability alone cannot say on which side of the mean the value lies. With `"one"` and `"two"`, Trama returns the upper value, at or above the mean. `"one"` accepts p up to 0.5 and `"two"` up to 1. `"left"` and `"right"` need 0 < p < 1.
- `TINV(p, df)` is the value whose upper tail is p/2, so p is a two-sided probability. `CHIINV` and `FINV` return the value whose upper tail is p. These three accept 0 < p ≤ 1.

The tail can also come from a text column, such as `=ZDIST(Score, Tail)`. A cell in that column that does not name a tail leaves that row blank. A tail typed in the formula must be valid: an unknown one is reported when you confirm the formula, and nothing is stored.

## Missing values and domains

A problem on one row leaves only that row blank. This includes a blank or excluded source cell, an SD or degrees of freedom that are not positive, a negative x for chi-square or F, a probability outside its range, and a non-integer k or n for `BINOMIAL`. `BINOMIAL` needs 0 ≤ k ≤ n and 0 ≤ p ≤ 1, and allows n = 0. A result that is mathematically infinite, such as the F density at 0 with df1 below 2, is also blank. Numbers stored as text in a column are read as numbers. A text value typed where a number is expected, or the wrong number of arguments, is a formula error.

## Small tails

Upper tails and upper quantiles are computed directly rather than as 1 − p, so very small probabilities keep their precision. Compare `=1 - NORMDIST(8)`, which only keeps rounding noise, with `=NORMDIST(8, 0, 1, "right")`, which returns 6.22096e-16. `ERFC` keeps the small values of the complementary error function in the same way. A probability below about 1e-308 is stored as 0.

## Examples

Each formula can be pasted into a calculated column. The results are rounded to the digits shown.

| Formula | Result |
| --- | --- |
| `=NORMDIST(1.96)` | 0.975002 |
| `=NORMDIST(130, 100, 15, "right")` | 0.0227501 |
| `=ZDIST(-1.96, "one")` | 0.0249979 |
| `=ZDIST(1.96, "two")` | 0.0499958 |
| `=NORMINV(0.975, 100, 15)` | 129.39946 |
| `=ZINV(0.05, "two")` | 1.959964 |
| `=ZINV(0.05, "one")` | 1.644854 |
| `=ZINV(1e-12, "right")` | 7.034484 |
| `=ZINV(0.7, "one")` | blank |
| `=NORMPDF(0)` | 0.3989423 |
| `=TDIST(2.228, 10)` | 0.0250059 |
| `=TINV(0.05, 10)` | 2.228139 |
| `=TPDF(0, 1)` | 0.3183099 |
| `=CHIDIST(3.841, 1)` | 0.0500137 |
| `=CHIINV(0.05, 1)` | 3.841459 |
| `=CHISQC(5.991, 2)` | 0.9499884 |
| `=FDIST(4.96, 1, 10)` | 0.0500877 |
| `=FINV(0.05, 2, 20)` | 3.492828 |
| `=FPDF(1, 2, 2)` | 0.25 |
| `=BINOMIAL(8, 10, 0.5)` | 0.0546875 |
| `=BINOMIAL(2.5, 10, 0.5)` | blank |
| `=ERF(1)` | 0.8427008 |
| `=ERFC(10)` | 2.088488e-45 |
| `=PROBIT(0.975)` | 6.959964 |
| `=NORMDIST(8, 0, 1, "right")` | 6.22096e-16 |
| `=1 - NORMDIST(8)` | 6.66134e-16 |

Two-sided P value of a t statistic, and the matching 95% critical value:

```text
=2 * TDIST(ABS(COL("t ratio")), COL("df"))
=TINV(0.05, COL("df"))
```

Saving an `.alab` project keeps these formulas, and they are recalculated when the data change. A compatible ZIP project that uses them reopens with the formula still active and its column references mapped to the imported worksheet. A formula outside this contract keeps the stored values, as before.
