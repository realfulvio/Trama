# One-way ANOVA from summaries

Use **Group Comparison → One-way ANOVA from summaries** when the original
observations are unavailable but each independent group has a mean, a measure
of dispersion and its sample size. This is an ordinary, equal-variance ANOVA.
Existing analyses of raw observations are unchanged. Welch ANOVA and the
original Brown–Forsythe F* on the same summaries are documented in
[Unequal-variance ANOVA from summaries](summary-unequal-anova.md). A missing
Method, and Method = Ordinary, stay on the path described here.

Two arrangements are supported:

* **Groups in rows:** select separate Mean, Dispersion and Sample size columns.
  A Group column is optional; otherwise the source row supplies a label.
* **Summary subcolumns:** select a single worksheet row, counted from 1, and
  each group's named `[Mean]`, `[SD]`/`[SEM]`/`[CV]`, and `[N]` subcolumns.
  The selected dispersion type determines which subcolumn is used. Extra
  named summary columns are retained but do not change that choice.

SD is the sample standard deviation. SEM is converted using SD = SEM × √N;
CV (%) uses SD = |Mean| × CV / 100 and is unavailable for a zero mean. N must
be an integer of at least 2. There must be 2–30 complete groups and total N
cannot exceed 2^53. A missing or excluded summary cell omits that group;
the **Omitted groups** sheet records its source row. Invalid nonmissing values
raise a field error. Groups are never pooled because their displayed labels
happen to coincide.

The engine uses the entered sufficient statistics directly. It does not
manufacture observations or allocate a vector with N elements. The within-group
sum of squares is Σ(N−1)SD²; between-group variation is calculated around the
sample-size-weighted grand mean. The F test uses k−1 and total N−k degrees of
freedom. Zero SD in an individual group is allowed, but positive pooled residual
variance is required. Internally scaled coordinates retain inference for very
small or large units; quantities not representable in displayed units are blank
and explained in Settings.

Optional all-pairs comparisons use **Tukey–Kramer**, **Holm**, or **Bonferroni**.
All share the omnibus residual variance. Differences are First minus Second;
Tukey provides simultaneous confidence intervals at the chosen confidence
level. Holm and Bonferroni provide adjusted two-sided p values, without claiming
simultaneous intervals. A comparison is significant when adjusted p is strictly
below 1 minus the confidence fraction.

The graph shows means and **pointwise** confidence intervals using pooled
variance. These are distinct from the simultaneous Tukey intervals. Result
sheets retain source rows and can be exported or used as data; recipes survive
save/reopen and recalculate after edits and exclusions. Dialog captions and
validation are available in English and Italian; result-table headings retain
the existing English convention.

Summary statistics do not preserve paired dependence, ranks, residuals or
distribution shape. This command therefore does not perform repeated-measures,
nonparametric, lognormal or normality analyses, or residual-based variance tests.
Those require the appropriate raw-data analysis.

