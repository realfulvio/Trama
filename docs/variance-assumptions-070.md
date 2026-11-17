# Ordinary one-way variance homogeneity — 0.70.0

Choose **Group Comparison → One-way ANOVA** with **Method** set to **Ordinary**. The **Diagnostics/Assumptions** tab offers two optional checks, both off by default:

- `Brown–Forsythe variance test`
- `Bartlett variance test`
- `Variance test alpha`, default 0.05, visible only when Method is Ordinary and at least one check is on

Saved keys and choice values stay canonical English. The tab title, captions, the note, field errors, and unavailable-test reasons are translated. Sheet names, test names, and Decision tokens stay English. `set_language` does not rebuild a result that is already on screen.

This Brown–Forsythe test is Levene's test centered on each group median. It checks homogeneity of variance. It is not the Brown–Forsythe F* test of means in `unequal_anova.py`, and a small p-value does not switch Method to Welch. Bartlett's test is sensitive to non-normal data. That distinction is the note on the tab. There is no tooltip widget. Reason stays an empty string when the statistic is defined, so the note is not copied into the sheet.

The checks run on the same ordinary one-way fit that builds the ANOVA table. `inference.one_way_anova` is still called once. Post-hoc, comparisons, the trend, and Method are unchanged. Welch and "Welch and Brown–Forsythe" ignore the keys, including a hidden invalid alpha. Missing keys, or both checks off, leave the sheets, order, titles, numbers, and figure as they were.

## Sheets

`Variance assumptions` is added only when at least one check is on, after the ANOVA, comparison, and trend sheets. Columns are `Test`, `Statistic`, `df1`, `df2`, `p`, `Alpha`, `Decision`, `Reason`. Brown–Forsythe comes first, then Bartlett, and only the selected rows are present. The canonical test names are `Brown–Forsythe (median Levene)` and `Bartlett`.

Decision is `Reject` when p is strictly below alpha, `Do not reject` otherwise, and `NA` when the statistic is undefined. Alpha is written on every row, including an NA row. Changing alpha changes only Decision. Bartlett has no second degree of freedom: `df2` is missing and the CSV cell is blank, not 0. A defined test has an empty Reason.

`Variance groups` is added whenever at least one check is requested. Columns are `Group`, `N`, `Mean`, `Median`, `SD`, `Absolute deviation mean`. Group order is first appearance after `complete()`, not alphabetical order. N counts complete Response/Group rows. SD uses the sample variance (`ddof=1`) and is missing when a group has fewer than 2 rows. The absolute-deviation column is the mean of `|y − median|`. The engine does not mutate the caller's frame. Exclusions are the normal mask applied before `analyse`.

## Undefined results

A group with fewer than 2 complete rows makes both requested tests NA. The reason names every short group, in group order, and the ANOVA table is still returned. A group with variance that is not strictly positive makes Bartlett NA and names that group. Brown–Forsythe can still be defined. A zero Levene denominator, including constant absolute deviations inside every group, makes Brown–Forsythe NA. SciPy's `levene` and `bartlett` can return infinity and a p-value of 0 on those inputs. This result does not. One unavailable test does not block the other. `df1` is still `k − 1` on an NA row.

The absolute deviations and the Bartlett variances are scaled before the squares and the logarithms. A non-positive variance never reaches `log`. The checks match an independent formula and `scipy.stats.levene(..., center="median")` / `scipy.stats.bartlett` on the defined fixtures, including a scale of `1e-150` and `1e150` and a translation that stays representable.

## What the dialog keeps

Both checks are visible only for Ordinary. The tab is disabled for Welch and for "Welch and Brown–Forsythe"; if it was selected, the notebook returns to the first tab. Switching back to Ordinary in the same dialog restores the checks and the note and does not reset the checkboxes. A hidden alpha is stored only when it parses to a finite number strictly between 0 and 1. An invalid hidden alpha is omitted and does not fail the run. When both checks are off, alpha is not validated. A valid number still sitting in the hidden alpha field can be saved; the engine ignores it while both checks are off.

Flags must be real booleans. A visible alpha must be a finite number strictly between 0 and 1. Invalid input stays in the dialog, keeps the typed value, and moves the keyboard focus to that field. Run Analysis and Cancel stay reachable. A worker `FieldError` reopens the dialog on the alpha field and keeps the previous result. One-way ANOVA is still validated in the dialog, so a successful Run reuses that result. The smoke drops the cached result after validation so the injected worker error is the one that reopens the dialog.

## No graph

