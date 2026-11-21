# Precision–recall curve

In the Vetro interface, choose **Analyze → Group Comparison → Precision–recall curve** (IT: *Curva precisione–richiamo*) when you already have the scores of one or two instruments on the same samples and the event is rare. The scores come from outside Trama: a lab assay, a classifier you ran elsewhere, a risk score. For the out-of-fold probabilities of a logistic model fitted in Trama, use **Validate binary logistic model**, which reports the same average precision.

## Fields

| Field | Meaning |
|---|---|
| Outcome | The column that says which samples are positive. |
| Positive, Negative | The exact labels of the two classes, typed by you (there is no guessing). Labels are compared literally: `01` is not `1`, `Case` is not `case`, a trailing space counts. A number in the worksheet matches its usual text (`1` for 1 and 1.0). |
| Score | Numeric column with the first instrument. |
| Second score | Optional second instrument on the same samples. |
| Direction, Second direction | **Higher is positive** (default) or **Lower is positive** for each score (the second one is shown only with a second score). |
| Bootstrap CI | Optional percentile bootstrap, also with a single score. |
| Confidence level (%), Bootstrap replicates, Bootstrap seed | Shown and saved only with Bootstrap CI. Level strictly between 0 and 100; replicates from 199 to 10,000; seed from 0 to 18,446,744,073,709,551,615. |

While you choose the columns the dialog shows how many samples the curves will share, how many are positive and the prevalence, or why they cannot be counted yet. A label in **Outcome** that is neither Positive nor Negative is refused on the Outcome field, naming the first row where it appears. A score that is not a finite number (text, ±infinity) is refused on its field with the row number. A single class among the complete rows is refused on Outcome.

## Rows used

A sample is used when its outcome and **every chosen score** are filled. A blank or excluded cell leaves the whole row out of every curve, so two scores are always compared on the same rows. Completely empty rows are ignored; the other omitted rows are listed in **Excluded rows** with their physical row (counted from 1), the outcome and the reason. The sheet appears only when at least one row is left out, and *Excluded rows* in Settings counts them.

## What is calculated

Every distinct observed score is a threshold; scores that tie are counted together. With *Higher is positive* a sample is predicted positive when score ≥ threshold, with *Lower is positive* when score ≤ threshold. For each threshold:

    TP, FP, TN, FN        counts of the 2×2 table
    Precision = TP / (TP + FP)
    Recall    = TP / P    (P = number of positives)

**Average precision** is the sum, from the strictest threshold to the loosest, of (Recall − previous Recall) × Precision at the new level, with Recall 0 before the first threshold. There is no interpolation. It is the definition of scikit-learn's [`average_precision_score`](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.average_precision_score.html), and Trama uses the same functions for the thresholds and for the AP as the logistic validation, so the two analyses agree on the same scores. The **prevalence** of the sample (positives / common samples) is the reference line: a score that carries no information (constant, or tied everywhere) has AP equal to the prevalence.

The drawn curve is a staircase that starts at the conventional point (recall 0, precision 1) and holds the precision of each threshold over the recall it adds, so the area under it is exactly the average precision. The start point is not a threshold and is not in the sheets.

## Sheets

- **Summary**: one row per score, in the order Score, Second score: *N*, *Positives*, *Prevalence*, *Average precision*, *ROC AUC*, *Direction* and, with the bootstrap, *AP lower* and *AP upper*.
- **Thresholds: NAME**: one sheet per score (NAME is the column name) with *Threshold* on the original scale, *TP*, *FP*, *TN*, *FN*, *Precision*, *Recall*, from the strictest threshold down.
- **Comparison** (two scores): *AP first*, *AP second* and *AP difference* = second − first, with *Difference lower* and *Difference upper* when the bootstrap is on.
- **Settings**: the columns, labels, directions, counts, the AP definition and, with the bootstrap, level, replicates, seed, the random sequence and the quantile rule.
- **Excluded rows**: see above.

## Paired bootstrap

The percentile bootstrap **stratifies by outcome**: each replicate draws, with replacement, as many positive samples and as many negative samples as the data holds, and applies **the same drawn samples to both scores**, so the interval of the difference keeps the pairing. `Generator(PCG64(seed))` draws, replicate after replicate, `integers(0, P, size=P)` over the positives and then `integers(0, N − P, size=N − P)` over the negatives. Inside each class the samples are first put in a canonical order (by the first score, then the second), so the replicates, and therefore the intervals, do **not** depend on the order of the worksheet rows. The interval uses the linear percentiles *α*/2 and 1 − *α*/2, with *α* = 1 − level/100, for each AP and for the difference. Two identical scores give a difference of exactly zero in every replicate.

**Budget:** replicates × common samples must not exceed **20,000,000** drawn positions (for example 10,000 replicates on 2,000 samples, or 199 on 100,000). It is checked before anything is drawn and the message names the field. The calculation runs on the Qt worker, can be cancelled with **Cancel calculation** (the last confirmed result and recipe are kept) and gives the same numbers on every run with the same seed. The figure never carries bands for the intervals: they are in the sheets and in the legend.

## AP, prevalence and ROC AUC

- **ROC AUC** is the probability that a random positive scores above a random negative, plus half the probability of a tie. It does not depend on how rare the positives are.
- **Average precision** averages the precision over the recall levels. It depends on the **prevalence of the sample** and on **which class you call positive**: the same instrument has a much lower AP when positives are rarer, and swapping the classes gives another curve.
- Illustration (400,000 simulated samples per row, normal scores 1.5 SD apart; seed 1):

  | Prevalence | ROC AUC | Average precision |
  |---|---|---|
  | 0.50 | 0.856 | 0.854 |
  | 0.10 | 0.857 | 0.480 |
  | 0.01 | 0.853 | 0.122 |

- Compare the AP with the prevalence of **that** sample, not with 0.5: the line drawn in the figure is the AP of a useless score. Two instruments are comparable only on the same samples (this analysis forces it); AP values from samples with different prevalences are not.
- With few positives the AP is unstable; the bootstrap interval shows by how much. A wide interval of the difference means the sample cannot tell the two instruments apart.

## Example

`docs/examples/Precisione-Richiamo.alab` holds the synthetic table `strumenti` (two instruments on 60 samples, 9 positives with the labels `Positivo` and `Negativo`, column names with spaces and symbols, one row without the second score and one without outcome) and the analysis with a 999-replicate bootstrap.
