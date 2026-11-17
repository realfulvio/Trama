# Trama 0.79.0 beta — verification

Accepted application source: `36a0060aeaed36f167080715f141d1c3c5c47046`.
Subsequent documentation and screenshot changes do not modify application modules. Synthetic data and isolated preferences were used.

| Check | Result |
| --- | --- |
| Complete Linux/Tk 8.6 unit suite | **2,415 PASS**, no skips; 167.137 seconds |
| Complete native Windows unit suite | **2,415 PASS**, no skips; 248.711 seconds |
| Complete Linux GUI smoke | **PASS**, 1920×1080, screenshots enabled, exit 0; 653 seconds |
| New dependency/project/real-Tk contracts | **33 tests**, included in both complete suites |
| Native portable targeted flows | **4 PASS**: result chains in Standard and Modern at 1024×768 and 1920×1080 |
| Complete native portable GUI smoke | **PASS**, 1920×1080, screenshots enabled |
| Ordinary animated startup | **PASS**, real splash animation and main-window transition |
| Source and frozen-code identity | **PASS**, 251 modules plus script entry; 1,090 tracked source files checked |
| Native desktop restoration | **PASS**, original 1024×768 resolution restored |

The tested archive SHA256 is `88da67a5050fcd3119db2d1ffba14403d7ce48f3de8fa44cffa29aeb6ea2ee32`.
The release verification asset records the final document-only archive digest and confirms that every tested runtime and license member is preserved byte for byte.

## What the new checks cover

Result-table input selection, a transformation → normalization → regression chain, formulas, source edits, cell exclusions and undo, independent result copies, source navigation and transactional replacement, cancellation, superseded worker revisions, parent parameter changes, missing-output repair, cross-table branches, navigator hierarchy, opening a linked layout before its sources, retained stale results and export protection, `.alab` round trips and CSV/PNG/SVG/PDF exports.

The numerical fixture gives slope 4 before a source edit, 3.8 after changing its second response, and 4 when that response is excluded. The worker-order check verifies one call per affected analysis and execution on the analysis worker. Separate tests cover deep iterative dependency traversal, 400 saved recipes, malformed identities, missing sources and combined input/annotation cycles. Format budgets are validation limits, not performance guarantees.

The initial layout check exposed missing source reconstruction on reopening a linked layout; it was corrected. Inspection at 1024×768 exposed a clipped result action, corrected by grouping the result actions into separate rows. A pure test fixture initially used the wrong Layout constructor; that fixture error is not counted as a product defect.

## Scope and limits

Native checks use 96 DPI. Native Windows 125%/150% scaling and exhaustive manual mouse/keyboard interaction were **NOT repeated**. The GUI scripts drive real widgets and intercept expected error prompts; this is not an exhaustive manual acceptance. Some result headings and existing messages remain in English.

Linked projects use `.alab` format 3 and require this version or newer; older builds reject them. Independent copied results remain independent. A failed upstream analysis can leave previous outputs visible but explicitly stale and unavailable for export/reuse until corrected. The existing dual-Y opposite-label overlap limitation remains documented in the axis guide.

Complete format or feature parity is not claimed. All releases remain beta.
