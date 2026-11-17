# Trama 0.74.0 beta — verification

The candidate application runtime is `28640d2cd7ca656f70e8500d1e99ecba120e7fcd`. Tests use synthetic data and isolated preferences. Release documentation and screenshots are packaged after runtime acceptance; the final executable and all bundled runtime files are checked byte-for-byte against the accepted portable.

| Check | Result |
| --- | --- |
| Complete Linux/Tk 8.6 unit suite | **2,264 PASS**, no skips; 166.932 seconds |
| Complete native Windows unit suite | **2,264 PASS**, no skips; 211.885 seconds |
| Complete Linux GUI smoke at 1920×1080 | **PASS**, with screenshots enabled |
| Dedicated parameter-interval GUI smoke | **PASS**, Linux at 1024×768 and native Windows portable at 1024×768 and 1920×1080 |
| Existing nonlinear-band GUI smoke | **PASS**, Linux and native Windows portable at 1024×768 |
| Native portable observed-weighting and global-IRLS flows | **PASS** |
| Frozen application code and source identity | **PASS**, 235 application modules and the entry point; tracked source files matched the candidate manifest |

The 23 added tests comprise 18 statistical/edge tests and five real-dialog tests. Independent numerical references include closed-form OLS intervals, an exponential-decay profile with analytically eliminated nuisance coefficients and a 4PL midpoint obtained through separable least squares. Cases cover bounds, non-convergence, budgets, groups, responses, scale changes and cancellation. Additional probes preserve normalized line intervals at response scales 1e−100 and 1e100.

The parameter GUI smoke checks separate parameter and band levels, field errors corrected in the same dialog, canonical EN/IT recipes, graph-first reopening, edits, exclusions, CSV/PNG/SVG/PDF export, Use Result as Data, cancellation retaining the last completed result and legacy table values. Native screenshots were inspected. The original display mode was restored; no display registry settings were changed.

## Limits

- Native Windows system scaling was **96 DPI**; 125% and 150% were not tested. Xvfb is not Windows.
- Tests drive real widgets; this is not an exhaustive manual keyboard/mouse study.
- The complete GUI regression ran on Linux. Windows portable acceptance in this cycle covered the five targeted flows above, alongside the complete native unit suite.
- An earlier Linux/Tk 9 full unit attempt crashed in Tcl/Tk and was not accepted. The replacement Tk 8.6 environment was isolated from system components. An initial missing caption registration failed on both platforms and was corrected before the accepted candidate runs.
- Weighted independent profile intervals remain unsupported; local profiles do not enumerate all disconnected solutions.
- Some result tables and legends remain English. Scientific, clinical or regulated suitability requires appropriate independent review.

[Release details](release-074.md) · [Parameter interval guide](nonlinear-parameter-intervals.md)
