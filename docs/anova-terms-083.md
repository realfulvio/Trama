# Multifactor ANOVA with a choice of terms — 0.83

Choose **Group Comparison → Multifactor ANOVA** and open the **Model** tab, which now follows **Variables**. Two canonical options decide the model:

| Option | Values | Default |
| --- | --- | --- |
| `Term selection` | `Full hierarchy`, `Selected terms` | `Full hierarchy` |
| `Model terms` | a list of terms, each a list of factor names | the terms of Full hierarchy |

`Full hierarchy` is the behaviour of every earlier version: every main effect and every interaction up to `Interaction order`, fitted exactly as before. A recipe saved before 0.83 has neither new key and gives the same sheets, statistics and figures. A new recipe in Full hierarchy is also saved without the two keys, unless the recipe being edited already had them.

`Selected terms` fits only the terms that are ticked. The same fit feeds the ANOVA table, the effect sizes, the model fit, the estimated marginal means and post hoc comparisons, and the residual diagnostics, so no sheet describes a different model from the others.

```json
{"Response": "Y", "Factors": ["Dose (mg)", "Group", "Lot 24"],
 "Term selection": "Selected terms",
 "Model terms": [["Dose (mg)"], ["Group"], ["Lot 24"], ["Dose (mg)", "Lot 24"]]}
```

Names in `Model terms` are the literal column names. They are never Patsy expressions, so a name such as `Dose (mg)` or `Lot 24` needs no quoting and no escape. Saved values stay canonical English in both languages (`Selected terms`, not its Italian caption), and the factor names are not translated.

The result sheets quote factor names containing colons or quotation marks, and a factor named `Residual`. That keeps a literal name distinguishable from an interaction or the residual row.

## The Model tab

* **Term selection** switches between the two modes. Interaction order is shown only in Full hierarchy, because Selected terms does not use it.
* **Main effects**, **Two-way interactions** and **Three-way interactions** list one checkbox per term that the chosen Factors allow, up to three factors per term. Select all, Clear and Add required terms sit above them.
* A summary line shows the model as `Y = A + B + A:B`. A second line names the chosen factors that no term uses (they stay out of the fit and out of the selection of complete rows). A red line names every term that lacks a prerequisite.
* A picker that has never been edited, and was not given a saved list, follows the Full hierarchy of the chosen Factors and Interaction order. The first edit freezes it. Switching to Selected terms therefore starts from the model Full hierarchy would fit, and the user prunes from there.
* The ticked terms are kept as a set of factor-name sets, not in the Tk widgets. A term survives while its factor is deselected for a moment and comes back with the factor, and a saved recipe that names a factor which is not among the Factors is refused by name.
* The page scrolls with the mouse wheel and with the keyboard focus, and Run Analysis and Cancel stay in the dialog button row. At 1024 × 768 the dialog fits the screen.

## Hierarchy and nothing added silently

Strong hierarchy is required: a two-way interaction needs both of its main effects, and a three-way interaction needs its three main effects and its three two-way interactions. The application never adds a missing term by itself. The dialog names the missing prerequisite beside the term, **Add required terms** adds them on request, and **Run Analysis** refuses the recipe with `Model term A:B needs A in the model (strong hierarchy).` and puts the focus on the first checkbox of the Model page. A recipe that arrives from a saved project or from a script gets the same refusal.

Other refusals name `Model terms` as well: an empty list, a term with no factor, a term that repeats a factor, a term of more than three factors, the same term listed twice, a factor that is not among the Factors, and a model that is not identifiable (empty cells, redundant terms, no residual degrees of freedom or no measurable residual variance). The editor stays open on the error and keeps what was typed. An error that is first known on the worker reopens the existing analysis-recovery dialog, keeps the confirmed analysis and focuses the field.

## What is fitted

