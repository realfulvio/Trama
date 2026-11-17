# Heat map: colors and legends — 0.72

**Graphing → Heat map** (Matrix, Long numeric, Long categories) gains custom gradients, opacity, stored category colors and an editable color legend. Recipes written by 0.72 draw exactly as before; the new options are optional.

## Dialog sections

| Tab | Fields |
|---|---|
| **Colors** | *Color mapping*: **Palette** (the five palettes and *Color scale*, as before), **Single gradient** or **Double gradient**. *Minimum / Midpoint / Maximum color* (defaults `#2166ac`, `#f7f7f7`, `#b2182b`; Midpoint only for the double gradient). The existing limits, midpoint, *Missing color* and *Out-of-range color* are reused. *Color opacity* 0–1 (default 1). |
| **Categories** | *Category colors* for Long categories: **Edit category colors…** opens a table (category, swatch, color, Pick…). A blank color keeps the palette color. |
| **Legend** | *Show color legend*, *Color legend orientation* (Vertical / Horizontal, numeric), *Reverse color legend*, *Color legend title* (literal text), *Color legend interval* (blank = automatic) and *Color legend start* (only with an interval). |

Fields that do not apply are hidden, are not validated and are not written to the recipe. Graph settings opens on the colors; the Inspector of a heat map has a **Colors and legend…** button that opens the same dialog (an unapplied Inspector draft is applied or dropped first).

The category table scrolls when needed, keeping Apply and Cancel visible. Keyboard focus and validation errors reveal the corresponding row. The horizontal numeric color bar follows the actual map width, including square cells and window resizing.

## Rules

* Gradient channels (sRGB, no gamma) and the alpha of each source color are interpolated linearly. The double gradient interpolates Minimum→Midpoint and Midpoint→Maximum around the existing midpoint (low < midpoint < high). Values outside the limits take the extreme color, or *Out-of-range color* when set.
* *Color opacity* multiplies the alpha of every observation, out-of-range ones included. The missing-cell color keeps its own alpha. Opacity 0 hides the observations without removing them. The color bar uses the same norm and colormap, so it shows the same transparency.
* The gradient is a 2048-entry table: the end colors are exact; interpolation at the midpoint is within 1/2048 per channel.
* **Category colors** is a `{level text: color}` mapping saved in the recipe. `low`, `LOW`, `1` and `01` are different keys. Transposing, reversing, editing or excluding cells never reassigns a color; pairs for levels that are absent now are kept and return with the level. Unmapped levels keep the legacy palette color.
* Legend ticks: *start* (default the minimum, never outside the color limits) + n·*interval* up to the maximum. More than **200** ticks is refused on *Color legend interval* before anything is built. Reversing the legend flips the bar and its ticks only; categories reverse only the order of the entries. A hidden legend leaves no empty axis.
* The calculation, the tables and the CSV do not change with any of these options.

