# Copy and paste native drawings — 0.68.0

Select a native line, arrow, capped line, rectangle or ellipse on a calculated graph. Right-click it and choose **Copy drawing** or **Cut drawing**. On another native graph, use **Graph shapes… → Paste drawing**. The workspace ribbon's Copy/Paste buttons also act on the selected native drawing when a graph is open. Worksheet and Info-sheet cell commands retain their existing behavior.

With a drawing tool active and the graph canvas focused, Ctrl+C, Ctrl+X and Ctrl+V perform the same drawing actions. Stopping drawing restores the canvas's previous key bindings; these shortcuts do not override Entry or table cell editing. Paste can be used without selecting an existing drawing.

## Format and position

A pasted object keeps its kind, coordinate units, geometry, colors, line thickness/style, opacity, layer, endings and fill pattern. It receives a new UUID on every paste and can be moved with the existing select tool. Plot-fraction coordinates use the destination plot's fractions; data coordinates retain their original numeric values. Paste rejects a drawing outside the destination logarithmic or probability-axis domain rather than silently omitting it. The per-graph limit remains 100 drawings.

Copy leaves the project and graph history unchanged. Cut deletes the original only after the system clipboard accepts the validated drawing. Cut and Paste create graph-scoped Undo/Redo entries, preserve other style settings, and do not recalculate or change the observations. Separate graphs have separate histories. Saving/reopening or recalculating the source retains pasted drawings, including vector figure and native-layout exports.

## Clipboard compatibility

The system Unicode text clipboard contains an independent, versioned `TramaStat/native-drawing` JSON envelope, bounded to 65,536 characters. Only one canonical drawing is accepted. Unknown fields/versions, duplicate JSON keys, nonfinite numbers and malformed records are rejected; text is never executed. Ordinary table text is rejected by Paste drawing. The `.alab` drawing schema is unchanged and absent optional properties remain absent.

This protocol supports transfer between compatible TramaStat windows and projects. It does not implement the proprietary drawing clipboards, attached object text, multiple-object transfer or drawing transfer from preserved imported binary graphs.

## Reference and validation

Tests cover strict decoding and limits, new identities, transaction failure, view/Inspector/pan/pending guards, real menu controls and local keyboard bindings. The real-app smoke exercises system clipboard reads and writes through an independent Windows Forms process, actual Windows canvas shortcuts, cross-graph/project transfer, Undo/Redo, project/source round trips and vector graph/layout SVG/PDF exports. The release notes and archive checksum identify completed Windows portable acceptance.

