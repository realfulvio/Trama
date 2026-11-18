# Weibull AFT regression

Choose **Survival Analysis → Weibull AFT regression** (Italian: *Analisi di sopravvivenza → Regressione Weibull AFT*) to describe how predictors stretch or shrink the time to an event, with right censoring. It is a parametric model: the times follow a Weibull distribution whose scale depends on the predictors, and one shape is shared by everybody. Kaplan–Meier and Cox regression are unchanged and keep their recipes.

## Reading the time ratio

The model is an *accelerated failure time* model: each predictor multiplies the time scale. The **time ratio** of a term is `exp(β)`.

- A time ratio **greater than 1** lengthens the distribution of the times at comparable values of the other predictors: events come later. A ratio of 2 means that every quantile of the time (the median, the 10th percentile, …) is twice as long.
- A ratio below 1 shortens the times; a ratio of 1 changes nothing.
- For a continuous predictor the ratio is per unit of the worksheet column; for a category it compares the level with the reference level.
- On the *Intercept* row, `exp(β₀)` is the Weibull scale (the time by which 63.2% of the events have happened) of a subject with every continuous predictor at 0 and every category at its reference.

The **shape** `k` describes how the hazard changes with time: below 1 it falls, 1 is the exponential model with a constant hazard, above 1 it rises. The time ratios are not hazard ratios: in a Weibull model the hazard ratio of a term is `time ratio^(−k)`.

## Choices

| Field | Meaning |
|---|---|
| Time | Numeric column; every used row must be positive and finite. |
| Event | The status column. Its codes are read with the rules of Cox regression. |
| Event value, Censor value | The two codes (defaults `1` and `0`). For a numeric column they must be numbers; for a text column the text must match as written. A code that is neither of them stops the analysis on *Event* with the first source row. |
| Predictors | Optional, up to 8 distinct columns. The intercept is always in the model. |
| Categorical predictors | A subset of *Predictors*, coded against a reference level: the levels are sorted as text and the first is the reference, as in the multiple regression and in Cox regression. |
| Shape mode | **Estimated ML** (the shape is estimated with the coefficients) or **Fixed**. |
| Shape | Only in *Fixed* mode, from 0.05 to 50 (default 1.5). Hidden in *Estimated ML*, it is neither checked nor saved. |
| Confidence level (%) | Wald intervals, strictly between 0 and 100 (default 95). |
| Profiles | Optional, 1 to 12 named sets of predictor values. A category must be one of the levels of the fit. |
| Times | Optional times for the profiles, one per line, 0 or more and strictly increasing, decimal comma accepted. Left empty, 101 points from 0 to the longest observed time are used. |
| Show graph | Draws the survival of the profiles; it needs at least one profile. |

A row is used when Time, Event and every predictor have a value; an empty cell or a cell you exclude counts as missing, and *Incomplete rows* in **Model fit** says how many rows were left out. Events and censored rows are counted separately; data in which every used row is censored is refused on *Event*.

## How it is computed

With `ηᵢ = xᵢβ`, the time of subject *i* has a Weibull distribution with scale `exp(ηᵢ)` and shape `k`:

```text
S(t | x) = exp(−exp(k · (log t − η)))      S(0) = 1
ℓᵢ = δᵢ · [log k − log tᵢ + k · (log tᵢ − ηᵢ)] − exp(k · (log tᵢ − ηᵢ))
```

with `δ = 1` for an event and 0 for a censoring. The log likelihood is maximised by a damped Newton method with the analytic gradient and Hessian, over β alone (Fixed) or over β and log k (Estimated ML). The work is done on a centred log time and standardised continuous predictors and the results are mapped back to the units of the worksheet, so multiplying the times by 24 adds `log 24` to the intercept and changes nothing else. One fit is done per run, on the worker thread.

The covariance is the inverse of the observed information in that parametrisation, mapped to the worksheet units. Coefficients have two-sided Wald tests and intervals; the time-ratio limits are the exponentials of the coefficient limits. In *Estimated ML* the shape interval is the Wald interval of log k, exponentiated. `AIC = −2ℓ + 2p`, where p counts the shape only when it is estimated. The median time of a row is `exp(η + log(log 2)/k)`.

There is no automatic fallback to the exponential model. A predictor that is constant, collinear with the others, or that separates the events (a level without events, a group whose events all sit at the highest value of the term) is refused on *Predictors* before the fit. A shape that runs to its limits (for example when every time is the same) is refused on *Shape mode*; an information matrix that is singular or too badly conditioned is refused on *Predictors* (on *Shape mode* when the model has the intercept only).

