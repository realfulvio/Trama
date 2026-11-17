# Trama 0.84.0 beta verification

Application source `d4c1c4fc13252eadc11b8c5b78bd7714b47db982`. Published captures are from genuine Windows widgets driven with synthetic data.

| Check | Result |
| --- | --- |
| Linux/Tk 8.6 unit suite | 2,602 passed |
| Native Windows unit suite | 2,601 passed, 1 skipped |
| Hierarchical styling contract | 20/20 passed |
| Linux GUI | Complete regression at 1920×1080 passed |
| Windows interactive portable | Eight checks passed, including both starting themes, both sizes, hierarchy import, complete regression and animated startup |
| Frozen application | 266 modules and entry point verified against source |
| Original desktop resolution | Restored |

The Windows account lacked permission to create a symbolic link, so one check was skipped.

Windows checks used 1024×768 and 1920×1080 screens, native 96 DPI and isolated preferences. The original-format reference was checked separately on the verified Windows application source. Controls were driven programmatically.

The tested ZIP SHA256 is `1ddf5637d39a7ad9ac2926f2da6920c297f94178e080de21cdb62ce3d076f38a`. The published manifest records the final archive digest and the comparison of all non-document archive members.
