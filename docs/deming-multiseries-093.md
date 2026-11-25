# Deming regression: known SDs, several series and projections — 0.93

Choose **Regression and Curves → Deming regression**. The dialog has three tabs, **Variables**, **Uncertainty** and **Output**. Four new canonical options sit beside the historical ones:

| Option | Values | Default |
| --- | --- | --- |
| `Uncertainty input` | `Variance ratio`, `Known SDs` | `Variance ratio` |
| `X error SD`, `Y error SD` | finite numbers greater than 0, in the units of each axis | — (only with `Known SDs`) |
| `Y series` | up to 12 columns, none of them the X column | empty |
| `Show projections` | on or off | off |

`X`, `Y`, `Y / X error variance`, `Parameter intervals`, `Confidence level (%)` and `Identity line` keep their names, defaults and meaning.

A recipe saved before 0.93 has none of the new keys. It runs the historical analysis: one Y, the sheets `Deming regression`, `Data` and `Pairs` with the same columns, and the same figure. A new recipe that leaves the four options at their defaults is saved without them, unless the recipe being edited already had them, so reopening and saving an old project does not rewrite its recipes.

```json
{"X": "Dose", "Y": "A", "Uncertainty input": "Known SDs", "X error SD": 2.0, "Y error SD": 1.0,
 "Y series": ["A", "B $"], "Show projections": true, "Parameter intervals": "Jackknife (t)",
 "Confidence level (%)": 95.0, "Identity line": true}
```

Saved values stay canonical English in both languages (`Known SDs`, not its Italian caption). Series names are the literal column names, so `B $` needs no escape and is never read as mathtext.

## Known SDs

The two SDs are the **measurement-error** standard deviations of X and Y, each in the units of its own axis. They are not the spread of the data. The ratio used by the fit is

λ = (SD_Y / SD_X)²

formed as one division and one square, so multiplying both SDs by the same factor (`1e-80`, say) gives exactly the same λ and exactly the same fit. The fit depends on the SDs only through λ. A λ that cannot be represented (below the smallest or above the largest normal double) is refused on **Y error SD**, never rounded to 0 or to infinity.

With Known SDs the field **Y / X error variance** is hidden and left out of the recipe; with Variance ratio the SD fields are hidden and left out. The report sheet shows the ratio that was used and, for a single series, the two SDs after it.

## Several Y series

**Y series** lists the columns to fit against the shared X. Each series is an independent Deming fit with its own complete pairs and the same uncertainty and interval settings. The shared ratio only makes sense when the responses have comparable units and precision; the dialog says so beside the list.

* `Deming regression` has one row per series, with `Series`, `N`, `Slope`, `Intercept` and `Y / X measurement error variance`. With Parameter intervals set to Jackknife (t) the existing interval columns follow, and an `Interval status` column appears when at least one series cannot give an interval (fewer than four complete pairs, a degenerate leave-one-out fit, more than 100 000 pairs). The full-sample fit of that series is always kept.
* `Data` has `Series`, `X` and `Y`. `Pairs` has `Series`, `Source row`, `X`, `Y`, `Fitted Y` and the vertical residual, in the order of the series and of the source rows. A missing cell is a missing pair, never zero.
* A series with fewer than three complete pairs, non-numeric or infinite data, or a degenerate fit (X and Y must both vary, with a nonzero covariance) stops the analysis with an error that names the series and keeps the focus on **Y series**. The X column, a column listed twice and a column that is not in the sheet are refused on the same field.
* Switching a series off (deselecting it) recalculates the others unchanged: each fit is computed once and reused by the tables, the intervals and the figure.
* Leaving **Y series** empty uses the single **Y** and the historical sheets, with the SDs added to the report when they are chosen.

## Projections

With **Show projections** on, each observed point (x, y) is joined to its projection on the fitted line y = a + b·x. With r = y − a − b·x the projected point is

x* = x + b·r / (λ + b²),  y* = y − λ·r / (λ + b²) = a + b·x*

which minimises λ·(x − x*)² + (y − y*)², the metric of the Deming model. For λ = 1 these are the Euclidean perpendiculars. A point that lies on the line projects onto itself, a zero-length segment. For |b| > 1 the weights are formed without squaring b, so a very steep fit does not overflow; a result that is not finite stops the analysis instead of being drawn.

`Pairs` gains `Projected X` and `Projected Y`, after the residual. The existing vertical residual stays in the table.

## The figure

* One series without projections is drawn exactly as in earlier versions.
* Projection segments are one `LineCollection` per series, in the colour of the series and below the points. They are the only line collections of the axes.
* Several series get their own colour and marker, their own fitted line and one legend entry each, up to 12 distinct pairs before they repeat. Legend text and axis labels are literal: a name containing `$` is not parsed as mathtext.
* **Identity line** draws a single dashed line over the union of the X and Y values actually used by every series, and both axes are limited to it. Without it each fitted line spans the X range of its own series.

## Export and reopening

PNG, SVG and PDF export the figure. The sheets export to CSV with their canonical English column names in both languages, and **Use Result as Data** copies a result sheet (`Pairs`, say) into an editable table. A `.alab` project keeps the recipe and recalculates after reopening, after an edited cell and after an excluded cell, each series from its own complete pairs.

## Smoke and tests

* `tests/test_deming_multiseries.py` checks the engine: λ from SDs and its scale invariance, the projection formula against an independent whitened-SVD oracle and exact rational arithmetic, zero-length segments, negative and very steep slopes, independent series, jackknife per series, every refusal and the unchanged historical path.
* `tests/test_deming_dialog.py` drives the real Analyze dialog in English and Italian: tabs, fields that appear and disappear, recipes, errors that stay on their field and page, and the catalog.
* `TRAMASTAT_SMOKE_ONLY=deming-multiseries python tramastat.py --smoke DIR` runs the desktop path (also part of the full smoke): Analyze, a field error corrected in the dialog, figure, exports, Use Result as Data, save and reopen, an edited and an excluded cell, a series switched off, the historical recipe, and the dialog in Italian and in the Modern theme.

## Choices made

| Choice | Reason |
| --- | --- |
| `Y series` empty means the single `Y`; it never repeats `Y` implicitly | Keeps the historical recipe and sheets unchanged and gives one meaning to the list. |
| The ratio is shared by all series | The specification asks for the same uncertainty settings for every series; the dialog states when that is reasonable. |
| Segments use the metric λ·dx² + dy², not Euclidean distance | They are the points the Deming model assumes; they coincide with perpendiculars only for λ = 1. |
| The fit and every interval stay those of `exploration.deming` and the existing jackknife | The new features add no estimator and no new test of significance. |
| New keys at their defaults are not written to a recipe that did not have them | An old project saved again keeps the same recipes. |

Out of scope for 0.93: SDs per point, R² and a different ratio per series. A later Qt option compares the slope and intercept of two series that are paired by row: [Paired Deming comparison](deming-paired.md).
