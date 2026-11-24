# Interaction plot

Choose **New Graph… → Interaction plot** (IT: *Nuovo grafico… → Grafico d'interazione*) or **Analyze → Graphing → Interaction plot** to plot the **observed cell means** of a numeric response across every combination of two categorical factors, with one line and distinct marker per series and selectable cellwise error bars.

This plot is a descriptive summary of observed data. It is designed to inspect main patterns and potential crossings before fitting an ANOVA, including unbalanced designs and missing factor combinations.

## Fields

| Field | Role and behavior |
|---|---|
| **Response** (`Risposta`) | Numeric measurement column (required, distinct from the factors). |
| **X factor** (`Fattore X`) | Categorical factor shown along the horizontal axis (at least two levels). |
| **Series factor** (`Fattore delle serie`) | Categorical grouping factor; each level is drawn as its own series (at least two levels). |
| **Error bars** (`Barre d'errore`) | **None** (*Nessuna*), **SD** (*DS*), **SEM**, or **Confidence interval** (*IC della media*, default). |
| **Confidence level** (`Livello di confidenza`) | Percentage strictly between `0` and `100` (default `95`); shown and validated only when **Confidence interval** is selected. |

All three column roles (`Response`, `X factor`, `Series factor`) must be existing and distinct columns. If a role is missing or duplicated, Trama highlights the field to correct while keeping your other selections intact.

## Example

Starting from a long-format table with columns `Dose`, `Group`, and `Response`:

| Dose | Group | Response |
|---|---|---|
| Low | Control $ | 2, 4, 6 |
| Low | Treatment | 6, 10 |
| Mid | Control $ | 5, 7 |
| Mid | Treatment | *(empty)* |
| High | Control $ | 9 |
| High | Treatment | 12, 12 |

- **Low × Control $** (`n = 3`): `Mean = 4.0`, sample `SD = 2.0`, `SEM = 1.1547`, 95% CI = `[−0.9683, 8.9683]`.
- **Mid × Treatment** (`n = 0`): empty cell; all numeric statistics remain empty and the connecting line between `Low` and `High` in the `Treatment` series is broken across `Mid`.
- **High × Control $** (`n = 1`): singleton cell; `Mean = 9.0` is plotted as a marker without error bars (`SD`, `SEM`, `Lower`, `Upper` are empty).
- **High × Treatment** (`n = 2`, constant `12, 12`): `Mean = 12.0`, `SD = 0.0`, `SEM = 0.0`, `Lower = Upper = 12.0`.

## Meaning of the error bars

Every error bar belongs to a **single cell** `(X level, Series)` computed from all valid replicates in that cell:

- **None**: plots cell means only; `Lower` and `Upper` remain empty in the **Interaction cells** sheet.
- **SD**: sample standard deviation with denominator `n − 1`; bars span `Mean ± SD`.
- **SEM**: `SD / √n`; bars span `Mean ± SEM`.
- **Confidence interval**: pointwise Student-*t* interval for that cell mean using `n − 1` degrees of freedom: `Mean ± t_{1 − α/2, n − 1} · SEM`, where `α = 1 − level / 100`.

## Category order and typed levels

- Levels for **X factor** and **Series factor** are collected from rows where **both factors are present** (before filtering out invalid `Response` values), in order of **first occurrence**.
- If the worksheet defines an explicit **category order** for either column, saved levels appear first in that order and any remaining levels follow in first-occurrence order.
- Identities preserve types (`1` and `"1"` stay distinct). If two distinct levels produce the same text label, only the colliding labels are disambiguated stably.
- Text strings in axis ticks, axis titles, and legend entries (including characters such as `$`) are always drawn literally rather than interpreted as math markup.

## Effect of missing, excluded, and non-numeric rows

- Trama passes the filtered worksheet frame so excluded cells behave like missing entries.
- Rows with a missing/blank factor or a non-numeric or non-finite `Response` (`inf`, `bad`, blank) are discarded from the statistics and counted in `Rows discarded` inside **Settings**.
- Valid decimal-comma strings (such as `2,5`) follow Trama's standard numeric conversion.
- Cells with `n = 0` leave all statistics empty (exported as blank cells in CSV) and interrupt the connecting line of their series; cells with `n = 1` show the mean marker with no error bar.

## Descriptive design note

**Interaction plot** reports **observed cell means only**. It does **not** fit a statistical model, does not compute *p*-values or model-based estimated marginal means, applies no multiplicity correction across cells, and performs no pairing or repeated-measures adjustment. Error bars assume independent observations within each cell.
