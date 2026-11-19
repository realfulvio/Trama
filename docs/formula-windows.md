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
=SUM(Dose) OVER Subject ORDER BY Visit ASC, COL("Recorded time") DESC ROWS UNBOUNDED PRECEDING
```

`ORDER BY` sorts each group by one or more comma-separated expressions. Each key uses ascending order unless marked `DESC`. Later keys break ties in earlier keys. Rows tied on every key keep worksheet order, and missing values sort last at each key. Results return to their original worksheet rows. Without `ROWS`, the statistic uses the whole group. When passing a window expression with several sort keys to another function, wrap the expression and its clauses in parentheses.

`ROWS` takes a nonnegative number of rows or `UNBOUNDED`, followed by `PRECEDING` or `FOLLOWING`. An omitted bound ends at the current row. The first and last windows stop at the group's edges. Without `ORDER BY`, positions follow worksheet order. With a filter, only contributing rows take positions or receive results.

Edits and excluded source cells feed the next calculation. Saving an `.alab` project keeps the formula. Compatible ZIP project formulas using these clauses can reopen with their original column references mapped to the imported worksheet.

## Logarithms and angles

Use `LN` for the natural logarithm, `LOG` or `LOG10` for base 10, and `LOG2` for base 2. Nonpositive inputs leave the log result blank.

`SIN`, `COS` and `TAN` take an angle in radians. `ARCSIN`, `ARCCOS`, `ARCTAN` and `ARCTAN2(y, x)` return an angle in radians. Use `RAD` to convert degrees to radians and `DEG` for the reverse conversion. `=COS(RAD(COL("Angle")))` calculates the cosine of an angle stored in degrees. These functions also remain editable in compatible imported ZIP project formulas.

The hyperbolic functions are `SINH`, `COSH` and `TANH`, with inverses `ARCSINH`, `ARCCOSH` and `ARCTANH`. `LOGIT(p)` returns the log odds for values strictly between zero and one. Values outside a function's domain leave the result blank.

## Arithmetic functions

`CEIL` rounds up and `FLOOR` rounds down. `INT` discards the fractional part toward zero. `SGN` gives −1, 0 or 1 according to sign, and `SQR` squares each value. The same functions are available to editable imported formulas.

## Special functions

`GAMMA(x)` and `PSI(x)` leave poles blank. `GAMMALN(x)` gives the real
logarithm wherever the gamma function is positive. `IGAMMA(shape, x)` and
`IGAMMAC(shape, x)` give the regularized lower and upper incomplete gamma
functions for positive shape and nonnegative x. `BETA(a, b)` and
`IBETA(a, b, x)` use positive shapes, and the regularized incomplete beta
accepts x from 0 to 1.

`ERF(x)` and `ERFC(x)` give the error function and its complement.
`BESSELJ(order, x)` and `BESSELY(order, x)` give real Bessel values where
defined. `PERC(x)` divides a percentage by 100. For example,
`=Dose * PERC(12.5)` gives one eighth of each dose. Undefined values and
nonfinite special-function results leave the cell blank.

## Distributions

`NORMDIST(x, mean, sd, tail)`, `NORMINV(p, mean, sd, tail)` and
`NORMPDF(x, mean, sd)` default to mean 0 and SD 1. The corresponding
standard normal functions are `ZDIST(z, tail)`, `ZINV(p, tail)` and `ZPDF(z)`.
Use the text `"left"` (the default), `"right"` or `"two"` for the tail.
The two-tail probability doubles the smaller tail. Its inverse returns the
upper quantile for half that probability. `PROBIT(p)` gives `5 + ZINV(p)`.

`TDIST(t, df)`, `CHIDIST(x, df)` and `FDIST(f, df1, df2)` give upper-tail
probabilities. `TINV(p, df)` uses a two-tail probability. `CHIINV(p, df)` and
`FINV(p, df1, df2)` use an upper-tail probability. `CHISQC(x, df)` gives a
lower-tail probability. `TPDF(t, df)` and `FPDF(f, df1, df2)` give densities.
`BINOMIAL(k, n, p)` gives the probability of at least k successes in n trials.
Invalid numeric arguments and nonfinite results leave the cell blank.

## Missing values

`ISBLANK(value)` and `IS_DEFINED(value)` test whether a value is absent or
present. An empty cell, whitespace-only text or a nonfinite calculation is
absent. Zero, false and nonblank text are values. For example,
`=IF(ISBLANK(Dose), 0, Dose)` uses zero for missing doses in the new column.

## Centering, standardizing and ranking

`CENTER(Column)` subtracts the mean of the usable values from each value. `STANDARDIZE(Column)` and `ZSCORE(Column)` divide the centered values by the sample standard deviation. A constant column or a single usable observation leaves standardized values blank.

`RANK(Column)` assigns rank 1 to the smallest usable value and averages the ranks of ties. These functions keep the original worksheet row order. Missing or nonfinite values leave a blank on their own row and are excluded from the statistics. When recognized in an imported ZIP project, the formulas recalculate after edits and remain editable when saved as `.alab`.


These four functions also accept `OVER`, `WHERE`, `ORDER BY` and `ROWS`. For example, `=ZSCORE(Dose) OVER Subject` uses each subject's mean and sample standard deviation. `=RANK(Dose) OVER Subject ORDER BY Visit ROWS 2 PRECEDING 1 FOLLOWING` ranks the current dose within its ordered window, including qualifying following rows.

With `WHERE` and a whole group, qualifying observations form the reference and each row can still receive a result. For a rank against that reference, a value present in the reference receives its mean rank and a value absent from the reference receives its insertion rank, starting at 1. With `ROWS`, only qualifying rows receive results. An empty reference or a blank current value gives a blank result.
