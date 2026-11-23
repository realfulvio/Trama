# Lognormal t-tests and ratios — 0.70.0

Choose **Group Comparison → Lognormal t-test** for positive data whose logarithms are roughly normal (concentrations, titres, intensities). The result is a **ratio of geometric means** with its confidence interval. The ordinary **t-test** and **Paired t-test (columns)** are unchanged and keep their recipes.

## Choices

| Field | Meaning |
|---|---|
| Design | **Paired** (complete pairs), **Welch**, **Student** (independent samples) or **One-sample** (First against a hypothetical geometric mean). Default Paired. |
| Sample format | Put the two samples in separate measurement columns, or use one measurement column with a group column. One-sample uses First only. |
| First, Second | Two different numeric columns in the two-column format. |
| Measurement, Group, Subject | In the grouped format, select the measurement and the column with two group levels. Paired also requires a subject ID. Each subject can have one measurement per group. |
| First group | Select the group used as First in the ratio. The recipe saves the label so a change in row order does not change the direction. |
| Report ratio | First / Second (default) or Second / First. Reversing only changes the sign of the log ratio and of t. |
| Null ratio | Positive finite value tested against; default 1. It moves t and P, not the estimate or its interval. |
| Hypothetical geometric mean | Positive finite; One-sample only. The reported ratio is the sample geometric mean divided by it (or the reverse). |
| Confidence level (%) | Real number with 0 < level < 100; default 95. The interval is always two-sided, also for one-sided P values. |
| Alternative | Two-sided, Greater or Less. |
| Log base | 10 or e. Only *Mean log ratio*, *SE log ratio* and the log limits depend on it. |
| Graph | Ratio estimation (default), Log observations, Log ratios (Paired and One-sample only) or None. |
| Pairing correlation | Paired only: Pearson r and its two-sided P for the log values of the two columns (at least three complete pairs and varying logs). It is not proof that the pairing was effective. |

Inactive fields are not validated and are not written to the recipe. Booleans are not accepted as a level, a ratio or a reference. Column names are literal.

## How it is computed

The test works on the natural logarithms and subtracts logs instead of computing `log(a / b)`, so a ratio that would overflow still has finite logs and inference. Observations are never scaled or shifted.

* **Paired:** complete pairs are chosen first, then positivity is checked on those rows only: a zero on a row without the other measurement is ignored. `delta = mean(log A − log B)`, `SE = SD(log A − log B)/√N`, `df = N − 1`.
* **One-sample:** `delta = mean(log A) − log(reference)`, `SE = SD(log A)/√N`, `df = N − 1`.
* **Student:** difference of the log means, pooled log variance, `df = n₁ + n₂ − 2`. **Welch:** `SE = √(s₁²/n₁ + s₂²/n₂)` with Welch–Satterthwaite df. Missing values are removed from each column separately.
* `t = (delta − log(Null ratio)) / SE`; the interval is `exp(delta ± t_crit·SE)`.

At least two observations per sample, or two complete pairs, are needed. A non-numeric, infinite or non-positive value on a row that is used is an error on First, Second or Measurement, naming the source row.

### Limits

* **SE = 0:** the estimate is kept, Status is *Inference unavailable*, t, P and the limits are empty and Reason says why. The zero test allows for the rounding of the logarithms (about `8·ε·(1 + |log values|)`), so ratios that are constant only up to floating-point noise are degenerate too, while measurable variation is kept. This tolerance is a Trama choice.
* **Ratio overflow:** when `exp` overflows or underflows, that result stays empty (never `inf` or a false zero), the logs and the test stay finite and Status is *Ratio overflow*. The graph then draws no point and prints the numeric limit.

## Result sheets

* **Lognormal test** (one row): N first, N second (0 for One-sample), Mean log ratio, SE log ratio, Log lower, Log upper, t, df, p, Geometric ratio, Lower, Upper, Status, Reason. N counts the selected samples in their saved order.
* **Log observations:** Source row, Sample (column name or group label), Value, Log value in the chosen base. Paired uses only complete pairs.
* **Paired ratios** (Paired only): Source row, First, Second, Log ratio, Ratio in the chosen orientation (empty on overflow). Grouped input reports the Subject and both source rows.
* **Settings:** every choice, the ratio definition with the column names, the null ratio, the reference used and the pairing correlation.

*Source row* is the index received by the analysis (original row labels, never renumbered), so CSV and **Use Result as Data** keep it.

## Graphs

* **Ratio estimation:** estimate and interval on a logarithmic axis with the Null ratio as reference. A missing interval does not stop the point.
* **Log observations:** transformed values per sample with the mean. Paired values are joined by row for separate measurement columns and by subject for grouped input.
* **Log ratios:** one point per pair (or per observation against the reference), the mean with its interval and the reference `log(Null ratio)`.

Titles and axes state the log base and the ratio orientation. Colors, the Inspector and Format Graph work as for any graph.

## Checks

```sh
python verify.py                      # independent references (from the package)
python verify.py --repo <checkout>    # real dispatcher against them
xvfb-run -a -s '-screen 0 1024x768x24' python -m unittest discover -s tests -q
TRAMASTAT_SMOKE_ONLY=lognormal-tests xvfb-run -a -s '-screen 0 1024x768x24' python tramastat.py --smoke /tmp/trama-lognormal
```

Fixtures live in `tests/data/lognormal_tests_070/` and are the authority for the numbers. Windows was not exercised from Linux.

