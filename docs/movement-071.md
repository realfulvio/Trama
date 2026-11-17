# Constrained drawing movement — 0.70.0

For a selected native graph drawing, drag its body with Ctrl to move horizontally, or with Shift to move vertically. Direction constraints operate in display coordinates, including logarithmic and reversed axes. Holding both modifiers leaves movement unconstrained. A pointer displacement entirely perpendicular to the allowed direction changes neither the confirmed record nor history. The ignored pointer component may leave the plot without invalidating a valid projected move.

Arrow keys move a selected drawing by one display pixel; Ctrl+arrow moves it by ten. Existing Shift+arrow remains a ten-pixel compatibility shortcut. Keyboard bindings belong to the drawing canvas while its drawing tools are active and restore pre-existing bindings when the tools stop. Creation and resizing retain their existing Ctrl square/circle behavior, and Shift still retains the creation tool.

These controls reuse the existing transaction, Undo/Redo, preview cancellation, domain guards, project persistence and vector-export paths. No persistent property or source-data transformation is added.

Acceptance requires core geometry and real Tk binding tests, native Windows modifier/mouse input, project reopening and export. Development source checks do not establish portable-release acceptance.

