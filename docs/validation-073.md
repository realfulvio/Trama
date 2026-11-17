# Trama 0.73.0 beta — verification

This report covers the assembled application and its Windows x64 portable package. Checks use synthetic data and isolated application preferences. It is software verification, not clinical validation or regulatory certification.

## Completed checks

| Check | Result |
| --- | --- |
| Complete Linux/Tk unit suite | **2,241 PASS**, no skips; 256.061 seconds |
| Complete native Windows unit suite | **2,241 PASS**, no skips; 438.821 seconds |
| Complete Linux GUI regression, Standard | **PASS** |
| Complete Linux GUI regression, Modern | **PASS**, including project reopen and final exports |
| Complete Windows portable GUI regression | **PASS**; 1,347 seconds |
| Native portable target flows at 1024×768 and 1920×1080 | **8/8 PASS**: Modern workspace, summary t-test, summary ANOVA and Q–Q artist styles |
| Independent Q–Q styles verifier | **27/27 PASS** |
| Independent summary ANOVA verifier | **30/30 PASS** |
| Final rebuilt portable, source/frozen-code checks and repeated Modern flows | **PASS**, both native resolutions; mapped frame clears the taskbar |

The complete native GUI run covers the assembled data/analysis/graph workflows, editing, exclusions, recalculation, project persistence, dialogs and exports. The targeted Modern checks exercise both interface languages, a private Figure preview, Inspector preview/cancel/apply, invalid logarithmic limits, source figure size and DPI preservation, linked recalculation and CSV/PNG/SVG/PDF output. Native screenshots were inspected, including the small dialogs.

Integration adds independent high-precision checks for extreme summary precision and Welch pairwise degrees of freedom. It also checks retained-result warnings and isolation of styled Q–Q panels in the Modern preview.

## Artifact traceability

The complete Windows run used runtime `689c6c98e415ae48d081f4b16041903251fa872a`. Its extracted portable ZIP was verified against the source manifest and the compiled application modules before testing. The Linux unit run preceded a smoke-only linked-Info navigation adjustment; the complete Windows unit suite ran after that adjustment.

The final harness revision is `fc3600a2d2706bf233b510df26d859b7198dede8`: it uses a conservative small client height and verifies the actual native window frame against the work area and taskbar. Normal application startup already uses a conservative size. The rebuilt, extracted portable passed this check and the complete dedicated Modern flow at both native resolutions. Compiled-code comparison covered 233 application modules plus the entry point: only `analisi.modern_theme_smoke` changed; the application entry point and all statistical modules match the complete-regression build.

The release supplies SHA-256 checksums and a machine-readable verification summary. Final documentation updates are packaged separately from application code, with byte-for-byte verification that the tested executable and bundled runtime remain unchanged.

## Scope and limits

- Windows desktop modes: **1024×768 and 1920×1080, 96 DPI**. Original display settings were restored after each test batch; no display registry settings were changed.
- Native system scaling **125% and 150% was not tested** in this release cycle. Xvfb and Tk scaling are not substitutes for it.
- GUI tests drive real application widgets and selected native interactions. This is not an exhaustive manual mouse/keyboard usability study.
- An earlier interrupted Linux Modern run was not accepted; the complete replacement run ended with PASS and exit code 0.
- Some result tables, legends and messages remain English. Legacy-project import remains limited to supported content.
- Synthetic fixtures and successful checks do not establish suitability for every scientific, clinical or regulated use.

[Release notes](release-073.md) · [Interface themes](interface-themes.md) · [Feature catalogue](features.md)


## Initial public distribution

The public-source snapshot retains the accepted scientific implementation.
Internal research and planning files are not included. Public packaging is
checked independently; its current checksums identify the published archive.
Historical acceptance figures above describe the tested beta runtime, and are
not a claim that an untested package was exercised.
