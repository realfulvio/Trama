# Curve pipeline — 0.93

**Smooth / differentiate / integrate** (in the Analyze picker, group **Data Exploration and Summary**) has a fourth choice in `Method`: **Curve pipeline**. It reads two columns, X and Y, as one curve and applies one operation to it, optionally followed by Savitzky–Golay smoothing. The three older choices (LOWESS, Differentiate, Cumulative integral) keep their code, sheets, numbers, graph and recipes exactly as before.

| Option | Values | Default | Shown when |
| --- | --- | --- | --- |
| `Operation` | `Identity`, `First difference`, `Second difference`, `Cumulative trapezoid` | `Identity` | Curve pipeline |
| `Smoothing` | `None`, `Savitzky–Golay` | `None` | Curve pipeline |
| `Baseline` | a finite number | `0` | Operation is Cumulative trapezoid |
| `Initial integral` | a finite number | `0` | Operation is Cumulative trapezoid |
| `Half-window` | a whole number from 1 to 50 | `2` | Smoothing is Savitzky–Golay |
| `Polynomial degree` | a whole number from 0 to min(6, 2 × half-window) | `2` | Smoothing is Savitzky–Golay |

The window of a smoothing has `2 × Half-window + 1` points. A field that does not act is hidden, is not read and is not saved: a recipe holds the keys of the fields that were shown and nothing else. Saved values are the canonical English ones in both languages (`First difference`, not its Italian caption), and the Italian dialog accepts a decimal comma. Going back to LOWESS, Differentiate or Cumulative integral shows the older controls again with the values they had, and the pipeline keeps what was chosen if you return to it.

## The curve

Every worksheet row is a point with three numbers: X, Y and its **zero-based position in the worksheet** (the number of rows above it). The position is what the result reports as a source row, whatever the pandas index of the table is.

* Points are sorted by X with a stable sort. X values must be distinct: a repeated X is refused on the X field, even when one of the two rows has no Y.
* A row without a usable X (empty, or excluded) has no place on the axis. It is skipped and counted in **Settings** (`Rows skipped (X missing or excluded)`).
* A row with a valid X and no usable Y (empty, or excluded) is a **gap**. It stays out of the curve and splits it there; it is counted as `Gap rows (Y missing or excluded)`.
* The curve can therefore have several **blocks**, numbered from 1 along increasing X, and blocks are never joined: no difference, area or window crosses a gap. A block that produces no output keeps its number, so a number always names the same stretch of the data.
* Text and infinite values are refused on the field that holds them (`Column Y has text instead of a number at row 3.`). Numbers follow the usual conversions of Trama.

## Operations

Per block, in the units of the worksheet:

| Operation | Formula | X of the result |
| --- | --- | --- |
| Identity | the samples | the sample X |
| First difference | `ΔY / ΔX` between two consecutive samples | `x_left + ΔX / 2` |
| Second difference | the same operation applied to the points of the first difference | `x_left + ΔX / 2` again, on those points |
| Cumulative trapezoid | `initial` at the first sample of every block, then adds `ΔX · ((y_left + y_right) / 2 − Baseline)` | the sample X |

The cumulative value is a **signed** area: it falls where Y is below Baseline. A block of one sample keeps `Initial integral`. A difference that cannot be formed (a block of one point for the first difference, of fewer than three for the second) gives nothing, and if no block can give anything the error names Operation.

**Units.** The `Output unit` row of Settings says what the numbers are: `Y per X` for the first difference, `Y per X squared` for the second, `Y × X` for the cumulative trapezoid, with the real column names (for example `Signal (mV) per Time (s)`). A shifted or rescaled grid changes the numbers and the unit consistently; the pipeline does not rescale anything.

## Smoothing

Savitzky–Golay runs **after** the operation, on the points that the operation produced, separately for every block. For a centre with `m` points on each side it fits, by least squares, the polynomial of the chosen degree to the `2m + 1` values of the window and evaluates it at the centre. That is a fixed weighted sum of the window; for a 5-point window and degree 2 the weights are `(−3, 12, 17, 12, −3) / 35`. The smoothed value is a **descriptive transformation** of the data, not a fitted model and not a new measurement; the note under the options and a `Note` row in Settings say so.

* Centres without a complete window are not emitted, so a block of `n` points gives `n − 2m` values and a block with fewer than `2m + 1` points gives none. If no block has the window, the error names Half-window.
* A block that is long enough must have evenly spaced X: the largest deviation of a step from the median step may not exceed `1e-10` times the median step, otherwise the error names **Smoothing**. Turning smoothing off removes the requirement. The first difference of an even grid is on an even grid again, so smoothing after a first or second difference is allowed.
* The weights are computed once per `(half-window, degree)` from the window offsets scaled to [−1, 1], which keeps the design matrix well conditioned up to a half-window of 50.

