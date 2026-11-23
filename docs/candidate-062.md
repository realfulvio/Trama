# TramaStat 0.62.0 — integration and acceptance

Integration after 0.61.0. The validation record below distinguishes the tested code from the final release archive. The validation covers the imported formats and operations listed below.

## Integrated work

- PR #54: pointwise nonlinear confidence and prediction bands. Prediction of a new observation requires an unweighted fit; mean bands can use supported final observed/fitted weights. Unsupported inference retains the fit with an availability explanation.
- PR #55 and #59: asymmetric X/Y errors, distance/end-point inputs, error directions and appearance, and validation that keeps the real dialog open with focus on the failing field.
- PR #56: independent custom-equation parser and bounded least squares, coefficient editor, fixed/free parameters and intervals. Follow-up checks cover common SD rescaling, very small coefficients, nonfinite curve counts and all-zero responses. Expressions are parsed; user expressions are not executed as Python.
- PR #57: explicitly ordered linear trend after ordinary one-way ANOVA, including unequal group sizes, typed group identities and the nonlinear remainder.
- PR #58: exact lower-tail runs diagnostics, replicate lack of fit and an optional raw-residual panel, all consuming the existing fit. Runs and lack-of-fit inference require unweighted fitting.
- PR #60: native line, rectangle and ellipse objects with preview, apply/cancel, duplication, ordering, EN/IT controls, persistence and vector exports. Preserved imported drawings retain their separate original-drawing workflows and are refused by this editor.

Bands, diagnostics and the residual view are tested together, including multiple responses. The combined path does not run a second optimization. Previously saved options without these additions retain their old outputs.

## Integration corrections

The integration preserves all imports, menu methods, translations and smoke hooks. Full GUI testing exposed test interference that was invisible in individual runs: temporary trend projects could exhaust the existing tab limit; a broad diagnostic-note selector also matched the new band note; and the XY round-trip check assumed its analysis was first in the project. These checks now clean up their own temporary projects and identify the relevant widget/recipe precisely.

PCA acceptance checks now verify the eigensystem, reconstruction, orthogonality and the actual canonical sign anchor. A one-ulp backend perturbation reproduces the former false failure. PDF title checks normalize extraction whitespace while still rejecting missing or reordered words. Neither correction changes calculation or rendering behavior.

## Validation

- Linux: 1,436 unit tests passed, no skips; complete Tk smoke passed after integration corrections.
- Independent handoff verifiers: original custom equations 28/28, numerical corrections 11/11 and zero-response corrections 6/6; nonlinear bands 14/14; trend ANOVA, fit diagnostics and XY errors passed; corrected native-shape fixtures 9/9.
- Windows: the final 0.62.0 archive passed all eight handoff verifiers, 31 original-reference groups plus the additional Grouped reference, 1,436 tests with no skips, packaging and the complete portable-executable smoke. The authenticated imported-PZF refusal check passed. The downloaded archive matches the VM checksum. See [validation-062.json](validation-062.json) for the tested source and archive identity.

The original-PZF renderer requires Windows. Its Linux refusal is a platform limitation, not evidence of a passed imported-graph GUI test. Windows acceptance explicitly requires a real `438.pzf` fixture and a saved import-refusal result; a missing fixture cannot silently count as a pass.

## Remaining scope
