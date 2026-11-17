# Normal and lognormal distributions

**Normality tests → Distribution** offers **Normal**, **Lognormal**, and **Both**.
Normal remains the default. The four existing tests apply to the logarithms for
lognormality. Missing or excluded cells remain omitted; zero and negative
observations are never discarded to manufacture a lognormal sample. Such a
column receives **Not tested** with a reason, while other columns and the normal
tests remain available.

**Compare distributions**, off by default, adds a comparison sheet with normal
and lognormal maximum-likelihood fits. Both models estimate two parameters. The
normal variance uses N, and the lognormal likelihood includes the change-of-
variable Jacobian. The sheet reports log likelihood, AIC, ΔAIC, and relative
weights normalized across these two candidates. These weights are not p values,
posterior probabilities, or evidence that either model describes the population
well. Constant, nonpositive, or fewer than three observations leave the
comparison unavailable, with a reason; no artificial 50/50 or 100/0 answer is
substituted.

The calculations analytically cancel the common data-unit offset in the weight
comparison. Changing units preserves relative weights within representable
input precision. The additional Log scale parameter stays available when the
raw scale would underflow; the raw cell is blank with a reason instead of a
false zero. Logarithms are centered, using `log1p` for nearby values, so
representable small variations are retained even at very large magnitudes.

## Q–Q plots and compatibility

With **Both**, Q–Q output contains a normal and a lognormal panel for the chosen
variable. Lognormal coordinates contain centered natural logarithms, original
observations, natural log values, and source rows. Settings disclose the common
log offset. The axis labels identify the centered scale; it is not a plot of
untransformed observations. The selected Q–Q variable must have positive values
when a lognormal panel is requested; an error keeps the dialog open on that
field so a different variable or output can be chosen.

The existing normal-only sheets, Q–Q coordinates, reference-line convention,
figure geometry, and numerical tests remain unchanged. Old recipes without
these fields keep their existing behavior. Interface choices and new domain
errors are available in English and Italian; recipes store canonical values.
Result sheets follow the existing English worksheet convention.

