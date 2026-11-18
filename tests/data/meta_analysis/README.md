# Meta-analysis references

Numbers here come from outside Trama and are never read by production code.

* `differences.csv`, `ratios.csv`, `zero-tau.csv`, `expected.json`: the acceptance fixtures of the meta-analysis
  handoff, synthetic. `expected.json` holds the common-effect and Paule–Mandel random-effects results (modified
  Knapp–Hartung, 95%), the prediction intervals, the leave-one-out estimates and the study limits of the ratios.
* `pm-reference.json`: Paule–Mandel τ², pooled estimate and Q(0) for nine extra cases (k = 2 to 60, and units scaled
  by 2^−480 and 2^470), solved with 50-digit arithmetic (mpmath bisection of `Q(τ²) = k − 1`), independent of the
  floating-point code under test.
