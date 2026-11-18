# Competing risks

Choose **Survival Analysis → Competing risks** (Italian: *Analisi di sopravvivenza → Rischi competitivi*) when a subject can end in one of several ways and one of them prevents the others. A patient who dies of another cause can no longer relapse; a device that is returned can no longer fail in service. The question the analysis answers is: **how likely is cause *k* to have happened by time *t*, while the other causes were also at work?**

The answer is the **cumulative incidence** of each cause, estimated with the Aalen–Johansen estimator, with an optional **Gray test** that compares groups. Kaplan–Meier and Cox regression are unchanged and keep their recipes.

## Why not 1 − Kaplan–Meier

Kaplan–Meier answers a different question: what would happen if the competing causes did not exist. It treats a competing event as a censoring and therefore assumes the subject would have gone on to experience cause *k* in the same way as the others still at risk. In the presence of a real competing event that is not true, and 1 − KM **overestimates** the probability of cause *k*; with several causes the 1 − KM curves can add up to more than 1. The cumulative incidence uses the probability of being event-free just before *t* to weigh every cause, so the cause-specific curves and the event-free curve always add up to 1.

The two agree only when there is a single cause. The 8-subject example `tests/data/competing_risks/ties.csv` (columns *Time* and *Status*; 0 = censored, 1 and 2 = two causes) shows the gap for cause 1:

| Time | At risk | 1 − KM (cause 2 treated as censored) | Cumulative incidence, cause 1 |
|---|---|---|---|
| 1 | 7 | 0.1429 | 0.1429 |
| 2 | 4 | 0.3571 | 0.3214 |
| 3 to 4 | 3, 2 | 0.3571 | 0.3214 |
| 5 | 1 | 1.0000 | 0.6786 |

At time 5 the last subject experiences cause 1, so 1 − KM jumps to 1: it ignores that a subject has already ended with cause 2 at time 3. The cumulative incidence of cause 1 stops at 0.6786 because 0.3214 of the subjects ended with cause 2.

## Choices

| Field | Meaning |
|---|---|
| Time | Numeric column of times of 0 or more. |
| Status | The column that says how each subject ended. Whole-number codes or text, one kind per column; booleans, complex numbers and a mix of numbers and text are refused. |
| Group | Optional. Up to 12 groups, compared by the Gray test; without it the single series is called *All*. |
| Censor code | The status of a subject who did not experience any cause (default `0`). |
| Event codes | One code per line, from 1 to 6, in the order of the tables. A cause that never occurs is allowed and has a zero curve. A code is read as typed: for a text column the spaces count; for a numeric column `1`, `1.0` and `01` are the same code. The censor code and every event code must differ. |
| Times | Optional. Times at which the estimates are also reported (up to 200), one per line, a decimal comma accepted. They may repeat, be unsorted or fall beyond the follow-up of a group. |
| Confidence level (%) | Pointwise Wald interval of the cumulative incidence, truncated to [0, 1] (default 95). |
| Gray tests | **Off**, **Omnibus** (all groups at once, for each cause) or **Omnibus and pairwise** (every pair of groups too, with the Holm correction inside each cause). |
| Graph | **Selected cause** (the cause chosen in *Graph cause*, empty meaning the first) or **All causes** (colour is the group, dash is the cause). With more than 12 group × cause lines the graph is split into one panel per cause with a shared legend. |
| Display | **Fraction** or **Percent**. Percent changes the axis and the bands of the graph only; the sheets are always fractions. |
| Show confidence bands | Draws the pointwise band along the step; the band stops where the interval is missing. |

A row is used only when it has a value for every role you chose (time, status and group); a cell you exclude counts as missing. The *Settings* sheet reports how many rows were complete and how many were omitted.

## How it is computed

For each group the outcomes are grouped by distinct time. With `Y(t)` the number of subjects whose observed time is at least `t` (a censoring at `t` still counts as at risk), `d_k(t)` the events of cause *k* and `d(t) = Σ d_k(t)`:

```text
F_k(t) = F_k(t−) + S(t−) · d_k(t) / Y(t)
S(t)   = S(t−) · (1 − d(t) / Y(t))
```

Curves are right-continuous; a time with only censorings does not create a jump. The variance is the delta-method variance of Aalen with the hypergeometric tie correction, in the convention of `cmprsk::cuminc`: it is evaluated at the times of cause *k* and carried to the times in between, and is zero before the first event of the cause.

The **Gray test** is the *k*-sample test of the subdistribution hazard, `rho = 0`, not stratified, referred to a chi-square with *G* − 1 degrees of freedom. It is calculated with a linear system, never with a pseudo-inverse. When the data cannot support it, the cell says **Unavailable** with the reason: a single group, a cause without events, a group without the cause, or a singular covariance. The omnibus p values are raw. The pairwise p values are adjusted with Holm, only over the pairs that are available and separately for each cause.

Reference values come from `cmprsk` 2.2-12 on the four fixtures of the package and on about 11,500 random datasets with ties, up to five groups and three causes; they live in `tests/data/competing_risks` and are never read by the program itself.

## Results

In this order:

1. **Cumulative incidence** — one row per group, observed time and declared cause: At risk, Cause events, All events, Censored, Event-free, CIF, Variance, CI lower, CI upper.
2. **Time estimates** — only when *Times* is filled: one row per group, requested time and cause, with Status **OK**, **CI unavailable** or **Beyond follow-up** (estimate, variance and interval empty after the last follow-up of the group).
3. **Gray tests** and **Gray pairwise** — only when requested; the pairwise sheet has Adjusted p and keeps its columns even when there are fewer than two groups.
4. **Settings** — complete and omitted rows, groups, causes, level, variance, tie and multiplicity rules, and what is not included.

**Use result as data** works on every sheet and **Graph settings…** on the graph page reopens the Graph page of the dialog.

## Limits

100,000 rows, 12 groups, 1 to 6 causes, 200 requested times, 200,000 rows in the curve sheet, and a work budget for the Gray tests of 30 million units (groups² × distinct times × causes, summed over the tests asked). A request over a limit is refused before any calculation, on the field that brings it back in budget: Time (round the times), Event codes, Group or Gray tests (use Omnibus only). A Gray calculation has a **Cancel** button; cancelling keeps the last completed result.

## Errors and recovery

Every error names its field and keeps the dialog open with what you typed: a repeated or empty code, a code equal to the censor code, a status that is neither the censor code nor an event code (with the first source row), a negative time, a drawn cause that is not an event code. A worksheet edit that makes a saved analysis impossible, for instance a new status code, keeps the last good result, marks it as out of date, and reopens the dialog on the field to correct.

## What it is not

Not included: Fine–Gray regression, recurrent events, delayed entry, weights, stratified Gray tests and simultaneous confidence bands. The intervals are pointwise.
