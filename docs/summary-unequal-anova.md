# Unequal-variance ANOVA from summaries

**Group Comparison → One-way ANOVA from summaries** accepts three Method
values: `Ordinary` (the default), `Welch`, and `Welch and Brown–Forsythe`.
The dash in the joint name is an en dash (U+2013). Canonical values stored in
a project stay English. The Italian interface shows Ordinaria, Welch, and
Welch e Brown–Forsythe.

This note belongs to branch `grok/summary-unequal-anova`, cut from
`d88764d8f7ea5e97723adfa64d0e3f390ed39b3c`. VERSION stays `0.72.0` and
RELEASE_CHANNEL stays `beta`. It is not a release. Windows was not run.

`Ordinary`, and a saved recipe with no Method key, keep the sheets, column
order, numbers, and figure of the ordinary summary ANOVA. That path is
described in [One-way ANOVA from summaries](summary-anova.md). The one-way
ANOVA on observations, lognormal ANOVA, mixed models, and
`inference.one_way_anova` are not changed. The median-centered Brown–Forsythe
homogeneity test is a different procedure and stays where it is.

## Calculation

The engine uses the means, SDs, and sample sizes already accepted by the
ordinary summary ANOVA. It does not manufacture observations and it does not
allocate storage proportional to N. Groups in rows and Summary subcolumns,
SD / SEM / CV (%), integer N from 2 through 2^53, total N at most 2^53, and
2–30 complete groups are the same rules. Parsing, provenance, and exclusions
are reused. A group already omitted because another cell is missing is not
checked for a zero SD.

Welch and Brown–Forsythe require a strictly positive SD in every group they
use. A zero SD raises `FieldError` on Dispersion, or on Variables for
subcolumns: “Every group used by Welch ANOVA needs a positive SD.” Negative
and non-finite values are already rejected by the shared summary checks.
Ordinary ANOVA still allows an individual zero SD when the pooled variance
is positive.

Means are centered and then scaled by the largest absolute centered mean or
SD before squares and weights. Multiplying every mean and SD by 1e−120 or
1e120 does not change F, degrees of freedom, or p. A positive SD that the
scale would turn into zero raises an explained field error. There is no
epsilon substituted for a variance, and there is no silent NaN or replaced p.
Descriptive numbers that cannot be written back in the original units are
left blank, with a Settings note. Inference that was computed in scaled units
is kept.

Welch weights are `w_i = n_i / s_i²`. The Welch correction term is always
included, including when the sample sizes are equal. For the weighted mean,
precisions are divided by their largest value before summation, so a finite
set of precisions cannot overflow the normalizing total. Pairwise
Welch–Satterthwaite degrees of freedom similarly use relative variances
before squaring, avoiding underflow at extreme scales. Equal sample sizes do
not make Welch F identical to the ordinary F. For two groups the (k−2) term
is zero, so Welch F equals the square of the two-sample Welch t. Degrees of
freedom are `df1 = k−1` and `df2 = (k²−1) / (3B)`.

Brown–Forsythe here is the original F* test of equality of means:

`F* = Σ n_i (m_i − m_g)² / Σ c_i`, with `c_i = (1 − n_i/N) s_i²` and
`df2 = D² / Σ (c_i² / (n_i−1))`. df1 stays k−1. The Mehrotra correction is
not applied. The implementation calls the existing pure `brown_forsythe` on
the scaled sufficient statistics.

## Sheets and graph

Welch writes one ANOVA row, Term = `Welch`. The joint method adds a second
row, Term = `Brown–Forsythe`. Columns are Term, F, F df1, F df2, and p.
Sums of squares and mean squares are not presented as a decomposition.

Summaries used keeps Source row, Group, Mean, SD, and N, and adds Mean SE,
Mean CI lower, and Mean CI upper. The standard error is `s_i / √n_i`. The
interval is the Student t interval on `n_i−1` degrees of freedom at the
chosen confidence level. These are not labeled as pooled mean intervals.
The ordinary path still uses Pooled mean CI lower and Pooled mean CI upper.

