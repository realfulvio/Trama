# Heat-map integration acceptance

13 November 2026. Application code `9566dacdca09c0a9e7e10003bb08a0c86f8560da`. Version remains 0.72.0 beta; the published archive has not been replaced. Subsequent changes in this acceptance commit are documentation only.

The review corrected the horizontal color-bar locator, category-editor scrolling and initial focus after mapping. Regression tests reproduce modal-grab and focus initialization. Clipboard fixtures clear old formats before an external Windows Forms process supplies data; external read-back, values and individual timeouts remain unchanged.

| Check | Result |
| --- | --- |
| Full Linux unit suite | 1919 PASS, no skips, 474.266 s |
| Full native Windows unit suite | 1919 PASS, no skips, 930.675 s |
| Package verifier | PASS on Linux and Windows |
| Focused heat-map/modal tests | 52 PASS |
| Full Linux GUI smoke | PASS |
| Fresh extracted Windows portable, heat-map smoke | PASS at 1024×768 and 1920×1080 |
| Same portable, complete GUI smoke | PASS |
| Native clipboard smoke | PASS, blanks, decimals, external read-back, project round trip and grid growth |
| Source-byte manifest and embedded frozen-code checks | PASS, all 958 source files match |
| ZIP CRC and transferred-byte digest | PASS |
| Original display restoration | PASS, 1024×768, 96 DPI |

Portable: 102,635,002 bytes, SHA-256 `866a1f899676962e86638b0bf4c188dc5202fc88ac3bea104891518e8fdae200`. Source archive SHA-256 `6101be7459ddee21c0fc30176e9a9dcae98eff9776c5e348fecf3577f538cf76`. Machine-readable results: [validation-heatmap-088.json](validation-heatmap-088.json).

The full native portable smoke outlasted its external supervisor's 20-minute total budget while continuing to make progress. That supervisor was detached before its deadline; the original application process continued unchanged and wrote PASS. No individual assertion, calculation timeout or clipboard timeout was relaxed. Temporary test tasks were removed after restoration.

The smoke controls real Tk widgets programmatically. Native captures were inspected; manual mouse/keyboard usability and native 125%/150% DPI are **not tested** in this acceptance. Dense explicit color-bar ticks can crowd compact maps; automatic ticks or a larger interval remain available.

