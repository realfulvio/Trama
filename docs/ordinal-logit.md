# Ordinal logistic regression

Choose **Regression and Curves → Ordinal logistic regression** (Italian: *Regressione e curve → Regressione logistica ordinale*) when the response is a set of ordered categories: a stage, a grade, a score on a short scale, *Low / Medium / High*. The analysis fits the **proportional odds** model, the cumulative logit with one set of coefficients shared by every threshold.

Multiple regression with a logistic model is unchanged and keeps its recipes; it remains the choice for a response with two outcomes.

## The model

With the categories numbered 1 … *J* from the lowest to the highest:

```text
logit P(Y ≤ j | x) = θ_j − x·β        j = 1 … J − 1,   θ_1 < θ_2 < … < θ_(J−1)
```

* **exp(β)** is the odds ratio of being **above** any threshold for one unit more of the predictor. A positive β moves the subjects towards the higher categories. The same β holds at every threshold: that is the proportional odds assumption.
* The thresholds θ absorb the intercept. The design has no intercept column, and a categorical predictor is coded with dummies against a reference level: the same coding and reference as Multiple regression, the first level in sorted text order.
* The fit is the maximum likelihood fit of `statsmodels` `OrderedModel(distr="logit")`, made on a standardized copy of the design and converted back to the units of the worksheet. Standard errors come from the inverse of the information, intervals and p values are two-sided Wald with the normal quantile. AIC counts the coefficients and the thresholds.
* The probability of each category is the difference of two cumulative probabilities. It is computed in a log form that stays accurate in the tails, so a very small probability is not rounded to zero.

## Choices

| Field | Meaning |
|---|---|
| Response | The ordered response: 3 to 12 categories among the complete rows. Numbers and text are both accepted and keep their literal labels (`01` stays `01`). |
| Predictors | 1 to 8 distinct columns, numeric or categorical. |
| Categorical predictors | The predictors to code as categories; each needs at least two levels. |
| Category order | The categories from the lowest to the highest. Select one and move it with **Up** and **Down** (or Alt+Up and Alt+Down); **Reset** reads the categories again from the worksheet. It is filled from the worksheet when you choose the response, in sorted order, and must be checked: text sorts alphabetically, so *High, Low, Medium* has to be moved to *Low, Medium, High*. |
| Confidence level (%) | Between 0 and 100, excluded (default 95). A decimal comma is accepted. |
| Profiles | Optional, up to 12. Each profile has a name and one value for every predictor, and gives the predicted probability of every category. A continuous value outside the observed range is allowed and marked *Extrapolation* in the sheet; a category that the predictor does not have is refused. |
| Show graph | Draws one stacked bar per profile; it needs at least one profile. |

A row is used only when the response and every predictor are filled; a cell you exclude counts as missing. The rows that are left out are counted in *Incomplete rows*. A filled value that cannot be used (text in a numeric predictor, an infinite number) is an error on its field and is never dropped silently.

## Results

In this order:

1. **Coefficients**: one row per predictor or dummy (`Site [south]`), with Estimate, SE, p, Odds ratio, OR lower and OR upper.
2. **Thresholds**: Lower category, Upper category and Estimate, increasing.
3. **Model fit**: N, Incomplete rows, Log likelihood, AIC and Confidence level (%).
4. **Fitted probabilities**: Source row (the row of the worksheet, counted from 1, so the numbers stay put when rows are excluded), Observed, Predicted and one column `P(<category>)` per category, in the declared order. When two categories have the same highest probability, Predicted is the first one in the declared order.
5. **Reference levels**: only with categorical predictors.
6. **Profile probabilities**: only with profiles; Profile, one `P(<category>)` per category and a Note when a profile extrapolates.

The optional graph stacks the profile probabilities from 0 to 1, with the lowest category at the bottom, a sequential palette that keeps the same colour for the same position, and the response name as the legend title. Names of profiles and categories are literal text: `$` and `_` are printed as typed. Format Graph and the Inspector change the style without fitting the model again.

## Example

`tests/data/ordinal_logit/stages.csv` has 168 rows: *Stage* (Low, Medium, High) and *Treatment* (0 or 1).

| Treatment | Low | Medium | High |
|---|---|---|---|
| 0 | 21 | 35 | 28 |
| 1 | 12 | 30 | 42 |

1. Open the file and choose **Analyze → Regression and Curves → Ordinal logistic regression**.
2. Response *Stage*, Predictors *Treatment*. Category order reads *High, Low, Medium*: select *Low* and press **Up**, then select *Medium* and press **Up**, until it reads *1. Low, 2. Medium, 3. High*.
3. Run Analysis.

The model with one binary predictor and three categories is saturated in the cumulative odds of the two groups, so the answer can be checked by hand:

| Quantity | Value |
|---|---|
| β (Treatment) | log 2 = 0.693147 (odds ratio 2.000) |
| SE | 0.292728, p = 0.01789 |
| Odds ratio, 95% interval | 1.1268 to 3.5498 |
| Thresholds | log(1/3) = −1.098612 (Low \| Medium) and log 2 = 0.693147 (Medium \| High) |
| Log likelihood, AIC | −173.866417, 353.732835 |
| Fitted P(Low), P(Medium), P(High) | 0.2500, 0.4167, 0.3333 with Treatment 0; 0.1429, 0.3571, 0.5000 with Treatment 1 |

Treated subjects have twice the odds of being above any threshold. Reversing the order (*High, Medium, Low*) changes the sign of β and of the thresholds and leaves every `P(<category>)` with its label. The values are frozen in `tests/data/ordinal_logit/expected.json` and the program never reads that file.

## Limits

40,000 complete rows, 12 categories, 8 predictors, 24 coefficients after the categorical predictors are expanded and 12 profiles. A request over a limit is refused before the fit, on the field to change. On a 4-core 2.1 GHz Xeon (Linux), 20,000 rows with 5 categories and 8 coefficients take about 1.3 s and 24 BFGS iterations; 40,000 rows with 12 categories and 24 coefficients about 15 s. The fit runs on the background worker and has no Cancel button.

## Errors and recovery

Every error names its field and keeps the dialog open with what you typed:

* **Response**: fewer than 3 or more than 12 categories, labels of different types that print alike (`1` and `"1"`), too many rows.
* **Predictors**: a constant predictor, a set of predictors that adds up to a constant (an implicit intercept) or that is collinear, a categorical predictor with a single level, too few rows for the parameters, too many coefficients. Data that separate the categories completely, a fit that does not converge, an information matrix that cannot be inverted or thresholds that coincide are known only after the fit; the dialog then opens again on Predictors with the reason.
* **Category order**: a category that the worksheet no longer uses, or a category of the worksheet that the order does not list. The note under the list names them.
* **Profiles**: a repeated or empty name, an unknown predictor, a missing value, a category that the predictor does not have, more than 12 profiles, *Show graph* without any profile.

A worksheet edit that makes a saved analysis impossible, for instance a new category in the response, keeps the recipe and the last good result, marks it as out of date and reopens the dialog on the field to correct. The saved order is never repaired silently: press **Reset** or arrange the new category yourself.

## What it is not

Not included: confidence intervals of the profile probabilities, a test of the proportional odds assumption (Brant), the partial proportional odds and multinomial models, other links (probit, complementary log-log) and penalized fits.
