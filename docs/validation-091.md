# Trama 0.91.0 beta verification

Application source `47c18925b373d83e2335e4a72f523eae3b7857c6`.

| Check | Result |
| --- | --- |
| Linux unit suite | 2,720 passed |
| Native Windows unit suite | 2,719 passed, one skipped because the account cannot create symbolic links |
| Saved PCA | 178 observations, 13 variables, three retained components and 1,000 parallel-analysis replicates |
| Linux desktop | Complete smoke at 1920×1080 passed |
| Native Windows portable | Six checks passed, including both themes at 1024×768 and 1920×1080, complete smoke and animated startup |
| Frozen application | 278 Python modules and entry point checked against source |
| Original desktop resolution | Restored |

Saved eigenvalues and scores matched the recalculation after sign alignment, with maximum absolute error below 2e-12. The saved selection parameters were recovered. Trama generates its own parallel-analysis samples from the recovered seed.

Windows checks drove the application programmatically at 96 DPI. The public figure was exported from a synthetic project. The tested ZIP SHA256 is `86531020b6cab14d3b206e28801f11f533bc3da91986b6716a74ecfd71c5a5f2`. The published manifest records the final ZIP digest and the byte comparison of application members.
