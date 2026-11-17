# Weighted Gaussian multiple regression — 0.70.0

**Regression and Curves → Multiple regression**, Family **Linear**, Options tab: **Gaussian weighting**.

| Choice | Fixed weight of a row |
| --- | --- |
| Unweighted (default) | 1; the historical fit, sheets and graph |
| 1/abs(Y) | 1/\|Y\| |
| 1/Y² | 1/Y² |
| 1/abs(Y)^K | 1/\|Y\|^K, **Weight exponent K** any finite number (default 1) |
| Inverse variance (SD column) | 1/SD², **Gaussian SD column** |
| Weight column | the positive value of **Gaussian weight column** |

The weights come from the observed data and never from fitted values: this is one weighted least-squares fit, not an IRLS. Logistic and Poisson ignore every Gaussian key. Recipes saved without the keys, or with the choice Unweighted, give exactly the earlier sheets.

## Rows and errors

Rows without the response, a predictor or a category leave first. The SD or weight column is then read on the remaining rows: a missing value removes its row (it counts in *Incomplete rows*); a value that is present but not a finite number above 0 is an error on that column naming the source row. A bad value on a row that already left is ignored. Categories and reference levels are learned only from the rows actually fitted. A Y of zero is an error on *Gaussian weighting* for every weighting from Y, except 1/\|Y\|^K with K = 0 (all weights 1). The worksheet is never changed and its row index is kept.

## Numerics

Weights are handled as logarithms: log w is computed first (never a squared SD or a power of a power), normalised to a maximum of 1 and only then exponentiated. For weights from Y the differences of the logs are taken before the multiplication by K, so equal weights stay equal for any K. A common factor on the weights or the SDs (1e±150), or an SD of 1e-200, changes no coefficient, SE, interval or dimensionless diagnostic. A real contrast between weights that the double range cannot hold, or a weighted design that is numerically singular, is a named error; nothing is cut silently.

The fit solves sqrt(wNorm)·(D, y) with the statsmodels WLS SVD solution after a rank check on that weighted matrix. The covariance is σ²(D′ W D)⁻¹ with σ² = RSS_w/(N − p); no HC or robust covariance is used.

## Sheets

- **Linear weights**: Source row, Observed, Weight (raw units, blank with a note when the double range cannot hold it), Normalized weight (maximum 1), Log weight (natural log of the raw weight, blank with a note when it cannot be represented) and Relative log weight (log of the weight relative to the largest, always finite).
- **Model** also reports the weighting, K, the variance units and the basis of R², log likelihood and AIC. The AIC uses the Gaussian likelihood of the weights normalised to a maximum of 1: compare it only between models fitted to the same rows with the same weights, never with an unweighted AIC. For weights from Y a note states that the standard errors and intervals are conditional on the fixed weights and do not include the uncertainty of choosing them.
- **Linear diagnostics / Linear model diagnostics / Linear predictions** come from the same fit. Leverage is wNorm·d′(D′ W D)⁻¹d, the studentized residual is √wNorm·r/√(σ²(1 − h)), Cook's distance r_w²·h/(pσ²(1 − h)²) with r_w = √wNorm·r, the PRESS residual stays r/(1 − h) in raw units; the summary adds *Weighted PRESS* = Σ wNorm·PRESS residual². Zero variance or leverage 1 keep the earlier blanks and notes. The residual graphs keep raw residuals and say so on the axis.

## Profiles and prediction intervals

The confidence interval of the mean always uses the fit's covariance. The variance of a *new* observation depends on its own precision, which a profile cannot imply. With **Weighted prediction intervals** off, the prediction limits are blank and a note says so. With it on, every profile needs a finite **Weight** above 0 in the same units as the raw training weights (1/SD², the column value, 1/\|Y\|…); the future variance is σ² · maxTrainingWeight/weight. Multiplying every training and profile weight by the same factor leaves all intervals unchanged. Unweighted fits never ask for a weight.

## Recipe keys

`Gaussian weighting`, `Weight exponent K` (power only), `Gaussian SD column`, `Gaussian weight column` (own mode only), `Weighted prediction intervals`, and `weight` in each profile. Keys are canonical in English and Italian; user column and profile names are kept literally.

