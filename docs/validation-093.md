# Trama 0.93.0 beta verification

Application source `1279da085e0635e6e40f05fb8ce0866cd69375c3`.

| Check | Result |
| --- | --- |
| Linux unit suite | 2,836 passed |
| Native Windows unit suite | 2,835 passed, one skipped because the account cannot create symbolic links |
| Linux desktop | Complete smoke at 1920×1080 passed |
| Native Windows portable | 14 checks passed, including both themes at 1024×768 and 1920×1080, complete smoke and animated startup |
| Frozen application | 285 modules verified against source, plus the executable entry point |
| Original desktop resolution | Restored |

The linked-analysis comparison imported 178 observations. At k=3 the within-cluster sum of squares was 1270.749115311807. The three diagnostic panels matched the reported metric series. The two-analysis dependency survived saving and reopening an .alab project. Editing the original worksheet recomputed the PCA eigenvalue while preserving the saved result snapshot. Per-k partitions and Gap simulations can vary across implementations.

Windows GUI checks drove the native application programmatically at 96 DPI. Captures use synthetic data. The tested ZIP SHA256 is `4134aff4ccecceee189c9a8291cc5753c3264513846155367368856d9d8bb1c4`. The release manifest also records the published ZIP digest and byte comparison of the application members.
