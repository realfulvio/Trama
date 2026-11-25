# Multifactor ANOVA: estimated marginal means

An estimated marginal mean is the model's prediction for one combination of factor levels, or for the whole design, after the factors you leave out have been averaged with the same weight on every cell. With unbalanced data this is not the raw mean of the rows.

In Qt choose **Analyze → Multifactor ANOVA** (*Analisi → ANOVA multifattoriale*). On Options, tick **Estimated marginal means** (*Medie marginali stimate*). The recipe asks for one combination: the ticked factors, and optionally the overall mean. Run (*Esegui*) adds one sheet. Leaving the option off adds nothing, and a project saved before this option keeps the same sheets and the same numbers. The classic Tk dialog does not draw this option; it keeps the four keys of a recipe saved in Qt.

## The option

* **Factors** (*Fattori*): the factors whose levels name the rows. Tick them in the order you want the columns. Only factors that are in the model can be used (all of `Factors` in Full hierarchy, the factors of the chosen terms in Selected terms). Every other model factor is averaged over.
* **Include the overall mean** (*Includi la media complessiva*): one extra row, the equal-weight mean of every cell of the reference grid. It can be asked for on its own.
* **Confidence (%)** (*Confidenza (%)*): 95 by default. The dialog shows a percent (95, or 95,0 in Italian). The recipe stores the proportion 0.95. The intervals are two-sided t intervals on the residual degrees of freedom of this fit.

Names and levels are literal text: `A & B`, `B |` or `µ "x"` are kept exactly as typed, in every language. A factor that is no longer in the model stays in the list until you untick it, with the note *are no longer factors of the model* (*non sono più fattori del modello*).

The controls stay on the Options page. In a narrow window the captions wrap and the factor list scrolls; the confidence field stays beside its caption.

## Recipe

Four keys are added to the `Multifactor ANOVA` recipe. They are read only when `Estimated marginal means` is true. Values are canonical English in both languages. The confidence is a proportion, not a percent.

```json
{
  "Response": "Y",
  "Factors": ["A", "B"],
  "Interaction order": 2,
  "Estimated marginal means": true,
  "Marginal mean factors": ["A", "B"],
  "Include overall mean": true,
  "Marginal mean confidence": 0.95
}
```

A recipe without the switch, or with the switch false, ignores the other three keys and adds no sheet. The classic Tk dialog has no editor for this option; opening a recipe there and pressing OK copies the four keys back, so a project saved in Qt is not stripped.

## The sheet

The sheet is named **Estimated marginal means** in both languages, like the other ANOVA sheets, so a CSV export and `Use Result as Data` do not depend on the language.

| Mean | A | B | Estimate | SE | df | CI low | CI high | Confidence | Weighting | Status | Reason |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- |
| Combination | A0 | B0 | 2 | 1.5119 | 7 | −1.5750 | 5.5750 | 0.95 | Uniform weight on each reference-grid cell | OK | |

`Mean` is present only when the overall mean was requested. Its value is `Combination` or `Overall`. On an `Overall` row the factor cells are empty. `Weighting` is the same sentence on every row, including a row that cannot be estimated: *Uniform weight on each reference-grid cell*.

A factor whose name is already a column of the sheet (`Mean`, `Estimate`, `SE`, …) is written as `Estimate (factor)`, repeating the suffix if needed. The columns stay in the order the factors were ticked. Levels inside a factor follow the text order used by the fit.

## Worked example

Eleven observations, two factors, cell counts 2, 4, 3 and 2. The model is the saturated `Y ~ A * B` (interaction order 2). The mean square error is 4.571428571428571 on 7 residual df. The raw mean of the six A0 rows is 6. The equal-weight marginal mean of A0 is the average of the two cell means, (2 + 8) / 2 = 5.

| Request | Estimate | SE | 95% CI |
| --- | ---: | ---: | --- |
| A0, averaging B | 5 | 0.9258 | 2.8108 to 7.1892 |
| A1, averaging B | 8 | 0.9759 | 5.6924 to 10.3076 |
| B0, averaging A | 4 | 0.9759 | 1.6924 to 6.3076 |
| B1, averaging A | 9 | 0.9258 | 6.8108 to 11.1892 |
| Overall | 6.5 | 0.6726 | 4.9096 to 8.0904 |
| Cell A0 B0 | 2 | 1.5119 | −1.5750 to 5.5750 |

