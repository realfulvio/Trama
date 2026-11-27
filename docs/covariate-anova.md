# Covariates in Multifactor ANOVA

**Multifactor ANOVA** can adjust the response for one or more numeric covariates. The one-factor ANCOVA command is unchanged. A recipe that does not name **Covariates** is fitted exactly as before, including a project saved before this option.

The model is ordinary least squares with independent observations. Factors keep the sum-to-zero coding. The interaction is the one already chosen for the factorial model (full hierarchy of the selected order, or the selected terms). Each covariate is an additive column, centred on its reference: the value minus the reference. There is no covariate-by-factor interaction, no repeated measures, no weights and no imputation in this release. While covariates are included, the sums of squares are Type III. Type I and Type II stay unavailable and the dialog says so.

The rows of the fit are the rows complete for the response, the factors in the model and every covariate. An excluded cell is missing, so that row is left out of every term together. The same fit supplies the ANOVA table, the effect sizes, the diagnostics, the planned contrasts, the comparisons and the estimated marginal means.

**Covariate references** stores an explicit number for a covariate. A covariate without one is centred on the mean of the rows used by the fit. Adjusted means and comparisons hold every covariate at its reference. A reference outside the observed range is an extrapolation. A reference outside the range inside a cell is reported on **Covariate references**. With two or more covariates those separate ranges do not establish that the references lie in the joint support.

Coefficients, standard errors and 95% t intervals use the residual degrees of freedom of this fit. A constant covariate, a covariate that repeats another, an empty cell of the model factors, or a model without full rank or without residual degrees of freedom is refused before a table is published. The calculation runs on the worker. Cancelling it keeps the previous recipe.
