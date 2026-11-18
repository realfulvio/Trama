# Cox regression with exact conditional ties — 0.93

In **Cox regression** the **Ties** option on the **Model and status** page now has a third value after `Efron` and `Breslow`:

| Option | Values | Default |
| --- | --- | --- |
| `Ties` | `Efron`, `Breslow`, `Exact (conditional)` | `Efron` |

Efron stays the default and Breslow is unchanged. A recipe saved before this option, or saved with Efron or Breslow, runs the same code as before and gives the same sheets, figure and numbers. Saved values stay canonical English in both languages (`Exact (conditional)`, not its Italian caption).

## The likelihood

At every event time `t` let `D` be the `d` rows that fail and `R` the rows with `T >= t`; censored rows at `t` stay in `R`. The discrete (exact conditional) partial likelihood adds, for each such time,

```
sum(eta_D) − log( sum over S ⊂ R with |S| = d of exp(sum(eta_S)) ),   eta = X·beta, no intercept
```

The denominator is the elementary symmetric polynomial `e_d` of the weights `exp(eta_i)` over `R`. A time with `d = 1` equals Breslow and Efron. A time with `d = |R|` contributes exactly zero and is skipped. The coefficients, standard errors, Wald statistics, confidence intervals, log likelihood and AIC come from this likelihood.

Subsets are never listed. Rows are added one at a time in decreasing time order, and because the risk sets are nested the running state after the last row of a time is that time's risk set. For each size `r = 1 … d_max` the state keeps `log e_r` and the mean and covariance of `sum(x_S)` under the weights; adding a row is a convex mixture, so the recursion is stable whatever the range of the weights. The score of a time is the observed `sum(x_D)` minus that mean and its information is that covariance.

## The fit

* Newton's method with step halving, from beta = 0, at most 100 iterations. The predictors are centred and scaled for the iteration and the results are returned on the original scale, so the estimates are invariant to a translation or a rescaling of a predictor. A last full step is taken when the decrement is below 1e-10 and the score must then be below 1e-8.
* The information must have full rank at every step. A likelihood that has no finite maximum (complete separation of the events, a monotone likelihood) is detected by a vanishing information or by a standardized coefficient beyond 20, and is reported on **Predictors** with a message that names the cause. A singular information matrix is reported on **Predictors** too.
* At least two events among the complete rows are needed. Times must be nonnegative. A missing cell removes the row (listed in `Incomplete rows`), as in the other Cox fits.

## Limits and nothing replaced silently

These are checked before any state is allocated, from the data actually used, and they are reported on **Ties** with the numbers and the way out. No other estimator is substituted.

| Limit | Value |
| --- | --- |
| Complete rows | 2 000 |
| Design columns after coding | 8 |
| Work budget `sum(\|R\|·d·(p+1)²)` over the times with `1 ≤ d < \|R\|` | 5 000 000 units |

## Outputs that stay with Efron and Breslow

Exact gives the **Coefficients**, **Model** and **Reference levels** sheets and no figure. **Predict survival**, **Cox diagnostics**, **Schoenfeld residuals** and a **Graph** other than Automatic belong to the Breslow baseline hazard and are refused, on the tab and the control that asks for them:

> Exact (conditional) ties give the coefficient and model sheets only. Turn off Predict survival or choose Efron or Breslow.

The dialog refuses on **Run Analysis**, stays open, and keeps everything typed, including the profile list. Selecting Exact shows a note on each of those tabs saying so before the user runs anything. Switching an existing Efron recipe that has predictions to Exact gets the same refusal, and switching back to Efron returns the unchanged recipe and the unchanged sheets. A recipe that reaches the dispatcher from a saved project or from a script is refused the same way.

## Cancel

An exact fit runs on the worker and shows **Cancel calculation**; the token is read every 64 rows and between iterations.

* A new analysis that is cancelled adds nothing.
* An edit that is cancelled keeps the last completed results and the confirmed recipe.
* A recalculation that is cancelled (after a cell edit or an exclusion) keeps the last result on screen, marked as not current, and **Recalculate** completes it.

Errors known only after the fit started (the limits, separation, a singular matrix, an unknown status code) reopen the existing analysis-recovery dialog on the field to correct and keep the confirmed analysis.

## Result sheets

`Coefficients` and `Reference levels` have the same columns as the other Cox fits. `Model` lists `N`, `Incomplete rows`, `Log likelihood`, `AIC`, `Ties` (`Exact (conditional)`), `Events` and `Tied event times`. Sheet names stay canonical English in both languages, so a saved project, an exported CSV and **Use Result as Data** do not depend on the language.

## Project file

A `.alab` project keeps the recipe with `"Ties": "Exact (conditional)"`. Reopening it, editing the data, excluding a cell and recalculating refit the same recipe.

## What was checked

* The engine against an independent enumeration of every subset of every risk set (value, score and information to 1e-10 or better), including times where `d = |R|`, censored rows tied with events, one event per time (Breslow/Efron limit) and rows with extreme weights.
* Frozen coefficients of an 11-row fixture with two tied event times, one censored row at an event time and one incomplete row: Marker −0.030136728866, Group [B] 0.516998689050, standard errors 0.341891779326 and 0.857142243089, log likelihood −10.347386212012.
* Invariance to translation and rescaling of a predictor and to row order; the first sorted level as the reference of a categorical predictor; the agreement with Efron and Breslow when no time is tied.
* The desktop smoke (`TRAMASTAT_SMOKE_ONLY=cox-exact-ties`) runs the real dialog and the real application in English and in Italian: notes, refusal with profiles kept, the frozen numbers, CSV of every sheet, Use Result as Data, the three cancellations, a cell exclusion against the dispatcher, save and reopen, an Efron recipe with predictions left untouched, a 2 001-row error on **Ties** and a separation error on **Predictors**, each followed by the correction.

## Choices made

* The launch budget follows the specification. It is more conservative than the cost of the nested pass (one evaluation costs at most `rows × d_max × (p+1)²` units), so a model slightly over the budget could still be fast; the limit is a stated contract, not a measurement.
* The numerical thresholds (decrement 1e-10, score 1e-8, rank 1e-10, vanishing information 1e-8, coefficient 20 in standardized units) are chosen to catch the failures in the tests; they are constants at the top of `analisi/cox_exact.py`.
* No comparison with R `coxph(ties = "exact")` was made, because R is not available where this was built. The reference is the independent enumeration above.
* A cancelled recalculation keeps the previous result flagged as not current instead of discarding it.

## Not tested

Windows, a native DPI above the emulated one, and manual use by a person. The desktop smoke ran under Xvfb (Tk 8.6, Linux) at 1024 × 768 and 1920 × 1080, Standard and Modern.
