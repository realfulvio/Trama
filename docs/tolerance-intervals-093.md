# Tolerance intervals — 0.93

Choose **Data Exploration and Summary → Tolerance intervals** (next to Descriptive statistics) to find the range that should contain a stated share of **all individual values** of a population, for example "90% of the units of a lot", with a stated confidence. It answers a different question from a confidence interval:

| | Describes | Gets narrower with more data? |
|---|---|---|
| Confidence interval of the mean | where the **average** probably lies | yes, it shrinks towards a point |
| Tolerance interval | where **individual values** probably lie | no, it settles near the real spread of the population |

Descriptive statistics, Normality tests and every other analysis are unchanged and keep their recipes.

## Two percentages

* **Population coverage (%)** is the share of all values the interval should contain. Default 90.
* **Confidence level (%)** is how sure you want to be that the interval really contains at least that share. Default 95. Read it as a long-run statement: building the interval this way on many independent samples, about 95% of the intervals would contain at least the stated coverage.

Both must be finite and strictly between 0 and 100. The dialog repeats this explanation under the fields.

## Choices

| Field | Meaning |
|---|---|
| Variables | One to 24 numeric columns, each analysed on its own. Nothing is preselected. |
| Group | Optional. One interval per group and variable, groups in order of first appearance, at most 48. Rows with an empty group are left out and counted in **Settings**. |
| Distribution | **Normal** (default) or **Distribution-free**. |
| Sides | **Two-sided** (default), **Lower** (a limit below which only a small share lies) or **Upper**. |
| Population coverage (%), Confidence level (%) | As above. 90 and 95. |
| Show graph | Off by default. |

Recipes keep the English field names and values whatever language the interface shows.

## How it is computed

*n* values, mean *x̄*, sample standard deviation *s*, coverage *P*, confidence *γ*.

* **Normal, two-sided** (Howe approximation): *k₂* = z((1+*P*)/2) · √[(*n*−1)(1+1/*n*) / χ²(1−*γ*; *n*−1)], limits *x̄* ± *k₂*·*s*. χ²(1−*γ*; *n*−1) is the lower (1−*γ*) quantile of the chi-square distribution.
* **Normal, one-sided** (exact): *k₁* = (quantile *γ* of the noncentral *t* distribution with *n*−1 degrees of freedom and noncentrality z(*P*)·√*n*) / √*n*. Lower limit *x̄* − *k₁*·*s*, upper limit *x̄* + *k₁*·*s*. The quantile is checked against its own tail probability; a value that fails the check is reported as "Calculation unavailable", never as a number.
* **Distribution-free**: no assumption about the shape. The limits are order statistics. Two-sided, the interval is *x*(r) to *x*(n−r+1) and its confidence is P(Beta(*n*−2r+1, 2r) ≥ *P*); one-sided, the limit is *x*(r) or *x*(n−r+1) and the confidence is P(Beta(*n*−r+1, r) ≥ *P*). Trama takes the **largest rank *r*** that still reaches the confidence you asked for, which gives the narrowest valid interval. The confidence usually overshoots a little; it is reported as **Achieved confidence (%)**. When even *r* = 1 (the extreme values) falls short, the sample is too small: the row says **Insufficient sample** and **Maximum confidence (%)** shows the best confidence the sample can give.

Means and standard deviations come from values scaled by a power of two and a corrected two-pass sum, so a large common shift (1 000 000 000 added to every value) or a very large or small unit does not change the spread, and confidence levels very close to 0 or 100 keep their precision.

## Results

* **Tolerance intervals**, one row per variable and group: Variable, Group, N, Mean, SD, Lower, Upper, k factor, Lower rank, Upper rank, Achieved confidence (%), Maximum confidence (%), Status. The Normal method fills Mean, SD and k factor; Distribution-free fills the ranks and the two confidences (Mean and SD are still shown for orientation). A cell that does not apply is empty, never 0.
* **Settings**: method and formula, distribution, sides, both percentages, variables and group, missing values omitted per variable, rows without a group, and the interpretation.

Status values: **OK**; **Insufficient sample** (one value, or too few for the distribution-free rank); **Variance not measurable** (all values equal, so a Normal interval has no width to report); **Calculation unavailable** (a number that cannot be computed reliably).

Distribution-free confidence is exact for independent observations from a continuous population. When the sample has repeated values (rounding, resolution), the confidence is approximate and **Settings** lists the samples concerned.

## Figure

With **Show graph** the figure has one panel per variable and one row per group. A two-sided interval is a horizontal segment with end caps (Line2D `tolerance-interval-N`, numbered in the order of the valid rows). A one-sided limit is a single triangle pointing towards the values the limit bounds (`tolerance-limit-N`). A row without a valid interval is labelled with its status and nothing is drawn, so the axes never contain infinite values. Inspector colour and visibility apply to a group in every panel at once; Format Graph title and axis labels reach the first panel only. SVG, PDF and PNG exports keep the segment ids.

## Limits

Up to 100 000 observations per variable, 24 variables, 48 groups and 192 variable-group pairs. The dialog names the field and the number when a limit is exceeded.

## Reproducible example

The packaged measurements are in `tests/data/tolerance_093/measurements.csv` (synthetic: Lot A has 60 values 1 to 60, Lot B has 12 values 81 to 92). Import the file, then **Analyze → Data Exploration and Summary → Tolerance intervals**, Variables = Signal, Group = Group, leave 90 / 95 and Normal / Two-sided, Run Analysis.

| Group | N | Mean | SD | k factor | Lower | Upper |
|---|---|---|---|---|---|---|
| Lot A | 60 | 30.5 | 17.46425 | 1.957811 | −3.691692 | 64.691692 |
| Lot B | 12 | 86.5 | 3.605551 | 2.654715 | 76.928287 | 96.071713 |

Change Sides to **Upper**: the lower limit goes away and Upper becomes 58.598459 (Lot A, *k₁* = 1.608913) and 94.468743 (Lot B, *k₁* = 2.210132). Change Distribution to **Distribution-free** with Sides **Lower**: Lot A shows Lower rank 2, Lower 2, Achieved confidence 98.62%, Maximum confidence 99.82%; Lot B shows **Insufficient sample** with Maximum confidence 71.76%, because 12 values cannot support a 90% / 95% one-sided limit.

The same example from Python:

```python
import pandas as pd
from analisi.workbench import analyse

frame = pd.read_csv("tests/data/tolerance_093/measurements.csv")
result = analyse("Tolerance intervals", frame, {"Variables": ["Signal"], "Group": "Group"})
print(result.tables["Tolerance intervals"])
```
