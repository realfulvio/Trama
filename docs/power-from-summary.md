# Power and sample size from expected means and SDs

On Qt, choose **Analyze → Power and sample size…**. In the classic interface the command is under **Tools**. It plans a study from expected means and standard deviations or a standardized effect size. It covers the one-sample t test, the paired t test, the independent t test (with an exact allocation ratio) and the balanced one-way ANOVA. It computes the sample size needed to reach a target power or the power for a given N.

The command works in a project with no tables, because the calculation needs no data. It opens the dialog, runs the calculation and adds an ordinary analysis to the project, so the result is a sheet like any other: it can be edited from its recipe, reopened from a saved `.alab`, placed in a layout and reused with **Use Result as Data**.

## The dialog

| Page | Fields |
| --- | --- |
| **Design** | `Goal`, `Design`, `Alpha`, `Target power` (Sample size) or `N (per group, if independent)` (Power), `ANOVA groups` (standardized ANOVA only), `Allocation A:B` (independent t only) |
| **Effect** | `Effect input`, then the numbers of the chosen input |
| **Curve** | `Show power curve` |

Only the fields that the current Goal, Design and Effect input use are shown. A field that is hidden never blocks the calculation, whatever it contains. A mistake is reported in the dialog on the right page and the keyboard focus goes to the field.

`Effect input` is **Standardized effect** (the behaviour of every earlier version: one effect size) or **Means and SD**:

| Design | Numbers | Standardized effect used |
| --- | --- | --- |
| One-sample t | `Mean A`, `Null mean`, `Common SD` | d = \|Mean A − Null mean\| / Common SD |
| Paired t | `Mean A`, `Mean B`, and either `Difference SD` or `SD A`, `SD B`, `Pair correlation` | d_z = \|Mean B − Mean A\| / SD of the differences |
| Independent t | `Mean A`, `Mean B`, `Common SD` | d = \|Mean B − Mean A\| / Common SD |
| One-way ANOVA | `Group means` (2 to 20), `Common SD` | f = SD of the group means / Common SD |

For the paired design the SD of the differences is either typed directly or derived from the two marginal SDs and the pair correlation, `sqrt(SD A² + SD B² − 2 ρ SD A SD B)`. A direct SD and the equivalent marginal SDs give the same plan. The SD of the group means is the population SD (divisor k): Cohen's f is defined for the groups of the design, not for a sample of groups.

The sign of the difference does not matter: the test is two-sided. The sheet keeps the numbers you typed and the standardized effect that came out of them.

### Lists of means

`Group means` takes numbers separated by semicolons or new lines, in a small multi-line box (Return adds a line, Tab leaves the box). A **comma is a decimal mark, never a separator**: `13,5` is one value, 13.5. An empty cell (`1; ;3`), a value that is not a number, a value that is not finite and a list shorter than 2 or longer than 20 are refused by item number. All means equal give a zero effect, which is refused as well.

## Allocation A:B (independent t)

`Allocation A:B` fixes the ratio of the two groups for every design the search considers: `2:3` means n A = 2m and n B = 3m for a whole number m. Each term is a whole number from 1 to 100 and the ratio is reduced (`4:6` is `2:3`). `1:1` is the equal-size test of earlier versions and gives the same numbers as before.

* **Sample size** searches the allocation lattice m = 1, 2, 3, … and returns the smallest m that reaches the target, with `N A`, `N B` and `Total N`. Both groups need at least 2 observations, so for `1:3` the first admissible m is 2. A target that the first admissible multiple already reaches is returned as that multiple.
* **Power** takes `N` as the size of group A, which must be a multiple of the A term so that the ratio stays exact; the refusal names the nearest valid sizes (`N must be a multiple of 2 to keep Allocation 2:3 exact, for example 50 or 52.`). A size that would leave group B with fewer than 2 observations, or more than 1,000,000, is refused.
* With unequal groups the power is computed from the two-sided noncentral t distribution with n A + n B − 2 degrees of freedom and noncentrality d / sqrt(1/n A + 1/n B).

## Search and limits

The search never builds a table of sizes. It grows the lattice index geometrically, bisects, and then checks that the predecessor really misses the target, so a rounding wobble cannot hide a smaller solution. A request that cannot be met inside the limit is refused with `Target power exceeds the sample size limit of 1,000,000.` Group sizes are limited to 1,000,000.

When SciPy cannot evaluate the lower tail of a large noncentral t (large effects, extreme alpha), that tail, which is at most min(alpha/2, the normal tail beyond −noncentrality), is left out. Power is never overstated.

## The power curve

`Show power curve` adds a sheet `Power curve` and a native figure of the same name, drawn from that sheet: power against the **total** sample size for the same design. The chosen N is marked, and with Sample size so is the target power. At most 200 points are drawn, geometrically spaced from the smallest admissible size, always including the chosen size, its predecessor and the end of the range, which stops where power reaches 0.999 or the size limit. With the option off the result has no curve sheet and no figure, exactly as before.

The figure is a normal graph of the project: **Format Graph…** and the Inspector edit it, it can be exported (PNG, SVG, PDF) and placed in a layout.

## What the result sheet says

The summary sheet keeps the legacy rows (`Design`, `Effect size`, `Effect measure`, `Alpha`, `N unit`, `Groups`, `N`, `Total N`, `Target power`, `Power`) and adds what the new inputs need: `Effect source` and the typed means and SDs (Means and SD), `N A`, `N B` and `Allocation A:B` (unequal allocation), an `Assumptions` row that names the test (for example `Two-sided independent t test (Student: common SD in both groups). Fixed allocation 2:3.`) and a `Power basis` row, `Prospective, from the design inputs`. The curve sheet has `N`, `Total N` and `Power`, plus `N A` and `N B` for an unequal allocation. A standardized effect with a balanced design gives the same sheet as the previous version.

Recipes keep canonical English field names and values in both languages, and numbers in locale-free form (`4.5`, `12; 13.5; 15; 16`). The interface text, the notes and every error message exist in English and Italian; the numbers in a message are copied literally.

## Assumptions and limits

* A prospective calculation from the numbers you expect; it is not a post hoc power of an observed result.
* Two-sided tests with equal variances (Student t, classical F). Welch, unequal group SDs, non-central effects, clustering and dropouts are not modelled.
* The F test is the balanced one-way ANOVA with total N = n × k; the result gives N per group.
* The effect from means and SDs is only as good as the SD you expect. A change of the SD changes the plan more than an equal relative change of the means.
