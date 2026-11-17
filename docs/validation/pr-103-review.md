# Lognormal ANOVA integration review

The candidate is based on PR #103 (`802ecbe`). During review, positive finite
subnormal values were incorrectly classified as unrepresentable when converting
log means and log contrasts back to the original scale. The previous lower
cutoff used the smallest **normal** float, which excludes representable values
below that threshold.

The conversion now evaluates the exponential and retains every finite positive
result. Actual overflow or rounding to zero still produces a missing value with
the existing explanation; finite log-scale estimates remain available.

A dispatcher regression covers geometric means around `1e-310` and a Tukey ratio
with positive subnormal confidence limits. It failed on the submitted code and
passed after the correction. All 11 lognormal ANOVA unit tests passed on Linux,
including the prior extreme-scale cases and the legacy Normal recipes.

Combined acceptance is complete: see [the scoped acceptance record](pr-103-105.md)
for the full Linux run, native affected-module tests, ten extracted-portable GUI
workflows and the preceding full Windows baseline. Version and release status
are unchanged.

