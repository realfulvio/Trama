# Trama 0.76.0 beta — verification

Accepted application source: `5ea46296960478b82845125a21b15d1c112e6fc9`.
Synthetic data and isolated preferences were used throughout. Final portable
acceptance and source/package identity are recorded in the release report.

| Check | Result |
| --- | --- |
| Complete Linux/Tk 8.6 unit suite | **2,304 PASS**, no skips; 160.892 seconds |
| Complete native Windows unit suite | **2,304 PASS**, no skips; 216.969 seconds |
| Complete Linux GUI smoke, 1920×1080 | **PASS**, screenshots enabled; source `6a1d578` |
| Final portable acceptance | **11 PASS**: ten GUI flows plus ordinary animated startup |
| Final portable custom-profile flows | **PASS**, 1024×768 and 1920×1080 |
| Final portable ordinary animated startup | **PASS**, eight distinct ring frames at fixed geometry; clean transition and exit |
| Source and frozen-code identity | **PASS**, 238 package modules, startup and application modules, plus script entry point |

The complete Linux GUI run preceded a final correction to the report note for
bound coefficients. That correction distinguishes an unavailable Wald SE from
available profile endpoints; it changes no estimates, limits or interaction
logic. Its regression assertion and the complete unit suites use the final
application source above.

## Custom parameter profiles

Independent references cover exact OLS/WLS t intervals at 90/95/99%, a separable
exponential decay with amplitude eliminated analytically, fixed coefficients,
all-fixed equations, imposed confidence-set boundaries and one-sided profiles
at active bounds. Tests cover common SD factors 1e−100/1e100, coefficient units
of 1e−15, grouped duplicate source indices, incomplete SDs, exact fits, budget
exhaustion and cancellation. Existing unweighted/weighted Wald reports are
compared with captured 0.75 tables; native 0.75 and candidate legacy tables were
also compared bit-for-bit on the same platform. Cross-platform finite-difference
Jacobians have a small numerical tolerance in that historical snapshot only.

Real-dialog tests cover canonical EN/IT selection, field errors, correction in
the same dialog and keeping fitting off the GUI thread. Dedicated lifecycle
checks exercise source edits, exclusions, CSV/PNG/SVG/PDF, Use Result as Data,
graph-first project reopening, cancellation preserving the completed result,
and unchanged legacy recipes.

## Animated startup

A fresh import of the bootstrap loads no scientific stack and opens no implicit
Tk window. Widget tests verify ring movement at fixed panel geometry, idempotent
close, background loading followed by main-thread handoff, and import-error
cleanup. An ordinary, uninstrumented Windows portable launch is separately
witnessed through native windows and changing ring-region pixels, followed by
main-window visibility and a normal close. It is not the `--smoke` path.

The ordinary-launch witness showed the splash after 0.280 seconds and the main window after 2.563 seconds in this one run. The original 1024×768 display mode was restored after the larger-mode checks. Executable and runtime files are preserved byte-for-byte when final product documentation is packaged.

## Limits

- System scaling was 96 DPI. Native 125%/150% and exhaustive manual keyboard or
  mouse use have not been repeated; scripted real widgets are not manual use.
- Complete GUI regression ran on Linux. Windows acceptance combines the complete
  native unit suite, selected portable flows and an ordinary startup witness.
- Local extra-SS profiles are approximate and follow one connected solution.
  Supplied SDs are fixed relative scales; their uncertainty is not propagated.
- Startup timing is a measurement of one test environment, not a benchmark or a
  guaranteed launch duration. No minimum display delay is introduced.
- Some result tables remain English. Software tests are not clinical validation
  or regulatory certification.

[Release details](release-076.md) · [Custom profiles](custom-parameter-profiles.md) ·
[Startup screen](startup-screen.md)