One recipe holds one of these requests (the cells are the request whose factors are A and B). The standard error of a margin is √(MSE / k² · Σ 1/n), with k the number of cells in the average, not the standard error of the raw mean.

A saturated model with a missing cell is still rank deficient, and Trama refuses that fit as it always has. An additive model (interaction order 1, or Selected terms with the two main effects) predicts the missing cell. The marginal mean of a level then includes that prediction, so it is not the mean of the observed cells alone.

## How it is computed

* **Same fit.** The means use the coefficients, the residual mean square and the residual df of the ANOVA fit already made, for any type of sums of squares. The model is not fitted again. Post hoc comparisons, when they are on, still use their own fit; adding the means does not add one.
* **Reference grid.** The grid is every combination of the levels in the complete rows of the fit. Each cell has the same weight, including a cell the additive model only predicts. The product of the level counts is limited to 4096, and that limit is checked before the fit.
* **Estimate and SE.** The row L is the equal-weight average of the design rows of the cells being averaged. The estimate is L·β and the variance is MSE × L (X′X)⁺ L′, from the same singular value decomposition the planned contrasts use.
* **Interval.** A two-sided t interval at the requested confidence, on the residual df. Sum-to-zero coding makes the scale of L equal to 1.

## Statuses

* `OK`: estimate, SE, df and both limits are filled.
* `No inference`: the mean is zero by construction. The estimate is 0 and the SE, df and limits are empty. The reason is *This mean is zero by construction, so there is no interval.*
* `Not estimable`: the mean is not a linear function of the fitted model. The numbers are empty and the reason is *This mean is not estimable from the fitted model.* Trama refuses a rank-deficient ANOVA fit before this point, so a successful fit does not produce this row. The status is kept so a singular design cannot be reported as a number. `Weighting` is still filled.

## Errors

Every error names its field. In the dialog the confidence is a percent: 0 and 100 are refused, and the cursor goes to that field. A recipe edited by hand stores a proportion, so 0, 1 and 95 are refused before the fit. A factor that is not in the model, a repeated factor, an empty request, a reference grid above 4096 cells, and two categories that read as the same text (the number 1 and the text "1") are refused the same way.

* *Enter a confidence percentage greater than 0 and less than 100.* / *Inserisci una percentuale di confidenza maggiore di 0 e minore di 100.* This is the sentence the dialog shows, because the field is a percent.
* *The confidence level must be a finite number greater than 0 and less than 1.* / *Il livello di confidenza deve essere un numero finito maggiore di 0 e minore di 1.* This is the sentence for a recipe that already stores a proportion outside (0, 1).
* *“C” is not a factor of the model, so estimated marginal means cannot use it.* / *“C” non è un fattore del modello, quindi le medie marginali stimate non possono usarlo.*
* *Estimated marginal means average over 4160 cells of the model factors. The limit is 4096.*

## Check

The Qt smoke ran on the real screen, not offscreen: Linux 7.3.5-2-cachyos, Wayland, screen eDP-1, available 1920×1080, device pixel ratio 1, logical DPI 96, PySide6 6.12.0. English and Italian each refused a confidence of 0 with the cursor in the percent field, then ran the unbalanced oracle (cells 2, 8, 6 and 10, overall 6.5). The project was saved and reopened, one response was edited, one row was excluded, and the sheet and its CSV matched a new fit of the masked worksheet. Screenshots, the CSV files and `report.txt` are in `docs/media/anova-marginal-means/`. The engine tests and the offscreen dialog tests passed in the same tree.

## Not covered

* Repeated-measures ANOVA, ANCOVA, nested ANOVA and mixed models. The fixed-effects multifactor ANOVA is the only analysis that gains this sheet.
* The classic Tk dialog does not edit the option. It keeps a recipe that Qt saved.
* Intervals are pointwise. There is no multiplicity adjustment on this sheet.
