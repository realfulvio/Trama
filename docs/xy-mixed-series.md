# Mixed XY series: points, lines, steps and bars

`XY series` draws every Y column as `Points`, `Line`, `Line and points`, `Step` or `Bars` on one numeric X axis,
each on the left or the right Y axis already chosen for it. The first three styles draw exactly as before.

## Recipe

- `Series style` stores the canonical values `Step` and `Bars` next to the existing ones. Older recipes need no change.
- `Bar cluster width` (optional) is the total width of a bar cluster in X units. Missing or blank means Auto. The Format
  Graph field accepts a decimal comma in the Italian interface and only appears while at least one series is drawn as
  bars. A saved width stays in the recipe, unused, when no series is drawn as bars any more.

## Geometry

- **Step** holds each value until the next X of the sheet (`steps-post`), in sheet order, and breaks on every excluded,
  missing or out-of-domain position, exactly like a line.
- **Bars** draw one rectangle from Y = 0 to each valid value on the series' own axis, zero and negative values
  included. Nothing is summed or stacked; a missing X or Y draws no rectangle.
- A position is a virtual cluster with one slot per Bars series in `Y columns` order, across both axes. With `m` bar
  series and cluster width `W`, slots are `W/m` wide and centred at `X + W × ((i + 0.5)/m − 0.5)`. A slot keeps its
  place when the value is missing or the series is hidden.
- Auto width is 0.8 times the smallest positive step between the distinct valid X values of all bar series, or
  0.8 X units when there is a single position.
- `Series values` is unchanged: original X, Y, Y column and source row for every drawable point. Bar centres are
  geometry only.

## Validation

| Problem | Field |
| --- | --- |
| A bar series repeats an X among its valid points | `Y columns`; Format Graph selects that series and its draw style |
| A width that is not finite and positive, or rectangles that would collapse or overflow | `Bar cluster width` |
| Bars on a logarithmic right Y axis | `Right scale` |
| Bars on a logarithmic or probability left Y axis | The Y scale control (`Y scale` in the engine) |
| Bars with a non-linear X axis | The X scale control (`X scale`) |

The same rules run from the analysis dialog, Change parameters (saved styles are taken into account), Format Graph
and the Inspector. Engine messages keep their English text and are translated with the `xy.error.*` keys of
`analisi/i18n.py`. A recalculation that hits a repeated X after an edit follows the existing XY recovery: the graph
waits for a fix and the status bar names the problem.

## Style and editors

- The series key stays `xy:1:<column>` whatever the draw style or axis, so saved colors and labels follow a series
  from Line to Bars and back.
- Bars accept color, label and visibility. Step accepts the line controls (color, label, line style, width) and
  visibility. Marker and line fields are disabled for bars and keep their saved values for the other styles.
- `visible` is a new series field for XY graphs. It is active for Step and Bars; for the other styles it stays saved
  and inactive, so their set of active fields is unchanged.
- The legend keeps Y-column order across both axes and the literal titles and labels. Hidden series and series with
  nothing to draw are left out.
- Format Graph and the Inspector preview changes; Cancel restores the confirmed style and Apply confirms it.

## Vector output

Each rectangle has a unique gid `xybar:<column>:<source row>` (`<source row>@<position>` when the sheet index
repeats), kept as a group id in SVG. Bars and steps stay vector paths in SVG, PDF and native layouts.

## Integration notes

Changes are local to:

- `analisi/xy_series.py`: `STEP`, `BARS`, `BAR_WIDTH`, `RECIPE_KEYS`, `parse_bar_width`, `bar_layout` (called by
  `check_xy_options` and `xy_series`) and the Bars and Step branches of the renderer.
- `analisi/presentation.py`: `xy_artists`, `xy_legend_handles`, `xy_draw_kind`, active fields for Step and Bars,
  defaults and application of bar styles, `_check_xy_bar_scales` in `validate_graph_style`.
- `analisi/graph_legend.py`: legend matching reads the XY artists through `xy_artists`.
- `analisi/graph_dialog.py`: Show series check box, Step and Bars choices, Bar cluster width field, error focus.
- `analisi/graph_inspector.py`: check boxes follow the active fields.
- `analisi/i18n.py`: `graph.series.*`, `graph.draw.*`, `graph.error.*` entries and one `xy.error.*` block.
- `tramastat.py`: the analysis dialog checks saved styles and translates `xy.error.*`; `submit_edit` keeps
  `RECIPE_KEYS`; the `xy-mixed` smoke hook.

Axis breaks (open separately) refuse graphs with bars through their existing "drawing elements" rule and draw the
graph without breaks; Step lines are repeated on every panel with their draw style.

## Verification

```bash
python -m unittest tests.test_xy_mixed_series tests.test_xy_mixed_editors -v
TRAMASTAT_SMOKE_ONLY=xy-mixed TRAMASTAT_SMOKE_SCREENSHOTS=1 python tramastat.py --smoke /tmp/trama-xy-mixed
```

The smoke writes `xy-mixed/report.json`, exports and window captures. The 1600 × 1000 window step runs when the
screen is at least 1680 × 1050.
