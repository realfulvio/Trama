# Intraclass correlation (ICC)

In Classica or Qt, choose **Analyze → Group Comparison → Intraclass correlation** (IT: *Correlazione intraclasse*) when several raters or instruments measure the **same subjects** on a continuous scale and you want to quantify how closely they agree. Each worksheet row is one subject. Each column you select under **Raters** is one rater, instrument or occasion. In Classica, hold Ctrl to add or remove a rater from the selection.

The ICC answers two different questions, and you choose which one:

- **Absolute agreement**: do the raters give the *same values*? A rater that reads 5 units higher than the others lowers the coefficient.
- **Consistency**: do the raters *rank and space the subjects alike*? A constant offset between raters does not matter.

## Choosing between ICC, Bland–Altman and kappa

| You have | Use |
|---|---|
| Continuous measurements, three or more raters, or you want one coefficient for reliability | **Intraclass correlation** (this page) |
| Continuous measurements by two methods and you want the size of the differences in measurement units (limits of agreement) | **Bland–Altman**, or *Bland–Altman for repeated pairs* when each subject is measured more than once |
| Categorical ratings (yes/no, grades) | Cohen's kappa for two raters (where available in your version) |

The ICC is not a substitute for the limits of agreement: a high ICC can coexist with differences that are too large for the purpose of the measurement. Compare the result with an acceptable difference chosen beforehand.

## What is estimated

The model is the balanced two-way layout with one observation per cell (McGraw and Wong 1996). With *n* subjects and *k* raters, the two-way ANOVA gives the mean squares MSo (subjects), MSr (raters) and MSe (residual). With D = MSo − MSe:

| Definition | Unit | Formula | McGraw–Wong form |
|---|---|---|---|
| Absolute agreement | Single measure | D / [MSo + (*k*−1) MSe + *k* (MSr − MSe) / *n*] | ICC(A,1) |
| Absolute agreement | Mean of raters | D / [MSo + (MSr − MSe) / *n*] | ICC(A,*k*) |
| Consistency | Single measure | D / [MSo + (*k*−1) MSe] | ICC(C,1) |
| Consistency | Mean of raters | D / MSo | ICC(C,*k*) |

**Single measure** is the reliability of one rater's reading; **Mean of raters** is the reliability of the average of all the raters you ticked. The default is *Absolute agreement, Single measure*.

The coefficient can be **negative**: the raters then disagree more than the subjects differ, and Trama reports the value as it is. A denominator of zero, or one that is not finite (for instance constant data, or consistency when every subject has the same mean), leaves **Estimate** empty and **Status** says why. For *Mean of raters* under *Absolute agreement* the denominator can be negative when the raters differ more than the subjects do; the coefficient is then outside −1 to 1 and the Note says so.

The ICC does not change when every value is shifted by a constant or multiplied by a common factor. Internally the data are shifted by their median and scaled by an exact power of two, so very large or very small measurements neither overflow nor underflow. Sums of squares are reported in the units of the data (and shown as 0 or empty, with a note, if they are outside the range of numbers the computer can hold).

## Fields

| Field | Meaning |
|---|---|
| Raters | Two or more numeric columns, up to 64. The **order in which you select them** is kept in the recipe and is the order of the profile graph and of the *Rater columns* setting. The estimate does not depend on the order. |
| Subject | Optional label column, shown in the Subjects and Excluded rows sheets. It has no effect on the calculation: the **physical row** is the identity of the subject, so repeated or blank labels are fine. |
| Definition | **Absolute agreement** (default) or **Consistency**. |
| Unit | **Single measure** (default) or **Mean of raters**. |
| Bootstrap CI | Off by default. Adds a percentile interval. |
| Confidence level (%), Bootstrap replicates, Seed | Shown and saved only with Bootstrap CI. Level strictly between 0 and 100 (default 95); replicates from 199 to 5,000 (default 2,000); seed from 0 to 18,446,744,073,709,551,615. |
| Profile graph | On by default. Draws one line per subject across the raters. |

The dialog shows a **Summary** under the column lists: complete subjects, incomplete rows left out, number of raters and the chosen definition and unit.

## Blank, excluded and invalid cells

At least three complete rows and two distinct rater columns are needed. A row with a blank or excluded cell in any rater column is **left out as a whole** and listed in the **Excluded rows** sheet with its source row (counted from 1), its subject label and the raters without a value. Completely empty rows are ignored. Text that is not a number, infinite values, boolean columns and magnitudes beyond 1e100 are refused on the Raters field with the row number. Negative measurements are valid. Numbers stored as text (`12,5`) are read.

## Sheets

- **ICC**: one row with Definition, Unit, **Estimate**, **N** (complete subjects), **Raters**, **Status** and, with the bootstrap, *CI low*, *CI high*, *Confidence level (%)* and *Interval status*.
- **ANOVA components**: Subjects, Raters and Residual with SS, df and MS.
- **Subjects**: one row per complete subject (all of them, whatever the graph shows): source row, label, mean, SD, minimum, maximum and range across the raters.
- **Settings**: model, McGraw–Wong form, counts, rater columns in order, bootstrap parameters and a Note.
- **Excluded rows**: only when something was left out.

## Subject bootstrap

Subjects (the complete rows, in sheet order) are drawn with replacement with `Generator(PCG64(seed))`, one `integers(0, n, size=n)` per replicate, replicate after replicate. Each drawn row carries its whole vector of ratings. The panel of raters is **fixed**: the interval describes the uncertainty from the sample of subjects, conditional on the observed raters, and says nothing about other raters. A replicate whose coefficient is undefined (for example all drawn rows identical) is invalid and left out. The percentile interval uses the linear quantile rule (`numpy.quantile`, method `linear`) on the valid replicates; with fewer than 80 % valid replicates the interval stays empty and the Note says why. The estimate does not depend on the bootstrap.

The work (replicates × rows × raters) may not exceed 20,000,000 resampled cells; it is checked before any sample is drawn. The replicates are split into blocks that start from the exact generator state of their first replicate, so the result is identical with one process or with the shared multicore pool (**Settings → Processes**). The calculation can be cancelled: the last confirmed result and recipe are kept.

## Profile graph

One line per subject across the raters in the order you ticked them, and a thick line with the mean of each rater over all subjects. With more than 60 subjects only 60 evenly spaced rows are drawn and the legend says so ("60 of N shown"); the sheets always include every row. Untick **Profile graph** to skip the figure. It is an ordinary editable graph (Inspector, Format Graph, export to PNG, SVG, PDF and TIFF).

## Reading the result

- Rough guides for reliability (for example below 0.5 poor, 0.5–0.75 moderate, 0.75–0.9 good, above 0.9 excellent) depend on the field; report the definition and unit with the number, because ICC(A,1) and ICC(C,k) of the same data can differ widely.
- A consistency ICC close to 1 together with a much lower absolute-agreement ICC means the raters rank the subjects alike but one reads systematically higher: look at the rater means in the profile graph.
- The ICC depends on the spread of the subjects: the same raters give a lower ICC in a homogeneous sample.
- The model assumes one observation per subject and rater and roughly equal variances; subjects are a random sample.

## Reference

McGraw KO, Wong SP. Forming inferences about some intraclass correlation coefficients. *Psychological Methods* 1996;1:30–46. [doi:10.1037/1082-989X.1.1.30](https://doi.org/10.1037/1082-989X.1.1.30)

## Example

`docs/examples/ICC-valutatori.alab` holds the synthetic table `valutatori` (12 subjects, three raters, column names with spaces and symbols, one subject with a missing rating) and the analysis with a 999-replicate subject bootstrap, with the raters ticked in the order C, A, B.
