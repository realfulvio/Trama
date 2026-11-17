# Global custom equation fitting — 0.70.0

Choose **Regression and Curves → Global fit custom equation**. Supply X, Y and a Group column in long format; at least two series must contain complete pairs. Missing values are omitted with the original source-row index kept in the residual sheet.

Write one safe mathematical expression and declare its coefficients. **Shared** estimates one value across all series, **Local** estimates one value per series, and **Fixed** uses a common supplied value. Series constraints can fix a local coefficient or narrow coefficient limits for a particular series. A shared coefficient uses the intersection of those limits; a fixed value must also satisfy the series limits. Coefficients cannot be fixed and shared at the same time.

Choose unweighted fitting or **Inverse variance (column)** with positive relative SD values. Multiplying every SD by a common factor preserves the estimated coefficients and their uncertainty. The covariance is computed jointly, including correlations between series; interior estimates use asymptotic t intervals. Active bounds, an exact fit or all-fixed coefficients have explicit inference notes rather than misleading intervals.

The result contains **Parameters**, **Global fit**, **Covariance**, **Residuals** and **Curve**. Curves use each series' observed X domain. Residuals and curves can become data; recipes, constraints and styles survive project reopening and recalculation. Fitting errors preserve the previous result and reopen the candidate dialog.

This analysis uses one equation for all series. IRLS, observed-Y weights, profile/bootstrap intervals and model comparisons are separate analyses and are outside this method.

## Response bands and predictions

The **Response** page (Italian: **Bande e previsioni**) adds two optional outputs computed from the same joint fit, with no second fit:

- **Curve band** `None` / `Confidence` / `Prediction` draws a pointwise band around each fitted curve, at **Response level (%)** (default 95; `90,0` is accepted in Italian). **Band drawing** is `Filled` or `Lines`. The variance is `gᵀCg` with the full covariance of the global fit, so correlations between shared and local coefficients are kept; Prediction adds the residual variance RSS/df. The `t` quantile uses the global df. The sheets **Curve bands** (same grid as Curve) and **Curve band settings** are added.
- **Predict responses** reads **Query X** and **Query group** columns of the same table and writes **Predictions**, one row per source row, with `Source row`, the series, the predicted value, SE mean and, with **Query interval**, the limits. For Prediction, **Query replicate count** gives `k` for the mean of k new observations (empty = 1). A query outside the X domain of its own series is `Outside domain` unless **Allow extrapolation** is on, in which case it is computed and marked `Extrapolated`. Missing X, missing or unknown series and undefined model values are reported per row and never stop the analysis. Query columns never add observations to the fit.

Bands and query intervals need an unweighted fit; with an SD column only point predictions are available. An exact fit, all-fixed coefficients or an active bound keep curves and point predictions and state why no interval is given; no zero-width band is drawn. Static checks run before the worker: at most 10,000 query rows, and a propagation budget of 2,000,000 cells (curve points × series + query rows, times free coordinates). The Confidence level (%) on Output still applies to the coefficients only.

Each band follows the colour and visibility of its fit line in Format Graph, the Inspector, Reset and reopening; the link is rebuilt at runtime and only data, options and styles are saved. With both outputs off the result keeps the five historical sheets and old recipes gain no new keys.

Targeted desktop check: `TRAMASTAT_SMOKE_ONLY=global-uncertainty xvfb-run -a -s '-screen 0 1024x768x24' python tramastat.py --smoke DIR` (also part of the full smoke). Existing **Fit custom equation** and catalog-based **Global nonlinear regression** recipes keep their behavior.

## Linux GUI acceptance

The desktop smoke requires a real or virtual screen of at least 1024×768. Enlarging a Tk window beyond a 640×480 virtual screen does not enlarge that screen: modal placement is still clipped. Use:

```sh
xvfb-run -a -s '-screen 0 1024x768x24' python -m unittest discover -s tests -v
xvfb-run -a -s '-screen 0 1024x768x24' python tramastat.py --smoke /tmp/tramastat-qa
```

The smoke records `display.json` and rejects an undersized screen with the required command. No control-width or button-visibility assertions are relaxed.