The engine was checked against the closed-form profile likelihood of the package fixture (at a fixed k the scale of group g is `(Σ tᵏ / d_g)^(1/k)`), against an independent optimiser with numerical derivatives, and, outside the repository, against `lifelines.WeibullAFTFitter` 0.30.3 (log likelihood equal within 1e−8). The coefficients are those of R `survreg(..., dist = "weibull")`, whose *scale* is `1/k`.

## Results

In this order:

1. **Coefficients** — one row per term (Intercept first): Estimate, SE, p, Lower, Upper, Time ratio, Ratio lower, Ratio upper.
2. **Model fit** — N, Events, Censored, Incomplete rows, Shape mode, Shape, Parameters, Log likelihood, AIC, Confidence level (%), Shape lower, Shape upper (the last two empty in *Fixed* mode).
3. **Fitted survival** — one row per used row in the order of the data: Source row (the position in the worksheet, from 1, that stays the same when rows above it are left out), Time, Event (1 or 0), Median time, Survival at time.
4. **Survival curves** — only with profiles: Profile, Time, Survival, Extrapolated, in the order of the profiles and then of the times. *Extrapolated* says **Yes** for a time beyond the longest observed time: the value is still a point estimate of the model, kept between 0 and 1, but it is not supported by the follow-up.
5. **Reference levels** — only with categorical predictors: the reference level of each.

The graph has one vector line per profile through the points of *Survival curves* (ids `aft-profile-1`, `aft-profile-2`, …), the Y axis from 0 to 1, and a shaded band beyond the longest observed time when the requested times reach it. Names of columns and profiles are written literally. **Graph settings…** on the graph page reopens the *Predicted survival* page of the dialog, and **Use Result as Data** works on every sheet.

## Example

`tests/data/weibull_aft/follow-up.csv` is synthetic: 16 subjects, 10 events and 6 censorings; *Status* is `event` or `censored`, and the 8 subjects with *Treatment* = 1 have exactly twice the times of the 8 with *Treatment* = 0, with the same censoring.

1. Open the file and choose **Analyze… → Survival Analysis → Weibull AFT regression**.
2. *Data*: Time = `Time`, Event = `Status`, Event value = `event`, Censor value = `censored`, Predictors = `Treatment`.
3. *Model*: leave **Estimated ML** and 95.
4. *Predicted survival*: add the profiles *Control* (Treatment 0) and *Treated* (Treatment 1), type the times `0`, `2`, `4`, `8`, `20` on separate lines and tick **Show graph**.

You get shape 1.490991 (95% interval 0.897 to 2.478), log likelihood −31.188842, AIC 68.377684, and:

| Term | Estimate | SE | p | Time ratio | 95% interval of the ratio |
|---|---|---|---|---|---|
| Intercept | 1.795738 | 0.300956 | < 0.0001 | 6.023917 | 3.339681 to 10.865582 |
| Treatment | 0.693147 | 0.424185 | 0.1022 | 2.000000 | 0.870890 to 4.593002 |

The time ratio is exactly 2, as the data were built. The medians are 4.711090 (Control) and 9.422181 (Treated). The survival of *Control* at 2, 4 and 8 is 0.824305, 0.580949 and 0.217287, and *Treated* has the same values at twice the times; the row at 20 is marked *Extrapolated* because the longest observed time is 17. With **Fixed** shape 1.5 the time ratio stays 2, the intercept is 1.795172 (SE 0.298142) and the AIC is 66.378225, because the shape is no longer a parameter.

## Limits

40,000 rows, 24 coefficients after the categories are expanded, 12 profiles and 5,000 profile × time pairs. A request over a limit is refused before the matrix or the curves are built, on the field that brings it back in budget (Time, Predictors, Profiles or Times). On the reference container (4-core Xeon at 2.3 GHz, Python 3.12) 20,000 rows with 8 covariates and 4 profiles take about 0.04 s per run. The calculation is short and has no Cancel button.

## Errors and recovery

Every error names its field and keeps the dialog open with what you typed: a column in the wrong role, equal or unknown codes, a time that is not positive (with the source row), a constant or collinear predictor, a level without events, a shape outside 0.05 to 50, a profile that does not match the predictors, a time list that is not increasing. A worksheet edit that makes a saved analysis impossible, for instance censoring the only event of a group, keeps the last good result, marks it as out of date and reopens the dialog on the field to correct.

## What it is not

Not included: left or interval censoring, delayed entry, weights, frailties, stratified shapes, other distributions (log-normal, log-logistic) and confidence bands for the curves. The curves of the profiles are point estimates.
