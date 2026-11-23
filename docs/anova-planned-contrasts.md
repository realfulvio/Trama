# Multifactor ANOVA: planned contrasts

A planned contrast is a comparison you decide **before** looking at the results: a treatment against the mean of two controls, a linear trend over doses, a difference of differences. Trama combines the estimated marginal means of the ANOVA model with your coefficients, which must add up to 0, and reports one row per contrast with its estimate, standard error, t test and confidence interval.

In Classica or Qt choose **Analyze → Multifactor ANOVA** (*Analisi → ANOVA multifattoriale*) and press **Planned contrasts…** (*Contrasti pianificati…*). The editor works on a copy: nothing changes in the analysis until you press OK in the editor and then Run (*Esegui*) in the ANOVA dialog. Cancel leaves the recipe as it was.

## The editor

* **Factors of the contrasts** (*Fattori dei contrasti*): the factors whose cells the weights name. Only factors that are in the model can be ticked (all of `Factors` in Full hierarchy, the factors of the chosen terms in Selected terms). The levels of every weight follow the order of this list. The model factors left out are averaged over with equal weight.
* **Correction** (*Correzione*): `Holm` (default), `Bonferroni` or `None`. It changes only the `Adjusted p` column, never the intervals.
* **Alpha of the intervals** (*Alfa degli intervalli*): 0.05 by default (*0,05* in Italian). The intervals are pointwise t intervals at level 1 − alpha.
* **Contrasts** (*Contrasti*): Add, Duplicate, Up, Down and Remove. Each contrast has a **Name** and a table of **Weights**: one level for each chosen factor (a drop-down list) and a **Coefficient**. Coefficients may be negative, decimal (0.5, or 0,5 in Italian) or fractions such as `-1/3`. Under the table the editor shows the sum of the coefficients and says when it is not 0.

Names, factors and levels are literal text: `Control $`, `B |` or a name with `−` are kept exactly as typed, in every language. Errors stay in the editor, select the contrast and the weight row that caused them, and say why in the active language.

A recipe saved with a level that is no longer in the data (for example after excluding every row of that level) still opens: the level is shown as *`<level>` (not in the data)* and the editor reports it until you choose another level or remove the weight.

## Recipe

Four keys are added to the `Multifactor ANOVA` recipe. Values are canonical English in both languages.

```json
{
  "Response": "Score",
  "Factors": ["Treatment", "Visit"],
  "Interaction order": 2,
  "Planned contrast factors": ["Treatment", "Visit"],
  "Planned contrasts": [
    {"name": "Treatment − Control $", "weights": [
      {"levels": ["Treated", "A"], "coefficient": 0.3333333333333333},
      {"levels": ["Treated", "B |"], "coefficient": 0.3333333333333333},
      {"levels": ["Treated", "C"], "coefficient": 0.3333333333333333},
      {"levels": ["Control $", "A"], "coefficient": -0.3333333333333333},
      {"levels": ["Control $", "B |"], "coefficient": -0.3333333333333333},
      {"levels": ["Control $", "C"], "coefficient": -0.3333333333333333}]},
    {"name": "Difference of differences", "weights": [
      {"levels": ["Control $", "A"], "coefficient": 1},
      {"levels": ["Control $", "C"], "coefficient": -1},
      {"levels": ["Treated", "A"], "coefficient": -1},
      {"levels": ["Treated", "C"], "coefficient": 1}]}
  ],
  "Planned contrast correction": "Holm",
  "Planned contrast alpha": 0.05
}
```

A recipe without `Planned contrasts`, or with an empty list, is the analysis as before: the other three keys are not read and no sheet is added, so every project and script saved before 0.96 gives the same sheets and numbers. The classic Tk dialog has no contrast editor; it keeps the four keys of a recipe saved in Qt unchanged.

## Worked example

The data are in `tests/data/planned_contrasts/contrasti-pianificati.csv`: two treatments by three visits, three subjects per cell, 18 responses. The cell means are:

| Treatment | A | B \| | C | Marginal mean |
| --- | ---: | ---: | ---: | ---: |
| Control $ | 2 | 4 | 6 | 4 |
| Treated | 3 | 7 | 11 | 7 |

Every cell has variance 1, so the mean square error is 1 on 12 residual df. With the recipe above, Run adds two sheets after the post hoc comparisons:

**Planned contrasts**

