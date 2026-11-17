# TOST integration validation — PR 86

Validated on 12 November 2026. The reviewed application tree is `d486ff352964a436a5102850c579352d94ee2c2e` (code commit `4f5b3f0c7b906dbfa180cbcd109224b96d4603d5`). The tested integration archive has the same tree; the validation documentation was added afterwards. Version remains 0.71.0 beta; this records integration acceptance rather than a new release.

The integration retains One-sample, Paired, Student and Welch TOST, explicit margins, four result sheets, a linked figure and the EN/IT analysis dialog. Existing ordinary, paired and lognormal t-test snapshots pass unchanged.

Review added seven regression tests and corrected four numerical issues:

- Centering before averaging preserves small differences around a large common offset. Representable variation is retained instead of being discarded by a threshold proportional to the input magnitude.
- Each independent sample retains its own variance scale; Welch degrees of freedom use normalized variance contributions.
- A tail quantile preserves finite intervals for small Alpha. A subtraction that overflows before division no longer rejects a representable t statistic.
- Extreme-unit figures use an explicit display multiplier, preserving original table and legend values while avoiding renderer overflow.

| Check | Linux | Windows 11 x64 |
| --- | --- | --- |
| Complete unittest suite | 1,870 PASS, no skips | 1,870 PASS, no skips |
| Complete application smoke | PASS, Tk under Xvfb, 1920×1080 | PASS, built portable, 1920×1200 desktop |
| Dedicated TOST smoke | PASS, 1024×768 | PASS, native 1024×768 and 1920×1200 |
| Save/reopen, edit/exclusion recalculation, Inspector, Format Graph, Use Result as Data, CSV/SVG/PNG/PDF | PASS | PASS |
| Whitespace/diff checks | PASS | — |

The smoke drives real Tk widgets programmatically. The Windows dialog and figure captures were visually inspected; this is not a manual mouse/keyboard usability study. Initial occluded Windows captures were discarded and the dedicated runs repeated in the foreground. Display resolution and pre-existing window state were restored. The new dialog was not separately retested at native 125%/150% scaling.

The source archive SHA-256 is `9c09a85d9ce9e588fc215de57cb4753069e5b0b85fb16cd9eecc85a070847ec4`. The tested Windows ZIP SHA-256 is `ff438a398da3003ec63d67a8a3fcb2a9a1db7320729a0606bfc1993435baf3b8`.

Known limits: result tables and plot text remain English; only the dialog and its validation are localized. An invalid analysis after a source edit follows the existing application behavior for stale results. These remain separate work items.

