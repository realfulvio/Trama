# Partial correlation

**Partial correlation** estimates the association between numeric variables after accounting for one or more numeric covariates. **Correlation**, **Correlation matrix**, **Repeated-measures correlation** and **Compare independent correlations** keep their own recipes.

Choose 2 to 12 variables and 1 to 8 covariates. A column cannot take both roles. The fit uses only the rows that are complete on every selected column. An excluded cell counts the row as excluded; a row that is not excluded and is missing a selected value counts as incomplete. Every pair uses that same set of rows. The result reports N, the excluded rows and the incomplete rows.

Pearson correlates the residuals of each variable from a fit on the covariates, with an intercept. Spearman ranks the selected columns on those rows first, with average ranks for ties, and then uses the same residuals. One decomposition of the covariate design is reused for every variable. The calculation does not invert a correlation matrix.

The coefficient r and its two-sided p value use a t statistic on N − k − 2 degrees of freedom, where k is the number of covariates. The Spearman p value is approximate. For Pearson, the Fisher interval uses standard error 1/√(N − k − 3). The interval is left empty when that denominator is not positive, and also when |r| is exactly 1. In that last case, and when the degrees of freedom are positive, p is 0. If N − k − 2 is not positive, or the covariates do not have full rank, the fit stops and no table is published. A variable whose residual variance is zero makes only the pairs that include it non-estimable: those coefficients and p values stay empty, and the row says why.

The result has the coefficient matrix, one row per pair, and a heat map on the fixed scale −1…1. The pair table names the variables, the method, N, the covariates, r, the degrees of freedom, p and the interval when there is one. **Holm adjustment** corrects the estimable pairs only and keeps the raw p value. With exactly two variables, **Residual scatter** adds the two residuals to the figure and keeps the worksheet row of each point.

Formulas, filters and exclusions stay in the saved recipe and are used again on recalculation. The fit runs on the worker. Cancelling it keeps the previous recipe.
