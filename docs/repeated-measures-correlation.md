# Repeated-measures correlation

Choose **Data Exploration and Summary → Repeated-measures correlation** (Italian: *Esplorazione e sintesi dei dati → Correlazione a misure ripetute*) when every subject was measured several times and the question is: **when X goes up within a subject, does Y go up too?**

The answer is the repeated-measures correlation of Bakdash and Marusich (2017): every subject keeps its own intercept and all subjects share one slope. It measures the association **within** subjects only. Correlation, Correlate against control and Compare independent correlations are unchanged and keep their recipes.

## Why not Pearson on the pooled rows or on the means

Pooling all rows into one Pearson correlation treats repeated measurements as independent and mixes two things: the association within subjects and the differences between subjects. Averaging each subject first keeps only the differences between subjects. Either can point the other way from what happens inside each subject.

The worksheet `tests/data/rmcorr/repeated.csv` (columns *Participant*, *Day*, *Signal*; 13 rows, four subjects) shows the gap. Inside each of A, B and C, Signal rises with Day:

| Method | Rows used | Coefficient |
|---|---|---|
| Pearson on the 11 pooled pairs of A, B and C | 11 | −0.600 (p = 0.051) |
| Pearson on the three subject means | 3 | −0.998 |
| **Repeated-measures correlation** | 11 pairs, 3 subjects | **+0.784** (p = 0.0124) |

The subjects who were measured later (B) happen to have lower signals, so both pooled and mean-based correlations come out negative. The within-subject association is positive.

## Choices

| Field | Meaning |
|---|---|
| Subject | The column that names each subject. Labels are kept as typed: `001` and `1` are different subjects in a text column, `1` and `1.0` are the same subject in a numeric column, and a text `"1"` differs from the number 1. Subjects are listed in the order of their first complete pair. |
| X, Y | Numeric columns. Subject, X and Y must be three different columns. |
| Confidence interval | **None** (default) or **Subject bootstrap**. |
| Confidence level (%) | Bootstrap only. Strictly between 0 and 100 (default 95). |
| Bootstrap replicates | Bootstrap only. Whole number from 100 to 10,000 (default 2000). |
| Seed | Bootstrap only. Whole number from 0 to 2⁶⁴ − 1 (default 0), read exactly: large seeds are never rounded through a float. |
| Show graph | Draws the points of each subject and its fitted line (default on). |

Level, replicates and seed are greyed out with **None**; they are kept in the recipe but never block the run.

A row counts as a **complete pair** when it has a subject, an X and a Y. A cell you exclude counts as missing. A row with X or Y but no subject is an error on *Subject*, because the value cannot be assigned. A subject with exactly one complete pair stays in the sheets with status **Singleton** and is not in the fit, because a single point carries no within-subject information.

Limits, checked in the dialog before any work: at most 50,000 complete pairs, at most 500 subjects in the fit, and with the bootstrap at most 2,000,000 subjects × replicates.

## How it is computed

With *N* complete pairs in the fit from *S* subjects (each with two or more pairs), X and Y are centred on the mean of each subject. With `u` and `w` the centred values:

```text
slope = Σ u·w / Σ u²
r_rm  = Σ u·w / √(Σ u² · Σ w²)
df    = N − S − 1                  (must be greater than 0)
t     = r_rm · √(df / (1 − r_rm²))  p two-sided from Student's t with df
```

This is the ANCOVA with a subject factor and a common slope; `r_rm` has the sign of the slope. A perfect within-subject fit gives `r = ±1`, `t = ±∞` and `p = 0`. Before centring, every subject is shifted by its own first value and the columns are rescaled, so large offsets between subjects and very small or very large units do not lose digits. If X or Y does not vary within any subject, or varies by less than the precision of its values, the run stops on that field and says so.

The **subject bootstrap** resamples whole subjects with their pairs: `Generator(PCG64(seed))`, and for every replicate `integers(0, S, size=S)` over the subjects in the fit. A replicate whose drawn subjects have no within-subject variation in X or in Y is **Degenerate** and has an empty coefficient. The interval is the two-sided percentile interval with linear interpolation over the valid replicates. If fewer than 80% of the replicates are valid the limits stay empty and *Interval status* gives the reason. The interval is approximate and is labelled so.

Cancel is offered for bootstrap runs; it is checked before every replicate, and the last completed result stays on screen. A change of graph style never repeats the resampling.

## Results

In this order:

1. **Repeated-measures correlation** — one row: N, Subjects, df, Coefficient, Slope, t, p, Lower, Upper, Bootstrap valid, Interval status. With the bootstrap the row also records Confidence level (%), Bootstrap replicates, Seed and Random sequence. Without it, Lower and Upper are empty and Interval status is *Not requested*.
2. **Participants** — one row per subject: Subject, Pairs used, Intercept, Status (**Used**, **Singleton** or **No complete pairs**).
3. **Pairs** — one row per non-empty worksheet row: Subject, Source row (physical position in the worksheet, from 1), X, Y, Fitted, Status (**Used**, **Singleton** or **Missing pair**).
4. **Bootstrap** — only with the bootstrap: Replicate, Coefficient, Status (**Valid** or **Degenerate**).

The graph draws one colour and marker per subject with its fitted line (`rmcorr-fit-1`, `rmcorr-fit-2`, … in SVG), singletons as open grey points, and the coefficient and slope in the legend. Subject labels are shown literally, including `$`, `_` and braces. With more than 40 subjects the legend is shortened and points to the *Participants* sheet.

## Reproducible example

1. Open `tests/data/rmcorr/repeated.csv`.
2. **Analyze… → Data Exploration and Summary → Repeated-measures correlation**.
3. Subject = *Participant*, X = *Day*, Y = *Signal*. On **Options** choose **Subject bootstrap**, 200 replicates, seed 867531.
4. Run. The first sheet shows:

| N | Subjects | df | Coefficient | Slope | t | p | Lower | Upper | Bootstrap valid |
|---|---|---|---|---|---|---|---|---|---|
| 11 | 3 | 7 | 0.783741 | 0.932039 | 3.338632 | 0.012443 | 0.757046 | 0.940019 | 200 |

*Participants* lists A, B, C (Used, intercepts 8.8026, −6.5364, −0.2573) and D (Singleton). In *Pairs* row 12 (A, X = 4, no Y) is a **Missing pair**. The first five bootstrap coefficients are 0.832848, 0.893542, 0.807233, 0.785057, 0.783741. The same seed always gives the same replicates, also after saving and reopening the project.

## What it does not do

No random slopes or mixed model, no Fisher-z or analytic interval, no partial correlation with further covariates, and no wide format: the data must be long, one row per measurement.

## Reference

Bakdash, J. Z., & Marusich, L. R. (2017). Repeated Measures Correlation. *Frontiers in Psychology*, 8, 456. <https://www.frontiersin.org/journals/psychology/articles/10.3389/fpsyg.2017.00456/full>
