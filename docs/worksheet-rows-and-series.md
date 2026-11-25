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

# Creating numeric series

Choose **Insert → Create numeric series…** (Italian: *Inserisci → Crea serie numerica…*) or right-click a numeric cell (or numeric/virtual column heading) to fill a single column with an arithmetic or geometric progression.

- Choose **Arithmetic** (first value + step, supporting negative steps such as `-0.25` / `-0,25`) or **Geometric** (first value × ratio, supporting fractional ratios such as `0.5` / `0,5` or `1/2`).
- A single-column multi-row selection proposes that length; a single cell proposes `10` terms; a column heading selection proposes the current table length.
- The dialog previews the target range, first and last terms using the active decimal separator, and the number of occupied cells to be replaced. Existing non-empty cells require explicit confirmation before inserting.
- Calculated columns, text/categorical columns, multi-column ranges, frozen/read-only sheets, oversize ranges, and non-finite or non-representable values are rejected before writing, leaving existing data, recalculation buffers, and Undo/Redo history untouched.
- Confirmed writes extend trailing rows and row identities atomically, record one Undo/Redo step, and trigger one recalculation pass for dependent recipes (such as XY series graphs).

