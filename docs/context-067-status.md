# 0.67 validation and compatibility

## Verification scope

- Linux unit tests and complete native-app smoke cover the menu operations, preview cancellation, undo, stale callbacks and persistence. Windows source preflight additionally uses actual OS right-click input and captures the real popup.
- Full Windows acceptance runs eight handoff verifiers, the original-reference groups plus the extra Grouped fixture, the complete unit suite, build/package and full smoke of the extracted portable executable. It requires native pointer, capped-line, editor-page and context-menu evidence and an explicit refusal on a preserved imported PZF.
- An earlier Windows gate exposed a PDF dialog test-driver focus race. The unchanged test passed three isolated runs before the driver was made to wait for a visible dialog and settled focus. All original assertions remain; PDF product behavior was unchanged.
- Integer and float property values select the same numeric menu preset without rewriting saved records.
- The first portable smoke exposed a test-only import of the program entry module. The driver now patches the shared tkinter color chooser directly, so it also works in the frozen executable. A source smoke alone cannot detect this packaging issue.

The release notes identify the accepted source and archive checksum after the complete Windows portable gate succeeds. A previously built ZIP or a source-only result is insufficient evidence for publication. Further native clipboard transfer, separate pattern color, attached text and proprietary object round trips remain outside 0.67.

