# Trama 0.78.0 beta — verification

Accepted application source: `9ff8737da3e299eb9dfe9bebb2f2b12f285c37f5`.
Subsequent documentation, screenshots and package-documentation updates change no application modules. Synthetic data and isolated preferences were used.

| Check | Result |
| --- | --- |
| Complete Linux/Tk 8.6 unit suite | **2,382 PASS**, no skips; 186.930 seconds |
| Complete native Windows unit suite | **2,382 PASS**, no skips; 235.152 seconds |
| Complete Linux GUI smoke | **PASS**, 1920×1080, screenshots enabled, exit 0 |
| Independent FDR packet verifier | **56/56 PASS** |
| Independent axis-guide packet verifier | **12/12 PASS** |
| Native portable targeted flows | **4 PASS**: FDR and axis-guide lifecycles at 1024×768 and 1920×1080 |
| Complete native portable GUI smoke | **PASS**, 1920×1080, screenshots enabled |
| Ordinary animated startup | **PASS**, real splash and main-window transition |
| Source and frozen-code identity | **PASS**, 247 modules plus script entry; 1,078 tracked source files checked |
| Native desktop restoration | **PASS**, original resolution restored after acceptance |

The tested archive SHA256 is `b6f92b6da187da94f6ce88708d95b7a7c10db714f6e1e3905fce92380d5b7760`.
The release verification asset records the final document-only archive digest and confirms that all tested runtime and license members are preserved byte for byte.

The first regression attempt exposed a stale-warning helper dependency in legacy tests and an existing GUI wait that did not enter Tk's real main loop. Both were corrected; final complete runs above passed. An interrupted earlier GUI run is not counted.

## Scope and remaining limits

The FDR lifecycle covers validation and correction in the same dialog, source edits and exclusions, recovery cancellation, stale-result export protection, recipes, round trips, derived data, layouts and CSV/PNG/SVG/PDF exports. Axis checks cover primary linear/log axes, literal labels, dynamic ticks, dual-Y preservation, transactional preview/apply/cancel, saved projects and vector exports. Additional regression tests keep out-of-view opposite ticks out of tight export bounds and prevent guides from expanding data autoscale limits.

Native tests used 96 DPI. Native Windows 125%/150% display scaling and exhaustive manual mouse/keyboard interaction were **NOT repeated**; the real GUI was driven programmatically. Opposite-side guide labels may overlap right-Y labels and titles in dual-axis plots; see the axis guide. Complete format or feature parity is not claimed. All releases remain beta.
