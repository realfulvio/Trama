# Draw and edit on the canvas — 0.64.0

On a calculated native graph, open **Graph shapes…** in the graph toolbar and choose **Select**, **Line**, **Arrow**, **Rectangle** or **Ellipse**. Drag inside the plot to create the object. A completed drag switches to Select; hold Shift when releasing to keep the drawing tool. Hold Ctrl while drawing or resizing a rectangle or ellipse to constrain its on-screen width and height equally.

In Select mode, drag an object's outline or filled interior to move it, or drag either square endpoint handle to resize it. An unfilled object's empty interior does not select it. Double-click a selected object or press Enter to open its numerical editor, including arrowheads, colors and patterns. Delete removes the selection. Arrow keys move it by one display pixel, or ten with Shift. Escape cancels a live drag. **Manage objects…** opens the existing list editor.

## Transactions and other tools

Drawing is opt-in. Choosing a drawing tool turns pan/zoom off and settles an Inspector draft using the existing Apply/Discard/Stay prompt. Opening the Inspector leaves drawing mode. A pan/zoom operation cannot also commit a shape. Leaving the graph, saving or exporting cancels an unfinished drag. Invalid or near-zero drags do not dirty the project. A pointer grab lasts only for the drag and is released on completion, cancellation, focus loss and page destruction.

The ordinary Undo/Redo buttons and Ctrl+Z/Ctrl+Y apply to shape edits while a graph with shape history is selected. Each graph has its own bounded history (up to 20 changes, normally no more than 512 KiB of snapshots; one newest transaction is retained if it alone exceeds that size). Undo changes only drawing objects, preserving unrelated graph style edits. History is in-session only and is cleared when reopening a project. Source-table undo remains separate. An unexpected external shape change invalidates stale history rather than overwriting that change.

## Coordinates and exports

New objects use plot fractions. Both endpoints must remain in [0, 1]; a Ctrl-constrained square that would exceed this area is rejected. Existing objects retain their saved coordinate system. Moving an object translates both endpoints in display space and transforms them back; on a logarithmic axis this preserves visual geometry rather than adding a constant to data coordinates. Existing data-coordinate objects continue to use the axis-domain rules and normal clipping.

Only committed canonical records are saved. Selection handles are screen overlays outside the figure's persistent artist tree, and are suppressed during saving. They do not appear in PNG, SVG, PDF or native layout exports. Drawing edits do not recalculate analyses, change source cells, data limits or legends, or recreate the graph canvas. Existing 0.63 recipes remain unchanged; the canvas introduces no new serialized shape keys.

## Reference basis and limits

This release edits the primary axes of calculated native graphs. Imported PZF/PZT drawings retain their existing import-specific editing workflow. Rounded rectangles, arcs, object rotation, additional end caps and editing drawings in a Prism file are still outside this implementation.

## Acceptance

Tests cover transaction cancellation (including an invalid release after a valid preview), Ctrl geometry, Shift reuse, log and inverted axes, hollow-object hit testing, movement/resizing/nudging/deletion, view/data stability, bounded/stale history, graph-scoped undo, pan/zoom exclusion, key binding restoration, callback cleanup and selection-free exports. The real-app smoke adds the existing numerical editor, source edit/exclusion and recalculation, reopening `.alab`, vector layout export and graph PNG/SVG/PDF. On Windows it requires an OS mouse drag through the visible Tk window and records that result separately from generated-event tests.

