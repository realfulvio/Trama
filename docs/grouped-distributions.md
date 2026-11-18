# Grouped distribution plot (box and violin cells)

**Graphing → Grouped distribution plot** («Distribuzioni raggruppate») draws one numeric response from a long worksheet, one row per observation: a category on the X axis and, optionally, a second factor that places one box or violin per series inside each category. Example: *Signal* by *Visit*, split by *Treatment*. The graph stays linked to the worksheet and is recalculated after every edit or exclusion. **Box / violin plot** is unchanged and keeps its recipes, in both input modes.

## Fields

| Field | Meaning |
|---|---|
| Response | Numeric column. Text or infinite values are an error on this field. |
| Category | Column of the X axis. A different column from Response. |
| Split by | Optional second factor, different from Response and Category. Empty = one box or violin per category, centered. |
| Style | **Box** (default) or **Violin**. |
| Whiskers, Show mean, Overlay observations, Point placement, Bandwidth multiplier, Median line, Quartile lines | The same keys, choices and defaults as Box / violin plot. Fields that do not apply to the chosen style are hidden and are not written to the recipe. |

Column names and category text are literal: a `$` in a title, a column name or a level never starts math notation, and levels are never sorted or translated. Two roles on the same column are refused on the later field, and the dialog stays open on it.

## Cells, order and positions

A *cell* is one category × series combination. A row with a missing or excluded value in Response, Category or (when it is used) Split by is ignored, and an ignored row does not introduce a level. Categories and series appear in the order of their first complete observation. Levels keep their type when the table does: `1`, `1.0`, `"1"` and `True` are four different levels.

For category *j* and series *i* (both counted from 0) among *s* series, the center of the cell is

**Position = 1 + j + 0.8 · (i − (s − 1) / 2) / s**

Without Split by, *s* = 1 and the box is centered at 1 + *j*. A combination without observations keeps its slot (N = 0 in the sheet) and draws nothing: no mark and no legend entry. Box and violin widths and the spread of the points are the ones of Box / violin plot divided by *s*, so the cells of one category share its slot. Up to 40 cells (categories × series) are drawn; the existing limits on observations and on the density estimate also apply.

Quartiles, whiskers, density and the fallbacks for N < 4, N = 1, N = 2 and constant values are those of Box / violin plot (rank (N + 1) p with linear interpolation, saturated at the extremes).

## Sheets

* **Distribution cells**: one row per cell in category then series order: Category, Series, N, Position, Mean, Median, Minimum, Q1, Q3, Maximum, then the whisker columns (Box) or Bandwidth (Violin) and a Note. Statistics are empty for N = 0, and Q1 and Q3 are empty for N < 4.
* **Distribution observations**: one row per finite observation in sheet order: Source row (counted from 1), Category, Series, Value, Position of the center of its slot, and Display (Outside whiskers, Overlay or Not drawn). The sheet includes the observations that the Overlay choice does not draw.
* **Distribution density** (Violin only): Category, Series, Position, Value, Density, Half-width.
* **Settings**: roles, rows used and omitted, level order, the position rule, empty cells, colors and the rules of the chosen style.

Sheets keep their English names in every language. Like every result sheet, the CSV export of a result writes the sheet index as its first column.

## Colors, Inspector and legend

By default every series has one color, the same in every category; without Split by the color is per category. In the Graph Inspector each cell is a selectable element named *Category · Series*, with color and visibility. Its style key is `box:` or `violin:` followed by `cell:<category>:<series>`, built from percent-encoded, type-preserving tokens (for example `str:Week $2$`). The key does not depend on the order of the sheet: after a recalculation, a reorder or the removal of another cell, the color and the selection stay with the same data.

With Split by the legend has one entry per series that still has a visible cell, titled with the Split by column; its symbol follows the first visible cell of that series, also after a color or visibility change in the Inspector. Legend entries use stable `group:<type>:<series>` keys for Legend formatting.

## Compatibility

The graph is native: vector in SVG and PDF, in layouts next to other graphs, saved in `.alab` as a recipe (canonical English keys) and recalculated on opening. The X axis is categorical and the Y axis numeric for axis formatting. Pairwise comparisons and compact letters are not offered on this graph.