## Result

The **Curve** sheet has the columns `X`, `Value`, `Block`, `First source row`, `Last source row`. The two row columns are the positions of the first and last worksheet row that the value was calculated from, in increasing X order, so for an unsorted sheet they can decrease. A difference joins the ends of the two points behind it, a cumulative value keeps the first row of its block as its first row, and smoothing extends both ends to the rows inside the window.

The **Settings** sheet has the columns `Setting` and `Value`: operation, smoothing, the parameters that act (baseline and initial value, half-window, degree, window points), the output unit, valid points, rows skipped, gap rows, blocks, blocks without output, output points and the numbering of the source rows. With smoothing it also carries the descriptive-transformation note.

The **graph** draws the result as segments inside each block, with the operation as the legend entry, and the line is broken between blocks, so no segment enters a gap. For Identity with smoothing the measured points stay visible behind the smoothed line (they have the same unit). Exports work as for every analysis: CSV of the selected sheet (the exporter writes the sheet index as the first column), SVG, PNG and PDF of the graph, and **Use Result as Data** copies the Curve sheet into a new table.

## Worked example

The synthetic fixtures of the tests. `Irregular` has X = 3, 0, 10, 1, 6 and Y = x² + 2x + 3 = 18, 3, 123, 6, 51.

| Operation | Rows of the Curve sheet (`X`, `Value`, `First`, `Last`) |
| --- | --- |
| First difference | (0.5, 3, 1, 3), (2, 6, 3, 0), (4.5, 11, 0, 4), (8, 18, 4, 2) |
| Second difference | (1.25, 2, 1, 0), (3.25, 2, 3, 4), (6.25, 2, 0, 2) |
| Cumulative trapezoid, Baseline 3, Initial integral 2 | (0, 2, 1, 1), (1, 3.5, 1, 3), (3, 21.5, 1, 0), (6, 116, 1, 4), (10, 452, 1, 2) |

`Uniform` has X = 0 … 8 and the same parabola: Y = 3, 6, 11, 18, 27, 38, 51, 66, 83. Savitzky–Golay with half-window 2 and degree 2 leaves a parabola unchanged (11, 18, 27, 38, 51 at X = 2 … 6). With an impulse at X = 3 (32 instead of 18) the same window gives 15.8 at X = 2, because `(−3·3 + 12·6 + 17·11 + 12·32 − 3·27) / 35 = 553 / 35`, and the filter spreads the impulse over the four centres whose window contains it (X = 2 … 5). **First difference** followed by the same smoothing on the clean parabola gives 7, 9, 11, 13 at X = 2.5, 3.5, 4.5, 5.5.

`Gaps` has X = 0, 1, 2, 3, 5, 6 and Y = 2, 4, *(empty)*, 8, 12, 14. The first difference has three segments, over [0, 1], [3, 5] and [5, 6]: (0.5, 2, block 1), (4, 2, block 2), (5.5, 2, block 2). Nothing joins X = 1 to X = 3.

A small project with these tables and recipes is in [examples/Curve-pipeline.alab](examples/Curve-pipeline.alab). It holds only synthetic data.

## Limits

* **200,000 worksheet rows.** The check comes before any conversion and names the X field. The limit exists because the working arrays and the Curve sheet stay a few tens of megabytes and the drawn line stays interactive; a 50,000-row curve (the size the pipeline is exercised at) is calculated in well under a second.
* **Half-window 1 to 50, degree 0 to min(6, 2m).** The error says which values the current half-window allows.
* **Not cancellable.** The calculation takes a fraction of a second at 50,000 rows, so it runs in the dialog (and in the worker when the data change) without the cancel control that the long fits have. A second edit made while a recalculation is running is refused by the application, as for every analysis, and changes nothing.
* **A value that is not finite** (for example from a rescaling that overflows) is an error, not a masked result: `The calculation produced a value that is not finite. Rescale X or Y, or choose another operation.`
* Smoothing needs an even X grid inside the blocks it uses. Uneven data can be differentiated or integrated without smoothing, or put on a grid first.
* The older choices are unchanged, including the derivative at the nodes of **Differentiate**.

## Languages

Captions, choices, the two notes under the options and every error message exist in English and Italian. The engine raises English messages that name their field; the dialog translates them and copies numbers and column names literally, adds the field caption in front when the sentence does not already name it, and shows the field on the page that holds it with the keyboard focus.
