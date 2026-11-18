# Multifactor ANOVA: Type I, Type II and Type III sums of squares

Choose **Group Comparison → Multifactor ANOVA** and open the **Model** tab. Under **Term selection** and **Interaction order** there is now a **Sums of squares** selector (in Italian, *Somme dei quadrati*) with three values:

| Value (IT) | Meaning | Result sheet |
| --- | --- | --- |
| `Type III` (*Tipo III*), the default | Each term is tested after every other term of the model, including the interactions that contain it | `ANOVA (type III)` |
| `Type I` (*Tipo I*) | Sequential: each term is tested after the terms that come before it, in the order of the model | `ANOVA (type I)` |
| `Type II` (*Tipo II*) | Each term is tested after the terms that do not contain it (marginality) | `ANOVA (type II)` |

The selector works in **Full hierarchy** and in **Selected terms**. Nothing else changes: the residual row, the model fit, the estimated marginal means and post hoc comparisons, and the residual diagnostics come from the same fit in every type.

```json
{"Response": "Y", "Factors": ["Dose", "Drug"], "Interaction order": 2, "Sums of squares": "Type I"}
```

A recipe without `Sums of squares` is Type III, so every project and script saved before this option gives the same sheets and numbers. A new recipe that stays on Type III is saved without the key, unless the recipe being edited already had it. Saved values are canonical English in both languages (`Type I`, never *Tipo I*). Any other value is refused on the field `Sums of squares`.

## What the three types compute

All types start from the one sum-to-zero design that the analysis fits once. A *reduced* model is that same design with some term blocks left out; it is never rebuilt from a formula, so the interaction columns, and the hypothesis they test, are the same in every type. The residual sum of squares, the residual df and the mean square error that divide every F are those of the full model.

* **Type I.** Terms enter in model order: first the main effects, then the two-way interactions, then the three-way ones; terms of the same size follow the position of their factors in `Factors`. The sum of squares of a term is the drop in the residual sum of squares when it is added to the intercept and every earlier term. The sums of squares of all terms plus the residual add up to the total sum of squares about the mean.
* **Type II.** For a term T the smaller model holds the intercept and every other term that does not contain T as a proper subset of its factors. In `A + B + C + A:B`, `A` is tested after `B` and `C`, and `C` after `A`, `B` and `A:B`. The sum of squares is the drop in the residual sum of squares when T is added to that model, and the df is the number of columns of T.
* **Type III.** The historical code, untouched: the increase of the residual sum of squares when only the columns of the term are removed from the full model.

With **balanced** data (equal counts in every cell) the three types give identical numbers for every term. They differ when the cells have unequal counts, and that is the case to read carefully.

## Worked example, balanced

Two drugs by two doses, three animals per cell, 12 responses. `Factors = [Drug, Dose]`, `Interaction order = 2`.

| Term | SS | df | MS | F | p |
| --- | ---: | ---: | ---: | ---: | ---: |
| Drug | 18.75 | 1 | 18.75 | 18.75 | 0.0025 |
| Dose | 90.75 | 1 | 90.75 | 90.75 | < 0.0001 |
| Drug:Dose | 6.75 | 1 | 6.75 | 6.75 | 0.0317 |
| Residual | 8.00 | 8 | 1.00 | | |

The table is the same for Type I, Type II and Type III.

## Worked example, unbalanced

Same two factors, 12 responses, but the cells hold 5, 2, 1 and 4 animals (Drug A: Low 5, High 2; Drug B: Low 1, High 4). The residual row is 8.00 on 8 df in every type, because it comes from the same fit.

| Term | Type III SS | Type II SS | Type I SS (Drug first) | Type I SS (Dose first) |
| --- | ---: | ---: | ---: | ---: |
| Drug | 12.8205 | 17.5513 | 78.8667 | 17.5513 |
| Dose | 51.2821 | 46.6846 | 46.6846 | 108.0000 |
| Drug:Dose | 4.6154 | 4.6154 | 4.6154 | 4.6154 |
| Residual | 8.0000 | 8.0000 | 8.0000 | 8.0000 |

How to read it:

