# Trama 0.75.0 beta — verification

The accepted runtime source is `e6064e4a540c2fe1e67ba9828fe4195f061e21a5`. Tests use synthetic data and isolated preferences. Release documentation and screenshots are packaged after runtime acceptance, with byte-for-byte checks that executable and runtime members remain unchanged.

| Check | Result |
| --- | --- |
| Complete Linux/Tk 8.6 unit suite | **2,280 PASS**, no skips; 165.545 seconds |
| Complete native Windows unit suite | **2,280 PASS**, no skips; 214.215 seconds |
| Complete Linux GUI smoke, 1920×1080 | **PASS**, screenshots enabled |
| Windows portable weighted-parameter flow | **PASS**, 1024×768 and 1920×1080 |
| Windows portable unweighted-parameter flow | **PASS**, 1024×768 and 1920×1080 |
| Windows portable existing nonlinear-band flow | **PASS**, 1024×768 |
| Windows portable observed-weight and global-IRLS flows | **PASS**, both |
| Tracked source and frozen code verification | **PASS**, 236 application modules plus entry point match the accepted source |

Sixteen tests were added in this increment. The focused parameter suite contains 39 tests. Independent references cover analytic WLS intervals at 90/95/99%, a separate IRLS fixed-point calculation, a deliberately frozen scale vector different from the fitted curve, and weighted exponential-decay profiling with analytically eliminated nuisance coefficients. Cases include negative responses, SD common-unit factors 1e−100 and 1e100, duplicate source indices, incomplete observations, grouping, invalid stored scales and unchanged legacy Wald/95 reports.

The dedicated native portable flow exercises invalid SD selection and correction in the same dialog, SD edits, source exclusions, observed/fitted-weight switches, canonical EN/IT project persistence, graph-first reopening, CSV/PNG/SVG/PDF, Use Result as Data, cancellation preserving the completed result, and a legacy weighted recipe. Native screenshots were inspected. The original 1024×768 display mode was restored after the larger-mode checks; no display registry settings were changed.

## Scope and limits

- Windows system scaling was **96 DPI**. Native 125%/150% and an exhaustive manual keyboard/mouse study were not tested. GUI automation drives real widgets; Xvfb is not Windows.
- Complete GUI regression ran on Linux. Native portable acceptance covered the seven flows listed above, alongside the complete native unit suite.
- Weighted inference is conditional on the confirmed observation scales. It does not propagate uncertainty from estimating the weights. Supplied SDs define relative error scales, not known absolute variances.
- Profiles follow a local solution, not all disconnected branches. Numeric and refitting budgets can leave an endpoint unavailable; no substitute unweighted or Wald endpoint is used.
- Some tables and messages remain English. Successful software verification does not establish clinical, regulatory or every scientific use-case suitability.

[Release details](release-075.md) · [Parameter interval guide](nonlinear-parameter-intervals.md)
