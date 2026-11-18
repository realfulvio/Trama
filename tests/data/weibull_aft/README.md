# Weibull AFT regression fixtures

`follow-up.csv` and `expected.json` come unchanged from the synthetic package of the 0.93 assignment
(16 cases, 10 events, 6 censored; the second group repeats the times of the first, so the time ratio is exactly 2).
`expected.json` holds the frozen profile-likelihood reference: at a fixed shape k the group scale is
`(sum t^k / d_g)^(1/k)`, and the estimated shape solves the scalar profile score (Brent's method).
