# Synthetic custom-profile references

legacy-075.json records the four public dispatcher tables for the synthetic X/Y/SD fixture in tests/test_custom_parameter_profiles.py, produced by unmodified Trama 0.75 runtime e6064e4a540c2fe1e67ba9828fe4195f061e21a5. No external dataset or product artifact is included.

New interval references are independent OLS/WLS t intervals and a separable exponential regression, eliminating amplitude analytically and searching only the decay rate. Fixed coefficients reduce the free parameter count. Source-order and cancellation checks exercise the actual dispatcher.