* **Drug:Dose is the same in every type** because it is the last term and the highest-order one.
* **Type II** tests Drug after Dose and Dose after Drug, without the interaction. Type III tests each main effect with the interaction in the model, which can give another value when the cells are unequal.
* **Type I depends on the order.** Drug first absorbs everything that Drug and Dose share, and Dose then gets only what is left (and the reverse when Dose comes first). The first term of a Type I table has no adjustment at all. Use Type I when the order has a meaning (a covariate-like factor entered first, a nested sequence) and say which order you used.
* The `Eta²` and `Partial eta²` columns are computed from the sums of squares of the type chosen. In Type II and Type III the sums of squares of different terms can overlap in an unbalanced design, so the `Eta²` values need not add up to 1; in Type I they add up to the explained fraction.

## Factor order and the Type I preview

Type I depends on the order of `Factors`, so the Model tab shows what it needs when Type I is chosen:

* A short note: Type I adds the terms in the order shown, and each term is tested after the ones before it.
* **Factor order**, a list of the ticked factors with native **Up** and **Down** buttons. The list starts from the order of `Factors` in the recipe being edited, and the order you leave is written into `Factors` of the recipe. The Factors list of the Variables page keeps the worksheet order; only this list orders the factors for Type I.
* A preview line, *Terms enter in this order: Dose → Drug → Dose:Drug*, that follows the Interaction order, or the terms ticked under Selected terms, and updates after every Up or Down.

A factor that is unticked for a moment keeps its place, and a newly ticked factor goes last. Terms already ticked in Selected terms stay ticked when the order changes: reordering only changes the sequence, never the model.

Type II shows one note, only when the model has an interaction: it tests each term after the terms that do not contain it. Type III shows no note.

## Result sheets and files

* The first sheet is `ANOVA (type I)`, `ANOVA (type II)` or `ANOVA (type III)`. Sheet names are canonical English in both languages, so a saved project, an exported CSV and **Use Result as Data** do not depend on the language. The selector adds no extra sheet.
* **Effect sizes** use the sums of squares of the active type.
* **Model fit**, the **residuals** and the diagnostics, and the **post hoc** comparisons are the same in every type.
* A `.alab` project keeps the recipe with `Sums of squares` and the order of `Factors`. Reopening it, editing the data, excluding a cell and recalculating reproduce the same type and the same order.

## Errors

* A value other than `Type I`, `Type II` or `Type III` is refused on the field: *Sums of squares: Choose Type I, Type II or Type III sums of squares.*
* A model that is not identifiable keeps the existing refusals (empty cells, redundant terms, no residual degrees of freedom).
* If the sums of squares of a type do not match the residuals of the full fit within rounding (a pathological scale of the response), the analysis stops with *The sums of squares could not be computed reliably for this model. Check the scale of the response and the model terms.* It does not print a table it cannot trust.

## Limits

The analysis keeps its limits: one to eight factors, interactions up to order 3 (Full hierarchy), 2 to 128 levels per factor, `coefficients × rows ≤ 4,000,000` and fewer coefficients than rows. Covariates, weak hierarchy and terms of order higher than 3 are not covered, as before.

## Choices made

* One full fit is shared by the three types. Type I and Type II are computed from a QR factorization of the reduced design with the centered response as an extra column, so a sum of squares is a sum of squared coordinates and not the difference of two large residual sums.
* A term is identified by the positions of its factors in the model, never by a text label, so factor names that contain `:`, `|` or spaces cannot be mistaken for model separators.
* Type III keeps the historical code path; its numbers are bit-for-bit unchanged.
* Type I is the only type for which the order of `Factors` matters. The order is stored in `Factors`, not in a second key, so a recipe has one list of factors and one order.

## Not covered

* Type IV sums of squares and unbalanced-design options beyond Types I, II and III.
* Covariates and nested terms.
* **Windows and native Windows DPI were not available while this was written: NON PROVATO.** Linux/Xvfb runs are not a Windows result.

## Checks

Base: `9675233` (main, 0.92.0). Platform: Linux 6.18 container under Xvfb, CPython 3.12.3, Tk 8.6, numpy 2.5.4, pandas 3.1.1, scipy 1.18.1, statsmodels 0.15.0, patsy 1.0.3. No dependency was added. Windows and native Windows DPI were not available: **NON PROVATO**.

