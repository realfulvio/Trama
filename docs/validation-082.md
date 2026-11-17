# Trama 0.82.0 beta — verification

Accepted source `202154c218e2b5765b493a0ad75c514a2ef215ee`. Synthetic data and isolated application preferences were used.

| Check | Result |
| --- | --- |
| Linux/Tk 8.6 unit suite | **2,521 PASS** |
| Native Windows unit suite | **2,520 PASS**, one capability skip out of 2,521 |
| Original legend contract | **13/13 PASS** on Linux and Windows |
| Legacy figures | **6 PASS**, pixel-identical under Agg, including labels, dimensions and bounds |
| Linux GUI | **PASS** at 1024×768 and 1600×1000, complete regression **PASS** at 1920×1080 |
| Windows portable | **4 PASS**, Standard and Modern starting preferences at 1024×768 and 1920×1080 |
| Complete Windows portable GUI regression | **PASS** at 1920×1080 |
| Ordinary portable startup and animated splash | **PASS** |
| Source and frozen-code identity | **PASS**, 262 modules plus main entry point |
| Original desktop resolution restored | **PASS** |

The legend flow covers preview, cancellation, application, live recalculation, project reopening, independent Q–Q labels, vector export and layouts. The GUI checks use generated events on real native widgets with isolated preferences at **96 DPI**. Manual mouse and keyboard acceptance and system scaling at 125% or 150% remain outside this run.

The Windows unit skip concerns symbolic-link creation under the test account (WinError 1314). The tested ZIP digest is `ca8d8541169e73b69c940975623f311805b31bbc6b1bb48061b4f775aae833cc`. The release verification asset records the final archive digest and confirms that the runtime and license members match the tested ZIP byte for byte.
