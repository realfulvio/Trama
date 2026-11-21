# Drawing-object context menu — 0.67.0

Right-click a native line, arrow, capped line, rectangle or ellipse on a calculated graph. The menu selects the object and offers its numerical editor, line/border color, thickness and style. Lines also offer ending direction, open/filled/capped design and ending size; rectangles/ellipses offer fill color, no fill and the existing fill patterns. Canonical values are used in either English or Italian.

The menu also duplicates an object with a fresh UUID, removes it, or changes native drawing order. Bring to front uses the above-data layer and the last position among native drawings; send to back uses the below-data layer and first position. These actions do not reorder text annotations or other graph artists. Duplicates initially retain the same geometry and appearance and can then be moved with the existing canvas tool.

## Transactions and compatibility

Changes validate the entire candidate before replacing drawing artists and committing. Choosing a current canonical value, cancelling the color picker or cancelling a numerical preview does not add shape history or dirty the project. Successful actions participate in graph-scoped Undo/Redo and preserve source data, calculations, axes and the canvas. The menu is disposed on a sheet/project change; stale callbacks and unavailable drawing contexts cannot edit a different graph. Pan/zoom, pending calculations and Inspector drafts retain their existing guards. Empty-space clicks do not create a drawing.

The existing shape schema is unchanged. The supported preset widths are 0.25, 0.5, 1, 1.5, 2, 3, 4, 6, 8 and 12 points; ending sizes are 6, 10, 14, 18, 24, 32 and 40 points. These are Trama presets. Use Format object for other supported numeric values. Line-ending controls are inactive when the line has no endings. Pattern color remains tied to the border color in the current schema. Native drawing clipboard transfer, separate pattern color, attached object text and proprietary object round trips remain further work. Imported drawings retain their existing workflow.

## Reference evidence


## Verification

Tests cover validated/no-op/invalid edits, UUID and object-limit safety, ordering, real translated menu choices, right-click selection and blocked contexts, source/canvas stability, color cancellation, graph undo and stale callbacks. The real-app smoke uses actual OS right-click input on Windows, invokes the real menu controls, opens/cancels the existing numerical editor, saves/reopens and recalculates after source edits/exclusion, and exports PNG/SVG/PDF. Full portable acceptance is required before publication and identified by the release notes and archive checksum.