| Contrast | Estimate | SE | df | t | p | Adjusted p | CI low | CI high | Status |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Treatment − Control $ | 3 | 0.4714 | 12 | 6.364 | 3.59e-05 | 7.18e-05 | 1.973 | 4.027 | OK |
| Difference of differences | 4 | 1.1547 | 12 | 3.464 | 0.00468 | 0.00468 | 1.484 | 6.516 | OK |

* *Treatment − Control $* is 7 − 4 = 3. Each marginal mean averages three cells of three subjects, so its variance is MSE/9 and the difference has SE √(2/9) = 0.4714.
* *Difference of differences* is (11 − 3) − (6 − 2) = 4, with SE √(4/3) = 1.1547.
* Holm multiplies the smallest p by 2 and the next by 1 (never below the previous adjusted p).

**Planned contrast weights** lists each weight as a row (`Contrast`, one column per chosen factor, `Coefficient`), so the recipe can be checked from the results. When a factor is named `Contrast` or `Coefficient`, its column becomes `Contrast (factor)`.

Sheet and column names stay canonical English in both languages, like the other ANOVA sheets, so exported CSV files and `Use Result as Data` do not depend on the language.

## How it is computed

* **Same fit.** The contrasts use the coefficients, residual SS and df of the ANOVA fit already made (any type of sums of squares, Full hierarchy or Selected terms). No second fit is made, and the ANOVA table, the post hoc comparisons and the diagnostics are unchanged.
* **Marginal means.** The marginal mean of a cell of the chosen factors is the equal-weight average of the model predictions over every level combination of the model factors left out of the contrast (unweighted, "population" marginal means). With unbalanced data this is not the raw mean of the rows.
* **Estimate and SE.** For the contrast row L = Σ coefficient × marginal row, the estimate is L·β and the variance MSE × L (X′X)⁺ L′, computed from the singular value decomposition of the design (X = U S V′ gives MSE × ‖S⁻¹ V′ L′‖²), without normal equations.
* **Corrections.** Holm's step-down or Bonferroni act jointly on the finite p values of the recipe's contrasts. Rows stay in recipe order, ties included.

## Thresholds and limits

| What | Value |
| --- | --- |
| Contrasts per recipe | 1 to 32 |
| Name | not empty, at most 120 characters, unique |
| Weights per contrast | 2 to 256, each a different cell, coefficient finite and not 0 |
| Cells of the model factors averaged over | at most 4096 |
| Sum of coefficients | \|Σ c\| ≤ 1e-12 × Σ \|c\| |
| Contrast zero by construction | max \|L\| ≤ 1e-9 × Σ \|c\| (status `No inference`) |
| Estimability | component of L outside the row space of X ≤ 1e-8 × ‖L‖ |

**Statuses.**

* `OK`: estimate, SE, t, p, adjusted p and interval are filled. An estimate that is exactly 0 with a positive SE is `OK` with t = 0 and p = 1.
* `No inference`: the contrast is zero by construction in this model, for example an interaction contrast in an additive model (Selected terms without the interaction). The estimate is 0 and the other cells are empty.
* `Not estimable`: L is not in the row space of the design. Trama refuses rank-deficient ANOVA fits before this point, so with the current engine this status does not occur; it is kept so that a future change cannot report a meaningless number.

Neither status takes part in the correction.

## Errors

Every error names the field (`Planned contrast factors`, `Planned contrasts`, `Planned contrast correction` or `Planned contrast alpha`), and for `Planned contrasts` the contrast and weight row. Examples, English and Italian:

* *“Difference of differences”: the coefficients add up to -0.5. They must add up to 0.* / *“Difference of differences”: i coefficienti sommano a -0,5. Devono sommare a 0.*
* *“Visit trend”, weight 3: “Visit” has no level “D” in the rows used by the model.*
* *Two different categories of “Dose” read as the same text, “1”. Make the categories distinct before using planned contrasts.* (for example the number 1 and the text "1" in the same column)

## Not covered

* Windows with real fonts and DPI has not been tested by this change; the screenshots are from Linux offscreen at 1024×768 and 1600×1000 with emulated DPI 96.
* Simultaneous (Scheffé or max-t) intervals are not offered: intervals are pointwise, and the correction acts on p values only.
* Contrasts on repeated-measures ANOVA, ANCOVA and nested ANOVA are out of scope.
