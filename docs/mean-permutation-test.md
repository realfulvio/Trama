# Permutation test for mean difference

Choose **Group Comparison → Permutation test for mean difference** (Italian: *Confronto tra gruppi → Test di permutazione per la differenza tra medie*) to compare the means of two numeric columns without assuming a normal distribution. The question it answers is: **if the labels First and Second carried no information, how often would a difference of means at least this extreme appear?**

The estimate is always **mean(First) − mean(Second)**: First decides the direction of the test. The test gives a p value and the null distribution; it gives **no confidence interval**.

## Data and design

Two columns of the same worksheet, in the same units.

| Field (Italian) | Meaning |
|---|---|
| First (*Primo campione*) | The first sample. |
| Second (*Secondo campione*) | The second sample; it must be a different column. |
| Design (*Disegno*) | **Independent** (*Indipendenti*) or **Paired** (*Appaiati*). |

* **Independent.** Blank and excluded cells are dropped column by column, so the samples can have different sizes. Each sample needs at least 2 values, and the two together at most 50,000. The values of First and then of Second, each in worksheet order, form one pooled sequence of N = N₁ + N₂ positions.
* **Paired.** Only rows with both values are used: a row with a blank or excluded cell is omitted and counted. From 2 to 25,000 complete pairs. The test works on the differences First − Second of the complete rows, in worksheet order. *Permutation results* reports the number of pairs as both N first and N second.

Text, infinite values and integers beyond ±9,007,199,254,740,992 (2⁵³, where a double stops being exact) stop the analysis on the sample they belong to, with the source row counted from 1 as in the worksheet. A decimal comma is accepted in text cells.

### The assumption: exchangeability

A permutation test is exact only when, under the null hypothesis, the labels can be swapped without changing the joint distribution of the data.

* **Independent:** the two samples come from **the same distribution** (not only distributions with the same mean). Then every split of the pooled values into a group of N₁ and a group of N₂ is equally likely. With very different spreads or shapes and unequal sizes, a small p value may reflect the difference in spread rather than in means; a Welch t-test is then the safer comparison of means.
* **Paired:** within each pair the two labels are exchangeable, so each difference is equally likely to be positive or negative (a symmetric distribution of the differences around zero). A zero difference counts in both sign configurations.

Equal values at different positions are different assignments: ties in the data are not merged.

## Test options

| Field (Italian) | Default | Meaning |
|---|---|---|
| Alternative (*Alternativa*) | Two-sided | **Two-sided**, **Greater** (First > Second) or **Less** (First < Second). |
| Method (*Metodo*) | Auto | **Auto**, **Exact** (*Esatto*) or **Monte Carlo**. |
| Resamples (*Repliche*) | 9,999 | Monte Carlo resamples, from 199 to 100,000. |
| Seed (*Seme*) | 0 | Any whole number from 0 to 18,446,744,073,709,551,615 (unsigned 64-bit). It is saved exactly in the recipe. |
| Keep draws (*Salva distribuzione nulla*) | Off | Adds the *Null distribution* sheet. |
| Show graph (*Mostra grafico*) | On | Draws the null distribution. |

**Exact** enumerates every assignment: up to **200,000 assignments** and **10 million operations**, counted as assignments × values (independent) or assignments × pairs (paired). Beyond either limit Exact is refused on the Method field. **Auto** enumerates when both limits hold and simulates otherwise; the note under Method says which way it will go with the columns chosen now, and how many assignments that is. **Monte Carlo** allows up to **50 million operations** (resamples × values or pairs); beyond that the Resamples field is refused with the largest number that fits.

With Exact, Resamples and Seed are hidden and ignored. A valid value stays in the recipe so that switching back to Monte Carlo finds it again.

## How the p value is computed

Tails include ties:

* **Greater** counts null statistics ≥ the observed one;
* **Less** counts null statistics ≤ the observed one;
* **Two-sided** counts |statistic| ≥ |observed|. This is the absolute rule, **not** twice the smaller one-sided p value: with unequal sizes the null distribution of an independent design is not symmetric and the two differ.

**Exact:** p = tail count / number of assignments. The observed assignment is one of them, so p is never 0. Enumeration lists the positions of the smaller sample (First when the sizes are equal) in lexicographic order; for pairs, the sign patterns in binary order with the first pair as the most significant digit and minus before plus.

**Monte Carlo:** p = (tail count + 1) / (resamples + 1). *Draws* reports the resamples evaluated, without the + 1. One `numpy.random.Generator(PCG64(Seed))` is created per run; each resample makes exactly one call:

* independent: `choice(N, N₁, replace=False)`, the positions given to First;
* paired: `integers(0, 2, size=pairs, dtype="int64")`, where 0 is minus and 1 is plus.

So the same seed with more resamples **keeps the earlier draws exactly**: 9,999 resamples are the first 9,999 of a run with 20,000.

### Ties in floating point

Decimal data rarely give two exactly equal means in floating point (0.1 + 0.2 ≠ 0.3), so statistics that should tie with the observed one could fall just outside the tail. Two statistics are therefore treated as equal when they differ by at most **τ = 2⁻³⁶ · S**, where S is the largest absolute centred value (independent; the pooled values minus their lower median, a data value) or the largest absolute paired difference. τ is about 10⁴ times the worst rounding of a mean of 50,000 values and does not depend on a common offset: data shifted by 2⁴⁰ give the same distribution and the same counts. Statistics closer than about 1.5·10⁻¹¹ · S are not distinguished. Values much larger than their spread (an offset beyond about 10⁶ times the spread) already carry decimal rounding that no test can recover; subtract a reference value first. τ is listed in *Settings*.

