# Meta-analysis of effect estimates

Choose **Data Exploration and Summary → Meta-analysis of effect estimates** (Italian: *Esplorazione e sintesi dei dati → Meta-analisi delle stime*) when you have one effect estimate and its standard error for each of several independent studies and want one pooled effect. The question it answers is: **what is the combined effect, how precise is it, and how much do the studies disagree?**

The legacy **Forest plot** (Graphing) is unchanged: it draws intervals you already have and keeps its recipes. The new method computes the pooled estimate and draws its own forest figure with a pooled diamond.

## Data

One row per independent study.

| Field | Meaning |
|---|---|
| Study | Optional. Text labels; a blank label becomes *Row n*. Duplicate labels and characters such as `$` are kept as written. |
| Estimate | The effect of each study. A decimal comma is accepted. |
| Standard error | Its standard error, greater than zero. |
| Measure | **Difference** (mean difference, risk difference, log values…) or **Ratio** (odds, risk or hazard ratio). |

With **Ratio** you enter the ratios as they are (for example `1.25`, never its logarithm), and as standard error the **SE of ln(ratio)**: the caption of the field changes to *SE of ln(ratio)* and a highlighted note repeats this. Pooling, Tau² and the pooled SE are on the natural-log scale; the estimate and every limit are shown back as ratios, exponentiated once. A ratio must be greater than zero.

A blank or excluded estimate or SE omits the row; the *Pooled* sheet counts the omitted rows. Any other bad cell (text, an infinite value, an SE of 0 or less, a ratio of 0 or less) stops the analysis on its field with the source row, counted from 1 as in the worksheet. From 2 to 200 studies.

## Model and output

| Field | Meaning |
|---|---|
| Pooling model | **Common effect** (one true effect; weights 1/SE²) or **Random effects (Paule–Mandel)** (the true effects vary with variance τ²; weights 1/(SE² + τ²)). |
| Random interval | Random effects only. **Modified Knapp–Hartung** (default) or **Normal**. |
| Confidence level (%) | Strictly between 0 and 100 (default 95). |
| Prediction interval | Random effects only. Off by default. |
| Leave one out | Repeats the chosen model omitting one study at a time. It can be cancelled between two omissions. |
| Show graph | Draws the forest figure (default on). |

### How it is computed

* **Cochran's Q** is computed with τ² = 0: `Q = Σ wᵢ (yᵢ − m)²`, `wᵢ = 1/SEᵢ²`, with k − 1 degrees of freedom. **Q p** is the upper-tail probability of the chi-square: a small value says the studies disagree more than their standard errors explain. It is not the p value of the pooled effect. **I² = max(0, 1 − (k − 1)/Q)** in percent.
* **Paule–Mandel τ²** is 0 when Q(0) ≤ k − 1; otherwise it is the root of `Q(τ²) = k − 1` on the bracket `[max(0, S/(k − 1) − max SEᵢ²), S/(k − 1) − min SEᵢ²]`, with `S` the sum of squares of the estimates around their plain mean. The root must converge; there is no silent fall-back to another estimator.
* **Modified Knapp–Hartung**: `q⋆ = Q(τ²)/(k − 1)`, `SE = √(max(1, q⋆) / Σwᵢ)`, quantile of *t* with k − 1 degrees of freedom. The variance is never shrunk below the normal one. **Normal** uses `SE = √(1/Σwᵢ)` and the normal quantile.
* **Prediction interval** (approximate): `m ± t(k − 2) · √(τ² + SE²)`, only with random effects and at least 3 studies; otherwise the *Prediction status* column says why it is missing.
* Values are rescaled by a power of two before the calculation, so units from 1e−150 to 1e150 give the same answer; standard errors too far apart to be combined are refused on their field.

## Results

1. **Studies** — Study, Source row, Estimate, Standard error, Lower, Upper, Weight (%) of the chosen model.
2. **Pooled** — Studies, Omitted studies, Pooling model, Interval method, Estimate, SE (on the analysis scale, ln for ratios), Lower, Upper, Prediction lower, Prediction upper, Prediction status, Confidence level (%).
3. **Heterogeneity** — Q, Q df, Q p, I² (%), Tau² (empty with Common effect).
4. **Leave one out** (when requested) — Omitted source row, Omitted study, Studies, Estimate, Lower, Upper, Tau², Status. With two studies an omission leaves one and the status says so.

The figure draws each study interval, a square whose area is proportional to its weight, the pooled diamond from Lower to Upper (SVG id `meta-pooled-diamond`), the prediction interval on its own row and a dashed no-effect line at 0 or 1 (`meta-null-reference`); a ratio uses a log axis. Labels are literal text. The figure can be styled with Format Graph and the Inspector, and placed in layouts.

## Example

`tests/data/meta_analysis/differences.csv`: four studies with estimates 0.2, 0.6, 1.0, 1.4 and SE 0.2.

| | Common effect | Random effects, modified Knapp–Hartung |
|---|---|---|
| Estimate | 0.8 | 0.8 |
| SE | 0.1 | 0.2582 |
| 95% interval | 0.6040 to 0.9960 | −0.0217 to 1.6217 |
| Q (3 df), Q p | 20, 0.00017 | 20, 0.00017 |
| I² | 85% | 85% |
| Tau² | — | 0.22667 |
| 95% prediction | — | −1.5303 to 3.1303 |

The equal weights keep the estimate at 0.8; the heterogeneity widens the random-effects interval, and q⋆ = 1 at the Paule–Mandel root, so the Knapp–Hartung SE equals the plain random-effects SE.

## Limits

* The studies must be independent; several estimates from the same study are not supported.
* With few studies τ² is imprecise. With 2 studies the Knapp–Hartung interval uses *t* with 1 degree of freedom and is very wide, and no prediction interval is given.
* The prediction interval is the usual approximation; it ignores the uncertainty of τ².
* There are no publication-bias tests, subgroups or meta-regression.
