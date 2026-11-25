# Two-way ANOVA from summaries

Use **Group Comparison → Two-way ANOVA from summaries** (*ANOVA a due fattori da riepiloghi*) when the original observations are unavailable but every cell of two fixed, crossed factors has a mean, a sample SD or SEM, and its sample size. This is an ordinary full model, A × B with interaction. Existing analyses of raw observations, including **Grouped two-way ANOVA**, are unchanged.

Two arrangements are supported. The dialog opens on the one that matches the sheet.

* **Summary subcolumns:** a Grouped sheet whose column groups already use the headers `[Mean]`, `[SD]` or `[SEM]`, and `[N]`. Choose the row-factor column (for the bundled sheet, `Row title`) and tick the summary subcolumns. An empty Variables list means every matching subcolumn. Entirely blank rows among the chosen columns are skipped. The results show the original worksheet row numbers.
* **Groups in rows:** one row per cell. Map the two factor columns and the Mean, Dispersion and Sample size columns. A long CSV is mapped in place; it is not pivoted onto a Grouped sheet.

Choose SD or SEM. If the choice is left unset, it is inferred only when every selected group has exactly one of those two roles. CV is not accepted. SEM is converted with SD = SEM × √N before the residual is formed. N must be an integer from 2 to 2^53. The mean and the dispersion must be finite, and the dispersion cannot be negative. The grid must be complete, with at least two levels of each factor, distinct factor names and each combination once. A partial or excluded cell is a field error on that cell; it is not dropped. Levels stay in first-seen order and the text is kept as typed, including a name such as `Dose $`.

The engine uses the sufficient statistics directly: the cell mean, N, and the within-cell sum of squares (N − 1) × SD². It does not manufacture replicates, and it does not call the grouped-ANOVA expander. Hypothesis sums of squares are Type III contrasts of the cell means, with weights equal to N. Main effects compare equal-weight marginal means. The interaction is the difference of those differences. The residual sum of squares is the sum of the within-cell sums of squares, on the sum of (N − 1) degrees of freedom. One cell may have SD 0. The pooled residual variance must be positive. The cost follows the number of cells, not N.

The result has three sheets, with the same English headings in both languages:

* **ANOVA (type III):** SS, df, MS, F and p for the row factor, the column factor and their interaction, then Residual and Corrected total. Residual has SS, df and MS. Corrected total has SS and df.
* **Summaries used:** the factor levels, Mean, SD, SEM, N and the 1-based source row.
* **Settings:** the model, the Type III choice, the input arrangement, the dispersion, the factor names, the cell count, total N and residual df. It states that equal-weight marginal means are estimates of the sum-to-zero contrasts, and that this table is not the estimated-marginal-means sheet. When the cell sizes differ, it also states that the Type III sums of squares do not add up to the corrected total. When they are equal, those sums and the residual do add up to the corrected total.

On the balanced synthetic grid (means 2, 6, 4 and 12 for A0/B0, A0/B1, A1/B0 and A1/B1, each with SD 1 and N 3) the F ratios are 48, 108 and 12, and the residual sum of squares is 8. The same ANOVA is obtained from SEM = SD / √N. Changing the A1/B1 mean from 12 to 14 gives F ratios 75, 147 and 27, with the residual sum of squares still 8. The unbalanced grid adds the level `Dose $`; its B1 cell has SD 0 and N 6, and the Type III sums of squares do not add up to the corrected total.

Repeated measures, a missing cell, zero pooled residual variance, sums of squares other than Type III, a model without the interaction, and diagnostics or comparisons that need the observations are refused. Recipes survive save and reopen. Editing a cell recalculates the sheets; Undo and Redo restore the previous values. A locked sheet can still be analyzed and cannot be edited.

The checks for this command, including the saved project and the screenshots, are in [Two-way summary ANOVA checks](validation-summary-twoway.md).