## Results

1. **Permutation results** — one row: N first, N second, Mean first, Mean second, Mean difference, Alternative, p, Tail count, Draws, Mode used (*Exact* or *Monte Carlo*: with Auto this is the method actually used).
2. **Settings** — one value per setting, indexed by name: columns, design, alternative, method requested and used, the statistic, the null hypothesis, the cells or pairs omitted, the number of assignments (Exact) or resamples, seed (as text, all 64 bits), generator and Monte Carlo correction, the tail rule, the tie tolerance and a reminder that no interval is computed.
3. **Null distribution** (only with *Keep draws*) — Draw (from 1) and Statistic, in evaluation order: the enumeration order for Exact, the order of the draws for Monte Carlo. *Use Result as Data* turns it into a worksheet.

The recipe keeps the English field names and choices in both languages; the method actually used is in *Mode used* and *Settings*.

## Graph

A native histogram of the null statistics (*Frequency* on the vertical axis) with:

* a dashed vertical line at the observed difference (SVG id `permutation-observed`);
* for a two-sided test, a dotted line at minus the observed difference (`permutation-mirror`), the other edge of the tail;
* a note with the observed value, p, the tail count and the method used (`permutation-summary`).

A discrete distribution with up to 80 values on a regular grid gets one bar per value; a single value gets one bar of positive width. Bars have the ids `permutation-null-bin-1`, `-2`, …. Format Graph and the Inspector restyle the lines and the bars without drawing a new null sample; SVG and PDF exports stay vector, and the figure can be placed in layouts. Column names appear literally in the axis title (`$` and `_` are not interpreted).

## Running time and Cancel

The test runs on the worker. Exact enumeration and Monte Carlo both check the Cancel button between short blocks (about 262,000 values each), so a click stops the run within a fraction of a second. Cancel keeps the last completed result; a cancelled new analysis adds no recipe. Memory grows with the data and the series of statistics only (8 bytes per assignment or resample).

Synthetic data, measured on Linux with Python 3.12 and one core (the times on a Windows PC will differ, the proportions should not):

| Run | Assignments or resamples | Time | Peak memory | Cancel |
|---|---|---|---|---|
| Exact, 10 + 10 values | 184,756 | 0.04 s | 5.6 MB | — |
| Exact, 2 + 269 values (9.9 million operations) | 36,585 | 0.01 s | 2.0 MB | — |
| Exact, 17 pairs | 131,072 | 0.01 s | 2.5 MB | — |
| Monte Carlo, 500 + 500 values (50 million operations) | 50,000 | 0.76 s | 0.8 MB | 0.003 s |
| Monte Carlo, 25,000 + 25,000 values | 1,000 | 0.22 s | 1.6 MB | 0.001 s |
| Monte Carlo, 25,000 pairs | 2,000 | 0.43 s | 1.2 MB | < 0.001 s |
| Monte Carlo, 4 + 5 values | 100,000 | 0.59 s | 1.6 MB | 0.02 s |

Peak memory is the memory traced by Python during the run, including the statistics kept for the graph. In the application the Cancel button answered within 0.04–0.13 s on a Monte Carlo run of 80,000 resamples of 600 values (about 1.5 s in all).

## Example

`tests/data/mean_permutation/independent.csv`: First = 1, 3, 4, 7 (one blank cell) and Second = −2, 0, 1, 5, 6.

| | Independent, Exact |
|---|---|
| Mean difference | 3.75 − 2 = 1.75 |
| Assignments | C(9, 4) = 126 |
| Two-sided | 57 in tail, p = 57/126 = 0.4524 |
| Greater | 30 in tail, p = 30/126 = 0.2381 |
| Less | 104 in tail, p = 104/126 = 0.8254 |

`tests/data/mean_permutation/paired.csv`: five complete pairs with differences 5, 2, −2, 0, 2 (mean 1.4); two incomplete rows are omitted.

| | Paired, Exact |
|---|---|
| Sign patterns | 2⁵ = 32 |
| Two-sided | 16 in tail, p = 0.5 |
| Greater | 8 in tail, p = 0.25 |
| Less | 30 in tail, p = 0.9375 |

The two-sided p values are not twice the smaller one-sided value (2 × 30/126 = 0.4762 ≠ 0.4524).

## Messages

Every message names the field to correct and keeps the dialog open:

* **Second** — the same column as First, or a cell that is not a finite number;
* **First** — too few values or pairs, or more than 50,000 values / 25,000 pairs;
* **Method** — Exact over 200,000 assignments or 10 million operations;
* **Resamples** — outside 199–100,000, or Monte Carlo over 50 million operations (with the largest number that fits);
* **Seed** — not a whole number from 0 to 18,446,744,073,709,551,615.

If an edit of the worksheet makes the saved analysis impossible (for example one value left in First), the last result is kept and marked as not current, and the dialog reopens on the field to correct.

## Related analyses

* **t-test** and **Paired t-test (columns)** — the mean difference with a confidence interval, assuming normality (Welch for unequal variances).
* **Mann–Whitney** and **Wilcoxon signed-rank** — rank-based tests with exact p values; they test a shift in location rather than the difference of means.
