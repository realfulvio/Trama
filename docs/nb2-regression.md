# Negative binomial regression

Choose **Regression and Curves → Negative binomial regression** (Italian: *Regressione e curve → Regressione binomiale negativa*) for counts — events, colonies, visits, defects — whose spread is larger than Poisson regression allows. In a Poisson model the variance equals the mean; real counts are often **overdispersed**, and Poisson then reports standard errors that are too small and p values that are too optimistic. The negative binomial model (NB2) adds one dispersion parameter α and keeps the same mean model, so the estimates and the incidence rate ratios read exactly as in Poisson regression.

Poisson regression in **Multiple regression** is unchanged and keeps its recipes.

## The model

```text
log μᵢ = xᵢβ + log(exposureᵢ)        Var(Yᵢ) = μᵢ + α μᵢ²
```

`exp(β)` is an **incidence rate ratio** (IRR): the factor by which the expected count per unit of exposure changes for one unit of a numeric predictor, or against the reference level of a categorical one. With α → 0 the model becomes Poisson.

## Choices

| Field | Meaning |
|---|---|
| Response | Counts: whole numbers of 0 or more. At least one count must be above 0. |
| Predictors | 1 to 8 columns. Numeric unless they are also chosen as categorical. |
| Categorical predictors | Optional, among the predictors. Each needs 2 to 100 levels among the complete rows; the first level in sorted order is the reference (the *Reference levels* sheet). Terms are named as in Multiple regression, for example `Batch [B]`. |
| Exposure | Optional. Time, area or volume of each row, finite and greater than 0; it enters as the offset `log(exposure)`. Without it every row has exposure 1. |
| Dispersion mode | **Estimated ML** (default) fits α together with the coefficients by maximum likelihood. **Fixed** uses the α you type. |
| Dispersion alpha | Shown and read only with **Fixed**: from 0.000001 to 1000 (default 0.5), a decimal comma accepted. Under Estimated ML a hidden value that still parses stays in the recipe; one that does not is left out and never blocks the analysis. |
| Confidence level (%) | Wald intervals of the coefficients and of the IRR, strictly between 0 and 100 (default 95). |
| Residual plot | Pearson residuals against the fitted counts. |

A row is used only when it has the response, every predictor and the exposure (when chosen). An empty cell or an excluded cell counts as missing; a zero count is a value. *Model fit* reports how many rows were incomplete. A cell that is present but unusable — a negative or fractional count, text in a numeric predictor, an exposure of 0 — stops the analysis and the message names the column, the row (counted from 1 as in the worksheet) and the value.

Limits, checked before the design matrix is built: 50,000 complete rows and 32 coefficients (intercept and dummy columns included).

## How it is computed

For a given α the coefficients maximise the NB2 log likelihood by Newton's method on the observed information, with step halving. The observed information of β is always positive definite, so each Newton step is an ascent direction; the iteration stops on the size of the step, which also means that a category or a range whose counts are all zero (separation) is reported as *did not converge* instead of returning a meaningless estimate. Columns are rescaled by their largest magnitude for the solver and the estimates are scaled back.

**Fixed.** α is the value typed. The covariance of β is the inverse of the Fisher information `Σ xᵢxᵢᵀ μᵢ/(1 + αμᵢ)`.

**Estimated ML.** The profile log likelihood of α is first evaluated on 37 points (four per decade from 10⁻⁶ to 1000) to bracket the maximum; then the score of α is solved inside the bracket. The estimate is accepted only strictly inside the supported range. If the likelihood keeps increasing toward α = 0, the counts are not overdispersed: this is the **Poisson boundary** and there is no ML estimate — the message suggests Fixed dispersion or Poisson regression. If it keeps increasing beyond α = 1000, the same holds at the other end. The covariance of β is the β block of the inverse of the **joint** observed information of (β, α), so the uncertainty of α is carried into the standard errors. When the Hessian is not finite, not positive definite or nearly singular the analysis stops on *Dispersion mode*.

The log likelihood keeps every constant (`log Γ` terms included), so *Log likelihood* and *AIC* are comparable with other count models fitted to the same rows. AIC counts α as a parameter only under Estimated ML.

The score and the curvature of α use stable forms for small αμ and cumulative sums for counts up to 200,000 (digamma and trigamma beyond). The reference values of the tests come from a closed-form oracle (two saturated groups), statsmodels (GLM with known α and the discrete NB2 model) and `scipy.stats.nbinom`; they live in `tests/data/nb2_regression` and `tests/test_nb2_regression.py` and are never read by the program itself.

## Results

1. **Coefficients** — one row per term: Estimate, SE, p, Lower, Upper (log scale), IRR, IRR lower, IRR upper.
2. **Model fit** — N, Incomplete rows, Dispersion mode, Alpha, Parameters, Log likelihood, AIC, Covariance (*Fisher information (alpha fixed)* or *Observed information (joint beta and alpha)*).
3. **Fitted values** — one row per complete row: Source row (the worksheet row, from 1), Observed, Exposure, Fitted count, Fitted rate (count per unit of exposure), Variance (`μ + αμ²`), Pearson residual.
4. **Reference levels** — only with categorical predictors.

The residual figure is drawn only when *Residual plot* is on; it follows Format Graph and the Inspector like the other figures. The sheets export to CSV, the figure to PNG, SVG and PDF; **Use Result as Data** on *Fitted values* keeps the source rows. Editing a cell or excluding a row recalculates the analysis. If a recalculation cannot be completed — for example a count edited to 2.5 — the last confirmed result stays on screen, is marked as not up to date, and the dialog reopens on the field to fix.

## Reproducible example

`tests/data/nb2_regression/counts.csv` has 16 rows: eight with *Treatment* 0 and *Exposure* 2, eight with *Treatment* 1 and *Exposure* 4. The mean counts are 3 and 9, so the rate per unit of exposure is 1.5 and 2.25 and the true rate ratio is 1.5.

1. **File → Open…** the CSV (or paste it into a new table).
2. **Analyze…**, then **Regression and Curves → Negative binomial regression**.
3. *Response* `Count`, *Predictors* `Treatment`, *Exposure* `Exposure`; leave *Dispersion mode* on **Estimated ML** and press **Run Analysis**.

| | Estimated ML | Fixed, α = 0.5 | Poisson (Multiple regression) |
|---|---|---|---|
| α | 1.9645 | 0.5 | — |
| IRR of Treatment | 1.5 | 1.5 | 1.5 |
| 95% interval of the IRR | 0.352 – 6.389 | 0.652 – 3.450 | 0.945 – 2.381 |
| p of Treatment | 0.583 | 0.340 | 0.085 |
| Log likelihood | −42.719 | −48.097 | −89.852 |
| AIC | 91.44 | 100.19 | 183.70 |

The three models agree on the rate ratio, because each group is saturated; they disagree on how sure they are. The counts within a group range from 0 to 31, far more than Poisson allows, and the much better log likelihood of NB2 says so: the Poisson interval is too narrow.

The same file, with the *Poisson boundary* fixture `tests/data/nb2_regression/poisson-boundary.csv` (counts of 2 and 3 only, less spread than Poisson), shows the other case: **Estimated ML** stops on *Dispersion mode* with the Poisson boundary message, while **Fixed** with a small α gives the Poisson estimates.

## What it does not do

No zero-inflated or hurdle models, no NB1 (`Var = μ(1 + α)`), no random effects, no robust (sandwich) standard errors and no profile-likelihood intervals: the intervals are Wald intervals on the log scale. The dispersion is one α for all rows.