| Check | Result |
| --- | --- |
| External contract verifier (`--repo`, `--json`), 35 checks | 35/35 PASS (22/35 on the base) |
| Contract test `test_candidate_contract.py` | OK |
| `tests/test_anova_ss.py` (28 tests) and `tests/test_anova_ss_dialog.py` (15 Tk tests) | OK |
| Whole suite, one module per process under Xvfb 1920 × 1080, 235 modules | 2773 tests; 234 modules OK; `test_formula_windows` has 1 failure and 1 error, the same two on the base `9675233` (a pandas 3.1 behaviour, unrelated to this change) |
| `TRAMASTAT_SMOKE_ONLY=anova-ss-types`, 1024 × 768 and 1600 × 1000, Standard and Modern, EN and IT preferences (8 runs, isolated home, preferences and export folder) | 8 × PASS |
| Full `tramastat.py --smoke`, Xvfb 1920 × 1080, Standard, EN, screenshots on (about 16 minutes) | PASS, exit 0, `status.txt` PASS |
| `git diff --check` | clean |

The verifier compares the application with independent definitions of the three types on balanced, unbalanced, reversed-factor, selected-terms and three-way designs, plus the legacy recipe, the effect sizes and the refusal of an unknown value. Independently, the unit tests recompute every sum of squares from the residual sums of squares of nested models, and the unbalanced example above agrees with `statsmodels.stats.anova.anova_lm` for `typ=1`, `2` and `3`.

The smoke `anova-ss-types` covers, on one synthetic 2 × 3 × 2 plate study with unequal cell counts and a factor name with spaces and parentheses and levels that contain `|`, `:` and spaces: the legacy recipe unchanged; the default Type III equal to the historical tables; Type I with the order visible in the dialog and the preview line; the factors reordered with Up and the table recomputed in the new order; the order reopened from the saved recipe; Type II unaffected by the order; Selected terms with the same selector, the effect sizes, the residual diagnostics and a post hoc comparison, where every sheet other than the ANOVA table and the effect sizes is identical in the three types; a data edit and an excluded cell refitted; the CSV exports; save and reopen of the `.alab` in the other language; **Use Result as Data**; the Italian dialog; a model error that reopens the dialog on the field and keeps the confirmed analysis; and the correction. Each table is compared with an independent statsmodels fit of the same model. The widgets were driven with `Button.invoke`, combobox variables and `event_generate`, which are events sent to real widgets and not the mouse or the keyboard of a person. Screenshots are the whole X screen from ImageMagick `import`.

Real screenshots, the Type I CSV and the synthetic project are in `docs/media/anova-ss-types/`. `*.alab` is gitignored for ordinary projects; the synthetic project in that folder is tracked on purpose and contains no laboratory data.

| File | Shows |
| --- | --- |
| `window-anova-ss-dialog-en.png`, `-dialog-it.png` | Model tab with Type I, the note, the factor list in the saved order and the preview line, EN and IT (Standard, 1024 × 768) |
| `window-anova-ss-order-en.png`, `-order-it.png` | the same after Group is moved above Dose with Up |
| `window-anova-ss-type-one-en.png`, `-type-one-it.png` | the `ANOVA (type I)` table |
| `window-anova-ss-type-two-en.png`, `-type-two-it.png` | the `ANOVA (type II)` table |
| `window-anova-ss-selected-type-two-en.png`, `-it.png` | Selected terms with Type II (note about marginality) |
| `*-modern-1600.png` | the Modern theme at 1600 × 1000 |
| `anova-ss-type-one.csv`, `anova-ss-italian.alab` | the exported Type I sheet and the project saved from the Italian dialog |

## Performance

`tests/bench_anova_ss.py` builds synthetic data with a fixed seed near the supported size of the design (`coefficients × rows` close to 4,000,000) and times `analyse` for each type, median of three runs, on the container above (4 cores, no other load). Run it once per source tree, in the same environment: `python tests/bench_anova_ss.py --tree . --runs 3`.

| Case | Rows | Coefficients | Terms | Type III (s) | Type I (s) | Type II (s) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 10 × 10 × 10 levels, order 3 | 3990 | 1000 | 7 | 2.90 | 0.71 | 0.88 |
| eight factors with 3 levels, order 3 | 6900 | 577 | 92 | 19.92 | 0.63 | 13.24 |
| one factor with 100 levels beside 4 and 3, order 2 | 3000 | 606 | 6 | 0.95 | 0.36 | 0.58 |

Type III is the unchanged historical path and is the slowest in these cases. Type I is one factorization. Type II needs one factorization per term, so it grows with the number of terms (92 in the second case) and stays below Type III. The peak resident memory of the whole benchmark process was 370 MB.
