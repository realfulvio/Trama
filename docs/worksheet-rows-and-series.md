# Moving and resizing worksheet rows

In Classica Qt, you can reorder contiguous data rows and adjust individual row heights directly from the numbered vertical header.

## Moving rows

- Drag a row or a contiguous selected block from the numbered vertical header to the target position; an insertion line shows where the rows will land.
- You can also use **Edit → Move up** (`Alt+Up`, Italian: *Modifica → Sposta su*) and **Edit → Move down** (`Alt+Down`, Italian: *Modifica → Sposta giù*), or right-click the numbered row header.
- Each move is a single atomic project edit with Undo/Redo (`Ctrl+Z` / `Ctrl+Y`) and triggers one recalculation pass for dependent analyses and formulas. The selection follows the moved block.
- Row titles, cell exclusions, cell backgrounds, custom row heights and stable row identities (`point_row_spans`) follow each original row across moves, undo/redo, and `.alab` save/reopen, so formatted duplicate observations in graphs keep their exact identity.
- Reordering is disabled on virtual trailing rows, frozen or read-only sheets, and fixed imported views.

## Row heights

- Drag the bottom border between two numbered row headers to resize a row (`18`–`480` px at 100% zoom).
- Custom heights are presentation-only (zero recalculations), scale with **View → Zoom**, follow their row when rows are moved, inserted or deleted, and are saved per worksheet in `.alab` (`row_heights`).
- Use **Reset height** (`Alt+0`, Italian: *Ripristina altezza*) from the vertical header context menu or **Edit** menu to restore the automatic height.
