# Multifactor ANOVA residual diagnostics — 0.70.0

Choose **Group Comparison → Multifactor ANOVA** and open the **Diagnostics** tab. The four canonical options are residual diagnostics, assumption tests, diagnostic alpha, and a diagnostic graph (`None`, `Residuals vs fitted`, `Homoscedasticity`, `Normal Q–Q`). Saved keys and choice values stay canonical English in both languages. The tab caption, field captions, graph-choice labels, and field-error sentences are translated.

Diagnostics and assumption tests reuse the same Type III fit that builds the ANOVA table: one full least-squares solution, then its design, coefficients, residual sum of squares, and residual degrees of freedom. Reduced Type III fits and post-hoc fits are unchanged. Public `factorial_anova` and `factorial_anova_fit` still return the historical pair. Rank-deficient models and models with no measurable residual variance still fail before any diagnostic sheet.

Observation diagnostics report leverage from a reduced QR, the raw residual, the internally studentized residual, Cook's distance, and the PRESS residual. A leverage within `1e-12` of 1, or a residual variance that the existing relative rule treats as zero, is missing with a reason. Values are never infinite and never an invented zero. The summary stores N, model rank, residual df, residual SS, residual variance, and PRESS. For an accepted ANOVA, model rank and the Cook denominator use the design column count, and residual SS and df match the Type III residual row. New sheets are appended after the ANOVA, effect-size, and comparison sheets.

Assumption tests do not require the residual-diagnostics flag. A graph does. The five rows are fixed: Spearman `|residual|` versus fitted, Shapiro–Wilk, D'Agostino–Pearson, Anderson–Darling, and Lilliefors. A skipped test is an NA row and does not stop the others or the ANOVA. Decision is `Reject` when p is below alpha, `Do not reject` otherwise, and `NA` when the p-value is undefined. These p-values are diagnostic checks on estimated residuals: the references do not correct for the projection matrix, the five p-values are not independent, and there is no multiplicity correction. Changing alpha changes only Decision. The Lilliefors table-limit note stays in Reason.

A diagnostic graph accepts at most 60,000 complete rows. The dialog checks that budget before the fit. The graph is a native Matplotlib figure, so Format Graph and the Graph Inspector edit it and SVG, PNG, and PDF export stay vector or raster copies of that figure. Homoscedasticity plots absolute residuals against fitted values, labelled `|Residual| (raw response units)`. The normal Q–Q plot uses Blom positions `(i − 0.375) / (N + 0.25)` and keeps source order for ties.

## Q–Q reference line

The four canonical options do not name a Q–Q line. This build adds `ANOVA Q–Q reference line`, default on, visible and saved only while the graph is `Normal Q–Q`. The line is the mean and the sample standard deviation (`N − 1`) of the plotted residuals, not the model sigma. Its label is `Mean + SD (N−1) × theoretical quantile`. Turning the graph off drops the hidden key, the same way a hidden effect-size alpha is omitted. Choosing `Normal Q–Q` again in the same dialog restores the checkbox to on. Reopening a recipe that already has the graph set to `Normal Q–Q` and the line set to off does not reset it, because the dialog remembers the saved graph before the first refresh.

## Project file and source rows

A `.alab` project stores row order and excluded cells. It does not store DataFrame index labels. In memory, the source-row column is the index left by `complete()`, including a sparse index. After save and reopen, imported rows use a default range index, so the source row is the positional row. Exclusion survives because it is stored as a cell position. The unit test covers the sparse index; the desktop smoke uses an imported table with one incomplete response and one excluded cell.

Result sheet names and graph titles stay canonical English when the language changes. `set_language` does not rebuild the main window. The translated surface in the screenshots is the dialog.

Opening a project still lands on the data sheet. A recipe whose saved diagnostic graph is not `None` is listed under Graphs before it has been calculated, so the graph can be opened without a prior visit to the worksheet. A recipe with no diagnostic graph does not gain a graph entry. `Multifactor ANOVA` is not added to `GRAPH_METHODS`.

## Validation

Flags must be booleans. Alpha is read only while assumption tests are on, must be finite, and must be strictly between 0 and 1. A hidden stale alpha is not validated. A graph other than `None` without residual diagnostics names the graph field and does not turn diagnostics on. Invalid input stays in the dialog, keeps the typed value, and moves focus to that field. Run Analysis and Cancel stay in the dialog button row. A worker `FieldError` reopens the dialog and keeps the previous result. Rank deficiency remains the existing `ValueError` without a field.

Explicit `False` is saved for the two flags, and `None` is saved for the graph. Hidden alpha and the hidden Q–Q line are omitted. Missing keys on an old recipe stay off and do not add sheets or a figure.

## Checks

Widgets were driven by the smoke script. These are not manual clicks. Screenshots are the whole X screen from ImageMagick `import`. Error sentences were checked on the message box, which the script dismisses; the error screenshots show the dialog afterwards, with the rejected value still in the field. DPI 125% and 150% are emulated with `tk scaling` on Linux and restored afterwards. The file names say `emulato`. On this Tk build the dialog did not reflow: scaling was 1.250 and 1.499, and Run Analysis and Cancel stayed mapped and viewable at the same pixel box (Run Analysis 123×27 at x=761, y=578; Cancel 112×27 at x=641, y=578) on the 1024×768 screen. The two screenshots are therefore byte-identical. Windows was not available: **NON PROVATO**. Do not treat the Xvfb runs as a Windows or native-DPI result.

Interpreter: CPython 3.14.9. The package verifier names 3.13.14. No dependency was added.

| Check | Result |
| --- | --- |
| Package verifier, oracle and repo, 6 tests | OK in 0.495 s |
| `python -m unittest discover -s tests -q` under Xvfb 1024×768 | 1596 tests, OK in 80.396 s |
| `TRAMASTAT_SMOKE_ONLY=anova-diagnostics`, Xvfb 1024×768 | PASS, `display.json` 1024×768 |
| Same targeted smoke, Xvfb 1600×1000 | PASS, `display.json` 1600×1000 |
| Full `tramastat.py --smoke` at 1024×768, this branch | FAIL, pre-existing |
| Same full smoke at `f2dfe57` (UI A, before this work) | FAIL, same assertion |

The full smoke stops in `check_workspace_setup` because the Layout ribbon button, after the window is set to 820×570, extends past `rootx + 820`. The same assertion fails on the untouched base. Both tracebacks are in `docs/media/anova-diagnostics-070/`. The assertion was not weakened. The new project-cycle check is the function the full smoke calls after the trend check; that function passed on its own at both sizes. The known 1920×1080 shape failure (`Axes` has no `_tramastat_shapes`) was not re-run.

Screenshots, the synthetic before/after projects, and the CSV, SVG, PNG, and PDF exports are in `docs/media/anova-diagnostics-070/`. The 1600×1000 copies use a `-1600` suffix. `*.alab` is gitignored for ordinary projects; the two synthetic projects in that folder are tracked on purpose. They contain no laboratory data.

This branch starts at UI A (`f2dfe57`, pull request 80). It does not contain the global-fit bands, lognormal, or PCA retention work. Version 0.70.0 is unchanged.

