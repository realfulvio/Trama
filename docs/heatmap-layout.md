# Heat map: cell gaps, vector geometry, and axis labels — 0.72

**Graphing → Heat map** adds a **Layout** tab next to **Graph options** with cell gaps and axis label placement options for Matrix, Long numeric, and Long categories heat maps. Existing recipes without layout keys (or with default values) keep the legacy `QuadMesh` rendering, tick placement, and single `Heat map data` sheet unchanged.

## Cell gaps
- **Row gap mode** / **Column gap mode**: `None` (default), `Every boundary`, or `Selected boundaries`.
- **Row gap size** / **Column gap size**: finite value from `0` to `2` in cell units along that axis (default `0.15`; decimal comma supported). Disabled under `None`.
- **Row gaps after** / **Column gaps after**: comma-separated 1-based positions from `1` to `n - 1` referring to displayed rows/columns *after* `Transpose`, `Reverse rows`, and `Reverse columns`. Active only under `Selected boundaries`.

When layout options are active, cells are rendered as a single aggregated vector `PolyCollection` so SVG and PDF exports preserve vector cell geometry, gaps, and literal text. Missing cells retain their `Missing color`, while gaps expose the axes background.

## Axis labels
- **Show row labels** / **Show column labels**: toggle axis labels (default on). Hiding an axis omits its ticks/labels and ignores its disabled controls.
- **Row label frequency** / **Column label frequency**: `Automatic` (legacy step `max(1, (n + 24) // 25)`) or `Every Nth` (`1..10000`).
- **Column label rotation**: `Legacy` (40°), `Horizontal` (0°), `Diagonal` (45°), or `Vertical` (90°).
- **Row label side**: `Left` or `Right`; **Column label side**: `Bottom` or `Top`.
- **Row label font size** / **Column label font size**: blank for default axis font, or `6..36` pt.

## Results & project integration
- `Heat map data` keeps its exact row/column order and values with no synthetic gap rows or columns.
- When any gap mode or axis label option differs from defaults, a descriptive `Heat map layout` sheet is added (`Display row`, `Display column`, `Row label`, `Column label`, `X left`, `X right`, `Y top`, `Y bottom`).
- If a worksheet edit reduces the number of rows/columns and invalidates a selected boundary, recalculation clears the stale plot and opens the recovery dialog focused on the offending field.

