# Paired proportions (McNemar)

Choose **Group Comparison → Paired proportions** (in Italian *Proporzioni appaiate*) when the same subjects, or matched pairs, are classified twice on a yes/no outcome: before and after a treatment, with two tests, by two raters. It compares the two proportions of positives with McNemar's test and reports the matched odds ratio. The **Contingency table** analysis is unchanged: it treats the groups as independent and is not a substitute.

## Orientation: Before → After

Every pair falls in one of four cells. The fixed orientation is **Before → After**:

| | After negative | After positive |
|---|---|---|
| **Before negative** | a — unchanged negative | b — **gain** (negative → positive) |
| **Before positive** | c — **loss** (positive → negative) | d — unchanged positive |

With N = a + b + c + d: the positive fraction before is (c + d)/N and after is (b + d)/N. Swapping Before and After swaps b and c, so the sign of the difference changes, the odds ratio becomes its reciprocal (its interval too) and the p value does not change.

## Input formats

| Field | Meaning |
|---|---|
| Input format | **Observations** (default) or **Count matrix**. |
| Before, After | Observations only. Two different columns, one pair per row. |
| Negative value, Positive value | Observations only: the codes that mean negative and positive, **0** and **1** by default. Text is trimmed and case-sensitive (`yes` and `Yes` are two codes); a number matches by value, so `1`, `1.0` and `1,0` are the same code. The two codes must be different and not empty. A Boolean cell is never read as 0/1: use text or numeric codes. |
| After negative counts, After positive counts | Count matrix only: two different numeric columns. **Row 1 is Before negative and row 2 is Before positive**, so a = row 1 / After negative, b = row 1 / After positive, c = row 2 / After negative, d = row 2 / After positive. Rows after the second must be empty. |
| Test | **Exact** (default), **Mid-p** or **Chi-square with continuity correction**. |
| Confidence level (%) | Strictly between 0 and 100; default 95. |
| Graph | Off by default. When on, the analysis adds a four-bar graph. |

Fields that do not belong to the chosen input format are hidden, are not validated and are not written to the recipe. Recipes keep the English field names and values whatever language the interface shows.

### Observations

A pair with an empty or excluded cell in either column is **discarded as a whole**; the number of discarded pairs is reported. A value that is neither code, in a pair that is otherwise complete, stops the dialog on the **Before** or **After** field and names the column, the value and its **source row**. Source row is the 1-based position of the row in the worksheet, counted before any filtering, whatever the pandas index is.

### Count matrix

Counts must be whole, non-negative and finite; blanks, text, Booleans, fractions and a third filled row are refused on the field concerned. The total is limited to 10,000,000 pairs and checked exactly. A total of zero is refused.

## What is computed

Three different things are reported, and they should not be mixed up.

**1. The marginal difference** (after − before) = (b − c)/N. It is the change in the proportion of positives. It has **no confidence interval** here; the interval in the report is not an interval for this difference.

**2. McNemar's test** uses only the D = b + c **discordant pairs**; the concordant pairs a and d carry no information about a change. Under the null hypothesis the number of gains B follows a Binomial(D, ½) law. With m = min(b, c):

* **Exact** (default): p = min(1, 2·P(B ≤ m)), the doubled tail of the exact conditional test.
* **Mid-p**: p = min(1, 2·P(B ≤ m) − P(B = m)). It is less conservative than the exact test.
* **Chi-square with continuity correction**: χ² = max(|b − c| − 1, 0)² / D with one degree of freedom; p is its upper tail. The statistic is shown only for this test, and left empty for the two binomial tests.

All p values are two-sided. With b = c the binomial p is 1.

**3. The matched odds ratio** is the conditional estimate b / c: the odds that a discordant pair is a gain rather than a loss. Its interval is the **Clopper–Pearson** exact interval of b out of D, written as odds q/(1 − q), at the chosen confidence level. It is the same whatever test you chose. **The interval belongs to the odds ratio; it is not an interval for the marginal difference, and it is not the confidence interval of the p value.** The report names the method.

Edge cases are stated, not corrected: with no losses (c = 0) the odds ratio and its upper limit are **infinite**; with no gains (b = 0) the odds ratio and its lower limit are **0**. No 0.5 continuity correction is applied. With **no discordant pairs** p = 1 and the statistic, the odds ratio and its interval cannot be estimated and are left empty, with the reason in the **Note** row.

## Results

* **Paired counts**: the 2 × 2 table of a, b, c, d with the rows Before negative / Before positive and the columns After negative / After positive.
* **Paired proportions** (one **Value** column): N pairs, Before positive fraction, After positive fraction, Difference (after − before), Discordant pairs, Chi-square, p, Matched odds ratio, OR CI lower, OR CI upper, then Test, Confidence level (%), OR CI method, Discarded pairs (observations only) and a Note.
* **Pairs** (observations only): each used pair with its **Source row**, Before, After and Transition (Unchanged negative, Gain, Loss or Unchanged positive). Excluded cells and incomplete pairs are not listed.

The graph has four bars: unchanged negative, gain, loss and unchanged positive, each labelled with its count; a bar of zero is drawn and labelled 0. With the graph off the analysis has no figure. The Inspector and Format Graph work as on other graphs.

## Not included

Stuart–Maxwell and Bowker tests for tables larger than 2 × 2, McNemar confidence intervals for the difference of proportions (Newcombe, Wald), exact sample size and power, repeated binary measurements on more than two occasions (Cochran's Q), and matched case-control designs with more than one control. Pairs where the outcome is not binary have to be recoded before the analysis.

## References

* Q. McNemar (1947), *Note on the sampling error of the difference between correlated proportions or percentages*, Psychometrika 12, 153–157.
* C. J. Clopper and E. S. Pearson (1934), *The use of confidence or fiducial limits illustrated in the case of the binomial*, Biometrika 26, 404–413.
* M. W. Fagerland, S. Lydersen and P. Laake (2013), *The McNemar test for binary matched-pairs data: mid-p and asymptotic are better than exact conditional*, BMC Medical Research Methodology 13, 91.
