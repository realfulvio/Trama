# Sorting worksheet rows

In Classica Qt, you can sort all rows of a data sheet by any non-calculated source column while carrying every row attribute along with its original observations.

## Sorting rows

- Choose **Edit → Sort rows…** (Italian: *Modifica → Ordina righe…*) or right-click any source column header and choose **Sort rows…** to open the compact sort dialog pre-selected on that column.
- Use **Edit → Reverse row order** (*Modifica → Inverti ordine delle righe*) to reverse the whole worksheet. From the row header menu, **Move rows to top** and **Move rows to bottom** (*Sposta righe in cima* and *Sposta righe in fondo*) move the selected block. The selection, row formatting and exclusions follow the observations. Undo restores the previous order.
- When the worksheet defines a **Row title** or **X** source column, **Edit → Sort by row title** (*Ordina per titolo di riga*) and **Edit → Sort by X** (*Ordina per X*) provide direct ascending quick sorts.
- The dialog states the worksheet scope (whole worksheet and row count) before choosing the **Sort by** source column and **Direction** (**Ascending** or **Descending**).

## Sorting rules and metadata preservation

- **Stability**: equal values retain their original relative order in both Ascending and Descending modes.
- **Missing values**: blank / `NA` cells always stay last in both Ascending and Descending modes.
- **Unicode text**: text columns and row titles use NFC Unicode case-insensitive (`casefold`) comparison while preserving each cell's original characters and casing.
- **Excluded cells**: excluded cells keep their exclusion flag and stored value and sort by their stored value.
- **Calculated columns excluded**: formula columns are excluded from sort keys because their values can depend on row order; positional formulas re-evaluate cleanly after the sort.
- **Metadata & links**: cell exclusions, custom row heights, cell backgrounds, font/text styles (`TextStyles`), stable point identities (`point_row_spans`), variable types, recipes, columns, and linked table references (`linked_tables`) follow each moved row cleanly.
- **Atomicity & guards**: each sort is a single atomic operation with one Undo/Redo step (`Ctrl+Z` / `Ctrl+Y`) and one recalculation pass for dependents. An identity permutation is a no-op. Frozen sheets, archived/read-only views, fixed legacy table formats, and stale sheets modified while the dialog was open are blocked before writing.
- **Cursor & selection**: after sorting, the active cell follows its moved row; a contiguous selection stays selected when those rows remain contiguous and avoids spanning unrelated rows otherwise.
