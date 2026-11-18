# Restricted mean survival time

Choose **Survival Analysis → Restricted mean survival time** (Italian: *Analisi di sopravvivenza → Sopravvivenza media ristretta*) to summarise a survival curve with one number in the units of time. The question the analysis answers is: **over the first τ units of follow-up, how long does a subject survive on average?** That number, the RMST, is the area under the Kaplan–Meier curve from 0 to the horizon τ. With two groups the analysis also reports the difference and the ratio of the two areas.

Unlike the median, the RMST exists even when the curve never falls to one half, and unlike a hazard ratio it does not assume proportional hazards. It does depend on τ: always state the horizon with the result. Kaplan–Meier, Cox regression and Competing risks are unchanged and keep their recipes.

## A worked example

The 12-subject example `tests/data/rmst/fixtures/cohorts.csv` has two synthetic cohorts, *Reference* and *Series $B* (the dollar is part of the name and is shown literally). Reference is observed up to 8 and Series $B up to 9, so the largest usable horizon is 8. With τ = 6.5:

| Group | RMST | SE | 95% CI |
|---|---|---|---|
| Reference | 4.2778 (= 77/18) | 0.9288 | 2.4574 to 6.0982 |
| Series $B | 5.0000 | 0.9742 | 3.0906 to 6.9094 |

Series $B gains 0.7222 time units over the first 6.5 (95% CI −1.9159 to 3.3603, p = 0.592); the ratio of the areas is 1.1688 (0.6598 to 2.0705, p = 0.593). The two curves cross before τ, which is exactly the case where a hazard ratio is hard to read and the RMST is not.

## Choices

The dialog has two pages, **Data** and **Codes and estimate**.

| Field | Meaning |
|---|---|
| Time | Numeric column of times of 0 or more, all measured from the same origin. |
| Status | The column that says whether each subject had the event. Whole-number codes or text, one kind per column; booleans, complex numbers and a mix of numbers and text are refused. |
| Group | Optional. Leave it empty for one cohort, called *All*, or choose a column with **exactly two** groups among the complete rows. |
| Reference group | Shown only with a Group. The group the other is compared with; it comes first in every sheet. The dialog proposes the first group when the field is empty, and the recipe always saves the choice. |
| Horizon | Required, no default: the τ of the analysis, in the units of the Time column, greater than 0 and no larger than the longest observed time of **every** group (equality is allowed). The line under the field shows the largest usable horizon for the columns chosen. A decimal comma is accepted. |
| Event code | The status of a subject who had the event (default `1`). |
| Censor code | The status of a subject who was censored (default `0`). It must differ from the event code. For a text column the code is read as typed, spaces included; for a numeric column `1`, `1.0` and `01` are the same code. |
| Confidence level (%) | Level of the Wald intervals and of the tests (default 95). |
| Show graph | Draws the curves and the shaded areas. |

A row is used only when it has a value for every role you chose (time, status and, when chosen, group); a cell you exclude counts as missing. The *Settings* sheet reports how many rows were complete and how many were not. Group names stay as they are written in the worksheet, in every language.

## How it is computed

For each group the observed times are grouped by distinct value. With `n(t)` the subjects whose time is at least `t` (a censoring at `t` still counts as at risk) and `d(t)` the events at `t`, the Kaplan–Meier curve is the right-continuous step function

```text
S(t) = Π over event times u ≤ t of (1 − d(u) / n(u))
```

and the RMST is the exact area of its rectangles from 0 to τ. Events at τ itself are counted in *Events through horizon* but do not change the area. The variance is the integrated Greenwood sum over the event times before τ,

```text
Var = Σ over event times t < τ of  d(t) / [n(t) (n(t) − d(t))] · A(t)²,   A(t) = area of S from t to τ
```

computed with a backward cumulative sum, in units of τ so that changing the time unit changes the result only by that factor. The interval is the asymptotic two-sided Wald interval `RMST ± z · SE`, not truncated.

With two groups:

- **Difference** = compared − reference, SE = √(SE₁² + SE₂²), Wald interval and two-sided normal p value against 0.
- **Ratio** = compared / reference, with delta-method inference on the log scale: SE(log ratio) = √((SE₁/RMST₁)² + (SE₂/RMST₂)²); the interval is transformed back and the p value tests log ratio = 0.

Swapping the reference changes the sign of the difference and turns the ratio into its reciprocal, with the limits exchanged; the p values do not change.

Reference values come from an exact rational oracle on the package fixtures and on random datasets, and from `survRM2` 1.0.4 (R 4.3.3) on three further datasets: continuous times, heavy ties, and events at time zero and at the horizon. They live in `tests/data/rmst` and are never read by the program itself.

## Results

In this order:

1. **RMST** — one row per group, the reference first: N, Events through horizon, Max follow-up, Horizon, RMST, SE, CI lower, CI upper, Status.
2. **RMST comparison** — only with a Group: one row for the Difference and one for the Ratio, with Compared group, Reference group, Estimate, Inference SE, Scale (Identity or Log), CI lower, CI upper, p and Status.
3. **Integration steps** — the rectangles of the area for each group: Left, Right, Survival and Area; the Area column of a group adds up to its RMST.
4. **Settings** — columns, codes, groups, horizon, largest usable horizon, level, complete and incomplete rows, and how estimates, variance, intervals and the comparison are computed.

The **Status** column says **OK**, or why an interval or a test is empty:

- **Zero variance** — the SE is 0, typically when there are no events before τ: the estimate stands, the interval and the p value are empty.
- **Undefined ratio** — the reference RMST is 0, so the ratio has no value.
- **Log inference unavailable** — the compared RMST is 0: the ratio is 0 but its logarithm, and so its interval and p value, do not exist.

The graph has one axis: X from 0 to τ, Y the survival probability from 0 to 1, the step curve of each group, its area shaded with a transparency that keeps overlaps readable, and a dashed vertical line at τ. The drawn objects have stable ids for styling and for SVG: `rmst-curve-0`, `rmst-curve-1`, `rmst-area-0`, `rmst-area-1` and `rmst-horizon` (with one cohort only the 0 ids exist). Format Graph, the Inspector and layouts work as for any graph and never recalculate the estimate. **Graph settings…** on the graph page reopens the Codes and estimate page. **Use result as data** works on every sheet.

## Limits

Up to 50,000 complete rows, refused on Time before any calculation. In the test environment (a 2.3 GHz Xeon) fifty thousand rows in two cohorts with almost every time distinct take about 15 ms without the graph and 24 ms with it.

## Errors and recovery

Every error names its field, opens the page that holds it and keeps the dialog open with what you typed: no time or status column, a negative or non-numeric time, a status that is neither the event code nor the censor code (with the first source row), equal codes, a Group with one or three groups, a reference that is not one of the two groups, an empty horizon, or a horizon beyond the follow-up, which names the group that ends first and how far it is observed.

A worksheet edit that makes a saved analysis impossible — for instance removing the last observation of a group so that its follow-up now ends before τ — keeps the last good result, marks it as out of date, and reopens the dialog on **Horizon** with the reason and the new largest usable horizon. Correct the horizon and run again; Cancel keeps the old result marked as out of date.

## What it is not

Not included: covariates (adjusted RMST), more than two groups or multiple comparisons, bootstrap or simultaneous intervals, delayed entry, weights, competing risks and the choice of τ from the data. The intervals are asymptotic and can be fragile with few events.
