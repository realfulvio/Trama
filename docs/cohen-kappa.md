# Cohen's kappa

Choose **Group Comparison → Cohen's kappa** (Italian: *Confronto tra gruppi → Concordanza tra valutatori (kappa di Cohen)*) when two raters, two instruments or two readings put the same subjects into categories and you want to know how much they agree **beyond the agreement expected by chance**. Each worksheet row is one subject; one column holds the first rating and another the second.

The analysis reports the observed agreement, Cohen's kappa (unweighted, linear or quadratic), an optional bootstrap interval and the matrix of agreement as sheets and as a graph. The worksheet is only read: nothing in it changes.

## A worked example

`tests/data/cohen_kappa/ratings.csv` has 32 rows rated *Mild*, *Moderate $* or *Severe* by two raters. Two rows have one rating missing, so 30 pairs are complete. In the order Mild, Moderate $, Severe the counts are:

| Rater A ↓ / Rater B → | Mild | Moderate $ | Severe |
|---|---|---|---|
| Mild | 8 | 2 | 1 |
| Moderate $ | 1 | 7 | 2 |
| Severe | 0 | 3 | 6 |

The raters agree on 21 of 30 subjects (observed agreement 0.7). The row totals 11, 10, 9 and the column totals 9, 12, 9 would give an agreement of 1/3 by chance, so the unweighted kappa is (0.7 − 1/3) / (1 − 1/3) = **11/20 = 0.55**. With linear weights it is **8/13 ≈ 0.615** and with quadratic weights **13/19 ≈ 0.684**: the weighted kappas give partial credit to the near misses (Mild against Moderate $) and penalise the far ones (Mild against Severe) more.

## Choices

The dialog has two pages.

**Ratings**

| Field | Meaning |
|---|---|
| First rating | The column of the first rating. It gives the **rows** of the matrix. A new analysis proposes the first column of the worksheet. |
| Second rating | The column of the second rating, different from the first. It gives the **columns** of the matrix. |
| Weighting | **Unweighted** (every disagreement costs 1), **Linear** (the cost is the distance between the positions of the two categories in the order) or **Quadratic** (the squared distance). |
| Category order | The order of the categories. Empty means the automatic order and is allowed only with **Unweighted**. **Linear** and **Quadratic** need an order that lists every category once, because the weights depend on it. |

**Interval and graph**

| Field | Meaning |
|---|---|
| Confidence interval | **None** or **Bootstrap percentile**. |
| Confidence level (%) | Shown with the bootstrap: a number greater than 0 and less than 100 (default 95). A decimal comma is accepted. |
| Resamples | Shown with the bootstrap: a whole number from 199 to 20,000 (default 1,999). |
| Seed | Shown with the bootstrap: a whole number from 0 to 2⁶⁴ − 1 (default 0). The same recipe gives the same interval. |
| Show graph | Draws the matrix of agreement (default on). |

The three bootstrap fields are hidden while the interval is **None**. Hidden, they are not checked and keep whatever they hold, so switching the interval off and on again does not lose what you typed.

### The category order editor

The list shows the saved order; the categories found in the complete pairs are shown next to it in an orange note, never written into the order by themselves:

- **Not in the order yet** lists categories present in the data but missing from the order (for instance a new rating typed in the worksheet);
- **Not in the complete pairs** lists categories of the order that are no longer in the data (they are also shown in orange in the list).

**Up** and **Down** move the selected category (also **Alt+Up** and **Alt+Down** on the list). **Propose** keeps the current order, drops the categories that are no longer in the pairs and appends the new ones at the end, in the automatic order. **Restore** brings back the order the dialog opened with, and **Clear** empties it (automatic order, Unweighted only).

## Categories

- A rating is a category when it is **text** (kept exactly as written, spaces included), a **finite number** or a **logical value**.
- A row whose first or second rating is missing (an empty cell, an excluded cell, or text made only of spaces) leaves out the whole pair and is counted once in **Incomplete pairs**. This is the same row rule as the paired comparisons.
- The categories are those seen in the complete pairs of either column, so a category used by only one rater still has its row and its column.
- Each category has a label that names it in the sheets, the editor and the graph: text is its own label; a whole number is written without decimals (`1`, also for `1.0`); any other number in its shortest exact form (`2.5`, `1e+20`); a logical value as `True` or `False`.
- Text and numbers are different categories: the text `01` and the number `1` stay apart. Two categories of different types with the **same label** (the text `1` and the number `1`, or the text `True` and the logical value True) are refused instead of being silently merged; the message names the text and asks to use one type in both columns.
- Infinite numbers, complex numbers and other values that are neither text nor finite numbers are refused with the source row and the column.

