# Lognormal one-way ANOVA

**Group Comparison → One-way ANOVA** gains **Distribution**: `Normal` or `Lognormal`. `Normal` is the default. A saved recipe with no `Distribution` key stays on the existing path: the same sheets, numbers, order, and post-hoc columns as before. `inference.one_way_anova` is not edited. Lognormal calls that engine on a copy of the natural logarithms.

The branch is `grok/lognormal-anova`, cut from `da5be06615728a31ae219590929c297ce1ca56b3` (VERSION 0.72.0). VERSION is not changed. There is no new graph. The result `figure` stays `None`.

## Model

Every observation that the analysis actually uses is converted with one common offset (`centered_logs` on the whole used sample, not one offset per group). Ordinary ANOVA uses the sums of squares of those logs. Welch uses the log variances. **Welch and Brown–Forsythe** keeps the original Brown–Forsythe F* test of means, with df1 = k − 1. That is not the Mehrotra correction. A residual sum of squares that is not strictly positive still raises the existing ordinary-ANOVA error. No epsilon turns a degenerate sample into a result.

The geometric mean is `exp(mean of centered logs + offset)`. It is not `anchor * exp(centered mean)`, which underflows a representable tiny geometric mean. The geometric SD is `exp` of the sample standard deviation of the logs (denominator N − 1). A group with N < 2 leaves geometric SD and log SD missing and says so in `Note`.

Positivity is checked only after missing values, exclusions, and rows without a group have already been dropped. A used non-positive response raises `FieldError` on `Response`. An unused non-positive row does not. The caller's frame is not modified.

Group labels keep their Python identity. `1`, `"1"`, and `True` stay three groups when all three appear. Surrogate keys are used only when equality would otherwise collapse those labels, and the sheets show the original labels again.

## What is in this increment

Independent groups and raw observations only. Repeated measures with `Distribution` = `Lognormal` raises `FieldError` on `Distribution`. A lognormal **Linear trend** raises `FieldError` on `Linear trend`. The Normal trend, including a garbage `Ratio direction` left in a hidden field, is unchanged. Summary input (mean, SD, and N instead of raw rows) is not accepted.

`Ratio direction` is `First / Second` or `Second / First`. The default in the dialog is `First / Second`. The control is active only for Lognormal when a post-hoc test is requested. A garbage value in a hidden field does not block `Normal`, and it does not block Lognormal with post-hoc `None`.

`Confidence level (%)` must be finite and strictly between 0 and 100 when an interval is active. For lognormal Tukey and Games–Howell the chosen level is used. On the Normal path those two procedures stay fixed at 95%, and the level stays hidden, as before. Dunnett, Tamhane T2, and Dunnett T3 already took the level. Holm, Bonferroni, and FDR (Benjamini–Hochberg) adjust p values only. They do not gain an invented interval. Holm–Šídák is not added. The current method and post-hoc compatibility rules still apply.

## Sheets

`ANOVA` keeps the engine columns, including `F`, `F df1`, `F df2`, and `p`, computed on the log scale. Sums of squares and mean squares are in log units. An extra column `Scale` is `Natural logarithms`.

`Geometric summary` columns are `Group`, `N`, `Geometric mean`, `Geometric SD`, `Log mean`, `Log SD`, and `Note`. Group order is first appearance. `Log mean` is the natural log of the geometric mean (the common offset is added back). Identifiers are not coerced through `float`.

`Lognormal settings` is a one-column `Value` report: the common offset, the log base, whether the confidence level and the ratio direction were used, and how many rows were used or omitted.

When a post-hoc test is requested, `Multiple comparisons` keeps the engine contrast as `Log difference` and `Log SE` (first minus second on the logs). Log limits, when the procedure has them, are `Log CI low` and `Log CI high`. They are not labeled as differences on the original scale. The sheet also has `Numerator`, `Denominator`, `Log ratio`, `Ratio`, `Ratio CI low`, `Ratio CI high`, `Ratio status`, and `Ratio reason`.

