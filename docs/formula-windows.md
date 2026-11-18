# Statistics in worksheet formulas

Use **Calculated column** to assign a statistic to the rows of a data table. Add `OVER` to calculate within each group and `WHERE` to select the rows that contribute. Use `COL("Column title")` for literal column names, including titles with spaces.

```text
=MEAN(COL("Response")) OVER COL("Treatment")
=SUM(COL("Dose")) OVER COL("Subject") WHERE COL("Visit") <= 3
=COL("Response") - (MEAN(COL("Response")) OVER COL("Treatment"))
```

The filter affects the calculation. Each row with a group receives that group's result. Grouping by a comparison, such as `OVER COL("Visit") > 0`, is also supported. A blank partition leaves the result blank on that row. In a `WHERE` comparison, text fields match without regard to case.

`MEAN`, `SUM`, `MIN`, `MAX`, `STDEV`, `STDERR`, `COUNT` and `COUNTA` support these clauses. `STDEV` and `STDERR` use the sample standard deviation. `COUNT` counts finite numeric values. `COUNTA` counts nonblank values, including text. Omit `OVER` to use a single group covering the worksheet. Put a statistic and its clauses in parentheses before combining it with a larger formula.

Use `MEANIF(values, condition)`, `SUMIF`, `MINIF`, `MAXIF`, `STDEVIF`, `STDERRIF`, `COUNTIF` or `COUNTAIF` to write the condition inside the function. These forms also accept `OVER`. If you add a `WHERE` clause, a row must satisfy both conditions to contribute.

Edits and excluded source cells feed the next calculation. Saving an `.alab` project keeps the formula. Compatible ZIP project formulas using these clauses can reopen with their original column references mapped to the imported worksheet. Ordered, running and moving windows require `ORDER BY` and `ROWS`, which are outside this version's supported syntax.