The **automatic order** lists the numbers ascending, then False and True, then the text ignoring case (ties by code point).

## How it is computed

With *N* complete pairs, *n*ᵢⱼ the counts, *r*ᵢ and *c*ⱼ the row and column totals and *w*ᵢⱼ the disagreement costs (0 on the diagonal; 1 elsewhere for Unweighted, |*i* − *j*| for Linear, (*i* − *j*)² for Quadratic, where *i* and *j* are positions in the order):

```text
kappa = 1 − N · Σ wᵢⱼ nᵢⱼ / Σ wᵢⱼ rᵢ cⱼ
```

Both sums are exact integers, so the point value is the correctly rounded quotient: 11/20, 8/13 and 13/19 in the example above. Kappa is **undefined** when the expected cost is zero, which happens when the complete pairs hold a single category; the sheet then says *Undefined kappa* and the observed agreement is still reported. Kappa can be negative when the raters disagree more than chance would. The three weightings agree with `statsmodels.stats.inter_rater.cohens_kappa` on the same order.

**Expected counts** are *r*ᵢ · *c*ⱼ / *N*.

### Bootstrap interval

Each resample draws one multinomial table of *N* pairs from the observed joint frequencies (whole pairs, in row-major order), with a single `numpy.random.Generator(PCG64(seed))` and one `multinomial` call per resample. Categories absent from a resample keep their row and column, so the weights do not change. A resample with a single category has an undefined kappa and is not used.

The two-sided percentile interval interpolates linearly between the order statistics of the resamples with a defined kappa (the same rule as `numpy.quantile(..., method="linear")`). The interpolation is done in exact fractions and each bound is rounded once, so the interval does not depend on the order of the floating-point sums. When fewer than **90%** of the requested resamples are valid the interval is left empty and the status says *Too few valid resamples*. A bootstrap run has a **Cancel** button; cancelling keeps the last completed result.

## Results

In this order:

1. **Agreement** — one row named *first × second*: Complete pairs, Incomplete pairs, Observed agreement, Kappa, CI lower, CI upper, Valid resamples and Status (**OK**, **Undefined kappa** or **Too few valid resamples**).
2. **Counts** — the matrix: rows are the first rating (named after its column), columns the second rating, in the chosen order.
3. **Expected counts** — the same layout with *r*ᵢ · *c*ⱼ / *N*.
4. **Category totals** — for each category, its total in the first and in the second rating.
5. **Settings** — the columns, the orientation of the matrix, the weighting and its costs, the order (explicit or automatic) with each category, the pairs, the rules for missing ratings and labels, the formula, the bootstrap settings when used, and what is not included.

The **graph** draws the Counts sheet as a vector matrix with the same orientation and labels: the first category is the top row and the first column, the first rating is on the vertical axis and the second on the horizontal one, every cell writes its count, and the diagonal of agreement is outlined so it stays visible whatever the colour of its cells. The title gives the weighting and kappa with three decimals. **Graph settings…** on the graph page reopens the dialog on *Show graph*; **Format Graph** and the **Inspector** change titles and text without calculating again, and text is always shown literally (`$`, `_` and braces are not formulas).

**Use result as data** works on every sheet: on Counts, the first rating becomes the first column of the new worksheet.

## Limits

50,000 complete pairs and 20 categories. A request over a limit is refused before any calculation, on *First rating*. The bootstrap reads 199 to 20,000 resamples. On 50,000 pairs and 20 categories, 20,000 resamples take less than a second on a 4-core Linux computer, and **Cancel** stops the run between two blocks of 250 resamples, within a few milliseconds.

## Errors and recovery

Every error names its field and keeps the dialog open with what you chose: a missing or repeated column, the same column twice (reported on *Second rating*), an order that repeats a category, misses one or names one that is not in the complete pairs, a weighted kappa without an order, a level, a number of resamples or a seed out of range, a value that is not a category (with the source row). The order editor shows the problem before you press **Run Analysis**.

A worksheet edit that makes a saved analysis impossible — typically a new category typed in a cell, or the last cell of a category excluded — keeps the last good result, marks it as out of date and reopens the dialog on *Category order*, where **Propose** fixes the order in one click.

## What it is not

Not included: Fleiss' kappa and more than two raters, intraclass correlation, p values for kappa, and arbitrary distances between categories.