`First / Second` reports `exp(log difference)` and exponentiates the log limits in the same order. `Second / First` reports `exp(−log difference)` and swaps the exponentiated limits. Adjusted p values do not change with the direction. `Ratio status` is `Available` when the ratio and its limits are finite and strictly positive. Otherwise it is `Unrepresentable`: finite pieces stay, the overflow cells are missing, and `Ratio reason` names the quantity. The sheet does not write a silent 0 or infinity. A p-only correction leaves both ratio-interval cells empty. Its reason is `Point ratio only. This correction adjusts p values and does not produce an interval.` A simultaneous interval says `Simultaneous ratio interval.`

If Brown–Forsythe homogeneity or Bartlett is on, both run on the logs. `Variance assumptions` and `Variance groups` say so in `Scale` and in a note. That Brown–Forsythe row remains the median-centered Levene test. It is not F*. Group columns are renamed to `Log mean`, `Log median`, `Log SD`, and `Log absolute deviation mean`. The common offset is added to the mean and the median before the rename. The SD is unchanged by a shift.

## Dialog

Captions and the new choices are English and Italian under `anova.lognormal.*`. The `.alab` file stores the canonical English values (`Lognormal`, `Second / First`), not the translated labels. Group labels stay as written.

The Options page of every One-way dialog scrolls, so **Run Analysis** and **Cancel** stay on a 1024×768 screen after Distribution, ratio direction, the level, and the note are added. The Diagnostics tab is a separate notebook page and is not inside that scroller. Focusing a field selects the notebook page that contains it and scrolls that page until the control is visible. A failed check leaves the dialog open on that field.

A worker `FieldError` reopens the dialog and keeps the previous result. The same recovery runs when a data edit or an exclusion makes a confirmed lognormal analysis invalid. A Normal one-way edit still clears the result, which is what the existing unequal-variance smoke expects. Use Result as Data, CSV export, and save/reopen are covered by the smoke. Italian decimal commas are accepted in the level field (`90,5` is 90.5). Cancelling that edit leaves the confirmed analysis at the level it already had.

The Options-page scroll frame means an Options control's immediate parent is no longer the notebook tab. The unequal-variance smoke and the trend smoke still require the selected notebook page to be the page that contains the field. They walk up to that page. The check was not removed.

## Checks

Widgets were driven by the smoke script. Screenshots are the whole X screen from ImageMagick `import -window root`. Xvfb supplied the screen. This is not a Windows session and it is not a native DPI measurement. `native_dpi` in the 1600×1000 app file is empty. Windows was not available: **NON PROVATO**.

The 1024×768 app dpi file was replaced by the smoke's button record (`display-1024.json`). The 1600×1000 app file is `display-app-1600.json`: width 1600, height 1000, `ui_scale` 1.0426929392446633, font DejaVu Sans.

| Screen | Run Analysis | Cancel |
| --- | --- | --- |
| 1024×768 | x=761 y=637, 123×27 | x=641 y=637, 112×27 |
| 1600×1000 | x=830 y=678, 123×27 | x=710 y=678, 112×27 |

Both buttons stay inside the screen (bottom 664 of 768, and 705 of 1000).

`lognormal-anova-before.alab` is the blocked counts 1, 2, 4, 8, 16, 32, 64, 128, 256 in groups A, B, C, with an ordinary recipe and no Distribution key. That result has no geometric summary. The English result screenshot is the lognormal Tukey fit of that table, before the later edit: geometric means 2, 16, and 128, geometric SD 2, ratios 8, 64, and 8 for Second / First. The smoke then writes 1.5 into the first response, excludes the next A row, and saves `lognormal-anova-after.alab`. The CSV is that later geometric summary (group A has N = 2). Reopening recalculates the same sheets. The recipe in the file is `Lognormal` and `Second / First`. The Italian word `Lognormale` is not in the recipe.