* The design has an intercept, the sum-to-zero (deviation) columns of each selected main effect, and for each selected interaction the row-wise products of the columns of its factors. The last level of a factor, in sorted order of its text, is the reference that carries −1. Only the selected terms are built.
* Terms are sorted by order, then by the position of their factors in `Factors`; the factors of a term follow `Factors` as well, so `Group:Dose (mg)` and `Dose (mg):Group` are the same term.
* **Type III.** The sum of squares of a term is the increase of the residual sum of squares when only that term's columns are removed from the same fit, divided by the number of columns removed, and F uses `MSE = SSE_full / residual df` of the selected model. With strong hierarchy and sum coding that is the usual Type III test. Rank, small negative differences and the size budget of the design matrix are checked as before, on the model that is fitted.
* **Rows.** A row is used when the response and every factor that appears in a term are present. Excluded cells and missing values behave as they do for Full hierarchy.
* **Effect sizes and model fit** use the same sums of squares and residual degrees of freedom. The *Model terms* sheet lists each selected term with its order, its degrees of freedom and its kind of effect.
* **Estimated marginal means and post hoc comparisons** use the design matrix of the selected model. The mean for one level of a compared factor is the average of the design rows over the levels of the other factors of the model, each combination of levels counted once (equal weights, the usual estimated marginal mean). Factors outside the model do not enter that average. Comparisons of cells, simple effects and control levels use the same design. A factor that is in no term cannot be compared, and the error says so on the field that named it. Tukey and Dunnett keep their existing coordinates and family handling.
* **Residual diagnostics** (leverage, studentized residual, Cook's distance, PRESS, the five assumption tests and the graphs) are computed from the same full-model design, coefficients and residuals.

When the ticked terms are the Full hierarchy of the chosen Factors, the numbers equal the Full hierarchy numbers; a unit test compares them to the historical Patsy fit for orders 1 to 3, including factor levels that look like numbers.

## Result sheets

Selected terms inserts one sheet, `Model terms`, right after the ANOVA sheet (`ANOVA (type III)` by default; `ANOVA (type I)` or `ANOVA (type II)` when [another type of sums of squares](anova-ss-types.md) is chosen). The other sheets keep their names and order. Sheet names stay canonical English in both languages, so a saved project, an exported CSV and `Use Result as Data` do not depend on the language. Full hierarchy adds no sheet.

## Project file

A `.alab` project keeps the recipe, with `Term selection` and `Model terms` in the canonical form above. Reopening a project, editing the data, excluding a cell and recalculating refit the same selection. Choosing Full hierarchy again in the editor drops `Model terms` and the sheet, and keeps `Term selection` when the saved recipe already had it.

## Choices made

* Strong hierarchy only. A model with an interaction and no main effect (weak hierarchy) is refused instead of being fitted, because Type III with sum coding only means what it says under strong hierarchy.
* The ticked set is the truth. Changing Factors or Interaction order after the first edit never adds or removes a term silently; a term that uses a deselected factor is dropped from the request, not from the set.
* Type III removes columns of the one design that is fitted, so the design is built once per analysis and its size is checked once.
* The Model tab is a scrollable page, the same way the heat map Layout tab is, so 1024 × 768 needs no smaller font or fewer terms.

## Not covered

* Weak hierarchy, nested terms, covariates and terms of order higher than 3. The dialog still takes one to eight Factors, each with 2 to 128 levels in the rows the model uses.
* Type I and Type II sums of squares are described in [anova-ss-types.md](anova-ss-types.md); this page describes the Type III default.
* Windows and native Windows DPI were not available while this was written: **NON PROVATO**. Linux/Xvfb runs are not a Windows result.

## Checks

Widgets were driven by the smoke scripts (`Checkbutton.invoke`, `Button.invoke`, combobox and entry variables, `event_generate` for the factor list). These are events sent to real widgets, not the mouse or the keyboard of a person. Screenshots are the whole X screen from ImageMagick `import`, taken on synthetic data (a 2 × 2 × 3 plate study with one missing response). Error sentences were checked on the message box, which the script dismisses; the error screenshots show the dialog afterwards, with the focus on the first checkbox of the Model page.

Base: `d60d6a7` (main, 0.83 beta). Platform: Linux 6.18 container under Xvfb, CPython 3.12.3, Tk 8.6.14, numpy 2.5.4, pandas 3.1.1, scipy 1.18.1, statsmodels 0.15.0, patsy 1.0.3. No dependency was added. Windows and native Windows DPI were not available: **NON PROVATO**.

| Check | Result |
| --- | --- |
| External contract verifier (`--repo`, `--json`), 11 checks | 11/11 PASS (5/11 on the base) |
| `python -m unittest discover -s tests -q` under Xvfb 1280 × 900 | 2604 tests, OK in 236.5 s |
| `TRAMASTAT_SMOKE_ONLY=anova-selected-terms`, 1024 × 768 and 1600 × 1000, Standard and Modern, EN and IT preferences (8 runs, isolated home, preferences and export folder) | 8 × PASS |
| Full `tramastat.py --smoke`, Xvfb 1920 × 1080, screenshots on | PASS, exit 0 |
| `git diff --check` | clean |

The first full smoke failed in `check_anova_effect_sizes`, an existing check that asserts `dialog.anova_fields() == {ANOVA_ALPHA: False}`. The Interaction order visibility had been added to that method; it now lives in `anova_term_fields()`, and the existing assertion is unchanged.

The smoke `anova-selected-terms` covers, on one project: the legacy recipe unchanged; the Model tab after Variables with the groups, the summary and the factors left out; a term edited out; a missing prerequisite refused with the focus on the Model page, then restored with Add required terms; the Type III table and the effect sizes against an independent statsmodels fit of the same model; Full hierarchy from the dialog equal to the legacy tables with a recipe free of the new keys; a data edit and an excluded cell refitted; the CSV of the new sheet and of the ANOVA table; save and reopen of the `.alab`; Use Result as Data; cancel leaving the project as it was; an Italian dialog with canonical values in the recipe and the saved project; switching back to Full hierarchy; an unidentifiable model reopening the dialog on Model terms and keeping the confirmed analysis. The main flow runs in the language of the stored preference; the Italian dialog runs in either case.

Real screenshots, the synthetic project and the CSV exports are in `docs/media/anova-terms-083/`. `*.alab` is gitignored for ordinary projects; the synthetic project in that folder is tracked on purpose and contains no laboratory data.

| File | Shows |
| --- | --- |
| `window-anova-terms-fields-en.png`, `-fields-it.png` | Model tab with Selected terms, EN and IT (Standard, 1024 × 768) |
| `window-anova-terms-error-en.png`, `-error-it.png` | the strong-hierarchy refusal, with the focus on the first checkbox |
| `window-anova-terms-ready-en.png` | the model ready to run |
| `window-anova-terms-anova-en.png`, `-sheet-en.png`, `-results-it.png` | the Type III table, the Model terms sheet, the Italian result |
| `*-modern-1600.png` | the same dialog in the Modern theme at 1600 × 1000 |
