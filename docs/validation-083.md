# Trama 0.83.0 beta — verification

The accepted runtime source is `dd3d6ad7fd0eb71e55d11055d2987931c9e7b198`. Product captures use synthetic data and isolated preferences.

| Check | Result |
| --- | --- |
| Linux/Tk 8.6 unit suite | **2,561 PASS** |
| Native Windows unit suite | **2,560 PASS**, one capability skip (WinError 1314) |
| Conditional equations contract | **32/32 PASS** on both platforms |
| Arithmetic project compatibility | **9** existing recipes with byte-identical rendered plots and equivalent CSV output for **58** tables |
| Hierarchical saved-example comparison | **88** merge rows and **42** WCSS values |
| Linux GUI | **PASS** for both workflows at 1024×768; full combined-source regression **PASS** at 1920×1080 |
| Windows portable | **PASS**, conditional dialogs at 1024×768 and 1920×1080 in Standard and Modern starting preferences, hierarchical import at 1920×1080 |
| Full Windows GUI and ordinary startup | **PASS**, including the animated loading screen |
| Frozen code compared with source | **PASS**, 263 modules and main entry point |
| Original desktop resolution restored | **PASS** |

Conditional results cover fixed thresholds, branch labels, fitted curves and bands, exports and saved project reopening. Hierarchical reports cover ordered merges, edit and recalculation, and within-cluster sums of squares. Saved-example numerical comparisons are separate from the native GUI smoke. The Windows checks drive real widgets at **96 DPI**. Manual input and system display scaling at 125% and 150% were outside this run.

Tested archive SHA256 `576929651c726831d7f64039eae9cb61149c1c77d16b92e74e782929710db4b5`. The verification asset records the final download digest and the comparison of the archived runtime members.
