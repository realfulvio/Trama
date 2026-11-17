# Summary t tests — candidate acceptance

This records an unreleased candidate. VERSION remains 0.72.0 beta.

## Functional runtime bcf0d38752cfb1c50389e5c81a6dc744324713cc

- Linux: 2,189 unit tests and complete GUI smoke PASS, plus 120 independent Decimal-based numerical cross-checks over Student/Welch and extreme unit scales.
- Native Windows: 37 focused unit tests PASS; portable build, package and frozen-code checks PASS.
- Native portable: summary t-test and summary ANOVA flows PASS at 1024×768 and 1920×1080, both at 96 DPI; complete GUI smoke PASS. The task ended with result 0, no owned app process remaining, and the original 1024×768/96-DPI display restored.
- Full native unit suite was not repeated for this candidate. GUI flows used real widgets driven programmatically, not a new manual mouse/keyboard acceptance run. Native 125/150% DPI remains untested here.
- Windows evidence ZIP SHA256: `cbddae17a50a35f09c3a533ab1a02521aa6704861cfa530246d578673b2bbc41`.

## Final runtime 6111aabc6f5edb161c93fa5170ff5ac2ce8952f1

This adds six translated numeric-field captions, stronger dialog checks, and a documentation link. Statistics and application execution code are unchanged.

- 37 focused Linux tests and targeted GUI smoke PASS.
- Native Windows portable build/package/frozen-content checks PASS.
- Final portable SHA256: `ec3c3994d3679aee491e1dabc1f7ecdc42fb42d5d7e9ca10fe4591dc52af3d19` (103,369,529 bytes).
- Final build evidence SHA256: `d75ba6bcd6aa54b7615fdc8dad7ea5487795c664ced00e084c38ca6618afe760`.
- Final focused native tests and four targeted portable GUI checks are **pending**. The shared test environment was released to another authorized test job after the previous complete smoke. The earlier full result is not a claim that these final checks ran.

Keep the PR in draft until the pending acceptance and integration are completed. Integrating summary unequal-variance ANOVA must retain this method's explicit option whitelist, pinned Ordinary/None parser settings, and shared dialog guards.

