# Trama 0.80.0 beta — verification

Accepted application source: `74a5d75dff56bde4f2088afa6064033678db8e9e`.
Later documentation, screenshots and the packaging guide allowlist do not change application modules. Synthetic data and isolated preferences were used for the GUI flows.

| Check | Result |
| --- | --- |
| Complete Linux/Tk 8.6 unit suite | **2,421 PASS**, no skips; 199.413 seconds on the immutable candidate |
| Complete native Windows unit suite | **2,421 PASS**, no skips; 529.965 seconds |
| Focused compatibility and clustering tests | **32 PASS**, including six new synthetic import contracts |
| Complete Linux GUI smoke | **PASS**, 1920×1080, screenshots enabled, exit 0 |
| Native portable targeted flows | **4 PASS**: imported clustering in Standard and Modern at 1024×768 and 1920×1080 |
| Complete native portable GUI smoke | **PASS**, 1920×1080, screenshots enabled |
| Ordinary animated startup | **PASS**, real splash animation and transition to the main application |
| Source and frozen-code identity | **PASS**, 252 application modules plus script entry; 1,100 tracked candidate files checked |
| Native desktop restoration | **PASS**, original 1024×768 resolution restored |
| Private compatibility reference checks, Linux and Windows | **PASS**, 88 merges and node pairs, 4,463 stored matrix values, 320 transformed values and saved partitions |

Tested archive SHA256: `19fcaed88df287e22a4464ace7370b59d10218dc7b87ca5df8c550681f238758`.
The release verification asset records the final document-only archive digest and confirms that tested runtime and license members are preserved byte for byte.

## What the new checks cover

Synthetic ZIP import, stable column-identifier mapping, row centering before dual-axis clustering, counts and uncut trees, selected distance/cophenetic reports, lower-triangle matrices, missing rows, malformed or unsupported metadata, live source changes and exclusions, native parameter edits, saved-snapshot independence, graph-style persistence, `.alab` reopening and CSV/PNG/SVG/PDF export. The targeted desktop flow runs in English and Italian with the approved Standard and Modern themes.

Independent small-matrix fixtures specify the transformed values and merge distances directly. Two external compatibility examples are checked privately on both platforms; they are not distributed. The largest observed merge-distance discrepancy in those examples is below 4×10⁻¹⁵. These checks do not establish every external recipe or every graph setting.

## Scope and limits

Native checks use **96 DPI**. Native Windows 125%/150% scaling and exhaustive manual mouse/keyboard acceptance were **NOT repeated**. GUI scripts operate real widgets and generate events; they are not an exhaustive manual acceptance. Some existing result headings and messages remain in English.

The new converter handles the documented hierarchical ZIP metadata. Native figures use Trama's presentation; complete original drawing fidelity, additional cut methods and arbitrary external-format round trips are not claimed. Additional saved graph views may remain unavailable, with import notices. Saved snapshots remain independent of native recalculation. See the [compatibility guide](hierarchical-import.md).

No project-format migration is introduced by this converter. Existing result-input chains and their `.alab` format 3 support remain available. The dual-Y opposite-label overlap limitation remains documented in the axis guide.

All releases remain beta; complete feature parity is not claimed.