The packet baseline of 4/17 was not saved as JSON before the engine existed. It was not reconstructed by editing the oracles. The candidate verifier after the dialog work is `verifier-candidate.json`: 17/17, exit 0.

Interpreter: CPython 3.14.10. Packages are the pinned set in `requirements.txt` (matplotlib 3.11.2, numpy 2.5.4, pandas 3.1.1, scipy 1.18.1, statsmodels 0.15.0). No dependency was added.

| Check | Result |
| --- | --- |
| `python -m unittest discover -s tests -q` under Xvfb 1024×768, before the legacy-error guard | 2141 tests, OK in 122.118 s, exit 0 |
| Same suite after that guard | 2141 tests, OK in 146.878 s, exit 0 |
| `tests.test_lognormal_anova` after the guard | 10 tests, OK in 11.160 s, exit 0 |
| Packet verifier `--repo` after the dialog | 17/17, exit 0 |
| `TRAMASTAT_SMOKE_ONLY=lognormal-anova`, Xvfb 1024×768 | PASS, exit 0 |
| Same targeted smoke, Xvfb 1600×1000 | PASS, exit 0 |
| Targeted smoke again at 1024×768 after the legacy-error guard | PASS, exit 0 |
| `TRAMASTAT_SMOKE_ONLY=anova-trend`, Xvfb 1024×768, after the page walk and the guard | PASS, exit 0 |
| Full `tramastat.py --smoke` at 1024×768 with screenshots | exit 1 after 479.73 s. The new lognormal check had already run. The process then raised `RuntimeError: The 1600×1000 view needs a screen of at least 1680×1050` in `analisi/pca_selection_smoke.py` |
| Same full smoke, Xvfb 1680×1050, screenshots on | PASS, exit 0, 571.58 s |

The legacy-error guard keeps Normal-path sentences on Linear trend, Response, and Confidence level in their existing wording. Lognormal sentences from this module are still translated. An earlier full smoke, before the Options page walk, stopped in `check_unequal_anova` because `Post-hoc` was no longer a direct child of the notebook tab. That assertion now walks to the tab. It still requires the selected page to be the one that holds the field. The 1024×768 screenshot run then passed that check, the trend check, and `check_lognormal_anova_smoke`. It stopped later in `pca_selection_smoke.py`, which refuses a screenshot run when the screen is smaller than 1680×1050. That raise was not changed. The same command on an Xvfb screen of 1680×1050 finished with `status.txt` `PASS` and exit 0 in 571.58 s. Both logs are in `docs/media/lognormal-anova/`.

Screenshots, both projects, the CSV, the button records, and the verifier JSON are in `docs/media/lognormal-anova/`. The 1600×1000 copies use a `-1600` suffix. `*.alab` is gitignored for ordinary projects; these files are tracked on purpose. There is no SVG, PNG, or PDF figure export, because the recipe has no figure.

## Files

- `analisi/lognormal_anova.py` — lognormal engine, validation, and sheet shaping.
- `analisi/additional.py` — dispatch for One-way, and the repeated-measures refusal.
- `analisi/i18n.py` — `anova.lognormal.*` and the `Ratio direction` caption key.
- `tramastat.py` — scrollable Options page, choice bindings, level visibility, recovery, smoke registration.
- `analisi/lognormal_anova_smoke.py` — real-dialog smoke, selector `lognormal-anova`.
- `analisi/unequal_anova_smoke.py`, `analisi/trend_anova_smoke.py` — notebook-page walk for Options fields.
- `tests/test_lognormal_anova.py` — closed form, Welch and Brown–Forsythe against an independent log fit, post-hoc p values and reciprocal ratios, levels 90 and 99, a ratio interval that covers 1, positivity, typed labels, scales, unrepresentable ratios, variance sheets, trend and repeated measures, and 21 Normal recipes against the untouched engine.

