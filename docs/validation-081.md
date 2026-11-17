# Trama 0.81.0 beta — verification

Accepted application source: `aa88a6e0a6015338f99b3c4ca4b66fe9a7dcf720`. Later product documentation and screenshots do not change application modules. Synthetic data and isolated preferences were used.

| Check | Result |
| --- | --- |
| Complete Linux/Tk 8.6 unit suite | **2,494 PASS**, no skips; 187.016 seconds |
| Complete native Windows unit suite | **2,493 PASS**, one capability skip out of 2,494; 454.969 seconds |
| Original family-workflow packet | **29/29 PASS** on Linux and Windows |
| Original variance-ratio packet | **15/15 PASS** on Linux and Windows |
| Cross-feature copy/edit/export/reopen | **PASS** on both platforms; original ratio 4, independent modified copy and reopened ratio 9 |
| Complete Linux GUI regression | **PASS**, 1920×1080; updated family fixture also passes separately in Standard and Modern, English and Italian |
| Native portable targeted workflows | **8 PASS**: families and variance comparison, Standard/Modern, 1024×768/1920×1080, English and Italian |
| Complete native portable GUI regression | **PASS**, 1920×1080 |
| Ordinary animated startup | **PASS**, real splash and transition to the main application |
| Source and frozen-code identity | **PASS**, 259 application modules plus entry point; 1,144 tracked candidate files |
| Desktop restoration | **PASS**, original resolution restored |

Tested ZIP SHA256: `ef4bf61d6e81071cfd4c27e0133ab15e6f512d7428d34e241fe63971df5262b2`. The release verification asset records the final documentation-only archive digest and byte-for-byte preservation of the tested runtime and license members.

## Scope and limits

Native Windows checks use **96 DPI**. Native 125%/150% system scaling and exhaustive manual mouse/keyboard acceptance were **NOT repeated**. Scripts operate real widgets and generated events. Some result headings remain in English.

The Windows test account cannot create symbolic links (WinError 1314). That single unit case is explicitly skipped, and the GUI report records the corresponding branch as unavailable. Actual hard-link and normalized-path overwrite protection passes on Windows; actual symbolic-link and hard-link protection passes on Linux. No account privilege changes are required for the application.

The native run found and corrected the same unsupported symbolic-link fixture assumption in the unit and GUI harnesses. Two independent numerical regression cases were reproduced before fixing variance scaling and extreme-confidence tails. The original packet oracles were not weakened.

Family copies preserve supported dependency links, styles, formulas, exclusions and Info values; shared external layout panels are declared in the preview. This does not broaden external-format support or promise complete original drawing fidelity. Analysis labels are optional metadata; existing project-format versions remain unchanged.

All releases remain beta. Complete feature parity, clinical validation and regulatory certification are not claimed.
