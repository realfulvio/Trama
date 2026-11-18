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

## Ordered and moving statistics

```text
=SUM(Dose) OVER Subject ORDER BY Visit ROWS UNBOUNDED PRECEDING
=MEAN(Response) OVER Subject ORDER BY Visit ROWS 1 PRECEDING 1 FOLLOWING
=COUNT(Response) OVER Subject ORDER BY Visit DESC ROWS UNBOUNDED PRECEDING
```

`ORDER BY` sorts each group by one expression. Add `DESC` for descending order. Ties keep worksheet order, and missing sort values go last. Results are returned to the original worksheet rows. Without `ROWS`, the statistic still uses the whole group.

`ROWS` takes a nonnegative number of rows or `UNBOUNDED`, followed by `PRECEDING` or `FOLLOWING`. An omitted bound ends at the current row. The first and last windows stop at the group's edges. Without `ORDER BY`, positions follow worksheet order. With a filter, only contributing rows take positions or receive results.

Edits and excluded source cells feed the next calculation. Saving an `.alab` project keeps the formula. Compatible ZIP project formulas using these clauses can reopen with their original column references mapped to the imported worksheet.

## Logarithms and angles

Use `LN` for the natural logarithm, `LOG` or `LOG10` for base 10, and `LOG2` for base 2. Nonpositive inputs leave the log result blank.

`SIN`, `COS` and `TAN` take an angle in radians. `ARCSIN`, `ARCCOS`, `ARCTAN` and `ARCTAN2(y, x)` return an angle in radians. Use `RAD` to convert degrees to radians and `DEG` for the reverse conversion. `=COS(RAD(COL("Angle")))` calculates the cosine of an angle stored in degrees. These functions also remain editable in compatible imported ZIP project formulas.

The hyperbolic functions are `SINH`, `COSH` and `TANH`, with inverses `ARCSINH`, `ARCCOSH` and `ARCTANH`. `LOGIT(p)` returns the log odds for values strictly between zero and one. Values outside a function's domain leave the result blank.

## Arithmetic functions

`CEIL` rounds up and `FLOOR` rounds down. `INT` discards the fractional part toward zero. `SGN` gives −1, 0 or 1 according to sign, and `SQR` squares each value. The same functions are available to editable imported formulas.

## Centering, standardizing and ranking

`CENTER(Column)` subtracts the mean of the usable values from each value. `STANDARDIZE(Column)` and `ZSCORE(Column)` divide the centered values by the sample standard deviation. A constant column or a single usable observation leaves standardized values blank.

`RANK(Column)` assigns rank 1 to the smallest usable value and averages the ranks of ties. These functions keep the original worksheet row order. Missing or nonfinite values leave a blank on their own row and are excluded from the statistics. When recognized in an imported ZIP project, the formulas recalculate after edits and remain editable when saved as `.alab`.