The One-way ANOVA result has `figure is None`. The method is not in `GRAPH_METHODS`, and this change does not add it. The navigator does not list a graph for the recipe. SVG, PNG, and PDF figure export, the Graph Inspector, and Format Graph are not applicable. The smoke does not invent a figure. CSV export and Use Result as Data cover the two sheets that do exist.

## Project file

`variance-assumptions-before.alab` is the synthetic table before the checks: columns Group and Y, groups A, B, and C, plus one incomplete response and one incomplete group. The recipe is Ordinary one-way ANOVA with the new keys absent. The result is the ANOVA sheet only.

The English result screenshot is that first run, before any later edit. Brown–Forsythe is about 5.798 (df1 2, df2 15, p about 0.0136) and Bartlett is about 12.976 (df2 blank, p about 0.00152).

The desktop smoke then writes 9.5 into the first response, excludes the next complete row, and saves `variance-assumptions-after.alab`. After that exclusion the group sizes are 5, 7, and 5. Brown–Forsythe is about 3.249 (df2 14, p about 0.0693, Do not reject at 0.05) and Bartlett is about 10.689 (p about 0.00477, Reject). The CSV and the Italian result screenshot are this later result. Reopening the project shows the data sheet first; opening the result recalculates the same sheets. Sheet titles stay English after the language changes. Use Result as Data, which the smoke runs before the Italian result screenshot, copies those sheets into the data list of the live window. That copy is not in the saved `.alab`.

The two projects contain no laboratory data. `*.alab` is gitignored for ordinary projects; these two files are tracked on purpose.

## Checks

Widgets were driven by the smoke script. These are not manual clicks. Screenshots are the whole X screen from ImageMagick `import`. The error sentence is checked on the message box, which the script dismisses; the error screenshots show the dialog afterwards, with the rejected value still in the field. DPI 125% and 150% are emulated with `tk scaling` on Linux and restored afterwards. The file names say `emulato`.

On this Tk build the dialog did not reflow. Button size stayed 123×27 for Run Analysis and 112×27 for Cancel, and the two screenshots at a given screen size are byte-identical.

| Screen | Scaling | Run Analysis | Cancel |
| --- | --- | --- | --- |
| 1024×768 | 1.2499807766243751 and 1.4989396035039186 | x=761 y=696 | x=641 y=696 |
| 1600×1000 | 1.2487708947885936 and 1.5011820330969265 | x=830 y=737 | x=710 y=737 |

Both buttons stayed mapped and viewable. The position changes with the screen because the dialog is not full-bleed. Windows was not available: **NON PROVATO**. Do not treat the Xvfb runs as a Windows or native-DPI result.

Interpreter: CPython 3.14.9. The package verifier names 3.13.14. No dependency was added.

| Check | Result |
| --- | --- |
| Package verifier, oracle only | 3 tests, OK in 0.015 s |
| Same verifier on the untouched base | FAIL: `Variance assumptions` absent; Bartlett zero-variance test errors with that missing sheet. `test_disabled` and `test_nonordinary_ignores_keys` already passed |
| Package verifier, oracle and repo, after the engine | 7 tests, OK in 0.422 s |
| `python -m unittest discover -s tests -q` under Xvfb 1024×768 | 1598 tests, OK in 81.704 s |
| `TRAMASTAT_SMOKE_ONLY=variance-assumptions`, Xvfb 1024×768 | PASS, `display.json` 1024×768 |
| Same targeted smoke, Xvfb 1600×1000 | PASS, `display.json` 1600×1000 |
| Full `tramastat.py --smoke` at 1024×768, this branch | FAIL, pre-existing |
| Same full smoke at `f2dfe57` (UI A, before this work) | FAIL, same assertion |

The full smoke stops in `check_workspace_setup` because the Layout ribbon button, after the window is set to 820×570, extends past `rootx + 820`. The same assertion fails on the untouched base. Both tracebacks are in `docs/media/variance-assumptions-070/`. The assertion was not weakened. The new project-cycle check is the function the full smoke calls after the trend check; that function passed on its own at both sizes. The known 1920×1080 shape failure was not re-run.

`git diff --check` on the uncommitted smoke and dialog hooks reported no whitespace errors.

Screenshots, the synthetic before/after projects, the CSV, the verifier logs, and the DPI measurements are in `docs/media/variance-assumptions-070/`. The 1600×1000 copies use a `-1600` suffix. There is no SVG, PNG, or PDF figure export, because the recipe has no figure.

This branch starts at UI A (`f2dfe57`, pull request 80). It does not contain the other open 0.70 drafts. Version 0.70.0 is unchanged.