The figure is the group means with those pointwise intervals, in the original
group order. The legend contains “pointwise”. It does not claim a pooled
residual variance. Changing the confidence level changes the intervals and
does not change the omnibus F or p. Format Graph, Inspector, and CSV, SVG,
PNG, and PDF export stay available. A descriptive value that cannot be drawn
in the original units is not replaced by an invented finite error bar.

## Comparisons

All pairs, in the original group order, i < j. Provenance rows stay 1-based
on the source sheet after omissions.

Ordinary post-hoc values stay None, Tukey (labeled Tukey–Kramer), Holm, and
Bonferroni. Welch and the joint method offer None, Games–Howell, Tamhane T2,
Holm, and Bonferroni. Tukey on Welch or on the joint method raises
`FieldError` on Post-hoc. Games–Howell or Tamhane T2 on Ordinary does the
same. The dialog does not switch the user’s choice to a compatible method.

Games–Howell uses the studentized range at the chosen level, with a
pair-specific standard error and Welch–Satterthwaite degrees of freedom.
Tamhane T2 uses the Dunn–Šidák adjustment of the Welch two-sided p over the
`k(k−1)/2` family, and a t critical value at that pair alpha. Both write
CI lower, CI upper, and Confidence level (%). Holm and Bonferroni adjust the
Welch raw p values over the whole family and do not add interval columns.
Significant means adjusted p is strictly below `1 − level/100`. There is no
selected-comparison list, no control group, and no Dunnett T3.

## Dialog and project

Method and Post-hoc are in the existing summary ANOVA dialog. Options sit in
a scrollable area. Run Analysis and Cancel stay outside that area. At
1024×768 and at 1600×1000 those buttons measured 123×27 and 112×27. UI A
fonts were not reduced. A short note states that the summaries are treated as
independent groups and cannot reconstruct paired dependence, normality,
residuals, or the distribution of the data. The Italian note is the same
sentence. Decimal commas use the common parser.

A field or budget error is reported before the worker, with focus on the
field and the dialog left open. An error discovered by the worker reopens the
dialog with the typed values. `SUMMARY_ANOVA` remains in weighting recovery.
A failed new recipe is not saved. Editing a source cell, excluding an SD,
Undo, reopening the `.alab`, and Use Result as Data were exercised on the
Welch and joint paths. A legacy recipe with no Method key still recalculates
as ordinary ANOVA.

## Checks on Linux

Xvfb and Tk scaling are not Windows and are not a real Windows DPI. Windows:
NON PROVATO.

Before any engine edit, the packet oracle was 6/6 and the packet verifier on
the base was 9/30, exit 1, matching the packet’s expected red list. After the
engine, the same verifier was 30/30, exit 0. The external contract unittest
(`test_candidate_contract.py` against this checkout) was 1 test, OK, exit 0,
in 4.747s. No numerical contradiction with the oracle was found, and the
verifier was not patched.

`tests.test_summary_anova`: 50 tests, OK, 8.255s. Dialog and catalog checks
that cover this method (`tests.test_summary_anova_dialog`,
`tests.test_interface_i18n`, `tests.test_catalog`, `tests.test_unequal_anova`,
`tests.test_summary_anova`): 10 tests in 1.248s and 68 tests in 10.206s, both
OK. Full `unittest discover` with a display: 2196 tests, OK, 165.442s, exit 0.

Targeted `TRAMASTAT_SMOKE_ONLY=summary-anova` with screenshots: PASS, exit 0,
at 1024×768 and at 1600×1000. The ordinary F = 12 case still runs first in
that smoke. Captures are under `docs/media/summary-unequal-anova/`. The graph
legend reads “Mean and 95% pointwise CI” on the Welch result and “Mean and
90.5% pointwise CI” after Format Graph on the joint result at level 90.5.
The exported SVG contains “pointwise”; the PDF begins with `%PDF`.

The complete `tramastat.py --smoke` with screenshots, on Xvfb at 1920×1080,
finished PASS, exit 0, in 671 s. `status.txt` is PASS. The summary ANOVA
section of that run recorded screen `[1920, 1080]` and the same checks,
including Welch and Brown–Forsythe, the incompatible post-hoc, pointwise
error bars, Inspector, and the legacy ordinary recipe. The pre-existing PCA
screen-size assertion was not changed. `docs/media/summary-unequal-anova/full-smoke-status.txt`
and `checks-1920.json` are that result.

