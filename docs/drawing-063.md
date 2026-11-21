# Native arrowheads and patterned fills — 0.63.0

Lines can have a head at the start, the end or both ends. Choose open or filled heads and a size from 3 to 40 points. The default size is 10 points. No heads preserves the existing plain line. Rectangles and ellipses can use diagonal, crosshatch or dot patterns in the stroke color, with a transparent interior or a background fill. Stroke, opacity, clipping and object order continue to apply.

Open **Insert → Graph shapes…**, add or edit an object, and use the arrow or fill controls. In Italian these are **Punte della freccia**, **Stile delle punte**, **Dimensione punte (pt)** and **Motivo riempimento**. Disabled inputs are ignored; a size error keeps the dialog open and focuses that field. Preview changes the displayed drawing, Apply commits it, and Cancel restores the confirmed figure.

## Recipe and export compatibility

The mandatory 0.62 shape keys and their canonical values are unchanged. Optional `arrow_heads`, `arrow_style` and `arrow_size` belong to line records; optional `hatch` belongs to rectangles and ellipses. Opening and applying an unchanged old shape does not insert optional defaults or dirty the project. A project using these new options needs a compatible 0.63-or-newer reader.

Arrowheads have a point-based physical size, including after zoom and DPI changes. Patterns and heads are vector paths in SVG/PDF. Native layouts prefix their SVG IDs so repeated objects/patterns in different panels remain distinct. New decoration artists do not become data series or change data limits, legends, source data or analysis results. Calculated native graphs use these controls; preserved imported drawings retain their existing editing workflow.

## Reference evidence and limits

The drawing editor supports named point sizes, two arrowhead designs and three hatch patterns. End caps, additional arrow styles, rounded rectangles, arcs, rotation and direct mouse drawing remain further work.

## Verification

The engine tests cover strict optional-key scope, malformed values, unchanged legacy records, start/end/both open/filled arrows, transform correctness, physical-size invariance across zoom/DPI, transparent hatches, data-limit/series stability, project persistence and vector graph/layout exports with unique resolvable SVG IDs. Real-Tk tests exercise EN/IT choices, decimal commas, field errors and inactive controls. The real-app smoke adds preview/cancel/apply, every supported head direction/design, save/reopen, source edits/exclusions, PNG/SVG/PDF and two-panel native layouts.

