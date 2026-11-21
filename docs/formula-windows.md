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

## Calculated columns that use other formulas

A formula can refer to another calculated column on either side of it. For example, an earlier column named `Output` can use `=2 * COL("Adjusted dose")`. Trama calculates the inputs first and keeps the columns in their worksheet order. Editing or excluding a source value updates the dependent results. A direct or indirect circular reference is reported before the edit is applied.

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

`ROUND(x, digits)` rounds to the specified number of decimal places, with halfway
values rounded away from zero. Negative digits round to the left of the decimal
point. Digits may come from another column and must be integers. Existing
`ROUND(x)` formulas keep their ties-to-even rounding.

`x MOD y` computes the remainder with the sign of the divisor. A zero divisor
leaves the result blank. `FACT(n)` accepts nonnegative integers and leaves a
blank when the factorial exceeds the numeric range.

`MIN`, `MAX` and `SUM` with two or more arguments operate across each row.
They skip missing numeric values and leave a row blank when it has no
usable arguments. With one column argument they still use the entire column.
These formulas can remain editable when imported from a compatible ZIP project.

## Special functions

`GAMMA(x)` and `PSI(x)` leave poles blank. `GAMMALN(x)` gives the real
logarithm wherever the gamma function is positive. `IGAMMA(shape, x)` and
`IGAMMAC(shape, x)` give the regularized lower and upper incomplete gamma
functions for positive shape and nonnegative x. `BETA(a, b)` and
`IBETA(a, b, x)` use positive shapes, and the regularized incomplete beta
accepts x from 0 to 1.

`ERF(x)` and `ERFC(x)` give the error function and its complement.
`BESSELJ(order, x)` and `BESSELY(order, x)` give real Bessel values where
defined. `BESSELI(order, x)` and `BESSELK(order, x)` give the modified Bessel
functions, with positive `x` for `BESSELK`. `HYPGEOMETRICM(a, b, x)` and
`HYPGEOMETRICU(a, b, x)` give the two confluent hypergeometric functions.
`HYPGEOMETRICF(a, b, c, x)` gives the Gauss hypergeometric function. The
worksheet keeps finite real results, including well-defined terminating series.

`PERC(x)` divides a percentage by 100. For example,
`=Dose * PERC(12.5)` gives one eighth of each dose. Undefined values and
nonfinite special-function results leave the cell blank.

## Text and conditions

Use `=CONCATENATE(COL("Study group"), " / ", Visit)` to build a label on
each row. Numbers are converted to text, blanks contribute an empty string,
and spaces and punctuation in text arguments are preserved. `AND` and `OR`
take two or more conditions, for example `=AND(Dose > 0, Visit <= 3, IS_DEFINED(Dose))`.

You can also put `AND` and `OR` between conditions and `NOT` before a condition.
For example, `=IF(Dose > 0 AND Visit <= 3, "Include", "Review")` evaluates each row
separately. Comparisons are evaluated before `NOT`, then `AND`, then `OR`.
Use parentheses to group conditions.

`=` and `<>` compare text without regard to case. Existing `==` and `!=`
comparisons outside filters are case-sensitive. Use `CASE_INSENSITIVE(expression)`
to apply case-insensitive comparisons throughout an expression, including ordering
comparisons. Imported formulas use it where needed to preserve their comparison rules.

## Random samples

`GAUSS(mean, sd)` draws from a normal distribution. `RND(lower, upper)` draws
uniformly between two bounds. Each call draws one value per row. Missing
arguments, a negative deviation, and reversed bounds leave that row blank.
A zero deviation returns the mean, and equal bounds return their common value.

When you confirm a calculated column, Trama saves the seed with its formula.
For example, `=WITH_SEED(42, GAUSS(Dose, 1))` uses the same random sequence when
you view, export or reopen the worksheet. Editing a parameter such as `Dose`
recalculates the formula from the saved sequence. Change the seed in the formula
editor for a new sample. Seeds are whole numbers from 0 through 2⁶⁴−1.
The sequence follows worksheet row order, and separate random calls consume
separate draws.

Imported random worksheet columns keep their recorded values. An imported
live transform with random calls receives a seed for a new reproducible result.

## Select and Transform

In Analyze, choose **Select and Transform**. Arrange the output columns in
**Variables**. In **Row filters**, set the first and last source row if you
need a range. Both bounds are inclusive and row numbers start at 1. Within
that range, the result keeps the rows that satisfy every condition. Conditions
can compare a column with a number, text or another column, or check for
missing values.

In **Calculated variables**, enter an output name and expression for each
new column. The formulas use the selected rows and may refer to source
columns or earlier calculated variables. Use `COL("Column name")` for a
name with spaces. To edit the range, conditions or formulas later, open the
result and choose **Change parameters**. Saving the project keeps these
settings with the analysis.

## Distributions

Use [probability, density and quantile formulas](distribution-formulas.md)
for the normal, Student t, chi-square, F and binomial distributions. The guide
lists arguments, tail conventions and examples you can paste into the worksheet.

## Centering, standardizing and ranking

`CENTER(Column)` subtracts the mean of the usable values from each value. `STANDARDIZE(Column)` and `ZSCORE(Column)` divide the centered values by the sample standard deviation. A constant column or a single usable observation leaves standardized values blank.

`RANK(Column)` assigns rank 1 to the smallest usable value and averages the ranks of ties. These functions keep the original worksheet row order. Missing or nonfinite values leave a blank on their own row and are excluded from the statistics. When recognized in an imported ZIP project, the formulas recalculate after edits and remain editable when saved as `.alab`.


These four functions also accept `OVER`, `WHERE`, `ORDER BY` and `ROWS`. For example, `=ZSCORE(Dose) OVER Subject` uses each subject's mean and sample standard deviation. `=RANK(Dose) OVER Subject ORDER BY Visit ROWS 2 PRECEDING 1 FOLLOWING` ranks the current dose within its ordered window, including qualifying following rows.

With `WHERE` and a whole group, qualifying observations form the reference and each row can still receive a result. For a rank against that reference, a value present in the reference receives its mean rank and a value absent from the reference receives its insertion rank, starting at 1. With `ROWS`, only qualifying rows receive results. An empty reference or a blank current value gives a blank result.
