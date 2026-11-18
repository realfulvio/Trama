# Cohen's kappa fixtures

`ratings.csv` and `expected.json` come unchanged from the synthetic package of the 0.93 assignment. The 32 rows
are one subject rated twice; the last two rows have one empty rating, so 30 pairs are complete and 2 incomplete.
In the order `Mild`, `Moderate $`, `Severe` the counts are `[[8, 2, 1], [1, 7, 2], [0, 3, 6]]` (rows are the first
rating), and the observed agreement is 21/30.

`expected.json` holds the exact kappas (11/20 unweighted, 8/13 linear, 13/19 quadratic) and two bootstrap
references, both with 199 resamples and seed 2701: the quadratic interval of the table above and a rare table
`[[20, 0], [0, 1]]` where only 125 resamples have a defined kappa, so no interval is reported.
