# Power for paired proportions

Choose **Tools → Paired proportions power…** (in Italian *Potenza per proporzioni appaiate…*). The same method is in the analysis catalog under **Study Design and Simulation**. It plans a two-sided exact McNemar test from the two transition probabilities you expect, before any pairs are collected. It computes the power at a fixed number of pairs, or the smallest number of pairs whose power reaches a target. It opens in a project with no tables, as **Power and sample size** does, and it does not change that plan. The paired-proportions test itself is unchanged; this plan does not read its result. See [Paired proportions](paired-proportions.md).

## The dialog

| Page | Fields |
| --- | --- |
| **Design** | `Goal`, `Alpha (%)`, `Target power` (Sample size) or `Number of pairs` (Power) |
| **Effect** | `Negative to positive (%)`, `Positive to negative (%)` |
| **Curve** | `Graph` |

`Negative to positive (%)` is p01 and `Positive to negative (%)` is p10, each a percentage of all pairs, not of the discordant pairs. The Effect page shows the expected difference p01 − p10, in percentage points, and the discordance p01 + p10. Either probability may be 0. Their sum may be 100. A sum above 100 is refused on `Positive to negative (%)`. A comma is a decimal mark (`30,5` is 30.5), as in the other numeric fields. `Number of pairs` is a whole number from 1 to 5,000; a decimal comma there is not a number of pairs.

Only the fields of the chosen goal are shown. A hidden field never blocks the calculation, whatever it contains, and it is not written to the recipe. A mistake stays in the dialog, on the page of the field, and the keyboard focus moves to that field.

Recipes keep the English field names and the English goal in both languages. Numbers are stored without a locale (`0.8`, `30`, `10`).

## What is calculated

The test is the exact two-sided McNemar test, conditional on the number D of discordant pairs. With r = p01 + p10 and, when r > 0, q = p01 / r:

* D follows a binomial law with N pairs and probability r. D = 0 never rejects.
* Given D, the number of negative-to-positive pairs follows a binomial law with probability q.
* For each D ≥ 1 the critical value k is the largest integer below D/2 such that 2 · Pr(Binomial(D, 1/2) ≤ k) ≤ α. Alpha is inclusive. If no such k exists, that D never rejects.
* Otherwise the conditional power is Pr(B ≤ k) + Pr(B ≥ D − k). The two tails are added separately.
* Project power is the exact average of those conditional probabilities over D.

The critical value is the rejection rule of the exact p already reported for paired proportions. Normal approximations and the mid-p test are not used.

Two designs are not the same thing. With no discordance (r = 0) the test never rejects, so the power is 0 at every N. With discordance but p01 = p10, the power is the size of the exact test at that design, not the power of an effect. In the sample-size goal, a target above α is then reported as unreachable: no number of pairs can exceed the size of the test.

Swapping the two transitions changes the sign of the expected difference and replaces q with 1 − q. The rejection region is symmetric, so the power does not change.

## Sample size

The search visits N = 1, 2, 3, … in that order and stops at the first N whose power is at least the target, or at 5,000 pairs. The limit is the `Pairs limit` row of every result. Power need not increase with N. A later N can have lower power, so the search does not jump ahead and the curve is not interpolated through missing integers.

For p01 = 75%, p10 = 25% and α = 5%, the power at 6 pairs is higher than the power at 7. The first N that reaches a target of 0.17 is 6, and 7 does not reach it. For the default planning case, p01 = 30%, p10 = 10%, α = 5% and target 0.8, the first N is 84 pairs. Both are locked by the tests against an enumeration that does not call this module.

If the target is not reached inside the limit, the result says so and reports the largest power that was calculated and the N at which it occurred. The sample-size sheet also reports the power at N − 1 when N > 1, which is not enough on its own to prove the minimum: every smaller N has to miss the target.

## The curve

`Graph` adds a sheet `Power curve` and a native figure of the same name. The sheet has one row for every integer N that was calculated, from 1 through the chosen N (the minimum, or the requested number of pairs, or 5,000 when the target was not reached). The line connects those calculated powers. It does not skip a value. Tick marks on N are whole numbers. The chosen N is marked. The horizontal target line is drawn only for the sample-size goal. With the option off there is no curve sheet and no figure.

The figure is an ordinary graph of the project: Format Graph and the Inspector edit it, and it exports as PNG, SVG or PDF.

## The result sheet

`Power for paired proportions` has one **Value** column: Result, N, Power, Power at N−1 when a minimum above 1 was found, Alpha, Discordance, Expected difference, Alternative (q, empty when there is no discordance), the two transition probabilities as fractions, Target power for the sample-size goal, Maximum power and N at maximum when the target was not reached, Pairs limit, and a Note when one is needed.

Result is **Minimum N**, **Power**, **Not reached**, **No discordance** or **Null effect**.

## Contract

`analisi/mcnemar_power.py` exposes

* `exact_power(n, p01, p10, alpha=0.05)` — power at `n` pairs. Probabilities and alpha are fractions. `n` is an integer from 1 to 5,000.
* `minimum_pairs(p01, p10, target, alpha=0.05, *, max_pairs=5000, cancel=None)` — the first N whose power reaches `target`, or `None` when none does within `max_pairs`. `max_pairs` cannot exceed 5,000.

Cancellation raises `McNemarPowerCancelled` (a `MonteCarloCancelled`) and does not return an N. A result already returned is left as it was. The desktop calculation uses the same cancellation as the other long analyses: cancelling one that is still running does not replace a result the project already holds.

## Limits

* Prospective planning from the probabilities you type. It is not the power of a table you have already observed.
* Two-sided exact conditional McNemar only. Mid-p, chi-square and normal or arcsine approximations are out of scope.
* At most 5,000 pairs. The search and the curve both stop there.
* The two probabilities are constant across pairs. Dropouts, clustering and a margin that is not the transition difference are not modelled.

## References

* J. M. Lachin (1992), *Power and sample size evaluation for the McNemar test*, Biometrics 48, 613–621.
* The exact p of the test is the one documented in [Paired proportions](paired-proportions.md).
