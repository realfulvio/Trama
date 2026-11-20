# Bland–Altman for repeated pairs

Choose **Analyze → Group Comparison → Bland–Altman for repeated pairs** (IT: *Bland–Altman per coppie ripetute*) when two methods measure the **same subject more than once**, for example two glucose meters used on each patient at several visits. Each worksheet row holds one pair already matched by you: First and Second measured together on one subject at one occasion. Trama never pairs values from different rows.

The classic **Bland–Altman** analysis treats every row as an independent subject. Its menu entry, options, sheets and saved recipes are unchanged.

## What is estimated

The analysis uses the random-intercept model of the differences that Bland and Altman (2007) describe for a quantity that may vary between occasions:

    d = First − Second (or log First − log Second) = bias + subject effect + within-subject error

| Quantity | Formula (subject *s* has *m*ₛ pairs, mean difference *d̄*ₛ; *N* pairs, *g* subjects) |
|---|---|
| Bias | Σ *m*ₛ *d̄*ₛ / *N*, the mean of all pairs |
| MS within | Σ squared deviations from *d̄*ₛ / (*N* − *g*) |
| MS between | Σ *m*ₛ (*d̄*ₛ − bias)² / (*g* − 1) |
| *m*₀ | (*N*² − Σ *m*ₛ²) / ((*g* − 1) *N*) |
| Within-subject variance | MS within |
| Between-subject variance | max(0, (MS between − MS within) / *m*₀); the raw value is kept in *Between-subject variance (unconstrained)*, and *Between-subject estimate* says **At boundary (set to 0)** when it was negative |
| Limits of agreement | bias ± *z* · √(within + between), *z* = Φ⁻¹((1 + coverage/100)/2) |

The limits describe where the difference of **one new pair on one new subject** is expected to fall. They are not confidence intervals.

**Log ratio** works on log First − log Second. Bias and limits are reported as ratios First / Second (exp of the log values, also listed as *Bias (log)*, *Lower limit (log)*, *Upper limit (log)*); the variance components stay on the log scale. A ratio that would overflow or underflow is left empty with a note, never replaced by a large finite number.

## Fields

| Field | Meaning |
|---|---|
| Subject | Required. Names are literal: `P1` and `P1 ` are different subjects, and text `1` differs from the number 1. |
| Occasion | Optional. Copied to the Pairs sheet. Two used pairs with the same Subject and Occasion are refused on this field (the message names both rows). Pairs with a blank occasion are never compared. |
| First, Second | Numeric, two different columns. Text, infinite values and magnitudes beyond 1e100 are refused on the field with the row number. Log ratio refuses zero and negative values the same way. |
| Mode | **Difference** (default) or **Log ratio**. |
| Coverage | Percentage strictly between 0 and 100, default 95. |
| Confidence intervals | **None** (default) or **Subject bootstrap**. |
| Confidence level (%), Bootstrap replicates, Seed | Shown and saved only with Subject bootstrap. Level between 0 and 100; replicates from 199 to 20,000; seed from 0 to 4,294,967,295. |
| Graph | **Pairs** (default) or **Subject diagnostics**. |

At least three subjects with complete pairs and at least one subject with two complete pairs are needed. Subjects with a single pair are allowed: they contribute to the bias and to the between-subject part.

## Blank and excluded cells

An excluded cell reaches the analysis as an empty cell. A row with an empty Subject, First or Second is not used; it is listed in the **Excluded rows** sheet with its source row (counted from 1), subject, occasion and reason (`First is blank or excluded`, …). Completely empty rows are ignored. The sheet appears only when at least one row is excluded, and *Excluded rows* in the Agreement sheet counts them.

## Sheets

- **Agreement**: one row with bias, the two variance components, the limits and every intermediate value (MS within and between, degrees of freedom, *m*₀, *z*), interval columns and a Note.
- **Subjects**: one row per subject in order of first use: pairs, first source row, mean difference (or mean log ratio and its ratio), within-subject SD (empty with one pair) and mean of the pair averages.
- **Pairs**: one row per used pair in worksheet order with *Source row*, subject, occasion, First, Second, abscissa and difference (or log ratio and ratio).

## Subject bootstrap

The *g* subjects (in order of first use) are drawn with replacement with `Generator(PCG64(seed))`, one vector `integers(0, g, size=g)` per replicate, replicate after replicate. Every draw is a new subject carrying all of its pairs. The estimator runs on the per-subject summaries of the drawn subjects, so no row is copied (an independent test recomputes replicates by copying the rows). A replicate in which every drawn subject has one pair cannot estimate the within-subject variance: it is counted as invalid, listed in *Invalid replicates* (first 20 numbers) and left out. The percentile intervals use the linear quantile rule on the valid replicates. With fewer than 90 % valid replicates the intervals stay empty and the Note says why; the estimates are still reported.

The replicates are split into blocks that start from the exact generator state of their first replicate, so the result is identical with one process or with the shared multicore pool (**Settings → Processes**). The calculation can be cancelled: the last confirmed result and recipe are kept.

## Graphs

- **Pairs**: each pair at the mean of First and Second (geometric mean in Log ratio) against the difference (ratio, on a ratio axis); bias, two limits, zero (or one) line and, with the bootstrap, shaded intervals of the bias and of each limit. The title gives the number of pairs and subjects.
- **Subject diagnostics**: the within-subject SD of each subject with two or more pairs against its mean magnitude, the marker growing with its pairs and labelled with their number, and the pooled within-subject SD. Subjects with one pair are counted in the legend.

Every element is an ordinary editable graph object (Inspector, Format Graph, export to PNG, SVG, PDF and TIFF).

## Reading the result, and limits of the model

- The model assumes that the bias is constant across the range, that subject effects and within-subject errors are independent and roughly normal, and that the within-subject variance is the same for every subject.
- If the Pairs graph fans out, or the Subject diagnostics show the within-subject SD growing with the magnitude, the spread depends on the size of the measurement: try **Log ratio**, which turns a proportional error into a constant one, or report the limits for limited ranges.
- A trend of the differences with the magnitude means the bias is not constant; the limits then mix different biases.
- The bootstrap intervals describe the uncertainty of bias and limits with few subjects; they do not widen the limits themselves.
- The width of the limits alone never shows that two methods are interchangeable. Compare the limits with a clinically acceptable difference chosen before looking at the data.

## Reference

Bland JM, Altman DG. Agreement between methods of measurement with multiple observations per individual. *J Biopharm Stat* 2007;17:571–582. [doi:10.1080/10543400701329422](https://doi.org/10.1080/10543400701329422) (section on a quantity that may vary).

## Example

`docs/examples/Bland-Altman-ripetute.alab` holds the synthetic table `glicemia ripetuta` (column names with spaces and symbols, one incomplete pair, one subject with a single pair) and the analysis with a 999-replicate subject bootstrap.
