# Compare independent ROC curves

Choose **Analyze → Group Comparison → Compare independent ROC curves** to compare the area under the ROC curve of two markers when the two markers were measured on **different people**. The method needs four columns: the controls and the patients of marker A, and the controls and the patients of marker B. No person appears twice, and no row links a value of A to a value of B.

To compare two markers measured on the **same** people use **Compare paired ROC curves** (DeLong for correlated curves). It is unchanged. The single-marker **ROC curve** analysis is unchanged too.

## Fields

| Field | Meaning |
|---|---|
| Control A, Patient A, Control B, Patient B | Four distinct numeric columns. Blank and excluded cells shrink only their own column; the columns need not have the same length. Each needs at least 2 valid values, and the four together at most 100,000. |
| Direction A, Direction B | **Higher in patients** (default) or **Lower in patients**, one per marker. With Lower, the scores of that marker are negated while the curve is built, so a larger score always points to a patient. Thresholds are reported on the original scale. |
| Area | **Full** (default), **Partial** or **Standardized partial**. |
| Maximum FPR | Cutoff *q* of the partial areas, a number with 0 < *q* < 1. Shown only for Partial and Standardized partial; not validated and not saved for Full. |
| Inference | **DeLong** (default for the full area) or **Percentile bootstrap**. A partial area has no DeLong variance: choosing a partial area proposes the percentile bootstrap, and DeLong with a partial area is refused on the Inference field. |
| Confidence level (%) | Greater than 0 and less than 100; default 95. |
| Bootstrap replicates, Bootstrap seed, Save bootstrap | Bootstrap only. Replicates are a whole number from 200 to 10,000 (default 1,000), the seed a whole number from 0 to 4,294,967,295 (default 0), Save bootstrap adds the sheet of replicates (default off). |

Numbers accept a decimal comma. Recipes keep the English field names and values whatever language the interface shows.

## How it is computed

**ROC curve.** The empirical curve of each marker is a polygon: the points are the distinct oriented scores, high to low, starting at (0, 0). Every observation with the same value enters the same step, so ties draw a diagonal segment.

**Full area.** The polygon's area equals the Mann–Whitney probability that a patient scores above a control, with half credit for ties.

**DeLong variance of independent cohorts.** For each marker, V = var(placement of the patients) / m + var(placement of the controls) / n, with the sample variance (n − 1), where m patients and n controls enter the marker's curve. A placement is the share of the opposite group that a person beats, counting a tie as one half. Because the four samples are independent, the variance of the difference is V(A) + V(B). Then Z = (AUC A − AUC B) / SE, p = 2·P(|N| ≥ |Z|) and the interval is the normal interval of the difference, clipped to [−1, 1]. With SE = 0, Z, p and the interval stay empty and Status reads **Zero variance**.

**Partial area.** The polygon is integrated over 0 ≤ FPR ≤ *q* by trapezoids. If *q* cuts a segment, the segment is cut by linear interpolation. Vertical steps have area zero.

**Standardized partial area.** The raw partial area *a* becomes 0.5 · (1 + (*a* − *C*) / (*P* − *C*)), where *C* = *q*²/2 is the area under the diagonal and *P* = *q* is the area of a perfect curve. A curve under the diagonal gives a value below 0.5, and Trama keeps it. The difference is taken on the scale you chose; the raw areas stay in the table.

**Percentile bootstrap.** One generator seeded with the bootstrap seed (NumPy PCG64) draws, replicate after replicate, in the order Control A, Patient A, Control B, Patient B: for each sample, as many indices as it has values, with replacement, from the sorted oriented values. The areas of a replicate are computed from per-value counts, never from a patient × control matrix. The interval is the linear-quantile interval at α/2 and 1 − α/2 of the differences of the replicates, with α = 1 − level; the variance is the sample variance (B − 1). The bootstrap is stratified by sample, so the four sample sizes never change. Z and p are not defined for it. The first B replicates do not depend on the number requested nor on the order of the worksheet rows. If every replicate gives the same difference, Status reads **Constant bootstrap distribution** and the note says that the interval is a single point.

**Limits.** At most 100,000 observations in total. For the bootstrap, replicates × observations must not exceed 5,000,000, and this is checked before anything is drawn (so 1,000 replicates allow 5,000 observations and 200 replicates 25,000). The bootstrap can be stopped with **Cancel calculation**; a cancelled new analysis adds nothing and a cancelled update leaves the previous result.

## Results

* **ROC comparison** (one row): Area A and Area B on the chosen scale, Raw area A and B, Difference (A − B), Variance of difference, SE, Lower and Upper, Z, p, Status, the four counts, both directions, Area type, Maximum FPR, Inference, Confidence level, Bootstrap replicates and seed, and a Note that states the method.
* **ROC curve A**, **ROC curve B**: Threshold (on the original scale; empty at the origin), False positive rate, True positive rate.
* **ROC bootstrap** (only when Save bootstrap is on): Replicate, Area A, Area B, Difference.

The figure draws both curves, the chance diagonal and, for partial areas, a shaded band and a dotted line at the Maximum FPR. The Inspector and **Format Graph** work as on other graphs; title, legend and axis styling survive every recalculation.

## Editing the worksheet

Editing a cell or excluding one recalculates the analysis. If a sample is left with fewer than 2 valid values, or the bootstrap budget is exceeded, the last valid result stays, the status says why and the dialog reopens on the field to correct.

## Not included

Paired or clustered data (use the paired comparison), tests of equivalence or non-inferiority of AUCs, bootstrap of paired curves, covariate-adjusted ROC, partial areas defined on the TPR axis, and any choice of cutoff by the program. A cutoff on the FPR is a scientific choice that you declare.

## References

* E. R. DeLong, D. M. DeLong, D. L. Clarke-Pearson (1988), Comparing the areas under two or more correlated receiver operating characteristic curves, *Biometrics* 44, 837–845.
* D. K. McClish (1989), Analyzing a portion of the ROC curve, *Medical Decision Making* 9, 190–195.
* B. Efron, R. J. Tibshirani (1993), *An Introduction to the Bootstrap*, Chapman & Hall.
