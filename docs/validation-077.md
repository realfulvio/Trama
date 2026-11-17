# Trama 0.77.0 beta — verification

Accepted application source: `ec669fe6f7cf7637fc7bdda51b8140dbaed46d56`.
The packaging-only correction `9e06be8171ca43ebbdd6b9de711c4042302846a1`
adds the missing global-profile guide. Later documentation and capture updates
change no application modules. Synthetic data and isolated preferences were used.

| Check | Result |
| --- | --- |
| Complete Linux/Tk 8.6 unit suite | **2,325 PASS**, no skips; 168.431 seconds |
| Complete native Windows unit suite | **2,325 PASS**, no skips; 224.951 seconds |
| Complete Linux GUI smoke, 1920×1080 | **PASS**, screenshots enabled; 639.544 seconds wall time |
| Dedicated Linux global-profile lifecycle | **PASS**, 1024×768; also passed within the complete run |
| Native portable acceptance | **15 PASS**: fourteen GUI flows and ordinary animated startup |
| Native global-profile and existing response flows | **PASS**, 1024×768 and 1920×1080 |
| Source and frozen-code identity | **PASS**, 242 modules plus script entry point; 1,059 tracked source files checked |
| Legacy numerical snapshots | **17 tables identical**, across Wald, weighted and response outputs |

The first complete Linux process terminated without a final report and is not
counted as a pass. A new tracked run completed with exit 0 and a final PASS report.
The first native package check caught the missing guide before GUI acceptance.
The corrected archive preserved all 2,643 original regular members byte for byte
and added that guide; the complete portable acceptance used the corrected archive.
The release report records its digest and verifies that final documentation-only
packaging changes preserve every tested runtime member.

## Joint profiles

Independent design-matrix references cover OLS/WLS intervals at 90/95/99%,
shared/local/all-shared/all-local mappings, fixed common and per-series
coefficients, and globally counted residual degrees of freedom. A separable
nonlinear shared-decay objective provides an independent nonlinear reference.

Additional cases exercise intersected and active bounds, more than eight joint
coordinates, tiny coefficients, common SD rescaling, missing SDs, duplicate source
labels, perfect and all-fixed fits, preflight limits, exhausted work budgets and
cancellation. Limits that cannot be determined remain unavailable with a reason.

The real-widget GUI lifecycle checks worker execution, field errors corrected
in place, canonical EN/IT recipes, separate parameter and response levels,
edit/exclusion recalculation, save/reopen with the graph opened first,
Use Result as Data, CSV/PNG/SVG/PDF and cancellation preserving the last result.
Previous independent parameter-profile, weighting, global IRLS and custom-equation
flows also pass in the native portable. The normal animated startup still passes.

## Scope and limits

Native acceptance used 96 DPI, changed the display temporarily between the two
resolutions and restored its original 1024×768 configuration. Native 125/150% DPI
and exhaustive manual pointer/keyboard use were **not repeated**. Widget-driven
native Windows tests are distinct from Linux/Xvfb tests and from manual use.

The nonlinear profile is local, connected and approximate. Its budgets can leave
an endpoint unresolved; a finite search does not prove an infinite interval.
Relative SDs are held fixed and their uncertainty is not propagated. Response
bands and predictions retain their separate previous inference restrictions.
Passing these cases is not a clinical, regulatory or general statistical certification.

[Feature guide](global-custom-parameter-profiles.md) · [Release notes](release-077.md) ·
[Coverage and remaining work](coverage.md)
