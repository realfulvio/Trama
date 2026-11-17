# Native drawing arrangement — 0.70.0

Choose Arrange → Arrange drawing objects… or the same command in the Graph shapes menu on a calculated native graph. Select two or more objects in the list (Ctrl/Shift selects several) and choose horizontal and vertical alignment. Equal spacing requires at least three selected objects and enough room for nonnegative gaps. Preview changes the visible figure only. Cancel restores confirmed geometry; Apply records one graph-local Undo/Redo transaction.

Alignment uses the enclosing selected endpoint rectangle in the current primary-axis display coordinates. Distribution preserves its outer bounds and equalizes edge gaps. Pen widths, caps and arrowhead extents are excluded from these numeric bounds. Original coordinate units, IDs, style, unselected records and observations are retained; original shapes anchored to data on log axes can consequently change their data-coordinate span when translated in display space. Invalid/overflowed/domain-violating coordinates are rejected atomically. Plot-fraction rounding is normalized only at floating-point boundary noise.

This increment covers native lines, rectangles and ellipses selected from an explicit list. Text annotations, layout panels, direct canvas multi-selection, automatic snapping and proprietary object round trips are outside its scope. No new persistent shape property is introduced; prior compatible readers can display the resulting coordinates.

Hand-computed geometry fixtures and real EN/IT modal/App tests cover alignment, spacing, mixed units, reversed/log axes, no-ops, field focus, cancellation and history. Release acceptance still requires complete Linux checks and the Windows portable gate; this development guide alone does not establish a published 0.70 release.

