# Perpendicular line caps — 0.65.0

The numerical shape editor now offers **Perpendicular cap** alongside open and filled arrows in **Ending style**. Choose the start, the end or both ends of a line. **Ending size (pt)** is the nominal full cap length in points (3–40, default 10); the cap is centered on the saved endpoint and perpendicular to the displayed shaft. Its color, width, opacity and stroke pattern follow the line. This is a drawing decoration, separate from statistical error bars.

In Italian, the controls are **Terminali della linea**, **Stile dei terminali**, **Barra perpendicolare** and **Dimensione terminali (pt)**. Preview and Cancel are transactional; validation retains the dialog and focuses the incorrect field. A plain line can retain an inactive cap preference without drawing a cap. Rectangles and ellipses continue to reject line-ending settings.

Caps work with the 0.64 direct canvas editor: select, move, resize, nudge, delete and graph Undo/Redo. Their physical size remains fixed across zoom and DPI changes, including on logarithmic data axes. They remain vector paths in graph and native-layout SVG/PDF exports and preserve data limits, graph series, original observations and analysis results.

## Compatibility and evidence

The existing optional canonical `arrow_style` field gains `cap`; existing mandatory keys and open/filled arrow recipes are unchanged. A saved project using caps requires 0.65 or newer. Older readers may reject this new value; do not assume backwards reading compatibility. New drawing objects still follow the primary-axis and coordinate conventions in [the canvas guide](drawing-064.md).

Tests independently check cap center, nominal length and orthogonality for each direction, reversed endpoints, zoom, DPI and log axes. Further checks cover selection away from the shaft, canonical/translated editor values, inactive preferences, unchanged legacy records and project/vector exports. The real-app smoke covers validation focus, preview/cancel/apply, direct movement and undo/redo, save/reopen, source edit/exclusion, PNG/SVG/PDF and repeated object IDs in two native layout panels.
