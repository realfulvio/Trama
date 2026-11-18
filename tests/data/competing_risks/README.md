# Competing-risks references

Numbers here come from outside Trama and are never read by production code.

* `ties.csv`, `cohorts.csv`, `status-text.csv`, `no-events.csv`, `legacy-km.csv`, `expected.json`: the acceptance
  fixtures of the competing-risks handoff. `expected.json` was produced with `cmprsk::cuminc` 2.2-12
  (`rho = 0`, no strata): curve counts, estimates, variances, Gray statistics and Holm-adjusted pairwise p values.
* `cmprsk-random.json`: extra datasets (ties, up to five groups and three causes, a rank-deficient covariance,
  a negative tie factor, a group without the cause and a fully censored group) run through the cmprsk 2.2-12
  Fortran routines `cinc` and `crstm`, compiled locally and called as a black box. Each case stores its inputs,
  the right-continuous step functions of every group and cause, and the omnibus and pairwise Gray statistics
  (`null` where cmprsk reports a singular covariance, `-1`).
